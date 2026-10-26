"""Confirmations are inline lines, not modal dialogs.

The REVIEW ``w`` action asks with a header line just above the divider, so the
screen keeps showing the changes being committed.  ESC cancels, the confirming
key continues the action, and every other key is ignored while the prompt is
live.  A prompt that only concerns one row (the RESTORE ``t`` retag) is drawn
directly below that row instead.
"""

import curses as cs
from pathlib import Path
from types import SimpleNamespace

from grub_wiz.main import (
    GrubWiz,
    InlineConfirmPrompt,
    RestoreScreen,
    ReviewScreen,
)


def make_gw():
    """Build the minimum GrubWiz state the inline-confirm helpers touch."""
    gw = object.__new__(GrubWiz)
    gw.win = SimpleNamespace(passthrough_mode=False, cols=80)
    gw.inline_confirm = InlineConfirmPrompt()
    gw._confirm_prev_passthrough = False
    return gw


def test_prompt_is_rendered_as_a_single_header_line():
    gw = make_gw()

    assert gw.begin_confirm('Delete backup') is True

    assert (gw.inline_confirm.get_display_string()
            == '⚠️ Delete backup  [Press "y" or ESC]')


def test_confirming_key_runs_the_callback_after_the_prompt_is_gone():
    gw = make_gw()
    answers = []
    gw.begin_confirm('Commit', on_confirm=answers.append)

    assert gw.handle_confirm_key(ord('y')) is True

    assert answers == ['y']
    assert gw.inline_confirm.is_active is False
    assert gw.inline_confirm.get_display_string() == ''


def test_escape_cancels_without_confirming():
    gw = make_gw()
    calls = []
    gw.begin_confirm('Commit',
                     on_confirm=lambda answer: calls.append(answer),
                     on_cancel=lambda: calls.append('cancel'))

    assert gw.handle_confirm_key(27) is True

    assert calls == ['cancel']
    assert gw.inline_confirm.is_active is False


def test_other_keys_are_ignored_while_the_prompt_is_live():
    gw = make_gw()
    confirmed = []
    gw.begin_confirm('Commit', on_confirm=confirmed.append)

    for key in (ord('n'), ord('w'), ord('q'), cs.KEY_DOWN):
        assert gw.handle_confirm_key(key) is True

    assert confirmed == []
    assert gw.inline_confirm.is_active is True


def test_idle_timeout_keeps_the_prompt_live():
    gw = make_gw()
    gw.begin_confirm('Commit')

    assert gw.handle_confirm_key(None) is True
    assert gw.inline_confirm.is_active is True


def test_begin_confirm_enables_passthrough_and_end_restores_it():
    gw = make_gw()
    assert gw.win.passthrough_mode is False

    gw.begin_confirm('Commit')
    assert gw.win.passthrough_mode is True

    gw.handle_confirm_key(27)
    assert gw.win.passthrough_mode is False


def test_begin_confirm_restores_a_previously_enabled_passthrough():
    gw = make_gw()
    gw.win.passthrough_mode = True

    gw.begin_confirm('Commit')
    gw.handle_confirm_key(27)

    assert gw.win.passthrough_mode is True


def test_callback_may_start_the_next_prompt():
    gw = make_gw()
    second = []
    gw.begin_confirm('First', on_confirm=lambda _answer: gw.begin_confirm(
        'Second', on_confirm=second.append))

    gw.handle_confirm_key(ord('y'))

    assert gw.inline_confirm.is_active is True
    assert (gw.inline_confirm.get_display_string()
            == '⚠️ Second  [Press "y" or ESC]')
    assert gw.win.passthrough_mode is True

    gw.handle_confirm_key(ord('y'))
    assert second == ['y']


def test_header_scope_draws_the_prompt_as_the_last_header_line():
    gw = make_gw()
    headers = []
    gw.win.add_header = lambda text, attr=None: headers.append((text, attr))

    gw.begin_confirm('Delete backup', scope='header')
    gw.add_confirm_header()

    assert headers == [('⚠️ Delete backup  [Press "y" or ESC]', cs.A_BOLD)]


def test_item_scope_does_not_add_a_header_line():
    gw = make_gw()
    headers = []
    gw.win.add_header = lambda text, attr=None: headers.append((text, attr))

    gw.begin_confirm('Delete backup', scope='item', item_key='row-1')
    gw.add_confirm_header()

    assert headers == []


