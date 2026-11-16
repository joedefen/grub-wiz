"""The COLOR THEME screen, its persistence, and the HELP screen's notes.

console-window builds the picker and draws it; grub-wiz's job is only to make it
a screen of this app, hand it the preferences object, and keep the shortcut out
of every header (it is listed on the HELP screen only).  In 3.1 ``mono`` is a
real theme, so the generated picker cycles it with no application override.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import grub_wiz.main as cli  # noqa: E402
from console_window import (  # noqa: E402
    BasicHelpScreen, Theme, colors_enabled, set_colors_enabled)
from console_window import glyphs as library_glyphs  # noqa: E402
from grub_wiz.Glyphs import Glyphs  # noqa: E402
from grub_wiz.UiPrefs import UiPrefs  # noqa: E402


@pytest.fixture(autouse=True)
def preserve_process_state():
    """Theme choice, glyph mode and the app singleton are process-wide."""
    previous_theme = Theme.get_current()
    previous_singleton = cli.GrubWiz.singleton
    Theme.set_active(None)
    set_colors_enabled(True)
    Glyphs.set_ascii(False)
    yield
    Theme.set_active(previous_theme)
    set_colors_enabled(True)
    cli.GrubWiz.singleton = previous_singleton
    Glyphs.set_ascii(False)


@pytest.fixture(autouse=True)
def _colour_pairs(monkeypatch):
    """The swatch rows ask curses for a colour pair; no initscr() runs here."""
    monkeypatch.setattr('curses.color_pair', lambda pair: 0)


def make_app(win, remember=None):
    """Build the picker's host: a window plus the app state its store uses."""
    prefs = UiPrefs()
    app = SimpleNamespace(win=win, prefs=prefs,
                          theme_name=Theme.resolve(win.theme))
    cli.GrubWiz.singleton = app
    if remember is not None:
        app.prefs = remember
    return app


def draw(screen):
    """Draw *screen* onto its window the way the loop does."""
    screen.clear()
    screen.draw_screen()
    return screen


def test_theme_screen_is_a_grub_wiz_screen():
    """Deriving from GrubWizScreen is what keeps ESC/? working there."""
    assert issubclass(cli.ThemeScreen, cli.GrubWizScreen)
    assert hasattr(cli.ThemeScreen, 'theme_screen_ACTION')
    assert hasattr(cli.ThemeScreen, 'spin_theme_ACTION')


def test_cycling_applies_the_next_theme(headless_win):
    app = make_app(headless_win)
    start = headless_win.theme

    cli.ThemeScreen(app).spin_theme_ACTION()

    assert headless_win.theme != start


def test_cycling_remembers_the_theme_the_window_draws(headless_win):
    app = make_app(headless_win)

    cli.ThemeScreen(app).spin_theme_ACTION()

    assert app.theme_name == headless_win.theme
    assert UiPrefs().get('theme') == headless_win.theme


def test_cycling_wraps_and_leaves_a_valid_theme(headless_win):
    app = make_app(headless_win)

    for _ in range(len(Theme.list_all()) + 1):
        cli.ThemeScreen(app).spin_theme_ACTION()
        assert headless_win.theme in Theme.list_all()

    assert UiPrefs().get('theme') in Theme.list_all()


def test_the_cycle_offers_every_theme_including_mono():
    # No application pseudo-theme any more: the library list is the cycle.
    assert 'mono' in Theme.list_all()


def test_cycling_into_mono_turns_colour_off_and_remembers_it(headless_win):
    app = make_app(headless_win)
    headless_win.set_theme('nord')      # mono's predecessor, so one step lands on it

    cli.ThemeScreen(app).spin_theme_ACTION()

    assert colors_enabled() is False
    assert headless_win.theme == 'mono'
    assert app.theme_name == 'mono'
    assert UiPrefs().get('theme') == 'mono'


def test_cycling_out_of_mono_restores_colour_and_a_palette(headless_win):
    app = make_app(headless_win)
    headless_win.set_theme('mono')

    cli.ThemeScreen(app).spin_theme_ACTION()

    assert colors_enabled() is True
    assert headless_win.theme == Theme.list_all()[0]
    assert UiPrefs().get('theme') == headless_win.theme


def test_a_mono_run_cycles_to_the_first_palette(headless_win):
    app = make_app(headless_win)
    headless_win.set_theme('mono')

    cli.ThemeScreen(app).spin_theme_ACTION()

    assert headless_win.theme == Theme.list_all()[0]


def test_the_picker_header_names_mono(headless_win):
    app = make_app(headless_win)
    headless_win.set_theme('mono')

    screen = draw(cli.ThemeScreen(app))

    assert 'mono' in ' '.join(screen.head.texts).lower()


def test_a_failing_store_never_breaks_the_cycle(headless_win):
    """A read-only config directory degrades to "works, not remembered"."""
    app = make_app(headless_win)

    def boom(_name):
        raise OSError('read-only store')

    app.prefs = SimpleNamespace(load=lambda: None, save=boom)
    start = headless_win.theme

    cli.ThemeScreen(app).spin_theme_ACTION()

    assert headless_win.theme != start


def test_picking_a_theme_lifts_a_mono_start(headless_win):
    """Choosing a theme is a request for colour, so the picker gets back out."""
    app = make_app(headless_win)
    headless_win.set_theme('mono')
    assert colors_enabled() is False

    cli.ThemeScreen(app).spin_theme_ACTION()

    assert colors_enabled() is True


