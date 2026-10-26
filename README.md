>  **Note: This is version 0.8.y - please report issues at https://github.com/joedefen/grub-wiz/issues**

## GrubWiz: Safe GRUB Configuration Made Simple

`grub-wiz` is a terminal-based editor that helps you manage /etc/default/grub safely and efficiently, replacing error-prone manual editing with guided configuration.

**The Problem It Solves.** Editing GRUB configurations manually is risky—typos can break your bootloader, and GUI tools often make overly aggressive changes. `grub-wiz` provides a middle ground: the power of direct editing with the safety of validation and guidance.

* **Safety by Design**
  -   Parameter validation via regex and cross-checks
  -   Safe defaults and guided choices for common settings
  -   Backups offered when configuration is unique
  -   **Smart initramfs rebuild**: Detects driver/kernel changes and offers to rebuild initramfs with disk space validation

* **Key Features**
  -   *Smart editing*: Preset choices for common values, regex validation for free-form entries
  -   *Context-aware warnings*: Cross-parameter validation and sensible defaults
  -   *Automatic initramfs rebuild*: Detects driver/kernel changes that need initramfs updates, validates disk space, and offers safe rebuild across all major distros
  -   *Full backup system*: Tagged, timestamped backups with easy restore and comparison, pruned automatically to the newest 24
  -   *Lightweight TUI*: Works everywhere—local, SSH, or minimal environments
  -   *Respects existing config*: Unknown parameters are preserved with minimal validation

* **How It Works**
  -   Back up first: on startup, GRUB's current defaults are backed up (tagged and checksummed) if they are unique
  -   Edit with guidance: Choose from presets or edit with validation
  -   Review with checks: See warnings and fix issues before writing
  -   Write safely: validate the candidate, install it atomically, then run update-grub; a failed update rolls the file back and regenerates grub.cfg from it
  -   Restore if needed: version history with diff comparison

`grub-wiz` focuses on the 95% of common GRUB configuration tasks, making them safe and simple while preserving your existing customizations.

#### Installation and Running is Easy

* `grub-wiz` is available on PyPI and installed via: `pipx install grub-wiz`
* Typically, just run `grub-wiz` w/o arguments
* **Note**: `grub-wiz` makes itself root using `sudo` and will prompt for password if needed.
* **Getting Help**:
  * In the app: Press `?` to view navigation keys and other key assignments
  * From terminal: Run `grub-wiz --help` to see command-line options

>⚠️ **Distro-Specific Caveats**: Linux distributions often layer their opinions atop of the standard GRUB configuration. While `grub-wiz` ensures your `/etc/default/grub` is valid and safe, distros may ignore your settings (e.g., in pursuit of "Hidden Menu" or "Flicker-free" features).
>* **Fedora Users**: Fedora uses an environment block (`grubenv`) that can override your timeout settings. If your menu is still hidden after using `grub-wiz`, you may need to run: `sudo grub2-editenv - unset menu_auto_hide`
>* **General Tip**: If your changes are ineffective, check if your distro uses specialized tools like `grub2-editenv`, `systemd-boot`, or has specific "fast-boot" logic enabled in the BIOS/UEFI.
---
#### How to Use grub-wiz
##### EDIT SCREEN
Running `grub-wiz` brings a screen similar to:
```
 EDIT  [g]uide=Off  [w]rite-grub    [R]estore [W]arnCfg ?:help [q]uit  𝚫=0
 [s]how-all-params(22-inact)  ⮜–⮞ [e]dit x:deact
─────────────────────────────────────────────────────────────────────────────────────────────
 [Boot Timeout]
>  TIMEOUT·················  5                                                               
   TIMEOUT_STYLE···········  menu
   RECORDFAIL_TIMEOUT······  2

 [Kernel Arguments]
   CMDLINE_LINUX···········  ""
   CMDLINE_LINUX_DEFAULT···  ""

 [Visual Appearance]
   DISTRIBUTOR·············  'Kubuntu'
```
NOTES:
* `grub-wiz` is only showing "active" parameters (the uncommented ones in the grub file); to add parameters, see them all with the `s` key. The parameters that are inactive will be marked with an `✘`.
* In the header, `⮜–⮞` indicates you can cycle through a list of values with the right/left arrow keys.
* Also, `[e]dit` indicates you can type `e` to free-style edit the parameter; in that case, your change will be checked with a regular expression and you must make it conform. The value is typed on a line right under that parameter — `⚠️ Edit value, then ENTER or ESC: 5│` — so the old value stays on screen while you edit it (`←`/`→` move the caret, `ENTER` applies, `ESC` cancels). A dim line below says what the value may be (`-1 for infinite, 0 or positive integer`), so the prompt itself stays short; an answer that fails the check leaves the text in place with the prompt changed to `⚠️ Re-edit value, then ENTER or ESC`. `E` runs the same editor in expert mode, with minimal checks. Only the few long parameters (`GRUB_CMDLINE_LINUX`, `GRUB_CMDLINE_LINUX_DEFAULT`, …) still open a full-screen dialog, because several rows of text do not fit on one line.
* When you done editing, then type `w` to write the parameter after you **review** them.
* Edits are held in memory until you write them, so leaving with `q` **or Ctrl-C** asks before discarding them (on the RESTORE screen either key just goes back one screen).
* For editing the `CMDLINE` parameters, see "Essential Linux Kernel Parameters (GRUB Arguments)" in the Appendix.

