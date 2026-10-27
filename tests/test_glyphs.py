"""grub-wiz's glyph vocabulary, as registered with console-window.

The mechanism -- the table, the ASCII fallback, terminal detection, the
``--ascii`` switch and the substitution applied while drawing -- is
console-window's, and its own suite tests it.  What has to be true here is that
grub-wiz registers *its* symbols, that both spellings stay meaningful, and that
the registry's transliterator now covers this app's decoration for free.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from console_window import glyphs as library_glyphs  # noqa: E402
from grub_wiz import Glyphs as glyphs_mod  # noqa: E402
from grub_wiz.Glyphs import Glyphs  # noqa: E402


@pytest.fixture(autouse=True)
def reset_glyphs():
    """Both the switch and the registry are process state; never leak them."""
    Glyphs.register_all()
    Glyphs.set_ascii(False)
    yield
    Glyphs.register_all()
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
    for name, (unicode_text, ascii_text) in glyphs_mod.GLYPHS.items():
        assert unicode_text, name
        assert ascii_text, name
        # The fallback must be plain ASCII, or it could fail the same way.
        assert ascii_text.isascii(), name
        assert Glyphs.get(name) == unicode_text
        Glyphs.set_ascii(True)
        assert Glyphs.get(name) == ascii_text
        Glyphs.set_ascii(False)


def test_probe_shows_grub_wiz_symbols_even_in_ascii_mode():
    """The font check must print what might be missing, even under --ascii."""
    Glyphs.set_ascii(True)

    probe = Glyphs.probe_text()

    for char in ('⮜', '⮞', '✘', '●', '🟌', '⚠️'):
        assert char in probe


def test_unknown_glyph_name_is_a_loud_error():
    with pytest.raises(KeyError, match='nope'):
        Glyphs.get('nope')


def test_registered_symbols_are_downgraded_in_any_drawn_text():
    """The library transliterates; grub-wiz's registration is what it knows."""
    Glyphs.set_ascii(True)

    assert library_glyphs.transliterate(
        'abort 🛑 now ⚠️ then ▶') == 'abort STOP now (!) then >'


def test_prose_and_parameter_values_are_never_rewritten():
    Glyphs.set_ascii(True)

    value = 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"'
    assert library_glyphs.transliterate(value) == value
    # Real UTF-8 content is content, not decoration.
    assert library_glyphs.transliterate('Grüße aus Köln') == 'Grüße aus Köln'


def test_register_all_restores_the_vocabulary_after_a_reset():
    """Anything that clears the shared registry can put the app's names back."""
    library_glyphs.reset()
    with pytest.raises(KeyError):
        Glyphs.get('warn')

    Glyphs.register_all()

    assert Glyphs.get('warn') == '✘'
    assert library_glyphs.unicode_of('stop') == '🛑'


def test_the_app_never_ships_its_own_switch_or_report():
    """The mechanism is the library's; keeping a copy here would be drift."""
    assert not hasattr(Glyphs, 'terminal_report')
    assert not hasattr(glyphs_mod, 'ASCII_TERMS')
    assert not hasattr(glyphs_mod, 'LIMITED_TERMS')
