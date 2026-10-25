"""Single source of truth for the GRUB defaults path (AUDIT.md M10).

Historically the path was hardcoded in ``GrubFile.std_location`` and in
``BackupMgr.GRUB_DEFAULT_PATH`` while ``DistroVars`` resolved it from YAML.
``GrubWiz.reinit_gw()`` also built ``GrubFile`` without a path, so reads could
diverge from the commits, which already used ``DistroVars.etc_grub``.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz.BackupMgr import GRUB_DEFAULT_PATH, BackupMgr  # noqa: E402
from grub_wiz.DistroVars import DEFAULT_ETC_GRUB, DistroVars  # noqa: E402
from grub_wiz.GrubFile import GrubFile  # noqa: E402


def test_all_fallbacks_derive_from_one_constant():
    assert DEFAULT_ETC_GRUB == '/etc/default/grub'
    assert GrubFile.std_location == DEFAULT_ETC_GRUB
    assert GRUB_DEFAULT_PATH == Path(DEFAULT_ETC_GRUB)
    assert DistroVars.default_yaml['_distro_vars_']['etc_grub'] == [DEFAULT_ETC_GRUB]


def test_backup_manager_coerces_target_to_path(tmp_path):
    target = tmp_path / 'grub'
    manager = BackupMgr(target_path=str(target))

    assert manager.target_path == target
    assert isinstance(manager.target_path, Path)


def test_reinit_gw_reads_the_distro_resolved_etc_grub(monkeypatch, tmp_path):
    """``reinit_gw()`` must pass ``DistroVars.etc_grub`` to ``GrubFile``."""
    import grub_wiz.main as main_mod

    seen = {}

    class FakeGrubFile:
        def __init__(self, supported_params, file_path=None):
            seen['file_path'] = file_path
            self.param_data = {
                name: SimpleNamespace(value=GrubFile.ABSENT, line_num=None,
                                      new_value=None, out_value=None)
                for name in supported_params
            }
            self.extra_params = {}

        def read_file(self):
            seen['read_file'] = True

    class FakeValidator:
        def __init__(self, param_cfg, initramfs_tool=None):
            pass

        def make_warns(self, values):
            return {}, {}

    class FakeWarnDB:
        def __init__(self, param_cfg=None):
            pass

        def audit_info(self, info):
            pass

        def write_if_dirty(self):
            pass

    monkeypatch.setattr(main_mod, 'GrubFile', FakeGrubFile)
    monkeypatch.setattr(main_mod, 'WizValidator', FakeValidator)
    monkeypatch.setattr(main_mod, 'WarnDB', FakeWarnDB)
    monkeypatch.setattr(main_mod, 'get_top_level_grub_entries', lambda _path: [])

    etc_grub = str(tmp_path / 'distro-grub')
    gw = object.__new__(main_mod.GrubWiz)
    gw.canned_config = SimpleNamespace(data={
        'Boot': {'GRUB_TIMEOUT': {'default': 5, 'enums': {}}},
    })
    gw.distro_vars = SimpleNamespace(
        etc_grub=etc_grub, update_initramfs=None, grub_cfg=None)
    gw.param_discovery = SimpleNamespace(
        ensure_discovered=lambda: set(),
        get_absent=lambda _names: set(),
    )
    gw.wiz_validator = None
    gw.refresh_backup_list = lambda: None

    gw.reinit_gw()

    assert seen['file_path'] == etc_grub
    assert seen['read_file'] is True
    assert gw.grub_file.param_data['GRUB_TIMEOUT'].value == GrubFile.ABSENT
