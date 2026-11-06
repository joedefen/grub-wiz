"""The appearance switch behind ``--no-color`` and the ``NO_COLOR`` convention.

Colour is decoration: with the switch off every semantic role resolves to an
attribute, so REVIEW keeps its emphasis hierarchy on a monochrome run.  The
switch is process-wide, and the autouse fixture in ``conftest.py`` puts it back
to "colour on" after each test.
"""

import curses
from types import SimpleNamespace

from console_window import Theme

from grub_wiz import Appearance
from grub_wiz import main as main_module


def test_colour_is_on_unless_something_turns_it_off():
    assert Appearance.resolve_colors(environ={}) is True


def test_the_no_color_flag_turns_colour_off():
    assert Appearance.resolve_colors(no_color=True, environ={}) is False


def test_the_no_color_flag_beats_an_explicit_theme():
    assert Appearance.resolve_colors(no_color=True, theme='nord',
                                     environ={}) is False


def test_an_explicit_theme_beats_the_environment_convention():
    """``--theme`` is a statement of intent, so it still asks for colour."""
    assert Appearance.resolve_colors(theme='nord',
                                     environ={'NO_COLOR': '1'}) is True


def test_the_environment_convention_disables_colour():
    assert Appearance.resolve_colors(environ={'NO_COLOR': '1'}) is False


def test_an_empty_no_color_variable_is_not_a_request():
    """no-color.org disables colour only for a non-empty value."""
    assert Appearance.resolve_colors(environ={'NO_COLOR': ''}) is True


def test_the_application_seeds_the_switch_from_the_parsed_flags(monkeypatch):
    monkeypatch.delenv('NO_COLOR', raising=False)

    main_module.apply_color_policy(
        SimpleNamespace(no_color=True, theme=None))
    assert Appearance.colors_enabled() is False

    main_module.apply_color_policy(
        SimpleNamespace(no_color=False, theme=None))
    assert Appearance.colors_enabled() is True


def test_colour_off_keeps_the_role_hierarchy_as_attributes():
    Appearance.set_colors_enabled(False)

    assert (Appearance.semantic_attr(Theme.DANGER)
            == curses.A_BOLD | curses.A_REVERSE)
    assert Appearance.semantic_attr(Theme.WARNING) == curses.A_BOLD
    assert Appearance.semantic_attr(Theme.SUCCESS) == curses.A_BOLD
    assert Appearance.semantic_attr(Theme.INFO) == curses.A_NORMAL
    # A role with no mono mapping degrades to plain text, not to an error.
    assert Appearance.semantic_attr(Theme.DEFAULT) == curses.A_NORMAL


def test_the_screens_draw_through_the_switch():
    """``theme_attr`` is the name the screen code calls."""
    Appearance.set_colors_enabled(False)

    assert main_module.theme_attr(Theme.WARNING) == curses.A_BOLD
