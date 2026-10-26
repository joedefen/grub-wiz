"""Dropdown/guidance rows must not become navigation stops.

The EDIT and REVIEW bodies emit dropdown rows only under the selected
parameter.  Those rows shift every row below them, so ``win.pick_pos`` from the
previous frame cannot be reused as a direct row index after a move.  The app
records a stable identity (parameter name / warning key) for every pickable row
and maps the old index through it on the next draw.

Without that mapping, DOWN from a parameter with a tall dropdown skipped the
next parameter entirely (the old row landed on a later parameter once the
dropdown collapsed), and dropdown rows that were left pickable made DOWN need a
second press.
"""

from types import SimpleNamespace

from console_window import Context

from grub_wiz.main import GrubWiz, HomeScreen


class FakeWin:
    """Record the context of every body row the screen emits."""

    cols = 100
    scroll_view_size = 40

    def __init__(self, pick_pos):
        self.pick_pos = pick_pos
        self.contexts = []
        self.body = SimpleNamespace(row_cnt=0, contexts=self.contexts)
        self.lines = []

    def reset(self):
        """Mimic ConsoleWindow.clear() between frames."""
        self.lines.clear()
        self.contexts.clear()
        self.body.row_cnt = 0

    def add_body(self, line, context=None):
        """Record the rendered row and its Context."""
        self.lines.append(line)
        self.contexts.append(context)
        self.body.row_cnt += 1


def make_home_screen(pick_pos, live_key=None):
    """Build a HomeScreen with a tall dropdown on the selected parameter.

    *live_key* is the parameter whose inline edit prompt is live, if any.
    """
    win = FakeWin(pick_pos)
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
        add_confirm_item_line=lambda key: (
            win.add_body(f'prompt:{key}') if key == live_key else None),
        spins=SimpleNamespace(guide='Enums'),
        param_name_wid=16,
    )
    screen = HomeScreen.__new__(HomeScreen)
    screen.gw = gw
    screen.win = win
    screen.search = ''
    screen.regex = None
    return screen, win


def test_home_dropdown_rows_are_not_pickable():
    """The dropdown rows emitted under the selected parameter are detail."""
    screen, win = make_home_screen(pick_pos=1)

    screen.draw_body()

    # row 0: section header, row 1: GRUB_TIMEOUT (picked),
    # rows 2-6: its dropdown, rows 7-8: next section header.
    assert win.contexts[1].genre == 'param'
    assert win.contexts[1].pickable is True
    for row in range(2, 7):
        assert win.contexts[row].genre == 'TRANSIENT'
        assert win.contexts[row].pickable is False


def test_down_from_tall_dropdown_lands_on_next_parameter():
    """DOWN must skip the collapsed rows and land on the *next* parameter."""
    screen, win = make_home_screen(pick_pos=1)
    screen.draw_body()
    assert win.pick_pos == 1

    # The library skips the five non-pickable dropdown rows and the blank /
    # section-header rows, landing on GRUB_DEFAULT in the *old* layout.
    default_row = next(row for row, key in screen._pick_anchors.items()
                       if key[1] == 'GRUB_DEFAULT')
    assert default_row == 9
    assert all(context.pickable is False
               for context in win.contexts[2:default_row])
    win.pick_pos = default_row

    # Next frame: the TIMEOUT dropdown is gone, so rows shift up by five.  The
    # anchor mapping must keep GRUB_DEFAULT selected rather than following the
    # stale row index down to DISABLE_OS_PROBER or beyond.
    win.reset()
    screen.draw_body()

    assert win.pick_pos == 4
    assert win.contexts[4].genre == 'param'
    assert win.contexts[4].param_name == 'GRUB_DEFAULT'
    assert win.contexts[1].param_name == 'GRUB_TIMEOUT'
    # No TIMEOUT dropdown between the two parameters now.
    assert win.contexts[2].genre == 'DECOR'
    assert win.contexts[3].genre == 'DECOR'


def test_live_inline_edit_replaces_the_dropdown_under_its_row():
    """The prompt must sit next to the row whose old value it shows."""
    screen, win = make_home_screen(pick_pos=1, live_key='GRUB_TIMEOUT')

    screen.draw_body()

    assert 'prompt:GRUB_TIMEOUT' in win.lines
    assert '    detail' not in win.lines


def test_wrapped_detail_continuations_are_not_pickable():
    """Continuation rows of a wrapped picked line are detail, not stops."""
    win = FakeWin(pick_pos=0)
    screen = GrubWiz.__new__(GrubWiz)
    screen.win = win

    screen.add_wrapped_body_line(
        'a detail line long enough to wrap at one hundred columns ' * 3,
        indent=4,
        is_current=True,
        context=Context(genre='warn', warn_key='GRUB_TIMEOUT warning'))

    assert len(win.contexts) > 1
    assert win.contexts[0].genre == 'warn'
    assert win.contexts[0].pickable is True
    for context in win.contexts[1:]:
        assert context.genre == 'TRANSIENT'
        assert context.pickable is False
