"""Coverage for the backup inventory and the backup naming scheme.

A backup file is identified by its unique filename.  Identical content is not
suppressed while the inventory is small: two different states may
legitimately hold the same bytes, and hiding one of them loses history.  The
one write-time collapse is ``RESYNC``, which removes the adjacent ``RESYNC``
of the same content it replaces.  Pruning old records is covered separately by
``test_backup_purge.py``.
"""

import hashlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

import grub_wiz.BackupMgr as backup_module  # noqa: E402
from grub_wiz.BackupMgr import (  # noqa: E402
    BACKUP_FILENAME_PATTERN,
    BASELINE_TAG,
    RESYNC_TAG,
    BackupMgr,
)
from grub_wiz.main import GrubWiz  # noqa: E402


CONTENT = b'GRUB_TIMEOUT=5\n'
OTHER = b'GRUB_TIMEOUT=9\n'


def content_checksum(data=CONTENT):
    """Return the checksum component a current backup name carries."""
    return hashlib.sha256(data).hexdigest()[:6].upper()


def legacy_checksum(data=CONTENT):
    """Return the checksum component an old release wrote."""
    return hashlib.sha256(data).hexdigest()[:8].upper()


def new_name(stamp, tag=None, data=CONTENT):
    """Build a current-format filename."""
    suffix = f'.{tag}' if tag else ''
    return f'{stamp}-s{content_checksum(data)}{suffix}.bak'


def legacy_name(stamp, tag, data=CONTENT):
    """Build a filename written by an earlier release (eight hex digits)."""
    return f'{stamp}-{legacy_checksum(data)}.{tag}.bak'


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


class _Clock:
    """Stand-in for ``datetime`` so filenames are deterministic."""

    def __init__(self, stamp):
        self.stamp = stamp

    def strftime(self, _fmt):
        return self.stamp


def freeze(monkeypatch, stamp):
    """Pin the timestamp ``create_backup()`` writes."""
    monkeypatch.setattr(
        backup_module, 'datetime',
        SimpleNamespace(now=lambda: _Clock(stamp)))


def make_manager(tmp_path):
    """Create a manager whose target and backup directory are temporary."""
    backup_dir = tmp_path / 'backups'
    backup_dir.mkdir()
    target = tmp_path / 'grub'
    target.write_bytes(CONTENT)
    manager = BackupMgr(target_path=target,
                        user_config=FakeUserConfig(backup_dir))
    return manager, backup_dir, target


def write_backup(directory, name, data=CONTENT):
    path = directory / name
    path.write_bytes(data)
    return path


def test_all_backup_files_are_listed(tmp_path):
    """Current and legacy names are both real backups."""
    manager, backup_dir, _target = make_manager(tmp_path)
    tagged = write_backup(backup_dir, new_name('20260101-000000', 'DisablSubmen'))
    untagged = write_backup(backup_dir, new_name('20260102-000000'))
    legacy = write_backup(backup_dir, legacy_name('20260103-000000', 'orig'))

    backups = manager.get_backups()

    assert set(backups) == {tagged.name, untagged.name, legacy.name}
    assert all(BACKUP_FILENAME_PATTERN.search(name) for name in backups)


def test_names_report_their_checksum_and_tag(tmp_path):
    manager, backup_dir, _target = make_manager(tmp_path)
    untagged = write_backup(backup_dir, new_name('20260101-000000'))
    legacy = write_backup(backup_dir, legacy_name('20260102-000000', 'orig'))

    assert manager.checksum_from_name(untagged.name) == content_checksum()
    assert manager.tag_from_name(untagged.name) == ''
    assert manager.checksum_from_name(legacy.name) == legacy_checksum()
    assert manager.tag_from_name(legacy.name) == 'orig'
    assert manager.checksum_matches(legacy_checksum(), content_checksum())


def test_create_backup_uses_baseline_and_six_hex_digits(tmp_path, monkeypatch):
    manager, backup_dir, _target = make_manager(tmp_path)
    freeze(monkeypatch, '20260101-000000')

    path = manager.create_backup(BASELINE_TAG)

    assert path.name == new_name('20260101-000000', BASELINE_TAG)
    assert len(list(backup_dir.glob('*.bak'))) == 1


def test_create_backup_writes_an_untagged_name_without_a_tag(tmp_path,
                                                             monkeypatch):
    manager, backup_dir, _target = make_manager(tmp_path)
    freeze(monkeypatch, '20260101-000000')

    path = manager.create_backup()

    assert path.name == new_name('20260101-000000')
    assert manager.tag_from_name(path.name) == ''
    assert len(list(backup_dir.glob('*.bak'))) == 1


def test_identical_content_is_not_suppressed(tmp_path, monkeypatch):
    """Two different states may hold the same bytes; keep both records."""
    manager, backup_dir, _target = make_manager(tmp_path)
    freeze(monkeypatch, '20260101-000000')
    first = manager.create_backup(BASELINE_TAG)
    freeze(monkeypatch, '20260102-000000')
    second = manager.create_backup('~Timeout')

    assert first != second
    assert first.exists() and second.exists()
    assert len(list(backup_dir.glob('*.bak'))) == 2


def test_resync_keeps_only_the_latest_file(tmp_path, monkeypatch):
    manager, backup_dir, _target = make_manager(tmp_path)
    freeze(monkeypatch, '20260101-000000')
    first = manager.create_backup(RESYNC_TAG)
    freeze(monkeypatch, '20260102-000000')
    second = manager.create_backup(RESYNC_TAG)

    assert first != second
    assert not first.exists(), 'the superseded RESYNC must be removed'
    assert [path.name for path in backup_dir.glob('*.bak')] == [second.name]


