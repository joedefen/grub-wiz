"""Regression coverage for backup inventory identity.

A backup file is identified by its unique filename.  ``create_backup()`` still
avoids creating a second file for identical content on a best-effort basis, but
files that are already on disk must all appear in the restore list, even when
their checksums match.
"""

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz.BackupMgr import BackupMgr  # noqa: E402
from grub_wiz.main import GrubWiz  # noqa: E402


CONTENT = b'GRUB_TIMEOUT=5\n'


def content_checksum(data=CONTENT):
    """Return the checksum component ``BackupMgr`` would write."""
    return hashlib.sha256(data).hexdigest()[:8].upper()


class FakeUserConfig:
    """Minimal user-state store; permission handling is out of scope here."""

    def __init__(self, root):
        self.user_state_dir = root

    @staticmethod
    def safe_read_bytes(path, max_bytes=1024 * 1024):
        del max_bytes
        return Path(path).read_bytes()

    @staticmethod
    def atomic_user_write(path, data, mode=0o644):
        del mode
        Path(path).write_bytes(data)


def make_manager(tmp_path):
    """Create a manager whose target and backup directory are temporary."""
    backup_dir = tmp_path / 'backups'
    backup_dir.mkdir()
    target = tmp_path / 'grub'
    target.write_bytes(CONTENT)
    manager = BackupMgr(target_path=target,
                        user_config=FakeUserConfig(backup_dir))
    return manager, backup_dir, target


def write_backup(directory, timestamp, tag, data=CONTENT):
    """Write a valid backup filename with an explicit timestamp/tag."""
    path = directory / f'{timestamp}-{content_checksum(data)}.{tag}.bak'
    path.write_bytes(data)
    return path


def test_all_backup_files_are_listed(tmp_path):
    """Same-content files with different tags must both be returned."""
    manager, backup_dir, _target = make_manager(tmp_path)
    first = write_backup(backup_dir, '20260101-000000', 'before-upgrade')
    second = write_backup(backup_dir, '20260102-000000', 'working')

    backups = manager.get_backups()

    assert set(backups) == {first.name, second.name}
    assert backups[first.name] == first
    assert backups[second.name] == second
    assert all(manager.checksum_from_name(name) == content_checksum()
               for name in backups)


def test_create_backup_still_avoids_new_duplicates(tmp_path):
    """Best-effort dedupe still returns the existing file, not a copy."""
    manager, backup_dir, _target = make_manager(tmp_path)

    first = manager.create_backup('orig')
    second = manager.create_backup('retry')

    assert first is not None
    assert second == first
    assert len(manager.get_backups()) == 1
    assert len(list(backup_dir.glob('*.bak'))) == 1


def test_existing_duplicate_stays_visible_and_is_not_duplicated_again(tmp_path):
    """A duplicate already on disk is shown and does not multiply."""
    manager, backup_dir, target = make_manager(tmp_path)
    first = manager.create_backup('orig')
    duplicate = write_backup(backup_dir, '20991231-235959', 'manual')

    assert first != duplicate
    assert len(manager.get_backups()) == 2

    third = manager.create_backup('third')

    # Dedupe returns one of the existing files; it neither adds another file
    # nor hides the duplicate that was already there.
    assert third in {first, duplicate}
    assert len(manager.get_backups()) == 2
    assert len(list(backup_dir.glob('*.bak'))) == 2
    assert target.exists()


def test_restore_list_keeps_one_row_per_file(tmp_path):
    """The UI inventory must carry filename rows plus their checksums."""
    manager, backup_dir, _target = make_manager(tmp_path)
    first = write_backup(backup_dir, '20260101-000000', 'before-upgrade')
    second = write_backup(backup_dir, '20260102-000000', 'working')
    gw = SimpleNamespace(backup_mgr=manager)

    GrubWiz.refresh_backup_list(gw)

    assert {pair[1] for pair in gw.ordered_backup_pairs} == {first, second}
    assert {pair[0] for pair in gw.ordered_backup_pairs} == {content_checksum()}


def test_backup_manager_resolves_user_config_lazily(monkeypatch, tmp_path):
    """Importing the module must not create user state (audit M13).

    The manager asks ``UserConfigDir`` for the singleton when it is
    constructed, so the accessor must not exist as a module-level attribute.
    """
    import grub_wiz.BackupMgr as backup_module

    assert not hasattr(backup_module, 'USER_CONFIG')
    assert not hasattr(backup_module, 'GRUB_CONFIG_DIR')

    fake = SimpleNamespace(user_state_dir=tmp_path / 'state')
    calls = []
    monkeypatch.setattr(
        backup_module.UserConfigDir, 'get_singleton',
        staticmethod(lambda app_name='grub-wiz':
                     calls.append(app_name) or fake),
    )

    manager = backup_module.BackupMgr()

    assert calls == ['grub-wiz']
    assert manager.config_dir == fake.user_state_dir
