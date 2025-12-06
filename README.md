>  **This project is very early in development ... come back later.**

## GrubPal: The Friendly GRUB Bootloader Assistant

A safe, simple, and reliable Text User Interface (TUI) utility for managing the most common GRUB bootloader configuration tasks on Linux systems.

GrubPal provides the ease-of-use of a graphical configurator without the dependency bloat or the reputation for complex, destructive changes. It operates strictly on configuration files, making safe backups before every change.

#### Why Use GrubPal?

Dealing with `/etc/default/grub` and running `update-grub` manually is tedious and prone to typos. Other visual configurators often make overly aggressive changes that break the boot process.

GrubPal solves this by focusing on core functionality and system safety:
  * ✅ Safety First: Always creates a timestamped backup of your current GRUB configuration before applying any changes.
  * 💻 Curses Interface: Lightning-fast, lightweight TUI works across all environments (local, SSH, minimal installs) without requiring a desktop environment.
  * ⚙️ Targeted Configuration: Focuses only on the most essential and common configuration tasks, minimizing risk.

#### Core Features

GrubPal makes complex, manual configuration steps as easy as a few keystrokes in a clean interface:
1. **Boot Entry Management** TODO
    * Reorder Entries: Easily move boot entries up or down the list to change the default boot option or preferred order.
    * Set Default: Select the specific entry that should boot automatically.

2. **Boot Parameters Editor** IP
    * Simple Parameter Toggles: Visually add, remove, or modify common kernel parameters (e.g., nomodeset, quiet, splash).
    * Custom Arguments: Add any custom arguments you need for specific hardware or debugging.

3. **Timeout Control** IP
    * Set Timeout: Quickly adjust the display duration of the GRUB menu (in seconds) via a simple numeric input.
    * Hide Menu: Option to set the timeout to zero for fast, non-interactive booting.

4. **Configuration Safety & Deployment** TODO
    * Automatic Backup: A compressed, timestamped backup is made before any file write. Recovery is straightforward.
    * Preview Changes: Review the final $GRUB_CONFIG_FILE content before it is written and update-grub is executed.
    * Configuration Validation: Basic checks to ensure the output configuration is syntactically correct before deployment.

#### Installation (Hypothetical)

* `grub-pal` is available on PyPI and installed via: `pipx install grub-pal`
* `grub-pal` makes itself root using `sudo` and will prompt for password when needed.

#### How to Use grub-pal
Running `grub-pal` brings up a screen like:
```
  [n]ext [g]UIDE [q]uit
──────────────────────────────────────────────────────────────────
 [Timeout & Menu]
   TIMEOUT .................  2
>  TIMEOUT_STYLE ...........  hidden                              
     What to show during TIMEOUT period. Choices:
      - menu: Show the full menu during the timeout period.
      - countdown: Show a countdown display instead of the menu.
      * hidden: Menu is hidden until a key is pressed.
   DEFAULT .................  0
   RECORDFAIL_TIMEOUT ......  30

 [Kernel Arguments]
   CMDLINE_LINUX ...........  ""
   CMDLINE_LINUX_DEFAULT ...  ""
   DISABLE_LINUX_UUID ......  false
   DISABLE_OS_PROBER .......  false

 [Appearance]
   BACKGROUND ..............
   DISTRIBUTOR .............  'Kubuntu'
   GFXMODE .................  640x480
   THEME ...................

 [Security & Advanced]
   ENABLE_CRYPTODISK .......  false
   TERMINAL_INPUT ..........  console
```
#### Backup and Restore
Backup and restore features:
 - backups of `/etc/default/grub` will be put in `~/.config/grub-pal`
 - backups will be named `YYYYMMDD.HHMMSS.{8-hex-digit-checksum}.{tag}.txt`
 - if there are no backup files, on startup `grub-pal` will automatically create one with tag='orig'
 - if there are backup files and have the same checksum as the current `/etc/default/grub`, you are prompted to provide a tag for its backup (you can decline if you wish)
 - tags must be word/phase-like strings with only [-_A-Za-z0-9] characters.
 - there is a `[R]estore` menu item that brings up a screen which is a list of backups; you can delete and restore backups
 - if an entry is restored, the program re-initializes using restored grub file and returns to main screen

👨‍💻 Development Status

    * Foundation: Built upon the robust console-window curses foundation.
    * Current State: Initial feature development and safety implementation.
    * Contributions: Contributions are welcome! See the CONTRIBUTING.md for guidelines.
