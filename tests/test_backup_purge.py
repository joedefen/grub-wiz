"""Retention: trimming the backup inventory back to ``KEEP_BACKUPS``.

Ordering is the filename alone -- every name starts with ``YYYYMMDD-HHMMSS``,
so alphabetical order is chronological order and the modification time is
never consulted.  The oldest record is always kept.  Every other record is
sacrificed oldest-first, with one preference: when the oldest removable
record carries a descriptive tag and the record *immediately* after it holds
the same bytes and is a ``RESYNC`` (or untagged), the ``RESYNC`` goes instead,
so the tag that says what changed survives.  The purge stops the moment the
inventory is down to the limit.
"""

import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz.BackupMgr import (  # noqa: E402
    BASELINE_TAG,
    KEEP_BACKUPS,
    RESYNC_TAG,
    BackupMgr,
)


STATE_X = b'GRUB_CMDLINE_LINUX="quiet"\n'
STATE_Y = b'GRUB_CMDLINE_LINUX="debug"\n'


def content(index):
    """A distinct payload per index, so contents never collide by accident."""
    return f'GRUB_TIMEOUT={index}\n'.encode()


def checksum(data):
    return hashlib.sha256(data).hexdigest()[:6].upper()


def stamp(index):
    """A timestamp whose alphabetical order matches the numeric order."""
    return f'20260101-{index:06d}'


def file_name(index, tag=None, data=None):
    data = content(index) if data is None else data
    suffix = f'.{tag}' if tag else ''
    return f'{stamp(index)}-s{checksum(data)}{suffix}.bak'


class FakeUserConfig:
    """Minimal user-state store; permission handling is not under test."""

    def __init__(self, root):
        self.user_state_dir = root

    @staticmethod
    def safe_read_bytes(path, max_bytes=1024 * 1024):
        del max_bytes
        return Path(path).read_bytes()


def make_manager(tmp_path):
    backup_dir = tmp_path / 'backups'
    backup_dir.mkdir()
    target = tmp_path / 'grub'
    target.write_bytes(content(0))
    manager = BackupMgr(target_path=target,
                        user_config=FakeUserConfig(backup_dir))
    return manager, backup_dir


def write(directory, index, tag=None, data=None):
    """Create one backup file and return its path."""
    path = directory / file_name(index, tag, data)
    path.write_bytes(content(index) if data is None else data)
    return path


def names(directory):
    return sorted(path.name for path in directory.glob('*.bak'))


def test_the_limit_is_twenty_four():
    assert KEEP_BACKUPS == 24


def test_a_small_inventory_is_left_alone(tmp_path, capsys):
    manager, backup_dir = make_manager(tmp_path)
    for index in range(24):
        write(backup_dir, index)

    assert manager.purge_backups() == []
    assert len(names(backup_dir)) == 24
    assert capsys.readouterr().out == '', 'a no-op purge must stay silent'


def test_the_oldest_record_is_never_removed(tmp_path):
    manager, backup_dir = make_manager(tmp_path)
    for index in range(30):
        write(backup_dir, index)

    removed = manager.purge_backups()

    remaining = names(backup_dir)
    assert len(remaining) == 24
    assert file_name(0) in remaining, 'the eldest is the history floor'
    assert set(removed) == {file_name(index) for index in range(1, 7)}


def test_a_follower_resync_is_sacrificed_to_save_a_tagged_record(tmp_path):
    """The worked example: 25 entries, so exactly the RESYNC next door goes."""
    manager, backup_dir = make_manager(tmp_path)
    write(backup_dir, 0, BASELINE_TAG, data=STATE_Y)
    write(backup_dir, 1, '+FooBar', data=STATE_X)
    write(backup_dir, 2, RESYNC_TAG, data=STATE_X)
    for index in range(3, 25):
        write(backup_dir, index)

    removed = manager.purge_backups()

    remaining = names(backup_dir)
    assert removed == [file_name(2, RESYNC_TAG, STATE_X)]
    assert file_name(1, '+FooBar', STATE_X) in remaining
    assert len(remaining) == 24


