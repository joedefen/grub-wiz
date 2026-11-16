#!/usr/bin/env python3
"""grub-wiz's decorative vocabulary, resolved from console-window's catalog.

Up to console-window 3.0 this module registered its own table.  3.1 folded the
two-cell "mark" API into ``Glyphs``: an emoji is now just a ``Glyph`` in the
``'emoji'`` group, and a library name such as ``ok`` or ``warn`` is read-only
(registering it replaces the picture for every caller).  Almost every symbol
grub-wiz draws is now a catalog name, and the library owns the ASCII fallback,
the width measurement and the substitution applied while drawing.  The one
exception is the REVIEW screen's severity mark (``✱``), which has no catalog
entry; it is registered below under an app-only name, with its own one-cell
ASCII fallback, so it follows the same rules as everything else.

This module keeps the app's *role* vocabulary so call sites read as intent
(``Glyphs.warn()`` rather than ``Glyphs.get('cross_heavy')``) and so a future
form change happens in one place.  Ask the registry by name; never paste the
symbol.

A note on the stars and the bell: these stay emoji.  3.1's width contract is
what makes that safe -- ``star`` (⭐) and ``bell`` (🔔) are East-Asian ``W``, so
they measure two cells with or without a variation selector, and their ASCII
spellings (``'s '`` / ``'n '``) are two cells too, so switching to ``--ascii``
never shifts a column.  The prompt marker is a bell rather than the glowing
star: the app already uses ⭐ for warning severity, and two near-identical
stars would read as the same badge at a glance.
"""

import sys

from console_window import Glyphs as _Glyphs

#: REVIEW's severity mark.  ``✱`` (U+2731) is East-Asian ``N`` and measures one
#: cell, so it takes the row's own colour and alignment like the text around it
#: (an emoji star is drawn in its own colours by the terminal).  It is an
#: app-only name because the library catalog has no asterisk.
SEVERITY_MARK = ('severity', '✱', '*')

#: Names the font check prints, in reading order.  They are Unicode forms, not
#: the active set, so a user still sees what a broken font is missing.
PROBE_NAMES = ('tri_left_small', 'tri_right_small', 'cross_heavy',
               'circle_filled', 'severity', 'star', 'bell')


def register_all():
    """Teach the library the app's one custom glyph.

    The registry is process state: ``Glyphs.reset()`` drops every application
    registration, so the fixtures that reset it call this afterwards to put
    the REVIEW severity mark back.  A repeated call is harmless.
    """
    _Glyphs.register(*SEVERITY_MARK, probe=True)


register_all()


def get(name):
    """Return catalog glyph *name* in the active set."""
    return _Glyphs.get(name)


def probe_text():
    """The real Unicode glyphs a user should look at (never the ASCII set)."""
    return ''.join(_Glyphs.unicode_of(name) for name in PROBE_NAMES)


def is_ascii():
    """True when the plain-ASCII set is in use."""
    return _Glyphs.is_ascii()


def set_ascii(enabled):
    """Select the plain-ASCII set (True) or the Unicode one (False)."""
    _Glyphs.set_ascii(enabled)


# Named accessors keep call sites readable and typo-proof.
def nav():
    """The ``cycle this value with left/right`` hint (one cell each)."""
    return (_Glyphs.get('tri_left_small') + _Glyphs.get('en_dash')
            + _Glyphs.get('tri_right_small'))


def prev():
    """Predecessor arrow (one cell; ASCII ``<``)."""
    return _Glyphs.get('tri_left_small')


def next():
    """Successor arrow (one cell; ASCII ``>``)."""
    return _Glyphs.get('tri_right_small')


def warn():
    """Marks an inactive parameter or an inhibited warning."""
    return _Glyphs.get('cross_heavy')


def current():
    """Marks the backup recorded by the current session."""
    return _Glyphs.get('circle_filled')


def severity():
    """REVIEW's warning-severity mark (one cell; ASCII ``'*'``)."""
    return _Glyphs.get('severity')


def sev_star():
    """The WARNINGS screen's severity stars (emoji, two cells)."""
    return _Glyphs.get('star')


def alert():
    """Marks a question/prompt with the bell (two cells; ASCII ``'n '``).

    Deliberately not a star: the WARNINGS screen already uses ``⭐`` for
    severity, and a glowing star next to a plain one reads as the same badge.
    """
    return _Glyphs.get('bell')


def ellipsis():
    """Marker appended to a truncated line (one cell)."""
    return _Glyphs.get('tri_right_small')


def ellipsis_tail():
    """Marker placed at a row's right edge when it was truncated (one cell)."""
    return _Glyphs.get('tri_right_small')


def ok():
    """Marks a successful step."""
    return _Glyphs.get('check')


def fail():
    """Marks a failed step."""
    return _Glyphs.get('cross')


def stop():
    """Marks a step that was refused for safety."""
    return _Glyphs.get('stop')


class Glyphs:
    """Namespace facade so call sites can say ``Glyphs.warn()``.

    Everything here delegates to ``console_window.Glyphs``: the switch, the
    catalog and the substitution table are process state in one place, and this
    class only supplies grub-wiz's role names for it.
    """

    register_all = staticmethod(register_all)
    get = staticmethod(get)
    probe_text = staticmethod(probe_text)
    is_ascii = staticmethod(is_ascii)
    set_ascii = staticmethod(set_ascii)
    nav = staticmethod(nav)
    prev = staticmethod(prev)
    next = staticmethod(next)
    warn = staticmethod(warn)
    current = staticmethod(current)
    severity = staticmethod(severity)
    sev_star = staticmethod(sev_star)
    alert = staticmethod(alert)
    ellipsis = staticmethod(ellipsis)
    ellipsis_tail = staticmethod(ellipsis_tail)
    ok = staticmethod(ok)
    fail = staticmethod(fail)
    stop = staticmethod(stop)


if __name__ == '__main__':
    # `python -m grub_wiz.Glyphs` prints the font check: the row a user can look
    # at when a screen shows boxes, without starting the whole editor.
    sys.stdout.write(f'{probe_text()}\n')
