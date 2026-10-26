# GrubWiz Tests

This directory contains regression tests for the `grub-wiz` project.

## Test Structure

```
tests/
├── README.md                          # This file
├── conftest.py                        # Isolates user/system state per test
├── test_grubfile_parsing.py          # Test suite for GrubFile parsing
├── test_grubfile_branches.py         # Duplicate lines, adoption, write failures
├── test_validator_rules.py           # Comprehensive test suite for WizValidator rules
├── test_grubwriter_commit.py         # Hermetic commit/rollback tests for GrubWriter
├── test_grubwriter_commands.py       # Update/initramfs argv and failure paths
├── test_param_discovery_internals.py # info parsing, cache rules, discovery CLI
├── test_backup_restore.py            # Restore security guards and checksums
├── test_backup_listing.py            # Backup inventory, naming and RESYNC collapse
├── test_backup_purge.py              # Retention: trimming the inventory to 24
├── test_backup_tag.py                # Automatic tag classification and abbreviation
├── test_distro_vars.py               # Startup path/binary resolution and gating
├── test_sync_check.py                # /etc/default/grub vs generated grub.cfg mtimes
├── test_canned_config_loading.py     # Custom-config loading and fallbacks
├── test_warn_db_persistence.py       # Warning DB formats and write failures
├── test_main_helpers.py              # Non-curses helpers in main.py
├── test_cli_branches.py              # Reset/validation/demo and module CLIs
├── test_data/                        # Test GRUB configuration files
│   ├── continuation_and_expansion.conf
│   └── edge_cases.conf
└── sample_grub_configs/              # Real-world sample /etc/default/grub files
```

## Running Tests

From the project root directory, with the package and dev dependencies
installed:

```bash
# Recommended: install the package plus test dependencies, then run pytest
python3 -m pip install -e ".[dev]"
python3 -m pytest
```

The same suite can also be run without installation (pytest discovers the
package via `pythonpath = ["."]` in `pyproject.toml`). The individual scripts
remain runnable for debugging:

```bash
python3 tests/test_grubfile_parsing.py
python3 tests/test_validator_rules.py
```

Or make them executable and run directly:

```bash
chmod +x tests/*.py
./tests/test_grubfile_parsing.py
./tests/test_validator_rules.py
```

## Continuous Integration

GitHub Actions runs the suite on every push to `main`/`dev` and on every pull
request. See [`.github/workflows/tests.yml`](../.github/workflows/tests.yml).

- Python 3.10, 3.11, 3.12 and 3.13 are tested on `ubuntu-24.04`. 3.10 is the
  minimum supported version, imposed by the pinned `console-window`
  (`Requires-Python: >=3.10`) and matched by `requires-python` in
  [`pyproject.toml`](../pyproject.toml:13).
- The workflow installs `.[dev]`, byte-compiles the sources, runs `pytest`, and
  separately builds a wheel to catch packaging regressions.
- The validator tests never call `lsblk`/`efibootmgr`; they inject a fixed
  disk-layout object, so results do not depend on the runner's hardware.
- The new command/restore/discovery tests never touch `/etc/default/grub` or
  the real user state directory; they use the `tmp_path`-backed fake from
  [`conftest.py`](conftest.py:148) and patch `os.geteuid()`.
- Coverage is not gated. A branch-coverage run on 2026-10-25 measured 66%
  overall: `BackupMgr`, `WarnDB`, `DistroVars`, `GrubWriter`, `CannedConfig`,
  and `GrubCfgParser` are 93–100%; `GrubFile`, `WizValidator`, and
  `ParamDiscovery` are 78–92%; `main.py` is 42% because most of it is curses
  drawing. When `coverage` is installed (it is not currently in the `dev`
  extras), run:

  ```bash
  python3 -m coverage run --branch --source=grub_wiz -m pytest
  python3 -m coverage report
  ```

## What Is Tested

### `test_grubfile_parsing.py`

This test suite covers the continuation line and variable expansion blacklisting features added to handle complex GRUB configurations:

#### 1. **Continuation Lines and Variable Expansion**
   - Backslash continuation lines are properly joined
   - Variable expansion patterns are correctly blacklisted
   - Referenced parameters remain editable
   - Commented parameters are tracked

#### 2. **Edge Cases**
   - Commented continuation lines
   - Continuation lines with extra whitespace
   - Multiple levels of variable references
   - Cross-parameter variable dependencies

#### 3. **Write Functionality**
   - Changed parameters are written correctly
   - Blacklisted parameters pass through unchanged
   - Continuation lines are written as single lines
   - File structure is preserved