##### REVIEW SCREEN AND WRITING/UPDATING GRUB
The next step in updating the `grub` configuration is the REVIEW screen:
```
 REVIEW  [g]uide=Off  [w]rite-grub    ESC:back [W]arnCfg ?:help [q]uit  𝚫=4
                               ⮜–⮞ [e]dit x:deact [u]ndo
───────────────────────────────────────────────────────────────────────────────────────
   TIMEOUT···················  0
                  └───   🟌🟌🟌🟌  when 0, TIMEOUT_STYLE cannot be "hidden"
   TIMEOUT_STYLE·············  hidden
                  └───   🟌🟌🟌🟌  when "hidden", TIMEOUT cannot be 0
   RECORDFAIL_TIMEOUT········  200
                └──────── was  ≡
                  └───      🟌  over 120s seems ill advised
   CMDLINE_LINUX·············  "splash"
                └──────── was  ""
                  └───    🟌🟌🟌  splash/quiet/rhgb belong only in CMDLINE_LINUX_DEFAULT
>  CMDLINE_LINUX_DEFAULT·····  ""                                                      
                └──────── was  "quiet splash"
   DISTRIBUTOR···············  'Kubuntu'
                └──────── was  `lsb_release -i -s 2> /dev/null || echo Debian`
```
NOTES:
* The review screen shows parameters that you have changed and parameters that have warnings.
* On this screen, you may edit parameter values just as on the EDIT screen if the parameter is shown.
* Warnings are be dismissed by fixing the values or by inhibiting the warning (with the `x` key).
* If you inhibit warnings, they remain suppressed in future sessions until allowed.
* Lines on this screen and others that end with `▶` are truncated. To see the rest of the text, visit that line.
* When done with your review, type `w` again to finally write the `grub` file and run `update-grub`.  The confirmation appears inline as a header line (`⚠️ Commit changes and update GRUB  [Press "y" or ESC]`), so the review stays visible: press `y` to commit, or `ESC` to cancel. **After this succeeds**, `grub-wiz` performs intelligent safety checks:

**Automatic Initramfs Rebuild Detection** (Major Safety Feature)

If you've changed kernel command-line arguments that affect early boot (GPU drivers, kernel mode setting, module loading, encryption, etc.), `grub-wiz` will:

1. **Detect the need**: Checks if changes to `GRUB_CMDLINE_LINUX`, `GRUB_CMDLINE_LINUX_DEFAULT`, or `GRUB_CMDLINE_LINUX_RECOVERY` contain triggers like:
   - GPU drivers: `i915`, `nvidia`, `nouveau`, `amdgpu`, `radeon`
   - Kernel mode setting: `nomodeset`, `modeset`
   - Module control: `module_blacklist`, `rd.driver`
   - Root filesystem: `root=`, `rootflags`, `rootfstype`
   - Encryption/LVM: `rd.luks`, `rd.lvm`, `cryptdevice`
   - And more (see full list in config)

