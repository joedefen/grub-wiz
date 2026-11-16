"""Dropdown/guidance rows must not become navigation stops.

The EDIT and REVIEW bodies emit dropdown rows only under the selected
parameter.  Those rows shift every row below them, so the pick position from the
previous frame cannot be reused as a direct row index after a move.  The app
records a stable identity (parameter name / warning key) for every pickable row
and maps the old index through it on the next draw.

In 3.0 the content writers live on ``Screen``, so these tests drive real screens
over a headless window and read the rows back off the screen that wrote them.
"""

import curses as cs
from types import SimpleNamespace

from console_window import Context, Theme

from grub_wiz import main as main_module
from grub_wiz.main import GrubWizScreen, HomeScreen


def row_attrs(body):
    """First attribute of each body row (A_NORMAL when the row is plain)."""
    return [rle[0][0] if rle else 0 for rle in body.text_attrs]


def make_home_screen(make_headless_win, pick_pos, live_key=None):
    """Build a HomeScreen with a tall dropdown on the selected parameter.

    *live_key* is the parameter whose inline edit prompt is live, if any.
    """
    win = make_headless_win(rows=40, cols=100)
    param_cfg = {
        'GRUB_TIMEOUT': {
            'default': '5',
            'enums': {'5': 'medium wait'},
            'edit_re': r'^[-0-9]+$',
            'guidance': '',
        },
        'GRUB_DEFAULT': {
            'default': 'saved',
            'enums': {'saved': 'saved entry'},
            'edit_re': None,
            'guidance': '',
        },
        'GRUB_DISABLE_OS_PROBER': {
            'default': 'false',
            'enums': {'true': 'on', 'false': 'off'},
            'edit_re': None,
            'guidance': '',
        },
    }

    def drop_down_lines(param_name):
        if param_name == 'GRUB_TIMEOUT':
            return ['    detail'] * 5
        if param_name == 'GRUB_DEFAULT':
            return ['    detail'] * 2
        return []

    gw = SimpleNamespace(
        win=win,
        hidden_stats=None,
        sections={'Boot Timeout': {'GRUB_TIMEOUT': None},
                  'Menu Entries': {'GRUB_DEFAULT': None,
                                   'GRUB_DISABLE_OS_PROBER': None}},
        param_cfg=param_cfg,
        param_values={'GRUB_TIMEOUT': '5',
                      'GRUB_DEFAULT': 'saved',
                      'GRUB_DISABLE_OS_PROBER': 'false'},
        is_active_param=lambda _name: True,
        show_hidden_params=False,
        drop_down_lines=drop_down_lines,
        has_live_item_confirm=lambda key: key == live_key,
        confirm_scope='header',
        confirm_item_key=None,
        spins=SimpleNamespace(guide='Enums'),
        param_name_wid=16,
    )
    screen = HomeScreen(gw)
    screen.clear()
    screen.pick_pos = pick_pos
    if live_key is not None:
        def confirm(key):
            if key == live_key:
                screen.add_body(f'prompt:{key}')
        screen.add_confirm_item_line = confirm
    return screen, win


def make_plain_screen(make_headless_win):
    """A bare GrubWizScreen over a headless window, for helper rows."""
    win = make_headless_win(rows=40, cols=100)
    app = SimpleNamespace(win=win, spins=SimpleNamespace(guide='Off'))
    screen = GrubWizScreen(app)
    screen.clear()
    return screen, win


def test_home_dropdown_rows_are_not_pickable(make_headless_win):
    """The dropdown rows emitted under the selected parameter are detail."""
    screen, win = make_home_screen(make_headless_win, pick_pos=1)

    screen.draw_body()

    # row 0: section header, row 1: GRUB_TIMEOUT (picked),
    # rows 2-6: its dropdown, row 7: blank, row 8: next section header.
    assert screen.body.contexts[1].genre == 'param'
    assert screen.body.contexts[1].pickable is True
    for row in range(2, 7):
        assert screen.body.contexts[row].genre == 'TRANSIENT'
        assert screen.body.contexts[row].pickable is False


