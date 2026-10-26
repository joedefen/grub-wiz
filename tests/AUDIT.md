# Audit: grub-wiz 0.8.19

Audit date: 2026-10-25
Scope: repository at version 0.8.19
Status: original read-only audit; production files were modified afterward. See [Remediation status](#remediation-status-2026-10-25).

## Executive summary

The project has a coherent modular structure and a good safety-oriented concept, and the existing tests pass and a wheel builds cleanly. However, there are several defects that undermine the product’s core promise (“safe GRUB configuration”), including a local privilege-escalation surface, a commit path that can leave the system unbootable with no rollback, multiple validation rules that silently never fire, and packaging metadata that claims Python versions the code cannot run on.

**Highest-risk items**

1. ~~Root writes into a user-controlled directory, enabling symlink-based arbitrary root file overwrite; combined with restore + `update-grub`, this can become root code execution.~~ Fixed: root-owned mutable state moved to `/var/lib/grub-wiz` and `/run/grub-wiz`; user-state writes reject symlinks and use atomic replacement (C1).
2. ~~`/etc/default/grub` is overwritten without syntax validation, atomically, or with rollback; a failed `update-grub` leaves the risky file in place.~~ Fixed: the candidate is staged beside the target, checked with `sh -n`, installed with `os.replace`, snapshotted, and rolled back if the GRUB update fails (C2).
3. ~~`--discovery=enable|disable` crashes due to a typo.~~ Fixed: the branch reads `opts.discovery` and is covered by [`tests/test_cli_args.py`](test_cli_args.py).
4. ~~Disk-layout detection is effectively dead due to wrong JSON key casing, so LUKS/LVM/multiboot warnings are wrong.~~ Fixed: the probe reads `lsblk`'s lowercase keys, walks flat and nested layouts, and no longer treats vfat as another OS.
5. ~~The validator crashes when any cross-referenced parameter is missing from the active parameter set.~~ Fixed: values are resolved per key, messages are `None`-safe, and rules no longer warn about parameters absent from the active set.
6. ~~The documented custom-config workflow cannot produce a valid, functional config.~~ Fixed: underscore-prefixed metadata sections are exempt from parameter validation, and `edit_re_human` is no longer required in the template (H4).
7. ~~`requires-python >=3.8` is false: the code uses PEP 701 f-strings (Python 3.12+) and the pinned dependency requires Python 3.10+.~~ Fixed: the f-string was rewritten and the project now declares `>=3.10`.

## Remediation status (2026-10-25)

Legend: ✅ fixed · ◐ partial · ☐ open.

| ID | Status | Summary |
|---|---|---|
| C1 | ✅ | Root-owned state moved to `/var/lib/grub-wiz` (cache, rollback) and `/run/grub-wiz` (session). User-directory writes use a directory fd plus `O_CREAT|O_EXCL|O_NOFOLLOW`, `fstat`/`fchmod`/`fchown`, and `os.replace()`. Restore rejects symlinks, NUL bytes, and command substitution. |
| C2 | ✅ | Candidate is staged beside the target and checked with `sh -n` (`grub-script-check` is advisory only); the previous file is snapshotted in memory and in `/var/lib/grub-wiz`; replacement is atomic; `commit_and_update()` rolls the file back when the GRUB update fails and re-runs the update, so `grub.cfg` matches the restored file. |
| C3 | ✅ | The only PEP 701 f-string was rewritten, so nothing in the tree needs 3.12+ syntax. `requires-python` is now `>=3.10` (the floor imposed by `console-window`), classifiers cover 3.10–3.13, and CI tests 3.10–3.13. |
| H1 | ✅ | [`main.py:1892`](../grub_wiz/main.py:1892) reads `opts.discovery`; `--discovery=enable\|disable\|show` all exit 0, and [`tests/test_cli_args.py`](test_cli_args.py) covers all three. |
| H2 | ✅ | `probe_disk_layout()` reads lowercase keys, walks flat and nested `lsblk` trees, skips `loop`/`rom`, counts only NTFS/exFAT and Microsoft partition GUIDs on non-removable media, and dedupes `efibootmgr` entries by `\EFI\<dir>`. [`tests/test_disk_layout.py`](test_disk_layout.py) covers 16 cases. |
| H3 | ✅ | [`getvals()`](../grub_wiz/WizValidator.py:263) resolves each key independently, [`sh()`](../grub_wiz/WizValidator.py:251) is `None`-safe with fallback names, companion-parameter rules require the companion to be active, and the enum loop resets `bad` per parameter. [`tests/test_validator_rules.py`](test_validator_rules.py:802) covers the audit reproduction and five related paths. |
| H4 | ✅ | [`validate_schema()`](../grub_wiz/CannedConfig.py:179) now skips reserved `_`-prefixed sections and requires only the YAML-present `default`/`edit_re`/`enums`/`guidance` keys, so an unmodified copy of the packaged config is accepted and remains functional. [`tests/test_canned_config.py`](test_canned_config.py) covers the packaged template and malformed fallbacks. |
| H5 | ✅ | The COMPARE screen no longer merges `extra_params` config dicts into `param_data`; `GrubFile` already registers a `SimpleNamespace` record per unvalidated parameter. `GrubFile` also works on a copy of the caller's config so reading a backup cannot adopt its extra params into `gw.param_cfg`. [`tests/test_compare_screen.py`](test_compare_screen.py) renders backups that contain unvalidated parameters. |
| H6 | ✅ | [`reset_screen_stack()`](../grub_wiz/main.py:1074) rebuilds `gw.ss` and rebinds `spinner.stack` (and `stack.obj`) to it; restore and write both use it. Restore now checks `restore_backup()`'s return value and alerts without reinitializing on failure. [`tests/test_restore_stack.py`](test_restore_stack.py) covers the rebind and both restore outcomes. |
| H7 | ✅ | [`GrubWiz.reinit_gw()`](../grub_wiz/main.py:1091) now calls [`ensure_discovered()`](../grub_wiz/ParamDiscovery.py:285) before filtering, so discovery runs at startup on a fresh install and whenever the cache is stale. [`save_params()`](../grub_wiz/ParamDiscovery.py:162) now refreshes the in-memory cache so the regenerated result is what `get_absent()` sees. [`tests/test_param_discovery.py`](test_param_discovery.py) covers fresh install, stale-cache refresh, once-per-process retry, and the `reinit_gw()` wiring. |
| H8 | ✅ | [`really_wanna()`](../grub_wiz/main.py:1778) opens with an empty seed ([`main.py:1791`](../grub_wiz/main.py:1791)) and accepts only the whole word `yes` ([`main.py:1795`](../grub_wiz/main.py:1795)); Enter, prefixes, Esc and `None` are refusals. [`tests/test_confirm_prompt.py`](test_confirm_prompt.py) covers the prompt; RESTORE `r`/`d` and REVIEW `w` now ask inline with no answer held (see the "Later change" note under H8). |
| H9 | ✅ | The editor now validates a whole-value shell grammar that allows plain GRUB values (`, = + : /`, etc.) and rejects splitting/expansion unless the parameter's `_re_specs_` entry opts into command substitution. Shipped enums/regexes were reconciled. |
| M1–M3 | ✅ | Quoting rules now detect an unquoted value directly instead of testing membership in `quotes(unquote(v))`; the missing/empty `GRUB_DISTRIBUTOR` rule no longer requires `exist()`, so ABSENT/COMMENT/empty values warn; the enum loop resets `bad` per parameter and has a regression test; `EXPERT_EDIT` is a string and the UI uses `has_edit_regex()` instead of truthiness. |
| M4 | ✅ | [`get_top_level_grub_entries()`](../grub_wiz/GrubCfgParser.py:42) now returns the documented `List[Dict[str, str]]`, matches both `menuentry` and `submenu` via `ENTRY_KEYWORDS`, dedupes titles, and the `__main__` block requires a `grub.cfg` path. [`entries_to_enums()`](../grub_wiz/GrubCfgParser.py:95) gives the `GRUB_DEFAULT` enum real descriptions instead of the raw keyword. |
| M5 | ✅ | [`WizValidator.demo()`](../grub_wiz/WizValidator.py:602) unpacks `make_warns()` and iterates `warnings.items()`; [`CannedConfig.dump()`](../grub_wiz/CannedConfig.py:215) writes through an `io.StringIO` stream. [`tests/test_debug_entry_points.py`](test_debug_entry_points.py) exercises both. |
| M6 | ✅ | User detection now prefers `SUDO_UID`/`SUDO_GID`; `os.getlogin()` is a last resort only. |
| M7 | ✅ | User state directory is `0700`; `warn-db.yaml` is `0600`; the generated template is written user-owned instead of `root:root`. |
| M8 | ✅ | [`WarnDB.audit_info()`](../grub_wiz/WarnDB.py:160) no longer latches after its first call: it reconciles `all_info`, severities, and orphaned inhibits against every snapshot it is given, and is a no-op when the snapshot is unchanged. [`WarnScreen.draw_body()`](../grub_wiz/main.py:973) re-audits live values before rendering, so entering the screen from HOME is covered too. [`tests/test_warn_db.py`](test_warn_db.py) covers repeat audits, later orphan cleanup, clean no-op redraws, and the screen redraw. |
| M9 | ✅ | [`write_file()`](../grub_wiz/GrubFile.py:346) no longer uses `assert`; `ABSENT` is ignored on both the existing-line and append paths, so it can never be written and cannot fail under `python -O`. `GRUB_TERMINAL` now defaults to `console`, and activation maps sentinel defaults to the first enum via [`_activation_default()`](../grub_wiz/main.py:1587). |
| M10 | ✅ | [`DEFAULT_ETC_GRUB`](../grub_wiz/DistroVars.py:17) is the single constant; [`GrubFile.std_location`](../grub_wiz/GrubFile.py:54) and [`BackupMgr.GRUB_DEFAULT_PATH`](../grub_wiz/BackupMgr.py:19) derive from it. [`reinit_gw()`](../grub_wiz/main.py:1274) passes `DistroVars.etc_grub` to `GrubFile`, and `BackupMgr` is built with the same resolved target. |
| M11 | ✅ | [`reinit_gw()`](../grub_wiz/main.py:1226) rebinds the validator to the rebuilt `param_cfg` through [`WizValidator.bind_param_cfg()`](../grub_wiz/WizValidator.py:42), works on a private deep copy of the config so `canned_config.data` is never mutated, and no longer calls `read_file()` a second time. |
| M12 | ✅ | [`save_params()`](../grub_wiz/ParamDiscovery.py:162) refreshes `cached_data` after the atomic write, so a forced regeneration is visible to `load_cached_data()`/`get_absent()` in the same process (also documented under H7). |
| M13 | ✅ | Pytest fixtures and CI/coverage configuration were added, and `GrubWriter`, `BackupMgr`, `WarnDB`, `CannedConfig`, `ParamDiscovery`, CLI parsing, and the commit/rollback path now have tests. Importing the package no longer creates user state: [`BackupMgr.__init__()`](../grub_wiz/BackupMgr.py:38) resolves [`UserConfigDir`](../grub_wiz/UserConfigDir.py:49) lazily, and [`tests/conftest.py`](conftest.py:1) replaces both the `UserConfigDir` and `ParamDiscovery` singletons with `tmp_path`-backed fakes (resetting the singleton/_instance slots per test). Direct coverage now exists: [`tests/test_user_config_dir.py`](test_user_config_dir.py:1) covers directory creation/permissions, singleton semantics, `SUDO_UID`/`SUDO_GID` detection, symlink rejection, atomic symlink-safe writes, the read-size bound, and staging paths; [`tests/test_action_scoping.py`](test_action_scoping.py:1) covers each action's `effective_scope`, dispatch and flag clearing, `come_from_whitelist` navigation, the HOME/REVIEW guards on the app-level R/W keys, Escape behaviour, and registration-time rejection. The new symlink test also exposed and fixed a dead check in [`_ensure_dir()`](../grub_wiz/UserConfigDir.py:159): `lstat()` reports links, so `S_ISLNK` must be tested before `S_ISDIR`. |
| M15 | ✅ | Restore stays intentionally source-only: it replaces `/etc/default/grub` and reloads the screens but does not run `update-grub`. The two-step behavior is documented in [`restore_ACTION()`](../grub_wiz/main.py:699), announced in a post-restore notice, and described in [`README.md`](../README.md:175). |
| M14 | ✅ | PEP 639 license metadata, relevant classifiers, dev extras, and ruff/mypy configs added; the console entry point now enters through `run_cli()` so exceptions tear down curses; LEFT/RIGHT are taken per window through `ConsoleWindowOpts(taken_nav_keys=...)` on `console-window==2.0.2`, so the library's `NAVIGATION_KEYS` is no longer mutated. |
| Lower-severity items | ◐ | Most fixed: `$prefix` resolution, `GrubFile` re-read state, the redundant broad except, `WarnDB` non-mapping YAML, `tag_ACTION` overwrite guard, `request_backup_tag` hint/feedback, `long_params` stray token, unknown-param activation, `os.system`/`input()` use, runner comments, sample scripts, README accuracy, the `--validate-custom-config` verdict/exit status, `BackupMgr`'s filename-keyed inventory, and continuation-line joining (single-quoted values and malformed trailing backslashes). Remaining: year-2999 sample timestamps and the broad maintainability cleanup. The non-atomic state writes were fixed as part of C1. |

No P0 or P1 items remain.

---

## Scope and method

Reviewed all modules under [`grub_wiz/`](../grub_wiz), [`canned_config.yaml`](../grub_wiz/canned_config.yaml), tests and test data, shell helper scripts, [`pyproject.toml`](../pyproject.toml), [`README.md`](../README.md), [`runner`](../runner), and repository state.

Executed:

- `python3 -m py_compile grub_wiz/*.py runner tests/*.py` — passed.
- Both test suites standalone — passed.
- `pytest -q` — 20 passed, 17 warnings.
- `python -m build --wheel` — succeeded; [`canned_config.yaml`](../grub_wiz/canned_config.yaml) is included in the wheel.
- Targeted probes against [`WizValidator`](../grub_wiz/WizValidator.py:18), [`GrubFile`](../grub_wiz/GrubFile.py:38), [`CannedConfig`](../grub_wiz/CannedConfig.py:14), [`GrubCfgParser`](../grub_wiz/GrubCfgParser.py:23), and CLI parsing.
- `pyflakes` over the package and tests.

Not exercised: real sudo elevation, a real terminal session, actual `update-grub`/initramfs execution, or writes to `/etc/default/grub` (deliberately avoided).

---

## Critical findings

### C1. Local privilege escalation: root writes into a user-owned directory — ✅ FIXED

The real user’s config directory is created and then **chowned to that user** in [`UserConfigDir._ensure_config_dir()`](../grub_wiz/UserConfigDir.py:85), mode `0755`. Root later writes several files into it using ordinary, symlink-following `open(..., 'w')`/`write_text` calls:

- Candidate GRUB file: [`update_grub()`](../grub_wiz/main.py:1602) builds `config_dir / 'etc_default_grub_candidate'` at [`main.py:1620`](../grub_wiz/main.py:1620), then [`GrubFile.write_file()`](../grub_wiz/GrubFile.py:336) calls `open(output_path, 'w', ...)` at [`GrubFile.py:403`](../grub_wiz/GrubFile.py:403).
- Warning database: [`WarnDB.write_if_dirty()`](../grub_wiz/WarnDB.py:90) uses `open('w')` at [`WarnDB.py:107`](../grub_wiz/WarnDB.py:107).
- Discovery cache: [`ParamDiscovery.save_params()`](../grub_wiz/ParamDiscovery.py:153) uses `open(..., 'w')` at [`ParamDiscovery.py:176`](../grub_wiz/ParamDiscovery.py:176).
- Canned template copy: [`CannedConfig.__init__()`](../grub_wiz/CannedConfig.py:33) uses `write_text()` at [`CannedConfig.py:45`](../grub_wiz/CannedConfig.py:45).

Because the directory is user-writable, a local user can pre-create a symlink at any of those paths pointing to a root-only target. When an administrator runs the tool, root follows the symlink and overwrites the target. The fixed, predictable candidate filename makes this especially easy.

**Compounding chain:** [`restore_backup()`](../grub_wiz/BackupMgr.py:74) copies a user-owned `.bak` over `/etc/default/grub` at [`BackupMgr.py:87`](../grub_wiz/BackupMgr.py:87). `/etc/default/grub` is sourced by distro GRUB scripts, and the editor explicitly permits command substitution (`$(...)` and backticks) via [`_is_valid_shell_token()`](../grub_wiz/main.py:1514) at [`main.py:1531`](../grub_wiz/main.py:1531) and via `re_quoted_or_command_sub` in [`canned_config.yaml:108`](../grub_wiz/canned_config.yaml:108). A crafted backup restored by an admin and followed by `update-grub` can therefore execute as root.

**Recommendations:** keep root-owned mutable state in a root-owned directory (e.g. `/var/lib/grub-wiz`); if user directories must be used, write with `os.open(..., O_CREAT|O_EXCL|O_NOFOLLOW)` plus `fstat` verification and `os.replace`; reject symlinks; validate restored content; do not run `update-grub` until the file has been parsed/validated; consider a privilege-separated helper.

### C2. The commit path is not “validated”, atomic, or reversible — ✅ FIXED

[`commit_validated_grub_config()`](../grub_wiz/GrubWriter.py:292) is named and documented as validating, but it performs no validation at all. It simply:

1. checks `euid == 0`;
2. `shutil.copy2()` over [`self.etc_grub`](../grub_wiz/GrubWriter.py:32) at [`GrubWriter.py:321`](../grub_wiz/GrubWriter.py:321);
3. `chmod 0644` at [`GrubWriter.py:326`](../grub_wiz/GrubWriter.py:326).

There is no `grub-script-check`, no shell-syntax check, no parse-back, no `fsync`, no temp-file-in-same-directory + `os.replace`, and no rollback. [`update_grub()`](../grub_wiz/main.py:1602) commits the file *before* running the update command at [`main.py:1628`](../grub_wiz/main.py:1628), then runs GRUB update at [`main.py:1635`](../grub_wiz/main.py:1635). If `grub-mkconfig` fails or the machine loses power mid-copy, `/etc/default/grub` remains changed and potentially invalid. For a bootloader tool, this is the most important reliability defect.

**Recommendations:** write candidate to `/etc/default/grub.new`, validate with `grub-script-check`, atomically `os.replace`, keep the previous file until `update-grub` succeeds, and roll back on failure. Re-run the update after rollback.

**Remediation:** the candidate is staged beside the target and installed with `os.replace`; the previous content is kept in memory and in `/var/lib/grub-wiz/last-known-good.grub`; [`commit_and_update()`](../grub_wiz/GrubWriter.py:475) runs the update, and on failure calls [`rollback_last_commit()`](../grub_wiz/GrubWriter.py:448) and then re-runs the update. Two deviations from the recommendation, both intentional:

- The syntax gate is `sh -n`, not `grub-script-check`. `/etc/default/grub` is sourced by distro shell scripts, not parsed by GRUB. `grub-script-check` rejects stock Ubuntu configs (it fails on `GRUB_DISTRIBUTOR=\`lsb_release -i -s ...\``), so using it as a gate would make valid machines uncommittable. It is still run when installed and its rejection is reported as an advisory warning.
- The staged name is unique (`.<name>.grub-wiz-<pid>-<token>`) rather than the fixed `.new`, so a pre-planted file or symlink cannot influence the commit.

### C3. Python version metadata is incorrect — ✅ FIXED

[`pyproject.toml:13`](../pyproject.toml:13) declares `requires-python = ">=3.8"` and classifiers include 3.8/3.9. In reality:

- [`main.py:859`](../grub_wiz/main.py:859) uses `f'{' ':>6}{line[:wid]}'`, which relies on PEP 701 and is a syntax error before Python 3.12.
- [`ParamDiscovery.discover_params()`](../grub_wiz/ParamDiscovery.py:93) uses `tuple[Set[str], str]` as an evaluated annotation, requiring 3.9+.
- The pinned `console-window` metadata declares `Requires-Python: >=3.10` and its source uses `ScreenStack | None`.

So the effective minimum is Python 3.12, not 3.8. Installation on 3.8–3.11 is either blocked by the dependency or fails at import/parse time.

**Recommendation:** declare `requires-python = ">=3.12"` (and update classifiers), or rewrite the nested f-string and replace builtin-generic annotations.

**Remediation:** the floor is **3.10**, not 3.12. The nested f-string was the only PEP 701 usage in the repository, and `console-window` requires 3.10, so rewriting one expression is enough:

- [`main.py:859`](../grub_wiz/main.py:859) now pads with `f'{indent}{line[:wid]}'`, where `indent = ' ' * 6` is computed once in `add_body()`, instead of nesting `' '` inside same-quoted f-string braces.
- A tokenizer scan of `grub_wiz/`, `tests/`, and `runner` found no remaining nested f-string, reused quote character inside a replacement field, or multi-line replacement field.
- No 3.11+ or 3.12+ runtime API is used (no `tomllib`, `StrEnum`, `TaskGroup`, `typing.Self`/`override`, `itertools.batched`, `Path.walk`, `datetime.UTC`, etc.), and `ast.parse(..., feature_version=(3, 10))` accepts every file.
- `tuple[Set[str], str]` at [`ParamDiscovery.discover_params()`](../grub_wiz/ParamDiscovery.py:99) is a runtime-evaluated annotation, but PEP 585 builtin generics work from 3.9, so it needs no change at a 3.10 floor.
- [`pyproject.toml:13`](../pyproject.toml:13) declares `requires-python = ">=3.10"` with 3.10–3.13 classifiers, and [`.github/workflows/tests.yml`](../.github/workflows/tests.yml) tests that whole range.

---

## High-severity findings

### H1. `--discovery=enable|disable` always crashes — ✅ FIXED

[`main.py:1890`](../grub_wiz/main.py:1890) references `opts.paramd` instead of `opts.discovery`:

[`opts.paramd`](../grub_wiz/main.py:1890)

Reproduced for both `--discovery=enable` and `--discovery=disable`: `AttributeError: 'Namespace' object has no attribute 'paramd'`. This also means the README’s advertised disable command at [`README.md:216`](../README.md:216) is broken. `--discovery=show` works.

**Remediation:** [`main.py:1892`](../grub_wiz/main.py:1892) now passes `opts.discovery == 'enable'` to [`ParamDiscovery.manual_enable()`](../grub_wiz/ParamDiscovery.py:79). A scan of the module found no other `opts.*` reference without a matching `add_argument()`, and the README text needed no change. All three branches were replayed through `main()` with `GrubWiz` and the sudo re-exec stubbed: `enable` → `manual_enable(True)`, `disable` → `manual_enable(False)`, `show` → dumps the defined parameter names, each exiting 0. Regression coverage is in [`tests/test_cli_args.py`](test_cli_args.py).

### H2. Disk-layout detection never detects anything — ✅ FIXED

[`WizValidator.probe_disk_layout()`](../grub_wiz/WizValidator.py:26) runs `lsblk -o FSTYPE,PARTTYPE -J`, but reads uppercase keys:

[`partition.get('FSTYPE')`](../grub_wiz/WizValidator.py:67) and [`partition.get('PARTTYPE')`](../grub_wiz/WizValidator.py:68)

`lsblk -J` emits lowercase keys (`fstype`, `parttype`). This was confirmed locally. On top of that, the code only scans nested `children` at [`WizValidator.py:64`](../grub_wiz/WizValidator.py:64), while `lsblk` output can present partitions flat. Result:

- LUKS detection is always false.
- LVM detection is always false.
- Partition-based multi-boot detection is always false.

Consequences: the LUKS/LVM warnings at [`WizValidator.py:262`](../grub_wiz/WizValidator.py:262) and [`WizValidator.py:267`](../grub_wiz/WizValidator.py:267) never fire, and the OS-prober advice is wrong. Also, if the casing were fixed, every UEFI ESP (vfat at [`WizValidator.py:71`](../grub_wiz/WizValidator.py:71)) would be mistaken for another OS, so simply fixing key case is not sufficient.

**Remediation:** [`probe_disk_layout()`](../grub_wiz/WizValidator.py:55) now reads the lowercase JSON keys and walks every device depth-first via [`_walk_block_devices()`](../grub_wiz/WizValidator.py:38), so flat and nested `lsblk` layouts are both scanned; `loop` and `rom` devices are skipped. Multi-boot detection no longer treats vfat as evidence on its own: only NTFS/exFAT filesystems and the Microsoft basic-data/recovery partition GUIDs count, and removable media is excluded. The `efibootmgr` fallback now groups entries by their `\EFI\<dir>` loader directory, so one OS that registers both shim and grub (as on the audit host) is not counted twice. The same host now probes as `has_another_os=True, is_luks_active=True` instead of three `False`s. Hermetic coverage in [`tests/test_disk_layout.py`](test_disk_layout.py) exercises flat vs. nested JSON, LUKS/LVM (including LVM below a LUKS mapping), ESP-only systems, internal vs. removable NTFS, loop devices, duplicate EFI loaders, missing `lsblk`, bad JSON, and caching.

### H3. Validator crashes when a cross-referenced parameter is missing — ✅ FIXED

[`getvals()`](../grub_wiz/WizValidator.py:221) returns a tuple of `None`s when any requested key is absent ([`WizValidator.py:229`](../grub_wiz/WizValidator.py:229)). Many rules unconditionally build messages containing `sh(p2)` before [`hey_if()`](../grub_wiz/WizValidator.py:231) decides whether the rule fired, e.g.:

[`WizValidator.py:247`](../grub_wiz/WizValidator.py:247), [`WizValidator.py:259`](../grub_wiz/WizValidator.py:259), [`WizValidator.py:279`](../grub_wiz/WizValidator.py:279), [`WizValidator.py:317`](../grub_wiz/WizValidator.py:317), [`WizValidator.py:351`](../grub_wiz/WizValidator.py:351).

With a partial `param_cfg` (e.g. `{'GRUB_DEFAULT': {}}`), the reproduced failure was:

`TypeError: 'NoneType' object is not subscriptable` in [`sh()`](../grub_wiz/WizValidator.py:213).

This matters in production because [`reinit_gw()`](../grub_wiz/main.py:1019) passes the *discovery-filtered* `param_cfg` to [`make_warns()`](../grub_wiz/WizValidator.py:186) at [`main.py:1078`](../grub_wiz/main.py:1078). If discovery ever removes a cross-referenced parameter, startup fails.

**Remediation:** [`getvals()`](../grub_wiz/WizValidator.py:263) now returns each requested `(name, value)` pair independently, so one absent key no longer discards the values of the keys that are present. [`sh()`](../grub_wiz/WizValidator.py:251) tolerates a missing name and accepts a fallback, so message construction can no longer raise. Rules that warn about a companion parameter now require that companion to be in the active set, which also avoids filing warnings under a `None` key ([`WizValidator.py:369`](../grub_wiz/WizValidator.py:369), [`WizValidator.py:405`](../grub_wiz/WizValidator.py:405)); the enum loop resets `bad` per parameter instead of reusing the previous rule's value ([`WizValidator.py:467`](../grub_wiz/WizValidator.py:467)). Regression coverage in [`tests/test_validator_rules.py`](test_validator_rules.py:802) includes the exact `{'GRUB_DEFAULT': {}}` reproduction plus serial, gfxterm, SAVEDEFAULT/DEFAULT, and splash/CMDLINE cases; `pytest -q` passes (50 tests).

### H4. The documented custom-config workflow is unusable — ✅ FIXED

[`README.md:232`](../README.md:232) tells users to copy the packaged `canned_config.yaml` to `custom_config.yaml`. [`validate_schema()`](../grub_wiz/CannedConfig.py:179) then rejected it:

- It required `edit_re_human` on every parameter, but that field is only injected at runtime and is not present in the YAML ([`canned_config.yaml:137`](../grub_wiz/canned_config.yaml:137) and throughout).
- It rejected top-level underscore sections: `_distro_vars_` and `_re_specs_` failed the `GRUB_*` parameter-name check.

Reproduced:

- Packaged config → `"Param ('grub_cfg' is not GRUB_*)"`.
- Config with underscore sections removed → `"Param ('GRUB_TIMEOUT' dict missing keys"`.

Removing `_distro_vars_` would also make [`DistroVars`](../grub_wiz/DistroVars.py:46) unable to find `/etc/default/grub` and exit at [`DistroVars.py:117`](../grub_wiz/DistroVars.py:117). So no custom config could be both accepted and functional. The README’s promise of schema validation/fallback was technically true, but the fallback was always taken for the documented workflow.

**Remediation:** [`validate_schema()`](../grub_wiz/CannedConfig.py:179) now skips top-level sections whose names start with `_` (after still requiring a mapping value), so [`_distro_vars_`](../grub_wiz/canned_config.yaml:1), [`_re_specs_`](../grub_wiz/canned_config.yaml:79), and [`_update_initramfs_triggers_`](../grub_wiz/canned_config.yaml:22) are accepted and remain available to [`DistroVars`](../grub_wiz/DistroVars.py:46) and [`_process_config()`](../grub_wiz/CannedConfig.py:77). Required per-parameter fields are now declared as [`required_cfg_keys`](../grub_wiz/CannedConfig.py:26) (`default`, `edit_re`, `enums`, `guidance`), excluding the runtime-derived `edit_re_human`; it is still accepted as an allowed key. A non-dict root now returns an error string instead of `False`. The README notes the reserved sections and required fields, and regression coverage in [`tests/test_canned_config.py`](test_canned_config.py) verifies that the packaged template validates, that an exact copy is loaded as the active custom config with regexes resolved and metadata intact, and that malformed configs still fall back with a warning (`pytest -q` passes, 64 tests).

### H5. Compare screen crashes on unvalidated parameters — ✅ FIXED

[`CompareScreen.add_body()`](../grub_wiz/main.py:746) merges config dictionaries into parameter data:

[`grub1.param_data.update(grub1.extra_params)`](../grub_wiz/main.py:759)

But [`GrubFile.extra_params`](../grub_wiz/GrubFile.py:60) stores *config dicts* (`default`, `enums`, `guidance`), not the `SimpleNamespace` records used by `param_data`. The subsequent `data[param].value` at [`main.py:751`](../grub_wiz/main.py:751) then raises. Reproduced:

`AttributeError: 'dict' object has no attribute 'value'`

Any backup containing an unvalidated `GRUB_*` parameter (explicitly supported and documented) will crash the compare screen.

**Remediation:** the merge is gone. [`GrubFile.read_file()`](../grub_wiz/GrubFile.py:285) already appends a `SimpleNamespace` record to `param_data` for every unvalidated parameter it adopts, so the compare screen now reads `param_data` alone, and [`get_val()`](../grub_wiz/main.py:791) treats a parameter missing from one backup as absent. [`GrubFile.__init__()`](../grub_wiz/GrubFile.py:52) also copies `supported_params` instead of mutating the caller's dict, so comparing a backup can no longer leak that backup's extra parameters into `gw.param_cfg`. Regression coverage in [`tests/test_compare_screen.py`](test_compare_screen.py) renders a backup with an unvalidated parameter, compares differing values of one, and asserts the caller's config is unchanged.

### H6. Restore/write replaces the screen stack but leaves the spinner bound to the old stack — ✅ FIXED

`OptionSpinner` stores the stack it was constructed with (`self.stack`). After a restore, [`restore_ACTION()`](../grub_wiz/main.py:704) replaced `gw.ss`; after a successful write, [`update_grub()`](../grub_wiz/main.py:1677) did the same. Neither updated `self.spinner.stack`, so action scoping and navigation checks continued to consult the stale stack. Also, [`restore_backup()`](../grub_wiz/BackupMgr.py:77) returns `False` on failure, but [`restore_ACTION()`](../grub_wiz/main.py:704) ignored the return value and reinitialized anyway.

**Remediation:** both paths now call [`reset_screen_stack()`](../grub_wiz/main.py:1074), which builds the replacement stack and rebinds `spinner.stack` to it (also syncing `stack.obj` with `spinner.default_obj`). [`restore_ACTION()`](../grub_wiz/main.py:704) checks the `restore_backup()` result and, on failure, shows an alert and leaves the current screens untouched. [`tests/test_restore_stack.py`](test_restore_stack.py) asserts the rebind and both restore outcomes.

### H7. Parameter discovery is never run by the application — ✅ FIXED

The README says parameters not present on the system are automatically removed. In practice, [`get_system_params()`](../grub_wiz/ParamDiscovery.py:307) was called only from the module’s own CLI. The application only called [`get_absent()`](../grub_wiz/ParamDiscovery.py:394), which reads an existing cache and returns an empty set if no cache exists. On a fresh install, discovery never ran, so no parameters were filtered. On later runs, results came from a possibly stale cache.

**Remediation:** [`GrubWiz.reinit_gw()`](../grub_wiz/main.py:1091) calls [`ensure_discovered()`](../grub_wiz/ParamDiscovery.py:285) before it builds the filtered parameter set. That method runs [`get_system_params()`](../grub_wiz/ParamDiscovery.py:307) exactly once per process; `get_system_params()` itself uses the cache when it is fresh and re-runs `info grub` when the cache is missing, older than a week, or in `NO_INFO` state. A failed discovery is not retried on every restore/write within the same process; restarting the application retries it. Two supporting fixes make the startup result authoritative:

- [`save_params()`](../grub_wiz/ParamDiscovery.py:162) now updates `self.cached_data` after the atomic write. Previously it only wrote the file, so `load_cached_data()` kept returning the pre-discovery snapshot and [`get_absent()`](../grub_wiz/ParamDiscovery.py:394) would ignore the fresh result (this was M12).
- The README now states that discovery runs automatically at startup when the cache is missing or stale, and that a missing-docs failure leaves all parameters visible until the next start.

Regression coverage is in [`tests/test_param_discovery.py`](test_param_discovery.py): a fresh install triggers discovery and feeds `get_absent()`, a stale `OK` cache is refreshed before filtering, a `NO_INFO` attempt is not repeated within one process, and `reinit_gw()` calls discovery before it removes unsupported parameters. `pytest -q` passes (74 tests).

### H8. Destructive prompts default to “yes” — ✅ FIXED

[`really_wanna()`](../grub_wiz/main.py:1778) seeded the answer with `'y'` and accepted any answer beginning with `y`. Pressing Enter therefore confirmed restore, delete, and commit. For a safety tool, the safe default must be “no”, and destructive actions should require an explicit match, not a prefix.

**Remediation:** the dialog now opens with an empty seed ([`main.py:1791`](../grub_wiz/main.py:1791)), so Enter submits an empty string, and confirmation requires the entire answer to equal `yes` ([`main.py:1795`](../grub_wiz/main.py:1795)) after stripping and lower-casing. `y`, `yeah`, `yess`, `yes!` and any other prefix are refusals, and Esc/`None` remains a refusal. The cost is one typed word for restore, delete, and commit; no second prompt or hold-to-confirm step was added. Regression coverage in [`tests/test_confirm_prompt.py`](test_confirm_prompt.py) asserts the seed is empty, that Enter/`None`/all prefixes refuse, that exact `yes` in any case or padding confirms, and that passthrough (search) mode is disengaged before the prompt.

**Later change (inline confirmations):** the destructive prompts no longer open a dialog at all. REVIEW's `w` asks with a header line (`⚠️ Commit changes and update GRUB  [Press "y" or ESC]`) and RESTORE's `r`/`d` ask with a one-key line under the picked row (`⚠️ Restore GRUB source from …` / `⚠️ Delete …`). Both still start with no answer held, so Enter alone cannot proceed, and Esc cancels; `really_wanna()` now guards only quitting with unapplied changes. See [`tests/test_inline_confirm_prompt.py`](test_inline_confirm_prompt.py).

**Later change (library-owned prompt):** console-window 2.1.x (added in 2.1.0, pinned at 2.1.1) provides the live prompt itself — [`begin_prompt()`](../console-window/console_window/window.py:1152), [`handle_prompt_key()`](../console-window/console_window/window.py:1176), [`add_prompt_header()`](../console-window/console_window/window.py:1198) and [`add_prompt_lines()`](../console-window/console_window/window.py:1206) — so grub-wiz keeps only what is genuinely its own: the `⚠️` decoration, and the choice of band (header for whole-screen actions, under the picked row for per-item ones, keyed by row identity the library does not model). The answer still arrives through a callback *after* the prompt is torn down, which is what lets a rejected value re-ask with the offending text still editable. Tag collisions and failed renames moved from `flash()` (which clears the screen before drawing) to [`status()`](../console-window/console_window/window.py:2249) on the separator row, so the listing stays visible while the error is shown. `COMPARE` now draws through [`BasicTextScreen`](../console-window/console_window/screens.py:260); `VIEW` keeps its own body builder because its line-number gutter is a second span on the same row, which the one-string-per-row model cannot express.

### H9. Shell-token validation is simultaneously too strict and too permissive — ✅ FIXED

[`_is_valid_shell_token()`](../grub_wiz/main.py:1514):

- Allows `$(reboot)`, backtick command substitution, and `"$(reboot)"` (verified).
- Rejects valid unquoted GRUB values containing `,`, `=`, `+`, `:`, etc. because the fallback is `^[\w.-]+$` at [`main.py:1545`](../grub_wiz/main.py:1545).

This conflicts with the shipped config: `GRUB_GFXMODE` supports `1024x768,auto` ([`canned_config.yaml:315`](../grub_wiz/canned_config.yaml:315)), `GRUB_EARLY_INITRD_LINUX_STOCK` supports space-separated unquoted values ([`canned_config.yaml:272`](../grub_wiz/canned_config.yaml:272)), and `re_theme_file` permits unquoted spaces ([`canned_config.yaml:117`](../grub_wiz/canned_config.yaml:117)). Users editing those values must add quotes that the enum path never required. Conversely, command substitution is accepted without assessing the trust boundary (see C1).

**Remediation:** the ad-hoc token check is replaced by a small shell-value grammar, [`check_shell_value()`](../grub_wiz/main.py:1083), that models the actual boundary: the value is written verbatim as `PARAM=value` into a file that distro scripts *source*. The grammar:

- accepts any bare value except the characters that change the assignment's meaning — whitespace, quotes, `\`, `$`, backticks, `; & | < > ( ) { } ! # ~` — so `1024x768,auto`, `net.ifnames=0`, `a+b:c=d`, and paths without spaces now work unquoted;
- accepts single- and double-quoted strings, but rejects expansion and command substitution *inside* double quotes, which closes the old `"$(reboot)"` bypass;
- accepts a whole-value `$(...)` or `` `...` `` command substitution only when the parameter's spec sets `allow_command_sub: true`. Only `re_quoted_or_command_sub` (used by `GRUB_DISTRIBUTOR`, whose default is `$(lsb_release -i -s)`) opts in; expert edit is an explicit administrator escape hatch that also permits it. The configured opt-in is the trust decision, and C1 already makes restore reject command substitution.
- rejects control characters (newline, NUL) so a value cannot start a new line in the sourced file.

The shipped config is reconciled with that grammar rather than papered over: `GRUB_EARLY_INITRD_LINUX_STOCK`'s multi-image enum is now quoted and its regex accepts the quoted form, `re_theme_file` accepts quoted paths containing spaces and unquoted paths without them, and `re_gfxmode` no longer allows a space after the comma. A space must be quoted because an unquoted one would make the shell treat the next word as a command; the enum values now follow the same rule as hand-edited values. Regression coverage in [`tests/test_shell_token.py`](test_shell_token.py) covers the accepted/rejected grammar, both edit paths, the opt-in boundary, double-quoted command substitution, and an invariant that every shipped enum is a safe shell value matching its own `edit_re`.

---

## Medium-severity findings

### M1. Two validation rules are dead code — ✅ FIXED

- Quoting rule: [`avi(v1) not in quotes(unquote(avi(v1)))`](../grub_wiz/WizValidator.py:356) can never be true because [`quotes()`](../grub_wiz/WizValidator.py:211) includes the unquoted value itself. The same flaw exists at [`WizValidator.py:361`](../grub_wiz/WizValidator.py:361). The test suite documents this instead of fixing it at [`test_validator_rules.py:617`](test_validator_rules.py:617).
- Missing/empty `GRUB_DISTRIBUTOR` rule: [`bad = p1 and exist(v1) and ...`](../grub_wiz/WizValidator.py:388) is false for an absent value, so it never warns. Both rules were verified to produce no warning for the intended bad input.

**Remediation:** a new `has_unquoted_space()` helper scans the value with the same single/double-quote tracking the parser uses, so `GRUB_CMDLINE_LINUX` and `GRUB_CMDLINE_LINUX_DEFAULT` now warn for a space outside quotes while fully quoted values and inner quoted spaces (`foo="a b"`) pass. The `GRUB_DISTRIBUTOR` rule no longer requires `exist(v1)` — which excluded exactly the ABSENT, COMMENT and `''` cases the rule is about — and still exempts whole-value `$(...)`/backtick command substitutions. [`test_cmdline_quoting()`](test_validator_rules.py) now includes both "should warn" cases (previously skipped with a TODO), and [`test_distributor_missing_or_empty()`](test_validator_rules.py) covers absent, commented, empty, empty-quotes and whitespace-only values plus the command-substitution exemptions. The shared test helper seeds a valid `GRUB_DISTRIBUTOR` so unrelated rule tests keep asserting about their own subject.

### M2. Stale `bad` leaks across enum iterations — ✅ FIXED

In the enum loop, [`bad`](../grub_wiz/WizValidator.py:413) is assigned only when `p1 and exist(v1)`, but [`hey_if(bad, ...)`](../grub_wiz/WizValidator.py:414) runs regardless. If the previous enum parameter warned, the next absent parameter inherits `bad=True`. A spurious `value not in list of allowed values` warning on an absent parameter was reproduced.

**Remediation:** the loop already sets `bad = False` before the presence guard (introduced with the H3 work); [`test_enum_bad_does_not_leak_between_params()`](test_validator_rules.py) now proves it for invalid→absent, absent→invalid, invalid→valid and valid→absent ordering, which the previous single-enum test could not observe.

### M3. `EXPERT_EDIT` is a tuple, not a string — ✅ FIXED

[`EXPERT_EDIT = '>>EXPERT_EDIT<<',`](../grub_wiz/CannedConfig.py:13) has a trailing comma. It happens to work because comparisons include both the tuple and its first element, but it is truthy in boolean contexts, causing the UI to advertise `[e]dit` for expert-only parameters at [`main.py:295`](../grub_wiz/main.py:295) and [`main.py:1389`](../grub_wiz/main.py:1389). It also propagates through the shallow copy at [`GrubFile.py:286`](../grub_wiz/GrubFile.py:286).

**Remediation:** [`EXPERT_EDIT`](../grub_wiz/CannedConfig.py:13) is now a plain string. [`is_expert_edit()`](../grub_wiz/CannedConfig.py:16) and [`has_edit_regex()`](../grub_wiz/CannedConfig.py:27) express the two meanings explicitly, [`_process_config()`](../grub_wiz/CannedConfig.py:143) keeps the sentinel instead of compiling it as a regex, and the UI checks `has_edit_regex()` before advertising or enabling the validated `[e]dit` action ([`main.py:350`](../grub_wiz/main.py:350), [`main.py:424`](../grub_wiz/main.py:424), [`main.py:1595`](../grub_wiz/main.py:1595)). `[E]xpertEdit` remains available. [`test_canned_config.py`](test_canned_config.py) asserts the sentinel type, the helper semantics, that `_process_config()` preserves it, and that an unvalidated `GrubFile` parameter receives a string sentinel rather than a tuple.

### M4. `GrubCfgParser` contract and implementation disagree — ✅ FIXED

[`get_top_level_grub_entries()`](../grub_wiz/GrubCfgParser.py:42) was documented and annotated as returning `List[Dict[str, str]]`, but returned a `dict` keyed by title. It also only matched `menuentry`, never `submenu`, despite [`ENTRY_KEYWORDS`](../grub_wiz/GrubCfgParser.py:11) and the docstring. The `__main__` block called it with no argument and treated keys as dicts, so both failed. Consumers at [`main.py:1275`](../grub_wiz/main.py:1275) injected enum entries whose descriptions were the literal string `menuentry`.

**Remediation:** the parser builds a list of `{'type', 'title'}` dicts (deduped by title, exclusions and `only_very_top` unchanged) and its regex alternates over `ENTRY_KEYWORDS`, so submenus are found. [`entries_to_enums()`](../grub_wiz/GrubCfgParser.py:95) converts that list to the `{value: description}` mapping used by the config, with human-readable descriptions from [`ENUM_DESCRIPTIONS`](../grub_wiz/GrubCfgParser.py:28); [`main.py`](../grub_wiz/main.py:1275) uses it instead of `.update(list)`. The module's `main()` now requires exactly one path and exits 2 with a usage message otherwise. [`tests/test_grub_cfg_parser.py`](test_grub_cfg_parser.py) covers the return type, both keywords, quoting, exclusions/dedup, `only_very_top`, the enum descriptions, and both CLI outcomes.

### M5. Debug/demo entry points are broken — ✅ FIXED

- [`WizValidator.demo()`](../grub_wiz/WizValidator.py:602) treated the two return values of [`make_warns()`](../grub_wiz/WizValidator.py:294) as an iterable of warning pairs, so `--validator-demo` failed. A `TypeError` was reproduced.
- [`CannedConfig.dump()`](../grub_wiz/CannedConfig.py:215) called `yaml.dump(self.data)` without a stream; ruamel raised `TypeError: Need a stream argument...`. Verified.

**Remediation:** [`demo()`](../grub_wiz/WizValidator.py:602) now unpacks `warnings, _all_warn_info = self.make_warns(vals)` and its printer iterates `warnings.items()`; the previous code also iterated the dict as `(param, pairs)` pairs and would have raised `ValueError` after the first crash was fixed. [`dump()`](../grub_wiz/CannedConfig.py:215) writes to an `io.StringIO` and prints the buffered YAML, which is also how the other YAML writers in the package call ruamel. [`tests/test_debug_entry_points.py`](test_debug_entry_points.py) runs `demo()` against a stubbed disk probe and asserts a known warning is printed, then checks `dump()` emits the configured YAML.

### M6. User detection prefers the terminal login over `SUDO_USER` — ✅ FIXED

[`UserConfigDir._detect_user()`](../grub_wiz/UserConfigDir.py:51) tries `os.getlogin()` before `SUDO_USER`. In tmux, cron, containers, `su`, or non-TTY contexts this can return the wrong user or raise. Setting `HOME=/tmp/gw-home` did not redirect tests: `os.getlogin()` returned the real user, so tests wrote to the real `~/.config/grub-wiz`. The correct source of truth under sudo is `SUDO_USER`/`SUDO_UID`/`SUDO_GID`.

### M7. Config-directory permissions and ownership are inconsistent — ✅ FIXED

The config dir is `0755` ([`UserConfigDir.py:96`](../grub_wiz/UserConfigDir.py:96)); backups are `0644` ([`BackupMgr.py:126`](../grub_wiz/BackupMgr.py:126)). Other local users can list and read backups. In addition, the generated `canned_config.yaml` was observed as `root:root` in the user’s directory because [`CannedConfig.py:45`](../grub_wiz/CannedConfig.py:45) does not call `give_to_user()`. Use `0700`/`0600` for the directory and sensitive files, and fix ownership consistently.

### M8. Warning DB audit runs only once per instance — ✅ FIXED

[`WarnDB.audit_info()`](../grub_wiz/WarnDB.py:152) returned immediately after the first call ([`WarnDB.py:165`](../grub_wiz/WarnDB.py:165)). [`ReviewScreen.add_body()`](../grub_wiz/main.py:451) calls it on every redraw, so new warnings and orphan cleanup after edits were not reflected in the warnings-configuration screen. The review screen still showed live warnings from `make_warns()`, but [`WarnScreen`](../grub_wiz/main.py:862) reads the stale `all_info`.

**Remediation:** the `audited` latch is gone. [`audit_info()`](../grub_wiz/WarnDB.py:160) now performs the full reconciliation on every call — it replaces `all_info` with the sorted snapshot, bumps the dirty counter only when the snapshot or the suppressed set actually changed, and purges inhibits whose warning disappeared. Repeated calls with an unchanged snapshot leave `dirty_count` at zero, so redraws do not cause spurious writes. [`WarnScreen`](../grub_wiz/main.py:959) also gained `refresh_warn_info()`, which calls `make_warns()` on the live `param_values` and audits the result at the start of [`draw_body()`](../grub_wiz/main.py:973); this covers entering the warnings screen directly from HOME without a REVIEW redraw. [`tests/test_warn_db.py`](test_warn_db.py) verifies that a later audit adds, re-grades, and removes warnings, that orphaned inhibits are purged on later audits and persisted, that an identical re-audit stays clean, and that a `WarnScreen` redraw replaces a startup warning with a post-edit warning.

### M9. `GrubFile` writing is brittle around sentinels and `assert` — ✅ FIXED

[`write_file()`](../grub_wiz/GrubFile.py:346) asserted `new_value != ABSENT` only in the existing-line loop; the append path did not guard against `ABSENT`. An `AssertionError` was reproduced for a parameter with an existing line; if the parameter is absent, the same state could append the literal sentinel `≡` into the config. Additionally, `assert` is removed under `python -O`.

Related: [`GRUB_TERMINAL`](../grub_wiz/canned_config.yaml:380) had `default: '#comment'`. [`activate_param()`](../grub_wiz/main.py:1602) used that default verbatim, so activating an absent `GRUB_TERMINAL` wrote `GRUB_TERMINAL=#comment` rather than a usable value.

**Remediation:** the `assert` is gone. Both write paths treat `ABSENT` as "no line to write": an existing line whose caller assigned `ABSENT` is left unchanged, and an absent parameter with an `ABSENT` value appends nothing. This behaves identically with or without `python -O`. Activation now calls [`_activation_default()`](../grub_wiz/main.py:1587), which treats `#comment`, `#absent`, and the internal `COMMENT`/`ABSENT` sentinels as documentation markers and falls back to the first enum (or `''`). The shipped `GRUB_TERMINAL` default is now `console`, a value that is also one of its enums. [`tests/test_grubfile_write.py`](test_grubfile_write.py) covers both write paths and the normal comment/append behaviour; [`tests/test_activation_default.py`](test_activation_default.py) covers the sentinel fallbacks and the shipped default.

### M10. Multiple sources of truth for the GRUB path — ✅ FIXED

- [`GrubFile.std_location`](../grub_wiz/GrubFile.py:54) hardcoded `/etc/default/grub`.
- [`BackupMgr.GRUB_DEFAULT_PATH`](../grub_wiz/BackupMgr.py:19) hardcoded it again.
- [`DistroVars`](../grub_wiz/DistroVars.py:46) resolves `etc_grub` from YAML.

[`GrubWiz.reinit_gw()`](../grub_wiz/main.py:1274) constructed `GrubFile` without a path, so reads ignored `DistroVars.etc_grub`, while commits used it. Any future distro override would read and write different files.

**Remediation:** [`DistroVars.DEFAULT_ETC_GRUB`](../grub_wiz/DistroVars.py:17) is now the only literal path. `DistroVars.default_yaml`, `GrubFile.std_location`, and `BackupMgr.GRUB_DEFAULT_PATH` all derive from it. At runtime the application uses the resolved value everywhere: [`GrubWiz.__init__()`](../grub_wiz/main.py:1197) builds `BackupMgr` with `Path(self.distro_vars.etc_grub)`, `reinit_gw()` passes `self.distro_vars.etc_grub` to `GrubFile`, and startup backups checksum/tag `backup_mgr.target_path`. A distro override in YAML therefore governs reads, backups, and commits. [`tests/test_grub_path.py`](test_grub_path.py) asserts the shared constant and that `reinit_gw()` passes the resolved path.

### M11. `reinit_gw()` retains stale validator state and mutates shared config — ✅ FIXED

- [`self.wiz_validator`](../grub_wiz/main.py:1046) is created only if `None`; after a restore or write, `param_cfg` is rebuilt but the validator keeps the old config reference.
- [`self.sections = self.canned_config.data`](../grub_wiz/main.py:1027) is mutated in place when underscore sections and the extra-params section are added ([`main.py:1029`](../grub_wiz/main.py:1029), [`main.py:1058`](../grub_wiz/main.py:1058)).
- `GrubFile` reads the file in its constructor ([`GrubFile.py:65`](../grub_wiz/GrubFile.py:65)) and is read again at [`main.py:1050`](../grub_wiz/main.py:1050), duplicating I/O and side effects.

**Remediation:** All three are fixed in [`reinit_gw()`](../grub_wiz/main.py:1226). The validator is still created once, but every later reinit calls [`bind_param_cfg()`](../grub_wiz/WizValidator.py:42) so it validates the new dict; the instance is reused deliberately because its initramfs policy and disk-layout cache describe the machine, not the config. `self.sections` is now a `copy.deepcopy()` of `canned_config.data` ([`main.py:1241`](../grub_wiz/main.py:1241)), so the app's "Unvalidated Params" section and the probed `GRUB_DEFAULT` menu entries live in a per-session copy; the loaded config stays pristine, the private `_...` sections survive for anyone re-processing it, and a section built from the previous `/etc/default/grub` cannot outlive that file. The redundant [`read_file()`](../grub_wiz/GrubFile.py:75) call after construction was dropped, leaving the constructor as the only read. Coverage is in [`tests/test_reinit_gw.py`](test_reinit_gw.py), with [`tests/test_grub_path.py`](test_grub_path.py) now asserting that no second read happens.

### M12. `ParamDiscovery` cache can remain stale in-session — ✅ FIXED

[`save_params()`](../grub_wiz/ParamDiscovery.py:162) writes the YAML but did not update `self.cached_data`. [`load_cached_data()`](../grub_wiz/ParamDiscovery.py:182) returns the old in-memory value, so a regeneration during the same process could continue using prior results, including in [`manual_enable()`](../grub_wiz/ParamDiscovery.py:69).

**Remediation:** [`save_params()`](../grub_wiz/ParamDiscovery.py:162) now updates `self.cached_data` immediately after the atomic write, so the regenerated result is what `load_cached_data()` returns. Coverage is part of [`tests/test_param_discovery.py`](test_param_discovery.py) (stale-cache refresh and `reinit_gw()` wiring).

### M13. Test suite is non-hermetic and misses safety-critical modules

The tests pass (`20 passed`) but:

- Importing the package creates `~/.config/grub-wiz` as a side effect via [`BackupMgr.py:18`](../grub_wiz/BackupMgr.py:18); tests were confirmed to write to the real home directory.
- `WizValidator` runs real `lsblk`/`efibootmgr` calls ([`WizValidator.py:46`](../grub_wiz/WizValidator.py:46), [`WizValidator.py:101`](../grub_wiz/WizValidator.py:101)) per validator instance; the suite took ~15.5 seconds and depends on host disk layout.
- Results depend on whether a `system-params.yaml` cache exists, because [`GrubFile.read_file()`](../grub_wiz/GrubFile.py:236) consults discovery at [`GrubFile.py:277`](../grub_wiz/GrubFile.py:277).
- Pytest reports 17 `PytestReturnNotNoneWarning`s because test functions return bools.
- No tests cover [`GrubWriter`](../grub_wiz/GrubWriter.py:16), [`BackupMgr`](../grub_wiz/BackupMgr.py:28), [`WarnDB`](../grub_wiz/WarnDB.py:18), [`ParamDiscovery`](../grub_wiz/ParamDiscovery.py:38), [`CannedConfig`](../grub_wiz/CannedConfig.py:14), [`UserConfigDir`](../grub_wiz/UserConfigDir.py:16), CLI parsing, or the TUI. The most safety-critical path has zero tests.
- No CI configuration, pytest configuration, lint/type configuration, coverage, or dev dependency group exists.

### M14. Packaging and dependency drift — ✅ FIXED

- Exact pin [`console-window==2.0.2`](../pyproject.toml:20) combined with monkeypatching its internal `NAVIGATION_KEYS` at [`main.py:40`](../grub_wiz/main.py:40) was highly version-coupled. The exact pin is deliberate policy — grub-wiz validates against one reviewed release, and the library owner may change its API between releases — but reaching into a module-level mutable set was not part of that policy. The latest commit message says “nailed the version of ConsoleWindow 3.1.2”, while the working tree pins 2.0.2 and earlier commits pinned 1.3.2 and 2.0.1.
- Topic classifier [`Topic :: Multimedia :: Video`](../pyproject.toml:25) is unrelated and misleading.
- [`[project.license]`](../pyproject.toml:31) with `text` is the legacy form under PEP 639; prefer an SPDX `license = "MIT"` and `license-files`.
- No `[project.optional-dependencies]`, no `[tool.pytest.ini_options]`, no `[tool.ruff]`/`[tool.mypy]`.
- The console entry point [`grub-wiz = "grub_wiz.main:main"`](../pyproject.toml:35) bypasses the top-level exception handler in [`main.py:1919`](../grub_wiz/main.py:1919) when the process is already root. Exceptions can leave curses in a broken state.

**Remediation:** This item is addressed. `pyproject.toml` now uses PEP 639 metadata (`license = "MIT"`, `license-files = ["LICENSE"]`, `Metadata-Version: 2.4`), replaces the multimedia topic with System/Boot and Systems Administration classifiers, requires `flit_core>=3.12`, and adds dev extras plus `[tool.ruff]`/`[tool.mypy]` configuration. The console script now points at [`run_cli()`](../grub_wiz/main.py:2170), which wraps [`main()`](../grub_wiz/main.py:2100) for both the installed script and `python -m grub_wiz.main`; it restores curses on exceptions, `KeyboardInterrupt`, and `SystemExit`, and regression coverage is in [`tests/test_cli_args.py`](test_cli_args.py).

The `NAVIGATION_KEYS` monkeypatch is gone. `console-window` 2.0.2 adds `ConsoleWindowOpts(taken_nav_keys={key: label})`, which subtracts keys from *that window's* navigation set (`opts.nav_keys`), prints the app's label in the navigation help, and leaves `NAVIGATION_KEYS` untouched for every other window. grub-wiz declares its two bindings in [`TAKEN_NAV_KEYS`](../grub_wiz/main.py:45), passes them at construction in [`setup_win()`](../grub_wiz/main.py:1319), and gives the spinner the same effective set so `add_key()` still rejects genuine navigation keys while accepting LEFT/RIGHT ([`main.py:1370`](../grub_wiz/main.py:1370)). Regression coverage in [`tests/test_nav_keys.py`](test_nav_keys.py) asserts that importing and configuring grub-wiz does not mutate the library's set, that vertical navigation survives, that the spinner accepts the taken keys and still rejects `KEY_DOWN`, and that the help screen credits LEFT/RIGHT to the app instead of advertising them as navigation.

### M15. Restore does not make the restored configuration effective — ✅ FIXED (INTENTIONAL, NOW DOCUMENTED)

[`restore_ACTION()`](../grub_wiz/main.py:699) copies the backup and reinitializes, but never invokes `run_grub_update()`. The user is returned to the main screen with `/etc/default/grub` restored but `grub.cfg` still generated from the old settings. This is intentional (“restore source then write”): restoring a backup may be used as a baseline for new changes without the boot-menu/initramfs/reboot churn of a write. The original finding was that this behavior was not stated clearly.

**Remediation:** The contract is now explicit. [`restore_ACTION()`](../grub_wiz/main.py:699) documents the two-step behavior, shows a post-restore notice stating that `grub.cfg` was not regenerated and that a write activates the restored settings, and the RESTORE SCREEN section of [`README.md`](../README.md:175) describes the same workflow.

---

## Lower-severity and polish findings

Legend: ✅ fixed · ☐ open (needs a design decision or is out of scope).

- ✅ [`WizValidator.demo()`](../grub_wiz/WizValidator.py:602) and [`CannedConfig.dump()`](../grub_wiz/CannedConfig.py:216) were broken and are now fixed (M5).
- ✅ [`WizValidator.get_full_path_and_check_existence()`](../grub_wiz/WizValidator.py:142) now expands `$prefix` to the first GRUB directory that exists (`/boot/grub`, then `/boot/grub2`, then `/usr/share/grub`) instead of always `/boot/grub`, so Fedora paths resolve.
- ✅ [`WizValidator.probe_disk_layout()`](../grub_wiz/WizValidator.py:89) no longer contains an early `break` at all: the H2 rewrite walks every device and sets independent flags.
- ✅ [`GrubFile._join_continuation_lines()`](../grub_wiz/GrubFile.py:185) no longer wraps an infallible `str.split()` in `except Exception` (the audit's bare `except:`).
- ✅ Continuation joining is complete. [`_join_continuation_lines()`](../grub_wiz/GrubFile.py:185) now joins single- and double-quoted values, and only treats a line as a continuation when it is a `[#]GRUB_*=` assignment whose opening quote is *still open* once the trailing backslash is removed. A malformed trailing backslash — a value that is already closed, a doubled/escaped backslash ([`_is_continuation_line()`](../grub_wiz/GrubFile.py:139)), a free-form comment containing `=` and a quote, or an unclosed quote followed by a new assignment — no longer swallows the next line, and a backslash after the closing quote stops the join instead of continuing the shell line. Regression coverage in [`tests/test_lower_severity_fixes.py`](test_lower_severity_fixes.py) covers single-quoted and commented single-quoted joins, the closed/quoted/escaped/comment/unterminated malformed cases, and the `pytest -q` suite passes (215 tests).
- ✅ [`GrubFile.read_file()`](../grub_wiz/GrubFile.py:246) now clears `blacklisted_params`, `extra_params`, and the adopted extra params in `supported_params` (plus `param_data`) before re-parsing, so [`_scan_for_variable_expansion()`](../grub_wiz/GrubFile.py:208) state cannot survive a re-read.
- ✅ [`WarnDB.refresh()`](../grub_wiz/WarnDB.py:49) now treats a non-mapping top-level YAML document, and non-list `inhibited`/non-dict `all_warnings` values, as an empty state instead of raising.
- ✅ [`WarnDB.write_if_dirty()`](../grub_wiz/WarnDB.py:90) and the other state writes are atomic (C1).
- ✅ [`BackupMgr.get_backups()`](../grub_wiz/BackupMgr.py:78) now keys by the unique filename, so two backups with different tags but identical content no longer collapse to one entry. [`create_backup()`](../grub_wiz/BackupMgr.py:142) still skips a new file whose checksum already exists (best effort), but an existing duplicate remains visible, restorable, and deletable. [`refresh_backup_list()`](../grub_wiz/main.py:1837) carries the filename checksum alongside each row, and [`restore_ACTION()`](../grub_wiz/main.py:700) restores the selected path rather than a checksum lookup. [`tests/test_backup_listing.py`](test_backup_listing.py) covers identical-content files, the still-active dedupe, and the restore list; [`tests/test_restore_stack.py`](test_restore_stack.py) covers selecting one of two same-checksum files.
- ✅ [`tag_ACTION()`](../grub_wiz/main.py:752) now refuses a rename whose destination already exists instead of letting `os.rename()` replace another backup.
- ✅ [`request_backup_tag()`](../grub_wiz/main.py:1820) now prints a well-formed `[regex=...]` hint, reports that the previous tag was invalid, and seeds the next attempt with it.
- ✅ [`GrubWiz.long_params`](../grub_wiz/main.py:1178) no longer contains the stray `'/'` token.
- ✅ [`is_active_param()`](../grub_wiz/main.py:1605) returns `False` for a parameter with no known value.
- ✅ [`update_grub()`](../grub_wiz/main.py:1874) now uses `print()` instead of `os.system('echo ...')` and `subprocess.run(['reboot'])`/`subprocess.run(['poweroff'])` instead of `os.system()`.
- ✅ The post-commit prompts use [`prompt_line()`](../grub_wiz/main.py:1180), and [`DistroVars`](../grub_wiz/DistroVars.py:146) catches `EOFError`, so a closed stdin is treated as the safe "no"/"return" answer instead of a traceback.
- ✅ [`Runner`](../runner:1) comments now name the real module (`grub_wiz.main`), and the manually assigned `sys.argv[0]` was removed because `runpy(..., alter_sys=True)` overwrites it.
- ✅ [`tests/install_grub_samples.sh`](install_grub_samples.sh:12) now references `fetch_grub_samples.sh`.
- ✅ [`tests/fix_checksums.sh`](fix_checksums.sh:1) now rewrites the checksum component of every `*.bak` from the file's actual SHA-256 instead of targeting obsolete `00000000` names.
- ✅ [`tests/fetch_grub_samples.sh`](fetch_grub_samples.sh:11) now downloads to a temporary name and derives the filename checksum from the downloaded content.
- ☐ Sample files still use year 2999 timestamps (intentional sort order; changing them would rename committed fixtures).
- README issues:
  - ✅ The “How It Works” bullets at [`README.md:26`](../README.md:26) now describe the real order: startup backup, validation, atomic write, update-grub with rollback.
  - ✅ The `--discovery=disable` behavior is fixed (H1).
  - ✅ `--validate-custom-config` now prints `OK`/`FAIL` and exits nonzero when the custom config was not accepted.
  - ✅ Typo “WRINTING” fixed at [`README.md:70`](../README.md:70).
- ◐ Maintainability is partly addressed: every stale `TBD` docstring/marker in [`grub_wiz/`](../grub_wiz) is replaced, and the production `except Exception` handlers are narrowed to the exceptions each path can actually raise (the CLI boundary in [`run_cli()`](../grub_wiz/main.py:2251) intentionally stays a catch-all so curses is always restored). Print-based diagnostics and the absence of logging remain. The specific unused imports/locals flagged by pyflakes are gone: `ruff check --select F401,F841,F811,F821,F822,F823` is clean over the package, `runner`, and tests.
- Regression coverage for the fixed items is in [`tests/test_lower_severity_fixes.py`](test_lower_severity_fixes.py).

---

## What works well

- Clear separation into parser, validator, writer, backup, config, and UI concerns.
- Config-driven parameter definitions and regex validation are a sensible architecture.
- Backup naming is deterministic, checksummed, and tag-sanitized; startup backup behavior is thoughtfully designed.
- Root checks exist before privileged operations, and commands are executed without `shell=True`.
- Continuation-line joining and variable-expansion blacklisting are genuinely useful and covered by regression tests.
- The test suites pass and exercise a broad set of validation rules; the wheel builds and includes the packaged YAML.
- The initramfs-trigger and disk-space logic is a thoughtful safety feature, with a critical-space guard.

---

## Recommended remaining remediation order

No P0 or P1 items remain. The remaining work is hardening and maintainability.

**P2 — hardening, testing, and maintainability**

1. DONE: The test suite is hermetic (M13): `BackupMgr` resolves `UserConfigDir` lazily, [`tests/conftest.py`](conftest.py:1) isolates both singletons under `tmp_path`, and [`tests/test_user_config_dir.py`](test_user_config_dir.py:1) plus [`tests/test_action_scoping.py`](test_action_scoping.py:1) provide direct `UserConfigDir` and TUI navigation/action-scoping coverage.
2. DONE: Finish continuation handling in [`GrubFile._join_continuation_lines()`](../grub_wiz/GrubFile.py:128): single-quoted continuations are still not joined, and a malformed trailing backslash can still join unrelated lines.
3. PARTIAL: the stale `TBD` docstrings/markers and the production broad `except Exception` handlers are replaced. Remaining: convert print-based diagnostics to logging and structured errors.

Intentional, not scheduled: the year-2999 sample timestamps stay as they are because changing them would rename committed fixtures.

---

## Verification notes

- Standalone tests: both suites passed.
- `pytest`: `20 passed, 17 warnings in 15.55s` (warnings are return-value misuse).
- Wheel build: `grub_wiz-0.8.19-py3-none-any.whl`; includes all modules plus `canned_config.yaml`.
- `pyflakes`: only unused imports/locals and `nonlocal` warnings; no undefined names.
- Confirmed at runtime: `--discovery` `AttributeError`, validator partial-config `TypeError`, spurious enum warning, quoting/distributor rules not firing, compare-screen `AttributeError`, `CannedConfig.validate_schema` failures, `ruamel` dump failure, `EXPERT_EDIT` tuple type, `GrubCfgParser` return/`__main__` failures, shell-token acceptance/rejection behavior, and real-home test pollution.
- Not run: real `/etc/default/grub` writes, `update-grub`, initramfs rebuild, or interactive TUI sessions.

---

## Remediation verification (2026-10-25)

- `python -m py_compile grub_wiz/*.py runner tests/*.py` — passed.
- `pytest -q` — 30 passed, 17 pre-existing warnings (10 new tests cover the commit path).
- Symlink probe: an `os.replace()`-based write replaced a destination symlink without modifying its target; `safe_read_bytes()` refused symlinks; `atomic_user_write()` rejected a path outside the user state directory; no temporary files remained.
- Validator probe: `grub-script-check /etc/default/grub` succeeds on the host, but fails with `Syntax error at line 9` on the stock Ubuntu sample because of the backtick `GRUB_DISTRIBUTOR` line. This is why `sh -n` is the gate and `grub-script-check` is advisory.
- Hermetic tests inject a fake `UserConfigDir`: NUL rejection, `sh -n` rejection (unterminated quote), successful atomic commit plus rollback copy, advisory `grub-script-check`, rollback and update re-run on failure, failed-rollback `CRITICAL` reporting, failed post-rollback update reporting, and rollback of a target that did not previously exist.
- CLI probe (H1): `main()` replayed with `GrubWiz` and `rerun_module_as_root` stubbed; `--discovery=enable`, `--discovery=disable`, and `--discovery=show` all exit 0 with the expected `manual_enable()` argument.
- Disk-layout probe (H2): the host previously probed as `has_another_os=False, is_luks_active=False, is_lvm_active=False`; it now reports `has_another_os=True, is_luks_active=True, is_lvm_active=False`, matching its `crypto_LUKS` partitions, Microsoft basic-data partition, and separate Kubuntu/Debian boot entries. [`tests/test_disk_layout.py`](test_disk_layout.py) feeds canned `lsblk`/`efibootmgr` output so the results do not depend on the host.
- `pytest -q` — 49 passed.
- Custom-config probe (H4): the packaged `canned_config.yaml` now passes `validate_schema()` unchanged, and an exact copy in a temporary user-config directory is selected as `using_path` with `edit_re` resolved against `_re_specs_` and `_distro_vars_` intact. [`tests/test_canned_config.py`](test_canned_config.py) also covers reserved metadata sections, runtime-only `edit_re_human`, malformed sections, and fallback to the packaged template. `pytest -q` — 64 passed.
- Discovery probe (H7): [`tests/test_param_discovery.py`](test_param_discovery.py) injects a fake state directory and a fake `discover_params()`. It verifies that a missing cache is discovered on the first `ensure_discovered()`, that a one-week-old `OK` cache is regenerated and the regenerated set—not the stale in-memory snapshot—drives `get_absent()`, that a `NO_INFO` attempt is not repeated within a process, and that `GrubWiz.reinit_gw()` calls discovery before it drops unsupported parameters. `pytest -q` — 74 passed.
- Shell-value probe (H9): `1024x768,auto` and paths without spaces pass unquoted; an unquoted space is refused with a quoting hint; `$(reboot)`, backticks and `"$(reboot)"` are refused by default; `$(lsb_release -i -s)` is accepted only for a parameter whose spec opted in (and by expert edit); every shipped enum passes [`check_shell_value()`](../grub_wiz/main.py:1083) and matches its own `edit_re`. `pytest -q` — 145 passed.
- Sentinel/path probe (M9–M10): assigning `ABSENT` to an existing parameter or to an absent one produces no sentinel and no exception (also under `-O`, since there is no `assert`); activating `GRUB_TERMINAL` writes `console`, not `#comment`; `GrubFile.std_location`, `BackupMgr.GRUB_DEFAULT_PATH`, and `DistroVars.default_yaml` share `DEFAULT_ETC_GRUB`; `reinit_gw()` passes `DistroVars.etc_grub` to `GrubFile`. `pytest -q` — 178 passed.
- Validator probe (M1–M2): an unquoted `GRUB_CMDLINE_LINUX='rd.luks.uuid=abc rd.lvm.vg=test'` now warns while the double- and single-quoted forms and `foo="a b"` do not; `GRUB_DISTRIBUTOR` warns for ABSENT, COMMENT, `''`, `'""'` and whitespace-only, and does not warn for a plain name or a `$(...)`/backtick command. Enum ordering probes show a warning only on the parameter whose value is actually invalid. `EXPERT_EDIT` is a `str`, `has_edit_regex(EXPERT_EDIT)` is `False`, and an adopted `GrubFile` parameter carries the string sentinel. `pytest -q` — 151 passed.
- Restore-contract probe (M15): a successful restore raises a notice naming the backup and destination, stating that `grub.cfg` was not regenerated and that a write activates the restored settings; the failed-restore path still alerts without reinitializing. [`tests/test_restore_stack.py`](test_restore_stack.py) covers both. `pytest -q` — 192 passed.
- Not re-tested: real sudo elevation, a real `/etc/default/grub` commit, or a real failing `grub-mkconfig`.

