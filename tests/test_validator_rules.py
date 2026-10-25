#!/usr/bin/env python3
"""
Comprehensive tests for WizValidator validation rules.

Tests cover all validation rules with multiple scenarios for each:
- Cases that should trigger warnings
- Cases that should NOT trigger warnings
- Edge cases (empty values, absent values, etc.)

This ensures the subtle logic around "presence vs. value" and
"false vs. not-true" is correctly implemented.
"""

import sys
import os
from pathlib import Path
from types import SimpleNamespace

# Add parent directory to path to import grub_wiz
sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz.WizValidator import WizValidator
from grub_wiz.GrubFile import GrubFile


class TestHelper:
    """Helper class for running validation tests."""

    # Prevent pytest from trying to collect this helper as a test class.
    __test__ = False

    def __init__(self):
        # Minimal param_cfg for testing
        self.param_cfg = {
            'GRUB_DEFAULT': {},
            'GRUB_SAVEDEFAULT': {},
            'GRUB_TIMEOUT': {},
            'GRUB_TIMEOUT_STYLE': {},
            'GRUB_CMDLINE_LINUX': {},
            'GRUB_CMDLINE_LINUX_DEFAULT': {},
            'GRUB_CMDLINE_LINUX_RECOVERY': {},
            'GRUB_DISABLE_RECOVERY': {},
            'GRUB_ENABLE_CRYPTODISK': {},
            'GRUB_DISABLE_LINUX_UUID': {},
            'GRUB_DISABLE_LINUX_PARTUUID': {},
            'GRUB_TERMINAL_INPUT': {},
            'GRUB_TERMINAL_OUTPUT': {},
            'GRUB_TERMINAL': {},
            'GRUB_SERIAL_COMMAND': {},
            'GRUB_GFXMODE': {},
            'GRUB_BACKGROUND': {},
            'GRUB_THEME': {},
            'GRUB_DISTRIBUTOR': {},
            'GRUB_DISABLE_OS_PROBER': {},
            'GRUB_RECORDFAIL_TIMEOUT': {},
            'GRUB_VIDEO_BACKEND': {'enums': {'vbe': {}, 'vesa': {}, 'efi_gop': {}, 'efi_uga': {}}},
        }

    def run_test(self, test_name, config, should_warn, expected_param=None, layout=None,
                 initramfs_tool='dracut'):
        """
        Run a single validation test.

        Args:
            test_name: Description of the test
            config: Dictionary of GRUB parameter values
            should_warn: True if warnings are expected, False otherwise
            expected_param: If should_warn is True, the parameter expected to have warnings
            layout: Optional mock layout object (for LUKS/LVM/OS tests)
            initramfs_tool: initramfs generator basename (defaults to dracut)
        """
        validator = WizValidator(self.param_cfg, initramfs_tool=initramfs_tool)

        # Never probe the host: default to a plain single-OS layout and let
        # each test case override it.  This keeps the suite hermetic and
        # deterministic across developer machines and CI runners.
        if layout is None:
            layout = SimpleNamespace(
                has_another_os=False,
                is_luks_active=False,
                is_lvm_active=False,
            )
        validator._disk_layout_cache = layout

        # Add default absent values for all params not in config
        vals = {param: GrubFile.ABSENT for param in self.param_cfg.keys()}
        # A missing GRUB_DISTRIBUTOR is a warning in its own right (M1), so seed
        # a valid value here; the dedicated distributor tests override it.
        if 'GRUB_DISTRIBUTOR' in vals:
            vals['GRUB_DISTRIBUTOR'] = 'Debian'
        vals.update(config)

        warns, _ = validator.make_warns(vals)

        has_warnings = len(warns) > 0

        failure = None
        if should_warn:
            if not has_warnings:
                failure = 'Expected warnings but got none'
            elif expected_param and expected_param not in warns:
                failure = (f'Expected warning on {expected_param} but got '
                           f'warnings on: {list(warns.keys())}')
        elif has_warnings:
            failure = f'Expected no warnings but got: {warns}'

        if failure:
            print(f"   ✗ FAIL: {test_name}")
            print(f"      {failure}")
            print(f"      Config: {config}")
            raise AssertionError(f"{test_name}: {failure}")

        print(f"   ✓ PASS: {test_name}")
        return True


def test_default_saved_vs_savedefault():
    """Test DEFAULT=saved vs SAVEDEFAULT validation."""
    print("\n" + "=" * 70)
    print("TEST: DEFAULT=saved vs SAVEDEFAULT")
    print("=" * 70)

    helper = TestHelper()
    passed = 0
    total = 0

    test_cases = [
        # Should warn: SAVEDEFAULT explicitly false
        ("DEFAULT=saved with SAVEDEFAULT=false (should warn)",
         {'GRUB_DEFAULT': 'saved', 'GRUB_SAVEDEFAULT': 'false'}, True, 'GRUB_DEFAULT'),
        ("DEFAULT=saved with SAVEDEFAULT='false' (should warn)",
         {'GRUB_DEFAULT': '"saved"', 'GRUB_SAVEDEFAULT': '"false"'}, True, 'GRUB_DEFAULT'),

        # Should NOT warn: SAVEDEFAULT is empty/absent/true
        ("DEFAULT=saved with SAVEDEFAULT absent (should NOT warn)",
         {'GRUB_DEFAULT': 'saved'}, False),
        ("DEFAULT=saved with SAVEDEFAULT empty (should NOT warn)",
         {'GRUB_DEFAULT': 'saved', 'GRUB_SAVEDEFAULT': ''}, False),
        ("DEFAULT=saved with SAVEDEFAULT=true (should NOT warn)",
         {'GRUB_DEFAULT': 'saved', 'GRUB_SAVEDEFAULT': 'true'}, False),
        ("DEFAULT='saved' with SAVEDEFAULT='true' (should NOT warn)",
         {'GRUB_DEFAULT': '"saved"', 'GRUB_SAVEDEFAULT': '"true"'}, False),

        # Should NOT warn: DEFAULT is not saved
        ("DEFAULT=0 with SAVEDEFAULT=false (should NOT warn)",
         {'GRUB_DEFAULT': '0', 'GRUB_SAVEDEFAULT': 'false'}, False),
        ("DEFAULT absent (should NOT warn)",
         {}, False),
    ]

    for test_name, config, should_warn, *args in test_cases:
        total += 1
        expected_param = args[0] if args else None
        if helper.run_test(test_name, config, should_warn, expected_param):
            passed += 1

    print(f"\nPassed: {passed}/{total}")