#### 4. **Referenced Parameter Editability**
   - Parameters referenced by blacklisted params remain editable
   - Changes to referenced params are written correctly
   - Blacklisted params preserve variable references

### `test_validator_rules.py`

This comprehensive test suite validates all validation rules in WizValidator with multiple scenarios for each rule:

#### Coverage

The test suite covers all ~25 validation rules with 6-8 test cases each, including:

1. **DEFAULT/SAVEDEFAULT conflicts** - Tests "saved" vs "false" logic
2. **TIMEOUT=0 with hidden style** - Critical unrecoverable state detection
3. **splash/quiet/rhgb placement** - Ensures boot params are in correct CMDLINE variable
4. **RECOVERY cmdline conflicts** - Tests empty() logic for presence vs. value
5. **LUKS/LVM detection** - Mock disk layout testing for rd.luks.uuid and rd.lvm.vg warnings
6. **CRYPTODISK without LUKS** - Cross-validation between settings and hardware
7. **UUID/PARTUUID disabled** - Fragile configuration detection
8. **Serial terminal configuration** - INPUT/OUTPUT matching and SERIAL_COMMAND requirements
9. **Graphical terminal settings** - gfxterm requirements and console conflicts
10. **SAVEDEFAULT with numeric DEFAULT** - Menu reordering warnings
11. **OS_PROBER configuration** - Multi-boot detection integration
12. **TIMEOUT limits** - Excessive timeout detection
13. **GFXMODE values** - Safe vs. uncommon resolution warnings
14. **Enum validation** - Valid value checking for enumerated parameters

#### Test Pattern

Each rule has tests covering:
- ✅ **Should warn** - Actual configuration problems
- ❌ **Should NOT warn** - Valid configurations including:
  - Variable present but empty (`≡`)
  - Variable absent/commented
  - Variable with valid value
  - Edge cases specific to that rule

#### Key Testing Insights

The test suite revealed and documents:
- **Presence vs. Value distinction** - Using `empty()` to check actual content vs. just existence
- **"false" vs "not-true" logic** - Some rules check explicit false, others check absence of true
- **Multiple rule interactions** - Tests avoid triggering unrelated rules (e.g., avoiding "quiet" in CMDLINE_LINUX tests)
- **Known issues** - Documents a bug in the quoting validation logic (TODO to fix)

### `test_grubwriter_commit.py`

Hermetic tests for the `GrubWriter` commit/rollback path (audit item C2). They
never touch `/etc/default/grub` or real user/system state directories: the
`UserConfigDir` dependency is replaced with an in-memory fake and the root
check is patched. Covered behavior includes NUL-byte rejection, `sh -n`
rejection, atomic replacement with a rollback copy, advisory
`grub-script-check`, rollback plus update re-run on failure, and explicit
critical reporting when rollback itself fails.

### `test_grubwriter_commands.py`

Covers the part of `GrubWriter` that the commit tests stub out: root and
missing-command refusal, `update-grub` versus `grub-mkconfig -o`, command exit
codes and `OSError`, initramfs trigger matching, `/boot` space calculations,
the argv used for each distro's initramfs tool, advisory `grub-script-check`,
and the commit error branches (rollback-copy failure, target-write failure,
target that did not exist).

### `test_param_discovery_internals.py`

Covers `info grub` parsing and its length/`__` filters, all discovery states
and execution failures, legacy/corrupt cache handling, the weekly staleness
rule, manual enable/disable persistence, the 20% absent-ratio guard (including
the single-probe exemption), and the module CLI.

### `test_backup_restore.py`

Pins the security contract of `restore_backup()`: non-root refusal, symlink
rejection, NUL and command-substitution refusal, explicit destinations, atomic
success, and write failures. Also covers checksum edge cases and backup
inventory filtering.

### `test_backup_listing.py`

Covers the inventory and the naming scheme: current and legacy filenames,
optional tags, six-digit checksums, the refusal to overwrite a same-second
file, identical content not being suppressed, the adjacent `RESYNC` collapse
(including a cascade through a pre-existing chain), retagging without losing
the checksum, and ordering by filename rather than modification time.

### `test_backup_purge.py`

Pins the retention rules: the 24-file limit, the oldest record never being
removed, deleting oldest-first, sacrificing an adjacent same-content `RESYNC`
before an older tagged record, *not* saving a record when the identical copy is
not adjacent, stopping the moment the limit is reached, ignoring modification
times, including legacy names, the single-line `Purge: N -> 24 backups.`
summary, and treating an unreadable file as non-redundant.

### `test_backup_tag.py`

Covers `change_tag()`: active/inactive classification (un-commenting counts as
an addition), the `+` > `-` > `~` priority, the `+N` count, and the
word-count/dash table that abbreviates a parameter to at most 12 characters.