2. **Check disk space**: Calculates space needed based on your existing initramfs files:
   - Needs ≈ 2× current size (new files created before deleting old ones)
   - **CRITICAL safety**: Blocks rebuild if insufficient space (prevents bricking your system!)
   - Example: 229MB of initramfs → needs ~508MB, you have 591GB ✓

3. **Prompt intelligently**:
   ```
   ⚠️  Gpu Drivers changes detected ('nvidia').
   Rebuilding initramfs ensures driver/module changes take effect at early boot.

   Disk space check: OK: 591468MB free in /boot (need ~507MB, surplus: 590961MB)

   Rebuild initramfs now? [y/N]:
   ```

4. **Execute safely**: Runs the distribution-appropriate command:
   - Debian/Ubuntu: `update-initramfs -u -k all`
   - RHEL/Fedora: `dracut --regenerate-all --force`
   - Arch: `mkinitcpio -P`
   - Alpine: `mkinitfs`
   - Gentoo: `genkernel --install initramfs`

**Why This Matters**: Many kernel parameter changes (especially GPU drivers, `nomodeset`, module blacklisting) require initramfs rebuild to take effect. Without it, your changes may not work, or worse, your system may fail to boot. `grub-wiz` prevents this common pitfall automatically.

After the optional initramfs rebuild, you will be given the choice to reboot, poweroff, or return to `grub-wiz`.

##### GUIDANCE LEVELS AND HEADER HINTS
* *Header Hints*: On the EDIT screen, `R` opens the RESTORE screen (to manage backups) and `W` opens the WARNINGS-CONFIG screen (to inhibit and allow warnings selectively).  On REVIEW, only `W` is shown: restoring a backup while reviewing would replace the configuration underneath the review, so RESTORE is intentionally available only from EDIT.  Press `?` for the complete key list.
* *Header Style*: Typing `f` cycles the header style between Underline, Reverse, and Off.
* *Guidance Levels*: Typing `g` on the EDIT and REVIEW screens cycles through its possible values, None, Enums, and Full.  Full guidance for the `DISABLE_OS_PROBER` parameter is shown below.
```
 REVIEW  [g]uide=Full  [w]rite-grub    ESC:back [W]arnCfg ?:help [q]uit  𝚫=3
                             ⮜–⮞ undo
──────────────────────────────────────────────────────────────────────────────
>  DISABLE_OS_PROBER·······  false                                            
              └──────── was  ∎
                └───      *  perhaps set "true" since no multi-boot detected?
    ╭Setting to 'true' prevents GRUB from automatically scanning other
    │     partitions for installed operating systems (like Windows, other
    │     Linux distros) and adding them to the boot menu.
    │: ⮜–⮞ :
    │  ⯀ false: Search for and automatically add other operating systems to
    │     the menu.
    ╰  🞏 true: Do not search for other operating systems.
```

##### RESTORE SCREEN
When you enter the restore screen by typing `R` from the EDIT screen, it looks something like:
```
 RESTORE [r]estore [d]el [t]ag [v]iew [c]mp [b]aseline    ESC:back ?:help [q]uit
───────────────────────────────────────────────────────────────────────────────────
>●     20261025-083036-s559DCA.~Timeout+1.bak
        ⚠️ Edit tag, then ENTER or ESC: ~Timeout+1│
       20261025-074512-s559DCA.BASELINE.bak
       20261024-221007-s0A91E4.~Theme.bak
   CMP 20261024-190231-s0A91E4.RESYNC.bak
```
The second line is what pressing `t` looks like: the prompt is drawn under the row being renamed, seeded with the current tag and edited in place (`←`/`→` move the caret, `ENTER` applies, `ESC` cancels). `[r]estore` and `[d]el` use the same place, asking one-key questions there instead of replacing the screen with a dialog: `⚠️ Restore GRUB source from …  [Press "y" or ESC]` and `⚠️ Delete …  [Press "y" or ESC]`. Nothing is written or removed until `y` is pressed, and `ESC` leaves the backup untouched.

