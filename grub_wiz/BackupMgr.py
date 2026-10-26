#!/usr/bin/env python3
"""Create, list, restore, and delete backups of ``/etc/default/grub``.

Backups are owned by the invoking user and live in the user state
directory.  Files read from that directory are treated as untrusted input;
writes to the root-owned target go through the symlink-safe atomic helpers
in :mod:`grub_wiz.UserConfigDir`.
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

# Regex pattern for identifying backup files: YYYYMMDD-HHMMSS-{CHECKSUM}.{TAG}.bak
BACKUP_FILENAME_PATTERN = re.compile(
    r"(\d{8}-\d{6})-([0-9a-fA-F]{8})\.([a-zA-Z0-9_-]+)\.bak$"
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
        """Return the first 8 hex digits of the SHA-256 of a file or string.

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

        return hashlib.sha256(content).hexdigest()[:8].upper()


    @staticmethod
    def checksum_from_name(name: str) -> str:
        """Return the checksum encoded in a backup filename, or ''.

        A filename is the identity of a backup once it is on disk.  The
        checksum component is still useful for best-effort duplicate
        detection, but it is not a unique key: two tags may share content.
        """
        match = BACKUP_FILENAME_PATTERN.search(name)
        return match.group(2).upper() if match else ''

    def get_backups(self) -> Dict[str, Path]:
        """Return every backup file, keyed by its unique filename.

        Directory entries already have unique names, so keying by filename
        exposes the complete inventory.  Two files with identical content but
        different tags are both returned; ``create_backup()`` prevents new
        duplicates on a best-effort basis and never hides an existing file.
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

    def find_backup_with_checksum(self, checksum: str) -> Optional[Path]:
        """Return an existing backup whose filename carries *checksum*.

        Used only for best-effort duplicate prevention in
        ``create_backup()``; filename identity decides what is displayed.
        """
        wanted = checksum.upper()
        for name, path in self.get_backups().items():
            if self.checksum_from_name(name) == wanted:
                return path
        return None

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


    def create_backup(self, tag: str, file_to_backup: Optional[Path] = None, checksum: Optional[str] = None) -> Optional[Path]:
        """
        Creates a new backup file for the target path and sets ownership to the real user.
        """
        target = file_to_backup if file_to_backup is not None else self.target_path

        if not target.exists():
            print(f"Error: Target file {target} does not exist. Skipping backup.", file=sys.stderr)
            return None

        current_checksum = checksum if checksum else self.calc_checksum(target)
        if not current_checksum:
            return None

        existing = self.find_backup_with_checksum(current_checksum)
        if existing is not None:
            print(f"Info: File is identical to existing backup: {existing.name}. Skipping new backup.")
            return existing

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        new_filename = f"{timestamp}-{current_checksum}.{tag}.bak"
        new_backup_path = self.config_dir / new_filename

        try:
            # Read the root-owned source, then install the backup with an
            # atomic user-owned write.  Never open a path inside the user's
            # directory as root.
            data = self.user_config.safe_read_bytes(target)
            self.user_config.atomic_user_write(new_backup_path, data, mode=0o644)

            print(f"Success: Created new backup: {new_backup_path.name}")
            return new_backup_path
        except (OSError, ValueError) as e:
            print(f"Error creating backup file {new_filename}: {e}", file=sys.stderr)
            return None
