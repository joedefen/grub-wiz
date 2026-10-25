#!/usr/bin/env python3
"""
Regression tests for GrubFile continuation line and variable expansion handling.

Tests cover:
1. Backslash continuation line joining
2. Variable expansion blacklisting
3. Commented continuation lines
4. Cross-parameter references
5. Write functionality with blacklisted params
"""

import sys
from pathlib import Path

# Add parent directory to path to import grub_wiz
sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz.GrubFile import GrubFile


def test_continuation_and_expansion():
    """Test basic continuation lines and variable expansion blacklisting."""
    print("\n" + "=" * 70)
    print("TEST: Continuation Lines and Variable Expansion")
    print("=" * 70)

    test_file = Path(__file__).parent / "test_data" / "continuation_and_expansion.conf"

    supported_params = {
        "GRUB_TIMEOUT": {"guidance": "Timeout in seconds"},
        "GRUB_CMDLINE_LINUX_DEFAULT": {"guidance": "Default kernel cmdline"},
        "GRUB_CMDLINE_LINUX": {"guidance": "Kernel cmdline for all modes"},
        "GRUB_DISABLE_RECOVERY": {"guidance": "Disable recovery mode"},
        "GRUB_THEME": {"guidance": "Theme path"},
        "GRUB_FOO": {"guidance": "Test parameter"},
    }

    grub = GrubFile(supported_params, file_path=str(test_file))

    # Test 1: Blacklist contains only params using expansion
    print("\n1. Blacklisted params (should be GRUB_CMDLINE_LINUX, GRUB_FOO):")
    print(f"   {grub.blacklisted_params}")
    assert grub.blacklisted_params == {'GRUB_CMDLINE_LINUX', 'GRUB_FOO'}, \
        f"Expected {{'GRUB_CMDLINE_LINUX', 'GRUB_FOO'}}, got {grub.blacklisted_params}"
    print("   ✓ PASS")

    # Test 2: GRUB_TIMEOUT is NOT blacklisted (only referenced)
    print("\n2. GRUB_TIMEOUT should be editable (not blacklisted):")
    print(f"   GRUB_TIMEOUT in blacklist: {('GRUB_TIMEOUT' in grub.blacklisted_params)}")
    assert 'GRUB_TIMEOUT' not in grub.blacklisted_params, \
        "GRUB_TIMEOUT should not be blacklisted (it's only referenced)"
    print(f"   GRUB_TIMEOUT value: {grub.get_current_state('GRUB_TIMEOUT')}")
    assert grub.get_current_state('GRUB_TIMEOUT') == '5', \
        f"Expected '5', got {grub.get_current_state('GRUB_TIMEOUT')}"
    print("   ✓ PASS")

    # Test 3: Continuation lines are joined
    print("\n3. Continuation lines should be joined into single value:")
    cmdline_value = grub.get_current_state('GRUB_CMDLINE_LINUX_DEFAULT')
    print(f"   Value: {cmdline_value}")
    expected = '"quiet splash nvidia-drm.modeset=1 acpi_backlight=vendor intel_pstate=disable"'
    assert cmdline_value == expected, \
        f"Expected {expected}, got {cmdline_value}"
    print("   ✓ PASS")

    # Test 4: Commented param tracked correctly
    print("\n4. Commented parameter should be tracked:")
    theme_value = grub.get_current_state('GRUB_THEME')
    print(f"   GRUB_THEME value: {theme_value}")
    assert theme_value == grub.COMMENT, \
        f"Expected {grub.COMMENT}, got {theme_value}"
    print("   ✓ PASS")

    print("\n✓ All tests PASSED for continuation_and_expansion.conf\n")


