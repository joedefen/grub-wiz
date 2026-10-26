"""The automatic backup tag: classification and abbreviation.

The tag is a hint, so these tests pin the parts a user reads: which category
wins, which parameter represents it, and how a long name is shortened.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz.BackupTag import (  # noqa: E402
    ADDED,
    CHANGED,
    MAX_PARAM_LEN,
    REMOVED,
    abbreviate,
    change_tag,
    classify,
    words_of,
)
from grub_wiz.GrubFile import GrubFile  # noqa: E402


ABSENT = GrubFile.ABSENT
COMMENT = GrubFile.COMMENT


# --- abbreviation ----------------------------------------------------------

def test_the_prefix_is_dropped_and_one_word_is_capitalized():
    assert abbreviate('GRUB_TIMEOUT') == 'Timeout'


def test_two_words_get_six_characters_each():
    assert abbreviate('GRUB_DISABLE_SUBMENU') == 'DisablSubmen'
    assert abbreviate('GRUB_CMDLINE_LINUX') == 'CmdlinLinux'


def test_three_words_get_four_characters_each():
    assert abbreviate('GRUB_CMDLINE_LINUX_DEFAULT') == 'CmdlLinuDefa'


def test_four_words_get_three_characters_each():
    assert abbreviate('GRUB_ALPHA_BETA_GAMMA_DELTA') == 'AlpBetGamDel'


def test_five_words_use_three_three_then_twos():
    assert abbreviate('GRUB_ALPHA_BETA_GAMMA_DELTA_EPSILON') == 'AlpBetGaDeEp'


def test_six_words_get_two_characters_each():
    assert abbreviate('GRUB_ALPHA_BETA_GAMMA_DELTA_EPSILON_ZETA') == 'AlBeGaDeEpZe'


def test_more_than_six_words_only_use_the_first_six():
    assert abbreviate(
        'GRUB_ALPHA_BETA_GAMMA_DELTA_EPSILON_ZETA_ETA') == 'AlBeGaDeEpZe'


def test_only_the_grub_prefix_is_stripped():
    assert abbreviate('SUSE_FOO_BAR') == 'SuseFooBar'
    assert words_of('SUSE_FOO_BAR') == ['SUSE', 'FOO', 'BAR']


def test_empty_chunks_are_skipped():
    assert abbreviate('GRUB_FOO__BAR') == 'FooBar'
    assert words_of('GRUB_') == []


def test_the_result_never_exceeds_the_limit():
    for name in ('GRUB_SUPERCALIFRAGILISTIC', 'GRUB_A_B_C_D_E_F_G'):
        assert len(abbreviate(name)) <= MAX_PARAM_LEN


# --- classification --------------------------------------------------------

def test_classify_uses_the_active_state():
    assert classify(ABSENT, '5') == ADDED
    assert classify(COMMENT, '5') == ADDED
    assert classify('5', ABSENT) == REMOVED
    assert classify('5', COMMENT) == REMOVED
    assert classify('5', '9') == CHANGED
    assert classify('5', '5') is None
    assert classify(COMMENT, COMMENT) is None


def test_change_tag_is_none_without_a_diff():
    assert change_tag({}) is None
    assert change_tag({'GRUB_TIMEOUT': (COMMENT, COMMENT)}) is None


def test_change_tag_marks_additions_and_drops_the_prefix():
    assert change_tag({'GRUB_DISABLE_SUBMENU': (ABSENT, 'true')}) == '+DisablSubmen'


def test_change_tag_marks_removals():
    assert change_tag({'GRUB_THEME': ('theme', ABSENT)}) == '-Theme'


def test_change_tag_marks_changes():
    assert change_tag({'GRUB_TIMEOUT': ('5', '9')}) == '~Timeout'


def test_additions_outrank_removals_which_outrank_changes():
    diffs = {
        'GRUB_THEME': ('theme', ABSENT),
        'GRUB_TIMEOUT': ('5', '9'),
        'GRUB_DISABLE_SUBMENU': (ABSENT, 'true'),
    }

    assert change_tag(diffs) == '+DisablSubmen+2'

    del diffs['GRUB_DISABLE_SUBMENU']
    assert change_tag(diffs) == '-Theme+1'

    del diffs['GRUB_THEME']
    assert change_tag(diffs) == '~Timeout'


def test_the_first_parameter_of_the_category_represents_it():
    diffs = {
        'GRUB_THEME': (ABSENT, 'theme'),
        'GRUB_TIMEOUT': (ABSENT, '5'),
    }

    assert change_tag(diffs) == '+Theme+1'


def test_the_count_is_the_number_touched_minus_one():
    diffs = {
        'GRUB_TIMEOUT': ('5', '9'),
        'GRUB_THEME': ('a', 'b'),
        'GRUB_GFXMODE': ('auto', '1024x768'),
    }

    assert change_tag(diffs) == '~Timeout+2'


def test_the_count_covers_every_category():
    diffs = {
        'GRUB_TIMEOUT': ('5', '9'),
        'GRUB_THEME': ('a', ABSENT),
        'GRUB_DISABLE_SUBMENU': (ABSENT, 'true'),
    }

    assert change_tag(diffs) == '+DisablSubmen+2'
