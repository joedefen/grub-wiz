"""The COLOR THEME screen, its persistence, and the HELP screen's display notes.

console-window builds the picker and draws it; grub-wiz's job is now only to
make it a screen of this app, to hand it the preferences object, and to keep the
shortcut out of every header (it is listed on the HELP screen only).
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import grub_wiz.main as cli  # noqa: E402
from console_window import Theme  # noqa: E402
from console_window import help as display_help  # noqa: E402
from grub_wiz.Glyphs import Glyphs  # noqa: E402
from grub_wiz.UiPrefs import UiPrefs  # noqa: E402


@pytest.fixture(autouse=True)
def preserve_process_state():
    """Theme choice, glyph mode and the app singleton are process-wide."""
    previous_theme = Theme.get_current()
    previous_singleton = cli.GrubWiz.singleton
    Theme.set_active(None)
    Glyphs.register_all()
    Glyphs.set_ascii(False)
    yield
    Theme.set_active(previous_theme)
    cli.GrubWiz.singleton = previous_singleton
    Glyphs.register_all()
    Glyphs.set_ascii(False)


@pytest.fixture(autouse=True)
def _colour_pairs(monkeypatch):
    """The swatch rows ask curses for a colour pair; no initscr() runs here."""
    monkeypatch.setattr('curses.color_pair', lambda pair: 0)


def make_app(win, remember=None):
    """Build the picker's host: a window plus the app state its store uses.

    The picker reaches the preferences through ``GrubWiz.singleton``, because
    the screen class is built at import time; standing an app in for it is what
    the real application does when it is constructed.
    """
    prefs = UiPrefs()
    app = SimpleNamespace(win=win, prefs=prefs,
                          theme_name=Theme.resolve(win.theme))
    cli.GrubWiz.singleton = app
    if remember is not None:
        app.prefs = remember
    return app


def test_theme_screen_is_a_grub_wiz_screen():
    """Deriving from GrubWizScreen is what keeps ESC/? working there."""
    assert issubclass(cli.ThemeScreen, cli.GrubWizScreen)
    assert hasattr(cli.ThemeScreen, 'theme_screen_ACTION')
    assert hasattr(cli.ThemeScreen, 'spin_theme_ACTION')


def test_cycling_applies_the_next_theme(headless_win):
    app = make_app(headless_win)
    start = Theme.resolve(headless_win.theme)

    cli.ThemeScreen(app).spin_theme_ACTION()

    assert Theme.resolve(headless_win.theme) != start


def test_cycling_remembers_the_theme_the_window_draws(headless_win):
    app = make_app(headless_win)

    cli.ThemeScreen(app).spin_theme_ACTION()

    resolved = Theme.resolve(headless_win.theme)
    assert app.theme_name == resolved
    assert UiPrefs().get('theme') == resolved


def test_cycling_wraps_and_leaves_a_valid_theme(headless_win):
    names = Theme.list_all()
    app = make_app(headless_win)

    for _ in range(len(names) + 1):
        cli.ThemeScreen(app).spin_theme_ACTION()
        assert headless_win.theme in names

    assert UiPrefs().get('theme') in names


def test_a_failing_store_never_breaks_the_cycle(headless_win):
    """A read-only config directory degrades to "works, not remembered"."""
    app = make_app(headless_win)

    def boom(_name):
        raise OSError('read-only store')

    app.prefs = SimpleNamespace(load=lambda: None, save=boom)
    start = Theme.resolve(headless_win.theme)

    cli.ThemeScreen(app).spin_theme_ACTION()

    assert Theme.resolve(headless_win.theme) != start


def test_draw_shows_the_current_theme_swatches_and_the_note(headless_win):
    app = make_app(headless_win)

    cli.ThemeScreen(app).draw_screen()

    header = ' '.join(headless_win.head.texts)
    body = headless_win.body.texts
    assert 'COLOR THEME' in header
    assert any('DANGER' in line for line in body)
    assert any('remembered' in line for line in body)


def test_help_screen_names_the_theme_keys_and_remembers_it():
    screen = object.__new__(cli.HelpScreen)

    notes = ' '.join(screen.extra_help_paragraphs())

    assert 'press T' in notes
    assert 't to cycle' in notes
    assert 'remembered' in notes


def test_help_screen_shows_the_library_font_check():
    """The font check explains boxes; it only works if it prints real glyphs."""
    assert cli.HelpScreen.show_display_notes is True

    notes = display_help.glyph_paragraph()

    assert '--ascii' in notes
    assert Glyphs.probe_text() in notes


def test_help_font_note_reflects_ascii_mode():
    Glyphs.set_ascii(True)

    notes = display_help.glyph_paragraph()

    assert 'ASCII' in notes
    assert '--ascii' in notes


def test_help_notes_draw_wrapped_on_a_headless_window(headless_win):
    """The notes are body rows: they must fit and use the window's own API."""
    screen = object.__new__(cli.HelpScreen)
    screen.win = headless_win

    screen.draw_notes(headless_win)

    lines = headless_win.body.texts
    assert len(lines) >= 2
    assert all(len(line) <= headless_win.cols for line in lines)
    assert 'Color theme' in ' '.join(lines)


def test_help_and_picker_rows_are_ascii_in_ascii_mode(headless_win):
    """The whole point: a terminal without the glyphs gets readable rows."""
    Glyphs.set_ascii(True)
    app = make_app(headless_win)
    screen = object.__new__(cli.HelpScreen)
    screen.win = headless_win

    screen.draw_notes(headless_win)
    cli.ThemeScreen(app).draw_screen()

    rows = headless_win.head.texts + headless_win.body.texts
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
        add_fancy_header=captured.append,
        warn_db=SimpleNamespace(write_if_dirty=lambda: None),
    )
    screen = object.__new__(cli.HomeScreen)
    screen.gw = gw

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
