# Audit: grub-wiz 0.8.19

Audit date: 2026-10-25
Scope: repository at version 0.8.19
Status: original read-only audit; production files were modified afterward. See [Remediation status](#remediation-status-2026-10-25).

## Executive summary

The project has a coherent modular structure and a good safety-oriented concept, and the existing tests pass and a wheel builds cleanly. However, there are several defects that undermine the product’s core promise (“safe GRUB configuration”), including a local privilege-escalation surface, a commit path that can leave the system unbootable with no rollback, multiple validation rules that silently never fire, and packaging metadata that claims Python versions the code cannot run on.

**Highest-risk items**

1. Root writes into a user-controlled directory, enabling symlink-based arbitrary root file overwrite; combined with restore + `update-grub`, this can become root code execution.
2. `/etc/default/grub` is overwritten without syntax validation, atomically, or with rollback; a failed `update-grub` leaves the risky file in place.
3. `--discovery=enable|disable` crashes due to a typo.
4. Disk-layout detection is effectively dead due to wrong JSON key casing, so LUKS/LVM/multiboot warnings are wrong.
5. The validator crashes when any cross-referenced parameter is missing from the active parameter set.
6. The documented custom-config workflow cannot produce a valid, functional config.
7. `requires-python >=3.8` is false: the code uses PEP 701 f-strings (Python 3.12+) and the pinned dependency requires Python 3.10+.

## Remediation status (2026-10-25)

Legend: ✅ fixed · ◐ partial · ☐ open.

| ID | Status | Summary |
|---|---|---|
| C1 | ✅ | Root-owned state moved to `/var/lib/grub-wiz` (cache, rollback) and `/run/grub-wiz` (session). User-directory writes use a directory fd plus `O_CREAT|O_EXCL|O_NOFOLLOW`, `fstat`/`fchmod`/`fchown`, and `os.replace()`. Restore rejects symlinks, NUL bytes, and command substitution. |
| C2 | ✅ | Candidate is staged beside the target and checked with `sh -n` (`grub-script-check` is advisory only); the previous file is snapshotted in memory and in `/var/lib/grub-wiz`; replacement is atomic; `commit_and_update()` rolls the file back when the GRUB update fails and re-runs the update, so `grub.cfg` matches the restored file. |
| C3 | ☐ | Unchanged. |
| H1–H8 | ☐ | Unchanged. |
| H9 | ☐ | Restore now rejects command substitution, but editor token-validation policy is unchanged. |
| M1–M5 | ☐ | Unchanged. |
| M6 | ✅ | User detection now prefers `SUDO_UID`/`SUDO_GID`; `os.getlogin()` is a last resort only. |
| M7 | ✅ | User state directory is `0700`; `warn-db.yaml` is `0600`; the generated template is written user-owned instead of `root:root`. |
| M8–M15 | ☐ | Unchanged. |
| Lower-severity items | ☐ | Open, except the non-atomic state writes (warning DB, discovery cache, backups), which are fixed as part of C1. |

Remaining P0 work is C3, H1, H2, H3, and H8.

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

### C3. Python version metadata is incorrect

[`pyproject.toml:13`](../pyproject.toml:13) declares `requires-python = ">=3.8"` and classifiers include 3.8/3.9. In reality:

- [`main.py:859`](../grub_wiz/main.py:859) uses `f'{' ':>6}{line[:wid]}'`, which relies on PEP 701 and is a syntax error before Python 3.12.
- [`ParamDiscovery.discover_params()`](../grub_wiz/ParamDiscovery.py:93) uses `tuple[Set[str], str]` as an evaluated annotation, requiring 3.9+.
- The pinned `console-window==2.0.1` metadata declares `Requires-Python: >=3.10` and its source uses `ScreenStack | None`.

So the effective minimum is Python 3.12, not 3.8. Installation on 3.8–3.11 is either blocked by the dependency or fails at import/parse time.

**Recommendation:** declare `requires-python = ">=3.12"` (and update classifiers), or rewrite the nested f-string and replace builtin-generic annotations.

---

## High-severity findings

### H1. `--discovery=enable|disable` always crashes

[`main.py:1890`](../grub_wiz/main.py:1890) references `opts.paramd` instead of `opts.discovery`:

[`opts.paramd`](../grub_wiz/main.py:1890)

Reproduced for both `--discovery=enable` and `--discovery=disable`: `AttributeError: 'Namespace' object has no attribute 'paramd'`. This also means the README’s advertised disable command at [`README.md:216`](../README.md:216) is broken. `--discovery=show` works.

### H2. Disk-layout detection never detects anything

[`WizValidator.probe_disk_layout()`](../grub_wiz/WizValidator.py:26) runs `lsblk -o FSTYPE,PARTTYPE -J`, but reads uppercase keys:

[`partition.get('FSTYPE')`](../grub_wiz/WizValidator.py:67) and [`partition.get('PARTTYPE')`](../grub_wiz/WizValidator.py:68)

`lsblk -J` emits lowercase keys (`fstype`, `parttype`). This was confirmed locally. On top of that, the code only scans nested `children` at [`WizValidator.py:64`](../grub_wiz/WizValidator.py:64), while `lsblk` output can present partitions flat. Result:

- LUKS detection is always false.
- LVM detection is always false.
- Partition-based multi-boot detection is always false.

Consequences: the LUKS/LVM warnings at [`WizValidator.py:262`](../grub_wiz/WizValidator.py:262) and [`WizValidator.py:267`](../grub_wiz/WizValidator.py:267) never fire, and the OS-prober advice is wrong. Also, if the casing were fixed, every UEFI ESP (vfat at [`WizValidator.py:71`](../grub_wiz/WizValidator.py:71)) would be mistaken for another OS, so simply fixing key case is not sufficient.

### H3. Validator crashes when a cross-referenced parameter is missing

[`getvals()`](../grub_wiz/WizValidator.py:221) returns a tuple of `None`s when any requested key is absent ([`WizValidator.py:229`](../grub_wiz/WizValidator.py:229)). Many rules unconditionally build messages containing `sh(p2)` before [`hey_if()`](../grub_wiz/WizValidator.py:231) decides whether the rule fired, e.g.:

[`WizValidator.py:247`](../grub_wiz/WizValidator.py:247), [`WizValidator.py:259`](../grub_wiz/WizValidator.py:259), [`WizValidator.py:279`](../grub_wiz/WizValidator.py:279), [`WizValidator.py:317`](../grub_wiz/WizValidator.py:317), [`WizValidator.py:351`](../grub_wiz/WizValidator.py:351).

With a partial `param_cfg` (e.g. `{'GRUB_DEFAULT': {}}`), the reproduced failure was:

`TypeError: 'NoneType' object is not subscriptable` in [`sh()`](../grub_wiz/WizValidator.py:213).

This matters in production because [`reinit_gw()`](../grub_wiz/main.py:1019) passes the *discovery-filtered* `param_cfg` to [`make_warns()`](../grub_wiz/WizValidator.py:186) at [`main.py:1078`](../grub_wiz/main.py:1078). If discovery ever removes a cross-referenced parameter, startup fails.

### H4. The documented custom-config workflow is unusable

[`README.md:232`](../README.md:232) tells users to copy the packaged `canned_config.yaml` to `custom_config.yaml`. [`validate_schema()`](../grub_wiz/CannedConfig.py:127) then rejects it:

- It requires `edit_re_human` on every parameter ([`CannedConfig.py:140`](../grub_wiz/CannedConfig.py:140)), but that field is only injected at runtime and is not present in the YAML ([`canned_config.yaml:137`](../grub_wiz/canned_config.yaml:137) and throughout).
- It rejects top-level underscore sections: `_distro_vars_` and `_re_specs_` fail the `GRUB_*` parameter-name check at [`CannedConfig.py:137`](../grub_wiz/CannedConfig.py:137).

Reproduced:

- Packaged config → `"Param ('grub_cfg' is not GRUB_*)"`.
- Config with underscore sections removed → `"Param ('GRUB_TIMEOUT' dict missing keys"`.

Removing `_distro_vars_` would also make [`DistroVars`](../grub_wiz/DistroVars.py:46) unable to find `/etc/default/grub` and exit at [`DistroVars.py:117`](../grub_wiz/DistroVars.py:117). So no custom config can be both accepted and functional. The README’s promise of schema validation/fallback is technically true, but the fallback is always taken for the documented workflow.

### H5. Compare screen crashes on unvalidated parameters

[`CompareScreen.add_body()`](../grub_wiz/main.py:746) merges config dictionaries into parameter data:

[`grub1.param_data.update(grub1.extra_params)`](../grub_wiz/main.py:759)

But [`GrubFile.extra_params`](../grub_wiz/GrubFile.py:60) stores *config dicts* (`default`, `enums`, `guidance`), not the `SimpleNamespace` records used by `param_data`. The subsequent `data[param].value` at [`main.py:751`](../grub_wiz/main.py:751) then raises. Reproduced:

`AttributeError: 'dict' object has no attribute 'value'`

Any backup containing an unvalidated `GRUB_*` parameter (explicitly supported and documented) will crash the compare screen.

### H6. Restore/write replaces the screen stack but leaves the spinner bound to the old stack

`OptionSpinner` stores the stack it was constructed with (`self.stack`). After a restore, [`restore_ACTION()`](../grub_wiz/main.py:661) replaces `gw.ss` at [`main.py:673`](../grub_wiz/main.py:673); after a successful write, [`update_grub()`](../grub_wiz/main.py:1602) does the same at [`main.py:1716`](../grub_wiz/main.py:1716). Neither updates `self.spinner.stack`. Action scoping and navigation checks in the spinner continue to consult the stale stack, so behavior after restore/write can be inconsistent or wrong. Also, [`restore_backup()`](../grub_wiz/BackupMgr.py:74) returns `False` on failure, but [`restore_ACTION()`](../grub_wiz/main.py:669) ignores the return value and proceeds to reinitialize anyway.

### H7. Parameter discovery is never run by the application

The README says parameters not present on the system are automatically removed. In practice, [`get_system_params()`](../grub_wiz/ParamDiscovery.py:254) is called only from the module’s own CLI at [`ParamDiscovery.py:450`](../grub_wiz/ParamDiscovery.py:450). The application only calls [`get_absent()`](../grub_wiz/ParamDiscovery.py:363), which reads an existing cache and returns an empty set if no cache exists. On a fresh install, discovery never runs, so no parameters are filtered. On later runs, results come from a possibly stale cache.

### H8. Destructive prompts default to “yes”

[`really_wanna()`](../grub_wiz/main.py:1588) seeds the answer with `'y'` ([`main.py:1595`](../grub_wiz/main.py:1595)) and accepts any answer beginning with `y` ([`main.py:1600`](../grub_wiz/main.py:1600)). Pressing Enter therefore confirms restore, delete, and commit. For a safety tool, the safe default must be “no”, and destructive actions should require an explicit match, not a prefix.

### H9. Shell-token validation is simultaneously too strict and too permissive

[`_is_valid_shell_token()`](../grub_wiz/main.py:1514):

- Allows `$(reboot)`, backtick command substitution, and `"$(reboot)"` (verified).
- Rejects valid unquoted GRUB values containing `,`, `=`, `+`, `:`, etc. because the fallback is `^[\w.-]+$` at [`main.py:1545`](../grub_wiz/main.py:1545).

This conflicts with the shipped config: `GRUB_GFXMODE` supports `1024x768,auto` ([`canned_config.yaml:315`](../grub_wiz/canned_config.yaml:315)), `GRUB_EARLY_INITRD_LINUX_STOCK` supports space-separated unquoted values ([`canned_config.yaml:272`](../grub_wiz/canned_config.yaml:272)), and `re_theme_file` permits unquoted spaces ([`canned_config.yaml:117`](../grub_wiz/canned_config.yaml:117)). Users editing those values must add quotes that the enum path never required. Conversely, command substitution is accepted without assessing the trust boundary (see C1).

---

## Medium-severity findings

### M1. Two validation rules are dead code

- Quoting rule: [`avi(v1) not in quotes(unquote(avi(v1)))`](../grub_wiz/WizValidator.py:356) can never be true because [`quotes()`](../grub_wiz/WizValidator.py:211) includes the unquoted value itself. The same flaw exists at [`WizValidator.py:361`](../grub_wiz/WizValidator.py:361). The test suite documents this instead of fixing it at [`test_validator_rules.py:617`](test_validator_rules.py:617).
- Missing/empty `GRUB_DISTRIBUTOR` rule: [`bad = p1 and exist(v1) and ...`](../grub_wiz/WizValidator.py:388) is false for an absent value, so it never warns. Both rules were verified to produce no warning for the intended bad input.

### M2. Stale `bad` leaks across enum iterations

In the enum loop, [`bad`](../grub_wiz/WizValidator.py:413) is assigned only when `p1 and exist(v1)`, but [`hey_if(bad, ...)`](../grub_wiz/WizValidator.py:414) runs regardless. If the previous enum parameter warned, the next absent parameter inherits `bad=True`. A spurious `value not in list of allowed values` warning on an absent parameter was reproduced.

### M3. `EXPERT_EDIT` is a tuple, not a string

[`EXPERT_EDIT = '>>EXPERT_EDIT<<',`](../grub_wiz/CannedConfig.py:13) has a trailing comma. It happens to work because comparisons include both the tuple and its first element, but it is truthy in boolean contexts, causing the UI to advertise `[e]dit` for expert-only parameters at [`main.py:295`](../grub_wiz/main.py:295) and [`main.py:1389`](../grub_wiz/main.py:1389). It also propagates through the shallow copy at [`GrubFile.py:286`](../grub_wiz/GrubFile.py:286).

### M4. `GrubCfgParser` contract and implementation disagree

[`get_top_level_grub_entries()`](../grub_wiz/GrubCfgParser.py:23) is documented and annotated as returning `List[Dict[str, str]]`, but returns a `dict` keyed by title ([`GrubCfgParser.py:66`](../grub_wiz/GrubCfgParser.py:66)). It also only matches `menuentry`, never `submenu`, despite [`ENTRY_KEYWORDS`](../grub_wiz/GrubCfgParser.py:11) and the docstring ([`GrubCfgParser.py:47`](../grub_wiz/GrubCfgParser.py:47)). The `__main__` block calls it with no argument and treats keys as dicts, so both fail ([`GrubCfgParser.py:71`](../grub_wiz/GrubCfgParser.py:71), [`GrubCfgParser.py:80`](../grub_wiz/GrubCfgParser.py:80)). Consumers at [`main.py:1072`](../grub_wiz/main.py:1072) inject enum entries whose descriptions are the literal string `menuentry`.

### M5. Debug/demo entry points are broken

- [`WizValidator.demo()`](../grub_wiz/WizValidator.py:436) treats the two return values of [`make_warns()`](../grub_wiz/WizValidator.py:186) as an iterable of warning pairs, so `--validator-demo` fails. A `TypeError` was reproduced.
- [`CannedConfig.dump()`](../grub_wiz/CannedConfig.py:147) calls `yaml.dump(self.data)` without a stream; ruamel raises `TypeError: Need a stream argument...`. Verified.

### M6. User detection prefers the terminal login over `SUDO_USER` — ✅ FIXED

[`UserConfigDir._detect_user()`](../grub_wiz/UserConfigDir.py:51) tries `os.getlogin()` before `SUDO_USER`. In tmux, cron, containers, `su`, or non-TTY contexts this can return the wrong user or raise. Setting `HOME=/tmp/gw-home` did not redirect tests: `os.getlogin()` returned the real user, so tests wrote to the real `~/.config/grub-wiz`. The correct source of truth under sudo is `SUDO_USER`/`SUDO_UID`/`SUDO_GID`.

### M7. Config-directory permissions and ownership are inconsistent — ✅ FIXED

The config dir is `0755` ([`UserConfigDir.py:96`](../grub_wiz/UserConfigDir.py:96)); backups are `0644` ([`BackupMgr.py:126`](../grub_wiz/BackupMgr.py:126)). Other local users can list and read backups. In addition, the generated `canned_config.yaml` was observed as `root:root` in the user’s directory because [`CannedConfig.py:45`](../grub_wiz/CannedConfig.py:45) does not call `give_to_user()`. Use `0700`/`0600` for the directory and sensitive files, and fix ownership consistently.

### M8. Warning DB audit runs only once per instance

[`WarnDB.audit_info()`](../grub_wiz/WarnDB.py:152) returns immediately after the first call ([`WarnDB.py:165`](../grub_wiz/WarnDB.py:165)). [`ReviewScreen.add_body()`](../grub_wiz/main.py:451) calls it on every redraw, so new warnings and orphan cleanup after edits are not reflected in the warnings-configuration screen. The review screen still shows live warnings from `make_warns()`, but [`WarnScreen`](../grub_wiz/main.py:862) reads the stale `all_info`.

### M9. `GrubFile` writing is brittle around sentinels and `assert`

[`write_file()`](../grub_wiz/GrubFile.py:336) asserts `new_value != ABSENT` only in the existing-line loop ([`GrubFile.py:358`](../grub_wiz/GrubFile.py:358)); the append path ([`GrubFile.py:374`](../grub_wiz/GrubFile.py:374)) does not guard against `ABSENT`. An `AssertionError` was reproduced for a parameter with an existing line; if the parameter is absent, the same state can append the literal sentinel `≡` into the config. Additionally, `assert` is removed under `python -O`.

Related: [`GRUB_TERMINAL`](../grub_wiz/canned_config.yaml:370) has `default: '#comment'`. [`activate_param()`](../grub_wiz/main.py:1353) uses that default verbatim, so activating an absent `GRUB_TERMINAL` writes `GRUB_TERMINAL=#comment` rather than a usable value.

### M10. Multiple sources of truth for the GRUB path

- [`GrubFile.std_location`](../grub_wiz/GrubFile.py:47) hardcodes `/etc/default/grub`.
- [`BackupMgr.GRUB_DEFAULT_PATH`](../grub_wiz/BackupMgr.py:17) hardcodes it again.
- [`DistroVars`](../grub_wiz/DistroVars.py:46) resolves `etc_grub` from YAML.

[`GrubWiz.reinit_gw()`](../grub_wiz/main.py:1019) constructs `GrubFile` without a path, so reads ignore `DistroVars.etc_grub`, while commits use it. Any future distro override would read and write different files.

### M11. `reinit_gw()` retains stale validator state and mutates shared config

- [`self.wiz_validator`](../grub_wiz/main.py:1046) is created only if `None`; after a restore or write, `param_cfg` is rebuilt but the validator keeps the old config reference.
- [`self.sections = self.canned_config.data`](../grub_wiz/main.py:1027) is mutated in place when underscore sections and the extra-params section are added ([`main.py:1029`](../grub_wiz/main.py:1029), [`main.py:1058`](../grub_wiz/main.py:1058)).
- `GrubFile` reads the file in its constructor ([`GrubFile.py:65`](../grub_wiz/GrubFile.py:65)) and is read again at [`main.py:1050`](../grub_wiz/main.py:1050), duplicating I/O and side effects.

### M12. `ParamDiscovery` cache can remain stale in-session

[`save_params()`](../grub_wiz/ParamDiscovery.py:153) writes the YAML but does not update `self.cached_data`. [`load_cached_data()`](../grub_wiz/ParamDiscovery.py:182) returns the old in-memory value at [`ParamDiscovery.py:190`](../grub_wiz/ParamDiscovery.py:190), so a regeneration during the same process may continue using prior results, including in [`manual_enable()`](../grub_wiz/ParamDiscovery.py:69).

### M13. Test suite is non-hermetic and misses safety-critical modules

The tests pass (`20 passed`) but:

- Importing the package creates `~/.config/grub-wiz` as a side effect via [`BackupMgr.py:18`](../grub_wiz/BackupMgr.py:18); tests were confirmed to write to the real home directory.
- `WizValidator` runs real `lsblk`/`efibootmgr` calls ([`WizValidator.py:46`](../grub_wiz/WizValidator.py:46), [`WizValidator.py:101`](../grub_wiz/WizValidator.py:101)) per validator instance; the suite took ~15.5 seconds and depends on host disk layout.
- Results depend on whether a `system-params.yaml` cache exists, because [`GrubFile.read_file()`](../grub_wiz/GrubFile.py:236) consults discovery at [`GrubFile.py:277`](../grub_wiz/GrubFile.py:277).
- Pytest reports 17 `PytestReturnNotNoneWarning`s because test functions return bools.
- No tests cover [`GrubWriter`](../grub_wiz/GrubWriter.py:16), [`BackupMgr`](../grub_wiz/BackupMgr.py:28), [`WarnDB`](../grub_wiz/WarnDB.py:18), [`ParamDiscovery`](../grub_wiz/ParamDiscovery.py:38), [`CannedConfig`](../grub_wiz/CannedConfig.py:14), [`UserConfigDir`](../grub_wiz/UserConfigDir.py:16), CLI parsing, or the TUI. The most safety-critical path has zero tests.
- No CI configuration, pytest configuration, lint/type configuration, coverage, or dev dependency group exists.

### M14. Packaging and dependency drift

- Exact pin [`console-window==2.0.1`](../pyproject.toml:16) combined with monkeypatching its internal [`NAVIGATION_KEYS`](../grub_wiz/main.py:24) at [`main.py:40`](../grub_wiz/main.py:40) is highly version-coupled. The latest commit message says “nailed the version of ConsoleWindow 3.1.2”, while the working tree pins 2.0.1 and the previous commit pinned 1.3.2.
- Topic classifier [`Topic :: Multimedia :: Video`](../pyproject.toml:25) is unrelated and misleading.
- [`[project.license]`](../pyproject.toml:31) with `text` is the legacy form under PEP 639; prefer an SPDX `license = "MIT"` and `license-files`.
- No `[project.optional-dependencies]`, no `[tool.pytest.ini_options]`, no `[tool.ruff]`/`[tool.mypy]`.
- The console entry point [`grub-wiz = "grub_wiz.main:main"`](../pyproject.toml:35) bypasses the top-level exception handler in [`main.py:1919`](../grub_wiz/main.py:1919) when the process is already root. Exceptions can leave curses in a broken state.

### M15. Restore does not make the restored configuration effective

[`restore_ACTION()`](../grub_wiz/main.py:661) copies the backup and reinitializes, but never invokes `run_grub_update()`. The user is returned to the main screen with `/etc/default/grub` restored but `grub.cfg` still generated from the old settings. This may be intentional (“restore source then write”), but it is not stated clearly and is surprising for a “restore” action.

---

## Lower-severity and polish findings

- [`WizValidator.demo()`](../grub_wiz/WizValidator.py:436) and [`CannedConfig.dump()`](../grub_wiz/CannedConfig.py:147) are broken (above).
- [`WizValidator.get_full_path_and_check_existence()`](../grub_wiz/WizValidator.py:142) expands `$prefix` to `/boot/grub` always at [`WizValidator.py:161`](../grub_wiz/WizValidator.py:161), which is wrong on Fedora (`/boot/grub2`).
- [`WizValidator.probe_disk_layout()`](../grub_wiz/WizValidator.py:89) “early break” only exits the inner partition loop, not the device loop.
- [`GrubFile._join_continuation_lines()`](../grub_wiz/GrubFile.py:128) uses a bare `except:` at [`GrubFile.py:165`](../grub_wiz/GrubFile.py:165); it can join unrelated lines after a malformed trailing backslash and only supports double quotes.
- [`GrubFile._scan_for_variable_expansion()`](../grub_wiz/GrubFile.py:208) blacklists any left-hand param containing `$GRUB_`, but does not clear `blacklisted_params`/`extra_params` on re-read.
- [`WarnDB.refresh()`](../grub_wiz/WarnDB.py:49) catches only `IOError`/`YAMLError`; a YAML document whose top level is a list/string leads to `AttributeError` at [`WarnDB.py:71`](../grub_wiz/WarnDB.py:71).
- [`WarnDB.write_if_dirty()`](../grub_wiz/WarnDB.py:90) and other state writes are non-atomic (C1).
- [`BackupMgr.get_backups()`](../grub_wiz/BackupMgr.py:64) keys by checksum, so two backups with different tags but identical content collapse to one entry; [`create_backup`](../grub_wiz/BackupMgr.py:98) also skips identical content by design.
- [`tag_ACTION()`](../grub_wiz/main.py:690) uses `os.rename()` at [`main.py:703`](../grub_wiz/main.py:703), which silently replaces an existing destination on POSIX.
- [`request_backup_tag()`](../grub_wiz/main.py:1554) prints a malformed hint with an extra bracket at [`main.py:1561`](../grub_wiz/main.py:1561) and retries silently on invalid input.
- [`GrubWiz.long_params`](../grub_wiz/main.py:974) contains a stray `'/'` token at [`main.py:977`](../grub_wiz/main.py:977).
- [`is_active_param()`](../grub_wiz/main.py:1344) returns `True` for an unknown parameter at [`main.py:1351`](../grub_wiz/main.py:1351).
- [`update_grub()`](../grub_wiz/main.py:1602) uses `os.system()` for echo/reboot/poweroff at [`main.py:1688`](../grub_wiz/main.py:1688) and [`main.py:1702`](../grub_wiz/main.py:1702); the strings are constants, but `subprocess.run`/`print` is preferable.
- `input()` in [`update_grub()`](../grub_wiz/main.py:1661) and [`DistroVars`](../grub_wiz/DistroVars.py:139) raises `EOFError` in non-interactive contexts.
- [`Runner`](../runner:13) comments reference a non-existent module name, and `alter_sys=True` will overwrite the manually assigned `sys.argv[0]` at [`runner:17`](../runner:17).
- [`tests/install_grub_samples.sh`](install_grub_samples.sh:12) references a non-existent `collect_grub_samples.sh`.
- [`tests/fix_checksums.sh`](fix_checksums.sh:6) targets `00000000` filenames that no longer exist.
- [`tests/fetch_grub_samples.sh`](fetch_grub_samples.sh:17) invents a random checksum for filenames, so the checksum component no longer reflects file content. Sample files also use year 2999 timestamps.
- README issues:
  - “validation → update-grub → backup” at [`README.md:26`](../README.md:26) does not match the implementation (backup happens at startup; there is no validation).
  - The advertised `--discovery=disable` at [`README.md:216`](../README.md:216) crashes (H1).
  - `--validate-custom-config` at [`README.md:239`](../README.md:239) only prints the selected config path; it does not report a validation verdict or exit nonzero ([`main.py:1882`](../grub_wiz/main.py:1882)).
  - Typo “WRINTING” at [`README.md:70`](../README.md:70).
- Maintainability: 45 `TBD` docstrings/markers, 25 broad `except Exception`/bare excepts, 133 top-level `print()` calls, 17 `pylint: disable` lines, no logging, and unused imports/locals flagged by pyflakes (e.g. [`main.py:299`](../grub_wiz/main.py:299), [`main.py:527`](../grub_wiz/main.py:527), [`WizValidator.py:216`](../grub_wiz/WizValidator.py:216)).

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

## Recommended remediation order

**P0 — before any real-world use**

1. ✅ Fix the privilege boundary (C1): move root-owned state out of the user directory and eliminate symlink-following writes.
2. ✅ Make the commit path validate, atomically replace, and roll back (C2).
3. Fix `requires-python` and classifiers to match reality (C3).
4. Fix `opts.paramd` (H1).
5. Fix `lsblk` key casing and scan both flat devices and children; stop treating every vfat ESP as another OS (H2).
6. Make validator message construction lazy so missing cross-references cannot crash startup (H3).
7. Change destructive confirmation defaults to “no” and require exact confirmation (H8).

**P1 — correctness and user-facing promises**

8. Repair the custom-config schema and validation workflow, including underscore sections and `edit_re_human` (H4).
9. Fix the extra-params merge in the compare screen (H5).
10. Keep `spinner.stack` in sync when replacing `ScreenStack`; check restore return values (H6).
11. Wire `get_system_params()` into startup or remove the documented automatic-discovery claim (H7).
12. Fix the shell-token validator and reconcile it with the shipped regexes/enums (H9).
13. Fix the dead quoting/distributor rules and the stale `bad` loop variable (M1, M2).
14. Run `update-grub` after restore or clearly document the two-step behavior; check restore success (M15).
15. Fix `EXPERT_EDIT`, `GrubCfgParser`, `demo()`, and `dump()` (M3–M5).

**P2 — hardening, testing, and maintainability**

16. Make tests hermetic: inject config paths, fake discovery/disk probes, add pytest fixtures, and remove import-time side effects.
17. Add tests for `GrubWriter`, `BackupMgr`, `WarnDB`, config validation, CLI parsing, and the commit/rollback path.
18. Add CI, lint/type configuration, and a dev dependency group.
19. ✅ Use `SUDO_USER` for ownership, tighten directory/file modes, and fix canned-template ownership (M6–M7).
20. Refactor path handling to a single source of truth and refresh validator/config state on reinit (M10–M11).
21. Replace stale `TBD` documentation, broad exceptions, and print-based diagnostics with logging.

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
- Not re-tested: real sudo elevation, a real `/etc/default/grub` commit, or a real failing `grub-mkconfig`.