def test_resync_leaves_other_tags_alone(tmp_path, monkeypatch):
    """Only RESYNC collapses; a tagged snapshot of the same content stays."""
    manager, backup_dir, _target = make_manager(tmp_path)
    freeze(monkeypatch, '20260101-000000')
    kept = manager.create_backup(BASELINE_TAG)
    freeze(monkeypatch, '20260102-000000')
    resync = manager.create_backup(RESYNC_TAG)

    assert kept.exists() and resync.exists()
    assert len(list(backup_dir.glob('*.bak'))) == 2


class _FixedDigest:
    """Pretend every content hashes to the same value."""

    @staticmethod
    def hexdigest():
        return 'ABCDEF' + '0' * 58


def test_same_name_different_content_is_never_overwritten(tmp_path, monkeypatch):
    """A checksum collision must not let a write destroy an existing file."""
    manager, backup_dir, target = make_manager(tmp_path)
    freeze(monkeypatch, '20260101-000000')
    monkeypatch.setattr(backup_module.hashlib, 'sha256',
                        lambda _data: _FixedDigest())
    first = manager.create_backup('~Timeout')
    target.write_bytes(OTHER)

    assert manager.create_backup('~Timeout') is None
    assert first.read_bytes() == CONTENT
    assert len(list(backup_dir.glob('*.bak'))) == 1


def test_same_second_same_tag_returns_the_existing_identical_file(tmp_path,
                                                                 monkeypatch):
    manager, backup_dir, _target = make_manager(tmp_path)
    freeze(monkeypatch, '20260101-000000')
    first = manager.create_backup(RESYNC_TAG)
    second = manager.create_backup(RESYNC_TAG)

    assert second == first
    assert len(list(backup_dir.glob('*.bak'))) == 1


def test_resync_collapse_cascades_through_an_adjacent_chain(tmp_path,
                                                            monkeypatch):
    """A pre-existing run of identical RESYNC files is repaired on write."""
    manager, backup_dir, _target = make_manager(tmp_path)
    write_backup(backup_dir, new_name('20260101-000000', RESYNC_TAG))
    write_backup(backup_dir, new_name('20260102-000000', RESYNC_TAG))
    freeze(monkeypatch, '20260103-000000')

    newest = manager.create_backup(RESYNC_TAG)

    assert [path.name for path in backup_dir.glob('*.bak')] == [newest.name]


def test_resync_collapse_stops_at_a_different_content(tmp_path, monkeypatch):
    """Only the adjacent same-content RESYNC is removed, never one further back."""
    manager, backup_dir, _target = make_manager(tmp_path)
    older = write_backup(backup_dir, new_name('20260101-000000', RESYNC_TAG),
                         data=OTHER)
    write_backup(backup_dir, new_name('20260102-000000', RESYNC_TAG))
    freeze(monkeypatch, '20260103-000000')

    manager.create_backup(RESYNC_TAG)

    assert older.exists(), 'a neighbour with different bytes must survive'
    assert len(list(backup_dir.glob('*.bak'))) == 2


def test_ordering_is_the_filename_not_the_modification_time(tmp_path):
    """A bulk copy rewrites mtimes; the name is the only authority."""
    manager, backup_dir, _target = make_manager(tmp_path)
    first = write_backup(backup_dir, new_name('20260101-000000', 'old'))
    second = write_backup(backup_dir, new_name('20260102-000000', 'new',
                                               data=OTHER))
    os.utime(first, (2_000_000_000, 2_000_000_000))

    assert manager.sort_key(first) == first.name
    assert sorted([second, first], key=manager.sort_key) == [first, second]


def test_retagged_name_preserves_the_checksum(tmp_path):
    manager, _backup_dir, _target = make_manager(tmp_path)
    untagged = new_name('20260101-000000')
    tagged = new_name('20260101-000000', 'old')

    assert manager.retagged_name(untagged, 'named') == new_name(
        '20260101-000000', 'named')
    assert manager.retagged_name(tagged, 'new') == new_name(
        '20260101-000000', 'new')
    assert manager.retagged_name(untagged, '') == untagged


def test_retagged_name_keeps_a_legacy_name_legacy(tmp_path):
    manager, _backup_dir, _target = make_manager(tmp_path)
    legacy = legacy_name('20260101-000000', 'orig')

    assert manager.retagged_name(legacy, 'mine') == legacy.replace(
        '.orig.bak', '.mine.bak')


def test_restore_list_keeps_one_row_per_file(tmp_path):
    """The UI inventory must carry filename rows plus their checksums."""
    manager, backup_dir, _target = make_manager(tmp_path)
    first = write_backup(backup_dir, new_name('20260101-000000', 'before'))
    second = write_backup(backup_dir, new_name('20260102-000000', 'after',
                                               data=OTHER))
    gw = SimpleNamespace(backup_mgr=manager)

    GrubWiz.refresh_backup_list(gw)

    assert {pair[1] for pair in gw.ordered_backup_pairs} == {first, second}
    assert {pair[0] for pair in gw.ordered_backup_pairs} == {
        content_checksum(), content_checksum(OTHER)}


def test_backup_manager_resolves_user_config_lazily(monkeypatch, tmp_path):
    """Importing the module must not create user state (audit M13).

    The manager asks ``UserConfigDir`` for the singleton when it is
    constructed, so the accessor must not exist as a module-level attribute.
    """
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
