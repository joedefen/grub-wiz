"""Tests for ``WizValidator.probe_disk_layout()``.

The probe shells out to ``lsblk -J``; these tests feed it canned JSON so the
suite never depends on the host's real disk layout.  ``lsblk`` emits lowercase
JSON keys and may return a flat list of devices or nested ``children``, so both
shapes are covered.
"""

import json
from types import SimpleNamespace

import pytest

from grub_wiz import WizValidator as wiz_validator_module
from grub_wiz.WizValidator import WizValidator

ESP_GUID = 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b'


@pytest.fixture(name='run_lsblk')
def fixture_run_lsblk(monkeypatch):
    """Install a fake ``subprocess.run`` returning canned lsblk/efibootmgr data."""

    def install(lsblk, efi_stdout='', efi_returncode=1):
        calls = []

        def fake_run(cmd, **_kwargs):
            calls.append(cmd)
            if cmd[0] == 'lsblk':
                payload = lsblk if isinstance(lsblk, str) else json.dumps(lsblk)
                return SimpleNamespace(returncode=0, stdout=payload, stderr='')
            if cmd[0] == 'efibootmgr':
                return SimpleNamespace(
                    returncode=efi_returncode, stdout=efi_stdout, stderr='')
            raise AssertionError(f'unexpected command: {cmd}')

        monkeypatch.setattr(wiz_validator_module.subprocess, 'run', fake_run)
        return calls

    return install


def probe():
    """Run a fresh probe against the layout installed by ``run_lsblk``."""
    return WizValidator({}).probe_disk_layout()


def test_luks_detected_in_flat_layout(run_lsblk):
    """Lowercase keys in a childless (flat) layout are still scanned."""
    run_lsblk({'blockdevices': [
        {'fstype': None, 'parttype': None, 'name': 'sda'},
        {'fstype': 'crypto_LUKS', 'parttype': 'ca7d7ccb-63ed-4c53-861c-1742536059cc',
         'name': 'sda1'},
    ]})

    layout = probe()

    assert layout.is_luks_active is True


def test_luks_detected_in_nested_layout(run_lsblk):
    run_lsblk({'blockdevices': [
        {'name': 'nvme0n1', 'fstype': None, 'parttype': None, 'children': [
            {'name': 'nvme0n1p2', 'fstype': 'crypto_LUKS', 'parttype': None},
        ]},
    ]})

    assert probe().is_luks_active is True


def test_lvm_detected_from_fstype(run_lsblk):
    run_lsblk({'blockdevices': [
        {'name': 'sda', 'fstype': None, 'parttype': None, 'children': [
            {'name': 'sda2', 'fstype': 'LVM2_member', 'parttype': None},
        ]},
    ]})

    assert probe().is_lvm_active is True


def test_lvm_detected_from_partition_type_guid(run_lsblk):
    run_lsblk({'blockdevices': [
        {'name': 'sda1', 'fstype': None,
         'parttype': 'E6D6D379-F507-44C2-A23C-238F2A3DF928'},
    ]})

    assert probe().is_lvm_active is True


def test_lvm_detected_below_luks_mapping(run_lsblk):
    """A LUKS container is inspected through its nested children."""
    run_lsblk({'blockdevices': [
        {'name': 'sda', 'fstype': None, 'parttype': None, 'children': [
            {'name': 'sda3', 'fstype': 'crypto_LUKS', 'parttype': None, 'children': [
                {'name': 'cryptroot', 'fstype': 'LVM2_member', 'parttype': None},
            ]},
        ]},
    ]})

    layout = probe()

    assert layout.is_luks_active is True
    assert layout.is_lvm_active is True


def test_vfat_esp_alone_is_not_another_os(run_lsblk):
    """Every UEFI system has a vfat ESP; that alone must not imply multi-boot."""
    run_lsblk(
        {'blockdevices': [
            {'name': 'sda', 'fstype': None, 'parttype': None, 'children': [
                {'name': 'sda1', 'fstype': 'vfat', 'parttype': ESP_GUID},
            ]},
        ]},
        efi_stdout=(
            'BootCurrent: 0001\n'
            'Boot0001* ubuntu\tHD(1,GPT,1234,0x800,0x100000)/File(\\EFI\\UBUNTU\\SHIMX64.EFI)\n'
        ),
        efi_returncode=0,
    )

    assert probe().has_another_os is False


def test_internal_ntfs_is_another_os(run_lsblk):
    run_lsblk({'blockdevices': [
        {'name': 'sdb', 'fstype': None, 'parttype': None, 'rm': False, 'children': [
            {'name': 'sdb3', 'fstype': 'ntfs', 'parttype': None, 'rm': False},
        ]},
    ]})

    assert probe().has_another_os is True


def test_removable_ntfs_is_not_another_os(run_lsblk):
    """A USB stick must not make the OS-prober advice wrong."""
    run_lsblk({'blockdevices': [
        {'name': 'sdc1', 'fstype': 'ntfs', 'parttype': None, 'rm': True, 'type': 'part'},
    ]})

    assert probe().has_another_os is False


def test_loop_device_is_ignored(run_lsblk):
    run_lsblk({'blockdevices': [
        {'name': 'loop0', 'fstype': 'ntfs', 'parttype': None, 'rm': False, 'type': 'loop'},
    ]})

    assert probe().has_another_os is False


def test_windows_recovery_partition_is_another_os(run_lsblk):
    run_lsblk({'blockdevices': [
        {'name': 'sda4', 'fstype': None, 'rm': False,
         'parttype': 'DE94BBA4-06D9-4D40-A16A-BFD50179D6AC'},
    ]})

    assert probe().has_another_os is True