def test_edge_cases():
    """Test edge cases like commented continuations, mixed expansions."""
    print("\n" + "=" * 70)
    print("TEST: Edge Cases")
    print("=" * 70)

    test_file = Path(__file__).parent / "test_data" / "edge_cases.conf"

    supported_params = {
        "GRUB_TIMEOUT": {"guidance": "Timeout in seconds"},
        "GRUB_CMDLINE_LINUX_DEFAULT": {"guidance": "Default kernel cmdline"},
        "GRUB_DISTRIBUTOR": {"guidance": "Distributor name"},
        "GRUB_DISABLE_RECOVERY": {"guidance": "Disable recovery mode"},
        "GRUB_FOO": {"guidance": "Test parameter"},
        "GRUB_BAR": {"guidance": "Test parameter 2"},
    }

    grub = GrubFile(supported_params, file_path=str(test_file))

    # Test 1: Commented continuation line joined
    print("\n1. Commented continuation line should be joined:")
    cmdline_value = grub.get_current_state('GRUB_CMDLINE_LINUX_DEFAULT')
    print(f"   GRUB_CMDLINE_LINUX_DEFAULT: {cmdline_value}")
    assert cmdline_value == grub.COMMENT, \
        f"Expected {grub.COMMENT}, got {cmdline_value}"
    print("   ✓ PASS")

    # Test 2: Continuation with spaces joined correctly
    print("\n2. Continuation with extra spaces should be joined:")
    distributor_value = grub.get_current_state('GRUB_DISTRIBUTOR')
    print(f"   GRUB_DISTRIBUTOR: {distributor_value}")
    # Spaces are preserved as-is
    assert 'Arch' in distributor_value and 'Linux' in distributor_value, \
        f"Expected 'Arch' and 'Linux' in value, got {distributor_value}"
    print("   ✓ PASS")

    # Test 3: Both GRUB_FOO and GRUB_BAR blacklisted
    print("\n3. GRUB_FOO and GRUB_BAR should be blacklisted:")
    print(f"   Blacklisted: {grub.blacklisted_params}")
    assert 'GRUB_FOO' in grub.blacklisted_params, "GRUB_FOO should be blacklisted"
    assert 'GRUB_BAR' in grub.blacklisted_params, "GRUB_BAR should be blacklisted"
    assert 'GRUB_TIMEOUT' not in grub.blacklisted_params, \
        "GRUB_TIMEOUT should not be blacklisted (only referenced)"
    print("   ✓ PASS")

    print("\n✓ All tests PASSED for edge_cases.conf\n")


def test_write_functionality():
    """Test that write preserves blacklisted params and writes joined continuations."""
    print("\n" + "=" * 70)
    print("TEST: Write Functionality")
    print("=" * 70)

    test_file = Path(__file__).parent / "test_data" / "continuation_and_expansion.conf"

    supported_params = {
        "GRUB_TIMEOUT": {"guidance": "Timeout in seconds"},
        "GRUB_CMDLINE_LINUX_DEFAULT": {"guidance": "Default kernel cmdline"},
        "GRUB_CMDLINE_LINUX": {"guidance": "Kernel cmdline for all modes"},
        "GRUB_DISABLE_RECOVERY": {"guidance": "Disable recovery mode"},
        "GRUB_THEME": {"guidance": "Theme path"},
        "GRUB_FOO": {"guidance": "Test parameter"},
    }

    grub = GrubFile(supported_params, file_path=str(test_file))

    # Make changes to editable params
    grub.set_new_value("GRUB_TIMEOUT", "10")
    grub.set_new_value("GRUB_DISABLE_RECOVERY", "false")
    grub.set_new_value("GRUB_THEME", "/boot/grub/themes/new")

    # Capture stdout
    import io
    from contextlib import redirect_stdout

    output = io.StringIO()
    with redirect_stdout(output):
        grub.write_file(use_stdout=True)

    result = output.getvalue()

    # Test 1: Changed params are written
    print("\n1. Changed params should be written:")
    assert "GRUB_TIMEOUT=10" in result, "GRUB_TIMEOUT should be changed to 10"
    assert "GRUB_DISABLE_RECOVERY=false" in result, "GRUB_DISABLE_RECOVERY should be false"
    print("   ✓ PASS")

    # Test 2: Blacklisted params passed through
    print("\n2. Blacklisted params should be passed through unchanged:")
    assert 'GRUB_CMDLINE_LINUX="base"' in result, "First GRUB_CMDLINE_LINUX line preserved"
    assert '${GRUB_CMDLINE_LINUX}' in result, "Second GRUB_CMDLINE_LINUX line preserved"
    assert 'GRUB_FOO="timeout is $GRUB_TIMEOUT seconds"' in result, "GRUB_FOO preserved"
    print("   ✓ PASS")

    # Test 3: Continuation line written as single line
    print("\n3. Continuation line should be written as single line:")
    # Should NOT have backslash continuation in output
    lines = result.split('\n')
    cmdline_lines = [line for line in lines if 'GRUB_CMDLINE_LINUX_DEFAULT=' in line]
    assert len(cmdline_lines) == 1, \
        f"Expected 1 GRUB_CMDLINE_LINUX_DEFAULT line, got {len(cmdline_lines)}"
    assert '\\' not in cmdline_lines[0], "Should not have backslash in written line"
    print("   ✓ PASS")

    print("\n✓ All tests PASSED for write functionality\n")