def test_timeout_zero_hidden():
    """Test TIMEOUT=0 with TIMEOUT_STYLE=hidden validation."""
    print("\n" + "=" * 70)
    print("TEST: TIMEOUT=0 with TIMEOUT_STYLE=hidden")
    print("=" * 70)

    helper = TestHelper()
    passed = 0
    total = 0

    test_cases = [
        # Should warn: TIMEOUT=0 and STYLE=hidden
        ("TIMEOUT=0 with STYLE=hidden (should warn)",
         {'GRUB_TIMEOUT': '0', 'GRUB_TIMEOUT_STYLE': 'hidden'}, True, 'GRUB_TIMEOUT'),
        ("TIMEOUT='0' with STYLE='hidden' (should warn)",
         {'GRUB_TIMEOUT': '"0"', 'GRUB_TIMEOUT_STYLE': '"hidden"'}, True, 'GRUB_TIMEOUT'),
        ("TIMEOUT=0.0 with STYLE=hidden (should warn)",
         {'GRUB_TIMEOUT': '0.0', 'GRUB_TIMEOUT_STYLE': 'hidden'}, True, 'GRUB_TIMEOUT'),

        # Should NOT warn: Valid combinations
        ("TIMEOUT=0 with STYLE=menu (should NOT warn)",
         {'GRUB_TIMEOUT': '0', 'GRUB_TIMEOUT_STYLE': 'menu'}, False),
        ("TIMEOUT=5 with STYLE=hidden (should NOT warn)",
         {'GRUB_TIMEOUT': '5', 'GRUB_TIMEOUT_STYLE': 'hidden'}, False),
        ("TIMEOUT=0 with STYLE absent (should NOT warn)",
         {'GRUB_TIMEOUT': '0'}, False),
        ("TIMEOUT=0 with STYLE empty (should NOT warn)",
         {'GRUB_TIMEOUT': '0', 'GRUB_TIMEOUT_STYLE': ''}, False),
    ]

    for test_name, config, should_warn, *args in test_cases:
        total += 1
        expected_param = args[0] if args else None
        if helper.run_test(test_name, config, should_warn, expected_param):
            passed += 1

    print(f"\nPassed: {passed}/{total}")


def test_splash_quiet_rhgb():
    """Test splash/quiet/rhgb in CMDLINE_LINUX validation."""
    print("\n" + "=" * 70)
    print("TEST: splash/quiet/rhgb in CMDLINE_LINUX")
    print("=" * 70)

    helper = TestHelper()
    passed = 0
    total = 0

    test_cases = [
        # Should warn: splash/quiet/rhgb in CMDLINE_LINUX
        ("quiet in CMDLINE_LINUX (should warn)",
         {'GRUB_CMDLINE_LINUX': '"quiet"'}, True, 'GRUB_CMDLINE_LINUX'),
        ("splash in CMDLINE_LINUX (should warn)",
         {'GRUB_CMDLINE_LINUX': '"splash"'}, True, 'GRUB_CMDLINE_LINUX'),
        ("rhgb in CMDLINE_LINUX (should warn)",
         {'GRUB_CMDLINE_LINUX': '"rhgb"'}, True, 'GRUB_CMDLINE_LINUX'),
        ("multiple: rhgb quiet in CMDLINE_LINUX (should warn)",
         {'GRUB_CMDLINE_LINUX': '"rhgb quiet"'}, True, 'GRUB_CMDLINE_LINUX'),
        ("quiet with other args in CMDLINE_LINUX (should warn)",
         {'GRUB_CMDLINE_LINUX': '"rd.luks.uuid=abc quiet"'}, True, 'GRUB_CMDLINE_LINUX'),

        # Should NOT warn: splash/quiet/rhgb in CMDLINE_LINUX_DEFAULT or absent
        ("quiet in CMDLINE_LINUX_DEFAULT (should NOT warn)",
         {'GRUB_CMDLINE_LINUX_DEFAULT': '"quiet splash"'}, False),
        ("CMDLINE_LINUX without splash/quiet/rhgb (should NOT warn)",
         {'GRUB_CMDLINE_LINUX': '"rd.luks.uuid=abc"'}, False),
        ("CMDLINE_LINUX empty (should NOT warn)",
         {'GRUB_CMDLINE_LINUX': '""'}, False),
        ("CMDLINE_LINUX absent (should NOT warn)",
         {}, False),
        # Make sure word boundaries work
        ("quieter (contains quiet but not word) (should NOT warn)",
         {'GRUB_CMDLINE_LINUX': '"quieter"'}, False),
    ]

    for test_name, config, should_warn, *args in test_cases:
        total += 1
        expected_param = args[0] if args else None
        if helper.run_test(test_name, config, should_warn, expected_param):
            passed += 1

    print(f"\nPassed: {passed}/{total}")


