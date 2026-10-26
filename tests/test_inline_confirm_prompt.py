"""Confirmations are inline lines, not modal dialogs.

The REVIEW ``w`` action asks with a header line just above the divider, so the
screen keeps showing the changes being committed.  ESC cancels, the confirming
key continues the action, and every other key is ignored while the prompt is
live.  A prompt that only concerns one row (the RESTORE ``t`` retag) is drawn
directly below that row instead.

The live prompt itself belongs to console-window (``begin_prompt()`` /
``handle_prompt_key()``), so these tests cover this application's share of it:
the warning glyph, which band the line is drawn in, which row it belongs to,
and the callback that finishes the action.
"""

import curses as cs
from pathlib import Path
from types import SimpleNamespace

from grub_wiz.main import GrubWiz, RestoreScreen, ReviewScreen


def make_gw(win):
    """Build the minimum GrubWiz state the inline-confirm helpers touch."""
    gw = object.__new__(GrubWiz)
    gw.win = win
    gw.confirm_scope, gw.confirm_item_key = 'header', None
    return gw


def test_prompt_is_rendered_as_a_single_header_line(headless_win):
    gw = make_gw(headless_win)

    assert gw.begin_confirm('Delete backup') is True
    gw.add_confirm_header()

    assert gw.win.head.texts == ['⚠️ Delete backup  [Press "y" or ESC]']


def test_the_header_prompt_is_bold(headless_win):
    gw = make_gw(headless_win)

    gw.begin_confirm('Delete backup')
    gw.add_confirm_header()

    assert cs.A_BOLD in [attr for attr, _cells in gw.win.head.text_attrs[0]]


def test_confirming_key_runs_the_callback_after_the_prompt_is_gone(
        headless_win):
    gw = make_gw(headless_win)
    seen = []
    gw.begin_confirm('Commit', on_confirm=lambda answer: seen.append(
        (answer, gw.win.prompt_active, gw.win.passthrough_mode)))

    assert gw.win.handle_prompt_key(ord('y')) == 'confirmed'

    # The callback runs after the teardown, which is what lets it start
    # another prompt (the re-ask path).
    assert seen == [('y', False, False)]
    assert gw.win.prompt_active is False

    gw.add_confirm_header()
    assert gw.win.head.texts == []


def test_escape_cancels_without_confirming(headless_win):
    gw = make_gw(headless_win)
    calls = []
    gw.begin_confirm('Commit',
                     on_confirm=lambda answer: calls.append(answer),
                     on_cancel=lambda: calls.append('cancel'))

    assert gw.win.handle_prompt_key(27) == 'cancelled'

    assert calls == ['cancel']
    assert gw.win.prompt_active is False


def test_other_keys_are_ignored_while_the_prompt_is_live(headless_win):
    gw = make_gw(headless_win)
    confirmed = []
    gw.begin_confirm('Commit', on_confirm=confirmed.append)

    for key in (ord('n'), ord('w'), ord('q'), cs.KEY_DOWN):
        assert gw.win.handle_prompt_key(key) == 'continue'

    assert confirmed == []
    assert gw.win.prompt_active is True


def test_begin_confirm_enables_passthrough_and_the_answer_restores_it(
        headless_win):
    gw = make_gw(headless_win)
    assert gw.win.passthrough_mode is False

    gw.begin_confirm('Commit')
    assert gw.win.passthrough_mode is True

    gw.win.handle_prompt_key(27)
    assert gw.win.passthrough_mode is False


def test_begin_confirm_restores_a_previously_enabled_passthrough(
        headless_win):
    gw = make_gw(headless_win)
    gw.win.passthrough_mode = True

    gw.begin_confirm('Commit')
    gw.win.handle_prompt_key(27)

    assert gw.win.passthrough_mode is True


