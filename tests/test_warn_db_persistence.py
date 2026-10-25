"""Persistence formats and failure handling in ``WarnDB``.

``audit_info()`` is already covered.  These tests cover the file boundary:
reading the legacy format, rejecting corrupt documents, writing only when
dirty, and reporting write failures instead of crashing the UI.
"""

import sys
from pathlib import Path

import pytest
from ruamel.yaml import YAML

sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz.WarnDB import WarnDB


def db_path(fake):
    return fake.user_state_dir / 'warn-db.yaml'


def write_db(fake, text):
    db_path(fake).write_text(text, encoding='utf-8')


def make_db(fake):
    return WarnDB(param_cfg=None)


def test_missing_file_starts_empty(isolated_user_config_dir):
    db = make_db(isolated_user_config_dir)

    assert db.inhibits == set()
    assert db.all_info == {}
    assert db.dirty_count == 0


def test_legacy_warns_list_migrates_to_inhibits(isolated_user_config_dir):
    write_db(isolated_user_config_dir,
             "warns:\n- 'GRUB_TIMEOUT: first'\n- 'GRUB_DEFAULT: second'\n")

    db = make_db(isolated_user_config_dir)

    assert db.inhibits == {
        'GRUB_TIMEOUT: first', 'GRUB_DEFAULT: second'}
    assert db.all_info == {}


@pytest.mark.parametrize('document', [
    'all_warnings: [unterminated\n',
    'inhibited: [unterminated\n',
])
def test_malformed_yaml_is_ignored(isolated_user_config_dir, document, capsys):
    write_db(isolated_user_config_dir, document)

    db = make_db(isolated_user_config_dir)

    assert db.inhibits == set()
    assert db.all_info == {}
    assert 'Failed to read warn-db.yaml' in capsys.readouterr().out


def test_read_error_is_reported_and_state_cleared(isolated_user_config_dir,
                                                  monkeypatch, capsys):
    write_db(isolated_user_config_dir, 'inhibited:\n- old\n')
    db = make_db(isolated_user_config_dir)
    assert db.inhibits == {'old'}

    def deny(*_a, **_k):
        raise OSError('permission denied')

    monkeypatch.setattr(isolated_user_config_dir, 'safe_read_text', deny)

    assert db.refresh() is True
    assert db.inhibits == set()
    assert db.all_info == {}
    assert 'Refusing to read' in capsys.readouterr().out


def test_write_if_dirty_is_a_noop_when_clean(isolated_user_config_dir):
    db = make_db(isolated_user_config_dir)

    assert db.write_if_dirty() is False
    assert not db_path(isolated_user_config_dir).exists()


def test_write_if_dirty_persists_sorted_state(isolated_user_config_dir):
    db = make_db(isolated_user_config_dir)
    db.all_info = {'GRUB_TIMEOUT: b': 2, 'GRUB_DEFAULT: a': 4}
    db.inhibits = {'GRUB_DEFAULT: a'}
    db.dirty_count = 2

    assert db.write_if_dirty() is True

    assert db.dirty_count == 0
    assert db.get_last_read_time() is not None
    data = YAML().load(db_path(isolated_user_config_dir).read_text(encoding='utf-8'))
    assert list(data['all_warnings']) == ['GRUB_DEFAULT: a', 'GRUB_TIMEOUT: b']
    assert data['inhibited'] == ['GRUB_DEFAULT: a']


def test_write_failure_is_reported_and_keeps_dirty_state(
        isolated_user_config_dir, monkeypatch, capsys):
    db = make_db(isolated_user_config_dir)
    db.dirty_count = 1

    def deny(*_a, **_k):
        raise OSError('disk full')

    monkeypatch.setattr(isolated_user_config_dir, 'atomic_user_write', deny)

    assert db.write_if_dirty() is False
    assert db.dirty_count == 1
    assert 'Error writing' in capsys.readouterr().out


def test_inhibit_and_uninhibit_only_dirty_on_change(isolated_user_config_dir):
    db = make_db(isolated_user_config_dir)

    db.inhibit('GRUB_TIMEOUT: one', True)
    assert db.is_inhibit('GRUB_TIMEOUT: one')
    assert db.dirty_count == 1

    db.inhibit('GRUB_TIMEOUT: one', True)
    assert db.dirty_count == 1

    db.inhibit('GRUB_TIMEOUT: one', False)
    assert not db.is_inhibit('GRUB_TIMEOUT: one')
    assert db.dirty_count == 2

    db.inhibit('GRUB_TIMEOUT: one', False)
    assert db.dirty_count == 2
