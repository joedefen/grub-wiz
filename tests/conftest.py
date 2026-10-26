"""Shared pytest configuration for the grub-wiz test suite.

The production code uses process-wide singletons for user/system state.
``GrubFile`` asks ``ParamDiscovery`` which parameters are absent on the host,
and constructing ``ParamDiscovery`` or ``UserConfigDir`` creates the real
``~/.config/grub-wiz`` (and a system-state fallback) as a side effect.

For tests we replace both singleton accessors with small filesystem-backed
objects rooted at ``tmp_path`` so the suite never reads or writes the invoking
user's configuration directory, and so results do not depend on a stale
``system-params.yaml`` cache.  The direct ``UserConfigDir`` tests construct the
real class explicitly (with redirected roots); this fixture only intercepts the
singleton used by the application modules.

The window fixtures at the bottom provide a *real* ``ConsoleWindow`` on a
headless backend.  The in-place prompt, the header/body model and the status
line therefore come from console-window itself; only the two interactions that
poll a real keyboard (``answer()`` and ``flash()``) are replaced.
"""

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from console_window import ConsoleWindow, ConsoleWindowOpts
from console_window.backend import HeadlessBackend

from grub_wiz.ParamDiscovery import ParamDiscovery
from grub_wiz.UserConfigDir import UserConfigDir

# One MiB, matching UserConfigDir.MAX_STATE_BYTES.
_MAX_STATE_BYTES = 1024 * 1024


class FakeUserConfigDir:
    """Filesystem-backed stand-in for ``UserConfigDir`` rooted at ``tmp_path``.

    Only the surface the application modules touch is implemented.  Writes are
    still atomic (temp file + ``os.replace``) so tests observe the same
    replacement semantics without a privileged directory.
    """

    def __init__(self, root: Path):
        self.home = root / 'home'
        self.user_state_dir = self.home / '.config' / 'grub-wiz'
        self.system_state_dir = root / 'system-state'
        self.run_dir = root / 'run'
        for path in (self.user_state_dir, self.system_state_dir, self.run_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.uid = os.getuid()
        self.gid = os.getgid()

    @property
    def config_dir(self) -> Path:
        """Backward-compatible alias for the user state directory."""
        return self.user_state_dir

    @staticmethod
    def safe_read_bytes(path, max_bytes=_MAX_STATE_BYTES) -> bytes:
        """Read a regular file without following a symlink."""
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            st = os.fstat(fd)
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
    def safe_read_text(cls, path, max_bytes=_MAX_STATE_BYTES) -> str:
        return cls.safe_read_bytes(path, max_bytes).decode('utf-8')

    @staticmethod
    def atomic_write(path, data, mode=0o644, uid=None, gid=None,
                     trusted_parent=False) -> None:
        """Atomically replace *path* with *data* (ownership args are ignored)."""
        del uid, gid, trusted_parent
        path = Path(path)
        payload = data.encode('utf-8') if isinstance(data, str) else data
        fd, tmp_name = tempfile.mkstemp(prefix=f'.{path.name}.tmp-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(tmp_name, mode)
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def atomic_user_write(self, path, data, mode=0o644) -> None:
        path = Path(path)
        if path.parent != self.user_state_dir:
            raise ValueError(
                f"Refusing user-state write outside {self.user_state_dir}: {path}")
        self.atomic_write(path, data, mode=mode, uid=self.uid, gid=self.gid)

    def atomic_root_write(self, path, data, mode=0o644) -> None:
        self.atomic_write(path, data, mode=mode, uid=0, gid=0, trusted_parent=True)

    @staticmethod
    def staging_path(target) -> Path:
        target = Path(target)
        return target.parent / f'.{target.name}.grub-wiz-test-{os.getpid()}'

    @staticmethod
    def give_to_user(filepath, mode=0o644) -> None:
        try:
            os.chmod(filepath, mode)
        except OSError:
            pass

    def get_user_info(self) -> dict:
        return {
            'home': self.home,
            'uid': self.uid,
            'gid': self.gid,
            'config_dir': self.user_state_dir,
            'user_state_dir': self.user_state_dir,
            'system_state_dir': self.system_state_dir,
            'run_dir': self.run_dir,
        }


@pytest.fixture(autouse=True)
def isolated_param_discovery(monkeypatch):
    """Keep tests independent of the host's GRUB discovery cache."""
    fake_discovery = SimpleNamespace(
        # No parameter is considered absent on the test host.
        get_absent=lambda _params: set(),
        manual_enable=lambda _state=None: True,
        # Startup refreshes the discovery cache; tests must not shell out.
        ensure_discovered=lambda: set(),
    )
    monkeypatch.setattr(
        ParamDiscovery,
        "get_singleton",
        staticmethod(lambda: fake_discovery),
    )


class HeadlessTestWin(ConsoleWindow):
    """A real window without a terminal, plus canned dialogs.

    Everything a test needs to observe is the production behaviour: the
    prompt lifecycle (``begin_prompt``/``handle_prompt_key``), the header and
    body row model, and the status line.  ``answer()`` and ``flash()`` block on
    the keyboard, so they are reduced to a canned answer and a record.
    """

    def __init__(self, rows=24, cols=80, answers=()):
        super().__init__(opts=ConsoleWindowOpts(),
                         backend=HeadlessBackend(rows=rows, cols=cols),
                         singleton=False)
        self.answers = list(answers)
        self.dialog_calls = []
        self.flashes = []

    def answer(self, prompt='', seed='', height=1, **_kwargs):
        """Replay the next canned dialog answer (``None`` ends the dialog)."""
        self.dialog_calls.append({'prompt': prompt, 'seed': seed,
                                  'height': height})
        return self.answers.pop(0) if self.answers else None

    def flash(self, message='', duration=2.0):
        """Record a modal message instead of drawing it and polling keys."""
        self.flashes.append((message, duration))


@pytest.fixture
def headless_win():
    """One real window on a headless backend, stopped at teardown."""
    win = HeadlessTestWin()
    yield win
    win.stop_curses()


@pytest.fixture
def make_headless_win():
    """Factory for any number of headless windows, all stopped at teardown."""
    opened = []

    def build(rows=24, cols=80, answers=()):
        win = HeadlessTestWin(rows=rows, cols=cols, answers=answers)
        opened.append(win)
        return win

    yield build
    while opened:
        opened.pop().stop_curses()


@pytest.fixture(autouse=True)
def isolated_user_config_dir(monkeypatch, tmp_path):
    """Keep application modules out of the invoking user's config directory.

    ``BackupMgr``, ``WarnDB`` and ``CannedConfig`` resolve this singleton at
    runtime.  The fake is filesystem-backed under ``tmp_path`` so tests can
    still exercise real read/write behaviour.  ``singleton``/``_instance`` are
    reset per test so a test that constructs the real class cannot leak state
    into the next one (see ``tests/test_user_config_dir.py``).
    """
    fake = FakeUserConfigDir(tmp_path)
    monkeypatch.setattr(
        UserConfigDir,
        'get_singleton',
        staticmethod(lambda app_name='grub-wiz': fake),
    )
    monkeypatch.setattr(UserConfigDir, 'singleton', None)
    monkeypatch.setattr(UserConfigDir, '_instance', None)
    return fake