def test_recovery_cmdline_vs_disable():
    """Test CMDLINE_LINUX_RECOVERY vs DISABLE_RECOVERY validation."""
    print("\n" + "=" * 70)
    print("TEST: CMDLINE_LINUX_RECOVERY vs DISABLE_RECOVERY")
    print("=" * 70)

    helper = TestHelper()
    passed = 0
    total = 0

    test_cases = [
        # Should warn: Recovery cmdline has value but recovery disabled
        ("RECOVERY='nomodeset' with DISABLE=true (should warn)",
         {'GRUB_CMDLINE_LINUX_RECOVERY': '"nomodeset"', 'GRUB_DISABLE_RECOVERY': 'true'}, True, 'GRUB_CMDLINE_LINUX_RECOVERY'),
        ("RECOVERY='quiet' with DISABLE='true' (should warn)",
         {'GRUB_CMDLINE_LINUX_RECOVERY': '"quiet"', 'GRUB_DISABLE_RECOVERY': '"true"'}, True, 'GRUB_CMDLINE_LINUX_RECOVERY'),

        # Should NOT warn: Recovery empty/absent even if disabled
        ("RECOVERY absent with DISABLE=true (should NOT warn)",
         {'GRUB_DISABLE_RECOVERY': 'true'}, False),
        ("RECOVERY empty with DISABLE=true (should NOT warn)",
         {'GRUB_CMDLINE_LINUX_RECOVERY': '', 'GRUB_DISABLE_RECOVERY': 'true'}, False),
        ("RECOVERY='""' (empty quoted) with DISABLE=true (should NOT warn)",
         {'GRUB_CMDLINE_LINUX_RECOVERY': '""', 'GRUB_DISABLE_RECOVERY': 'true'}, False),

        # Should NOT warn: Recovery has value but not disabled
        ("RECOVERY='nomodeset' with DISABLE=false (should NOT warn)",
         {'GRUB_CMDLINE_LINUX_RECOVERY': '"nomodeset"', 'GRUB_DISABLE_RECOVERY': 'false'}, False),
        ("RECOVERY='nomodeset' with DISABLE absent (should NOT warn)",
         {'GRUB_CMDLINE_LINUX_RECOVERY': '"nomodeset"'}, False),
        ("RECOVERY='nomodeset' with DISABLE empty (should NOT warn)",
         {'GRUB_CMDLINE_LINUX_RECOVERY': '"nomodeset"', 'GRUB_DISABLE_RECOVERY': ''}, False),
    ]

    for test_name, config, should_warn, *args in test_cases:
        total += 1
        expected_param = args[0] if args else None
        if helper.run_test(test_name, config, should_warn, expected_param):
            passed += 1

    print(f"\nPassed: {passed}/{total}")


def test_luks_detection():
    """Test LUKS detection and rd.luks.uuid validation."""
    print("\n" + "=" * 70)
    print("TEST: LUKS detection and rd.luks.uuid")
    print("=" * 70)

    helper = TestHelper()
    passed = 0
    total = 0

    # Mock layout with LUKS on the root device
    layout_with_luks = SimpleNamespace(
        has_another_os=False,
        is_luks_active=True,
        is_lvm_active=False,
        root_is_luks=True,
        root_is_lvm=False,
    )

    # Mock layout without LUKS
    layout_no_luks = SimpleNamespace(
        has_another_os=False,
        is_luks_active=False,
        is_lvm_active=False
    )

    test_cases = [
        # Should warn: LUKS active but no rd.luks.uuid
        ("LUKS active, CMDLINE_LINUX without rd.luks.uuid (should warn)",
         {'GRUB_CMDLINE_LINUX': '"rd.lvm.vg=test"'}, True, 'GRUB_CMDLINE_LINUX', layout_with_luks),
        ("LUKS active, CMDLINE_LINUX empty (should warn)",
         {'GRUB_CMDLINE_LINUX': '""'}, True, 'GRUB_CMDLINE_LINUX', layout_with_luks),

        # Should NOT warn: LUKS active and rd.luks.uuid present
        ("LUKS active, CMDLINE_LINUX with rd.luks.uuid (should NOT warn)",
         {'GRUB_CMDLINE_LINUX': '"rd.luks.uuid=abc-123"'}, False, None, layout_with_luks),

        # Should NOT warn: No LUKS
        ("No LUKS, CMDLINE_LINUX without rd.luks.uuid (should NOT warn)",
         {'GRUB_CMDLINE_LINUX': '"rd.lvm.vg=test"'}, False, None, layout_no_luks),
    ]

    for test_name, config, should_warn, expected_param, layout in test_cases:
        total += 1
        if helper.run_test(test_name, config, should_warn, expected_param, layout):
            passed += 1

    print(f"\nPassed: {passed}/{total}")


def test_lvm_detection():
    """Test LVM detection and rd.lvm.vg validation."""
    print("\n" + "=" * 70)
    print("TEST: LVM detection and rd.lvm.vg")
    print("=" * 70)

    helper = TestHelper()
    passed = 0
    total = 0

    # Mock layout with LVM on the root device
    layout_with_lvm = SimpleNamespace(
        has_another_os=False,
        is_luks_active=False,
        is_lvm_active=True,
        root_is_luks=False,
        root_is_lvm=True,
    )

    # Mock layout without LVM
    layout_no_lvm = SimpleNamespace(
        has_another_os=False,
        is_luks_active=False,
        is_lvm_active=False
    )

    test_cases = [
        # Should warn: LVM active but no rd.lvm.vg
        ("LVM active, CMDLINE_LINUX without rd.lvm.vg (should warn)",
         {'GRUB_CMDLINE_LINUX': '"rd.luks.uuid=test"'}, True, 'GRUB_CMDLINE_LINUX', layout_with_lvm),

        # Should NOT warn: LVM active and rd.lvm.vg present
        ("LVM active, CMDLINE_LINUX with rd.lvm.vg (should NOT warn)",
         {'GRUB_CMDLINE_LINUX': '"rd.lvm.vg=vg0"'}, False, None, layout_with_lvm),

        # Should NOT warn: No LVM
        ("No LVM, CMDLINE_LINUX without rd.lvm.vg (should NOT warn)",
         {'GRUB_CMDLINE_LINUX': '"rd.luks.uuid=test"'}, False, None, layout_no_lvm),
    ]

    for test_name, config, should_warn, expected_param, layout in test_cases:
        total += 1
        if helper.run_test(test_name, config, should_warn, expected_param, layout):
            passed += 1

    print(f"\nPassed: {passed}/{total}")


