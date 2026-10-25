#!/usr/bin/env python3
""" TBD"""
# pylint: disable=line-too-long,invalid-name,broad-exception-caught
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
USER_CONFIG = UserConfigDir.get_singleton("grub-wiz")
GRUB_CONFIG_DIR = USER_CONFIG.user_state_dir

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

        # Use provided user_config or get singleton
        self.user_config = user_config if user_config else USER_CONFIG
        self.config_dir = self.user_config.user_state_dir

    # --- calc_checksum, get_backups, and restore_backup remain the same ---
    # (Leaving these out for brevity in the response, but they are included in the full file block)

    def calc_checksum(self, source: Union[Path, str]) -> str:
        """ TBD """
        content = b''

        if isinstance(source, Path):
            if not source.exists():
                return ""
            try:
                content = source.read_bytes()
            except Exception:
                # print(f"Error reading file {source} for checksum: {e}", file=sys.stderr)
                return ""
        elif isinstance(source, str):
            content = source.encode('utf-8')
        else:
            raise TypeError("Source must be a Path or a string.")

        return hashlib.sha256(content).hexdigest()[:8].upper()


    def get_backups(self) -> Dict[str, Path]:
        """ TBD """
        backups: Dict[str, Path] = {}
        # Do not follow symlinks: a link must never be treated as a backup.
        with os.scandir(self.config_dir) as entries:
            for entry in entries:
                if not entry.is_file(follow_symlinks=False):
                    continue
                match = BACKUP_FILENAME_PATTERN.search(entry.name)
                if match:
                    checksum = match.group(2).upper()
                    backups[checksum] = self.config_dir / entry.name
        return backups

    def restore_backup(self, backup_file: Path, dest_path: Optional[Path] = None) -> bool:
        """ TBD """
        destination = dest_path if dest_path is not None else self.target_path

        if os.geteuid() != 0:
            print(f"Error: Root permissions required to write to {destination}.", file=sys.stderr)
            return False

        try:
            # A backup lives in a user-writable directory, so treat it as
            # untrusted input: reject symlinks/non-regular files and bound size.
            data = self.user_config.safe_read_bytes(backup_file)
            if b'\x00' in data:
                print(f"Error: Backup {backup_file.name} contains NUL bytes.", file=sys.stderr)
                return False

            # /etc/default/grub is sourced by the distro's GRUB scripts, so a
            # restored file containing command substitution is root code
            # execution.  A backup is user-writable input; refuse it.
            if b'$(' in data or b'`' in data:
                print(f"Error: Backup {backup_file.name} contains command substitution; "
                      "refusing to restore.", file=sys.stderr)
                return False

            # Atomic, symlink-safe replacement of the target.
            self.user_config.atomic_root_write(destination, data, mode=0o644)
            print(f"Success: Restored {backup_file.name} to {destination}")
            return True
        except Exception as e:
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

        existing_backups = self.get_backups()
        if current_checksum in existing_backups:
            print(f"Info: File is identical to existing backup: {existing_backups[current_checksum].name}. Skipping new backup.")
            return existing_backups[current_checksum]

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        new_filename = f"{timestamp}-{current_checksum}.{tag}.bak"
        new_backup_path = self.config_dir / new_filename

        try:
            # Read the root-owned source, then install the backup with an
            # atomic user-owned write.  Never open a path inside the user's
            # directory as root.
            data = self.user_config.safe_read_bytes(target)
            self.user_config.atomic_user_write(new_backup_path, data, mode=0o644)
            existing_backups = self.get_backups()

            print(f"Success: Created new backup: {new_backup_path.name}")
            return new_backup_path
        except Exception as e:
            print(f"Error creating backup file {new_filename}: {e}", file=sys.stderr)
            return None