*Backup and restore features*:
 - the leading `●` indicates it is the backup for the current session.
 - backups of `/etc/default/grub` are stored in `~/.config/grub-wiz` (mode `0700`; only your user can read them)
 - backups are named `YYYYMMDD-HHMMSS-s{6-hex-checksum}.{tag}.bak` and are listed newest first. The timestamp is the primary clue; the tag is a hint that is filled in automatically, so committing never asks you to name a backup. Only the explicit `[t]ag` action renames one.
 - `BASELINE` is the only backup taken at start-up: it is written once, when the backup directory is still empty. Starting grub-wiz writes nothing else — a backup is created when grub-wiz *changes* grub, so a hand edit or a package update between sessions is not snapshotted. `RESYNC` means grub-wiz updated GRUB while REVIEW had nothing to report; only one `RESYNC` per content is kept, because a new one deletes the `RESYNC` standing next to it. A name with **no tag at all** means a commit whose diff could not be classified (for example a parameter moved between "commented out" and "deleted").
 - a written change is tagged `+` (a parameter was activated), `-` (a parameter was commented out) or `~` (only values changed), followed by an abbreviated parameter name and `+N` when more than one parameter moved. For example `~Timeout+1` means two parameters changed and `Timeout` is the first of them.
 - identical content is otherwise kept; two different states may hold the same bytes, and one of them disappearing would lose history.
 - the inventory is capped at **24** files. At start-up, while there are more than 24, grub-wiz deletes from the oldest end and stops as soon as it is back to 24. Two records are privileged: the oldest one is never removed (it is the earliest state you can return to), and when the oldest removable record carries a descriptive tag and the record immediately after it holds the same bytes and is a `RESYNC`, that `RESYNC` goes instead — so the tag that says *what* changed survives. Only adjacent records are compared.
 - the order is the filename, so the timestamp decides; a file's modification time is deliberately ignored (a bulk copy rewrites it). A summary such as `Purge: 27 -> 24 backups.` is printed before the screens open. `grub-wiz -k` (or `--keep-all-bak`) keeps every backup and skips the purge for that launch.
 - files written by older versions (`YYYYMMDD-HHMMSS-{8-hex}.{tag}.bak`) stay visible, restorable and renameable, and take part in the purge like any other.
 - tags use `[-_+~A-Za-z0-9]` characters (spaces are converted to "-"); press `t` on the RESTORE screen to rename one. The new tag is typed inline under that backup's row (no dialog replaces the screen), and a rejected tag is asked for again with the bad text still editable. A rename that cannot happen — the tag is already taken, or the file cannot be moved — is reported on the status line (the row above the divider, where the scroll indicator lives) for a few seconds rather than in a dialog, so the listing and the name that collided stay visible.
 - if a backup is restored, `grub-wiz` re-initializes using the restored grub file and returns to the main screen. **Restore is intentionally a two-step operation:** it replaces `/etc/default/grub` but does *not* regenerate `grub.cfg`. The restored values become active only when you write from the main screen, which runs the normal atomic write and `update-grub` path. This lets you restore an older configuration as a baseline for further edits without changing the current boot menu in the middle of the session.
 - the `[v]iew` action bring up the VIEW screen to peruse the selected `.bak` file.
 - the `[c]mp` action compares the selected `.bak` to the `CMP` (or baseline) `.bak`, and you can set the `baseline` with the `[b]aseline` action. And example the COMPARE screen is below.  As you can see, it just show the parameter values difference, not different comments or blank lines or whatnot.
