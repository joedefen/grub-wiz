"""Loading, fallback, and post-processing of the active canned config.

Schema validation is covered elsewhere.  These tests exercise the part that
decides *which* file becomes active: the reference copy, a valid
``custom_config.yaml``, and every failure mode that must fall back to the
packaged config.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import grub_wiz.CannedConfig as cc_mod
from grub_wiz.CannedConfig import EXPERT_EDIT, CannedConfig


def minimal_config(timeout='5'):
    """A schema-valid config with one parameter."""
    return (
        'Boot:\n'
        '  GRUB_TIMEOUT:\n'
        f'    default: {timeout!r}\n'
        "    edit_re: ''\n"
        '    enums: {}\n'
        "    guidance: ''\n"
    )


def write_custom(fake, text):
    path = fake.user_state_dir / 'custom_config.yaml'
    path.write_text(text, encoding='utf-8')
    return path


def test_reference_copy_is_created_when_missing(isolated_user_config_dir):
    cfg = CannedConfig()

    ref = isolated_user_config_dir.user_state_dir / 'canned_config.yaml'
    assert ref.is_file()
    assert cfg.using_path.name == 'canned_config.yaml'
    assert 'GRUB_TIMEOUT' in ref.read_text(encoding='utf-8')


def test_existing_reference_copy_is_not_overwritten(isolated_user_config_dir):
    ref = isolated_user_config_dir.user_state_dir / 'canned_config.yaml'
    ref.write_text('do not touch\n', encoding='utf-8')

    CannedConfig()

    assert ref.read_text(encoding='utf-8') == 'do not touch\n'


def test_valid_custom_config_becomes_active(isolated_user_config_dir):
    custom = write_custom(isolated_user_config_dir, minimal_config('12'))

    cfg = CannedConfig()

    assert Path(cfg.using_path) == custom
    assert cfg.data['Boot']['GRUB_TIMEOUT']['default'] == '12'


def test_invalid_schema_falls_back_with_warning(isolated_user_config_dir,
                                                capsys):
    write_custom(isolated_user_config_dir,
                 'Boot:\n  GRUB_TIMEOUT:\n    default: 5\n')

    cfg = CannedConfig()

    assert 'custom_config.yaml' not in str(cfg.using_path)
    output = capsys.readouterr().out
    assert 'invalid' in output and 'using canned config' in output


def test_unreadable_custom_config_falls_back(isolated_user_config_dir,
                                             capsys):
    real = isolated_user_config_dir.user_state_dir / 'real-custom.yaml'
    real.write_text(minimal_config(), encoding='utf-8')
    custom = isolated_user_config_dir.user_state_dir / 'custom_config.yaml'
    custom.symlink_to(real)

    cfg = CannedConfig()

    assert 'custom_config.yaml' not in str(cfg.using_path)
    assert 'Refusing to read' in capsys.readouterr().out


def test_malformed_yaml_falls_back(isolated_user_config_dir, capsys):
    write_custom(isolated_user_config_dir, 'a: [unterminated\n')

    cfg = CannedConfig()

    assert 'custom_config.yaml' not in str(cfg.using_path)
    assert 'Cannot yaml.load' in capsys.readouterr().out


def processed(data):
    """Run ``_process_config()`` on plain data without touching user state."""
    cfg = object.__new__(CannedConfig)
    cfg.data = data
    cfg._process_config()
    return cfg


def test_invalid_regex_spec_is_reported_and_degraded(capsys):
    data = {
        '_re_specs_': {'bad': {'re': '(', 'human': 'broken'}},
        'Boot': {'GRUB_X': {'edit_re': 'bad'}},
    }

    processed(data)

    cfg = data['Boot']['GRUB_X']
    assert cfg['edit_re'] == ''
    assert cfg['edit_re_human'] == 'broken'
    assert cfg['allow_command_sub'] is False
    assert 'Invalid regex in _re_specs_.bad' in capsys.readouterr().out


def test_invalid_inline_regex_is_reported_and_cleared(capsys):
    data = {'Boot': {'GRUB_X': {'edit_re': '('}}}

    processed(data)

    cfg = data['Boot']['GRUB_X']
    assert cfg['edit_re'] == ''
    assert cfg['edit_re_human'] == ''
    assert 'Invalid inline regex for GRUB_X' in capsys.readouterr().out


def test_expert_edit_sentinel_is_preserved():
    data = {'Boot': {'GRUB_X': {'edit_re': EXPERT_EDIT}}}

    processed(data)

    cfg = data['Boot']['GRUB_X']
    assert cfg['edit_re'] == EXPERT_EDIT
    assert cfg['edit_re_human'] == ''
    assert cfg['allow_command_sub'] is False


def test_regex_spec_propagates_command_substitution_opt_in():
    data = {
        '_re_specs_': {
            'command': {'re': r'^\$\(.*\)$', 'human': 'command',
                        'allow_command_sub': True},
        },
        'Boot': {'GRUB_DISTRIBUTOR': {'edit_re': 'command'}},
    }

    processed(data)

    cfg = data['Boot']['GRUB_DISTRIBUTOR']
    assert cfg['allow_command_sub'] is True
    assert cfg['edit_re_human'] == 'command'
    assert cfg['edit_re'].search('$(lsb_release -i -s)')


def test_non_dict_sections_and_params_are_skipped():
    data = {
        '_metadata_': 1,
        'BadSection': ['not', 'a', 'mapping'],
        'Boot': {'GRUB_X': 'not-a-config'},
    }

    processed(data)

    assert data['BadSection'] == ['not', 'a', 'mapping']
    assert data['Boot']['GRUB_X'] == 'not-a-config'


def test_validate_schema_rejects_extra_parameter_keys():
    cfg = object.__new__(CannedConfig)
    data = {
        'Boot': {
            'GRUB_TIMEOUT': {
                'default': '5', 'edit_re': '', 'enums': {}, 'guidance': '',
                'bogus': 1,
            },
        },
    }

    err = cfg.validate_schema(data)

    assert 'extra keys' in err


def test_module_main_prints_the_active_config(monkeypatch, capsys):
    calls = []

    class FakeCanned:
        def dump(self):
            calls.append('dump')
            print('dumped-config')

    monkeypatch.setattr(cc_mod, 'CannedConfig', FakeCanned)

    cc_mod.main()

    assert calls == ['dump']
    assert 'dumped-config' in capsys.readouterr().out
