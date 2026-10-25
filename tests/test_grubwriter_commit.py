#!/usr/bin/env python3
"""
Hermetic tests for the GrubWriter commit / rollback path (audit item C2).

These tests never touch /etc/default/grub or the real user/system state
directories: UserConfigDir is replaced by a small in-memory implementation and
the root check is patched to succeed.

Covered behaviour:
1. NUL bytes are rejected before anything is installed.
2. A candidate that fails ``sh -n`` is rejected and the target is untouched.
3. A valid candidate replaces the target atomically and leaves a rollback copy.
4. ``grub-script-check`` is advisory: it rejects valid shell content (e.g.
   Ubuntu's backtick ``GRUB_DISTRIBUTOR``) but does not block the commit.
5. A failed GRUB update rolls the defaults file back and re-runs the update.
6. A failed rollback and a failed post-rollback update are reported clearly.
"""

import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Add parent directory to path to import grub_wiz
sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz.GrubWriter import GrubWriter  # noqa: E402


OLD_CONFIG = b'GRUB_TIMEOUT=10\nGRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n'
NEW_CONFIG = b'GRUB_TIMEOUT=3\nGRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n'


class FakeUserConfig:
    """Minimal UserConfigDir stand-in with fault injection."""

    def __init__(self, system_state_dir: Path, fail_on_calls=()):
        self.system_state_dir = system_state_dir
        self.fail_on_calls = set(fail_on_calls)
        self.writes = []

    def safe_read_bytes(self, path, max_bytes=1024 * 1024):
        path = Path(path)
        if path.is_symlink():
            raise OSError(f"symlink rejected: {path}")
        return path.read_bytes()

    def atomic_root_write(self, path, data, mode=0o644):
        path = Path(path)
        self.writes.append(path)
        if len(self.writes) in self.fail_on_calls:
            raise OSError(f"injected write failure #{len(self.writes)}: {path}")
        payload = data.encode('utf-8') if isinstance(data, str) else data
        tmp = path.with_name(f'.{path.name}.tmp')
        tmp.write_bytes(payload)
        os.chmod(tmp, mode)
        os.replace(tmp, path)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Build a writer wired to a temp target + fake state directory."""
    monkeypatch.setattr(os, 'geteuid', lambda: 0)

    target = tmp_path / 'grub'
    target.write_bytes(OLD_CONFIG)
    state_dir = tmp_path / 'state'
    state_dir.mkdir()

    distro_vars = SimpleNamespace(
        etc_grub=str(target),
        update_grub='/usr/sbin/update-grub',
        grub_cfg='/boot/grub/grub.cfg',
        update_initramfs=None,
        initramfs_triggers={},
    )
    user_config = FakeUserConfig(state_dir)
    writer = GrubWriter(distro_vars, user_config=user_config)
    return SimpleNamespace(writer=writer, target=target,
                           state_dir=state_dir, user_config=user_config)


def stage(tmp_path: Path, content: bytes) -> Path:
    candidate = tmp_path / 'grub.new'
    candidate.write_bytes(content)
    return candidate


def test_nul_bytes_rejected(env, tmp_path, capsys):
    candidate = stage(tmp_path, NEW_CONFIG + b'\x00')

    ok, msg = env.writer.commit_validated_grub_config(candidate)

    assert not ok
    assert 'NUL' in msg
    assert env.target.read_bytes() == OLD_CONFIG
    assert not candidate.exists(), 'staging file must be removed'
    assert env.user_config.writes == [], 'nothing should be written'


def test_shell_syntax_error_rejected(env, tmp_path):
    # Unterminated double quote: `sh -n` must reject this.
    candidate = stage(tmp_path, b'GRUB_CMDLINE_LINUX="unterminated\n')

    ok, msg = env.writer.commit_validated_grub_config(candidate)

    assert not ok
    assert 'shell syntax check failed' in msg
    assert env.target.read_bytes() == OLD_CONFIG
    assert not candidate.exists()


def test_commit_replaces_target_and_keeps_rollback_copy(env, tmp_path):
    candidate = stage(tmp_path, NEW_CONFIG)

    ok, msg = env.writer.commit_validated_grub_config(candidate)

    assert ok, msg
    assert env.target.read_bytes() == NEW_CONFIG
    assert not candidate.exists()

    rollback_copy = env.state_dir / 'last-known-good.grub'
    assert rollback_copy.read_bytes() == OLD_CONFIG


def test_grub_script_check_is_only_advisory(env, tmp_path, capsys):
    if not shutil.which('grub-script-check'):
        pytest.skip('grub-script-check not installed')

    # Valid shell, but `grub-script-check` rejects backticks (as it does for
    # stock Ubuntu GRUB_DISTRIBUTOR).  The commit must still succeed.
    content = (b'GRUB_DISTRIBUTOR=`lsb_release -i -s 2> /dev/null || echo Debian`\n'
               b'GRUB_TIMEOUT=3\n')
    candidate = stage(tmp_path, content)

    ok, msg = env.writer.commit_validated_grub_config(candidate)

    captured = capsys.readouterr()
    assert ok, msg
    assert env.target.read_bytes() == content
    assert 'grub-script-check rejected the candidate (advisory' in captured.err


def test_failed_update_rolls_back_and_re_runs(env, tmp_path):
    candidate = stage(tmp_path, NEW_CONFIG)
    results = [(False, 'grub-mkconfig exited 1'), (True, 'OK')]
    calls = []

    def runner():
        calls.append('run')
        return results.pop(0)

    ok, msg = env.writer.commit_and_update(candidate, update_runner=runner)

    assert not ok
    assert len(calls) == 2, 'update must be re-run after rollback'
    assert env.target.read_bytes() == OLD_CONFIG, 'previous file must be restored'
    assert 'grub-mkconfig exited 1' in msg
    assert 'Rolled back and re-ran the GRUB update' in msg


def test_failed_rollback_is_reported_as_critical(env, tmp_path, monkeypatch):
    candidate = stage(tmp_path, NEW_CONFIG)
    # 1st write: rollback copy; 2nd: target; 3rd: the rollback itself.
    env.user_config.fail_on_calls = {3}

    def runner():
        return False, 'grub-mkconfig exited 1'

    ok, msg = env.writer.commit_and_update(candidate, update_runner=runner)

    assert not ok
    assert 'CRITICAL' in msg
    assert 'Do not reboot' in msg
    assert env.target.read_bytes() == NEW_CONFIG, 'rollback failed, file stays changed'


def test_failed_re_update_after_rollback_is_reported(env, tmp_path):
    candidate = stage(tmp_path, NEW_CONFIG)
    results = [(False, 'first failure'), (False, 'second failure')]

    def runner():
        return results.pop(0)

    ok, msg = env.writer.commit_and_update(candidate, update_runner=runner)

    assert not ok
    assert env.target.read_bytes() == OLD_CONFIG
    assert 'second failure' in msg
    assert 'may still reflect the rejected change' in msg


def test_no_update_is_run_when_commit_fails(env, tmp_path):
    candidate = stage(tmp_path, NEW_CONFIG + b'\x00')
    calls = []

    def runner():
        calls.append('run')
        return True, 'OK'

    ok, msg = env.writer.commit_and_update(candidate, update_runner=runner)

    assert not ok
    assert 'NUL' in msg
    assert calls == []
    assert env.target.read_bytes() == OLD_CONFIG


def test_rollback_removes_file_that_did_not_exist(env, tmp_path):
    env.target.unlink()
    candidate = stage(tmp_path, NEW_CONFIG)

    ok, msg = env.writer.commit_and_update(
        candidate, update_runner=lambda: (True, 'OK'))
    assert ok, msg
    assert env.target.read_bytes() == NEW_CONFIG

    rb_ok, rb_msg = env.writer.rollback_last_commit()
    assert rb_ok, rb_msg
    assert not env.target.exists(), 'target did not exist before the commit'


def test_rollback_without_commit_is_refused(env):
    ok, msg = env.writer.rollback_last_commit()
    assert not ok
    assert 'no committed change' in msg