```
COMPARE   ESC:back
< 20261025-074512-s559DCA.BASELINE.bak [#lines=44]
> 20261024-190231-s0A91E4.RESYNC.bak [#lines=39]
───────────────────────────────────────────────────────────────────────────────────

< GRUB_RECORDFAIL_TIMEOUT=2
>

< GRUB_TIMEOUT=2
> GRUB_TIMEOUT=0

< GRUB_TIMEOUT_STYLE=menu
> GRUB_TIMEOUT_STYLE=hidden

```
##### WARNINGS CONFIGURATION SCREEN
Finally, we show the Warnings Configuration Screen.  Here is a short snippet:
```
 WARNINGS-CONFIG   x:inhibit-warning   /   ESC=back quit
───────────────────────────────────────────────────────────────────────────────────
 [ ]   ** BACKGROUND: path does not seem to exist
>[ ]  *** CMDLINE_LINUX: "quiet" belongs only in CMDLINE_LINUX_DEFAULT             
 [ ]  ***                "splash" belongs only in CMDLINE_LINUX_DEFAULT
 [X]   **                has spaces and thus must be quoted
 [ ]  ***                no "rd.luks.uuid=" but LUKS seems active
 [ ]  ***                no "rd.lvm.vg=" but LVM seems active
 [ ]   ** CMDLINE_LINUX_DEFAULT: has spaces and thus must be quoted
           ...
```
Every possible warning (currently about 50) is shown on the Warning Configuration Screen. You can inhibit and allow warnings as you please. More often, you probably will inhibit/allow warnings on the Review Screen as they arise and you wish to dismiss it.

---
#### Files, State, and Residue

`grub-wiz` runs as root but keeps two kinds of state apart: files that belong to the user who invoked `sudo`, and machine-wide files that only root may change. This split is what prevents a local user from redirecting a root write with a pre-created symlink.

*User-facing state* — `~/.config/grub-wiz/` (mode `0700`, owned by the invoking user):

| Path | Purpose | Safe to delete? |
|---|---|---|
| `*.bak` | Backups of `/etc/default/grub` (tag optional, newest 24 kept) | Yes (loses restore/compare history) |
| `warn-db.yaml` | Inhibited/allowed warnings and severities | Yes (resets warning preferences) |
| `custom_config.yaml` | Your optional custom parameter definitions | Keep |
| `canned_config.yaml` | Reference template for the custom-config workflow | Yes (recreated on the next start) |

*Root-owned system state* — never writable by a normal user:

| Path | Purpose | Safe to delete? |
|---|---|---|
| `/var/lib/grub-wiz/system-params.yaml` | Cached `info grub` parameter discovery (machine-wide) | Yes (regenerated; `--factory-reset` deletes it) |
| `/var/lib/grub-wiz/last-known-good.grub` | Rollback copy of `/etc/default/grub` from the last commit | Yes (used only for rollback during a commit) |
| `/run/grub-wiz/` | Reserved for per-session scratch and locks; cleared at boot | Yes |
| `/etc/default/.grub-wiz-*` | Transient commit staging file next to the target | Yes (removed automatically) |

Notes:
- State that must survive a reboot lives in `/var/lib`; state that does not lives in `/run`.
- `sudo` is required to inspect or remove the root-owned system state.
- Writes into `~/.config/grub-wiz` are atomic and never follow symlinks. The commit candidate is staged next to `/etc/default/grub` so the final rename is atomic, and it is removed whether the commit succeeds or fails.
- Nothing is written to `/tmp`; no lock or cache files are left behind.
- `grub-wiz --factory-reset` deletes the discovery cache and the warning database, but preserves `*.bak` backups.
- Start-up pruning keeps at most 24 backups and always keeps the oldest; `grub-wiz -k` skips it for that launch.
- Restoring a backup is refused if it is a symlink, contains NUL bytes, or contains shell command substitution (a backtick or `$(`). This prevents a crafted backup from executing as root when the distro sources `/etc/default/grub`.

---

#### Startup Config/Menu Sync Check

`/etc/default/grub` is only *installed* once `update-grub` (or `grub-mkconfig`) has regenerated `grub.cfg` from it. Before the screens open, grub-wiz compares their modification times and prints both timestamps:

- `/etc/default/grub` newer than `grub.cfg` — the generated menu does not reflect the defaults file yet. This happens after a hand edit, or after a restore, which deliberately does not regenerate the menu. grub-wiz asks `Continue? [Y/n]`; Enter continues and `n` aborts.
- `grub.cfg` more than four hours newer — printed as a note instead of a prompt. This is the normal result of a kernel or GRUB package update. It is only worth investigating if `/etc/default/grub` was replaced from a backup with its old timestamp preserved.
- Differences of a second or less, or a generated file less than four hours newer, are treated as in sync and print nothing.