def test_rd_arg_rules_are_dracut_and_root_scoped():
    """rd.luks.uuid/rd.lvm.vg are dracut-specific and root-scoped."""
    print("\n" + "=" * 70)
    print("TEST: rd.* rules are dracut + root-chain scoped")
    print("=" * 70)

    helper = TestHelper()

    def layout(root_luks=False, root_lvm=False, any_luks=False, any_lvm=False):
        return SimpleNamespace(
            has_another_os=False,
            is_luks_active=any_luks,
            is_lvm_active=any_lvm,
            root_is_luks=root_luks,
            root_is_lvm=root_lvm,
        )

    test_cases = [
        # dracut + root on LUKS + no rd.luks.uuid -> warn
        ('dracut root LUKS, no rd.luks.uuid (should warn)',
         {'GRUB_CMDLINE_LINUX': '""'}, True, 'GRUB_CMDLINE_LINUX',
         layout(root_luks=True, any_luks=True), 'dracut'),
        # initramfs-tools unlocks through /etc/crypttab, never rd.luks.uuid
        ('initramfs-tools root LUKS, no rd.luks.uuid (should NOT warn)',
         {'GRUB_CMDLINE_LINUX': '""'}, False, None,
         layout(root_luks=True, any_luks=True), 'update-initramfs'),
        # A LUKS data disk needs nothing at boot
        ('dracut data-only LUKS, no rd.luks.uuid (should NOT warn)',
         {'GRUB_CMDLINE_LINUX': '""'}, False, None,
         layout(any_luks=True), 'dracut'),
        # dracut consumes the merged command line, so DEFAULT counts
        ('dracut root LUKS, rd.luks.uuid in DEFAULT (should NOT warn)',
         {'GRUB_CMDLINE_LINUX': '""',
          'GRUB_CMDLINE_LINUX_DEFAULT': '"rd.luks.uuid=abc quiet"'},
         False, None, layout(root_luks=True, any_luks=True), 'dracut'),
        # LVM follows the same scoping
        ('dracut root LVM, no rd.lvm.vg (should warn)',
         {'GRUB_CMDLINE_LINUX': '""'}, True, 'GRUB_CMDLINE_LINUX',
         layout(root_lvm=True, any_lvm=True), 'dracut'),
        ('initramfs-tools root LVM, no rd.lvm.vg (should NOT warn)',
         {'GRUB_CMDLINE_LINUX': '""'}, False, None,
         layout(root_lvm=True, any_lvm=True), 'update-initramfs'),
    ]

    for test_name, config, should_warn, expected_param, fake_layout, tool in test_cases:
        helper.run_test(test_name, config, should_warn, expected_param,
                        fake_layout, initramfs_tool=tool)

    print(f"\nPassed: {len(test_cases)}/{len(test_cases)}")


def test_cryptodisk_without_luks():
    """Test ENABLE_CRYPTODISK without LUKS validation."""
    print("\n" + "=" * 70)
    print("TEST: ENABLE_CRYPTODISK without LUKS")
    print("=" * 70)

    helper = TestHelper()
    passed = 0
    total = 0

    layout_with_luks = SimpleNamespace(
        has_another_os=False,
        is_luks_active=True,
        is_lvm_active=False,
        root_is_luks=True,
        root_is_lvm=False,
    )

    layout_no_luks = SimpleNamespace(
        has_another_os=False,
        is_luks_active=False,
        is_lvm_active=False
    )

    test_cases = [
        # Should warn: CRYPTODISK enabled but no LUKS
        ("CRYPTODISK=true without LUKS (should warn)",
         {'GRUB_ENABLE_CRYPTODISK': 'true'}, True, 'GRUB_ENABLE_CRYPTODISK', layout_no_luks),
        ("CRYPTODISK='true' without LUKS (should warn)",
         {'GRUB_ENABLE_CRYPTODISK': '"true"'}, True, 'GRUB_ENABLE_CRYPTODISK', layout_no_luks),

        # Should NOT warn: CRYPTODISK enabled with LUKS (need rd.luks.uuid to avoid other warning)
        ("CRYPTODISK=true with LUKS (should NOT warn)",
         {'GRUB_ENABLE_CRYPTODISK': 'true', 'GRUB_CMDLINE_LINUX': '"rd.luks.uuid=abc"'},
         False, None, layout_with_luks),

        # Should NOT warn: CRYPTODISK not enabled
        ("CRYPTODISK=false without LUKS (should NOT warn)",
         {'GRUB_ENABLE_CRYPTODISK': 'false'}, False, None, layout_no_luks),
        ("CRYPTODISK absent without LUKS (should NOT warn)",
         {}, False, None, layout_no_luks),
    ]

    for test_name, config, should_warn, expected_param, layout in test_cases:
        total += 1
        if helper.run_test(test_name, config, should_warn, expected_param, layout):
            passed += 1

    print(f"\nPassed: {passed}/{total}")


def test_uuid_disabled():
    """Test UUID/PARTUUID disabled validation."""
    print("\n" + "=" * 70)
    print("TEST: UUID/PARTUUID disabled")
    print("=" * 70)

    helper = TestHelper()
    passed = 0
    total = 0

    test_cases = [
        # Should warn: Both disabled (severity 2)
        ("Both UUID and PARTUUID disabled (should warn)",
         {'GRUB_DISABLE_LINUX_UUID': 'true', 'GRUB_DISABLE_LINUX_PARTUUID': 'true'}, True, 'GRUB_DISABLE_LINUX_UUID'),

        # Should warn: Only UUID disabled (severity 1)
        ("Only UUID disabled (should warn)",
         {'GRUB_DISABLE_LINUX_UUID': 'true'}, True, 'GRUB_DISABLE_LINUX_UUID'),

        # Should warn: Only PARTUUID disabled (severity 1)
        ("Only PARTUUID disabled (should warn)",
         {'GRUB_DISABLE_LINUX_PARTUUID': 'true'}, True, 'GRUB_DISABLE_LINUX_PARTUUID'),

        # Should NOT warn: Neither disabled
        ("Neither disabled (should NOT warn)",
         {}, False),
        ("UUID=false, PARTUUID=false (should NOT warn)",
         {'GRUB_DISABLE_LINUX_UUID': 'false', 'GRUB_DISABLE_LINUX_PARTUUID': 'false'}, False),
    ]

    for test_name, config, should_warn, *args in test_cases:
        total += 1
        expected_param = args[0] if args else None
        if helper.run_test(test_name, config, should_warn, expected_param):
            passed += 1

    print(f"\nPassed: {passed}/{total}")


