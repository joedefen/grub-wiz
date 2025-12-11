#!/usr/bin/env python3

import yaml
import os
import stat
from pathlib import Path
from typing import Set, Dict, Any, Optional

# --- Assume these constants are defined elsewhere in your project ---
# GRUB_DEFAULT_PATH = Path('/etc/default/grub')
# GRUB_CONFIG_DIR = Path('/home/user/.config/grub-wiz') # The real user's config directory
# USER_INFO = {'uid': 1000, 'gid': 1000} # Real user's UID/GID

DEFAULT HIDES:
    GRUB_HIDDEN_TIMEOUT (deprecated/confusing)
    GRUB_RECORDFAIL_TIMEOUT (Ubuntu-specific)
    GRUB_DISABLE_SUBMENU (rarely changed)
    GRUB_DISTRIBUTOR (cosmetic)
    GRUB_GFXMODE (advanced)
    GRUB_GFXPAYLOAD_LINUX (very advanced)
    GRUB_VIDEO_BACKEND (troubleshooting only)
    GRUB_INIT_TUNE (novelty)
    GRUB_ENABLE_CRYPTODISK (specialized)
    GRUB_TERMINAL_INPUT (advanced)
    GRUB_DISABLE_LINUX_UUID (rare)
    GRUB_CMDLINE_LINUX_RECOVERY (edge case)
    GRUB_DISABLE_LINUX_PARTUUID (rare)
    GRUB_TERMINAL_OUTPUT (server/serial)
    GRUB_SERIAL_COMMAND (server/serial)
    GRUB_PRELOAD_MODULES (server/troubleshooting)
    GRUB_BADRAM (rare hardware issue)
# ---

class BackupMgr:
    """
    Manages backups and provides user/directory context.
    (Placeholder class mirroring the structure you provided)
    """
    def __init__(self, target_path: Path, config_dir: Path, user_info: Dict[str, int]):
        self.target_path = target_path
        self.config_dir = config_dir
        self.target_uid = user_info['uid']
        self.target_gid = user_info['gid']

class WizHides:
    """
    Manages the persistent storage and state for hidden parameters and suppressed warnings.
    """
    
    def __init__(self, backup_manager: BackupMgr, filename: str = 'hidden-items.yaml'):
        """
        Initializes the class, creates the config directory if necessary, 
        and performs the initial read/refresh.
        """
        self.config_dir: Path = backup_manager.config_dir
        self.yaml_path: Path = self.config_dir / filename
        self.target_uid: int = backup_manager.target_uid
        self.target_gid: int = backup_manager.target_gid
        
        self.params: Set[str] = set()       # e.g., {'GRUB_DEFAULT'}
        self.warns: Set[str] = set()        # e.g., {'GRUB_DEFAULT.3'} (3 for ***)
        self.dirty_count: int = 0
        self.last_read_time: Optional[float] = None
        
        # Ensure directory exists and has correct permissions
        self._setup_config_dir()
        
        # Suck up the file on startup (initial refresh)
        self.refresh()

    def _setup_config_dir(self):
        """Creates the config directory and sets ownership/permissions."""
        if not self.config_dir.exists():
            try:
                # Create directory, setting permission to 0o700 (rwx for owner only)
                self.config_dir.mkdir(parents=True, mode=0o700)
                # Change ownership to the target user/group
                os.chown(self.config_dir, self.target_uid, self.target_gid)
            except OSError as e:
                print(f"Error setting up config directory {self.config_dir}: {e}")
                # Failure here is critical, but we let the read/write methods handle file errors

    def refresh(self):
        """Reads the hidden items from the YAML file, clearing the current state on failure."""
        self.params.clear()
        self.warns.clear()
        self.last_read_time = None
        self.dirty_count = 0 # Assume file state is clean
        
        if not self.yaml_path.exists():
            return
            
        try:
            with self.yaml_path.open('r') as f:
                data: Dict[str, Any] = yaml.safe_load(f) or {}
                
            # Safely cast list data to sets
            self.params.update(set(data.get('params', [])))
            self.warns.update(set(data.get('warns', [])))
            
            # Record file modification time
            self.last_read_time = self.yaml_path.stat().st_mtime
            
        except (IOError, yaml.YAMLError) as e:
            # Any failure leads to empty sets, allowing the application to continue.
            print(f"Warning: Failed to read hidden-items.yaml: {e}")

    def write_if_dirty(self) -> bool:
        """Writes the current hidden state to disk if the dirty count is > 0."""
        if self.dirty_count == 0:
            return False
            
        data = {
            'params': sorted(list(self.params)),
            'warns': sorted(list(self.warns))
        }
        
        try:
            # 1. Write the file
            with self.yaml_path.open('w') as f:
                yaml.safe_dump(data, f, default_flow_style=False)
            
            # 2. Correct ownership and permissions (crucial when running as root)
            # Permission 0o600 (rw for owner only) is typical for config files
            os.chown(self.yaml_path, self.target_uid, self.target_gid)
            os.chmod(self.yaml_path, 0o600) 
            
            # 3. Update state
            self.dirty_count = 0
            self.last_read_time = self.yaml_path.stat().st_mtime
            return True
            
        except OSError as e:
            print(f"Error writing or setting permissions on hidden-items.yaml: {e}")
            return False

    def hide_param(self, name: str):
        """Hides a parameter by name (e.g., 'GRUB_DEFAULT')."""
        if name not in self.params:
            self.params.add(name)
            self.dirty_count += 1

    def unhide_param(self, name: str):
        """Unhides a parameter by name."""
        if name in self.params:
            self.params.remove(name)
            self.dirty_count += 1

    def hide_warn(self, composite_id: str):
        """Hides a warning by composite ID (e.g., 'GRUB_DEFAULT.3')."""
        if composite_id not in self.warns:
            self.warns.add(composite_id)
            self.dirty_count += 1

    def unhide_warn(self, composite_id: str):
        """Unhides a warning by composite ID."""
        if composite_id in self.warns:
            self.warns.remove(composite_id)
            self.dirty_count += 1
            
    def is_hidden_param(self, name: str) -> bool:
        """Checks if a parameter should be hidden."""
        return name in self.params

    def is_hidden_warn(self, composite_id: str) -> bool:
        """Checks if a warning should be suppressed."""
        return composite_id in self.warns

    def is_dirty(self) -> bool:
        """Indicates if there are unsaved changes."""
        return self.dirty_count > 0

    def get_last_read_time(self) -> Optional[float]:
        """Returns the last file modification time when the file was read."""
        return self.last_read_time
