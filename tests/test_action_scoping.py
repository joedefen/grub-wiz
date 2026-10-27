"""TUI navigation and action scoping (audit M13).

``OptionSpinner`` derives an action's ``effective_scope`` from the screens
that implement ``<action>_ACTION``, and ``ScreenStack`` enforces each screen's
``come_from_whitelist``.  These tests pin the grub-wiz side of that contract so
an action cannot fire on a screen where it makes no sense, and a screen cannot
be reached from the wrong place.
"""

import curses
from types import SimpleNamespace

import pytest

import grub_wiz.main as cli
from console_window import OptionSpinner, ScreenStack
from console_window.opts import ConsoleWindowOpts

ALL_SCREENS = set(range(len(cli.SCREENS)))
VALUE_SCREENS = {cli.HOME_ST, cli.REVIEW_ST}
WARN_ACTION_SCREENS = {cli.HOME_ST, cli.REVIEW_ST, cli.WARN_ST}

# (attr, key) for every action registered by GrubWiz.setup_win().
ACTIONS = [
    ('escape', 27),
    ('help_mode', ord('?')),
    ('cycle_next', ord(' ')),
    ('cycle_prev', ord('C')),
    ('edit', ord('e')),
    ('expert_edit', ord('E')),
    ('undo', ord('u')),
    ('hide', ord('x')),
    ('show_hidden', ord('s')),
    ('write', ord('w')),
    ('enter_restore', ord('R')),
    ('enter_warnings', ord('W')),
    ('restore', ord('r')),
    ('delete', ord('d')),
    ('tag', ord('t')),
    ('view', ord('v')),
    ('baseline', ord('b')),
    ('compare', ord('c')),
    ('slash', ord('/')),
    ('theme_screen', ord('T')),
    ('spin_theme', ord('t')),
]


class FakeWin:
    """Minimal window state read by ``ScreenStack``."""

    def __init__(self):
        self.pick_pos = 0
        self.scroll_pos = 0
        self.free_scroll = False


def _screen(cls):
    """Instantiate a screen without running its constructor."""
    return object.__new__(cls)


def make_ui():
    """Build the real screen classes, stack, and action spinner."""
    win = FakeWin()
    screens = {
        cli.HOME_ST: _screen(cli.HomeScreen),
        cli.REVIEW_ST: _screen(cli.ReviewScreen),
        cli.RESTORE_ST: _screen(cli.RestoreScreen),
        cli.VIEW_ST: _screen(cli.ViewScreen),
        cli.COMPARE_ST: _screen(cli.CompareScreen),
        cli.WARN_ST: _screen(cli.WarnScreen),
        cli.HELP_ST: _screen(cli.HelpScreen),
        cli.THEME_ST: _screen(cli.ThemeScreen),
    }
    # Navigation hooks and the one recording-action test need a small app stub.
    app = SimpleNamespace(
        bak_lines=None,
        bak_path=None,
        must_reviews=None,
        clues=[],
        refresh_backup_list=lambda: None,
        warn_db=SimpleNamespace(write_if_dirty=lambda: None,
                                is_inhibit=lambda _key: False),
    )
    for screen in screens.values():
        screen.gw = app
        screen.app = app

    stack = ScreenStack(win, None, cli.SCREENS, screens)
    opts = ConsoleWindowOpts(taken_nav_keys=cli.TAKEN_NAV_KEYS)
    spinner = OptionSpinner(stack=stack, nav_keys=opts.nav_keys)
    for attr, key in ACTIONS:
        spinner.add_key(attr, f'{attr} action', genre='action', keys=[key])
    return win, screens, stack, spinner


def test_action_scope_matches_the_screens_that_implement_it():
    """Actions are scoped by ``<action>_ACTION``, not registered everywhere."""
    _win, _screens, _stack, spinner = make_ui()

    def scope(action):
        return spinner.attr_to_option[action].effective_scope

    assert scope('edit') == VALUE_SCREENS
    assert scope('expert_edit') == VALUE_SCREENS
    assert scope('cycle_next') == VALUE_SCREENS
    assert scope('cycle_prev') == VALUE_SCREENS
    assert scope('show_hidden') == VALUE_SCREENS
    assert scope('write') == VALUE_SCREENS
    assert scope('undo') == {cli.REVIEW_ST}
    assert scope('hide') == WARN_ACTION_SCREENS
    assert scope('slash') == WARN_ACTION_SCREENS
    for action in ('restore', 'delete', 'tag', 'view', 'baseline', 'compare'):
        assert scope(action) == {cli.RESTORE_ST}
    # The picker opens from anywhere, but its cycle key only exists on it.
    assert scope('theme_screen') == ALL_SCREENS
    assert scope('spin_theme') == {cli.THEME_ST}
    # Base-screen actions remain available everywhere.
    for action in ('escape', 'help_mode', 'enter_restore', 'enter_warnings'):
        assert scope(action) == ALL_SCREENS