The check is skipped when `grub.cfg` is missing (already reported as crippled mode), and it never runs in the `--discovery`, `--factory-reset`, `--validate-custom-config` or `--validator-demo` modes. Timestamps are a heuristic: `cp -p`, `tar`, a restored config directory or a clock change can mislead them.

---
#### Parameter Discovery and Excluded Parameters
Because GRUB can vary per system, `grub-wiz` uses `info -f grub -n "Simple Configuration"` to discover which parameters are actually supported. Parameters not found on your system are automatically removed by `grub-wiz` from its screens so that you do not add it from the confusion. Discovery runs automatically at startup whenever the cache is missing (for example on a fresh install) or older than one week, so the filtering is never decided by a missing or stale cache. Notes:
- We recommend installing GRUB documentation for best results:
    - Ubuntu/Debian: `sudo apt install grub-doc`
    - Fedora/RHEL: `sudo dnf install grub2-common`
- If `info` provides inaccurate results, you can disable discovery:
    - `grub-wiz --discovery=disable` (use "enable" or "show" for other actions)
- Discovery results are cached machine-wide in `/var/lib/grub-wiz/system-params.yaml`
- If discovery fails because the documentation is not installed, `grub-wiz` keeps all parameters visible and retries on the next start. Installing `grub-doc` and restarting (or running `python -m grub_wiz.ParamDiscovery --regenerate`) refreshes the cache.


`grub-wiz` focuses on common configuration tasks. You may have specialized needs such as:

- **Xen virtualization**: GRUB_CMDLINE_XEN, GRUB_CMDLINE_XEN_DEFAULT
- **Debug output**: GRUB_ENABLE_BLSCFG, GRUB_DEBUG
- **Early initrd**: GRUB_EARLY_INITRD_LINUX*

If so, add these manually to `/etc/default/grub`; then, `grub-wiz` will recognize and preserve them (but with limited validation and no cross-checks).

#### Custom Parameter Configuration (Advanced)

For advanced users who need to modify parameter definitions:

1. grub-wiz creates `~/.config/grub-wiz/canned_config.yaml` as a template
2. Copy it to `~/.config/grub-wiz/custom_config.yaml`
3. Edit as needed (add params, modify validation regex, change guidance, etc.)
4. Restart `grub-wiz` - it will use your custom config if valid

**Notes:**
- Invalid YAML or schema errors fall back to packaged config with a warning
- Use `grub-wiz --validate-custom-config` to test your changes: it reports which config is in use, prints `OK` and exits 0 when your custom config was accepted, and prints `FAIL` and exits nonzero when `grub-wiz` fell back to the packaged config
- Top-level sections beginning with `_` (`_distro_vars_`, `_re_specs_`, `_update_initramfs_triggers_`) are reserved metadata. Keep them when copying the template: `_distro_vars_` tells `grub-wiz` where to find `/etc/default/grub` and the update commands.
- Each `GRUB_*` entry requires `default`, `edit_re`, `enums`, and `guidance`. `edit_re_human` is generated at runtime from `_re_specs_`; do not add it.
- Values are written into `/etc/default/grub`, which is sourced as a shell script, so a value with spaces or shell metacharacters must be quoted (for example `"quiet splash"`). Plain values such as `1024x768,auto` need no quotes. Command substitution is refused unless the regex spec in `_re_specs_` sets `allow_command_sub: true`; only `re_quoted_or_command_sub` (used by `GRUB_DISTRIBUTOR`) does so in the packaged template.
- Consider submitting useful additions as GitHub issues/PRs!

---
---
---

## Appendix: Additional Topics

#### GRUB File Parsing and Rewriting Rules

When `grub-wiz` reads and writes `/etc/default/grub`, it follows specific rules to ensure compatibility and safety. Understanding these rules helps you avoid patterns that could cause issues.

##### ✅ Supported Patterns

**Standard Parameter Assignments**
```bash
GRUB_TIMEOUT=5
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"
GRUB_DEFAULT=0
```
These are read, managed, and written back correctly.

