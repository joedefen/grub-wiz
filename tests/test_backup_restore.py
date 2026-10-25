"""Security and error behaviour of ``BackupMgr``.

``restore_backup()`` copies untrusted, user-writable content over a root-owned
file that distro scripts *source*.  Its guard clauses therefore matter more
than the happy path, which was previously exercised only through stubs.
"""

import hashlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz.BackupMgr import BackupMgr, BACKUP_FILENAME_PATTERN


CONTENT = b'GRUB_TIMEOUT=5\n'


def make_manager(tmp_path, user_config, target_content=CONTENT):
    target = tmp_path / 'grub'
    target.write_bytes(target_content)
    manager = BackupMgr(target_path=target, user_config=user_config)
    return manager, target


def checksum(data=CONTENT):
    return hashlib.sha256(data).hexdigest()[:8].upper()


def test_calc_checksum_handles_missing_and_unreadable_paths(tmp_path):
    manager = BackupMgr(target_path=tmp_path / 'target',
                        user_config=_ManagerlessUserConfig(tmp_path))
    missing = tmp_path / 'missing'

    assert manager.calc_checksum(missing) == ''
    # A directory exists but cannot be read as bytes.
    assert manager.calc_checksum(tmp_path) == ''
    assert manager.calc_checksum('abc') == hashlib.sha256(b'abc').hexdigest()[:8].upper()
    with pytest.raises(TypeError):
        manager.calc_checksum(123)


def test_calc_checksum_str_and_path_agree(tmp_path):
    manager = BackupMgr(target_path=tmp_path / 'target',
                        user_config=_ManagerlessUserConfig(tmp_path))
    source = tmp_path / 'source'
    source.write_text('same', encoding='utf-8')

    assert manager.calc_checksum(source) == manager.calc_checksum('same')


class _ManagerlessUserConfig:
    """Only the attributes needed by tests that do not touch state."""

    def __init__(self, root):
        self.user_state_dir = Path(root)


def test_restore_requires_root(tmp_path, isolated_user_config_dir, monkeypatch):
    manager, target = make_manager(tmp_path, isolated_user_config_dir)
    backup = tmp_path / 'backup.bak'
    backup.write_bytes(b'GRUB_TIMEOUT=9\n')
    monkeypatch.setattr(os, 'geteuid', lambda: 1000)

    assert manager.restore_backup(backup) is False
    assert target.read_bytes() == CONTENT


def test_restore_rejects_symlinked_backup(tmp_path, isolated_user_config_dir,
                                          monkeypatch):
    manager, target = make_manager(tmp_path, isolated_user_config_dir)
    real = tmp_path / 'real.bak'
    real.write_bytes(b'GRUB_TIMEOUT=9\n')
    linked = isolated_user_config_dir.user_state_dir / 'linked.bak'
    linked.symlink_to(real)
    monkeypatch.setattr(os, 'geteuid', lambda: 0)

    assert manager.restore_backup(linked) is False
    assert target.read_bytes() == CONTENT


@pytest.mark.parametrize('payload, expected', [
    (b'GRUB_TIMEOUT=9\x00\n', 'NUL'),
    (b'GRUB_DISTRIBUTOR=$(reboot)\n', 'command substitution'),
    (b'GRUB_DISTRIBUTOR=`reboot`\n', 'command substitution'),
])
def test_restore_rejects_untrusted_payloads(tmp_path, isolated_user_config_dir,
                                            monkeypatch, payload, expected,
                                            capsys):
    manager, target = make_manager(tmp_path, isolated_user_config_dir)
    backup = isolated_user_config_dir.user_state_dir / 'payload.bak'
    backup.write_bytes(payload)
    monkeypatch.setattr(os, 'geteuid', lambda: 0)

    assert manager.restore_backup(backup) is False
    assert target.read_bytes() == CONTENT
    assert expected in capsys.readouterr().err


def test_restore_replaces_target_atomically(tmp_path, isolated_user_config_dir,
                                            monkeypatch):
    manager, target = make_manager(tmp_path, isolated_user_config_dir)
    backup = isolated_user_config_dir.user_state_dir / 'new.bak'
    backup.write_bytes(b'GRUB_TIMEOUT=9\n')
    monkeypatch.setattr(os, 'geteuid', lambda: 0)

    assert manager.restore_backup(backup) is True
    assert target.read_bytes() == b'GRUB_TIMEOUT=9\n'


def test_restore_honours_explicit_destination(tmp_path, isolated_user_config_dir,
                                              monkeypatch):
    manager, original = make_manager(tmp_path, isolated_user_config_dir)
    backup = isolated_user_config_dir.user_state_dir / 'new.bak'
    backup.write_bytes(b'GRUB_TIMEOUT=9\n')
    destination = tmp_path / 'other-grub'
    monkeypatch.setattr(os, 'geteuid', lambda: 0)

    assert manager.restore_backup(backup, dest_path=destination) is True
    assert destination.read_bytes() == b'GRUB_TIMEOUT=9\n'
    assert original.read_bytes() == CONTENT


def test_restore_write_failure_returns_false(tmp_path, isolated_user_config_dir,
                                             monkeypatch):
    manager, target = make_manager(tmp_path, isolated_user_config_dir)
    backup = isolated_user_config_dir.user_state_dir / 'new.bak'
    backup.write_bytes(b'GRUB_TIMEOUT=9\n')
    monkeypatch.setattr(os, 'geteuid', lambda: 0)

    def fail_write(*_args, **_kwargs):
        raise OSError('disk full')

    monkeypatch.setattr(isolated_user_config_dir, 'atomic_root_write', fail_write)

    assert manager.restore_backup(backup) is False
    assert target.read_bytes() == CONTENT


def test_create_backup_missing_target_returns_none(tmp_path,
                                                   isolated_user_config_dir):
    manager = BackupMgr(target_path=tmp_path / 'missing',
                        user_config=isolated_user_config_dir)

    assert manager.create_backup('orig') is None


def test_create_backup_without_checksum_returns_none(tmp_path,
                                                     isolated_user_config_dir,
                                                     monkeypatch):
    manager, _target = make_manager(tmp_path, isolated_user_config_dir)
    monkeypatch.setattr(manager, 'calc_checksum', lambda _source: '')

    assert manager.create_backup('orig') is None


def test_create_backup_read_failure_returns_none(tmp_path,
                                                 isolated_user_config_dir,
                                                 monkeypatch):
    manager, _target = make_manager(tmp_path, isolated_user_config_dir)
    monkeypatch.setattr(manager, 'calc_checksum', lambda _source: 'DEADBEEF')
    monkeypatch.setattr(isolated_user_config_dir, 'safe_read_bytes',
                        lambda *_a, **_k: (_ for _ in ()).throw(OSError('denied')))

    assert manager.create_backup('orig') is None


def test_get_backups_ignores_symlinks_and_other_non_files(tmp_path,
                                                          isolated_user_config_dir):
    manager = BackupMgr(target_path=tmp_path / 'grub',
                        user_config=isolated_user_config_dir)
    state = isolated_user_config_dir.user_state_dir
    real = state / f'20260101-000000-{checksum()}.orig.bak'
    real.write_bytes(CONTENT)
    linked = state / f'20260102-000000-{checksum()}.linked.bak'
    linked.symlink_to(real)
    (state / 'subdir').mkdir()

    backups = manager.get_backups()

    assert set(backups) == {real.name}
    assert BACKUP_FILENAME_PATTERN.search(real.name)
