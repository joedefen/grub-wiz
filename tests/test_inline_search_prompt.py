"""The WARNINGS-CONFIG '/' prompt is an inline editor with a movable caret.

console-window's ``InlineConfirmation`` owns the buffer and the caret, so the
adapter must expose the same surface as the old ``IncrementalSearchBar`` while
allowing LEFT/RIGHT and Home/End to position the caret instead of forcing every
edit to happen at the end of the pattern.
"""

import curses
from types import SimpleNamespace

from grub_wiz.main import InlineSearchPrompt, WarnScreen


def make_prompt(**callbacks):
    changes, accepted, cancelled = [], [], []
    prompt = InlineSearchPrompt(
        on_change=callbacks.get('on_change', changes.append),
        on_accept=callbacks.get('on_accept', accepted.append),
        on_cancel=callbacks.get('on_cancel', cancelled.append),
    )
    return prompt, changes, accepted, cancelled


def test_caret_starts_at_end_and_can_move_left_before_inserting():
    prompt, _changes, _accepted, _cancelled = make_prompt()
    prompt.start('abc')

    assert prompt.get_display_string(prefix='   /') == '   / abc█'

    assert prompt.handle_key(curses.KEY_LEFT) is True
    assert prompt.handle_key(curses.KEY_LEFT) is True
    assert prompt.cursor_pos == 1

    assert prompt.handle_key(ord('X')) is True
    assert prompt.text == 'aXbc'
    assert prompt.get_display_string(prefix='   /') == '   / aX█bc'


def test_home_end_and_delete_edit_at_the_caret():
    prompt, _changes, _accepted, _cancelled = make_prompt()
    prompt.start('abcd')

    prompt.handle_key(curses.KEY_HOME)
    prompt.handle_key(curses.KEY_DC)      # delete 'a'
    prompt.handle_key(curses.KEY_END)
    prompt.handle_key(ord('Z'))

    assert prompt.text == 'bcdZ'


def test_enter_accepts_even_an_empty_pattern():
    prompt, _changes, accepted, _cancelled = make_prompt()
    prompt.start('old')

    prompt.handle_key(curses.KEY_HOME)
    for _ in range(len('old')):
        prompt.handle_key(curses.KEY_DC)
    assert prompt.text == ''

    assert prompt.handle_key(10) is True
    assert accepted == ['']
    assert prompt.is_active is False
    # Nothing to show once the filter is cleared.
    assert prompt.get_display_string(prefix='   /') == ''


def test_escape_restores_the_pattern_that_was_active_on_entry():
    prompt, _changes, _accepted, cancelled = make_prompt()
    prompt.start('keep')

    prompt.handle_key(ord('X'))
    assert prompt.get_display_string(prefix='   /') == '   / keepX█'

    assert prompt.handle_key(27) is True
    assert cancelled == ['keep']
    assert prompt.is_active is False
    assert prompt.text == 'keep'
    assert prompt.get_display_string(prefix='   /') == '   /keep'


def test_change_callback_fires_only_when_the_text_changes():
    prompt, changes, _accepted, _cancelled = make_prompt()
    prompt.start('ab')

    prompt.handle_key(curses.KEY_LEFT)
    prompt.handle_key(curses.KEY_RIGHT)
    assert changes == []

    prompt.handle_key(ord('X'))
    assert changes == ['abX']


def test_warn_slash_action_uses_the_inline_prompt_and_enables_passthrough():
    prompt, _changes, _accepted, _cancelled = make_prompt()
    prompt.start('term')
    gw = SimpleNamespace(search_bar=prompt,
                         win=SimpleNamespace(passthrough_mode=False))
    screen = WarnScreen.__new__(WarnScreen)
    screen.gw = gw
    screen.search = 'term'

    screen.slash_ACTION()

    assert prompt.is_active is True
    assert gw.win.passthrough_mode is True
    assert prompt.get_display_string(prefix='   /') == '   / term█'