def test_the_tagged_record_goes_when_no_adjacent_copy_matches(tmp_path):
    """One more entry: the RESYNC goes first, then the tagged record itself."""
    manager, backup_dir = make_manager(tmp_path)
    write(backup_dir, 0, BASELINE_TAG, data=STATE_Y)
    write(backup_dir, 1, '+FooBar', data=STATE_X)
    write(backup_dir, 2, RESYNC_TAG, data=STATE_X)
    for index in range(3, 26):
        write(backup_dir, index)

    removed = manager.purge_backups()

    assert removed == [file_name(2, RESYNC_TAG, STATE_X),
                       file_name(1, '+FooBar', STATE_X)]
    assert len(names(backup_dir)) == 24


def test_a_non_adjacent_copy_does_not_save_an_older_record(tmp_path):
    """Only the immediate neighbour is compared, never one further down."""
    manager, backup_dir = make_manager(tmp_path)
    write(backup_dir, 0, BASELINE_TAG, data=STATE_Y)
    write(backup_dir, 1, '+FooBar', data=STATE_X)
    write(backup_dir, 2)                                  # different content
    write(backup_dir, 3, RESYNC_TAG, data=STATE_X)        # same content, apart
    for index in range(4, 25):
        write(backup_dir, index)

    removed = manager.purge_backups()

    remaining = names(backup_dir)
    assert removed == [file_name(1, '+FooBar', STATE_X)]
    assert file_name(3, RESYNC_TAG, STATE_X) in remaining
    assert len(remaining) == 24


def test_the_purge_stops_at_the_limit(tmp_path):
    """40 identical RESYNC files are trimmed to 24, not collapsed to one."""
    manager, backup_dir = make_manager(tmp_path)
    for index in range(40):
        write(backup_dir, index, RESYNC_TAG, data=STATE_X)

    removed = manager.purge_backups()

    assert len(removed) == 16
    assert len(names(backup_dir)) == 24
    assert file_name(0, RESYNC_TAG, STATE_X) in names(backup_dir)


def test_the_modification_time_is_ignored_when_choosing_the_eldest(tmp_path):
    manager, backup_dir = make_manager(tmp_path)
    first = write(backup_dir, 0, 'old')
    second = write(backup_dir, 1, 'new', data=STATE_X)
    os.utime(first, (2_000_000_000, 2_000_000_000))

    assert manager.sort_key(first) == first.name
    assert manager.purge_backups(keep=1) == [second.name]
    assert first.exists()


def test_legacy_names_take_part_in_the_purge(tmp_path):
    """A name written by an older release sorts by its stamp like any other."""
    manager, backup_dir = make_manager(tmp_path)
    legacy = backup_dir / '20250101-000000-ABCD1234.orig.bak'
    legacy.write_bytes(STATE_Y)
    for index in range(24):
        write(backup_dir, index)

    assert manager.purge_backups() == [file_name(0)]

    remaining = names(backup_dir)
    assert legacy.name in remaining, 'the legacy record is the eldest'
    assert len(remaining) == 24


def test_the_summary_is_a_single_line(tmp_path, capsys):
    manager, backup_dir = make_manager(tmp_path)
    for index in range(25):
        write(backup_dir, index)

    manager.purge_backups()

    assert capsys.readouterr().out == 'Purge: 25 -> 24 backups.\n'


def test_an_unreadable_record_is_never_mistaken_for_a_duplicate(tmp_path,
                                                               monkeypatch):
    """Identity is byte equality, so a read failure cannot justify a delete."""
    manager, backup_dir = make_manager(tmp_path)
    write(backup_dir, 0, BASELINE_TAG, data=STATE_Y)
    tagged = write(backup_dir, 1, '+FooBar', data=STATE_X)
    follower = write(backup_dir, 2, RESYNC_TAG, data=STATE_X)
    for index in range(3, 25):
        write(backup_dir, index)
    real_read = FakeUserConfig.safe_read_bytes

    def blind_read(path, max_bytes=1024 * 1024):
        if Path(path).name == follower.name:
            raise OSError('unreadable')
        return real_read(path, max_bytes)

    monkeypatch.setattr(FakeUserConfig, 'safe_read_bytes',
                        staticmethod(blind_read))

    manager.purge_backups()

    # The follower cannot be proven redundant, so the older record goes first.
    assert not tagged.exists()
    assert follower.exists()
    assert len(names(backup_dir)) == 24
