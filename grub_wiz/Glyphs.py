#!/usr/bin/env python3
"""grub-wiz's decorative vocabulary, resolved from console-window's catalog."""
import sys

from console_window import Glyphs as _Glyphs

SEVERITY_MARK = ('severity', '✱', '*')
PROBE_NAMES = ('tri_left_small', 'tri_right_small', 'cross_heavy',
               'circle_filled', 'severity', 'star', 'bell')


def register_all():
    """Teach the library the app's one custom glyph."""
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
    """Marks a question/prompt with the bell (two cells; ASCII ``'n '``)."""
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
    """Namespace facade so call sites can say ``Glyphs.warn()``"""

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
    sys.stdout.write(f'{probe_text()}\n')