def test_terminal_serial():
    """Test serial terminal configuration validation."""
    print("\n" + "=" * 70)
    print("TEST: Serial terminal configuration")
    print("=" * 70)

    helper = TestHelper()
    passed = 0
    total = 0

    test_cases = [
        # Should warn: Serial terminal without SERIAL_COMMAND
        ("INPUT=serial without SERIAL_COMMAND (should warn)",
         {'GRUB_TERMINAL_INPUT': 'serial'}, True, 'GRUB_SERIAL_COMMAND'),
        ("OUTPUT=serial without SERIAL_COMMAND (should warn)",
         {'GRUB_TERMINAL_OUTPUT': 'serial'}, True, 'GRUB_SERIAL_COMMAND'),
        ("TERMINAL=serial without SERIAL_COMMAND (should warn)",
         {'GRUB_TERMINAL': 'serial'}, True, 'GRUB_SERIAL_COMMAND'),

        # Should warn: INPUT/OUTPUT mismatch when serial
        ("INPUT=serial, OUTPUT=console (should warn)",
         {'GRUB_TERMINAL_INPUT': 'serial', 'GRUB_TERMINAL_OUTPUT': 'console',
          'GRUB_SERIAL_COMMAND': '"serial"'}, True, 'GRUB_TERMINAL_OUTPUT'),
        ("INPUT=console, OUTPUT=serial (should warn)",
         {'GRUB_TERMINAL_INPUT': 'console', 'GRUB_TERMINAL_OUTPUT': 'serial',
          'GRUB_SERIAL_COMMAND': '"serial"'}, True, 'GRUB_TERMINAL_INPUT'),

        # Should warn: SERIAL_COMMAND without serial terminal
        ("SERIAL_COMMAND without serial terminal (should warn)",
         {'GRUB_SERIAL_COMMAND': '"serial --unit=0"',
          'GRUB_TERMINAL_INPUT': 'console'}, True, 'GRUB_SERIAL_COMMAND'),

        # Should NOT warn: Proper serial configuration
        ("INPUT=OUTPUT=serial with SERIAL_COMMAND (should NOT warn)",
         {'GRUB_TERMINAL_INPUT': 'serial', 'GRUB_TERMINAL_OUTPUT': 'serial',
          'GRUB_SERIAL_COMMAND': '"serial"'}, False),

        # Note: GRUB_TERMINAL is checked separately and requires INPUT/OUTPUT to not be set
        # This is not a common configuration, so we skip testing it

        # Should NOT warn: No serial configuration
        ("No serial configuration (should NOT warn)",
         {}, False),
        ("INPUT=OUTPUT=console (should NOT warn)",
         {'GRUB_TERMINAL_INPUT': 'console', 'GRUB_TERMINAL_OUTPUT': 'console'}, False),
    ]

    for test_name, config, should_warn, *args in test_cases:
        total += 1
        expected_param = args[0] if args else None
        if helper.run_test(test_name, config, should_warn, expected_param):
            passed += 1

    print(f"\nPassed: {passed}/{total}")


def test_terminal_graphical():
    """Test graphical terminal configuration validation."""
    print("\n" + "=" * 70)
    print("TEST: Graphical terminal configuration")
    print("=" * 70)

    helper = TestHelper()
    passed = 0
    total = 0

    test_cases = [
        # Should warn: console terminal with graphical settings
        ("TERMINAL=console with GFXMODE (should warn)",
         {'GRUB_TERMINAL': 'console', 'GRUB_GFXMODE': '1024x768'}, True, 'GRUB_TERMINAL'),
        ("TERMINAL=console with BACKGROUND (should warn)",
         {'GRUB_TERMINAL': 'console', 'GRUB_BACKGROUND': '/boot/bg.png'}, True, 'GRUB_TERMINAL'),
        ("TERMINAL=console with THEME (should warn)",
         {'GRUB_TERMINAL': 'console', 'GRUB_THEME': '/boot/theme'}, True, 'GRUB_TERMINAL'),

        # Should warn: gfxterm without GFXMODE
        ("TERMINAL=gfxterm without GFXMODE (should warn)",
         {'GRUB_TERMINAL': 'gfxterm'}, True, 'GRUB_TERMINAL'),

        # Should NOT warn: Proper configurations
        ("TERMINAL=gfxterm with GFXMODE (should NOT warn)",
         {'GRUB_TERMINAL': 'gfxterm', 'GRUB_GFXMODE': '1024x768'}, False),
        ("TERMINAL=console without graphical settings (should NOT warn)",
         {'GRUB_TERMINAL': 'console'}, False),
        ("No TERMINAL set (should NOT warn)",
         {}, False),
    ]

    for test_name, config, should_warn, *args in test_cases:
        total += 1
        expected_param = args[0] if args else None
        if helper.run_test(test_name, config, should_warn, expected_param):
            passed += 1

    print(f"\nPassed: {passed}/{total}")


def test_savedefault_numeric():
    """Test SAVEDEFAULT=true with numeric DEFAULT validation."""
    print("\n" + "=" * 70)
    print("TEST: SAVEDEFAULT=true with numeric DEFAULT")
    print("=" * 70)

    helper = TestHelper()
    passed = 0
    total = 0

    test_cases = [
        # Should warn: SAVEDEFAULT=true with numeric DEFAULT
        ("SAVEDEFAULT=true, DEFAULT=0 (should warn)",
         {'GRUB_SAVEDEFAULT': 'true', 'GRUB_DEFAULT': '0'}, True, 'GRUB_SAVEDEFAULT'),
        ("SAVEDEFAULT=true, DEFAULT=2 (should warn)",
         {'GRUB_SAVEDEFAULT': 'true', 'GRUB_DEFAULT': '2'}, True, 'GRUB_SAVEDEFAULT'),
        ("SAVEDEFAULT='true', DEFAULT='5' (should warn)",
         {'GRUB_SAVEDEFAULT': '"true"', 'GRUB_DEFAULT': '"5"'}, True, 'GRUB_SAVEDEFAULT'),

        # Should NOT warn: SAVEDEFAULT=true with non-numeric DEFAULT
        ("SAVEDEFAULT=true, DEFAULT=saved (should NOT warn)",
         {'GRUB_SAVEDEFAULT': 'true', 'GRUB_DEFAULT': 'saved'}, False),
        ("SAVEDEFAULT=true, DEFAULT=entry-name (should NOT warn)",
         {'GRUB_SAVEDEFAULT': 'true', 'GRUB_DEFAULT': '"Ubuntu"'}, False),

        # Should NOT warn: SAVEDEFAULT not true
        ("SAVEDEFAULT=false, DEFAULT=0 (should NOT warn)",
         {'GRUB_SAVEDEFAULT': 'false', 'GRUB_DEFAULT': '0'}, False),
        ("SAVEDEFAULT absent, DEFAULT=0 (should NOT warn)",
         {'GRUB_DEFAULT': '0'}, False),
    ]

    for test_name, config, should_warn, *args in test_cases:
        total += 1
        expected_param = args[0] if args else None
        if helper.run_test(test_name, config, should_warn, expected_param):
            passed += 1

    print(f"\nPassed: {passed}/{total}")