**Backslash Continuation Lines**
```bash
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash \
nvidia-drm.modeset=1 \
acpi_backlight=vendor \
intel_pstate=disable"
```
- Continuation lines are automatically joined during reading
- Written back as a single line: `GRUB_CMDLINE_LINUX_DEFAULT="quiet splash nvidia-drm.modeset=1 acpi_backlight=vendor intel_pstate=disable"`
- **Requirements**:
  - Value must be double-quoted (not single quotes or unquoted)
  - Each line except the last must end with `\` immediately before the newline
  - Works with both commented and uncommented parameters

**Commented Parameters**
```bash
# This parameter is disabled
#GRUB_DISABLE_RECOVERY=true
```
- Tracked with special internal value (shown as `∎` in param data)
- Can be uncommented and given a value through the UI
- Commented continuations are also supported (each line must start with `#`)

##### ⛔ Blacklisted Patterns (Passthrough Only)

`grub-wiz` detects but **does not manage** parameters using shell variable expansion. These patterns require shell interpretation and are preserved exactly as written but excluded from the UI:

**Variable Self-Reference**
```bash
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"
GRUB_CMDLINE_LINUX_DEFAULT="${GRUB_CMDLINE_LINUX_DEFAULT} extra_option"
```
- **Both lines** are blacklisted and passed through unchanged
- The parameter `GRUB_CMDLINE_LINUX_DEFAULT` will not appear in the UI

