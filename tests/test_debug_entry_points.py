"""Regression tests for the debug/demo entry points (audit M5).

Both helpers used to raise ``TypeError``:
- ``WizValidator.demo()`` treated the two return values of ``make_warns()``
  as an iterable of warning pairs.
- ``CannedConfig.dump()`` called ruamel's ``yaml.dump(data)`` without a
  stream.
"""

from types import SimpleNamespace

from grub_wiz.CannedConfig import CannedConfig
from grub_wiz.WizValidator import WizValidator


def _validator(param_cfg=None):
    """Build a validator whose disk probe cannot touch the host."""
    validator = WizValidator(param_cfg or {
        'GRUB_DEFAULT': {},
        'GRUB_SAVEDEFAULT': {},
        'GRUB_TIMEOUT': {},
    })
    validator.probe_disk_layout = lambda: SimpleNamespace(
        is_luks_active=False, has_another_os=False)
    return validator


def test_validator_demo_runs_and_prints_warnings(capsys):
    """``demo()`` unpacks ``make_warns()`` and prints each scenario."""
    _validator().demo({'GRUB_DEFAULT': '0', 'GRUB_TIMEOUT': '5'})

    output = capsys.readouterr().out
    assert 'DEFAULT=saved without SAVEDEFAULT=true' in output
    assert 'when "saved", SAVEDEFAULT cannot be "false"' in output
    assert '****' in output
    assert 'Clean config - no issues' in output
    assert '(no warnings)' in output


def test_canned_config_dump_uses_a_stream(capsys):
    """``dump()`` must pass a stream to ruamel and print the YAML."""
    cfg = object.__new__(CannedConfig)
    cfg.data = {'Boot': {'GRUB_TIMEOUT': {
        'default': '5', 'edit_re': '', 'enums': {}, 'guidance': ''}}}

    cfg.dump()

    output = capsys.readouterr().out
    assert 'GRUB_TIMEOUT' in output
    assert "default: '5'" in output