def test_callback_may_start_the_next_prompt(headless_win):
    gw = make_gw(headless_win)
    second = []
    gw.begin_confirm('First', on_confirm=lambda _answer: gw.begin_confirm(
        'Second', on_confirm=second.append))

    gw.win.handle_prompt_key(ord('y'))

    assert gw.win.prompt_active is True
    assert (gw.win.prompt_line.get_display_string()
            == '⚠️ Second  [Press "y" or ESC]')
    assert gw.win.passthrough_mode is True

    gw.win.handle_prompt_key(ord('y'))
    assert second == ['y']


def test_begin_confirm_without_a_window_is_a_noop():
    gw = make_gw(None)

    assert gw.begin_confirm('Commit') is False
    assert gw.has_live_item_confirm('row-1') is False


def test_item_scope_does_not_add_a_header_line(headless_win):
    gw = make_gw(headless_win)

    gw.begin_confirm('Delete backup', scope='item', item_key='row-1')
    gw.add_confirm_header()

    assert gw.win.head.texts == []


def test_item_hint_is_drawn_dim_below_the_prompt_line(headless_win):
    gw = make_gw(headless_win)

    gw.begin_confirm('Edit value, then ENTER or ESC', mode='text', seed='5',
                     scope='item', item_key='GRUB_TIMEOUT',
                     hint='-1 for infinite, 0 or positive integer')
    gw.add_confirm_item_line('GRUB_TIMEOUT')

    assert gw.win.body.texts == [
        '⚠️ Edit value, then ENTER or ESC: 5│',
        '-1 for infinite, 0 or positive integer',
    ]
    # Detail lines, never pick targets: the row being edited stays selected.
    assert [context.genre for context in gw.win.body.contexts] == [
        'TRANSIENT', 'TRANSIENT']
    assert [context.pickable for context in gw.win.body.contexts] == [
        False, False]
    assert cs.A_DIM in [attr for attr, _cells in gw.win.body.text_attrs[1]]


def test_has_live_item_confirm_matches_only_its_own_row(headless_win):
    gw = make_gw(headless_win)
    gw.begin_confirm('Edit value, then ENTER or ESC', mode='text', seed='5',
                     scope='item', item_key='GRUB_TIMEOUT')

    assert gw.has_live_item_confirm('GRUB_TIMEOUT') is True
    assert gw.has_live_item_confirm('GRUB_DEFAULT') is False

    gw.win.handle_prompt_key(27)

    assert gw.has_live_item_confirm('GRUB_TIMEOUT') is False


def test_item_scope_draws_the_prompt_only_after_its_item(headless_win):
    gw = make_gw(headless_win)

    gw.begin_confirm('Delete backup', scope='item', item_key='row-1')
    gw.add_confirm_item_line('row-0')
    assert gw.win.body.texts == []

    gw.add_confirm_item_line('row-1')

    assert gw.win.body.texts == ['⚠️ Delete backup  [Press "y" or ESC]']


def test_item_prompt_disappears_once_it_is_answered(headless_win):
    gw = make_gw(headless_win)

    gw.begin_confirm('Delete backup', scope='item', item_key='row-1')
    gw.win.handle_prompt_key(27)
    gw.add_confirm_item_line('row-1')

    assert gw.win.body.texts == []


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


def test_commit_confirmation_resumes_update_grub_without_asking_again(
        headless_win):
    gw = make_gw(headless_win)
    calls = []
    gw.update_grub = lambda tag=None, confirmed=False: calls.append(
        (tag, confirmed))

    assert gw.begin_commit_confirm('~Timeout') is True
    assert gw.win.passthrough_mode is True

    gw.win.handle_prompt_key(ord('y'))

    assert calls == [('~Timeout', True)]
    assert gw.win.passthrough_mode is False


def test_commit_confirmation_escape_does_not_commit(headless_win):
    gw = make_gw(headless_win)
    calls = []
    gw.update_grub = lambda tag=None, confirmed=False: calls.append(
        (tag, confirmed))

    gw.begin_commit_confirm(None)
    gw.win.handle_prompt_key(27)

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
