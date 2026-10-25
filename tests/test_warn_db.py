"""Regression tests for audit finding M8.

``WarnDB.audit_info()`` used to latch after the first call, so a redraw of the
review screen could not register warnings that appeared (or disappeared) after
a parameter edit, and the warnings-configuration screen kept reading the stale
``all_info`` snapshot taken at startup.  The audit is now a comparison against
the live snapshot on every call, and ``WarnScreen`` refreshes it while drawing.

The tests use an in-memory stand-in for ``UserConfigDir`` so they never touch
the invoking user's configuration directory.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz.UserConfigDir import UserConfigDir
from grub_wiz.WarnDB import WarnDB
from grub_wiz.main import WarnScreen


class FakeUserConfig:
    """Minimal ``UserConfigDir`` replacement backed by a temporary directory."""

    def __init__(self, root):
        self.user_state_dir = root

    @staticmethod
    def safe_read_text(path, max_bytes=1024 * 1024):
        """Read like the real helper, including FileNotFoundError on first run."""
        del max_bytes
        return Path(path).read_text(encoding='utf-8')

    @staticmethod
    def atomic_user_write(path, data, mode=0o600):
        """Write like the real helper; permission handling is out of scope."""
        del mode
        Path(path).write_text(data, encoding='utf-8')


@pytest.fixture
def warn_db(tmp_path, monkeypatch):
    """A WarnDB whose user-config singleton lives in ``tmp_path``."""
    fake = FakeUserConfig(tmp_path)
    monkeypatch.setattr(
        UserConfigDir,
        'get_singleton',
        staticmethod(lambda app_name='grub-wiz': fake),
    )
    return WarnDB(param_cfg=None)


def test_audit_applies_every_call(warn_db):
    """A later audit must add, re-grade, and drop warnings."""
    first = WarnDB.make_key('GRUB_TIMEOUT', 'first warning')
    second = WarnDB.make_key('GRUB_CMDLINE_LINUX', 'second warning')

    warn_db.audit_info({first: 2})
    assert warn_db.all_info == {first: 2}

    # An edit introduces a new warning and re-grades the existing one.
    warn_db.audit_info({first: 4, second: 1})
    assert warn_db.all_info == {first: 4, second: 1}

    # Reverting the edit removes the new warning again.
    warn_db.audit_info({first: 4})
    assert warn_db.all_info == {first: 4}


def test_later_audit_purges_orphaned_inhibits(warn_db):
    """Only the first audit used to clean orphans; later ones must too."""
    kept = WarnDB.make_key('GRUB_TIMEOUT', 'kept warning')
    orphan = WarnDB.make_key('GRUB_TIMEOUT_STYLE', 'orphan warning')

    warn_db.audit_info({kept: 1, orphan: 2})
    warn_db.inhibit(kept, True)
    warn_db.inhibit(orphan, True)
    assert warn_db.write_if_dirty()

    # The parameter behind ``orphan`` was edited away.
    warn_db.audit_info({kept: 1})
    assert warn_db.inhibits == {kept}
    assert warn_db.write_if_dirty()

    warn_db.refresh()
    assert warn_db.inhibits == {kept}
    assert set(warn_db.all_info) == {kept}


def test_repeated_identical_audit_stays_clean(warn_db):
    """Re-auditing an unchanged snapshot must not dirty the database."""
    key = WarnDB.make_key('GRUB_TIMEOUT', 'steady warning')

    warn_db.audit_info({key: 3})
    assert warn_db.write_if_dirty()
    assert not warn_db.is_dirty()

    warn_db.audit_info({key: 3})
    assert not warn_db.is_dirty()
    assert warn_db.all_info == {key: 3}


class FakeWin:
    """Collect body lines instead of drawing them."""

    def __init__(self):
        self.cols = 100
        self.lines = []

    def add_body(self, line, **_kwargs):
        """Record a rendered body line."""
        self.lines.append(line)

    def get_picked_context(self):
        """WarnScreen.draw_head() needs this; the body does not use it."""
        return None


class FakeValidator:
    """Return a warning snapshot that the test can swap between redraws."""

    def __init__(self):
        self.all_info = {}

    def make_warns(self, _values):
        """Return no per-parameter rules, only the aggregate snapshot."""
        return {}, dict(self.all_info)


def test_warn_screen_redraws_live_warnings(warn_db):
    """The warnings screen must not render the startup snapshot forever."""
    win = FakeWin()
    validator = FakeValidator()
    gw = SimpleNamespace(
        win=win,
        warn_db=warn_db,
        wiz_validator=validator,
        param_values={},
    )
    screen = WarnScreen(gw)

    stale = WarnDB.make_key('GRUB_TIMEOUT', 'startup warning')
    validator.all_info = {stale: 2}
    screen.draw_body()
    assert any('startup warning' in line for line in win.lines)

    # A later edit replaces the warning set; a redraw must show only the new
    # warning and update the database the screen reads from.
    fresh = WarnDB.make_key('GRUB_CMDLINE_LINUX', 'post-edit warning')
    validator.all_info = {fresh: 4}
    win.lines.clear()
    screen.draw_body()

    rendered = '\n'.join(win.lines)
    assert 'post-edit warning' in rendered
    assert 'startup warning' not in rendered
    assert warn_db.all_info == {fresh: 4}
