# grub-wiz GIF demo script

A tightly paced take of the features that are hard to explain in prose.
Target length: **75–85 seconds** of action, plus however long `update-grub`
takes on the demo machine.

> **Safety first:** `grub-wiz` runs as root and writes `/etc/default/grub`.
> The full take below also runs `update-grub`. Use a disposable VM or a VM
> snapshot. Do not record this on a machine whose boot configuration you care
> about.

## Before you record

- Resize the terminal to about **80x24** (the app needs at least 70x10).
- Use a font that can draw `⮜ ⮞ ✘ ● 🟌 ⚠️`
- Ensure passwordless `sudo`
- Capture tool: `keep`

## The take (in "shorthand")
  - `clear; ./runner --factory reset; ./runner`
  - [K]show-keys
  - [T]hemeScreen, [t]heme... until "gruvbox"
  - `Keep` app: start-recording
  - EDIT screen:
    - [e]dit TIMEOUT to "29"
    - [s]how-all-params, [/]recov
    - on DISABLE_RECOVERY [g] [g] -> "true" [g]
    - [s]hide-hidden-params
    - [w]rite-grub
  - REVIEW screen
    - <-> TIMEOUT to -1, [x]inhibit-warning
    - [w]rite-grub
  - [R]ecovery -> RECOVERY screen
    - [t]ag "DEMO"
    - [c]mp changes
    - [r]estore BASELINE
    - [w], [w]rite-grub
  DONE
  - [R]ecovery -> RECOVERY screen
    - [d]elete DEMO backup