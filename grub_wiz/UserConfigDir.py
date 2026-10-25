#!/usr/bin/env python3
"""
Singleton for locating mutable state and writing it safely.

The tool normally runs as root (via sudo) but is invoked by an unprivileged
user.  Mutable state is therefore split by ownership:

    user_state_dir    ~/.config/grub-wiz   0700, owned by the invoking user
                      Backups, warning preferences and the user's custom
                      config.  Root may write here, but every write goes
                      through ``atomic_user_write()`` so a pre-planted
                      symlink can never redirect a root write.

    system_state_dir  /var/lib/grub-wiz    0700, root:root
                      Machine-wide, root-owned state such as the parameter
                      discovery cache and the rollback copy.  The whole
                      parent chain is root-owned, so it cannot be swapped
                      out by an unprivileged user.

    run_dir           /run/grub-wiz        0700, root:root
                      Ephemeral session state (locks, scratch).

Why the split: a root-owned directory *inside* a user-owned parent is not a
security boundary, because the user can rename the directory and substitute a
symlink.  State that must be trusted lives under /var/lib or /run; state that
belongs to the user lives in their config directory and is written with
directory-fd based primitives that do not follow symlinks.
"""
# pylint: disable=broad-exception-caught,invalid-name

import os
import secrets
import stat
import sys
import pwd
from pathlib import Path
from typing import Optional, Union

# System locations for root-owned mutable state.
SYSTEM_STATE_ROOT = Path('/var/lib')
RUN_ROOT = Path('/run')

# Maximum size accepted when reading user-supplied state (1 MiB).
MAX_STATE_BYTES = 1024 * 1024