def test_item_hint_is_drawn_dim_below_the_prompt_line():
    gw = make_gw()
    body = []
    gw.win.add_body = lambda text, attr=None, context=None: body.append(
        (text, attr))

    gw.begin_confirm('Edit value, then ENTER or ESC', mode='text', seed='5',
                     scope='item', item_key='GRUB_TIMEOUT',
                     hint='-1 for infinite, 0 or positive integer')
    gw.add_confirm_item_line('GRUB_TIMEOUT')

    assert body == [
        ('⚠️ Edit value, then ENTER or ESC: 5│', cs.A_BOLD),
        ('-1 for infinite, 0 or positive integer', cs.A_DIM),
    ]


def test_has_live_item_confirm_matches_only_its_own_row():
    gw = make_gw()
    gw.begin_confirm('Edit value, then ENTER or ESC', mode='text', seed='5',
                     scope='item', item_key='GRUB_TIMEOUT')

    assert gw.has_live_item_confirm('GRUB_TIMEOUT') is True
    assert gw.has_live_item_confirm('GRUB_DEFAULT') is False

    gw.handle_confirm_key(27)

    assert gw.has_live_item_confirm('GRUB_TIMEOUT') is False


def test_item_scope_draws_the_prompt_only_after_its_item():
    gw = make_gw()
    body = []
    gw.win.add_body = lambda text, attr=None, context=None: body.append(
        (text, attr))

    gw.begin_confirm('Delete backup', scope='item', item_key='row-1')
    gw.add_confirm_item_line('row-0')
    assert body == []

    gw.add_confirm_item_line('row-1')

    assert body == [('⚠️ Delete backup  [Press "y" or ESC]', cs.A_BOLD)]


def test_review_header_appends_the_live_confirmation_after_its_hints():
    screen = object.__new__(ReviewScreen)
    calls = []
    screen.gw = SimpleNamespace(
        hidden_stats=SimpleNamespace(warn=0),
        add_confirm_header=lambda: calls.append('confirm'))
    screen.add_common_head1 = lambda title: calls.append('head1')
    screen.add_common_head2 = lambda header: calls.append('head2')

    ReviewScreen.add_head(screen)

    assert calls == ['head1', 'head2', 'confirm']


def test_commit_confirmation_resumes_update_grub_without_asking_again():
    gw = make_gw()
    calls = []
    gw.update_grub = lambda tag=None, confirmed=False: calls.append(
        (tag, confirmed))

    assert gw.begin_commit_confirm('~Timeout') is True
    assert gw.win.passthrough_mode is True

    gw.handle_confirm_key(ord('y'))

    assert calls == [('~Timeout', True)]
    assert gw.win.passthrough_mode is False


def test_commit_confirmation_escape_does_not_commit():
    gw = make_gw()
    calls = []
    gw.update_grub = lambda tag=None, confirmed=False: calls.append(
        (tag, confirmed))

    gw.begin_commit_confirm(None)
    gw.handle_confirm_key(27)

    assert calls == []


def make_restore_screen(chosen, older, drawn, asked):
    """Build a RESTORE screen whose only real behaviour is the drawing order."""
    screen = object.__new__(RestoreScreen)
    screen.gw = SimpleNamespace(
        ordered_backup_pairs=[('AAA', chosen), ('BBB', older)],
        backup_mgr=SimpleNamespace(
            checksum_matches=lambda *args: False,
            tag_from_name=lambda name: 'RESYNC'),
        grub_checksum='NEW',
        add_confirm_item_line=lambda key: drawn.append(('confirm', key)),
        request_backup_tag=lambda key, seed='': asked.append((key, seed)))
    screen.win = SimpleNamespace(
        pick_pos=0,
        add_body=lambda text, context=None: drawn.append(('row', text)))
    screen.baseline_bak = older
    return screen


def test_restore_body_places_the_tag_prompt_under_the_backup_it_renames():
    chosen = Path('/b/20261025-083036-s559DCA.RESYNC.bak')
    older = Path('/b/20261025-074512-s559DCA.BASELINE.bak')
    drawn, asked = [], []
    screen = make_restore_screen(chosen, older, drawn, asked)

    RestoreScreen.add_body(screen)

    assert [kind for kind, _ in drawn] == ['row', 'confirm', 'row', 'confirm']
    assert drawn[1] == ('confirm', chosen)
    assert drawn[3] == ('confirm', older)


def test_restore_tag_action_seeds_the_inline_prompt_with_the_current_tag():
    chosen = Path('/b/20261025-083036-s559DCA.RESYNC.bak')
    older = Path('/b/20261025-074512-s559DCA.BASELINE.bak')
    drawn, asked = [], []
    screen = make_restore_screen(chosen, older, drawn, asked)

    RestoreScreen.tag_ACTION(screen)

    assert asked == [(chosen, 'RESYNC')]
