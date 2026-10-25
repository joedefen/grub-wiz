"""Command construction and failure handling in ``GrubWriter``.

The existing commit/rollback tests exercise the staged-write path with a fake
update runner.  These tests cover what that runner and the initramfs helpers
actually do: argv selection per distro, space checks, advisory validation, and
the commit error branches.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import grub_wiz.GrubWriter as gw_mod
from grub_wiz.GrubWriter import GrubWriter


OLD = b'GRUB_TIMEOUT=10\n'
NEW = b'GRUB_TIMEOUT=3\n'


class FakeUserConfig:
    """State-directory stand-in with fault injection on writes."""

    def __init__(self, state_dir, fail_on_calls=()):
        self.system_state_dir = Path(state_dir)
        self.fail_on_calls = set(fail_on_calls)
        self.writes = []

    def safe_read_bytes(self, path, max_bytes=1024 * 1024):
        del max_bytes
        return Path(path).read_bytes()

    def atomic_root_write(self, path, data, mode=0o644):
        path = Path(path)
        self.writes.append(path)
        if len(self.writes) in self.fail_on_calls:
            raise OSError(f'injected write failure #{len(self.writes)}')
        payload = data.encode('utf-8') if isinstance(data, str) else data
        path.write_bytes(payload)
        os.chmod(path, mode)


def make_writer(tmp_path, update_grub='/usr/sbin/update-grub',
                grub_cfg='/boot/grub/grub.cfg',
                update_initramfs=None, triggers=None):
    target = tmp_path / 'grub'
    target.write_bytes(OLD)
    state = tmp_path / 'state'
    state.mkdir(exist_ok=True)
    distro_vars = SimpleNamespace(
        etc_grub=str(target),
        update_grub=update_grub,
        grub_cfg=grub_cfg,
        update_initramfs=update_initramfs,
        initramfs_triggers=triggers or {},
    )
    user_config = FakeUserConfig(state)
    return GrubWriter(distro_vars, user_config=user_config), target, user_config


# --- run_grub_update -------------------------------------------------------

def test_run_grub_update_requires_root(tmp_path, monkeypatch):
    writer, _target, _u = make_writer(tmp_path)
    monkeypatch.setattr(gw_mod.os, 'geteuid', lambda: 1000)

    ok, msg = writer.run_grub_update()

    assert not ok
    assert 'root required' in msg


def test_run_grub_update_requires_a_command(tmp_path, monkeypatch):
    writer, _target, _u = make_writer(tmp_path, update_grub=None)
    monkeypatch.setattr(gw_mod.os, 'geteuid', lambda: 0)

    ok, msg = writer.run_grub_update()

    assert not ok
    assert 'cannot find GRUB update cmd' in msg


def test_update_grub_runs_the_plain_command(tmp_path, monkeypatch):
    writer, _target, _u = make_writer(tmp_path)
    monkeypatch.setattr(gw_mod.os, 'geteuid', lambda: 0)
    calls = []

    def fake_run(argv, check=False):
        calls.append((argv, check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gw_mod.subprocess, 'run', fake_run)

    ok, msg = writer.run_grub_update()

    assert ok and msg == 'OK'
    assert calls == [(['/usr/sbin/update-grub'], False)]


def test_mkconfig_gets_output_flag_and_target(tmp_path, monkeypatch):
    writer, _target, _u = make_writer(
        tmp_path, update_grub='/usr/sbin/grub-mkconfig')
    monkeypatch.setattr(gw_mod.os, 'geteuid', lambda: 0)
    calls = []

    def fake_run(argv, check=False):
        calls.append(argv)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gw_mod.subprocess, 'run', fake_run)

    assert writer.run_grub_update()[0] is True
    assert calls == [['/usr/sbin/grub-mkconfig', '-o', '/boot/grub/grub.cfg']]


def test_mkconfig_without_grub_cfg_omits_output_flag(tmp_path, monkeypatch):
    writer, _target, _u = make_writer(
        tmp_path, update_grub='/usr/sbin/grub-mkconfig', grub_cfg=None)
    monkeypatch.setattr(gw_mod.os, 'geteuid', lambda: 0)
    calls = []
    monkeypatch.setattr(gw_mod.subprocess, 'run',
                        lambda argv, check=False: calls.append(argv)
                        or SimpleNamespace(returncode=0))

    assert writer.run_grub_update()[0] is True
    assert calls == [['/usr/sbin/grub-mkconfig']]


def test_update_returns_command_exit_code(tmp_path, monkeypatch):
    writer, _target, _u = make_writer(tmp_path)
    monkeypatch.setattr(gw_mod.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(gw_mod.subprocess, 'run',
                        lambda *_a, **_k: SimpleNamespace(returncode=2))

    ok, msg = writer.run_grub_update()

    assert not ok
    assert 'exit code 2' in msg


def test_update_catches_os_error(tmp_path, monkeypatch):
    writer, _target, _u = make_writer(tmp_path)
    monkeypatch.setattr(gw_mod.os, 'geteuid', lambda: 0)

    def explode(*_a, **_k):
        raise OSError('permission denied')

    monkeypatch.setattr(gw_mod.subprocess, 'run', explode)

    ok, msg = writer.run_grub_update()

    assert not ok
    assert 'permission denied' in msg


# --- initramfs triggers ----------------------------------------------------

TRIGGERS = {'gpu_drivers': ['nvidia', 'nouveau'], 'modules': ['vfio']}


@pytest.mark.parametrize('diffs, expected', [
    ({'GRUB_CMDLINE_LINUX': ('', 'quiet nvidia-drm.modeset=1')},
     ('nvidia', 'gpu_drivers')),
    ({'GRUB_CMDLINE_LINUX_DEFAULT': ('nouveau.modeset=1', '')},
     ('nouveau', 'gpu_drivers')),
    ({'GRUB_CMDLINE_LINUX_RECOVERY': ('', 'VFIO')}, ('vfio', 'modules')),
])
def test_initramfs_trigger_detection(tmp_path, diffs, expected):
    writer, _target, _u = make_writer(tmp_path, triggers=TRIGGERS)

    needs, keyword, category = writer.should_rebuild_initramfs(diffs)

    assert needs is True
    assert (keyword, category) == expected


def test_initramfs_ignores_other_parameters(tmp_path):
    writer, _target, _u = make_writer(tmp_path, triggers=TRIGGERS)

    assert writer.should_rebuild_initramfs(
        {'GRUB_TIMEOUT': ('5', '10')}) == (False, '', '')


def test_initramfs_without_triggers_is_a_noop(tmp_path):
    writer, _target, _u = make_writer(tmp_path, triggers={})

    assert writer.should_rebuild_initramfs(
        {'GRUB_CMDLINE_LINUX': ('', 'nvidia')}) == (False, '', '')


# --- initramfs space -------------------------------------------------------

@pytest.fixture(name='space_system')
def fixture_space_system(monkeypatch):
    """Patch glob/getsize/statvfs with a controllable one-file /boot."""
    state = SimpleNamespace(existing_mb=100, free_mb=1000,
                            boot_files=['/boot/initrd.img-1'])

    monkeypatch.setattr(
        gw_mod.glob, 'glob',
        lambda pattern: list(state.boot_files)
        if pattern.endswith('initrd.img-*') else [])
    monkeypatch.setattr(
        gw_mod.os.path, 'getsize',
        lambda _path: int(state.existing_mb * 1024 * 1024))
    return state


def _statvfs(free_mb):
    return SimpleNamespace(f_bavail=int(free_mb * 1024 * 1024 / 4096),
                           f_frsize=4096)


@pytest.mark.parametrize('free_mb, sufficient, critical', [
    (1000, True, False),
    (200, False, False),
    (50, False, True),
])
def test_initramfs_space_outcomes(tmp_path, monkeypatch, space_system,
                                  free_mb, sufficient, critical):
    writer, _target, _u = make_writer(tmp_path)
    monkeypatch.setattr(gw_mod.os, 'statvfs', lambda _path: _statvfs(free_mb))

    info = writer.check_initramfs_space()

    assert info['boot_path'] == '/boot'
    assert info['existing_size_mb'] == pytest.approx(100)
    assert info['needed_mb'] == pytest.approx(250)  # 2x + 50 MB margin
    assert info['is_sufficient'] is sufficient
    assert info['is_critical'] is critical
    assert ('CRITICAL' if critical else
            'WARNING' if not sufficient else 'OK') in info['message']


def test_initramfs_space_failure_returns_safe_defaults(tmp_path, monkeypatch):
    writer, _target, _u = make_writer(tmp_path)

    def explode(_path):
        raise OSError('statvfs failed')

    monkeypatch.setattr(gw_mod.os, 'statvfs', explode)

    info = writer.check_initramfs_space()

    assert info['free_mb'] == -1
    assert info['needed_mb'] == -1
    assert info['is_sufficient'] is False
    assert 'Unable to check disk space' in info['message']


# --- initramfs update command ---------------------------------------------

@pytest.mark.parametrize('command, expected_tail', [
    ('/usr/sbin/update-initramfs', ['-u', '-k', 'all']),
    ('/usr/bin/dracut', ['--regenerate-all', '--force']),
    ('/usr/bin/mkinitcpio', ['-P']),
    ('/sbin/mkinitfs', []),
    ('/usr/bin/genkernel', ['--install', 'initramfs']),
    ('/opt/custom-initramfs', []),
])
def test_initramfs_command_per_distro(tmp_path, monkeypatch, command,
                                      expected_tail):
    writer, _target, _u = make_writer(tmp_path, update_initramfs=command)
    monkeypatch.setattr(gw_mod.os, 'geteuid', lambda: 0)
    calls = []
    monkeypatch.setattr(gw_mod.subprocess, 'run',
                        lambda argv, check=False: calls.append(argv)
                        or SimpleNamespace(returncode=0))

    ok, msg = writer.run_initramfs_update()

    assert ok and msg == 'OK'
    assert calls == [[command, *expected_tail]]


def test_initramfs_requires_root(tmp_path, monkeypatch):
    writer, _target, _u = make_writer(
        tmp_path, update_initramfs='/usr/sbin/update-initramfs')
    monkeypatch.setattr(gw_mod.os, 'geteuid', lambda: 1000)

    ok, msg = writer.run_initramfs_update()

    assert not ok
    assert 'root required' in msg


def test_initramfs_without_command_warns(tmp_path, monkeypatch):
    writer, _target, _u = make_writer(tmp_path, update_initramfs=None)
    monkeypatch.setattr(gw_mod.os, 'geteuid', lambda: 0)

    ok, msg = writer.run_initramfs_update()

    assert not ok
    assert 'No initramfs update command' in msg


def test_initramfs_failure_and_exception(tmp_path, monkeypatch):
    writer, _target, _u = make_writer(
        tmp_path, update_initramfs='/usr/bin/dracut')
    monkeypatch.setattr(gw_mod.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(gw_mod.subprocess, 'run',
                        lambda *_a, **_k: SimpleNamespace(returncode=1))

    ok, msg = writer.run_initramfs_update()
    assert not ok and 'exit code 1' in msg

    def explode(*_a, **_k):
        raise OSError('dracut missing')

    monkeypatch.setattr(gw_mod.subprocess, 'run', explode)
    ok, msg = writer.run_initramfs_update()
    assert not ok and 'dracut missing' in msg


# --- candidate validation fallbacks ---------------------------------------

def test_validate_without_sh_or_checker_warns_and_accepts(tmp_path, monkeypatch,
                                                          capsys):
    writer, _target, _u = make_writer(tmp_path)
    candidate = tmp_path / 'candidate'
    candidate.write_bytes(NEW)
    monkeypatch.setattr(gw_mod.shutil, 'which', lambda _name: None)
    monkeypatch.setattr(gw_mod.os.path, 'exists', lambda _path: False)

    ok, msg = writer._validate_candidate(candidate, NEW)

    assert ok and msg == 'OK'
    assert "was not syntax-checked" in capsys.readouterr().err


def test_validate_falls_back_to_grub_script_check(tmp_path, monkeypatch):
    writer, _target, _u = make_writer(tmp_path)
    candidate = tmp_path / 'candidate'
    candidate.write_bytes(NEW)
    monkeypatch.setattr(
        gw_mod.shutil, 'which',
        lambda name: '/usr/bin/grub-script-check'
        if name == 'grub-script-check' else None)
    monkeypatch.setattr(gw_mod.os.path, 'exists', lambda _path: False)
    calls = []
    monkeypatch.setattr(gw_mod.subprocess, 'run',
                        lambda argv, **_k: calls.append(argv)
                        or SimpleNamespace(returncode=0, stderr='', stdout=''))

    assert writer._validate_candidate(candidate, NEW)[0] is True
    assert calls == [['/usr/bin/grub-script-check', str(candidate)]]


def test_grub_script_check_rejection_is_advisory(tmp_path, monkeypatch, capsys):
    writer, _target, _u = make_writer(tmp_path)
    candidate = tmp_path / 'candidate'
    candidate.write_bytes(NEW)
    monkeypatch.setattr(gw_mod.shutil, 'which', lambda name: f'/usr/bin/{name}')

    def fake_run(argv, **_k):
        if argv[0].endswith('/sh'):
            return SimpleNamespace(returncode=0, stderr='', stdout='')
        return SimpleNamespace(returncode=1, stderr='parse error\nmore')

    monkeypatch.setattr(gw_mod.subprocess, 'run', fake_run)

    ok, _msg = writer._validate_candidate(candidate, NEW)

    assert ok is True
    assert 'advisory' in capsys.readouterr().err


# --- commit error branches -------------------------------------------------

def test_commit_requires_root(tmp_path, monkeypatch):
    writer, target, _u = make_writer(tmp_path)
    candidate = tmp_path / 'candidate'
    candidate.write_bytes(NEW)
    monkeypatch.setattr(gw_mod.os, 'geteuid', lambda: 1000)

    ok, msg = writer.commit_validated_grub_config(candidate)

    assert not ok
    assert 'Root access is required' in msg
    assert target.read_bytes() == OLD


def test_rollback_copy_failure_is_nonfatal(tmp_path, monkeypatch, capsys):
    writer, target, user_config = make_writer(tmp_path)
    candidate = tmp_path / 'candidate'
    candidate.write_bytes(NEW)
    user_config.fail_on_calls = {1}  # rollback copy
    monkeypatch.setattr(gw_mod.os, 'geteuid', lambda: 0)

    ok, msg = writer.commit_validated_grub_config(candidate)

    assert ok, msg
    assert target.read_bytes() == NEW
    assert 'could not write rollback copy' in capsys.readouterr().err


def test_target_write_failure_restores_previous_bytes(tmp_path, monkeypatch):
    writer, target, user_config = make_writer(tmp_path)
    candidate = tmp_path / 'candidate'
    candidate.write_bytes(NEW)
    user_config.fail_on_calls = {2}  # rollback copy succeeds, target fails
    monkeypatch.setattr(gw_mod.os, 'geteuid', lambda: 0)

    ok, msg = writer.commit_validated_grub_config(candidate)

    assert not ok
    assert 'previous' in msg and 'restored' in msg
    assert target.read_bytes() == OLD


def test_commit_creates_target_when_it_did_not_exist(tmp_path, monkeypatch):
    writer, target, user_config = make_writer(tmp_path)
    target.unlink()
    candidate = tmp_path / 'candidate'
    candidate.write_bytes(NEW)
    monkeypatch.setattr(gw_mod.os, 'geteuid', lambda: 0)

    ok, msg = writer.commit_validated_grub_config(candidate)

    assert ok, msg
    assert target.read_bytes() == NEW
    assert len(user_config.writes) == 1  # no rollback copy is written


def test_rollback_requires_root(tmp_path, monkeypatch):
    writer, _target, _u = make_writer(tmp_path)
    monkeypatch.setattr(gw_mod.os, 'geteuid', lambda: 1000)

    ok, msg = writer.rollback_last_commit()

    assert not ok
    assert 'root required' in msg
