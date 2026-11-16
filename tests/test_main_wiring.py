"""Headless wiring test for the real screen/stack/spinner construction.

This is the cheap test the console-window 3.1 upgrade notes recommend: it builds
the real screen classes, the real ``ScreenStack`` and the real ``OptionSpinner``,
registers the application's keys through ``GrubWiz.register_keys()``, and drives
``?``/ESC/``q`` through ``do_key()`` + ``perform_actions()``.  Registration
errors (a reserved built-in key, a duplicate attribute, a navigation-key
conflict) and a broken scope fire here, before curses is ever involved.
"""

from types import SimpleNamespace

from console_window import (
    ConsoleWindow, ConsoleWindowOpts, Screen, ScreenStack, OptionSpinner)
from console_window.backend import HeadlessBackend

import grub_wiz.main as cli


def _screen(cls, app):
    """Instantiate a real screen without running its application setup."""
    screen = object.__new__(cls)
    Screen.__init__(screen, app)
    screen.gw = app
    return screen


def make_ui():
    """Build the app's real screens, stack and spinner on a headless window."""
    win = ConsoleWindow(
        opts=ConsoleWindowOpts(taken_nav_keys=cli.TAKEN_NAV_KEYS),
        backend=HeadlessBackend(rows=24, cols=80),
        singleton=False,
    )
    app = SimpleNamespace(win=win, running=True)
    app.request_quit = lambda: True

    screens = {
        cli.HOME_ST: _screen(cli.HomeScreen, app),
        cli.REVIEW_ST: _screen(cli.ReviewScreen, app),
        cli.RESTORE_ST: _screen(cli.RestoreScreen, app),
        cli.VIEW_ST: _screen(cli.ViewScreen, app),
        cli.COMPARE_ST: _screen(cli.CompareScreen, app),
        cli.WARN_ST: _screen(cli.WarnScreen, app),
        cli.HELP_ST: _screen(cli.HelpScreen, app),
        cli.THEME_ST: _screen(cli.ThemeScreen, app),
    }
    stack = ScreenStack(win, None, cli.SCREENS, screens)
    app.ss = stack
    app.navigate_to = lambda num: stack.push(num) is not None
    app.navigate_back = lambda: stack.pop() is not None

    spinner = OptionSpinner(stack=stack, nav_keys=win.opts.nav_keys,
                            escape_keys=[27])
    # The app only supplies a ``self`` for register_keys(); it touches nothing.
    cli.GrubWiz.register_keys(SimpleNamespace(), spinner)
    win.set_handled_keys(spinner)
    return win, app, screens, stack, spinner


def test_registration_succeeds_and_scopes_follow_the_action_methods():
    _win, _app, _screens, _stack, spin = make_ui()

    def scope(attr):
        return spin.attr_to_option[attr].effective_scope

    assert scope('edit') == {cli.HOME_ST, cli.REVIEW_ST}
    assert scope('undo') == {cli.REVIEW_ST}
    assert scope('restore') == {cli.RESTORE_ST}
    assert scope('slash') == {cli.HOME_ST, cli.REVIEW_ST, cli.WARN_ST}
    assert scope('theme_screen') == set(range(len(cli.SCREENS)))
    assert scope('spin_theme') == {cli.THEME_ST}


def test_built_in_quit_and_escape_are_registered_once():
    _win, _app, _screens, _stack, spin = make_ui()

    assert set(spin.attr_to_option['quit'].keys) == {ord('q'), 0x3}
    assert spin.attr_to_option['quit'].builtin is True
    assert spin.attr_to_option['escape'].keys == [27]
    assert spin.attr_to_option['escape'].builtin is True
    # ENTER/^J are left for the search prompt, not bound to escape.
    assert 10 not in spin.attr_to_option['escape'].keys


def test_help_and_escape_are_dispatched_through_the_spinner():
    win, app, _screens, stack, spin = make_ui()
    assert stack.curr.num == cli.HOME_ST

    spin.do_key(ord('?'), win)
    stack.perform_actions(spin)
    assert stack.curr.num == cli.HELP_ST

    spin.do_key(27, win)
    stack.perform_actions(spin)
    assert stack.curr.num == cli.HOME_ST

    spin.do_key(ord('q'), win)
    stack.perform_actions(spin)
    assert app.running is False


def test_the_help_screen_draws_the_scoped_key_map():
    """``BasicHelpScreen`` supplies the body; the app must not override it."""
    from console_window import BasicHelpScreen

    assert cli.HelpScreen.draw_screen is BasicHelpScreen.draw_screen
    assert cli.HelpScreen.is_help_screen is True

    win, _app, screens, stack, spin = make_ui()
    spin.do_key(ord('?'), win)
    stack.perform_actions(spin)
    help_screen = screens[cli.HELP_ST]
    help_screen.clear()
    help_screen.draw_screen()

    text = '\n'.join(help_screen.head.texts + help_screen.body.texts)
    assert "Keys for 'HOME':" in text
    assert 'e - edit value' in text
    # RESTORE-only actions are not advertised on HOME's page.
    assert 'r - restore selected backup' not in text
    assert '---------- Fonts ----------' in text