_OPEN_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class UserConfigDir:
    """
    Singleton that resolves state directories for the invoking user and
    provides symlink-safe read/write helpers.
    """

    singleton = None
    _instance: Optional['UserConfigDir'] = None

    def __new__(cls, app_name: str = "grub-wiz"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, app_name: str = "grub-wiz"):
        # Only initialize once (singleton pattern)
        if UserConfigDir.singleton:
            raise RuntimeError("Use UserConfigDir.get_singleton(), not constructor")
        UserConfigDir.singleton = self

        self.app_name = app_name
        self._detect_user()

        # User-owned, user-facing state.
        self.user_state_dir = self.home / ".config" / self.app_name
        self._ensure_dir(self.user_state_dir, mode=0o700,
                         uid=self.uid, gid=self.gid, label="user state",
                         must_be_root_owned=False)

        # Root-owned machine state and session scratch.
        self.system_state_dir = self._ensure_root_dir(
            SYSTEM_STATE_ROOT / self.app_name, fallback=self.user_state_dir / ".system")
        self.run_dir = self._ensure_root_dir(
            RUN_ROOT / self.app_name, fallback=self.user_state_dir / ".run")

    # ------------------------------------------------------------------
    # Construction / directory security
    # ------------------------------------------------------------------

    @staticmethod
    def get_singleton(app_name: str = 'grub-wiz'):
        """ Get or create the UserConfigDir singleton instance.
        Args:
            app_name: Application name for config directory
        Returns:
            UserConfigDir singleton instance
        """
        if not UserConfigDir.singleton:
            UserConfigDir.singleton = UserConfigDir(app_name)
        return UserConfigDir.singleton

    def _detect_user(self):
        """
        Identify the real user who initiated the script.

        SUDO_UID/SUDO_GID are the source of truth under sudo.  ``os.getlogin()``
        is only a last resort: in tmux, cron, containers and ``su`` it can be
        wrong or raise, and it can point at a different account than the one
        that owns the terminal.
        """
        euid = os.geteuid()
        pw_entry = None

        if euid == 0:
            sudo_uid = os.environ.get('SUDO_UID')
            sudo_gid = os.environ.get('SUDO_GID')
            if sudo_uid and sudo_uid.isdigit():
                try:
                    pw_entry = pwd.getpwuid(int(sudo_uid))
                except KeyError:
                    pw_entry = None
                if pw_entry is not None and sudo_gid and sudo_gid.isdigit():
                    # Honour the recorded gid even if it is not the login gid.
                    self.uid = pw_entry.pw_uid
                    self.gid = int(sudo_gid)
                elif pw_entry is not None:
                    self.uid = pw_entry.pw_uid
                    self.gid = pw_entry.pw_gid
        else:
            try:
                pw_entry = pwd.getpwuid(os.getuid())
            except KeyError:
                pw_entry = None

        if pw_entry is None:
            # Fall back to the login name, then to the effective user.
            name = None
            try:
                name = os.getlogin()
            except OSError:
                name = None
            if name:
                try:
                    pw_entry = pwd.getpwnam(name)
                except KeyError:
                    pw_entry = None

        if pw_entry is not None:
            home = Path(pw_entry.pw_dir or '/')
            if not home.is_absolute():
                home = Path.home()
            self.home = home
            self.uid = getattr(self, 'uid', pw_entry.pw_uid)
            self.gid = getattr(self, 'gid', pw_entry.pw_gid)
        else:
            self.home = Path.home()
            self.uid = os.getuid() if euid != 0 else 0
            self.gid = os.getgid() if euid != 0 else 0

    def _ensure_dir(self, path: Path, mode: int, uid: int, gid: int,
                    label: str, must_be_root_owned: bool, quiet: bool = False):
        """
        Create ``path`` if needed and verify it is a real directory.

        A pre-existing symlink is rejected rather than followed.  When
        ``must_be_root_owned`` is set, the directory must belong to uid 0.
        """
        try:
            path.mkdir(parents=True, exist_ok=True)
            st = os.lstat(path)
            # lstat() reports the link itself, so check S_ISLNK before
            # S_ISDIR: otherwise every symlink is misreported as "not a
            # directory" and the specific message below is unreachable.
            if stat.S_ISLNK(st.st_mode):
                raise RuntimeError(f"{label} path is a symlink: {path}")
            if not stat.S_ISDIR(st.st_mode):
                raise RuntimeError(f"{label} path is not a directory: {path}")
            if must_be_root_owned and st.st_uid != 0:
                raise RuntimeError(
                    f"{label} directory must be root-owned, found uid={st.st_uid}: {path}")

            os.chmod(path, mode)
            if os.geteuid() == 0:
                os.chown(path, uid, gid)
        except (OSError, RuntimeError) as e:
            if not quiet:
                print(f"Error: Could not prepare {label} directory {path}: {e}",
                      file=sys.stderr)
            raise

    def _ensure_root_dir(self, preferred: Path, fallback: Path) -> Path:
        """
        Prepare a root-owned directory.

        When running unprivileged (tests, ``--help``, linting) the system
        location is not writable.  Degrade to a per-user fallback rather than
        aborting; the fallback is never used for a privileged write.
        """
        try:
            self._ensure_dir(preferred, mode=0o700, uid=0, gid=0,
                             label="system state", must_be_root_owned=True,
                             quiet=(os.geteuid() != 0))
            return preferred
        except (OSError, RuntimeError):
            if os.geteuid() == 0:
                # Running as root: failing here is a real error, not a sandbox.
                raise
            self._ensure_dir(fallback, mode=0o700, uid=self.uid, gid=self.gid,
                             label="fallback state", must_be_root_owned=False)
            print(f"Warning: {preferred} unavailable; using {fallback}",
                  file=sys.stderr)
            return fallback

    @property
    def config_dir(self) -> Path:
        """Backward-compatible alias for the user-facing state directory."""
        return self.user_state_dir

    # ------------------------------------------------------------------
    # Low-level safe primitives
    # ------------------------------------------------------------------

    @staticmethod
    def _open_dir_fd(path: Path) -> int:
        """Open a directory without following a symlink in the final component."""
        return os.open(str(path), _OPEN_DIR_FLAGS)

    @staticmethod
    def _verify_trusted_parent(dir_fd: int, container: Path):
        st = os.fstat(dir_fd)
        if not stat.S_ISDIR(st.st_mode):
            raise RuntimeError(f"Not a directory: {container}")
        if os.geteuid() == 0 and st.st_uid != 0:
            raise RuntimeError(
                f"Refusing to write into non-root-owned directory: {container}")

    def atomic_write(self, path: Union[Path, str], data: Union[bytes, str],
                     mode: int = 0o644, uid: Optional[int] = None,
                     gid: Optional[int] = None, trusted_parent: bool = False) -> None:
        """
        Atomically replace ``path`` with ``data``.

        The temporary file is created with ``O_CREAT|O_EXCL|O_NOFOLLOW`` in the
        destination directory (via a directory fd), then installed with
        ``os.replace()``.  ``rename(2)`` does not follow a symlink in the final
        path component, so a pre-planted symlink is replaced rather than
        followed.  This is the only supported way to write under
        ``user_state_dir``.
        """
        path = Path(path)
        payload = data.encode('utf-8') if isinstance(data, str) else data

        dir_fd = self._open_dir_fd(path.parent)
        tmp_name = f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(6)}"
        tmp_fd = None
        try:
            if trusted_parent:
                self._verify_trusted_parent(dir_fd, path.parent)

            tmp_fd = os.open(
                tmp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                mode,
                dir_fd=dir_fd,
            )

            written = 0
            while written < len(payload):
                written += os.write(tmp_fd, payload[written:])

            os.fchmod(tmp_fd, mode)
            if os.geteuid() == 0 and uid is not None:
                os.fchown(tmp_fd, uid, gid if gid is not None else -1)

            os.fsync(tmp_fd)
            os.close(tmp_fd)
            tmp_fd = None

            os.replace(tmp_name, path.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
            try:
                os.fsync(dir_fd)
            except OSError:
                pass
        except (OSError, ValueError):
            if tmp_fd is not None:
                try:
                    os.close(tmp_fd)
                except OSError:
                    pass
            try:
                os.unlink(tmp_name, dir_fd=dir_fd)
            except OSError:
                pass
            raise
        finally:
            try:
                os.close(dir_fd)
            except OSError:
                pass

    def atomic_user_write(self, path: Union[Path, str], data: Union[bytes, str],
                          mode: int = 0o644) -> None:
        """Write user-facing state, owned by the invoking user."""
        path = Path(path)
        if path.parent != self.user_state_dir:
            raise ValueError(f"Refusing user-state write outside {self.user_state_dir}: {path}")
        self.atomic_write(path, data, mode=mode, uid=self.uid, gid=self.gid)

    def atomic_root_write(self, path: Union[Path, str], data: Union[bytes, str],
                          mode: int = 0o644) -> None:
        """Write root-owned state; requires a root-owned parent directory."""
        self.atomic_write(path, data, mode=mode, uid=0, gid=0, trusted_parent=True)

    @staticmethod
    def safe_read_bytes(path: Union[Path, str], max_bytes: int = MAX_STATE_BYTES) -> bytes:
        """
        Read a regular file without following a symlink.

        Raises ``OSError`` for symlinks (ELOOP), non-regular files, or files
        larger than ``max_bytes``.
        """
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise OSError(f"Not a regular file: {path}")
            if st.st_size > max_bytes:
                raise OSError(f"File too large ({st.st_size} > {max_bytes}): {path}")
            chunks = []
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
            return b''.join(chunks)
        finally:
            os.close(fd)

    @classmethod
    def safe_read_text(cls, path: Union[Path, str],
                       max_bytes: int = MAX_STATE_BYTES) -> str:
        return cls.safe_read_bytes(path, max_bytes=max_bytes).decode('utf-8', errors='strict')

    def staging_path(self, target: Union[Path, str]) -> Path:
        """
        Return a fresh same-directory staging path for ``target``.

        Same directory guarantees ``os.replace()`` is atomic (no EXDEV), and
        the unique name avoids colliding with a pre-existing entry.  Only use
        this in a root-owned directory such as ``/etc/default``.
        """
        target = Path(target)
        return target.parent / f".{target.name}.grub-wiz-{os.getpid()}-{secrets.token_hex(4)}"

    # ------------------------------------------------------------------
    # Backward-compatible helpers
    # ------------------------------------------------------------------

    def give_to_user(self, filepath: Path, mode: int = 0o644):
        """
        Set ownership and permissions on an existing file without following
        a symlink.  Prefer ``atomic_user_write()`` for new content.
        """
        try:
            fd = os.open(str(filepath), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except FileNotFoundError:
            print(f"Warning: Cannot set ownership on non-existent file: {filepath}",
                  file=sys.stderr)
            return
        except OSError as exc:
            print(f"Warning: Refusing to follow symlink or open {filepath}: {exc}",
                  file=sys.stderr)
            return

        try:
            os.fchmod(fd, mode)
            if os.geteuid() == 0:
                os.fchown(fd, self.uid, self.gid)
        except OSError as e:
            print(f"Warning: Could not set ownership/permissions on {filepath}: {e}",
                  file=sys.stderr)
        finally:
            os.close(fd)

    def get_user_info(self) -> dict:
        """
        Returns dictionary with user information for backward compatibility.

        Returns:
            {'home': Path, 'uid': int, 'gid': int, 'config_dir': Path,
             'user_state_dir': Path, 'system_state_dir': Path, 'run_dir': Path}
        """
        return {
            'home': self.home,
            'uid': self.uid,
            'gid': self.gid,
            'config_dir': self.user_state_dir,
            'user_state_dir': self.user_state_dir,
            'system_state_dir': self.system_state_dir,
            'run_dir': self.run_dir,
        }
