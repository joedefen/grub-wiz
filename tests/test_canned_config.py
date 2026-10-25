"""Regression tests for the custom-config workflow in ``CannedConfig``.

``README.md`` documents copying the packaged ``canned_config.yaml`` to
``custom_config.yaml`` and editing it.  That template must therefore pass the
same ``validate_schema()`` check that is applied to user configs.

Two historical bugs are covered here:

* ``edit_re_human`` was required by the validator even though it is injected
  by ``_process_config()`` at runtime and never appears in the YAML.
* Reserved top-level metadata sections (``_distro_vars_``, ``_re_specs_``,
  ``_update_initramfs_triggers_``) were treated as GRUB parameters and
  rejected for not starting with ``GRUB_``.
"""

from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace

import pytest
from ruamel.yaml import YAML

import grub_wiz.CannedConfig as canned_config_module
from grub_wiz.CannedConfig import CannedConfig


def _packaged_text():
    """Return the packaged template as text."""
    return files('grub_wiz').joinpath('canned_config.yaml').read_text(encoding='utf-8')


def _packaged_data():
    """Load the packaged template as YAML data."""
    return YAML().load(_packaged_text())


def _validator():
    """An instance sufficient for ``validate_schema()`` (class attrs only)."""
    return object.__new__(CannedConfig)


class _StubUserConfig:
    """In-memory stand-in for ``UserConfigDir`` used by ``CannedConfig``."""

    def __init__(self, directory):
        self.user_state_dir = directory

    def atomic_user_write(self, path, text, mode=0o644):
        Path(path).write_text(text, encoding='utf-8')

    def safe_read_text(self, path):
        return Path(path).read_text(encoding='utf-8')


def _isolate_user_config(monkeypatch, directory):
    """Point ``CannedConfig`` at ``directory`` instead of the real home."""
    stub = _StubUserConfig(directory)
    monkeypatch.setattr(
        canned_config_module,
        'UserConfigDir',
        SimpleNamespace(
            get_singleton=staticmethod(lambda app_name='grub-wiz': stub)),
    )


def test_packaged_template_passes_schema():
    """The documented starting point must validate as a custom config."""
    assert CannedConfig.validate_schema(_validator(), _packaged_data()) is None


def test_reserved_underscore_sections_are_skipped():
    """Metadata sections are not GRUB parameters and must not be rejected."""
    data = _packaged_data()
    assert '_distro_vars_' in data
    assert '_re_specs_' in data

    # Even a metadata section with no GRUB_* keys validates.
    assert CannedConfig.validate_schema(
        _validator(), {'_distro_vars_': {'grub_cfg': ['/boot/grub/grub.cfg']}}) is None

    # Removing reserved sections still leaves a valid parameter config.
    without_metadata = {k: v for k, v in data.items()
                        if not str(k).startswith('_')}
    assert CannedConfig.validate_schema(_validator(), without_metadata) is None


def test_edit_re_human_is_not_required():
    """``edit_re_human`` is derived at runtime, so it must be optional."""
    data = _packaged_data()
    data['Boot Timeout'] = dict(data['Boot Timeout'])
    data['Boot Timeout']['GRUB_TIMEOUT'] = {
        'default': 5,
        'edit_re': 're_timeout',
        'enums': {},
        'guidance': '',
    }
    assert CannedConfig.validate_schema(_validator(), data) is None


@pytest.mark.parametrize(
    'mutate, expected',
    [
        (lambda data: data['Boot Timeout'].update(grub_timeout={}),
         'is not GRUB_*'),
        (lambda data: data['Boot Timeout'].__setitem__(
            'GRUB_TIMEOUT', {'default': 5, 'edit_re': 're_timeout', 'guidance': ''}),
         'missing keys'),
        (lambda data: data['Boot Timeout']['GRUB_TIMEOUT'].__setitem__('bogus', 1),
         'extra keys'),
        (lambda data: data.__setitem__('Boot Timeout', None),
         'value not dict'),
    ],
)
def test_schema_rejects_malformed_sections(mutate, expected):
    """Genuine schema errors are still reported with a useful message."""
    data = _packaged_data()
    data['Boot Timeout'] = dict(data['Boot Timeout'])
    # Shallow-copy the nested config so parametrized cases cannot leak.
    data['Boot Timeout']['GRUB_TIMEOUT'] = dict(
        data['Boot Timeout']['GRUB_TIMEOUT'])
    mutate(data)
    err = CannedConfig.validate_schema(_validator(), data)
    assert err is not None
    assert expected in err


def test_non_mapping_root_is_reported():
    """A non-dict root returns an error string, not ``False``."""
    assert 'not a mapping' in CannedConfig.validate_schema(_validator(), ['nope'])


def test_copy_of_packaged_template_is_used_as_custom(tmp_path, monkeypatch):
    """An exact copy of the template is accepted and fully processed."""
    (tmp_path / 'custom_config.yaml').write_text(
        _packaged_text(), encoding='utf-8')
    _isolate_user_config(monkeypatch, tmp_path)

    cfg = CannedConfig()

    assert Path(cfg.using_path) == tmp_path / 'custom_config.yaml'
    timeout = cfg.data['Boot Timeout']['GRUB_TIMEOUT']
    # edit_re name was resolved against _re_specs_ ...
    assert timeout['edit_re'].pattern == r'^(-1|\d+)$'
    # ... and the human description was injected at runtime.
    assert timeout['edit_re_human'] == 'number (-1 for infinite, 0 or positive integer)'
    # Metadata needed by DistroVars survived the load.
    assert cfg.data['_distro_vars_']['grub_cfg'][0] == '/boot/grub/grub.cfg'


def test_invalid_custom_config_falls_back_to_packaged(
        tmp_path, monkeypatch, capsys):
    """Malformed custom configs warn and keep using the packaged template."""
    (tmp_path / 'custom_config.yaml').write_text(
        'Boot Timeout:\n  GRUB_TIMEOUT:\n    default: 5\n', encoding='utf-8')
    _isolate_user_config(monkeypatch, tmp_path)

    cfg = CannedConfig()

    assert 'invalid' in capsys.readouterr().out
    assert Path(cfg.using_path).name == 'canned_config.yaml'
    assert Path(cfg.using_path) != tmp_path / 'custom_config.yaml'
