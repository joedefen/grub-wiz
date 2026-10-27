"""Glyph selection and terminal detectability.

Part of the UI's meaning lives in non-ASCII symbols, so ``--ascii`` has to swap
every one of them consistently, and the start-up report must stay honest about
what it can and cannot see: the terminal's *encoding* is observable, a font's
glyph coverage is not.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz import Glyphs as glyphs_mod  # noqa: E402
from grub_wiz.Glyphs import Glyphs  # noqa: E402


@pytest.fixture(autouse=True)
def reset_glyphs():
    """The ASCII switch is process state; never leak it between tests."""
    Glyphs.set_ascii(False)
    yield
    Glyphs.set_ascii(False)


def test_unicode_is_the_default_set():
    assert Glyphs.is_ascii() is False
    assert Glyphs.alert() == '⚠️'
    assert Glyphs.warn() == '✘'
    assert Glyphs.star() == '🟌'
    assert Glyphs.current() == '●'
    assert Glyphs.nav() == '⮜–⮞'


def test_ascii_swaps_every_meaningful_glyph():
    Glyphs.set_ascii(True)

    assert Glyphs.is_ascii() is True
    assert Glyphs.alert() == '(!)'
    assert Glyphs.warn() == 'X'
    assert Glyphs.star() == '*'
    assert Glyphs.current() == '*'
    assert Glyphs.nav() == '<->'


def test_every_glyph_has_both_forms():
    for name, pair in glyphs_mod.GLYPHS.items():
        unicode_text, ascii_text = pair
        assert unicode_text, name
        assert ascii_text, name
        # The fallback must be plain ASCII, or it could fail the same way.
        assert ascii_text.isascii(), name


def test_probe_always_shows_the_unicode_glyphs():
    """The font check must print what might be missing, even under --ascii."""
    Glyphs.set_ascii(True)

    probe = Glyphs.probe_text()

    for char in ('⮜', '⮞', '✘', '●', '🟌', '⚠️'):
        assert char in probe


def test_unknown_glyph_name_is_a_loud_error():
    with pytest.raises(KeyError, match='nope'):
        Glyphs.get('nope')


class _FakeOut:
    """Stand-in for a text stream: only ``encoding`` is consulted."""

    def __init__(self, encoding):
        self.encoding = encoding


def _report(encoding='UTF-8', term='xterm-256color'):
    return Glyphs.terminal_report(environ={'TERM': term},
                                  stream=_FakeOut(encoding))


@pytest.mark.parametrize('encoding', ['UTF-8', 'utf8', 'UTF8', 'utf_8'])
def test_utf8_spellings_are_recognized(encoding):
    assert _report(encoding=encoding).utf8 is True


def test_utf8_terminal_needs_no_fallback_but_asks_for_a_font_check():
    report = _report()

    assert report.ascii_required is False
    assert any('font check' in note for note in report.notes)
    # The check is only useful if it shows the real characters.
    assert any('⚠️' in note for note in report.notes)


@pytest.mark.parametrize('encoding', ['ascii', 'ANSI_X3.4-1968', 'latin-1'])
def test_non_utf8_encoding_requires_ascii(encoding):
    report = _report(encoding=encoding)

    assert report.ascii_required is True
    assert any('ASCII symbols' in note for note in report.notes)


def test_dumb_terminal_requires_ascii():
    report = _report(term='dumb')

    assert report.ascii_required is True
    assert any('TERM=dumb' in note for note in report.notes)


def test_linux_console_warns_but_does_not_force_ascii():
    """The console font is usually limited, but that cannot be proven."""
    report = _report(term='linux')

    assert report.ascii_required is False
    assert any('--ascii' in note for note in report.notes)