def test_actions_run_only_on_screens_in_their_scope_and_flags_are_cleared():
    """A scoped-out action must not run and must not linger until later."""
    _win, screens, stack, spinner = make_ui()
    spins = spinner.default_obj
    calls = []

    screens[cli.HOME_ST].gw = SimpleNamespace(
        navigate_to=lambda screen: calls.append(('write', screen)) or True,
        must_reviews=None,
        clues=[],
    )
    screens[cli.RESTORE_ST].restore_ACTION = (
        lambda: calls.append(('restore', cli.RESTORE_ST)))

    # On HOME: write is implemented, restore is not.
    spins.write = True
    spins.restore = True
    stack.perform_actions(spinner)

    assert calls == [('write', cli.REVIEW_ST)]
    assert spins.write is False
    assert spins.restore is False

    # On RESTORE the reverse is true.
    assert stack.push(cli.RESTORE_ST) == 0
    spins.write = True
    spins.restore = True
    stack.perform_actions(spinner)

    assert calls == [('write', cli.REVIEW_ST), ('restore', cli.RESTORE_ST)]
    assert spins.write is False
    assert spins.restore is False


def test_navigation_whitelists_restrict_where_screens_can_be_entered():
    """VIEW/COMPARE come from RESTORE, RESTORE from HOME, HELP from anywhere."""
    _win, _screens, stack, _spinner = make_ui()

    assert stack.curr.num == cli.HOME_ST
    assert stack.push(cli.VIEW_ST) is None       # only from RESTORE
    assert stack.push(cli.COMPARE_ST) is None    # only from RESTORE
    assert stack.push(cli.HELP_ST) == 0          # no whitelist
    stack.pop()

    assert stack.push(cli.REVIEW_ST) == 0        # no whitelist
    assert stack.push(cli.RESTORE_ST) is None    # only from HOME
    stack.pop()

    assert stack.push(cli.RESTORE_ST) == 0
    assert stack.push(cli.VIEW_ST) == 0
    assert stack.push(cli.COMPARE_ST) is None    # only directly from RESTORE


def test_enter_restore_only_navigates_from_home():
    """The app-level R key is registered everywhere but guarded at runtime."""
    calls = []
    gw = SimpleNamespace(
        ss=SimpleNamespace(is_curr=lambda _screens: False),
        navigate_to=lambda screen: calls.append(screen),
    )
    screen = object.__new__(cli.GrubWizScreen)
    screen.gw = gw

    screen.enter_restore_ACTION()
    assert calls == []

    gw.ss = SimpleNamespace(is_curr=lambda screens: screens == cli.HOME_ST)
    screen.enter_restore_ACTION()
    assert calls == [cli.RESTORE_ST]


def test_enter_warnings_only_navigates_from_home_or_review():
    calls = []
    gw = SimpleNamespace(
        ss=SimpleNamespace(is_curr=lambda _screens: False),
        navigate_to=lambda screen: calls.append(screen),
    )
    screen = object.__new__(cli.GrubWizScreen)
    screen.gw = gw

    screen.enter_warnings_ACTION()
    assert calls == []

    gw.ss = SimpleNamespace(
        is_curr=lambda screens: cli.REVIEW_ST in screens)
    screen.enter_warnings_ACTION()
    assert calls == [cli.WARN_ST]


def test_theme_screen_opens_once_and_not_from_itself():
    """``T`` opens the picker, and pressing it again must not stack another."""
    calls = []
    gw = SimpleNamespace(
        ss=SimpleNamespace(is_curr=lambda _screen: False),
        navigate_to=lambda screen: calls.append(screen),
    )
    screen = object.__new__(cli.GrubWizScreen)
    screen.gw = gw

    screen.theme_screen_ACTION()
    assert calls == [cli.THEME_ST]

    gw.ss = SimpleNamespace(is_curr=lambda screen: screen == cli.THEME_ST)
    screen.theme_screen_ACTION()
    assert calls == [cli.THEME_ST]


def test_escape_only_navigates_back_when_a_stack_exists():
    calls = []
    gw = SimpleNamespace(
        ss=SimpleNamespace(stack=[]),
        navigate_back=lambda: calls.append('back'),
    )
    screen = object.__new__(cli.GrubWizScreen)
    screen.gw = gw

    screen.escape_ACTION()
    assert calls == []

    gw.ss.stack = [object()]
    screen.escape_ACTION()
    assert calls == ['back']


def test_navigation_keys_remain_available_for_cursor_movement():
    """The app only takes LEFT/RIGHT; vertical navigation reaches the window."""
    opts = ConsoleWindowOpts(taken_nav_keys=cli.TAKEN_NAV_KEYS)

    assert curses.KEY_LEFT not in opts.nav_keys
    assert curses.KEY_RIGHT not in opts.nav_keys
    assert curses.KEY_UP in opts.nav_keys
    assert curses.KEY_DOWN in opts.nav_keys


def test_invalid_action_arguments_are_rejected():
    """Duplicate attributes and navigation keys fail at registration."""
    _win, _screens, stack, _spinner = make_ui()
    opts = ConsoleWindowOpts(taken_nav_keys=cli.TAKEN_NAV_KEYS)
    spinner = OptionSpinner(stack=stack, nav_keys=opts.nav_keys)
    spinner.add_key('write', 'write action', genre='action', keys=[ord('w')])

    with pytest.raises(ValueError, match='already registered'):
        spinner.add_key('write', 'duplicate write', genre='action',
                        keys=[ord('y')])
    # The same key is allowed again on a disjoint screen scope.
    spinner.add_key('write_elsewhere', 'write elsewhere', genre='action',
                    keys=[ord('w')], scope={cli.HELP_ST})
    with pytest.raises(ValueError, match='navigation key'):
        spinner.add_key('scroll_down', 'down', genre='action',
                        keys=[curses.KEY_DOWN])
