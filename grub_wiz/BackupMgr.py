#!/usr/bin/env python3
"""Create, list, restore, and delete backups of ``/etc/default/grub``"""
import hashlib
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from .DistroVars import DEFAULT_ETC_GRUB
from .UserConfigDir import UserConfigDir

# --- Constants ---

GRUB_DEFAULT_PATH = Path(DEFAULT_ETC_GRUB)
CHK_LEN = 6
KEEP_BACKUPS = 24
BASELINE_TAG = 'BASELINE'
RESYNC_TAG = 'RESYNC'

# Recognizes both current legacy forms.
BACKUP_FILENAME_PATTERN = re.compile(
    r'^(?P<stamp>\d{8}-\d{6})-'
    r'(?:s(?P<chk6>[0-9A-F]{6})(?:\.(?P<tag6>[A-Za-z0-9_+~-]+))?'
    r'|(?P<chk8>[0-9A-Fa-f]{8})\.(?P<tag8>[A-Za-z0-9_-]+))'
    r'\.bak$'
)

class BackupMgr:
    """
    Manages backups for the /etc/default/grub configuration file.
    Backups are stored in the real user's ~/.config/grub-wiz/ location.
    """

    def __init__(self, target_path: Path = GRUB_DEFAULT_PATH, user_config=None):
        self.target_path = Path(target_path)

        # Resolve the user state directory lazily.
        self.user_config = (user_config if user_config is not None
                            else UserConfigDir.get_singleton("grub-wiz"))
        self.config_dir = self.user_config.user_state_dir
        self.last_error: str = ''

    def calc_checksum(self, source: Path | str) -> str:
        """Return the first 6 hex digits of the SHA-256 of a file or string or ``''``"""
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
        """Return the checksum encoded in a backup filename, or ''."""
        match = BACKUP_FILENAME_PATTERN.search(name)
        if not match:
            return ''
        return (match.group('chk6') or match.group('chk8') or '').upper()

    @staticmethod
    def checksum_matches(backup_checksum: str, current_checksum: str) -> bool:
        """True when *backup_checksum* can identify *current_checksum*."""
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
        """Return *name* with its tag replaced or added."""
        match = BACKUP_FILENAME_PATTERN.search(name)
        if not match or not tag:
            return name
        stamp = match.group('stamp')
        if match.group('chk6'):
            return f'{stamp}-s{match.group("chk6")}.{tag}.bak'
        return f'{stamp}-{match.group("chk8")}.{tag}.bak'

    def get_backups(self) -> dict[str, Path]:
        """Return every backup file, keyed by its unique filename."""
        backups: dict[str, Path] = {}
        # Do not follow symlinks
        with os.scandir(self.config_dir) as entries:
            for entry in entries:
                if not entry.is_file(follow_symlinks=False):
                    continue
                if BACKUP_FILENAME_PATTERN.search(entry.name):
                    backups[entry.name] = self.config_dir / entry.name
        return backups

    def sort_key(self, path: Path):
        """Return a key that orders backups oldest first."""
        return Path(path).name

    def _content(self, path: Path) -> bytes | None:
        """Return *path*'s bytes, or ``None`` when it cannot be read."""
        try:
            return self.user_config.safe_read_bytes(path)
        except (OSError, ValueError):
            return None

    def _holds(self, path: Path, data: bytes) -> bool:
        """True when *path* can be read and holds exactly *data*."""
        return self._content(path) == data

    @staticmethod
    def _command_substitution_line(data: bytes) -> int | None:
        """Return the 1-based line of live command substitution, or ``None``."""
        text = data.decode('utf-8', errors='replace')
        for line_number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            if '`' in stripped or '$(' in stripped:
                return line_number
        return None

    def restore_backup(self, backup_file: Path, dest_path: Path | None = None) -> bool:
        """Restore *backup_file* over *dest_path* (default: the target path)."""
        destination = dest_path if dest_path is not None else self.target_path
        self.last_error = ''

        if os.geteuid() != 0:
            self.last_error = f'root permissions required to write {destination}'
            print(f"Error: Root permissions required to write to {destination}.", file=sys.stderr)
            return False

        try:
            data = self.user_config.safe_read_bytes(backup_file)
            if b'\x00' in data:
                self.last_error = f'{backup_file.name} contains NUL bytes'
                print(f"Error: Backup {self.last_error}.", file=sys.stderr)
                return False

            bad_line = self._command_substitution_line(data)
            if bad_line is not None:
                self.last_error = (f'{backup_file.name} contains command '
                                   f'substitution on line {bad_line}; refusing to restore')
                print(f"Error: Backup {self.last_error}.", file=sys.stderr)
                return False

            self.user_config.atomic_root_write(destination, data, mode=0o644)
            print(f"Success: Restored {backup_file.name} to {destination}")
            return True
        except (OSError, ValueError, RuntimeError) as e:
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
        """Remove the adjacent same-content ``RESYNC`` records."""
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
        """True when *follower* is the redundant copy that should go first."""
        if self.tag_from_name(elder) in ('', RESYNC_TAG):
            return False
        if self.tag_from_name(follower) not in ('', RESYNC_TAG):
            return False
        follower_data = self._content(self.config_dir / follower)
        if follower_data is None:
            return False
        return self._holds(self.config_dir / elder, follower_data)

    def purge_backups(self, keep: int = KEEP_BACKUPS) -> list:
        """Trim the inventory to *keep* files, oldest first."""
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

    def create_backup(self, tag: str | None = None,
                      file_to_backup: Path | None = None) -> Path | None:
        """Record the content of *file_to_backup* as a backup of the target."""
        target = file_to_backup if file_to_backup is not None else self.target_path

        if not target.exists():
            print(f"Error: Target file {target} does not exist. Skipping backup.", file=sys.stderr)
            return None

        try:
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
            if self._holds(new_backup_path, data):
                print(f"Info: {new_backup_path.name} already holds this content.")
                return new_backup_path
            print(f"Error: {new_backup_path.name} already exists with different "
                  "content; not overwriting it.", file=sys.stderr)
            return None

        previous = sorted(self.get_backups().values(), key=self.sort_key,
                          reverse=True)

        try:
            self.user_config.atomic_user_write(new_backup_path, data, mode=0o644)
        except (OSError, ValueError) as e:
            print(f"Error creating backup file {new_filename}: {e}", file=sys.stderr)
            return None

        if tag == RESYNC_TAG:
            self._collapse_adjacent_resync(previous, data)

        print(f"Success: Created new backup: {new_backup_path.name}")
        return new_backup_path
