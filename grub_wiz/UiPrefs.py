#!/usr/bin/env python3
"""Persistent user-interface choices that are not warnings state.

Only one thing lives here today: the colour theme chosen in the theme picker.
It is deliberately separate from ``WarnDB``: that file is reconciled against
validator output on every start, which would be the wrong home for a value the
user sets by hand and expects to survive untouched.

The file is user-owned state, so it lives in ``~/.config/grub-wiz`` and every
write goes through ``UserConfigDir.atomic_user_write()`` (symlink-safe, atomic
replace).  A hand-edited or corrupt file is ignored rather than fatal: a
cosmetic preference must never keep the editor from starting.
"""

import io
from pathlib import Path
from typing import Any, Optional

from ruamel.yaml import YAML, YAMLError

from .UserConfigDir import UserConfigDir

yaml = YAML()
yaml.default_flow_style = False


class UiPrefs:
    """Small key/value store for interface choices, backed by a YAML file."""

    def __init__(self, filename: str = 'ui-prefs.yaml'):
        self.user_config = UserConfigDir.get_singleton('grub-wiz')
        self.yaml_path: Path = Path(self.user_config.user_state_dir) / filename
        self.data: dict = {}
        self.refresh()

    def refresh(self) -> bool:
        """(Re)read the file.  A missing file is a normal first run."""
        try:
            text = self.user_config.safe_read_text(self.yaml_path)
        except FileNotFoundError:
            self.data = {}
            return True
        except (IOError, OSError) as exc:
            print(f'Warning: refusing to read {self.yaml_path.name}: {exc}')
            self.data = {}
            return True

        try:
            loaded = yaml.load(io.StringIO(text))
        except YAMLError as exc:
            print(f'Warning: failed to read {self.yaml_path.name}: {exc}')
            self.data = {}
            return True

        if loaded is None:
            self.data = {}
        elif isinstance(loaded, dict):
            self.data = dict(loaded)
        else:
            # A hand edit can put a list or a scalar at the top level; treating
            # that as "no preferences" is safer than raising on every start.
            print(f'Warning: {self.yaml_path.name} is not a mapping; ignoring it')
            self.data = {}
        return True

    def get(self, key: str, default: Any = None) -> Any:
        """Return the stored value for *key*, or *default*."""
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> bool:
        """Store *key* and persist it; return False when the write failed.

        The in-memory value is kept either way, so a read-only config directory
        degrades to "works for this session, not remembered".
        """
        if self.data.get(key) == value:
            return True
        self.data[key] = value
        return self._write()

    def _write(self) -> bool:
        stream = io.StringIO()
        try:
            yaml.dump(dict(self.data), stream)
            self.user_config.atomic_user_write(
                self.yaml_path, stream.getvalue(), mode=0o600)
        except (IOError, OSError, YAMLError) as exc:
            print(f'Warning: could not save {self.yaml_path.name}: {exc}')
            return False
        return True

    def delete(self) -> bool:
        """Remove the preferences file (used by ``--factory-reset``)."""
        try:
            self.yaml_path.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            print(f'Warning: could not delete {self.yaml_path.name}: {exc}')
            return False
        self.data = {}
        return True

    def as_dict(self) -> dict:
        """Return a copy of the stored preferences."""
        return dict(self.data)


def get_pref(key: str, default: Optional[Any] = None) -> Any:
    """Convenience read for callers that do not need the object."""
    return UiPrefs().get(key, default)