def test_down_from_tall_dropdown_lands_on_next_parameter(make_headless_win):
    """DOWN must skip the collapsed rows and land on the *next* parameter."""
    screen, win = make_home_screen(make_headless_win, pick_pos=1)
    screen.draw_body()
    assert screen.pick_pos == 1

    # The library skips the five non-pickable dropdown rows and the blank /
    # section-header rows, landing on GRUB_DEFAULT in the *old* layout.
    default_row = next(row for row, key in screen._pick_anchors.items()
                       if key[1] == 'GRUB_DEFAULT')
    assert default_row == 9
    assert all(context.pickable is False
               for context in screen.body.contexts[2:default_row])
    screen.pick_pos = default_row

    # Next frame: the TIMEOUT dropdown is gone, so rows shift up by five.  The
    # anchor mapping must keep GRUB_DEFAULT selected rather than following the
    # stale row index down to DISABLE_OS_PROBER or beyond.
    screen.clear()
    screen.draw_body()

    assert screen.pick_pos == 4
    assert screen.body.contexts[4].genre == 'param'
    assert screen.body.contexts[4].param_name == 'GRUB_DEFAULT'
    assert screen.body.contexts[1].param_name == 'GRUB_TIMEOUT'
    # No TIMEOUT dropdown between the two parameters now.
    assert screen.body.contexts[2].genre == 'DECOR'
    assert screen.body.contexts[3].genre == 'DECOR'


def test_live_inline_edit_replaces_the_dropdown_under_its_row(
        make_headless_win):
    """The prompt must sit next to the row whose old value it shows."""
    screen, win = make_home_screen(make_headless_win, pick_pos=1,
                                   live_key='GRUB_TIMEOUT')

    screen.draw_body()

    assert 'prompt:GRUB_TIMEOUT' in screen.body.texts
    assert '    detail' not in screen.body.texts


def test_wrapped_detail_continuations_are_not_pickable(make_headless_win):
    """Continuation rows of a wrapped picked line are detail, not stops."""
    screen, win = make_plain_screen(make_headless_win)

    screen.add_wrapped_body_line(
        'a detail line long enough to wrap at one hundred columns ' * 3,
        indent=4,
        is_current=True,
        context=Context(genre='warn', warn_key='GRUB_TIMEOUT warning'))

    assert len(screen.body.contexts) > 1
    assert screen.body.contexts[0].genre == 'warn'
    assert screen.body.contexts[0].pickable is True
    for context in screen.body.contexts[1:]:
        assert context.genre == 'TRANSIENT'
        assert context.pickable is False


def test_wrapped_detail_rows_carry_the_attribute_they_were_given(
        make_headless_win):
    """A coloured warning must stay coloured on its wrapped rows."""
    colour = 0x0300
    screen, win = make_plain_screen(make_headless_win)

    screen.add_wrapped_body_line(
        'a detail line long enough to wrap at one hundred columns ' * 3,
        indent=4,
        is_current=True,
        attr=colour,
        context=Context(genre='warn', warn_key='GRUB_TIMEOUT warning'))

    attrs = row_attrs(screen.body)
    assert len(attrs) > 1
    assert set(attrs) == {colour}

    screen.clear()
    screen.add_wrapped_body_line('short warning', indent=4, is_current=False,
                                 attr=colour)

    assert row_attrs(screen.body) == [colour]


def test_home_guidance_rows_carry_the_info_role(monkeypatch,
                                               make_headless_win):
    """EDIT colours its dropdown INFO, exactly as REVIEW does."""
    monkeypatch.setattr(main_module, 'theme_attr', lambda pair: pair << 8)
    screen, win = make_home_screen(make_headless_win, pick_pos=1)

    screen.draw_body()

    attrs = row_attrs(screen.body)
    transient = [attr for attr, context in zip(attrs, screen.body.contexts)
                 if context is not None and context.genre == 'TRANSIENT']
    assert transient
    assert set(transient) == {Theme.INFO << 8}

    # The parameter's own rows are state and stay plain.
    param = [attr for attr, context in zip(attrs, screen.body.contexts)
             if context is not None and context.genre == 'param']
    assert param and set(param) == {cs.A_NORMAL}


def test_home_wrapped_value_continuations_stay_plain(monkeypatch,
                                                      make_headless_win):
    """A wrapped value is still state: only the advice below it is INFO."""
    monkeypatch.setattr(main_module, 'theme_attr', lambda pair: pair << 8)
    screen, win = make_home_screen(make_headless_win, pick_pos=1)
    screen.body_param_lines = lambda name, is_current: ['GRUB_TIMEOUT   5',
                                                        '    wrapped value']

    screen.draw_body()

    attrs = row_attrs(screen.body)
    boxed = [(line, attr) for line, attr
             in zip(screen.body.texts, attrs)
             if any(char in line for char in '╭│╰')]
    assert boxed[0] == ('   ╭wrapped value', cs.A_NORMAL)
    assert {attr for _line, attr in boxed[1:]} == {Theme.INFO << 8}
