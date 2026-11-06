"""grub-wiz's wiring to console-window's appearance switch.

The precedence rules, the mono role table and the fail-safe lookup live in
``console_window.appearance`` and are tested there.  These tests only prove the
two things this app owns: it seeds the process-wide switch from the flags it
parsed, and its draw sites resolve roles through that switch.
"""

import curses
from types import SimpleNamespace

from console_window import Theme, colors_enabled, set_colors_enabled

from grub_wiz import main as main_module


def apply_policy(no_color=False, theme=None):
    """Call the seeding hook with the shape argparse hands the application."""
    main_module.apply_color_policy(
        SimpleNamespace(no_color=no_color, theme=theme))


def test_the_application_seeds_the_switch_from_the_parsed_flags():
    apply_policy(no_color=True)
    assert colors_enabled() is False

    apply_policy(no_color=False)
    assert colors_enabled() is True


def test_the_no_color_flag_wins_over_a_theme():
    apply_policy(no_color=True, theme='nord')
    assert colors_enabled() is False


def test_an_explicit_theme_asks_for_colour_even_under_no_color(monkeypatch):
    """``--theme`` is a statement of intent, so it still asks for colour."""
    monkeypatch.setenv('NO_COLOR', '1')

    apply_policy(theme='nord')
    assert colors_enabled() is True


def test_the_environment_convention_is_honoured(monkeypatch):
    monkeypatch.setenv('NO_COLOR', '1')

    apply_policy()
    assert colors_enabled() is False


def test_no_options_means_colour_on():
    """Tests and embedded use pass no namespace at all."""
    main_module.apply_color_policy(None)
    assert colors_enabled() is True


def test_the_screens_draw_through_the_switch():
    """``theme_attr`` is the name the screen code calls."""
    set_colors_enabled(False)

    assert main_module.theme_attr(Theme.WARNING) == curses.A_BOLD
    assert main_module.theme_attr(Theme.DANGER) == (
        curses.A_BOLD | curses.A_REVERSE)
