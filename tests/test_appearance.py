"""grub-wiz's wiring to console-window's unified theme/appearance decision.

console-window 3.1 collapsed the two axes: ``Appearance.resolve_appearance()``
returns one theme name, ``mono`` is a real theme, and ``Theme.set_active()`` is
what synchronizes the color switch.  These tests prove the two things this app
owns: it resolves the precedence once from the flags and remembered choice, and
its draw sites resolve roles through the library switch.
"""

import curses

from console_window import Theme, colors_enabled, set_colors_enabled

from grub_wiz import main as main_module


class FakePrefs:
    """The ``UiPrefs`` surface the theme resolver reads."""

    def __init__(self, remembered=None):
        self.remembered = remembered

    def load(self):
        return self.remembered


def resolve(theme=None, prefs=None):
    """Call the resolver with the shape argparse hands the application."""
    return main_module.initial_theme_name(theme, prefs)


def test_the_resolved_theme_is_a_canonical_name():
    assert resolve() == 'default'
    assert resolve(theme='nord') == 'nord'
    assert resolve(prefs=FakePrefs('gruvbox')) == 'gruvbox'


def test_an_explicit_theme_wins_over_a_remembered_one():
    assert resolve(theme='nord', prefs=FakePrefs('gruvbox')) == 'nord'


def test_mono_is_a_real_theme_and_survives_a_restart():
    assert resolve(prefs=FakePrefs('mono')) == 'mono'
    assert resolve(theme='mono') == 'mono'


def test_the_environment_convention_selects_mono(monkeypatch):
    monkeypatch.setenv('NO_COLOR', '1')

    assert resolve() == 'mono'


def test_an_explicit_theme_beats_no_color(monkeypatch):
    """--theme is a statement of intent, so it still asks for colour."""
    monkeypatch.setenv('NO_COLOR', '1')

    assert resolve(theme='nord') == 'nord'


def test_no_color_beats_a_remembered_palette(monkeypatch):
    monkeypatch.setenv('NO_COLOR', '1')

    assert resolve(prefs=FakePrefs('nord')) == 'mono'


def test_a_stale_remembered_theme_degrades_to_the_default():
    assert resolve(prefs=FakePrefs('a-theme-that-was-removed')) == 'default'


def test_a_broken_store_degrades_to_the_default():
    """A cosmetic preference must never keep the editor from starting."""

    class Broken:
        @staticmethod
        def load():
            raise OSError('preferences are unreadable')

    assert resolve(prefs=Broken()) == 'default'


def test_a_non_string_remembered_choice_degrades_to_the_default():
    """A hand edit can put anything in the file; only names mean anything."""
    assert resolve(prefs=FakePrefs(['not', 'a', 'theme'])) == 'default'


def test_set_active_synchronizes_the_colour_switch():
    Theme.set_active(resolve(prefs=FakePrefs('mono')))
    assert colors_enabled() is False

    Theme.set_active(resolve(theme='nord'))
    assert colors_enabled() is True


def test_the_screens_draw_through_the_switch():
    """``theme_attr`` is the name the screen code calls."""
    set_colors_enabled(False)

    assert main_module.theme_attr(Theme.WARNING) == curses.A_BOLD
    assert main_module.theme_attr(Theme.DANGER) == (
        curses.A_BOLD | curses.A_REVERSE)
