#!/usr/bin/env python3
"""The decorative glyphs grub-wiz draws, and how to live without them.

Every non-ASCII symbol the UI relies on for *meaning* lives here, together
with a plain-ASCII fallback and the checks that decide whether the fallback is
needed.  Keeping them in one table matters because a symbol that fails to draw
does not fail loudly: the terminal shows a box (or nothing) and the row
silently loses its meaning -- a missing ``✘`` looks exactly like the blank
marker of an active parameter.

What can and cannot be checked
------------------------------
Whether a terminal can *encode* UTF-8 is observable (the stream's encoding and
the locale).  Whether the *font* has a glyph for a code point is not: it is a
property of the emulator and the font it was given, invisible from inside the
process.  The detection is therefore split into three parts:

* :func:`terminal_report` reports what is detectable and sets
  ``ascii_required`` when UTF-8 output is impossible;
* the report always carries a *font check* line containing the real glyphs, so
  the user can look at them (or copy them into a shell) and judge;
* ``--ascii`` (:func:`set_ascii`) forces the fallback for everything else,
  including a font the check cannot see.

The application applies the policy once, before curses takes the terminal
(``grub_wiz.main.apply_glyph_policy``), and the HELP screen repeats the font
check because that is where a user goes when the screen looks wrong.
"""

import locale
import os
import sys
from dataclasses import dataclass
from typing import Mapping, Optional

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
    'ellipsis_tail': ('⯈', '>'), # the same marker at a row's right edge
    'ok': ('✓', 'OK'),
    'fail': ('✗', 'X'),
    'stop': ('🛑', 'STOP'),
}

#: Glyph names the font check prints, in reading order.
PROBE_NAMES = ('prev', 'next', 'warn', 'current', 'star', 'alert')

#: Terminal types that cannot draw the Unicode set at all.
ASCII_TERMS = frozenset({'dumb'})

#: Terminals that encode UTF-8 but whose default font usually lacks the
#: emoji-style glyphs; the Linux console is the common case.
LIMITED_TERMS = frozenset({'linux', 'cons25'})

#: Module-level switch.  It is process state on purpose: the choice is made
#: once at start-up, before curses draws anything, and every draw afterwards
#: must agree with it.
_ascii_mode = False


def set_ascii(enabled: bool) -> None:
    """Select the plain-ASCII glyph set (True) or the Unicode one (False)."""
    global _ascii_mode  # pylint: disable=global-statement
    _ascii_mode = bool(enabled)


def is_ascii() -> bool:
    """True when the ASCII fallback is in use."""
    return _ascii_mode


def get(name: str) -> str:
    """Return glyph *name* in the active set."""
    try:
        unicode_text, ascii_text = GLYPHS[name]
    except KeyError as exc:
        raise KeyError(f'unknown glyph {name!r}') from exc
    return ascii_text if _ascii_mode else unicode_text


# Named accessors keep call sites readable and typo-proof.
def nav() -> str:
    """The ``cycle with arrows`` hint."""
    return get('nav')


def warn() -> str:
    """Marks an inactive parameter or an inhibited warning."""
    return get('warn')


def current() -> str:
    """Marks the backup recorded by the current session."""
    return get('current')


def star() -> str:
    """One warning star."""
    return get('star')


def sev_star() -> str:
    """One severity star."""
    return get('sev_star')


def alert() -> str:
    """Marks a question/prompt."""
    return get('alert')


def ellipsis() -> str:
    """Marker appended to a truncated line."""
    return get('ellipsis')


def ellipsis_tail() -> str:
    """Marker placed at a row's right edge when it was truncated."""
    return get('ellipsis_tail')


def ok() -> str:
    """Marks a successful step."""
    return get('ok')


def fail() -> str:
    """Marks a failed step."""
    return get('fail')


def stop() -> str:
    """Marks a step that was refused for safety."""
    return get('stop')


def probe_text() -> str:
    """The real Unicode glyphs a user should look at (never the ASCII set).

    The font check has to print the glyph that might be missing; printing the
    fallback would check nothing.
    """
    return ' '.join(GLYPHS[name][0] for name in PROBE_NAMES)


@dataclass(frozen=True)
class TerminalReport:
    """What could be learned about this terminal's glyph support."""

    encoding: str
    utf8: bool
    term: str
    ascii_required: bool
    notes: tuple = ()


def _normalized(encoding: Optional[str]) -> str:
    return (encoding or '').strip().lower().replace('-', '').replace('_', '')


def _is_utf8(encoding: Optional[str]) -> bool:
    """True for the UTF-8 family (``utf-8``, ``UTF8``, ``utf_8``, ...)."""
    name = _normalized(encoding)
    return name.startswith('utf8') or name == 'utf'


def terminal_report(environ: Optional[Mapping] = None,
                    stream: object = None) -> TerminalReport:
    """Describe this terminal's ability to draw the UI's symbols.

    *environ* and *stream* exist so tests can supply a fake terminal.  The
    result is advisory except for ``ascii_required``, which is True only when
    the terminal provably cannot carry the glyphs (non-UTF-8 encoding, or
    ``TERM=dumb``).  A font's glyph coverage cannot be observed; the font-check
    note asks the user to look instead.
    """
    env = os.environ if environ is None else environ
    out = sys.stdout if stream is None else stream
    encoding = (getattr(out, 'encoding', None)
                or locale.getpreferredencoding(False) or '')
    term = str(env.get('TERM', '')).strip().lower()
    notes = []
    ascii_required = False

    utf8 = _is_utf8(encoding)
    if not utf8:
        ascii_required = True
        notes.append(
            f'output encoding is {encoding or "unknown"}, which cannot show '
            'the symbols grub-wiz draws; using ASCII symbols instead')
    if term in ASCII_TERMS:
        ascii_required = True
        notes.append(
            f'TERM={term} cannot draw the symbols; using ASCII symbols instead')

    if ascii_required:
        notes.append('for the full symbol set, run in a UTF-8 locale inside a '
                     'Unicode-capable terminal')
        return TerminalReport(encoding=encoding, utf8=utf8, term=term,
                              ascii_required=True,
                              notes=tuple(notes))

    if term in LIMITED_TERMS:
        notes.append(
            f'TERM={term} uses a console font that often lacks some of these '
            'symbols; restart with --ascii if any line shows boxes')
    notes.append(
        f'font check: {probe_text()}  (if any symbol is a box or blank, use --ascii)')
    return TerminalReport(encoding=encoding, utf8=utf8, term=term,
                          ascii_required=False, notes=tuple(notes))


class Glyphs:
    """Namespace facade over the module's single piece of state.

    The implementation is module-level functions (so the switch is process
    state, not per-instance state); this class gives call sites a readable
    ``Glyphs.warn()`` spelling without inventing an object to pass around.
    """

    set_ascii = staticmethod(set_ascii)
    is_ascii = staticmethod(is_ascii)
    get = staticmethod(get)
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
    probe_text = staticmethod(probe_text)
    terminal_report = staticmethod(terminal_report)