def test_a_failing_store_still_lifts_a_mono_start(headless_win):
    """The lift is part of the choice, not part of remembering it."""
    app = make_app(headless_win)

    def boom(_name):
        raise OSError('read-only store')

    app.prefs = SimpleNamespace(load=lambda: None, save=boom)
    headless_win.set_theme('mono')

    cli.ThemeScreen(app).spin_theme_ACTION()

    assert colors_enabled() is True


def test_draw_shows_the_current_theme_swatches_and_the_note(headless_win):
    app = make_app(headless_win)

    screen = draw(cli.ThemeScreen(app))

    header = ' '.join(screen.head.texts)
    body = screen.body.texts
    assert 'COLOR THEME' in header
    assert any('DANGER' in line for line in body)
    assert any('remembered' in line for line in body)


def test_help_screen_names_the_theme_keys_and_remembers_it():
    screen = object.__new__(cli.HelpScreen)

    notes = ' '.join(screen.extra_help_paragraphs())

    assert 'press T' in notes
    assert 't to cycle' in notes
    assert 'remembered' in notes


def test_help_screen_uses_the_library_font_check():
    """The Fonts section explains boxes; a hand-rolled page would lose it."""
    assert cli.HelpScreen.draw_screen is BasicHelpScreen.draw_screen
    assert cli.HelpScreen.font_section is None
    assert cli.HelpScreen.fonts_separator == '---------- Fonts ----------'
    assert library_glyphs.font_check_rows()


def test_help_notes_draw_wrapped_on_a_headless_window(headless_win):
    """The notes are body rows: they must fit and use the window's own API."""
    app = make_app(headless_win)
    screen = draw(cli.HelpScreen(app))
    screen.clear()
    screen.draw_notes()

    lines = screen.body.texts
    assert len(lines) >= 2
    assert all(len(line) <= headless_win.cols for line in lines)
    assert 'Color theme' in ' '.join(lines)


def test_help_and_picker_rows_are_ascii_in_ascii_mode(headless_win):
    """The whole point: a terminal without the glyphs gets readable rows."""
    Glyphs.set_ascii(True)
    app = make_app(headless_win)

    notes = draw(cli.HelpScreen(app))
    notes.clear()
    notes.draw_notes()
    picker = draw(cli.ThemeScreen(app))

    rows = notes.body.texts + picker.head.texts + picker.body.texts
    assert rows
    assert all(row.isascii() for row in rows), [
        row for row in rows if not row.isascii()]


def test_theme_key_is_not_advertised_in_the_edit_header():
    """The header is scarce; the picker is a preference, not an edit step."""
    captured = []
    gw = SimpleNamespace(
        ss=SimpleNamespace(is_curr=lambda _screen: False),
        spins=SimpleNamespace(guide='Off'),
        get_diffs=lambda: {},
        warn_db=SimpleNamespace(write_if_dirty=lambda: None),
    )
    screen = object.__new__(cli.HomeScreen)
    screen.gw = gw
    screen.app = gw
    screen.add_fancy_header = captured.append

    screen.add_common_head1('EDIT')

    assert 'theme' not in captured[0].lower()
    assert 'T -' not in captured[0]


# --- the theme precedence, now owned by console_window ---------------------

def test_initial_theme_prefers_cli_then_saved_then_default():
    prefs = UiPrefs()

    assert Theme.initial(None, prefs) == 'default'
    assert Theme.initial('nord', prefs) == 'nord'

    prefs.save('gruvbox')
    assert Theme.initial(None, prefs) == 'gruvbox'
    # A one-shot CLI choice does not overwrite the remembered one.
    assert Theme.initial('nord', prefs) == 'nord'
    assert UiPrefs().get('theme') == 'gruvbox'


def test_initial_choice_preserves_a_remembered_mono():
    """``mono`` is a real theme now, so it survives without an app override."""
    prefs = UiPrefs()
    prefs.save('mono')

    assert cli.initial_theme_name(None, prefs) == 'mono'
    # A one-shot --theme still wins without changing what was remembered.
    assert cli.initial_theme_name('nord', prefs) == 'nord'
    assert UiPrefs().get('theme') == 'mono'


def test_initial_choice_still_degrades_a_stale_theme():
    prefs = UiPrefs()
    prefs.save('a-theme-that-was-removed')

    assert cli.initial_theme_name(None, prefs) == 'default'


def test_stale_saved_theme_degrades_to_the_default():
    prefs = UiPrefs()
    prefs.save('a-theme-that-was-removed')

    assert Theme.initial(None, prefs) == 'default'


def test_the_store_reports_nothing_without_a_running_app():
    cli.GrubWiz.singleton = None

    assert cli.PREFS_THEME_STORE.load() is None
    cli.PREFS_THEME_STORE.save('nord')     # a no-op, not an error


def test_the_store_reads_and_writes_the_live_preferences():
    app = SimpleNamespace(prefs=UiPrefs(), theme_name='default')
    cli.GrubWiz.singleton = app

    cli.PREFS_THEME_STORE.save('gruvbox')

    assert app.theme_name == 'gruvbox'
    assert cli.PREFS_THEME_STORE.load() == 'gruvbox'
    assert UiPrefs().get('theme') == 'gruvbox'
