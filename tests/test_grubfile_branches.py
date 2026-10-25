"""Parsing and writing branches in ``GrubFile`` not covered elsewhere.

The main parsing suite covers continuations and expansion, and the sentinel
tests cover ABSENT/COMMENT.  This file covers duplicate assignments, missing
files, discovery filtering, unknown-parameter adoption, and write failures.
"""

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz.GrubFile import GrubFile
from grub_wiz.ParamDiscovery import ParamDiscovery


def make_grub(tmp_path, text, params=None):
    conf = tmp_path / 'grub'
    conf.write_text(text, encoding='utf-8')
    return GrubFile(params or {}, file_path=str(conf)), conf


def write_to_string(grub):
    output = io.StringIO()
    with redirect_stdout(output):
        assert grub.write_file(use_stdout=True) is True
    return output.getvalue()


def test_last_uncommented_duplicate_wins_and_earlier_line_is_commented(tmp_path):
    grub, _conf = make_grub(
        tmp_path, 'GRUB_TIMEOUT=5\nGRUB_TIMEOUT=7\n',
        {'GRUB_TIMEOUT': {'guidance': ''}})

    data = grub.param_data['GRUB_TIMEOUT']
    assert data.value == '7'
    assert data.line_num == 1
    assert grub.lines[0].startswith('#GRUB_TIMEOUT=5')
    assert grub.param_of[0] is None

    text = write_to_string(grub)
    assert '#GRUB_TIMEOUT=5' in text
    assert 'GRUB_TIMEOUT=7' in text


def test_later_commented_duplicate_does_not_override_active_value(tmp_path):
    grub, _conf = make_grub(
        tmp_path, 'GRUB_TIMEOUT=5\n#GRUB_TIMEOUT=9\n',
        {'GRUB_TIMEOUT': {'guidance': ''}})

    assert grub.get_current_state('GRUB_TIMEOUT') == '5'
    assert grub.param_data['GRUB_TIMEOUT'].line_num == 0


def test_commented_only_value_is_tracked_as_comment(tmp_path):
    grub, _conf = make_grub(
        tmp_path, '#GRUB_TIMEOUT=9\n',
        {'GRUB_TIMEOUT': {'guidance': ''}})

    data = grub.param_data['GRUB_TIMEOUT']
    assert data.value == grub.COMMENT
    assert data.out_value == '9'


def test_earlier_comment_is_superseded_by_active_value(tmp_path):
    grub, _conf = make_grub(
        tmp_path, '#GRUB_TIMEOUT=9\nGRUB_TIMEOUT=5\n',
        {'GRUB_TIMEOUT': {'guidance': ''}})

    assert grub.get_current_state('GRUB_TIMEOUT') == '5'
    assert grub.param_data['GRUB_TIMEOUT'].line_num == 1
    assert grub.param_of[0] is None


def test_missing_file_starts_empty_with_warning(tmp_path, capsys):
    grub = GrubFile({'GRUB_TIMEOUT': {'guidance': ''}},
                    file_path=str(tmp_path / 'missing'))

    assert grub.lines == []
    # The early return leaves param_data uninitialised; the warning is the
    # observable contract for a missing defaults file.
    assert grub.param_data == {}
    assert 'File not found' in capsys.readouterr().out


def test_discovery_absent_parameter_is_not_adopted(tmp_path, monkeypatch):
    fake = SimpleNamespace(get_absent=lambda names: set(names))
    monkeypatch.setattr(ParamDiscovery, 'get_singleton', staticmethod(lambda: fake))

    grub, _conf = make_grub(tmp_path, 'GRUB_SKIP=1\n')

    assert grub.extra_params == {}
    assert grub.param_data == {}


def test_unknown_parameter_is_adopted_with_guidance(tmp_path, monkeypatch):
    fake = SimpleNamespace(get_absent=lambda _names: set())
    monkeypatch.setattr(ParamDiscovery, 'get_singleton', staticmethod(lambda: fake))

    grub, _conf = make_grub(
        tmp_path, '# Theme path\nGRUB_THEME=/boot/grub/themes/x\n')

    assert 'GRUB_THEME' in grub.extra_params
    assert 'GRUB_THEME' in grub.supported_params
    assert grub.extra_params['GRUB_THEME']['guidance'] == 'Theme path'
    assert grub.get_current_state('GRUB_THEME') == '/boot/grub/themes/x'


def test_guidance_is_wrapped_when_appending(tmp_path):
    guidance = ('Select the theme directory used by the graphical menu; '
                'this text is deliberately long enough to wrap over more '
                'than one comment line.')
    grub, _conf = make_grub(tmp_path, 'GRUB_TIMEOUT=5\n',
                            {'GRUB_TIMEOUT': {'guidance': ''},
                             'GRUB_THEME': {'guidance': guidance}})
    grub.set_new_value('GRUB_THEME', '/boot/grub/themes/x')

    text = write_to_string(grub)

    assert 'GRUB_THEME=/boot/grub/themes/x' in text
    comment_lines = [line for line in text.splitlines()
                     if line.startswith('+  # ')]
    assert len(comment_lines) >= 2


def test_write_failure_returns_false(tmp_path, isolated_user_config_dir,
                                    monkeypatch, capsys):
    grub, _conf = make_grub(tmp_path, 'GRUB_TIMEOUT=5\n',
                            {'GRUB_TIMEOUT': {'guidance': ''}})

    def deny(*_a, **_k):
        raise OSError('read-only destination')

    monkeypatch.setattr(isolated_user_config_dir, 'atomic_write', deny)

    assert grub.write_file(str(tmp_path / 'out')) is False
    assert 'read-only destination' in capsys.readouterr().out


@pytest.mark.parametrize('raw, expected', [
    ('5 # comment', '5'),
    ('"has #hash" #comment', '"has #hash"'),
    ("'has #hash'", "'has #hash'"),
    ('   spaced   ', 'spaced'),
])
def test_cleanse_clips_only_unquoted_comments(raw, expected):
    grub = object.__new__(GrubFile)

    assert grub._cleanse(raw) == expected


@pytest.mark.parametrize('text, expected', [
    ('"unterminated', '"'),
    ("'unterminated", "'"),
    ('"closed"', None),
    ('plain', None),
    (r'"escaped \" still open', '"'),
])
def test_open_quote_tracks_escapes(text, expected):
    assert GrubFile._open_quote(text) == expected


@pytest.mark.parametrize('text, expected', [
    ('x\\', True),
    ('x\\\\', False),
    ('x', False),
    ('x\\\\\\', True),
])
def test_is_continuation_line_respects_escaped_backslashes(text, expected):
    assert GrubFile._is_continuation_line(text) is expected
