"""Regression tests for the COMPARE screen (audit finding H5).

``CompareScreen.add_body()`` used to merge ``GrubFile.extra_params`` (config
dicts such as ``default``/``enums``/``guidance``) into ``param_data`` (which
holds ``SimpleNamespace`` records).  Any backup containing an unvalidated
``GRUB_*`` parameter then crashed the screen with:

    AttributeError: 'dict' object has no attribute 'value'
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz.main import CompareScreen


class FakeWin:
    """Just enough of ConsoleWindow for ``CompareScreen.add_body()``."""

    cols = 80

    def __init__(self):
        self.body_lines = []
        self.header_lines = []

    def set_pick_mode(self, flag):
        """Record nothing; the compare screen never picks."""
        return flag

    def add_body(self, text, **_kwargs):
        """Collect the rendered comparison lines."""
        self.body_lines.append(text)

    def add_header(self, text, **_kwargs):
        """Collect the header lines."""
        self.header_lines.append(text)


def make_screen(param_cfg, bak1, bak2):
    """Build a CompareScreen bound to fakes instead of a live curses app."""
    win = FakeWin()
    gw = SimpleNamespace(win=win, param_cfg=param_cfg)
    screen = CompareScreen(gw)
    screen.bak1 = bak1
    screen.bak2 = bak2
    return screen, win


def write_backup(tmp_path, name, text):
    """Create a backup file and return its Path."""
    path = tmp_path / name
    path.write_text(text)
    return path


def test_compare_with_unvalidated_param_does_not_crash(tmp_path):
    """An unvalidated GRUB_* parameter must render, not raise AttributeError."""
    param_cfg = {
        'GRUB_TIMEOUT': {
            'default': '5',
            'enums': {},
            'guidance': 'Timeout in seconds',
        },
    }
    bak1 = write_backup(
        tmp_path, 'one.bak',
        'GRUB_TIMEOUT=5\nGRUB_CUSTOM_UNKNOWN=foo\n')
    bak2 = write_backup(
        tmp_path, 'two.bak',
        'GRUB_TIMEOUT=10\n')

    screen, win = make_screen(param_cfg, bak1, bak2)
    screen.add_body()  # used to raise AttributeError

    rendered = '\n'.join(win.body_lines)
    assert 'GRUB_CUSTOM_UNKNOWN=foo' in rendered
    assert 'GRUB_TIMEOUT=5' in rendered
    assert 'GRUB_TIMEOUT=10' in rendered
    assert screen.cnt1 == 2
    assert screen.cnt2 == 1


def test_compare_unvalidated_param_in_both_backups(tmp_path):
    """Different values for the same unvalidated param are both shown."""
    bak1 = write_backup(
        tmp_path, 'one.bak',
        'GRUB_CUSTOM_UNKNOWN=foo\n')
    bak2 = write_backup(
        tmp_path, 'two.bak',
        'GRUB_CUSTOM_UNKNOWN=bar\n')

    screen, win = make_screen({}, bak1, bak2)
    screen.add_body()

    assert '< GRUB_CUSTOM_UNKNOWN=foo' in win.body_lines
    assert '> GRUB_CUSTOM_UNKNOWN=bar' in win.body_lines


def test_compare_leaves_caller_param_cfg_untouched(tmp_path):
    """Reading a backup must not adopt its extra params into the app config."""
    param_cfg = {
        'GRUB_TIMEOUT': {
            'default': '5',
            'enums': {},
            'guidance': 'Timeout in seconds',
        },
    }
    bak1 = write_backup(
        tmp_path, 'one.bak',
        'GRUB_TIMEOUT=5\nGRUB_CUSTOM_UNKNOWN=foo\n')
    bak2 = write_backup(
        tmp_path, 'two.bak',
        'GRUB_TIMEOUT=10\n')

    screen, _win = make_screen(param_cfg, bak1, bak2)
    screen.add_body()

    assert 'GRUB_CUSTOM_UNKNOWN' not in param_cfg
    assert list(param_cfg) == ['GRUB_TIMEOUT']