### `test_distro_vars.py`

Drives startup resolution without inspecting the host: candidate order for
paths and binaries, fatal missing `/etc/default/grub` and update command,
crippled-mode confirmation (`y`, `n`, EOF), complete-system state, and custom
initramfs triggers.

### `test_canned_config_loading.py`

Covers the reference copy, a valid `custom_config.yaml` becoming active, and
fallbacks for invalid schema, unreadable/symlinked files, and malformed YAML.
Also exercises `_process_config()` for bad regex specs, expert-edit sentinels,
command-substitution opt-in, and non-dict sections.

### `test_warn_db_persistence.py`

Covers the legacy `warns:` format, corrupt/unreadable YAML, clean and dirty
writes, write failures, and idempotent inhibit/un-inhibit.

### `test_grubfile_branches.py`

Covers duplicate assignments (last uncommented wins, earlier comment
superseded), missing files, discovery-filtered and adopted parameters,
guidance wrapping, write failures, and the quote/continuation helpers.

### `test_main_helpers.py`

Covers the non-curses helpers: cell-width measurement and truncation, diffs,
enum/regex selection, activation defaults, activate/deactivate state,
backup-tag normalization, the startup rule (BASELINE once, nothing on later
launches), the tag handed over from REVIEW (`RESYNC` for an empty diff,
untagged when no change could be classified), recording every commit, the
quit confirmation for unapplied changes, Ctrl-C reaching that same check (it
is the quit key, even when it arrives as `KeyboardInterrupt`), and quoted enum
lookup.

### `test_cli_branches.py`

Covers `--validate-custom-config`, `--factory-reset` (including partial
failure), `--validator-demo`, the pre-curses ordering of the purge and the
`BASELINE` record, `-k`/`--keep-all-bak` suppressing only the purge, and the
`GrubCfgParser`/`DistroVars` module entry points.

## Test Data Files

### `continuation_and_expansion.conf`

Tests the core functionality:
- Simple backslash continuation lines
- Variable self-reference (both lines blacklisted)
- Variable cross-reference (only using param blacklisted)
- Normal parameters
- Commented parameters

### `edge_cases.conf`

Tests corner cases:
- Commented continuation lines (each line starts with `#`)
- Continuation lines with extra spaces/tabs
- Variable expansion with continuation lines
- Chained variable references

## Expected Behavior

### Continuation Lines
```bash
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash \
nvidia-drm.modeset=1 \
acpi_backlight=vendor"
```
- **Read**: Joined into single value `"quiet splash nvidia-drm.modeset=1 acpi_backlight=vendor"`
- **Write**: Written as single line (no backslashes)

### Variable Expansion - Self-Reference
```bash
GRUB_CMDLINE_LINUX="base"
GRUB_CMDLINE_LINUX="${GRUB_CMDLINE_LINUX} extra"
```
- **Blacklist**: `GRUB_CMDLINE_LINUX` (both lines, same param)
- **UI**: Does not appear in parameter list
- **Write**: Both lines passed through unchanged

### Variable Expansion - Cross-Reference
```bash
GRUB_TIMEOUT=5
GRUB_FOO="timeout is $GRUB_TIMEOUT seconds"
```
- **Blacklist**: `GRUB_FOO` only (uses expansion)
- **UI**: `GRUB_TIMEOUT` appears and is editable, `GRUB_FOO` does not appear
- **Write**: `GRUB_TIMEOUT` changes are written, `GRUB_FOO` passed through unchanged
- **Runtime**: When GRUB sources the file, `GRUB_FOO` picks up the new `GRUB_TIMEOUT` value

## Adding New Tests

To add new regression tests:

1. Create a new test GRUB configuration file in `test_data/`
2. Add a test function to `test_grubfile_parsing.py`
3. Call the new test function from `main()`
4. Run the tests to verify

Example test function:
```python
def test_my_new_feature():
    """Test description."""
    print("\n" + "=" * 70)
    print("TEST: My New Feature")
    print("=" * 70)

    test_file = Path(__file__).parent / "test_data" / "my_test.conf"
    supported_params = { ... }
    grub = GrubFile(supported_params, file_path=str(test_file))

    # Your assertions here
    assert some_condition, "Error message"
    print("   ✓ PASS")
```

## Test Philosophy

These tests are **regression tests** designed to:
- Ensure continuation line handling doesn't break
- Verify variable expansion blacklisting works correctly
- Catch unintended changes to parsing behavior
- Document expected behavior through executable examples

They are NOT comprehensive unit tests covering all edge cases. They focus on the specific features added for continuation lines and variable expansion.
