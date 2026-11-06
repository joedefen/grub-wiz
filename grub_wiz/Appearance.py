#!/usr/bin/env python3
"""Semantic colour roles, and the switch that turns colour off.

Colour here is decoration, never information.  REVIEW paints a few rows by role
(warnings, guidance, the value being replaced, the commit prompt); with colour
off every role degrades to an attribute, so the same hierarchy survives on a
monochrome terminal or under ``--no-color``.

The role ids are ``console_window.Theme``'s semantic pairs rather than literal
colour numbers.  console-window installs those pairs at startup and re-installs
them whenever a theme is applied, so changing the active theme recolours the
whole UI without an edit to any draw code.

``--no-color`` is a per-run switch, not a saved preference: it replaces the
pairs with the attributes in :data:`MONO_ROLES` for this process.  Picking a
theme from the COLOR THEME screen is a request for colour, so it lifts the
switch again (vappman's ``mono`` appearance behaves the same way).
"""

import curses
import os

from console_window import Theme

# Role -> attribute used when colour is off.  The hierarchy is kept with
# emphasis instead of hue: the commit prompt is bold+reverse, warnings and the
# replaced value are bold, and advice carries nothing (its guidance box and the
# enum markers already distinguish it).
MONO_ROLES = {
    Theme.DANGER: curses.A_BOLD | curses.A_REVERSE,
    Theme.ERROR: curses.A_BOLD | curses.A_REVERSE,
    Theme.WARNING: curses.A_BOLD,
    Theme.SUCCESS: curses.A_BOLD,
    Theme.EMPHASIS: curses.A_BOLD,
    Theme.INFO: curses.A_NORMAL,
    Theme.PROGRESS: curses.A_NORMAL,
    Theme.OLD_SUCCESS: curses.A_NORMAL,
    Theme.HOTSWAP: curses.A_NORMAL,
}

# Process-wide switch, seeded at startup by --no-color / NO_COLOR.  One
# terminal, so one decision.
_COLORS_ENABLED = True


def set_colors_enabled(enabled):
    """Turn semantic colour on or off for the whole process."""
    global _COLORS_ENABLED  # pylint: disable=global-statement
    _COLORS_ENABLED = bool(enabled)


def colors_enabled():
    """True while semantic roles resolve to colour pairs rather than attributes."""
    return _COLORS_ENABLED


def resolve_colors(no_color=False, theme=None, environ=None):
    """Starting colour switch from the flag, an explicit theme and the environment.

    Precedence, highest first: ``--no-color``, an explicit ``--theme`` (a
    statement of intent, so it is honoured even when ``NO_COLOR`` is set), the
    ``NO_COLOR`` convention (any non-empty value disables colour, per
    no-color.org), then colour on.
    """
    env = os.environ if environ is None else environ
    if no_color:
        return False
    if theme:
        return True
    return not bool(env.get('NO_COLOR'))


def semantic_attr(pair_id):
    """Attribute for a console-window ``Theme`` role, or plain when no colour.

    With colour off the role becomes an attribute from :data:`MONO_ROLES`.
    Otherwise both ``curses.has_colors()`` and ``curses.color_pair()`` can raise
    (``color_pair()`` refuses to run before ``initscr()``), and a failed lookup
    must never abort a redraw, so any failure degrades to plain text.
    """
    if not _COLORS_ENABLED:
        return MONO_ROLES.get(pair_id, curses.A_NORMAL)
    try:
        if not curses.has_colors():
            return 0
        return curses.color_pair(pair_id)
    except Exception:                       # terminal not initialised yet
        return 0
