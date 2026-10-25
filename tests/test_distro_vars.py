"""Startup resolution and gating in ``DistroVars``.

``DistroVars`` decides which GRUB defaults file, update command, and initramfs
tool the rest of the application will use.  It also exits the program when
``/etc/default/grub`` or the update command is missing, and prompts before
continuing in "crippled" mode when only ``grub.cfg`` is unavailable.

Earlier tests only imported the module to check the path constant; these tests
drive the resolution order and every startup outcome without touching the real
system.
"""

import builtins
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import grub_wiz.DistroVars as dv_mod
from grub_wiz.DistroVars import DistroVars


ETC = '/etc/default/grub'
GRUB_CFG = '/boot/grub/grub.cfg'
UPDATE_GRUB = '/usr/sbin/update-grub'


def distro_data(grub_cfg=(GRUB_CFG,), etc_grub=(ETC,),
                update_grub=('update-grub',), update_initramfs=(),
                triggers=None):
    """Build a YAML-shaped ``_distro_vars_`` section for a test."""
    return {
        '_distro_vars_': {
            'grub_cfg': list(grub_cfg),
            'etc_grub': list(etc_grub),
            'update_grub': list(update_grub),
            'update_initramfs': list(update_initramfs),
        },
        '_update_initramfs_triggers_': triggers or {},
    }


@pytest.fixture(name='system')
def fixture_system(monkeypatch):
    """Patch path/binary lookup with an explicit fake system."""
    state = SimpleNamespace(paths=set(), binaries={})

    monkeypatch.setattr(
        dv_mod.os.path, 'exists', lambda path: path in state.paths)
    monkeypatch.setattr(
        dv_mod.shutil, 'which', lambda name: state.binaries.get(name))
    return state


def configure_complete(system):
    system.paths.update({ETC, GRUB_CFG})
    system.binaries['update-grub'] = UPDATE_GRUB


def test_first_existing_path_and_binary_win_in_candidate_order(system):
    """Resolution must preserve the priority encoded in the YAML lists."""
    system.paths.update({ETC, '/first/grub.cfg', '/second/grub.cfg'})
    system.binaries.update({'one': '/bin/one', 'two': '/bin/two'})

    data = distro_data(
        grub_cfg=('/missing/grub.cfg', '/first/grub.cfg', '/second/grub.cfg'),
        update_grub=('missing-cmd', 'one', 'two'),
    )
    dv = DistroVars(data)

    assert dv.grub_cfg == '/first/grub.cfg'
    assert dv.update_grub == '/bin/one'
    assert dv.update_initramfs is None


def test_missing_etc_grub_is_fatal(system):
    """Without the defaults file there is nothing to edit."""
    system.binaries['update-grub'] = UPDATE_GRUB

    with pytest.raises(SystemExit) as excinfo:
        DistroVars(distro_data())

    assert excinfo.value.code == 1


def test_missing_update_command_is_fatal(system):
    """A file-only tool cannot apply changes, so this is also fatal."""
    system.paths.add(ETC)

    with pytest.raises(SystemExit) as excinfo:
        DistroVars(distro_data())

    assert excinfo.value.code == 1


def test_missing_grub_cfg_confirmed_enters_crippled_mode(system, monkeypatch):
    """The operator may continue without menu-entry enumeration."""
    system.paths.add(ETC)
    system.binaries['update-grub'] = UPDATE_GRUB
    monkeypatch.setattr(builtins, 'input', lambda _prompt: 'y')

    dv = DistroVars(distro_data(grub_cfg=()))

    assert dv.grub_cfg is None
    assert dv.is_crippled is True


def test_missing_grub_cfg_refused_aborts_cleanly(system, monkeypatch):
    """Answering anything but ``y`` aborts with exit code 0."""
    system.paths.add(ETC)
    system.binaries['update-grub'] = UPDATE_GRUB
    monkeypatch.setattr(builtins, 'input', lambda _prompt: 'n')

    with pytest.raises(SystemExit) as excinfo:
        DistroVars(distro_data(grub_cfg=()))

    assert excinfo.value.code == 0


def test_missing_grub_cfg_with_closed_stdin_aborts(system, monkeypatch):
    """EOF is the safe default: do not continue in a degraded mode."""
    system.paths.add(ETC)
    system.binaries['update-grub'] = UPDATE_GRUB

    def raise_eof(_prompt):
        raise EOFError

    monkeypatch.setattr(builtins, 'input', raise_eof)

    with pytest.raises(SystemExit) as excinfo:
        DistroVars(distro_data(grub_cfg=()))

    assert excinfo.value.code == 0


def test_complete_system_is_not_crippled(system):
    configure_complete(system)

    dv = DistroVars(distro_data())

    assert dv.is_crippled is False
    assert (dv.grub_cfg, dv.etc_grub, dv.update_grub) == (
        GRUB_CFG, ETC, UPDATE_GRUB)


def test_custom_yaml_loads_initramfs_triggers(system):
    """The trigger table comes from the active config, not a global."""
    configure_complete(system)
    triggers = {'gpu_drivers': ['nouveau', 'nvidia']}
    data = distro_data(triggers=triggers)

    dv = DistroVars(data)

    assert dv.initramfs_triggers == triggers


def test_empty_yaml_falls_back_to_packaged_defaults(system):
    """A false-y config must not make every component disappear."""
    configure_complete(system)

    dv = DistroVars(None)

    assert dv.etc_grub == ETC
    assert dv.grub_cfg == GRUB_CFG


def test_find_first_path_and_binary_return_none_when_empty(system):
    """The helpers are total: an empty candidate list yields ``None``."""
    dv = object.__new__(DistroVars)

    assert dv._find_first_path([]) is None
    assert dv._find_binary([]) is None