def test_cmdline_quoting():
    """Test CMDLINE_LINUX quoting validation."""
    print("\n" + "=" * 70)
    print("TEST: CMDLINE_LINUX quoting")
    print("=" * 70)

    helper = TestHelper()
    passed = 0
    total = 0

    test_cases = [
        # Should warn: an unquoted space splits the value into separate words
        # when /etc/default/grub is sourced.
        ("CMDLINE_LINUX with unquoted spaces (should warn)",
         {'GRUB_CMDLINE_LINUX': 'rd.luks.uuid=abc rd.lvm.vg=test'},
         True, 'GRUB_CMDLINE_LINUX'),
        ("CMDLINE_LINUX_DEFAULT with unquoted spaces (should warn)",
         {'GRUB_CMDLINE_LINUX_DEFAULT': 'rd.luks.uuid=abc rd.lvm.vg=test'},
         True, 'GRUB_CMDLINE_LINUX_DEFAULT'),

        # Should NOT warn: Properly quoted or no spaces
        ("CMDLINE_LINUX with spaces, properly double quoted (should NOT warn)",
         {'GRUB_CMDLINE_LINUX': '"rd.luks.uuid=abc rd.lvm.vg=test"'}, False),
        ("CMDLINE_LINUX with spaces, properly single quoted (should NOT warn)",
         {'GRUB_CMDLINE_LINUX': "'rd.luks.uuid=abc rd.lvm.vg=test'"}, False),
        ("CMDLINE_LINUX_DEFAULT with spaces, properly quoted (should NOT warn)",
         {'GRUB_CMDLINE_LINUX_DEFAULT': '"quiet splash"'}, False),
        ("CMDLINE_LINUX with an unquoted word and a quoted space (should NOT warn)",
         {'GRUB_CMDLINE_LINUX': 'foo="a b"'}, False),
        ("CMDLINE_LINUX without spaces (should NOT warn)",
         {'GRUB_CMDLINE_LINUX': 'rd.luks.uuid=abc'}, False),
        ("CMDLINE_LINUX empty (should NOT warn)",
         {'GRUB_CMDLINE_LINUX': '""'}, False),
    ]

    for test_name, config, should_warn, *args in test_cases:
        total += 1
        expected_param = args[0] if args else None
        if helper.run_test(test_name, config, should_warn, expected_param):
            passed += 1

    print(f"\nPassed: {passed}/{total}")


def test_os_prober():
    """Test OS_PROBER configuration validation."""
    print("\n" + "=" * 70)
    print("TEST: OS_PROBER configuration")
    print("=" * 70)

    helper = TestHelper()
    passed = 0
    total = 0

    layout_multiboot = SimpleNamespace(
        has_another_os=True,
        is_luks_active=False,
        is_lvm_active=False
    )

    layout_single = SimpleNamespace(
        has_another_os=False,
        is_luks_active=False,
        is_lvm_active=False
    )

    test_cases = [
        # Should warn: OS_PROBER disabled on multi-boot system
        ("DISABLE_OS_PROBER=true with multi-boot (should warn)",
         {'GRUB_DISABLE_OS_PROBER': 'true'}, True, 'GRUB_DISABLE_OS_PROBER', layout_multiboot),

        # Should warn (low severity): OS_PROBER not disabled on single-boot
        ("DISABLE_OS_PROBER=false on single-boot (should warn)",
         {'GRUB_DISABLE_OS_PROBER': 'false'}, True, 'GRUB_DISABLE_OS_PROBER', layout_single),

        # Should NOT warn: Proper configurations
        ("DISABLE_OS_PROBER=false with multi-boot (should NOT warn)",
         {'GRUB_DISABLE_OS_PROBER': 'false'}, False, None, layout_multiboot),
        ("DISABLE_OS_PROBER=true on single-boot (should NOT warn)",
         {'GRUB_DISABLE_OS_PROBER': 'true'}, False, None, layout_single),
        ("DISABLE_OS_PROBER absent (should NOT warn)",
         {}, False, None, layout_single),
    ]

    for test_name, config, should_warn, expected_param, layout in test_cases:
        total += 1
        if helper.run_test(test_name, config, should_warn, expected_param, layout):
            passed += 1

    print(f"\nPassed: {passed}/{total}")


def test_timeout_limits():
    """Test TIMEOUT value limits validation."""
    print("\n" + "=" * 70)
    print("TEST: TIMEOUT value limits")
    print("=" * 70)

    helper = TestHelper()
    passed = 0
    total = 0

    test_cases = [
        # Should warn: Excessive timeout values
        ("TIMEOUT=61 (over limit, should warn)",
         {'GRUB_TIMEOUT': '61'}, True, 'GRUB_TIMEOUT'),
        ("TIMEOUT=500 (way over limit, should warn)",
         {'GRUB_TIMEOUT': '500'}, True, 'GRUB_TIMEOUT'),
        ("TIMEOUT=-1 (indefinite, should warn)",
         {'GRUB_TIMEOUT': '-1'}, True, 'GRUB_TIMEOUT'),
        ("RECORDFAIL_TIMEOUT=121 (over limit, should warn)",
         {'GRUB_RECORDFAIL_TIMEOUT': '121'}, True, 'GRUB_RECORDFAIL_TIMEOUT'),

        # Should NOT warn: Reasonable timeout values
        ("TIMEOUT=5 (should NOT warn)",
         {'GRUB_TIMEOUT': '5'}, False),
        ("TIMEOUT=60 (at limit, should NOT warn)",
         {'GRUB_TIMEOUT': '60'}, False),
        ("TIMEOUT=0 (should NOT warn)",
         {'GRUB_TIMEOUT': '0'}, False),
        ("RECORDFAIL_TIMEOUT=120 (at limit, should NOT warn)",
         {'GRUB_RECORDFAIL_TIMEOUT': '120'}, False),
    ]

    for test_name, config, should_warn, *args in test_cases:
        total += 1
        expected_param = args[0] if args else None
        if helper.run_test(test_name, config, should_warn, expected_param):
            passed += 1

    print(f"\nPassed: {passed}/{total}")


