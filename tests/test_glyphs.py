"""grub-wiz's role vocabulary, resolved from console-window's 3.1 catalog.

The mechanism -- the catalog, the ASCII fallback, terminal detection, the
``--ascii`` switch and the substitution applied while drawing -- is
console-window's, and its own suite tests it.  What has to be true here is that
grub-wiz's *role* names resolve to the intended catalog glyphs, that the emoji
stay emoji (⭐/🔔), that ``✱`` is the app's one registered mark, and that no
library name is shadowed by an app registration.
"""

import sys
import unicodedata
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
    assert Glyphs.alert() == '🔔'          # bell, two cells
    assert Glyphs.warn() == '✘'            # cross_heavy (inactive/inhibited)
    assert Glyphs.severity() == '✱'        # app mark, one cell
    assert Glyphs.sev_star() == '⭐'       # WARN screen, two-cell emoji
    assert Glyphs.current() == '●'
    assert Glyphs.nav() == '◂–▸'


def test_ascii_swaps_every_meaningful_glyph():
    Glyphs.set_ascii(True)

    assert Glyphs.is_ascii() is True
    assert Glyphs.alert() == 'n '          # two cells, like the emoji
    assert Glyphs.warn() == 'x'
    assert Glyphs.severity() == '*'
    assert Glyphs.sev_star() == 's '       # two cells, like the emoji
    assert Glyphs.current() == '@'
    assert Glyphs.nav() == '<->'


def test_every_role_has_a_meaningful_fallback():
    roles = (Glyphs.nav, Glyphs.prev, Glyphs.next, Glyphs.warn,
             Glyphs.current, Glyphs.severity, Glyphs.sev_star, Glyphs.alert,
             Glyphs.ellipsis, Glyphs.ellipsis_tail, Glyphs.ok, Glyphs.fail,
             Glyphs.stop)
    for role in roles:
        unicode_text = role()
        assert unicode_text, role.__name__
        Glyphs.set_ascii(True)
        ascii_text = role()
        Glyphs.set_ascii(False)
        assert ascii_text, role.__name__
        # The fallback must be plain ASCII, or it could fail the same way.
        assert ascii_text.isascii(), role.__name__


def test_the_emoji_rules_are_respected():
    """The prompt bell and the WARN stars stay emoji, and measure two cells."""
    for name in ('star', 'bell'):
        glyph = library_glyphs.lookup(name)
        assert glyph.group == 'emoji'
        assert library_glyphs.string_width(glyph.unicode) == 2
        assert library_glyphs.string_width(glyph.ascii) == 2


def test_the_review_mark_is_a_clean_one_cell_symbol():
    """``✱`` is East-Asian N and passes the audit; only the app must register it."""
    assert unicodedata.east_asian_width('✱') == 'N'
    assert library_glyphs.string_width('✱') == 1
    assert library_glyphs.find_issues('✱') == []
    assert library_glyphs.lookup('severity').group == 'application'
    assert library_glyphs.lookup('severity').ascii == '*'


def test_probe_shows_grub_wiz_symbols_even_in_ascii_mode():
    """The font check must print what might be missing, even under --ascii."""
    Glyphs.set_ascii(True)

    probe = Glyphs.probe_text()

    for char in ('◂', '▸', '✘', '●', '✱', '⭐', '🔔'):
        assert char in probe


def test_unknown_glyph_name_is_a_loud_error():
    with pytest.raises(KeyError, match='nope'):
        Glyphs.get('nope')


def test_the_library_names_are_never_shadowed():
    """3.1 made a library name read-only; grub-wiz must not replace any."""
    assert library_glyphs.get('ok') == '✅'
    assert library_glyphs.get('fail') == '❌'
    assert library_glyphs.get('stop') == '🛑'
    assert library_glyphs.get('warn') == '⚠'


def test_registered_symbols_are_downgraded_in_any_drawn_text():
    """The library transliterates; the app's roles are all catalog entries."""
    Glyphs.set_ascii(True)

    drawn = '◂–▸ ✘ ● ⭐ ✱ 🔔 ✓ ✗ 🛑'
    assert library_glyphs.transliterate(drawn) == '<-> x @ s  * n  v x - '


def test_prose_and_parameter_values_are_never_rewritten():
    Glyphs.set_ascii(True)

    value = 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"'
    assert library_glyphs.transliterate(value) == value
    # Real UTF-8 content is content, not decoration.
    assert library_glyphs.transliterate('Grüße aus Köln') == 'Grüße aus Köln'


def test_the_catalog_keeps_the_app_vocabulary_after_a_reset():
    """A reset drops the one app mark; ``register_all()`` puts it back."""
    library_glyphs.reset()

    with pytest.raises(KeyError):
        Glyphs.get('severity')
    Glyphs.register_all()

    assert Glyphs.severity() == '✱'
    assert Glyphs.warn() == '✘'
    assert library_glyphs.unicode_of('stop') == '🛑'


def test_the_app_never_ships_its_own_switch_or_report():
    """The mechanism is the library's; keeping a copy here would be drift."""
    assert not hasattr(Glyphs, 'terminal_report')
    assert not hasattr(glyphs_mod, 'ASCII_TERMS')
    assert not hasattr(glyphs_mod, 'LIMITED_TERMS')
