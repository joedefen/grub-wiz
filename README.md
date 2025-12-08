>  **This project is very early in development ... come back later.**

## GrubWiz: The Friendly GRUB Bootloader Assistant

A safe, simple, and reliable Text User Interface (TUI) utility for managing the most common GRUB bootloader configuration tasks on Linux systems.

GrubWiz provides the ease-of-use of a graphical configurator without the dependency bloat or the reputation for complex, destructive changes. It operates strictly on configuration files, making safe backups before every change.

#### Why Use GrubWiz?

Dealing with `/etc/default/grub` and running `update-grub` manually is tedious and prone to typos. Other visual configurators often make overly aggressive changes that break the boot process.

GrubWiz solves this by focusing on core functionality and system safety:
  * ✅ Safety First: Always creates a timestamped backup of your current GRUB configuration before applying any changes.
  * 💻 Curses Interface: Lightning-fast, lightweight TUI works across all environments (local, SSH, minimal installs) without requiring a desktop environment.
  * ⚙️ Targeted Configuration: Focuses only on the most essential and common configuration tasks, minimizing risk.

#### Core Features

GrubWiz makes complex, manual configuration steps as easy as a few keystrokes in a clean interface:
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

* `grub-wiz` is available on PyPI and installed via: `pipx install grub-wiz`
* `grub-wiz` makes itself root using `sudo` and will prompt for password when needed.

#### How to Use grub-wiz
Running `grub-wiz` brings up a screen like:
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
 - backups of `/etc/default/grub` will be put in `~/.config/grub-wiz`
 - backups will be named `YYYYMMDD.HHMMSS.{8-hex-digit-checksum}.{tag}.txt`
 - if there are no backup files, on startup `grub-wiz` will automatically create one with tag='orig'
 - if there are backup files and have the same checksum as the current `/etc/default/grub`, you are prompted to provide a tag for its backup (you can decline if you wish)
 - tags must be word/phase-like strings with only [-_A-Za-z0-9] characters.
 - there is a `[R]estore` menu item that brings up a screen which is a list of backups; you can delete and restore backups
 - if an entry is restored, the program re-initializes using restored grub file and returns to main screen

👨‍💻 Development Status

    * Foundation: Built upon the robust console-window curses foundation.
    * Current State: Initial feature development and safety implementation.
    * Contributions: Contributions are welcome! See the CONTRIBUTING.md for guidelines.

## Appendix

#### Checks
* Critical (prevent boot issues):
  * saved → must have GRUB_SAVEDEFAULT=true
  * hidden → should have GRUB_HIDDEN_TIMEOUT set
* Best practices:
  * splash only in _DEFAULT, not in _LINUX (recovery mode shows text)
  * quiet only in _DEFAULT, not in _LINUX
  * GRUB_TIMEOUT=0 with GRUB_TIMEOUT_STYLE=hidden → unrecoverable if default fails
  * GRUB_DISABLE_OS_PROBER=true when dual-boot detected (check for Windows/other partitions)
* Common mistakes:
  * Unquoted values in GRUB_CMDLINE_* (should have quotes)
  * GRUB_BACKGROUND path doesn't exist
  * GRUB_THEME path doesn't exist
  * GRUB_GFXMODE set but no valid modes (warn if not using auto)
* Advanced:
  * GRUB_ENABLE_CRYPTODISK=true but no LUKS detected
  * GRUB_SAVEDEFAULT=true but GRUB_DEFAULT is numeric (contradictory)

* Implementation:
  * Warnings (yellow) vs Errors (red)
  * Allow override/proceed anyway
  * Group by severity
  * Top priority: first 2 critical checks.

#### Running grub-wiz at recovery time

To leverage user-installed, `grub-wiz` even in minimal recovery environment of grub recovery mode:
1. Remount the root filesystem as Read-Write: `mount -o remount,rw /`
2. Execute grub-wiz using its full path: `/home/{username}/.local/bin/grub-wiz`
3. Make changes as needed, and "write" them to update the boot instructions.


#### Essential Linux Kernel Parameters (GRUB Arguments)

These are the arguments that get passed directly to the Linux kernel during the boot process.
Parameter	Purpose & When to Use It	Example Use Case

* quiet
  * Boot Output Control: Suppresses most kernel startup messages, making the boot process appear cleaner and faster (often used with splash).
  * Default setting on most consumer distributions.
* splash
  * Visual Boot: Tells the kernel to display a graphical boot screen (e.g., the Ubuntu or Fedora logo) instead of raw text output.
  * Default setting for an aesthetic desktop experience.
* nomodeset
  * Graphics Troubleshooting: Crucial for fixing black screens or corrupted graphics.
  * It forces the kernel to skip loading video drivers and use basic VESA graphics initially, often allowing you to boot into the desktop to install proper proprietary drivers.	Use when the system freezes or shows a black screen after kernel loading.
* init=/bin/bash
  * Emergency Shell: Replaces the standard /sbin/init or /usr/lib/systemd/systemd process with a simple Bash shell, giving you immediate root access to the system for repair.
  * Use when you forget your root password or the system fails to boot into runlevels.
* ro or rw
  * Root Filesystem Mode: ro mounts the root filesystem as Read-Only initially (standard for safety, as the initramfs will remount it rw later). rw forces it to mount Read-Write immediately.
  * ro is the safer, common default. Change to rw only if explicitly needed for early-boot modifications.
* single or 1
  * Single-User Mode (Rescue): Boots the system to a minimal state, usually without networking or graphical interfaces, often requiring the root password.
  * This is ideal for system maintenance.	Use for maintenance or recovery, especially when networking or services are causing issues.
* systemd.unit=multi-user.target
  * Bypass Graphical Login: Forces the system to boot to a command-line terminal login instead of the graphical desktop (skipping graphical.target).
  * Use when GUI problems prevent login or you want a server-like environment.
* noapic or acpi=off
  * Hardware Compatibility (Legacy): Disables the Advanced Programmable Interrupt Controller (noapic) or the Advanced Configuration and Power Interface (acpi=off).
  * These are extreme measures for very old or extremely non-compliant hardware that hangs during boot.	Use as a last resort when the kernel hangs while initializing hardware components.
* rhgb
  * Red Hat Graphical Boot: Similar to splash, but specifically used by Red Hat/Fedora systems to control their graphical boot experience.
  * Used primarily on RHEL, CentOS, or Fedora distributions.


The authoritative source for all kernel command-line parameters is the official Linux kernel documentation. Since parameters can change between major kernel versions, this is always the best place to check for advanced or very specific options:

Official Linux Kernel Documentation (Current): Search for the `kernel-parameters.rst` document in the official kernel git repository. A common link to this documentation is the `kernel-command-line(7)` manual page, which is linked to the online documentation.