"""``reinit_gw()`` must leave no stale state behind (AUDIT.md M11).

Re-initialization happens after a restore or a write, i.e. exactly when the
process keeps running with new state.  Three things used to go wrong:

* ``param_cfg`` was rebuilt as a new dict while the validator kept the old one,
  so warnings were computed against the previous session's configuration.
* ``self.sections`` was the loaded ``canned_config.data`` itself, so the app's
  "Unvalidated Params" section and the probed GRUB menu entries accumulated
  inside the shared config and survived into the next file.
* ``GrubFile`` reads in its constructor and ``reinit_gw()`` called
  ``read_file()`` again, doubling the I/O and every parsing side effect.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import grub_wiz.main as main_mod  # noqa: E402
from grub_wiz.GrubFile import GrubFile  # noqa: E402


class FakeGrubFile:
    """``GrubFile`` stand-in that reads in its constructor, like the real one."""

    files: dict = {}   # file_path -> {param: value}
    extras: dict = {}  # file_path -> {param: cfg}

    def __init__(self, supported_params, file_path=None):
        self.file_path = file_path
        self.supported_params = dict(supported_params)
        self.extra_params = {}
        self.reads = 0
        self.read_file()

    def read_file(self):
        self.reads += 1
        values = self.files.get(self.file_path, {})
        extras = self.extras.get(self.file_path, {})
        self.extra_params = {name: dict(cfg) for name, cfg in extras.items()}
        self.param_data = {
            name: SimpleNamespace(value=values.get(name, GrubFile.ABSENT),
                                  line_num=None, new_value=None, out_value=None)
            for name in list(self.supported_params) + list(self.extra_params)
        }


class RecordingValidator:
    """Records every config it is bound to."""

    def __init__(self, param_cfg, initramfs_tool=None):
        self.param_cfg = param_cfg
        self.initramfs_tool = initramfs_tool
        self.bound = []

    def bind_param_cfg(self, param_cfg):
        self.bound.append(param_cfg)
        self.param_cfg = param_cfg

    def make_warns(self, values):
        return {}, {}


class FakeWarnDB:
    """WarnDB stand-in; reinit only audits and flushes it."""

    def __init__(self, param_cfg=None, filename='warn-db.yaml'):
        self.param_cfg = param_cfg

    def audit_info(self, info):
        pass

    def write_if_dirty(self):
        pass


@pytest.fixture(autouse=True)
def reset_fake_grubfile():
    """Keep the class-level fixtures of ``FakeGrubFile`` per-test."""
    FakeGrubFile.files = {}
    FakeGrubFile.extras = {}
    yield
    FakeGrubFile.files = {}
    FakeGrubFile.extras = {}


def _make_gw(monkeypatch, tmp_path, menu_entries=()):
    monkeypatch.setattr(main_mod, 'GrubFile', FakeGrubFile)
    monkeypatch.setattr(main_mod, 'WizValidator', RecordingValidator)
    monkeypatch.setattr(main_mod, 'WarnDB', FakeWarnDB)
    monkeypatch.setattr(main_mod, 'get_top_level_grub_entries',
                        lambda _path: list(menu_entries))

    gw = object.__new__(main_mod.GrubWiz)
    gw.canned_config = SimpleNamespace(data={
        '_re_specs_': {'timeout': {'re': r'^\d+$', 'human': 'seconds'}},
        'Basic': {
            'GRUB_TIMEOUT': {'default': '5', 'enums': {}, 'guidance': ''},
            'GRUB_DEFAULT': {'default': '0', 'enums': {}, 'guidance': ''},
        },
    })
    gw.distro_vars = SimpleNamespace(etc_grub=str(tmp_path / 'grub'),
                                     update_initramfs=None, grub_cfg=None)
    gw.param_discovery = SimpleNamespace(ensure_discovered=lambda: set(),
                                         get_absent=lambda _names: set())
    gw.wiz_validator = None
    gw.refresh_backup_list = lambda: None
    gw.reinit_gw()
    return gw


def test_reinit_rebinds_the_validator_to_the_rebuilt_config(monkeypatch, tmp_path):
    """The validator must follow the new ``param_cfg`` dict, not the old one."""
    gw = _make_gw(monkeypatch, tmp_path)
    validator = gw.wiz_validator
    old_cfg = gw.param_cfg

    gw.reinit_gw()

    assert gw.wiz_validator is validator      # the disk-layout cache survives
    assert gw.param_cfg is not old_cfg        # reinit really builds a new dict
    assert validator.param_cfg is gw.param_cfg
    assert validator.bound and validator.bound[-1] is gw.param_cfg


def test_reinit_does_not_mutate_the_shared_canned_config(monkeypatch, tmp_path):
    """App state must not accumulate inside ``canned_config.data``."""
    menu_entries = [{'type': 'menuentry', 'title': "'Linux'"}]
    gw = _make_gw(monkeypatch, tmp_path, menu_entries=menu_entries)
    canned = gw.canned_config.data
    snapshot = {
        'private': dict(canned['_re_specs_']),
        'enums': dict(canned['Basic']['GRUB_DEFAULT']['enums']),
        'sections': sorted(canned),
    }

    gw.reinit_gw()

    assert dict(canned['_re_specs_']) == snapshot['private']
    assert dict(canned['Basic']['GRUB_DEFAULT']['enums']) == snapshot['enums']
    assert sorted(canned) == snapshot['sections']
    assert 'Unvalidated Params' not in canned
    # The copy is where the app works, so the menu entries reached it.
    assert gw.sections is not canned
    assert "'Linux'" in gw.param_cfg['GRUB_DEFAULT']['enums']


def test_reinit_drops_the_previous_sessions_unvalidated_section(monkeypatch, tmp_path):
    """A section built from the old file must not survive into the new one."""
    gw = _make_gw(monkeypatch, tmp_path)
    extras_path = tmp_path / 'with-extras'
    plain_path = tmp_path / 'plain'
    FakeGrubFile.extras[str(extras_path)] = {
        'GRUB_CUSTOM_THING': {'default': 'yes', 'enums': {}, 'guidance': '',
                              'edit_re': ''},
    }

    gw.distro_vars.etc_grub = str(extras_path)
    gw.reinit_gw()
    assert 'Unvalidated Params' in gw.sections
    assert 'GRUB_CUSTOM_THING' in gw.param_cfg

    gw.distro_vars.etc_grub = str(plain_path)
    gw.reinit_gw()

    assert 'Unvalidated Params' not in gw.sections
    assert 'GRUB_CUSTOM_THING' not in gw.param_cfg
    assert 'GRUB_CUSTOM_THING' not in gw.param_names


def test_reinit_reads_the_grub_file_once(monkeypatch, tmp_path):
    """The constructor already reads; reinit must not read a second time."""
    gw = _make_gw(monkeypatch, tmp_path)

    gw.reinit_gw()

    assert gw.grub_file.reads == 1
