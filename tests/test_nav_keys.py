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
from console_window import (NAVIGATION_KEYS, ConsoleWindow, OptionSpinner,
                            signals)
from console_window.backend import HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.window import render_nav_help


def test_grub_wiz_takes_only_the_cursor_keys():
    """LEFT/RIGHT cycle values; every other navigation key stays with the library."""
    assert cli.TAKEN_NAV_KEYS == [curses.KEY_LEFT, curses.KEY_RIGHT]


def test_configuring_grub_wiz_does_not_mutate_the_library_key_set():
    ConsoleWindowOpts(taken_nav_keys=cli.TAKEN_NAV_KEYS)

    assert {curses.KEY_LEFT, curses.KEY_RIGHT} <= NAVIGATION_KEYS
    assert set(cli.TAKEN_NAV_KEYS) <= NAVIGATION_KEYS


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


def test_ctrl_c_is_delivered_as_the_quit_key():
    """Ctrl-C must reach the main loop as a key, never as a dead signal.

    ``ConsoleWindowOpts(ctrl_c_terminates=False)`` makes the library turn
    SIGINT into key 0x3, but only when the window was told the app handles it.
    A window that forgot to register the key would swallow Ctrl-C silently, so
    the quit prompt would be unreachable by Ctrl-C.
    """
    win = ConsoleWindow(ConsoleWindowOpts(ctrl_c_terminates=False),
                        backend=HeadlessBackend(), singleton=False)
    win.handled_keys = {cli.QUIT_KEY}
    signals.ctrl_c_flag = True
    try:
        assert cli.prompt_key(win, 0.05) == cli.QUIT_KEY
    finally:
        signals.ctrl_c_flag = False


def test_nav_help_prunes_taken_keys_instead_of_repeating_them():
    """3.1 removes a taken key from its chunk; there is no second ``App:`` line."""
    opts = ConsoleWindowOpts(taken_nav_keys=cli.TAKEN_NAV_KEYS)
    lines = render_nav_help(opts.nav_keys)

    rendered = '\n'.join(lines)
    assert 'App:' not in rendered
    # The cursor keys are no longer advertised as navigation.
    assert 'LEFT' not in rendered
    assert 'RIGHT' not in rendered
    # The remaining default bindings are still documented.
    assert any('down: j/DOWN' in line for line in lines)
    assert any('up: k/UP' in line for line in lines)
    assert opts.taken_nav_keys == [curses.KEY_LEFT, curses.KEY_RIGHT]
