#!/usr/bin/env python3
"""Create, list, restore, and delete backups of ``/etc/default/grub``.

Backups are owned by the invoking user and live in the user state
directory.  Files read from that directory are treated as untrusted input;
writes to the root-owned target go through the symlink-safe atomic helpers
in :mod:`grub_wiz.UserConfigDir`.

Naming
------
``{YYYYMMDD}-{HHMMSS}-s{CHK6}.{tag}.bak``, where ``CHK6`` is the first six
hex digits of the content's SHA-256, upper case, behind a lower-case ``s``.
The tag is optional: a snapshot whose change nobody could classify carries
no tag at all (``{date}-{time}-s{CHK6}.bak``).  The timestamp is the index a
user restores by; the tag is a hint.

Content duplicates are kept while the inventory is small: two different states
may legitimately hold the same bytes, and hiding one of them loses history.
Two mechanisms stop the directory growing without bound.  A new ``RESYNC``
removes the adjacent ``RESYNC`` of the same content it was written next to,
because neither says anything the other does not.  The start-up purge trims
the inventory back to :data:`KEEP_BACKUPS`, sacrificing an adjacent
same-content ``RESYNC`` before an older record that still carries a
descriptive tag.

Ordering
--------
The filename alone is the authority: every name begins with
``YYYYMMDD-HHMMSS``, so alphabetical order is chronological order and the
rest of the name is a total tie-break inside one second.  A file's
modification time records when the copy was made, not when the state existed,
so it is never consulted.

Backwards compatibility
-----------------------
Backups written by older releases (``{date}-{time}-{CHK8}.{tag}.bak``) are
listed, restorable and retaggable.  They are never renamed behind the user's
back.
"""
# pylint: disable=line-too-long,invalid-name
import os
import sys
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Union

from .DistroVars import DEFAULT_ETC_GRUB
from .UserConfigDir import UserConfigDir

# --- Constants ---

# Derived from the single canonical constant (audit M10).  The application
# passes ``DistroVars.etc_grub`` explicitly so a distro override is honoured.
GRUB_DEFAULT_PATH = Path(DEFAULT_ETC_GRUB)

#: Number of hex digits kept in a backup filename.
CHK_LEN = 6

#: Number of backup files the start-up purge leaves behind.
KEEP_BACKUPS = 24

#: Tag of the first backup ever recorded for this user.
BASELINE_TAG = 'BASELINE'

#: Tag of a backup that holds the same content as the previous one.
RESYNC_TAG = 'RESYNC'

# Recognises both the current shape (``s`` + 6 hex, optional tag) and the
# legacy one (8 hex, mandatory tag).  ``stamp`` is the leading date-time.
BACKUP_FILENAME_PATTERN = re.compile(
    r'^(?P<stamp>\d{8}-\d{6})-'
    r'(?:s(?P<chk6>[0-9A-F]{6})(?:\.(?P<tag6>[A-Za-z0-9_+~-]+))?'
    r'|(?P<chk8>[0-9A-Fa-f]{8})\.(?P<tag8>[A-Za-z0-9_-]+))'
    r'\.bak$'
)

# --- Class Implementation ---