**Variable Cross-Reference**
```bash
GRUB_TIMEOUT=5
GRUB_FOO="timeout is $GRUB_TIMEOUT seconds"
```
- Only `GRUB_FOO` is blacklisted (uses expansion, can't predict final value)
- `GRUB_TIMEOUT` remains editable in the UI
- Changes to `GRUB_TIMEOUT` through `grub-wiz` will be picked up by `GRUB_FOO` when the file is sourced
- `GRUB_FOO` is written back exactly as found

**Why Blacklist Variable Expansion?**
- Parameters using `$VAR` or `${VAR}` require shell evaluation at runtime
- `grub-wiz` cannot reliably predict or validate their final expanded values
- Attempting to manage these could corrupt complex scripting logic
- Referenced parameters (like `GRUB_TIMEOUT` above) remain fully editable - changes propagate when the file is sourced by GRUB

##### 📝 Best Practices for Manual Editing

**DO:**
- ✅ Use double quotes for values with spaces or special characters
- ✅ Use continuation lines (with `\`) for very long parameter values
- ✅ Add comments above parameters for documentation
- ✅ Keep it simple - one assignment per parameter

**DON'T:**
- ❌ Use variable expansion (`$VAR` or `${VAR}`) if you want `grub-wiz` to manage the parameter
- ❌ Mix quoted and unquoted values in continuation lines
- ❌ Put `#` comments in the middle of continuation sequences
- ❌ Use single quotes with backslash continuations (shell doesn't expand `\` in single quotes)

##### 🔍 How to Check if a Parameter is Blacklisted

If a parameter you expect to see doesn't appear in `grub-wiz`:
1. Check `/etc/default/grub` for variable expansion (`$` or `${...}`)
2. Simplify to a direct assignment: `GRUB_PARAM="value"` instead of `GRUB_PARAM="${OTHER} value"`
3. Restart `grub-wiz` - the parameter should now appear

##### 📌 Parameter Discovery

Parameters that don't exist on your system (per `info grub`) are also excluded from the UI but preserved in the file. See **Parameter Discovery and Excluded Parameters** section for details.

---

#### Running grub-wiz at recovery time

To leverage user-installed, `grub-wiz` even in minimal recovery environment of grub recovery mode:
1. Remount the root filesystem as Read-Write: `mount -o remount,rw /`
2. Execute grub-wiz using its full path: `/home/{username}/.local/bin/grub-wiz`
3. Make changes as needed, and "write" them to update the boot instructions.

---

#### Essential Linux Kernel Parameters (GRUB Arguments)

These are the arguments that get passed directly to the Linux kernel during the boot process.
Parameter	Purpose & When to Use It	Example Use Case

* **quiet**
  * Boot Output Control: Suppresses most kernel startup messages, making the boot process appear cleaner and faster (often used with splash).
  * Default setting on most consumer distributions.
* **splash**
  * Visual Boot: Tells the kernel to display a graphical boot screen (e.g., the Ubuntu or Fedora logo) instead of raw text output.
  * Default setting for an aesthetic desktop experience.
* **nomodeset**
  * Graphics Troubleshooting: Crucial for fixing black screens or corrupted graphics.
  * It forces the kernel to skip loading video drivers and use basic VESA graphics initially, often allowing you to boot into the desktop to install proper proprietary drivers.	Use when the system freezes or shows a black screen after kernel loading.
* **init=/bin/bash**
  * Emergency Shell: Replaces the standard /sbin/init or /usr/lib/systemd/systemd process with a simple Bash shell, giving you immediate root access to the system for repair.
  * Use when you forget your root password or the system fails to boot into runlevels.
* **ro** or **rw**
  * Root Filesystem Mode: ro mounts the root filesystem as Read-Only initially (standard for safety, as the initramfs will remount it rw later). rw forces it to mount Read-Write immediately.
  * `ro` is the safer, common default. Change to rw only if explicitly needed for early-boot modifications.
* **single** or **1**
  * Single-User Mode (Rescue): Boots the system to a minimal state, usually without networking or graphical interfaces, often requiring the root password.
  * This is ideal for system maintenance.	Use for maintenance or recovery, especially when networking or services are causing issues.
* **systemd.unit=multi-user.target**
  * Bypass Graphical Login: Forces the system to boot to a command-line terminal login instead of the graphical desktop (skipping graphical.target).
  * Use when GUI problems prevent login or you want a server-like environment.
* **noapic** or **acpi=off**
  * Hardware Compatibility (Legacy): Disables the Advanced Programmable Interrupt Controller (noapic) or the Advanced Configuration and Power Interface (acpi=off).
  * These are extreme measures for very old or extremely non-compliant hardware that hangs during boot.	Use as a last resort when the kernel hangs while initializing hardware components.
* **rhgb**
  * Red Hat Graphical Boot: Similar to splash, but specifically used by Red Hat/Fedora systems to control their graphical boot experience.
  * Used primarily on RHEL, CentOS, or Fedora distributions.


The authoritative source for all kernel command-line parameters is the official Linux kernel documentation. Since parameters can change between major kernel versions, this is always the best place to check for advanced or very specific options:

Official Linux Kernel Documentation (Current): Search for the `kernel-parameters.rst` document in the official kernel git repository. A common link to this documentation is the `kernel-command-line(7)` manual page, which is linked to the online documentation.

---

## Future Feature Considerations

#### Sparse Override Feature
* Effort: Medium-high
* Value: High - best UX This is the most powerful and user-friendly:

###### ~/.config/grub-wiz/custom_config.yaml
```
##########     NOTE: this is FOR DISCUSSION (NOT IMPLEMENTED)  ################
schema_version: "1.0"  # Must match canned_config

# Permanently exclude parameters (stricter than WizHider)
killed_params:
  - GRUB_BADRAM        # Never show, even in "show all"
  - GRUB_INIT_TUNE     # Don't care about beeps

# Override specific parameter configs
overrides:
  GRUB_TIMEOUT:
    # Only override what you want - rest inherited from canned
    enums:
      0: no wait
      3: short (my preference)
      10: normal (my preference)
      30: long (my preference)

  GRUB_GFXMODE:
    hide: False  # Make visible by default (was True in canned)

  GRUB_CMDLINE_LINUX:
    guidance: "Custom help text for my specific use case..."

# Add custom parameters
user_params:
  GRUB_MY_CUSTOM_FLAG:
    default: '""'
    edit_re: ^".*"$
    guidance: "My organization's custom kernel parameter"
    hide: False
```

###### Implementation notes for Sparse Override Feature:
* Schema version check - ignore custom_config if version mismatches (safe)
* killed_params vs WizHider - different purposes:
* WizHider: Runtime user preferences (hide/unhide in UI)
* killed_params: Admin decision "never expose this parameter"
* Merge strategy: canned → apply overrides → add user_params
* Updates safe: Changes to canned_config automatically flow through (unless overridden)