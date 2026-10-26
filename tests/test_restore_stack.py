"""Regression tests for audit finding H6.

``OptionSpinner`` captures the ``ScreenStack`` it was constructed with and
consults it for action scoping and navigation.  Restoring a backup (and a
successful GRUB write) replaces ``GrubWiz.ss``; the spinner must be rebound to
the new stack or it keeps making decisions from the stale one.  A failed
restore must also leave the screens untouched instead of reinitializing the
app for a file that was never replaced.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

from console_window import OptionSpinner

sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz.main import GrubWiz, RestoreScreen, SCREENS


class FakeScreen:
    """Navigation hooks ScreenStack consults when pushing the home screen."""

    is_terminal = False
    come_from_whitelist = None

    def on_pause(self):
        """Allow screens to be covered."""
        return True

    def on_resume(self):
        """Allow returning to a screen."""
        return True

    def on_pop(self):
        """Allow leaving a screen."""
        return True


class FakeWin:
    """Minimal ConsoleWindow stand-in for ScreenStack and alert()/flash()."""

    def __init__(self):
        self.pick_pos = 0
        self.scroll_pos = 0
        self.free_scroll = False
        self.alerts = []
        self.flashes = []

    def alert(self, message=None, **_kwargs):
        """Record the alert instead of drawing it."""
        self.alerts.append(message)

    def flash(self, message='', duration=2.0):
        """Record the transient notice instead of drawing it."""
        self.flashes.append(message)


def make_stack_owner():
    """Build just enough of GrubWiz for reset_screen_stack()."""
    win = FakeWin()
    spinner = OptionSpinner()
    spins = spinner.default_obj
    screens = {num: FakeScreen() for num in range(len(SCREENS))}
    gw = SimpleNamespace(
        win=win,
        spinner=spinner,
        spins=spins,
        screens=screens,
        ss=SimpleNamespace(dead=True),
    )
    return gw, win, spinner


def test_reset_screen_stack_rebinds_spinner():
    """The spinner must consult the replacement stack, not the old one."""
    gw, win, spinner = make_stack_owner()
    stale_stack = gw.ss

    GrubWiz.reset_screen_stack(gw)

    assert gw.ss is not stale_stack
    assert spinner.stack is gw.ss
    assert gw.ss.obj is spinner.default_obj
    assert gw.ss.curr.num == 0
    assert win.pick_pos == 0


def make_restore_screen(restore_ok):
    """Build a RestoreScreen with fake collaborators and record callbacks."""
    win = FakeWin()
    target = Path('/tmp/20990101-000000-DEADBEEF.custom.bak')
    calls = []
    gw = SimpleNamespace(
        ordered_backup_pairs=[('DEADBEEF', target)],
        backups={'DEADBEEF': target},
        really_wanna=lambda _act: True,
        backup_mgr=SimpleNamespace(
            target_path=Path('/etc/default/grub'),
            restore_backup=lambda _path: restore_ok,
            calc_checksum=lambda _path: 'DEADBEEF',
        ),
        navigate_back=lambda: False,
        reinit_gw=lambda: calls.append('reinit'),
        reset_screen_stack=lambda: calls.append('reset'),
    )
    screen = RestoreScreen.__new__(RestoreScreen)
    screen.gw = gw
    screen.app = gw
    screen.win = win
    return screen, win, calls


def test_failed_restore_does_not_reinitialize():
    """restore_backup() returning False must abort before any rebuild."""
    screen, win, calls = make_restore_screen(restore_ok=False)

    screen.restore_ACTION()

    assert calls == []
    assert win.alerts == ['ERR: restore of '
                          "'20990101-000000-DEADBEEF.custom.bak' failed: "
                          'unknown error']


def test_failed_restore_reports_the_reason_from_backup_mgr():
    """The alert must carry why the restore failed, not just that it did.

    BackupMgr only writes the reason to stderr, which curses hides, so the
    screen has to forward ``last_error`` or the user is left with "failed".
    """
    screen, win, _calls = make_restore_screen(restore_ok=False)
    screen.gw.backup_mgr.last_error = 'stock.bak contains command substitution on line 1'

    screen.restore_ACTION()

    assert len(win.alerts) == 1
    assert 'command substitution on line 1' in win.alerts[0]


def test_successful_restore_rebuilds_with_fresh_stack():
    """A successful restore reinitializes and rebinds the stack exactly once.

    No backup is written: the bytes came from a file that is still on disk, so
    the only state that moves is the checksum marking the current file.
    """
    screen, win, calls = make_restore_screen(restore_ok=True)

    screen.restore_ACTION()

    assert calls == ['reinit', 'reset']
    assert screen.gw.grub_checksum == 'DEADBEEF'


def test_successful_restore_notifies_without_an_alert():
    """A successful restore is reported as an OK flash, not a modal ALERT.

    Nothing went wrong, so popping a modal titled ALERT made a normal outcome
    look like a failure.  The transient notice must still say the source was
    restored and that a write (which runs update-grub) is what applies it,
    because restore alone deliberately does not regenerate grub.cfg (audit
    M15).
    """
    screen, win, _calls = make_restore_screen(restore_ok=True)

    screen.restore_ACTION()

    assert win.alerts == []
    assert len(win.flashes) == 1
    notice = win.flashes[0]
    assert notice.startswith('OK')
    assert 'restored' in notice
    assert 'press w' in notice
    assert 'update-grub' in notice


def test_restore_uses_the_selected_path_not_checksum_lookup():
    """Two backups can share a checksum; the selected row must win."""
    win = FakeWin()
    selected = Path('/tmp/20990101-000000-DEADBEEF.selected.bak')
    other = Path('/tmp/20990102-000000-DEADBEEF.other.bak')
    restored = []
    gw = SimpleNamespace(
        ordered_backup_pairs=[('DEADBEEF', selected)],
        backups={'DEADBEEF': other},
        really_wanna=lambda _act: True,
        backup_mgr=SimpleNamespace(
            target_path=Path('/etc/default/grub'),
            restore_backup=lambda path: restored.append(path) or True,
            calc_checksum=lambda _path: 'DEADBEEF',
        ),
        navigate_back=lambda: False,
        reinit_gw=lambda: None,
        reset_screen_stack=lambda: None,
    )
    screen = RestoreScreen.__new__(RestoreScreen)
    screen.gw = gw
    screen.app = gw
    screen.win = win

    screen.restore_ACTION()

    assert restored == [selected]
