"""Pure helpers in ``main.py`` that do not need a curses window.

Most of ``main.py`` is screen drawing.  These helpers decide what the commit
writes, how values are activated, and how backup tags are formed, so they are
worth pinning without constructing a terminal.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz.BackupMgr import RESYNC_TAG
from grub_wiz.GrubFile import GrubFile
from grub_wiz.main import (
    QUIT_KEY,
    RESTORE_ST,
    GrubWiz,
    ReviewScreen,
    Tab,
    display_width,
    prompt_key,
    truncate_to_width,
)


# --- text width ------------------------------------------------------------

def test_display_width_counts_cells_not_code_points():
    assert display_width('abc') == 3
    assert display_width('界') == 2
    assert display_width('e\u0301') == 1


def test_truncate_to_width_preserves_short_text():
    assert truncate_to_width('abc', 3) == 'abc'
    assert truncate_to_width('abc', 10) == 'abc'


def test_truncate_to_width_respects_cell_budget():
    truncated = truncate_to_width('abcdef', 4)

    assert truncated == 'abc▶'
    assert display_width(truncated) <= 4

    wide = truncate_to_width('界界界', 4)
    assert wide == '界▶'
    assert display_width(wide) <= 4


def test_tab_layout_positions():
    tab = Tab(cols=80, param_wid=10)

    assert (tab.la, tab.lz, tab.lwid) == (1, 15, 14)
    assert (tab.ra, tab.rz, tab.rwid) == (17, 80, 63)
    assert tab.wid == 79


# --- diffs and selection ---------------------------------------------------

def test_get_diffs_uses_string_equivalence():
    gw = object.__new__(GrubWiz)
    gw.prev_values = {'GRUB_TIMEOUT': 5, 'GRUB_DEFAULT': '0', 'GRUB_THEME': 'x'}
    gw.param_values = {'GRUB_TIMEOUT': '5', 'GRUB_DEFAULT': '1',
                       'GRUB_THEME': 'x'}

    assert gw.get_diffs() == {'GRUB_DEFAULT': ('0', '1')}


def test_get_enums_regex_without_a_picked_parameter():
    gw = object.__new__(GrubWiz)
    gw.ss = SimpleNamespace(is_curr=lambda _screens: True)
    gw.win = SimpleNamespace(get_picked_context=lambda: None)

    assert gw.get_enums_regex() == ('', {}, {}, '', None)


def test_get_enums_regex_returns_selected_parameter_context():
    cfg = {'enums': {'a': 'A'}, 'edit_re': 'regex'}
    gw = object.__new__(GrubWiz)
    gw.ss = SimpleNamespace(is_curr=lambda _screens: True)
    gw.win = SimpleNamespace(
        get_picked_context=lambda: SimpleNamespace(
            genre='param', param_name='GRUB_DEFAULT'))
    gw.param_cfg = {'GRUB_DEFAULT': cfg}
    gw.param_values = {'GRUB_DEFAULT': 'a'}

    assert gw.get_enums_regex() == (
        'GRUB_DEFAULT', cfg, {'a': 'A'}, 'regex', 'a')


def test_is_active_param_states():
    gw = object.__new__(GrubWiz)
    gw.param_values = {
        'GRUB_TIMEOUT': '5',
        'GRUB_THEME': GrubFile.COMMENT,
        'GRUB_FOO': GrubFile.ABSENT,
    }

    assert gw.is_active_param('GRUB_TIMEOUT') is True
    assert gw.is_active_param('GRUB_THEME') is False
    assert gw.is_active_param('GRUB_FOO') is False
    assert gw.is_active_param('GRUB_MISSING') is False


# --- activation ------------------------------------------------------------

def bare_gw(param_cfg, values, prev=None):
    gw = object.__new__(GrubWiz)
    gw.param_cfg = param_cfg
    gw.param_values = dict(values)
    gw.prev_values = dict(prev or {})
    gw.saved_active_param_values = {}
    return gw


def test_activation_default_skips_documentation_sentinels():
    gw = bare_gw(
        {'GRUB_TERMINAL': {'default': '#comment',
                           'enums': {'console': 'Console', 'serial': 'Serial'}}},
        {})

    assert gw._activation_default('GRUB_TERMINAL') == 'console'


def test_activation_default_handles_empty_config():
    gw = bare_gw({}, {})

    assert gw._activation_default('GRUB_MISSING') == ''


def test_activate_restores_saved_value_before_using_default():
    gw = bare_gw(
        {'GRUB_TIMEOUT': {'default': '10', 'enums': {}}},
        {'GRUB_TIMEOUT': GrubFile.COMMENT})
    gw.saved_active_param_values['GRUB_TIMEOUT'] = '42'

    assert gw.activate_param('GRUB_TIMEOUT') is True
    assert gw.param_values['GRUB_TIMEOUT'] == '42'


def test_activate_uses_writable_default_and_is_idempotent():
    gw = bare_gw(
        {'GRUB_TIMEOUT': {'default': '10', 'enums': {}}},
        {'GRUB_TIMEOUT': GrubFile.ABSENT})

    assert gw.activate_param('GRUB_TIMEOUT') is True
    assert gw.param_values['GRUB_TIMEOUT'] == '10'
    assert gw.activate_param('GRUB_TIMEOUT') is False


def test_deactivate_uses_comment_or_absent_and_saves_value():
    gw = bare_gw(
        {'GRUB_TIMEOUT': {}, 'GRUB_THEME': {}},
        {'GRUB_TIMEOUT': '5', 'GRUB_THEME': 'theme'},
        {'GRUB_TIMEOUT': '4', 'GRUB_THEME': GrubFile.ABSENT})

    assert gw.deactivate_param('GRUB_TIMEOUT') is True
    assert gw.param_values['GRUB_TIMEOUT'] == GrubFile.COMMENT
    assert gw.saved_active_param_values['GRUB_TIMEOUT'] == '5'

    assert gw.deactivate_param('GRUB_THEME') is True
    assert gw.param_values['GRUB_THEME'] == GrubFile.ABSENT


def test_deactivate_is_a_noop_for_inactive_params():
    gw = bare_gw({}, {'GRUB_TIMEOUT': GrubFile.COMMENT})

    assert gw.deactivate_param('GRUB_TIMEOUT') is False


# --- backup tags -----------------------------------------------------------

class FakeWin:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def answer(self, prompt=None, seed=None, height=1):
        self.calls.append({'prompt': prompt, 'seed': seed, 'height': height})
        return self.answers.pop(0)


def test_request_backup_tag_normalizes_and_reprompts():
    gw = object.__new__(GrubWiz)
    gw.win = FakeWin(['bad tag!', 'good tag'])

    assert gw.request_backup_tag('Enter a tag') == 'good-tag'

    assert gw.win.calls[0]['prompt'].startswith('Enter a tag')
    assert gw.win.calls[0]['seed'] == ''
    assert gw.win.calls[1]['prompt'].startswith('Invalid tag;')
    assert gw.win.calls[1]['seed'] == 'bad-tag!'


def test_request_backup_tag_cancel_returns_none():
    gw = object.__new__(GrubWiz)
    gw.win = FakeWin([None])

    assert gw.request_backup_tag('Enter a tag') is None


def test_request_backup_tag_accepts_generated_characters():
    """Generated tags use '+' and '~', so a handwritten tag may too."""
    gw = object.__new__(GrubWiz)
    gw.win = FakeWin(['+Timeout+2'])

    assert gw.request_backup_tag('Enter a tag') == '+Timeout+2'


class FakeBackupMgr:
    """Record what the startup and commit rules ask for, without a disk."""

    def __init__(self, files=None, checksum='NEW'):
        self.target_path = Path('/etc/default/grub')
        self.files = dict(files or {})
        self.checksum = checksum
        self.created = []

    def calc_checksum(self, _target):
        return self.checksum

    def checksum_from_name(self, name):
        return self.checksum

    def tag_from_name(self, name):
        stem = name[:-4] if name.endswith('.bak') else name
        parts = stem.split('.')
        return parts[1] if len(parts) > 1 else ''

    def get_backups(self):
        return dict(self.files)

    def create_backup(self, tag=None):
        suffix = f'.{tag}' if tag else ''
        name = f'20260101-000000-s{self.checksum}{suffix}.bak'
        self.files[name] = Path(name)
        self.created.append(tag)
        return Path(name)


def make_backup_gw(manager):
    gw = object.__new__(GrubWiz)
    gw.backup_mgr = manager
    gw.grub_checksum = None
    gw.refresh_backup_list = lambda: setattr(gw, 'backups',
                                             gw.backup_mgr.get_backups())
    return gw


def test_startup_backup_is_baseline_when_no_backups_exist():
    manager = FakeBackupMgr()
    gw = make_backup_gw(manager)

    gw.do_start_up_backup()

    assert manager.created == ['BASELINE']
    assert gw.grub_checksum == 'NEW'
    assert len(gw.backups) == 1


def test_startup_backup_records_nothing_when_the_inventory_is_not_empty():
    """A launch is not an event: only grub-wiz commits write a backup."""
    manager = FakeBackupMgr({'20260101-000000-sOLD.RESYNC.bak': Path('old')})
    gw = make_backup_gw(manager)

    gw.do_start_up_backup()

    assert manager.created == []
    assert gw.grub_checksum == 'NEW'


def test_record_committed_backup_records_a_new_state():
    manager = FakeBackupMgr({'20260101-000000-sOLD.~Timeout.bak': Path('old')})
    gw = make_backup_gw(manager)

    gw.record_committed_backup('~Timeout')

    assert manager.created == ['~Timeout']


def test_record_committed_backup_keeps_an_identical_state_as_resync():
    """BackupMgr collapses the neighbour, so RESYNC must stay recordable."""
    manager = FakeBackupMgr({'20260101-000000-sNEW.~Timeout.bak': Path('old')})
    gw = make_backup_gw(manager)

    gw.record_committed_backup(RESYNC_TAG)

    assert manager.created == [RESYNC_TAG]


def test_review_write_passes_the_computed_tag():
    """The tag is built on REVIEW, where the parameter diff exists."""
    screen = object.__new__(ReviewScreen)
    seen = {}
    screen.gw = SimpleNamespace(
        get_diffs=lambda: {'GRUB_DISABLE_SUBMENU': (GrubFile.ABSENT, 'true')},
        update_grub=lambda tag=None: seen.setdefault('tag', tag))
    screen.app = screen.gw

    ReviewScreen.write_ACTION(screen)

    assert seen['tag'] == '+DisablSubmen'


def test_review_write_without_a_diff_passes_resync():
    """Pressing w twice still updates GRUB; that is a RESYNC, not a no-op."""
    screen = object.__new__(ReviewScreen)
    seen = {}
    screen.gw = SimpleNamespace(
        get_diffs=lambda: {},
        update_grub=lambda tag=None: seen.setdefault('tag', tag))
    screen.app = screen.gw

    ReviewScreen.write_ACTION(screen)

    assert seen['tag'] == RESYNC_TAG


def test_review_write_between_two_sentinels_is_untagged():
    """COMMENT -> ABSENT is a real edit with no value change, not a RESYNC."""
    screen = object.__new__(ReviewScreen)
    seen = {}
    screen.gw = SimpleNamespace(
        get_diffs=lambda: {'GRUB_TIMEOUT': (GrubFile.COMMENT, GrubFile.ABSENT)},
        update_grub=lambda tag=None: seen.setdefault('tag', tag))
    screen.app = screen.gw

    ReviewScreen.write_ACTION(screen)

    assert seen['tag'] is None


def test_confirm_quit_is_silent_without_pending_changes():
    asked = []
    gw = object.__new__(GrubWiz)
    gw.get_diffs = lambda: {}
    gw.really_wanna = lambda act: asked.append(act) or True

    assert gw.confirm_quit() is True
    assert asked == []


def test_confirm_quit_asks_before_discarding_changes():
    asked = []
    gw = object.__new__(GrubWiz)
    gw.get_diffs = lambda: {'GRUB_TIMEOUT': ('5', '9'),
                            'GRUB_THEME': ('a', 'b')}
    gw.really_wanna = lambda act: asked.append(act) or False

    assert gw.confirm_quit() is False
    assert asked == ['quit and discard 2 unapplied change(s)']


class FakeLoopWin:
    """Just enough window for ``prompt_key()``: a key, or a Ctrl-C."""

    def __init__(self, result=None, interrupt=False):
        self.result = result
        self.interrupt = interrupt
        self.timeouts = []

    def prompt(self, seconds=0.0):
        self.timeouts.append(seconds)
        if self.interrupt:
            raise KeyboardInterrupt
        return self.result


def test_quit_key_is_ctrl_c():
    assert QUIT_KEY == 0x3


def test_prompt_key_returns_the_typed_key():
    win = FakeLoopWin(ord('q'))

    assert prompt_key(win, 0.1) == ord('q')
    assert win.timeouts == [0.1]


def test_prompt_key_turns_ctrl_c_into_the_quit_key():
    """Ctrl-C must reach the loop as a key, never as an escaping exception."""
    assert prompt_key(FakeLoopWin(interrupt=True), 0.1) == QUIT_KEY


def test_request_quit_from_restore_goes_back_instead_of_asking():
    gw = object.__new__(GrubWiz)
    gw.ss = SimpleNamespace(is_curr=lambda num: num == RESTORE_ST)
    calls = []
    gw.navigate_back = lambda: calls.append('back') or True
    gw.confirm_quit = lambda: calls.append('asked') or True

    assert gw.request_quit() is False
    assert calls == ['back']


def test_request_quit_elsewhere_asks_before_stopping():
    gw = object.__new__(GrubWiz)
    gw.ss = SimpleNamespace(is_curr=lambda _num: False)
    calls = []
    gw.navigate_back = lambda: calls.append('back')
    gw.confirm_quit = lambda: calls.append('asked') or True

    assert gw.request_quit() is True
    assert calls == ['asked']


# --- enum lookup -----------------------------------------------------------

def test_find_in_normalizes_quoted_values():
    gw = object.__new__(GrubWiz)

    result = gw.find_in('"b"', enums={'a': 'A', '"b"': 'B'})

    assert result.choices == ['a', '"b"']
    assert result.idx == 1
    assert result.next_value == 'a'
    assert result.prev_value == 'a'


def test_find_in_reads_enums_from_cfg():
    gw = object.__new__(GrubWiz)

    result = gw.find_in('x', enums='enums', cfg={'enums': {'x': 'X', 'y': 'Y'}})

    assert result.idx == 0
    assert result.next_value == 'y'
