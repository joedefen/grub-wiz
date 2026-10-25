"""Direct coverage for ``UserConfigDir`` (audit M13).

The shared ``tests/conftest.py`` fixture replaces the singleton that the
application modules use.  These tests exercise the real class instead: its
directory setup, singleton semantics, user detection, and the symlink-safe
read/write primitives that the C1 remediation depends on.  Every path is
redirected below ``tmp_path`` so nothing touches ``$HOME``, ``/var/lib`` or
``/run``.
"""

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import grub_wiz.UserConfigDir as ucd

# Captured before the autouse conftest fixture replaces the class attribute.
_REAL_GET_SINGLETON = ucd.UserConfigDir.get_singleton


@pytest.fixture
def real_config(monkeypatch, tmp_path):
    """Construct a real ``UserConfigDir`` with all state rooted at tmp_path."""
    monkeypatch.setattr(ucd, 'SYSTEM_STATE_ROOT', tmp_path / 'var-lib')
    monkeypatch.setattr(ucd, 'RUN_ROOT', tmp_path / 'run-root')

    def fake_detect_user(self):
        self.home = tmp_path / 'home'
        self.uid = os.getuid()
        self.gid = os.getgid()

    monkeypatch.setattr(ucd.UserConfigDir, '_detect_user', fake_detect_user)
    # The real singleton must start clean for each test.
    ucd.UserConfigDir.singleton = None
    ucd.UserConfigDir._instance = None
    config = ucd.UserConfigDir('grub-wiz')
    yield config
    ucd.UserConfigDir.singleton = None
    ucd.UserConfigDir._instance = None


def test_creates_private_user_state_directory(real_config):
    """The user state directory is created 0700 under the detected home."""
    config = real_config

    assert config.user_state_dir == config.home / '.config' / 'grub-wiz'
    assert config.user_state_dir.is_dir()
    assert stat.S_IMODE(config.user_state_dir.stat().st_mode) == 0o700
    # System and run state are redirected, never the real /var/lib or /run.
    assert config.system_state_dir.is_dir()
    assert config.run_dir.is_dir()
    assert config.system_state_dir.is_relative_to(config.home.parent)
    assert config.run_dir.is_relative_to(config.home.parent)


def test_get_singleton_reuses_the_instance(real_config):
    """The real singleton accessor returns the already-constructed instance."""
    assert _REAL_GET_SINGLETON() is real_config
    assert _REAL_GET_SINGLETON('grub-wiz') is real_config


def test_direct_second_construction_is_rejected(real_config):
    """Constructing a second instance would silently drop state; it raises."""
    del real_config

    with pytest.raises(RuntimeError, match='get_singleton'):
        ucd.UserConfigDir('grub-wiz')


def test_detect_user_prefers_sudo_ids(monkeypatch):
    """SUDO_UID/SUDO_GID decide the owner; getlogin() is not consulted (M6)."""
    config = object.__new__(ucd.UserConfigDir)
    monkeypatch.setattr(ucd.os, 'geteuid', lambda: 0)
    monkeypatch.setenv('SUDO_UID', '1001')
    monkeypatch.setenv('SUDO_GID', '1002')
    entry = SimpleNamespace(pw_uid=1001, pw_gid=100, pw_dir='/home/alice')
    monkeypatch.setattr(ucd.pwd, 'getpwuid', lambda uid: entry)

    def fail_getlogin():
        raise AssertionError('os.getlogin() must not be used under sudo')

    monkeypatch.setattr(ucd.os, 'getlogin', fail_getlogin)

    config._detect_user()

    assert config.home == Path('/home/alice')
    assert config.uid == 1001
    # The recorded gid wins over the login gid.
    assert config.gid == 1002


def test_atomic_user_write_replaces_symlink_without_touching_target(
        real_config, tmp_path):
    """A pre-planted symlink is replaced, not followed (C1)."""
    protected = tmp_path / 'protected'
    protected.write_text('keep me')
    link = real_config.user_state_dir / 'warn-db.yaml'
    link.symlink_to(protected)

    real_config.atomic_user_write(link, 'new state', mode=0o600)

    assert not link.is_symlink()
    assert link.read_text() == 'new state'
    assert protected.read_text() == 'keep me'
    assert stat.S_IMODE(link.stat().st_mode) == 0o600


def test_atomic_user_write_rejects_paths_outside_user_state(
        real_config, tmp_path):
    """Only the user state directory may receive unprefixed user writes."""
    with pytest.raises(ValueError, match='outside'):
        real_config.atomic_user_write(tmp_path / 'elsewhere', b'nope')


def test_safe_read_bytes_rejects_symlinks(real_config, tmp_path):
    """Opening with O_NOFOLLOW refuses a user-planted link."""
    secret = tmp_path / 'secret'
    secret.write_bytes(b'do not read')
    link = real_config.user_state_dir / 'link'
    link.symlink_to(secret)

    with pytest.raises(OSError):
        real_config.safe_read_bytes(link)


def test_safe_read_bytes_rejects_oversized_files(real_config):
    """The size bound keeps a corrupted state file from exhausting memory."""
    path = real_config.user_state_dir / 'big'
    path.write_bytes(b'x' * 32)

    with pytest.raises(OSError, match='too large'):
        real_config.safe_read_bytes(path, max_bytes=16)


def test_safe_read_text_round_trips_utf8(real_config):
    path = real_config.user_state_dir / 'text'
    path.write_text('héllo wörld')

    assert real_config.safe_read_text(path) == 'héllo wörld'


def test_ensure_dir_rejects_a_symlinked_directory(real_config, tmp_path):
    """A directory entry that is a symlink must be refused, not followed."""
    target = tmp_path / 'real-dir'
    target.mkdir()
    link = tmp_path / 'link-dir'
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(RuntimeError, match='symlink'):
        real_config._ensure_dir(
            link, mode=0o700, uid=real_config.uid, gid=real_config.gid,
            label='test', must_be_root_owned=False)


def test_give_to_user_sets_mode_without_following_links(real_config):
    path = real_config.user_state_dir / 'file'
    path.write_text('x')
    os.chmod(path, 0o644)

    real_config.give_to_user(path, mode=0o600)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_staging_path_is_unique_and_beside_the_target(real_config, tmp_path):
    target = tmp_path / 'grub'

    first = real_config.staging_path(target)
    second = real_config.staging_path(target)

    assert first.parent == target.parent
    assert first.name.startswith('.grub.grub-wiz-')
    assert first != second
