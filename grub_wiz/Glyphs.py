#!/usr/bin/env python3
"""grub-wiz's decorative glyphs, registered with console-window.

The mechanism used to live here: the table, the ASCII fallback per symbol, the
process-wide switch, the detection of what a terminal can encode, and the
report printed at start-up.  All of that is now ``console_window.glyphs``, so
every console-window app gets it -- and gets the *substitution* too: text handed
to the window is downgraded as it is drawn, which covers the symbols this module
never had to name.

What is left is the vocabulary.  A symbol that fails to draw does not fail
loudly -- the terminal shows a box (or nothing) and the row silently loses its
meaning: a missing ``✘`` looks exactly like the blank marker of an active
parameter.  So these are the symbols whose loss would change what the screen
says, each with a fallback that carries the same meaning in plain cells.

Registering them also teaches the library's transliterator, so ``⚠️`` in a
message string degrades to ``(!)`` even where nobody called ``alert()``.
"""

import sys

from console_window import Glyphs as _Glyphs

#: ``name -> (unicode, ascii)``.  The Unicode form is what the UI is designed
#: around; the ASCII form must carry the same meaning in plain cells.
GLYPHS = {
    'nav': ('⮜–⮞', '<->'),       # "cycle this value with left/right"
    'prev': ('⮜', '<'),          # predecessor arrow, used by the font check
    'next': ('⮞', '>'),          # successor arrow, used by the font check
    'warn': ('✘', 'X'),          # inactive parameter / inhibited warning
    'current': ('●', '*'),       # the backup recorded by this session
    'star': ('🟌', '*'),         # one warning star
    'sev_star': ('🟍', '*'),     # one severity star
    'alert': ('⚠️', '(!)'),      # marks a question/prompt
    'ellipsis': ('▶', '>'),      # "this line was truncated"
    'ellipsis_tail': ('⯈', '>'),  # the same marker at a row's right edge
    'ok': ('✓', 'OK'),
    'fail': ('✗', 'X'),
    'stop': ('🛑', 'STOP'),
}

#: Glyph names the font check prints, in reading order.
PROBE_NAMES = ('prev', 'next', 'warn', 'current', 'star', 'alert')


def register_all():
    """(Re)register grub-wiz's vocabulary with console-window.

    Called at import time.  It is public because the registry is process state:
    anything that resets it (a test, an app that reconfigures the symbol set)
    can put this application's symbols back with one call.
    """
    _Glyphs.register_many(GLYPHS, probe=PROBE_NAMES)


def get(name):
    """Return grub-wiz glyph *name* in the active set."""
    return _Glyphs.get(name)


def probe_text():
    """The real Unicode glyphs a user should look at (never the ASCII set)."""
    return _Glyphs.probe_text()


def is_ascii():
    """True when the plain-ASCII set is in use."""
    return _Glyphs.is_ascii()


def set_ascii(enabled):
    """Select the plain-ASCII set (True) or the Unicode one (False)."""
    _Glyphs.set_ascii(enabled)


# Named accessors keep call sites readable and typo-proof.
def nav():
    """The ``cycle with arrows`` hint."""
    return get('nav')


def warn():
    """Marks an inactive parameter or an inhibited warning."""
    return get('warn')


def current():
    """Marks the backup recorded by the current session."""
    return get('current')


def star():
    """One warning star."""
    return get('star')


def sev_star():
    """One severity star."""
    return get('sev_star')


def alert():
    """Marks a question/prompt."""
    return get('alert')


def ellipsis():
    """Marker appended to a truncated line."""
    return get('ellipsis')


def ellipsis_tail():
    """Marker placed at a row's right edge when it was truncated."""
    return get('ellipsis_tail')


def ok():
    """Marks a successful step."""
    return get('ok')


def fail():
    """Marks a failed step."""
    return get('fail')


def stop():
    """Marks a step that was refused for safety."""
    return get('stop')


class Glyphs:
    """Namespace facade so call sites can say ``Glyphs.warn()``.

    Everything here delegates to ``console_window.Glyphs``: the switch, the
    table and the substitution table are process state in one place, and this
    class only supplies grub-wiz's names for it.
    """

    register_all = staticmethod(register_all)
    get = staticmethod(get)
    probe_text = staticmethod(probe_text)
    is_ascii = staticmethod(is_ascii)
    set_ascii = staticmethod(set_ascii)
    nav = staticmethod(nav)
    warn = staticmethod(warn)
    current = staticmethod(current)
    star = staticmethod(star)
    sev_star = staticmethod(sev_star)
    alert = staticmethod(alert)
    ellipsis = staticmethod(ellipsis)
    ellipsis_tail = staticmethod(ellipsis_tail)
    ok = staticmethod(ok)
    fail = staticmethod(fail)
    stop = staticmethod(stop)


register_all()

if __name__ == '__main__':
    # `python -m grub_wiz.Glyphs` prints the font check: the row a user can look
    # at when a screen shows boxes, without starting the whole editor.
    sys.stdout.write(f'{probe_text()}\n')
