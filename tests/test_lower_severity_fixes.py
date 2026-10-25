#!/usr/bin/env python3
"""Regression tests for the lower-severity/polish items in ``tests/AUDIT.md``.

Each test covers a defect that was fixed without changing a user-facing
contract:

* ``WarnDB.refresh()`` must survive a YAML document whose root is not a mapping.
* ``GrubFile.read_file()`` must not keep blacklist/extra-param state from a
  previous read.
* ``$prefix`` expansion must use the distro's GRUB directory that exists
  (Fedora uses ``/boot/grub2``), not always ``/boot/grub``.
* ``GrubFile._join_continuation_lines()`` must join single-quoted values and
  must not let a malformed trailing backslash swallow an unrelated line.
* ``prompt_line()`` must treat a closed stdin as the caller's safe default.
* ``GrubWiz.long_params`` must not contain the stray ``'/'`` token, and an
  unknown parameter is not "active".
"""

import builtins
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz.GrubFile import GrubFile
from grub_wiz.UserConfigDir import UserConfigDir
from grub_wiz.WarnDB import WarnDB
from grub_wiz.WizValidator import WizValidator
from grub_wiz.main import GrubWiz, prompt_line


class FakeUserConfig:
    """Minimal ``UserConfigDir`` replacement backed by a temporary directory."""

    def __init__(self, root):
        self.user_state_dir = root

    @staticmethod
    def safe_read_text(path, max_bytes=1024 * 1024):
        del max_bytes
        return Path(path).read_text(encoding='utf-8')


def test_warn_db_ignores_non_mapping_document(tmp_path, monkeypatch):
    """A top-level YAML list must clear the state, not raise AttributeError."""
    fake = FakeUserConfig(tmp_path)
    monkeypatch.setattr(
        UserConfigDir,
        'get_singleton',
        staticmethod(lambda app_name='grub-wiz': fake),
    )
    (tmp_path / 'warn-db.yaml').write_text(
        '- not\n- a\n- mapping\n', encoding='utf-8')

    warn_db = WarnDB(param_cfg=None)

    assert warn_db.inhibits == set()
    assert warn_db.all_info == {}


def test_warn_db_ignores_malformed_sections(tmp_path, monkeypatch):
    """Wrongly-typed ``inhibited``/``all_warnings`` values must not raise."""
    fake = FakeUserConfig(tmp_path)
    monkeypatch.setattr(
        UserConfigDir,
        'get_singleton',
        staticmethod(lambda app_name='grub-wiz': fake),
    )
    (tmp_path / 'warn-db.yaml').write_text(
        'inhibited: not-a-list\nall_warnings: not-a-mapping\n',
        encoding='utf-8')

    warn_db = WarnDB(param_cfg=None)

    assert warn_db.inhibits == set()
    assert warn_db.all_info == {}


def test_grubfile_reread_clears_previous_state(tmp_path):
    """A second read must forget the blacklist and adopted extra params."""
    conf = tmp_path / 'grub'
    conf.write_text(
        'GRUB_TIMEOUT=5\n'
        'GRUB_FOO=$GRUB_TIMEOUT\n'
        'GRUB_BAR=baz\n',
        encoding='utf-8',
    )

    grub = GrubFile({'GRUB_TIMEOUT': {'default': '5', 'guidance': ''}},
                    file_path=str(conf))
    assert grub.blacklisted_params == {'GRUB_FOO'}
    assert 'GRUB_BAR' in grub.extra_params
    assert 'GRUB_BAR' in grub.supported_params

    # The file no longer uses expansion and no longer defines GRUB_BAR.
    conf.write_text('GRUB_TIMEOUT=7\n', encoding='utf-8')
    grub.read_file()

    assert grub.blacklisted_params == set()
    assert grub.extra_params == {}
    assert 'GRUB_BAR' not in grub.supported_params
    assert set(grub.param_data) == {'GRUB_TIMEOUT'}
    assert grub.get_current_state('GRUB_TIMEOUT') == '7'


def test_prefix_expansion_uses_existing_grub_dir(monkeypatch):
    """``$prefix`` must resolve to /boot/grub2 when that is the distro layout."""
    validator = WizValidator({})
    monkeypatch.setattr(
        'grub_wiz.WizValidator.os.path.isdir',
        lambda path: path == '/boot/grub2',
    )
    monkeypatch.setattr(
        'grub_wiz.WizValidator.os.path.exists',
        lambda path: path == '/boot/grub2/theme.txt',
    )

    exists, resolved = validator.get_full_path_and_check_existence(
        '$prefix/theme.txt')

    assert exists is True
    assert resolved == '/boot/grub2/theme.txt'