def test_referenced_param_editable():
    """Test that params referenced by blacklisted params remain editable."""
    print("\n" + "=" * 70)
    print("TEST: Referenced Parameters Remain Editable")
    print("=" * 70)

    test_file = Path(__file__).parent / "test_data" / "continuation_and_expansion.conf"

    supported_params = {
        "GRUB_TIMEOUT": {"guidance": "Timeout in seconds"},
        "GRUB_FOO": {"guidance": "Test parameter"},
    }

    grub = GrubFile(supported_params, file_path=str(test_file))

    print("\n1. GRUB_TIMEOUT should be editable even though referenced by GRUB_FOO:")
    print(f"   GRUB_TIMEOUT in blacklist: {('GRUB_TIMEOUT' in grub.blacklisted_params)}")
    print(f"   GRUB_FOO in blacklist: {('GRUB_FOO' in grub.blacklisted_params)}")
    assert 'GRUB_TIMEOUT' not in grub.blacklisted_params, \
        "GRUB_TIMEOUT should not be blacklisted"
    assert 'GRUB_FOO' in grub.blacklisted_params, \
        "GRUB_FOO should be blacklisted"
    print("   ✓ PASS")

    print("\n2. Editing GRUB_TIMEOUT should work:")
    original = grub.get_current_state('GRUB_TIMEOUT')
    grub.set_new_value("GRUB_TIMEOUT", "99")
    new_value = grub.param_data['GRUB_TIMEOUT'].new_value
    print(f"   Original: {original}, New: {new_value}")
    assert new_value == "99", f"Expected '99', got {new_value}"
    print("   ✓ PASS")

    print("\n3. Written file should reflect GRUB_TIMEOUT change:")
    import io
    from contextlib import redirect_stdout

    output = io.StringIO()
    with redirect_stdout(output):
        grub.write_file(use_stdout=True)
    result = output.getvalue()

    assert "GRUB_TIMEOUT=99" in result, "GRUB_TIMEOUT should be 99 in output"
    assert 'GRUB_FOO="timeout is $GRUB_TIMEOUT seconds"' in result, \
        "GRUB_FOO should be unchanged (will pick up new value when sourced)"
    print("   ✓ PASS")

    print("\n✓ All tests PASSED for referenced param editability\n")


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("GrubFile Parsing and Blacklist Regression Tests")
    print("=" * 70)

    try:
        test_continuation_and_expansion()
        test_edge_cases()
        test_write_functionality()
        test_referenced_param_editable()

        print("\n" + "=" * 70)
        print("ALL TESTS PASSED ✓")
        print("=" * 70 + "\n")
        return 0

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
