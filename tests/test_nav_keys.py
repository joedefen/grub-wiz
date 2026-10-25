"""Navigation keys are taken per window, not by mutating the library (M14).

grub-wiz binds LEFT/RIGHT to ``cycle_prev``/``cycle_next``.  With
console-window 2.0.1 the only way to do that was to ``discard()`` the two key
codes from ``console_window.NAVIGATION_KEYS`` -- a module-level mutable set
shared by every window in the process, and version-coupled to the library's
internals.  console-window 2.0.2 adds ``ConsoleWindowOpts(taken_nav_keys=...)``;
these tests pin that supported path so the monkeypatch cannot come back.
"""

import curses

import pytest

import grub_wiz.main as cli
from console_window import NAVIGATION_KEYS, OptionSpinner
from console_window.opts import ConsoleWindowOpts
from console_window.window import render_nav_help


def test_grub_wiz_takes_only_the_cursor_keys():
    """LEFT/RIGHT cycle values; every other navigation key stays with the library."""
    assert cli.TAKEN_NAV_KEYS == {
        curses.KEY_LEFT: 'prev value',
        curses.KEY_RIGHT: 'next value',
    }


def test_configuring_grub_wiz_does_not_mutate_the_library_key_set():
    ConsoleWindowOpts(taken_nav_keys=cli.TAKEN_NAV_KEYS)

    assert {curses.KEY_LEFT, curses.KEY_RIGHT} <= NAVIGATION_KEYS
    assert cli.TAKEN_NAV_KEYS.keys() <= NAVIGATION_KEYS


def test_effective_navigation_set_drops_only_the_taken_keys():
    opts = ConsoleWindowOpts(taken_nav_keys=cli.TAKEN_NAV_KEYS)

    assert curses.KEY_LEFT not in opts.nav_keys
    assert curses.KEY_RIGHT not in opts.nav_keys
    # Vertical navigation is untouched, so scrolling still works.
    for key in (curses.KEY_UP, curses.KEY_DOWN,
                curses.KEY_PPAGE, curses.KEY_NPAGE):
        assert key in opts.nav_keys


def test_a_window_that_takes_nothing_keeps_the_full_set():
    """One window's bindings must not leak into the next window."""
    assert ConsoleWindowOpts().nav_keys == frozenset(NAVIGATION_KEYS)


def test_spinner_accepts_taken_keys_but_still_rejects_navigation():
    opts = ConsoleWindowOpts(taken_nav_keys=cli.TAKEN_NAV_KEYS)
    spinner = OptionSpinner(nav_keys=opts.nav_keys)

    spinner.add_key('cycle_next', '=>,SP - next cycle value', genre='action',
                    keys=[curses.KEY_RIGHT, ord(' ')])
    spinner.add_key('cycle_prev', '<=,BS - prev cycle value', genre='action',
                    keys=[curses.KEY_LEFT, ord('C'), curses.KEY_BACKSPACE])

    with pytest.raises(ValueError, match='navigation key'):
        spinner.add_key('scroll_down', 'DOWN - one row', genre='action',
                        keys=[curses.KEY_DOWN])


def test_nav_help_credits_taken_keys_to_the_app():
    """The help screen must not advertise stolen keys as navigation."""
    opts = ConsoleWindowOpts(taken_nav_keys=cli.TAKEN_NAV_KEYS)
    lines = render_nav_help(opts.nav_keys, opts.taken_nav_keys)

    app_line = next(line for line in lines if line.startswith('App:'))
    assert '\u2190: prev value' in app_line
    assert '\u2192: next value' in app_line
    # The remaining default bindings are still documented.
    assert any('DOWN: down one row' in line for line in lines)
    assert any('UP: up one row' in line for line in lines)