def test_prompt_line_treats_eof_as_default(monkeypatch):
    """A closed stdin must not abort the post-commit prompts with EOFError."""

    def raise_eof(_prompt):
        raise EOFError

    monkeypatch.setattr(builtins, 'input', raise_eof)

    assert prompt_line('\n> ', default='') == ''
    assert prompt_line('Continue? [y/N]: ', default='n') == 'n'


def test_single_quoted_continuation_is_joined(tmp_path):
    """Values in single quotes must continue onto the next line too."""
    conf = tmp_path / 'grub'
    conf.write_text(
        "GRUB_CMDLINE_LINUX_DEFAULT='quiet splash \\\n"
        "nowatchdog'\n"
        'GRUB_TIMEOUT=5\n',
        encoding='utf-8',
    )

    grub = GrubFile(
        {'GRUB_CMDLINE_LINUX_DEFAULT': {}, 'GRUB_TIMEOUT': {}},
        file_path=str(conf),
    )

    assert grub.lines[0] == (
        "GRUB_CMDLINE_LINUX_DEFAULT='quiet splash nowatchdog'\n")
    assert grub.get_current_state('GRUB_CMDLINE_LINUX_DEFAULT') == \
        "'quiet splash nowatchdog'"
    assert grub.get_current_state('GRUB_TIMEOUT') == '5'


def test_commented_single_quoted_continuation_is_joined(tmp_path):
    """A commented-out value keeps its comment while being joined."""
    conf = tmp_path / 'grub'
    conf.write_text(
        "#GRUB_CMDLINE_LINUX_DEFAULT='quiet \\\n"
        "#splash'\n"
        'GRUB_TIMEOUT=5\n',
        encoding='utf-8',
    )

    grub = GrubFile(
        {'GRUB_CMDLINE_LINUX_DEFAULT': {}, 'GRUB_TIMEOUT': {}},
        file_path=str(conf),
    )

    data = grub.param_data['GRUB_CMDLINE_LINUX_DEFAULT']
    assert data.value == grub.COMMENT
    assert data.out_value == "'quiet splash'"
    assert grub.get_current_state('GRUB_TIMEOUT') == '5'


def test_malformed_trailing_backslash_does_not_join_next_line(tmp_path):
    """A backslash after an already-closed value is not a continuation."""
    conf = tmp_path / 'grub'
    conf.write_text(
        'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash" \\\n'
        'GRUB_TIMEOUT=5\n',
        encoding='utf-8',
    )

    grub = GrubFile(
        {'GRUB_CMDLINE_LINUX_DEFAULT': {}, 'GRUB_TIMEOUT': {}},
        file_path=str(conf),
    )

    assert len(grub.lines) == 2
    assert grub.get_current_state('GRUB_TIMEOUT') == '5'


def test_escaped_trailing_backslash_is_not_a_continuation(tmp_path):
    """A literal (doubled) backslash must not continue the line."""
    conf = tmp_path / 'grub'
    conf.write_text(
        'GRUB_FOO="path\\\\\n'
        'GRUB_TIMEOUT=5\n',
        encoding='utf-8',
    )

    grub = GrubFile(
        {'GRUB_FOO': {}, 'GRUB_TIMEOUT': {}},
        file_path=str(conf),
    )

    assert len(grub.lines) == 2
    assert grub.get_current_state('GRUB_TIMEOUT') == '5'


def test_free_form_comment_backslash_is_not_joined(tmp_path):
    """Prose comments containing '=' and a quote must never swallow a line."""
    conf = tmp_path / 'grub'
    conf.write_text(
        '# set GRUB_TIMEOUT=5 "loudly" \\\n'
        'GRUB_TIMEOUT=5\n',
        encoding='utf-8',
    )

    grub = GrubFile({'GRUB_TIMEOUT': {}}, file_path=str(conf))

    assert len(grub.lines) == 2
    assert grub.get_current_state('GRUB_TIMEOUT') == '5'


def test_unterminated_quote_does_not_swallow_next_param(tmp_path):
    """An open quote followed by a new assignment stops the join."""
    conf = tmp_path / 'grub'
    conf.write_text(
        'GRUB_CMDLINE_LINUX_DEFAULT="unterminated \\\n'
        'GRUB_TIMEOUT=5\n',
        encoding='utf-8',
    )

    grub = GrubFile(
        {'GRUB_CMDLINE_LINUX_DEFAULT': {}, 'GRUB_TIMEOUT': {}},
        file_path=str(conf),
    )

    assert len(grub.lines) == 2
    assert grub.get_current_state('GRUB_TIMEOUT') == '5'


def test_long_params_has_no_stray_slash():
    assert '/' not in GrubWiz.long_params


def test_unknown_param_is_not_active():
    gw = GrubWiz.__new__(GrubWiz)
    gw.param_values = SimpleNamespace(
        get=lambda _name, _default=None: None,
    )

    assert gw.is_active_param('GRUB_DOES_NOT_EXIST') is False
