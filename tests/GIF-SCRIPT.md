# grub-wiz GIF demo script

A tightly paced take of the features that are hard to explain in prose.
Target length: **75–85 seconds** of action, plus however long `update-grub`
takes on the demo machine.

> **Safety first:** `grub-wiz` runs as root and writes `/etc/default/grub`.
> The full take below also runs `update-grub`. Use a disposable VM or a VM
> snapshot. Do not record this on a machine whose boot configuration you care
> about.

## Before you record

- Use a disposable VM or take a snapshot now.
- Resize the terminal to about **80x24** (the app needs at least 70x10).
- Use a font that can draw `⮜ ⮞ ✘ ● 🟌 ⚠️`; otherwise the GIF will show boxes.
- Make sure `~/.config/grub-wiz` is in a known state. On a fresh VM the
      first launch creates the `BASELINE` backup, which the RESTORE beat uses
      as the comparison reference.
- Prefer passwordless `sudo` (or a root shell in the VM) so the recording
      never contains a password prompt.
- Capture tool: `asciinema` + `agg` is the simplest path.
- Reset between takes
  - Use `grub-wiz --factory-reset` only if you also want to clear the warning
        database and the discovery cache. It intentionally keeps `.bak` files.
  - Start `grub-wiz`, press `[R]estore` and `[r]estore` the `BASELINE` backup
    - optionally, remove all the backups, too
  - Press `ESC` back to `EDIT`, then `[w]rite-grub` to complete restore.

Start the recorder **before** launching the TUI if you use `asciinema`
(it records the shell it starts), or launch the TUI first and use an external
window recorder such as Peek/OBS.

```sh
# asciinema route: start recording, then launch inside it
asciinema rec -i 1 --overwrite grub-wiz-demo.cast
grub-wiz          # or: python3 runner
```

## The take

- **[START]** Let the `EDIT` screen settle.
    * Navigate to `TIMOUT`

- **[EDIT]** On `TIMEOUT`, press `[e]dit`
    * Change value to 29.

- **[EDIT]** Press [s]show-all-params.
    * Expected: the inactive rows are marked `✘`.

- **[EDIT]** Press `/`, type `RECOVERY` + `Enter`.
    * Expected: the filters reduces the list.

- **[EDIT]** On `DISABLE_RECOVERY`, press `→` until the value is `true`.
    * Expected: `⮜–⮞` and `x:deact` appear in the header; `𝚫=2`.

- **[EDIT]** Press `s` again to hide inactive parameters.
    * The search filter stops being applied, so the screen is clean again.

- **[EDIT]** On `DISABLE_RECOVERY`,
    * press `[g]uide` for `→ Enums` and hold 2s
    * press `[g]uide` for `→ Full` and hold 2s
    * press `[g]uide` for `→ Off` and hold 2s
    * Expected: with guidance on, it show enum descriptions and
      the `⮜–⮞` key hint.

- **[EDIT → REVIEW]** Press `[w]rite`. Expected: the `REVIEW` screen lists:
    * `TIMEOUT` with its `was` line and
    * `DISABLE_RECOVERY` with its `was false` line.
    * The header shows `𝚫=2`.
     

- **[REVIEW]** Navigate to top review row, then:
    * press `[g]uide` for `→ Enums`
    * press `[g]uide` for `→ Full`
    * press `[g]uide` for `→ Off`
    * Expected: with guidance on, it show enum descriptions and the `⮜–⮞` key hint.

- **[REVIEW]** Press `[w]write`.
    * Expected: the confirmation promp `⚠️  Commit changes?...  ⚠️`.

- **[COMMIT]** Press `y`.
    * Expected: curses stops, the screen prints the commit/update messages and
      runs `update-grub`.
    * If an initramfs rebuild prompt appears, answer `n`
      (not expected for timeout/recovery changes).
    * When the `[r]eboot / ... / ENTER` appears, press `Enter` to return to TUI.

- **[RESTORE]** From refreshed `EDIT` screen, press `[R]estore`.
    * Expected: the new backup is at the top with the `●` current marker and an
      automatic tag such as `~Timeout+1`.

- **[COMPARE]** Press `c` to compare recent commit with `BASELINE`/`CMP` reference.
    * Expected: only the value differences are shown, not comments or blank
      lines.

- **[EXIT]** Press `ESC` back to `RESTORE`, `ESC` back to `EDIT`, then `q`.
      Expected: no “discard unapplied changes?” prompt, because the commit
      cleared the diff.

## Optional beats (choose one or two, not all)

- **A warning that always exists:** on `EDIT`, press `s` if the row is
      hidden and `x` if `RECORDFAIL_TIMEOUT` is inactive, then press `e`, set
      it to `200`, press `Enter`; then `w` to REVIEW. Select the `🟌` warning,
      press `x` to inhibit it, then `s` to reveal it again.
- **WARNINGS-CONFIG screen:** from `EDIT` or `REVIEW`, press `W`; press `/`
      and type `TIMEOUT`; press `x` on one warning; press `ESC` to go back.
     
- **Help screen:** press `?`, hold for a beat, press `ESC`.
- **Header style:** press `f` to cycle Underline / Reverse / Off.
- **Expert edit:** press `E` on the selected value, make a small change,
      press `Enter`.
- **View a backup:** on `RESTORE`, press `v`; `ESC` returns.
- **Retag a backup:** on `RESTORE`, press `t`, type a short tag, press
      `Enter`.

## Key facts that bite

- `[R]estore` is uppercase and is available only from `EDIT`.
- `[W]arnCfg` is uppercase and is available from `EDIT` and `REVIEW`.
- `s` means “show inactive parameters” on `EDIT`, but “show inhibited
  warnings” on `REVIEW`.
- `x` means “activate/deactivate the selected parameter” on `EDIT`. On
  `REVIEW`, `x` on a warning row inhibits/allows that warning, and `x` on a
  parameter row deactivates that parameter. On `WARNINGS-CONFIG`, `x`
  inhibits/allows the selected warning.
- `g` cycles `Off → Enums → Full → Off`.
- `←`/`→` cycle enumerated values. `→` on a commented-out parameter first
  activates it with the first enum value. For `DISABLE_RECOVERY` (enums
  `false`, `true`), `x` while it shows `✘` then one `→` is the predictable
  path; if it is already active, skip `x` and just press `→`.
- `q` quits immediately when there are no pending edits. With pending edits it
  asks you to type `yes`; `Enter` or `ESC` keeps the session.
- Restore is intentionally two-step: `R` → `r` replaces `/etc/default/grub`,
  but `grub.cfg` is regenerated only when you later press `w` on `REVIEW`.
- The commit backup tag is automatic; the app never asks you to name a backup.
  `~Timeout+1` means a value-only change where `Timeout` is the first changed
  parameter and one more parameter changed too.


## Render the GIF

```sh
# stop the asciinema recording with exit or Ctrl-D, then:
agg --font-size 16 --speed 1.2 grub-wiz-demo.cast grub-wiz-demo.gif
```

Trim the sudo/startup frames and any long `update-grub` output; the UI beats
are the point of the GIF.
