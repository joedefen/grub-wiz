"""The COLOR THEME screen and the theme choice around it.

console-window builds the picker itself; grub-wiz's job is (a) to make it a
screen of this app, (b) to remember what the picker applied, and (c) to keep the
shortcut out of every header (it is listed on the HELP screen only).
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import grub_wiz.main as cli  # noqa: E402
from console_window import Theme  # noqa: E402
from grub_wiz.Glyphs import Glyphs  # noqa: E402
from grub_wiz.UiPrefs import UiPrefs  # noqa: E402


@pytest.fixture(autouse=True)
def preserve_process_state():
    """Both switches are process-wide; restore them for the next test."""
    previous_theme = Theme.get_current()
    Glyphs.set_ascii(False)
    yield
    Theme.set_active(previous_theme)
    Glyphs.set_ascii(False)


def make_screen(win, remember=None):
    """Build the real screen with the two collaborators it uses."""
    remembered = []

    def remember_theme():
        name = Theme.resolve(win.theme)
        remembered.append(name)
        return name

    app = SimpleNamespace(win=win,
                          remember_theme=remember if remember else remember_theme)
    return cli.ThemeScreen(app), remembered


def test_theme_screen_is_a_grub_wiz_screen():
    """Deriving from GrubWizScreen is what keeps ESC/? working there."""
    assert issubclass(cli.ThemeScreen, cli.GrubWizScreen)
    assert hasattr(cli.ThemeScreen, 'theme_screen_ACTION')
    assert hasattr(cli.ThemeScreen, 'spin_theme_ACTION')


def test_cycling_applies_the_next_theme_and_remembers_it(headless_win):
    screen, remembered = make_screen(headless_win)
    start = Theme.resolve(headless_win.theme)

    screen.spin_theme_ACTION()

    assert Theme.resolve(headless_win.theme) != start
    assert remembered == [headless_win.theme]


def test_cycling_wraps_and_leaves_a_valid_theme(headless_win):
    names = Theme.list_all()
    screen, remembered = make_screen(headless_win)

    for _ in range(len(names) + 1):
        screen.spin_theme_ACTION()
        assert headless_win.theme in names

    assert len(remembered) == len(names) + 1


def test_draw_shows_the_current_theme_swatches_and_the_note(headless_win,
                                                            monkeypatch):
    # The library's swatch rows call curses.color_pair(), which needs a real
    # initialised screen; a headless window has none.
    monkeypatch.setattr(cli.cs, 'color_pair', lambda _pair: 0)
    screen, _remembered = make_screen(headless_win)

    screen.draw_screen()

    header = ' '.join(headless_win.head.texts)
    body = headless_win.body.texts
    assert 'COLOR THEME' in header
    assert any('DANGER' in line for line in body)
    assert any('remembered' in line for line in body)


def test_help_screen_lists_the_theme_keys_and_the_font_check():
    screen = object.__new__(cli.HelpScreen)

    notes = ' '.join(screen.extra_help_paragraphs())

    assert 'press T' in notes
    assert 't to cycle' in notes
    assert 'remembered' in notes
    assert '--ascii' in notes
    assert Glyphs.probe_text() in notes


def test_help_notes_draw_wrapped_on_a_headless_window(headless_win):
    """The notes are body rows: they must fit and use the window's own API."""
    screen = object.__new__(cli.HelpScreen)
    screen.win = headless_win

    screen.draw_notes()

    lines = headless_win.body.texts
    assert len(lines) >= 3                     # both paragraphs wrapped
    assert all(len(line) <= headless_win.cols for line in lines)
    assert 'Color theme' in ' '.join(lines)
    assert '--ascii' in ' '.join(lines)


def test_help_font_note_reflects_ascii_mode():
    screen = object.__new__(cli.HelpScreen)
    Glyphs.set_ascii(True)

    notes = ' '.join(screen.extra_help_paragraphs())

    assert 'ASCII symbols are in use' in notes
    # The probe is still printed so the user can compare.
    assert Glyphs.probe_text() in notes


def test_theme_key_is_not_advertised_in_the_edit_header():
    """The header is scarce; the picker is a preference, not an edit step."""
    captured = []
    gw = SimpleNamespace(
        ss=SimpleNamespace(is_curr=lambda _screen: False),
        spins=SimpleNamespace(guide='Off'),
        get_diffs=lambda: {},
        add_fancy_header=captured.append,
        warn_db=SimpleNamespace(write_if_dirty=lambda: None),
    )
    screen = object.__new__(cli.HomeScreen)
    screen.gw = gw

    screen.add_common_head1('EDIT')

    assert 'theme' not in captured[0].lower()
    assert 'T -' not in captured[0]


def test_initial_theme_prefers_cli_then_saved_then_default(isolated_user_config_dir):
    wiz = object.__new__(cli.GrubWiz)
    wiz.prefs = UiPrefs()

    assert wiz._initial_theme(None) == 'default'
    assert wiz._initial_theme(SimpleNamespace(theme=None)) == 'default'
    assert wiz._initial_theme(SimpleNamespace(theme='nord')) == 'nord'

    wiz.prefs.set('theme', 'gruvbox')
    assert wiz._initial_theme(None) == 'gruvbox'
    # A one-shot CLI choice does not overwrite the remembered one.
    assert wiz._initial_theme(SimpleNamespace(theme='nord')) == 'nord'
    assert UiPrefs().get('theme') == 'gruvbox'


def test_stale_saved_theme_degrades_to_the_default(isolated_user_config_dir):
    wiz = object.__new__(cli.GrubWiz)
    wiz.prefs = UiPrefs()
    wiz.prefs.set('theme', 'a-theme-that-was-removed')

    assert wiz._initial_theme(None) == 'default'


def test_remember_theme_persists_what_the_window_draws(isolated_user_config_dir):
    wiz = object.__new__(cli.GrubWiz)
    wiz.prefs = UiPrefs()
    wiz.theme_name = 'default'
    wiz.win = SimpleNamespace(theme='nord')

    assert wiz.remember_theme() == 'nord'
    assert UiPrefs().get('theme') == 'nord'

    # Nothing changed, so nothing new is written.
    wiz.win.theme = 'nord'
    assert wiz.remember_theme() == 'nord'
    assert UiPrefs().get('theme') == 'nord'
