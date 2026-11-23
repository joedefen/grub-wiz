#!/usr/bin/env python3
"""Persistent warning severities and suppressed-warning state.

``all_warnings`` records every warning key with its severity (1-4),
while ``inhibited`` records the keys the user asked to hide.
Both are reconciled against the live validator output so edits, orphaned inhibits,
and grading changes survive a restart without the database going stale.
"""

import io
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, YAMLError

from .UserConfigDir import UserConfigDir

yaml = YAML()
yaml.default_flow_style = False


class WarnDB:
    """
    Manages the persistent storage and state for the warnings database.
    Stores all warning info with severity levels and
    tracks which warnings are suppressed (inhibited).
    """

    def __init__(self, param_cfg, filename: str = 'warn-db.yaml'):
        """
        Initializes the class, creates the config directory if necessary,
        and performs the initial read/refresh.

        Args:
         *  user_config: UserConfigDir instance (uses singleton if not provided)
         *  filename: Name of the YAML file to store warning database
        """
        self.user_config = UserConfigDir.get_singleton("grub-wiz")
        # User preference data: belongs to the invoking user.
        self.config_dir: Path = self.user_config.user_state_dir
        self.yaml_path: Path = self.config_dir / filename
        self.param_cfg = param_cfg # has out-of-box state

        self.inhibits: set[str] = set()   # Suppressed/inhibited warnings (keys)
        self.all_info: dict[str, int] = {}  # All warning info: key -> severity (1-4)
        self.dirty_count: int = 0
        self.last_read_time: float | None = None
        self.refresh()

    def refresh(self):
        """
        Reads the warning database from the YAML file.
        If file doesn't exist, starts with empty state (normal on first run).

        Supports both old format ('warns' list) and new format
        ('all_warnings' dict + 'inhibited' list) for backward compatibility.
        """
        self.last_read_time = None
        self.dirty_count = 0 # Assume file state is clean

        try:
            text = self.user_config.safe_read_text(self.yaml_path)
        except FileNotFoundError:
            self.inhibits.clear()
            self.all_info.clear()
            return True
        except OSError as e:
            print(f"Warning: Refusing to read {self.yaml_path.name}: {e}")
            self.inhibits.clear()
            self.all_info.clear()
            return True

        try:
            data: dict[str, Any] = yaml.load(io.StringIO(text)) or {}
            if not isinstance(data, dict):
                print(f"Warning: {self.yaml_path.name} is not a mapping; ignoring it")
                self.inhibits.clear()
                self.all_info.clear()
                return True

            if 'inhibited' in data: # New format: 'all_warnings' + 'inhibited'
                inhibited = data.get('inhibited')
                all_warnings = data.get('all_warnings')
                self.inhibits = (set(inhibited)
                                 if isinstance(inhibited, (list, tuple, set))
                                 else set())
                self.all_info = (dict(all_warnings)
                                 if isinstance(all_warnings, dict) else {})
            else: # Old format: 'warns' list (backward compatibility)
                warns = data.get('warns')
                self.inhibits = (set(warns)
                                 if isinstance(warns, (list, tuple, set))
                                 else set())
                # all_info will be populated by audit_info()

            self.last_read_time = self.yaml_path.stat().st_mtime
            return True

        except (OSError, YAMLError) as e:
            print(f"Warning: Failed to read {self.yaml_path.name}: {e}")
            self.inhibits.clear()
            self.all_info.clear()
            return True

    def write_if_dirty(self) -> bool:
        """Writes the current warning database to disk if dirty count is > 0."""
        if self.dirty_count == 0:
            return False

        data = {
            'all_warnings': dict(sorted(self.all_info.items())),
            'inhibited': sorted(list(self.inhibits))
        }

        try:
            stream = io.StringIO()
            yaml.dump(data, stream)
            self.user_config.atomic_user_write(
                self.yaml_path, stream.getvalue(), mode=0o600)

            self.dirty_count = 0
            self.last_read_time = self.yaml_path.stat().st_mtime
            return True

        except OSError as e:
            print(f"Error writing or setting permissions on {self.yaml_path.name}: {e}")
            return False

    def inhibit(self, composite_id: str, hide: bool):
        """Hides a warning by composite ID (e.g., 'GRUB_DEFAULT.3')."""
        hidden = self.is_inhibit(composite_id)
        if hide and not hidden:
            self.inhibits.add(composite_id)
            self.dirty_count += 1
        elif not hide and hidden:
            self.inhibits.remove(composite_id)
            self.dirty_count += 1

    @staticmethod
    def make_key(param_name: str, message: str) -> str:
        """Construct a warning key from parameter name and message.

        Args:
         *  param_name: The GRUB parameter name (e.g., 'GRUB_TIMEOUT')
         *  message: The warning message (e.g., 'when 0, TIMEOUT_STYLE cannot be "hidden"')

        Returns: Composite key string (e.g., 'GRUB_TIMEOUT: when 0, TIMEOUT_STYLE cannot be "hidden"')
        """
        return f'{param_name}: {message}'

    def is_inhibit(self, composite_id: str) -> bool:
        """Checks if a warning should be suppressed."""
        return composite_id in self.inhibits

    def audit_info(self, all_warn_info: dict):
        """Update the warning database with current validation info.

        Safe to call repeatedly: every call reconciles ``all_info``
        and the suppressed set with the supplied snapshot,
        so warnings that appear, disappear,
        or change severity after a parameter edit are reflected immediately.
        Calling it again with the same snapshot is a no-op.

        Args:
          * all_warn_info: Dict mapping warning keys to severity levels (1-4)

        Actions:
        - Updates all_info with current warnings and severities
        - Removes orphaned keys from suppressed warnings list
        - Updates severity if changed
        """
        new_all_info = {k: all_warn_info[k] for k in sorted(all_warn_info)}

        if new_all_info != self.all_info:
            self.dirty_count += 1

        self.all_info = new_all_info

        orphans = []
        for key in self.inhibits:
            if key not in all_warn_info:
                orphans.append(key)

        for key in orphans:
            self.inhibits.discard(key)
            self.dirty_count += 1

    def is_dirty(self) -> bool:
        """Indicates if there are unsaved changes."""
        return self.dirty_count > 0

    def get_last_read_time(self) -> float | None:
        """Returns the last file modification time when the file was read."""
        return self.last_read_time
