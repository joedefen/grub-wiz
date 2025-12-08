#!/usr/bin/env python3 
import os
import sys
import shutil
import hashlib
import re
import pwd # Needed for user lookup
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Union, List

# --- The Core Fix: Reliable User Information ---

def get_real_user_info(app_name: str) -> dict:
    """
    Identifies the real user who initiated the script, regardless of sudo settings, 
    by prioritizing os.getlogin().
    Returns: {'home': Path, 'uid': int, 'gid': int, 'config_dir': Path}
    """
    # 1. Try to get the login name of the terminal owner (most reliable non-root check)
    real_username = None
    try:
        real_username = os.getlogin()
    except OSError:
        # Fallback to SUDO_USER if getlogin fails (e.g., in some service contexts)
        real_username = os.environ.get('SUDO_USER')
        
    if real_username:
        try:
            # Get user info structure based on the determined username
            user_info = pwd.getpwnam(real_username)
            
            return {
                'home': Path(user_info.pw_dir),
                'uid': user_info.pw_uid,
                'gid': user_info.pw_gid,
                'config_dir': Path(user_info.pw_dir) / ".config" / app_name
            }
        except KeyError:
            # User lookup failed (e.g., deleted account or bad SUDO_USER)
            pass 

    # 2. Default to the current effective user's information (usually 'root' if running as root)
    # This acts as a final fallback, using the current home directory and effective UIDs.
    return {
        'home': Path.home(),
        'uid': os.geteuid(),
        'gid': os.getegid(),
        'config_dir': Path.home() / ".config" / app_name
    }


# --- Constants ---

GRUB_DEFAULT_PATH = Path("/etc/default/grub")
USER_INFO = get_real_user_info("grub-wiz")
GRUB_CONFIG_DIR = USER_INFO['config_dir']

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
    
    def __init__(self, target_path: Path = GRUB_DEFAULT_PATH, config_dir: Path = GRUB_CONFIG_DIR, user_info: dict = USER_INFO):
        self.target_path = target_path
        self.config_dir = config_dir
        self.target_uid = user_info['uid']
        self.target_gid = user_info['gid']
        
        # Ensure the config directory exists upon instantiation
        self._ensure_config_dir()

    def _ensure_config_dir(self):
        """
        Ensures the backup directory exists and is owned by the real user.
        """
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            # Ensure the directory is owned by the real user so they can manage backups later
            if os.geteuid() == 0: # Only change ownership if running as root
                os.chown(self.config_dir, self.target_uid, self.target_gid)
            
        except Exception as e:
            print(f"Error: Could not ensure backup directory {self.config_dir} exists: {e}", file=sys.stderr)
            sys.exit(1)

    # --- calc_checksum, get_backups, and restore_backup remain the same ---
    # (Leaving these out for brevity in the response, but they are included in the full file block)

    def calc_checksum(self, source: Union[Path, str]) -> str:
        # ... (implementation from previous response) ...
        content = b''
        
        if isinstance(source, Path):
            if not source.exists():
                return ""
            try:
                content = source.read_bytes()
            except Exception as e:
                # print(f"Error reading file {source} for checksum: {e}", file=sys.stderr)
                return ""
        elif isinstance(source, str):
            content = source.encode('utf-8')
        else:
            raise TypeError("Source must be a Path or a string.")

        return hashlib.sha256(content).hexdigest()[:8].upper()


    def get_backups(self) -> Dict[str, Path]:
        backups: Dict[str, Path] = {}
        for file_path in self.config_dir.iterdir():
            match = BACKUP_FILENAME_PATTERN.search(file_path.name)
            if match:
                checksum = match.group(2).upper()
                backups[checksum] = file_path
        return backups

    def restore_backup(self, backup_file: Path, dest_path: Optional[Path] = None) -> bool:
        destination = dest_path if dest_path is not None else self.target_path
        
        if os.geteuid() != 0:
            print(f"Error: Root permissions required to write to {destination}.", file=sys.stderr)
            return False

        if not backup_file.exists():
            print(f"Error: Backup file {backup_file} not found.", file=sys.stderr)
            return False

        try:
            shutil.copy2(backup_file, destination)
            os.chmod(destination, 0o644)

            print(f"Success: Restored {backup_file.name} to {destination}")
            return True
        except Exception as e:
            print(f"Error restoring backup to {destination}: {e}", file=sys.stderr)
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
            # Copy the file to the backup location (done as root)
            shutil.copy2(target, new_backup_path)
            
            # --- CRITICAL FIX: Change ownership to the real user ---
            # Only required if we are running as root (os.geteuid() == 0)
            if os.geteuid() == 0:
                os.chown(new_backup_path, self.target_uid, self.target_gid)
            # -----------------------------------------------------

            print(f"Success: Created new backup: {new_backup_path.name}")
            return new_backup_path
        except Exception as e:
            print(f"Error creating backup file {new_filename}: {e}", file=sys.stderr)
            return None