def test_multiple_efi_entries_imply_multiboot(run_lsblk):
    run_lsblk(
        {'blockdevices': [
            {'name': 'sda1', 'fstype': 'vfat', 'parttype': ESP_GUID, 'rm': False},
        ]},
        efi_stdout=(
            'BootCurrent: 0001\n'
            'Boot0001* ubuntu\tHD(1,GPT,1234,0x800,0x100000)/File(\\EFI\\UBUNTU\\SHIMX64.EFI)\n'
            'Boot0002* Windows Boot Manager\tHD(1,GPT,1234,0x800,0x100000)'
            '/File(\\EFI\\MICROSOFT\\BOOTMGFW.EFI)\n'
        ),
        efi_returncode=0,
    )

    assert probe().has_another_os is True


def test_generic_fallback_entry_is_not_multiboot(run_lsblk):
    run_lsblk(
        {'blockdevices': [
            {'name': 'sda1', 'fstype': 'vfat', 'parttype': ESP_GUID, 'rm': False},
        ]},
        efi_stdout=(
            'BootCurrent: 0001\n'
            'Boot0001* ubuntu\tHD(1,GPT,1234,0x800,0x100000)/File(\\EFI\\UBUNTU\\SHIMX64.EFI)\n'
            'Boot0002* UEFI OS\tHD(1,GPT,1234,0x800,0x100000)/File(\\EFI\\BOOT\\BOOTX64.EFI)\n'
        ),
        efi_returncode=0,
    )

    assert probe().has_another_os is False


def test_duplicate_loaders_for_one_os_are_not_multiboot(run_lsblk):
    """One OS often registers both shim and grub in the same ``\\EFI`` directory."""
    run_lsblk(
        {'blockdevices': [
            {'name': 'nvme0n1p1', 'fstype': 'vfat', 'parttype': ESP_GUID, 'rm': False},
        ]},
        efi_stdout=(
            'BootCurrent: 0002\n'
            'Boot0002* debian\tHD(6,GPT,7de53f82,0xee175000,0x200000)'
            '/File(\\EFI\\DEBIAN\\SHIMX64.EFI)\n'
            'Boot0003* debian\tHD(6,GPT,7de53f82,0xee175000,0x200000)'
            '/File(\\EFI\\DEBIAN\\GRUBX64.EFI)\n'
        ),
        efi_returncode=0,
    )

    assert probe().has_another_os is False


def test_root_on_luks_is_flagged(run_lsblk):
    """The LUKS container is an ancestor of the filesystem mounted at /."""
    run_lsblk({'blockdevices': [
        {'name': 'nvme0n1', 'fstype': None, 'parttype': None, 'children': [
            {'name': 'nvme0n1p3', 'fstype': 'crypto_LUKS', 'parttype': None,
             'children': [
                 {'name': 'cryptroot', 'fstype': 'btrfs', 'parttype': None,
                  'mountpoints': ['/']},
             ]},
            {'name': 'nvme0n1p5', 'fstype': 'crypto_LUKS', 'parttype': None,
             'mountpoints': [None]},
        ]},
    ]})

    layout = probe()

    assert layout.is_luks_active is True
    assert layout.root_is_luks is True
    assert layout.root_is_lvm is False


def test_luks_data_disk_is_not_root(run_lsblk):
    """An encrypted data disk elsewhere must not imply rd.luks.uuid is needed."""
    run_lsblk({'blockdevices': [
        {'name': 'sda', 'fstype': None, 'parttype': None, 'children': [
            {'name': 'sda1', 'fstype': 'crypto_LUKS', 'parttype': None,
             'children': [
                 {'name': 'sda1-luks', 'fstype': 'ext4', 'parttype': None,
                  'mountpoints': ['/my-win']},
             ]},
        ]},
        {'name': 'nvme0n1', 'fstype': None, 'parttype': None, 'children': [
            {'name': 'nvme0n1p2', 'fstype': 'btrfs', 'parttype': None,
             'mountpoints': ['/', '/home']},
        ]},
    ]})

    layout = probe()

    assert layout.is_luks_active is True
    assert layout.root_is_luks is False


def test_root_on_lvm_is_flagged(run_lsblk):
    run_lsblk({'blockdevices': [
        {'name': 'sda', 'fstype': None, 'parttype': None, 'children': [
            {'name': 'sda2', 'fstype': 'LVM2_member', 'parttype': None,
             'children': [
                 {'name': 'vg-root', 'fstype': 'ext4', 'parttype': None,
                  'mountpoints': ['/']},
             ]},
        ]},
    ]})

    layout = probe()

    assert layout.is_lvm_active is True
    assert layout.root_is_lvm is True
    assert layout.root_is_luks is False


def test_missing_lsblk_yields_all_false(monkeypatch):
    def raise_missing(*_args, **_kwargs):
        raise FileNotFoundError('lsblk')

    monkeypatch.setattr(wiz_validator_module.subprocess, 'run', raise_missing)

    layout = probe()

    assert (layout.has_another_os, layout.is_luks_active, layout.is_lvm_active) == (
        False, False, False)


def test_invalid_json_yields_all_false(run_lsblk):
    run_lsblk('not json')

    layout = probe()

    assert (layout.has_another_os, layout.is_luks_active, layout.is_lvm_active) == (
        False, False, False)


def test_result_is_cached(run_lsblk):
    calls = run_lsblk({'blockdevices': []})

    validator = WizValidator({})
    first = validator.probe_disk_layout()
    second = validator.probe_disk_layout()

    assert first is second
    assert sum(1 for cmd in calls if cmd[0] == 'lsblk') == 1