def test_distributor_missing_or_empty():
    """M1: a missing/empty GRUB_DISTRIBUTOR must actually warn.

    The old guard ``p1 and exist(v1)`` made every intended bad input
    (ABSENT, COMMENT, '') skip the rule, so it never fired.
    """
    print("\n" + "=" * 70)
    print("TEST: GRUB_DISTRIBUTOR missing or empty")
    print("=" * 70)

    helper = TestHelper()
    passed = 0
    total = 0

    test_cases = [
        # Should warn: no usable distro name
        ("DISTRIBUTOR absent (should warn)",
         {'GRUB_DISTRIBUTOR': GrubFile.ABSENT}, True, 'GRUB_DISTRIBUTOR'),
        ("DISTRIBUTOR commented out (should warn)",
         {'GRUB_DISTRIBUTOR': GrubFile.COMMENT}, True, 'GRUB_DISTRIBUTOR'),
        ("DISTRIBUTOR empty (should warn)",
         {'GRUB_DISTRIBUTOR': ''}, True, 'GRUB_DISTRIBUTOR'),
        ("DISTRIBUTOR empty quotes (should warn)",
         {'GRUB_DISTRIBUTOR': '""'}, True, 'GRUB_DISTRIBUTOR'),
        ("DISTRIBUTOR whitespace only (should warn)",
         {'GRUB_DISTRIBUTOR': '   '}, True, 'GRUB_DISTRIBUTOR'),

        # Should NOT warn: plain names and command substitutions
        ("DISTRIBUTOR plain name (should NOT warn)",
         {'GRUB_DISTRIBUTOR': 'Debian'}, False),
        ("DISTRIBUTOR quoted name (should NOT warn)",
         {'GRUB_DISTRIBUTOR': '"Ubuntu"'}, False),
        ("DISTRIBUTOR $(command) (should NOT warn)",
         {'GRUB_DISTRIBUTOR': '$(lsb_release -i -s 2> /dev/null || echo Debian)'}, False),
        ("DISTRIBUTOR `command` (should NOT warn)",
         {'GRUB_DISTRIBUTOR': '`lsb_release -i -s`'}, False),
    ]

    for test_name, config, should_warn, *args in test_cases:
        total += 1
        expected_param = args[0] if args else None
        if helper.run_test(test_name, config, should_warn, expected_param):
            passed += 1

    print(f"\nPassed: {passed}/{total}")


def test_enum_bad_does_not_leak_between_params():
    """M2: ``bad`` from a previous enum parameter must not warn the next one.

    ``bad`` is assigned only inside the presence guard, so without an explicit
    reset an absent parameter following an invalid enum value inherited
    ``True`` and produced a spurious "value not in list" warning.
    """
    print("\n" + "=" * 70)
    print("TEST: enum warning does not leak to the next parameter")
    print("=" * 70)

    param_cfg = {
        'GRUB_FIRST_ENUM': {'enums': {'one': 'first'}},
        'GRUB_SECOND_ENUM': {'enums': {'two': 'second'}},
    }
    validator = WizValidator(param_cfg)
    validator._disk_layout_cache = SimpleNamespace(
        has_another_os=False,
        is_luks_active=False,
        is_lvm_active=False,
    )

    scenarios = [
        ('invalid then absent',
         {'GRUB_FIRST_ENUM': 'bogus', 'GRUB_SECOND_ENUM': GrubFile.ABSENT},
         {'GRUB_FIRST_ENUM'}),
        ('absent then invalid',
         {'GRUB_FIRST_ENUM': GrubFile.ABSENT, 'GRUB_SECOND_ENUM': 'bogus'},
         {'GRUB_SECOND_ENUM'}),
        ('invalid then valid',
         {'GRUB_FIRST_ENUM': 'bogus', 'GRUB_SECOND_ENUM': 'two'},
         {'GRUB_FIRST_ENUM'}),
        ('valid then absent',
         {'GRUB_FIRST_ENUM': 'one', 'GRUB_SECOND_ENUM': GrubFile.ABSENT},
         set()),
    ]

    passed = 0
    for description, vals, expected_params in scenarios:
        warns, _ = validator.make_warns(vals)
        enum_warns = {
            name for name, pairs in warns.items()
            if any('allowed values' in message for _, message in pairs)
        }
        assert enum_warns == expected_params, (
            f"{description}: expected enum warnings on {expected_params}, "
            f"got {enum_warns} ({warns})")
        print(f"   ✓ PASS: {description}")
        passed += 1

    print(f"\nPassed: {passed}/{len(scenarios)}")


def test_gfxmode_values():
    """Test GFXMODE value validation."""
    print("\n" + "=" * 70)
    print("TEST: GFXMODE value validation")
    print("=" * 70)

    helper = TestHelper()
    passed = 0
    total = 0

    test_cases = [
        # Should warn: Uncommon GFXMODE values
        ("GFXMODE=1920x1080 (uncommon, should warn)",
         {'GRUB_GFXMODE': '1920x1080'}, True, 'GRUB_GFXMODE'),
        ("GFXMODE=2560x1440 (uncommon, should warn)",
         {'GRUB_GFXMODE': '2560x1440'}, True, 'GRUB_GFXMODE'),

        # Should NOT warn: Safe GFXMODE values
        ("GFXMODE=640x480 (safe, should NOT warn)",
         {'GRUB_GFXMODE': '640x480'}, False),
        ("GFXMODE=800x600 (safe, should NOT warn)",
         {'GRUB_GFXMODE': '800x600'}, False),
        ("GFXMODE=1024x768 (safe, should NOT warn)",
         {'GRUB_GFXMODE': '1024x768'}, False),
        ("GFXMODE=auto (safe, should NOT warn)",
         {'GRUB_GFXMODE': 'auto'}, False),
        ("GFXMODE=keep (safe, should NOT warn)",
         {'GRUB_GFXMODE': 'keep'}, False),
        ("GFXMODE absent (should NOT warn)",
         {}, False),
    ]

    for test_name, config, should_warn, *args in test_cases:
        total += 1
        expected_param = args[0] if args else None
        if helper.run_test(test_name, config, should_warn, expected_param):
            passed += 1

    print(f"\nPassed: {passed}/{total}")


