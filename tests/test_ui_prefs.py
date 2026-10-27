"""Persistence boundary for ``UiPrefs`` (the remembered theme choice).

The file is cosmetic state, so every failure mode must degrade to "works for
this session" instead of aborting start-up: a missing file, a corrupt one, a
hand edit that put a scalar at the top level, and a read-only directory.
"""

import sys
from pathlib import Path

from ruamel.yaml import YAML

sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz.UiPrefs import UiPrefs  # noqa: E402


def prefs_path(fake):
    return fake.user_state_dir / 'ui-prefs.yaml'


def test_missing_file_starts_empty(isolated_user_config_dir):
    prefs = UiPrefs()

    assert prefs.as_dict() == {}
    assert prefs.get('theme') is None
    assert prefs.get('theme', 'default') == 'default'


def test_set_persists_and_a_new_instance_reads_it(isolated_user_config_dir):
    prefs = UiPrefs()

    assert prefs.set('theme', 'nord') is True

    stored = YAML().load(prefs_path(isolated_user_config_dir).read_text(encoding='utf-8'))
    assert stored == {'theme': 'nord'}
    assert UiPrefs().get('theme') == 'nord'


def test_setting_the_same_value_twice_is_a_noop(isolated_user_config_dir):
    prefs = UiPrefs()
    prefs.set('theme', 'nord')
    first = prefs_path(isolated_user_config_dir).stat().st_mtime_ns

    assert prefs.set('theme', 'nord') is True
    assert prefs_path(isolated_user_config_dir).stat().st_mtime_ns == first


def test_malformed_yaml_is_ignored(isolated_user_config_dir, capsys):
    prefs_path(isolated_user_config_dir).write_text(
        'theme: [unterminated\n', encoding='utf-8')

    prefs = UiPrefs()

    assert prefs.as_dict() == {}
    assert 'failed to read ui-prefs.yaml' in capsys.readouterr().out


def test_non_mapping_document_is_ignored(isolated_user_config_dir, capsys):
    prefs_path(isolated_user_config_dir).write_text(
        '- just\n- a list\n', encoding='utf-8')

    prefs = UiPrefs()

    assert prefs.as_dict() == {}
    assert 'is not a mapping' in capsys.readouterr().out


def test_read_error_is_reported_and_state_cleared(isolated_user_config_dir,
                                                  monkeypatch, capsys):
    prefs_path(isolated_user_config_dir).write_text('theme: nord\n',
                                                    encoding='utf-8')
    prefs = UiPrefs()
    assert prefs.get('theme') == 'nord'

    def deny(*_args, **_kwargs):
        raise OSError('permission denied')

    monkeypatch.setattr(isolated_user_config_dir, 'safe_read_text', deny)

    assert prefs.refresh() is True
    assert prefs.as_dict() == {}
    assert 'refusing to read ui-prefs.yaml' in capsys.readouterr().out


def test_write_failure_keeps_the_value_for_this_session(
        isolated_user_config_dir, monkeypatch, capsys):
    prefs = UiPrefs()

    def deny(*_args, **_kwargs):
        raise OSError('disk full')

    monkeypatch.setattr(isolated_user_config_dir, 'atomic_user_write', deny)

    assert prefs.set('theme', 'gruvbox') is False
    assert prefs.get('theme') == 'gruvbox'
    assert 'could not save ui-prefs.yaml' in capsys.readouterr().out


def test_delete_removes_the_file(isolated_user_config_dir):
    prefs = UiPrefs()
    prefs.set('theme', 'nord')

    assert prefs.delete() is True
    assert not prefs_path(isolated_user_config_dir).exists()
    assert prefs.as_dict() == {}
    # A second delete is "nothing to do", not an error.
    assert prefs.delete() is False