class BackupMgr:
    """
    Manages backups for the /etc/default/grub configuration file.
    Backups are stored in the real user's ~/.config/grub-wiz/ location.
    """

    def __init__(self, target_path: Path = GRUB_DEFAULT_PATH, user_config=None):
        # Accept str for convenience; every method operates on a Path.
        self.target_path = Path(target_path)

        # Resolve the user state directory lazily.  The module used to call
        # UserConfigDir.get_singleton() at import time, which created
        # ~/.config/grub-wiz as a side effect of importing the package (and
        # defeated test isolation, audit M13).
        self.user_config = (user_config if user_config is not None
                            else UserConfigDir.get_singleton("grub-wiz"))
        self.config_dir = self.user_config.user_state_dir

        # Reason the most recent restore_backup() refused or failed.  The TUI
        # runs under curses, so a message printed to stderr is invisible to
        # the user; the caller reads this attribute and shows it in an alert.
        self.last_error: str = ''

    def calc_checksum(self, source: Union[Path, str]) -> str:
        """Return the first 6 hex digits of the SHA-256 of a file or string.

        A missing or unreadable file yields ``''`` so callers can treat the
        checksum as "unknown" instead of raising during a backup listing.
        """
        content = b''

        if isinstance(source, Path):
            if not source.exists():
                return ""
            try:
                content = source.read_bytes()
            except OSError:
                return ""
        elif isinstance(source, str):
            content = source.encode('utf-8')
        else:
            raise TypeError("Source must be a Path or a string.")

        return hashlib.sha256(content).hexdigest()[:CHK_LEN].upper()

    @staticmethod
    def checksum_from_name(name: str) -> str:
        """Return the checksum encoded in a backup filename, or ''.

        A filename is the identity of a backup once it is on disk.  The
        checksum component tells which content the file *claims* to hold; it
        is a label, not a key, because six hex digits can collide.
        """
        match = BACKUP_FILENAME_PATTERN.search(name)
        if not match:
            return ''
        return (match.group('chk6') or match.group('chk8') or '').upper()

    @staticmethod
    def checksum_matches(backup_checksum: str, current_checksum: str) -> bool:
        """True when *backup_checksum* can identify *current_checksum*.

        Current names carry six digits while legacy names carry eight, so the
        longer value is matched by prefix.  A match is only ever used to draw
        the "current configuration" marker or to pre-select a candidate for
        deletion; anything destructive additionally compares file bytes.
        """
        if not backup_checksum or not current_checksum:
            return False
        return backup_checksum.upper().startswith(current_checksum.upper())

    @staticmethod
    def tag_from_name(name: str) -> str:
        """Return the tag encoded in a backup filename, or '' when untagged."""
        match = BACKUP_FILENAME_PATTERN.search(name)
        if not match:
            return ''
        return match.group('tag6') or match.group('tag8') or ''

    @classmethod
    def retagged_name(cls, name: str, tag: str) -> str:
        """Return *name* with its tag replaced or added.

        The stamp and checksum are preserved.  Substituting the last
        dot-separated component would overwrite the checksum of an untagged
        name, whose component is the checksum itself.
        """
        match = BACKUP_FILENAME_PATTERN.search(name)
        if not match or not tag:
            return name
        stamp = match.group('stamp')
        if match.group('chk6'):
            return f'{stamp}-s{match.group("chk6")}.{tag}.bak'
        return f'{stamp}-{match.group("chk8")}.{tag}.bak'

    def get_backups(self) -> Dict[str, Path]:
        """Return every backup file, keyed by its unique filename.

        Directory entries already have unique names, so keying by filename
        exposes the complete inventory.  Files with identical content but
        different tags are all returned: the tag is what distinguishes them.
        """
        backups: Dict[str, Path] = {}
        # Do not follow symlinks: a link must never be treated as a backup.
        with os.scandir(self.config_dir) as entries:
            for entry in entries:
                if not entry.is_file(follow_symlinks=False):
                    continue
                if BACKUP_FILENAME_PATTERN.search(entry.name):
                    backups[entry.name] = self.config_dir / entry.name
        return backups

    def sort_key(self, path: Path):
        """Return a key that orders backups oldest first.

        The filename is the only authority.  It begins with the
        ``YYYYMMDD-HHMMSS`` stamp, so alphabetical order is chronological
        order, and the rest of the name breaks ties inside one second.  The
        modification time is deliberately ignored: it records when the copy
        was made -- not when the state existed -- and a bulk copy rewrites it.
        """
        return Path(path).name

    def _content(self, path: Path) -> Optional[bytes]:
        """Return *path*'s bytes, or ``None`` when it cannot be read."""
        try:
            return self.user_config.safe_read_bytes(path)
        except (OSError, ValueError):
            return None

    def _holds(self, path: Path, data: bytes) -> bool:
        """True when *path* can be read and holds exactly *data*."""
        return self._content(path) == data

    @staticmethod
    def _command_substitution_line(data: bytes) -> Optional[int]:
        """Return the 1-based line of live command substitution, or ``None``.

        ``/etc/default/grub`` is sourced by the distro's shell scripts, so a
        substitution in an *assignment* is root code execution.  Comments are
        never executed, and stock distro files contain backticks inside their
        commentary (Debian: "the command ``videoinfo'``"), so scanning the raw
        bytes rejected perfectly valid restores.  Only lines that survive
        comment removal can run.
        """
        text = data.decode('utf-8', errors='replace')
        for line_number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            if '`' in stripped or '$(' in stripped:
                return line_number
        return None

    def restore_backup(self, backup_file: Path, dest_path: Optional[Path] = None) -> bool:
        """Restore *backup_file* over *dest_path* (default: the target path).

        Returns ``True`` only after the destination was atomically replaced.
        The backup is untrusted user-owned input, so symlinks, NUL bytes, and
        command substitution in live (non-comment) code are rejected before any
        privileged write.  On failure ``last_error`` explains why.
        """
        destination = dest_path if dest_path is not None else self.target_path
        self.last_error = ''

        if os.geteuid() != 0:
            self.last_error = f'root permissions required to write {destination}'
            print(f"Error: Root permissions required to write to {destination}.", file=sys.stderr)
            return False

        try:
            # A backup lives in a user-writable directory, so treat it as
            # untrusted input: reject symlinks/non-regular files and bound size.
            data = self.user_config.safe_read_bytes(backup_file)
            if b'\x00' in data:
                self.last_error = f'{backup_file.name} contains NUL bytes'
                print(f"Error: Backup {self.last_error}.", file=sys.stderr)
                return False

            # /etc/default/grub is sourced by the distro's GRUB scripts, so
            # command substitution in live code is root code execution.  A
            # comment is inert, so it is not a reason to refuse the restore.
            bad_line = self._command_substitution_line(data)
            if bad_line is not None:
                self.last_error = (f'{backup_file.name} contains command '
                                   f'substitution on line {bad_line}; refusing to restore')
                print(f"Error: Backup {self.last_error}.", file=sys.stderr)
                return False

            # Atomic, symlink-safe replacement of the target.
            self.user_config.atomic_root_write(destination, data, mode=0o644)
            print(f"Success: Restored {backup_file.name} to {destination}")
            return True
        except (OSError, ValueError, RuntimeError) as e:
            # RuntimeError covers the directory-security checks in
            # UserConfigDir (a non-root-owned parent, a symlinked directory).
            # It is a user-triggered action, so report it in the UI instead of
            # letting it escape curses as a traceback.
            self.last_error = f'{e}'
            print(f"Error restoring backup {backup_file} to {destination}: {e}", file=sys.stderr)
            return False
    # -----------------------------------------------------------------------

    def _unlink_backup(self, name: str) -> bool:
        """Remove one backup file, reporting a failure without aborting."""
        try:
            os.unlink(self.config_dir / name)
        except OSError as e:
            print(f"Warning: could not remove {name}: {e}", file=sys.stderr)
            return False
        return True

    def _collapse_adjacent_resync(self, previous: list, data: bytes) -> list:
        """Remove the adjacent same-content ``RESYNC`` records.

        *previous* is the inventory as it stood before the new file was
        written, newest first.  Only an unbroken run of ``RESYNC`` files that
        hold *data* is removed: a tagged record of the same content still says
        what changed and is left alone, and stopping at the first different
        record keeps the rule "no two adjacent ``RESYNC`` files of the same
        content".  The comparison is on bytes, never on the six hex digits --
        six digits can collide, and deleting a file that held different
        content would lose it.
        """
        removed = []
        for path in previous:
            if self.tag_from_name(path.name) != RESYNC_TAG:
                break
            if not self._holds(path, data):
                break
            if not self._unlink_backup(path.name):
                break
            removed.append(path)
        return removed

    def _sacrifice_follower(self, elder: str, follower: str) -> bool:
        """True when *follower* is the redundant copy that should go first.

        The elder must carry a descriptive tag, so there is something worth
        keeping, and the follower must be a ``RESYNC`` or an untagged record
        of exactly the same bytes.  Identity is byte equality.
        """
        if self.tag_from_name(elder) in ('', RESYNC_TAG):
            return False
        if self.tag_from_name(follower) not in ('', RESYNC_TAG):
            return False
        follower_data = self._content(self.config_dir / follower)
        if follower_data is None:
            return False
        return self._holds(self.config_dir / elder, follower_data)

    def purge_backups(self, keep: int = KEEP_BACKUPS) -> list:
        """Trim the inventory to *keep* files, oldest first.

        The oldest record is always preserved: it is the earliest state the
        user can return to.  Everything after it is fair game, with one
        preference.  When the oldest removable record carries a descriptive
        tag and the record immediately after it holds the same bytes and is a
        ``RESYNC`` (or untagged), that ``RESYNC`` is removed instead, so the
        tag which says *what* changed survives.  Only adjacent records are
        compared: an identical file further down the inventory does not save
        an older one.

        The loop stops the moment the inventory is down to *keep* entries, so
        a purge never deletes more than it must.  Returns the removed names; a
        file that cannot be deleted is reported and skipped.
        """
        keep = max(int(keep), 1)
        alive = sorted(self.get_backups())
        removed: list = []
        if len(alive) <= keep:
            return removed
        before = len(alive)

        while len(alive) > keep and len(alive) > 1:
            # Index 1 is the oldest record that is not the protected eldest.
            while (len(alive) > keep and len(alive) > 2
                   and self._sacrifice_follower(alive[1], alive[2])):
                name = alive.pop(2)
                if self._unlink_backup(name):
                    removed.append(name)
            if len(alive) > keep:
                name = alive.pop(1)
                if self._unlink_backup(name):
                    removed.append(name)

        if removed:
            print(f'Purge: {before} -> {len(alive)} backups.')
        return removed

    def create_backup(self, tag: Optional[str] = None,
                      file_to_backup: Optional[Path] = None) -> Optional[Path]:
        """Record the content of *file_to_backup* as a backup of the target.

        *tag* is ``None`` when nothing could classify the change; the name
        then carries only the timestamp and checksum.  Identical content is
        not suppressed while the inventory is small; instead a new ``RESYNC``
        removes the adjacent same-content ``RESYNC`` it replaces, and
        :meth:`purge_backups` caps the directory.
        """
        target = file_to_backup if file_to_backup is not None else self.target_path

        if not target.exists():
            print(f"Error: Target file {target} does not exist. Skipping backup.", file=sys.stderr)
            return None

        try:
            # Read the root-owned source, then install the backup with an
            # atomic user-owned write.  Never open a path inside the user's
            # directory as root.
            data = self.user_config.safe_read_bytes(target)
        except (OSError, ValueError) as e:
            print(f"Error reading {target} for backup: {e}", file=sys.stderr)
            return None

        checksum = hashlib.sha256(data).hexdigest()[:CHK_LEN].upper()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        suffix = f'.{tag}' if tag else ''
        new_filename = f"{timestamp}-s{checksum}{suffix}.bak"
        new_backup_path = self.config_dir / new_filename

        if os.path.lexists(new_backup_path):
            # Same second and same tag.  Only a no-op when the bytes agree;
            # otherwise a rename would silently destroy the earlier file.
            if self._holds(new_backup_path, data):
                print(f"Info: {new_backup_path.name} already holds this content.")
                return new_backup_path
            print(f"Error: {new_backup_path.name} already exists with different "
                  "content; not overwriting it.", file=sys.stderr)
            return None

        # The inventory as it stands now, newest first, taken before the write
        # so the new file can never be compared with itself.
        previous = sorted(self.get_backups().values(), key=self.sort_key,
                          reverse=True)

        try:
            self.user_config.atomic_user_write(new_backup_path, data, mode=0o644)
        except (OSError, ValueError) as e:
            print(f"Error creating backup file {new_filename}: {e}", file=sys.stderr)
            return None

        # Drop the redundant neighbour only after the new file exists, so an
        # interrupted run cannot leave the user with neither.
        if tag == RESYNC_TAG:
            self._collapse_adjacent_resync(previous, data)

        print(f"Success: Created new backup: {new_backup_path.name}")
        return new_backup_path