def test_enum_validation():
    """Test enum value validation."""
    print("\n" + "=" * 70)
    print("TEST: Enum value validation")
    print("=" * 70)

    helper = TestHelper()
    passed = 0
    total = 0

    test_cases = [
        # Should warn: Invalid enum values
        ("VIDEO_BACKEND=invalid (should warn)",
         {'GRUB_VIDEO_BACKEND': 'invalid'}, True, 'GRUB_VIDEO_BACKEND'),
        ("VIDEO_BACKEND='unknown' (should warn)",
         {'GRUB_VIDEO_BACKEND': '"unknown"'}, True, 'GRUB_VIDEO_BACKEND'),

        # Should NOT warn: Valid enum values
        ("VIDEO_BACKEND=vbe (should NOT warn)",
         {'GRUB_VIDEO_BACKEND': 'vbe'}, False),
        ("VIDEO_BACKEND=efi_gop (should NOT warn)",
         {'GRUB_VIDEO_BACKEND': 'efi_gop'}, False),
        ("VIDEO_BACKEND absent (should NOT warn)",
         {}, False),
    ]

    for test_name, config, should_warn, *args in test_cases:
        total += 1
        expected_param = args[0] if args else None
        if helper.run_test(test_name, config, should_warn, expected_param):
            passed += 1

    print(f"\nPassed: {passed}/{total}")


def test_missing_cross_referenced_params():
    """H3: a cross-referenced parameter missing from the active set must not crash.

    ``getvals`` used to return an all-None tuple as soon as any requested key
    was absent, and messages were built with ``sh(p2)`` before the rule decided
    whether it fired.  A discovery-filtered ``param_cfg`` (which is what
    ``main.reinit_gw`` passes to ``make_warns``) therefore crashed with
    ``TypeError: 'NoneType' object is not subscriptable``.
    """
    print("\n" + "=" * 70)
    print("TEST: missing cross-referenced parameters")
    print("=" * 70)

    scenarios = [
        # (description, param_cfg, vals, expected warning params)
        # Exact audit reproduction: only GRUB_DEFAULT is active.
        ('only GRUB_DEFAULT active',
         {'GRUB_DEFAULT': {}},
         {'GRUB_DEFAULT': 'saved'},
         set()),
        # Discovery removed SERIAL_COMMAND while a terminal still says serial.
        ('serial terminal without active SERIAL_COMMAND',
         {'GRUB_TERMINAL_INPUT': {}},
         {'GRUB_TERMINAL_INPUT': 'serial'},
         set()),
        # Both terminal parameters are gone, but SERIAL_COMMAND remains.
        ('SERIAL_COMMAND without active terminals',
         {'GRUB_SERIAL_COMMAND': {}},
         {'GRUB_SERIAL_COMMAND': 'serial --unit=0 --speed=115200'},
         {'GRUB_SERIAL_COMMAND'}),
        # GFXMODE is gone, so the message must still name it.
        ('gfxterm without active GFXMODE',
         {'GRUB_TERMINAL': {}},
         {'GRUB_TERMINAL': 'gfxterm'},
         {'GRUB_TERMINAL'}),
        # DEFAULT is gone, so there is nothing numeric to warn about.
        ('SAVEDEFAULT=true without active DEFAULT',
         {'GRUB_SAVEDEFAULT': {}},
         {'GRUB_SAVEDEFAULT': 'true'},
         set()),
        # DEFAULT is gone, but splash is still in the wrong parameter.
        ('splash in CMDLINE_LINUX without active DEFAULT',
         {'GRUB_CMDLINE_LINUX': {}},
         {'GRUB_CMDLINE_LINUX': '"quiet splash"'},
         {'GRUB_CMDLINE_LINUX'}),
    ]

    passed = 0
    for description, param_cfg, vals, expected_params in scenarios:
        validator = WizValidator(param_cfg)
        validator._disk_layout_cache = SimpleNamespace(
            has_another_os=False,
            is_luks_active=False,
            is_lvm_active=False,
        )

        warns, _ = validator.make_warns(vals)

        assert None not in warns, (
            f"{description}: warning filed under missing parameter name: {warns}")
        assert set(warns) == expected_params, (
            f"{description}: expected warnings on {expected_params}, got {warns}")
        for pairs in warns.values():
            for _, message in pairs:
                assert 'None' not in message, (
                    f"{description}: unresolved parameter name in message: {message}")

        print(f"   ✓ PASS: {description}")
        passed += 1

    print(f"\nPassed: {passed}/{len(scenarios)}")


def main():
    """Run all validation rule tests."""
    print("\n" + "=" * 70)
    print("GRUB-WIZ VALIDATOR COMPREHENSIVE TEST SUITE")
    print("=" * 70)

    all_tests = [
        test_default_saved_vs_savedefault,
        test_timeout_zero_hidden,
        test_splash_quiet_rhgb,
        test_recovery_cmdline_vs_disable,
        test_luks_detection,
        test_lvm_detection,
        test_cryptodisk_without_luks,
        test_uuid_disabled,
        test_terminal_serial,
        test_terminal_graphical,
        test_savedefault_numeric,
        test_cmdline_quoting,
        test_distributor_missing_or_empty,
        test_enum_bad_does_not_leak_between_params,
        test_os_prober,
        test_timeout_limits,
        test_gfxmode_values,
        test_enum_validation,
        test_missing_cross_referenced_params,
    ]

    failed_tests = []
    total_tests = len(all_tests)

    for test_func in all_tests:
        try:
            test_func()
        except AssertionError as exc:
            failed_tests.append((test_func.__name__, str(exc)))

    passed_tests = total_tests - len(failed_tests)

    print("\n" + "=" * 70)
    print(f"OVERALL RESULTS: {passed_tests}/{total_tests} test suites passed")
    print("=" * 70)

    if not failed_tests:
        print("\n✓ All tests PASSED!")
        return 0

    for name, message in failed_tests:
        print(f"✗ {name}: {message}")
    print(f"\n✗ {len(failed_tests)} test suite(s) FAILED")
    return 1


if __name__ == '__main__':
    sys.exit(main())
