#!/usr/bin/env python3

"""
{parameter-name}:
  section: {TUI grouping}
  type: {cycle | input | boolean | special_list} # Controls Curses interaction
  default: {default value from GRUB docs}
  enums: # list of values for 'type: cycle' or 'type: special_list'
    - value: meaning
  regex: {regex} # Optional, for 'type: input' validation
  specials: # Optional, for 'type: special_list' population
    - {special_key} # e.g., "get-res-list", "get-disk-uuid"
  brief: {text} # < 60 char description
  full: {text} # < 400 char detailed explanation
"""

GRUB_PAL_CONFIG = r"""
GRUB_DEFAULT:
  section: "Boot Selection"
  type: cycle
  default: "0"
  enums:
    - value: "0"
      meaning: "Boot the first entry in the menu (usually the latest kernel)."
    - value: "saved"
      meaning: "Boot the entry selected in the previous session."
    - value: "gnulinux-advanced-*-*"
      meaning: "Specify a menu entry title (complex, use 'e' edit)."
  regex: '(\d+|saved|gnulinux-advanced-\S+-\S+)'
  specials: []
  brief: "Which boot entry to select by default."
  full: "Sets the default menu entry to boot. '0' is the first entry, 'saved' remembers the last successful boot."

GRUB_TIMEOUT:
  section: "Timeout & Menu"
  type: input
  default: "5"
  enums: []
  regex: '^-?\d+$' # Allows any integer, including -1 for wait-forever
  specials: []
  brief: "Time (in seconds) to wait before booting the default entry."
  full: "The timeout for the GRUB menu display. Set to 0 for instant boot, or -1 to wait indefinitely until a key is pressed."

GRUB_TIMEOUT_STYLE:
  section: "Timeout & Menu"
  type: cycle
  default: "menu"
  enums:
    - value: "menu"
      meaning: "Show the full menu during the timeout period."
    - value: "countdown"
      meaning: "Show a countdown display instead of the menu."
    - value: "hidden"
      meaning: "Menu is hidden until a key is pressed."
  regex: '^(menu|countdown|hidden)$'
  specials: []
  brief: "How the timeout is displayed."
  full: "Determines if the full menu, a countdown, or nothing is displayed during the timeout."

GRUB_CMDLINE_LINUX_DEFAULT:
  section: "Kernel Arguments"
  type: input
  default: "quiet splash"
  enums:
    - value: "nomodeset"
      meaning: "Disable kernel mode setting (often for broken graphics drivers)."
    - value: "text"
      meaning: "Force text-only console."
    - value: "systemd.show_status=1"
      meaning: "Show systemd startup messages."
  regex: '.+'
  specials: []
  brief: "Arguments passed to the kernel when booting (normal mode)."
  full: "The most important line for common kernel options like 'quiet', 'splash', 'nomodeset', etc. Ensure arguments are space-separated."

GRUB_CMDLINE_LINUX:
  section: "Kernel Arguments"
  type: input
  default: ""
  enums: []
  regex: '.*'
  specials: []
  brief: "Arguments passed to all kernel entries, including recovery."
  full: "Kernel parameters applied to all entries, including recovery. Use this for necessary hardware options that must *always* be present."

GRUB_DISABLE_OS_PROBER:
  section: "Scanning"
  type: boolean # A special cycle type for T/F
  default: "false"
  enums:
    - value: "true"
      meaning: "Do NOT search for other operating systems (Windows, other Linux installs)."
    - value: "false"
      meaning: "Search for other operating systems."
  regex: '^(true|false)$'
  specials: []
  brief: "Toggle scanning for other OSes (os-prober)."
  full: "If set to 'true', GRUB will not automatically add entries for other operating systems found on separate partitions."

GRUB_TERMINAL_INPUT:
  section: "Appearance"
  type: cycle
  default: "console"
  enums:
    - value: "console"
      meaning: "Use standard text input."
    - value: "serial"
      meaning: "Enable serial console input (requires GRUB_SERIAL_COMMAND)."
  regex: '^(console|serial)$'
  specials: []
  brief: "Sets the input device for the GRUB menu."
  full: "Typically set to 'console'. Change to 'serial' if you are managing the system remotely via a serial connection."

GRUB_GFXMODE:
  section: "Appearance"
  type: special_list
  default: "auto"
  enums:
    - value: "auto"
      meaning: "Automatically determine best resolution."
  regex: '^\d+x\d+x\d+$|^\d+x\d+$|^auto$'
  specials:
    - "get-res-list" # TUI would populate enums with detected resolutions
  brief: "The resolution for the graphical GRUB menu."
  full: "The pixel resolution for the menu display, e.g., '1024x768'. 'auto' is the safest choice. List is populated via 'get-res-list'."

GRUB_BACKGROUND:
  section: "Appearance"
  type: input
  default: ""
  enums: []
  regex: '^(\/|\w).*$'
  specials: []
  brief: "Path to a background image file (PNG, JPG, TGA)."
  full: "Specifies a full path (e.g., /boot/grub/splash.png) to a custom image for the GRUB menu background."

GRUB_DISTRIBUTOR:
  section: "Metadata"
  type: input
  default: "$(lsb_release -i -s 2> /dev/null || echo Debian)"
  enums: []
  regex: '.*'
  specials: []
  brief: "Label used to identify your OS in the menu entries."
  full: "The string used in the menu entry titles to denote the operating system (e.g., 'Ubuntu', 'Debian')."

GRUB_RECORDFAIL_TIMEOUT:
  section: "Timeout & Menu"
  type: input
  default: "30" # Often defaulted to 30s
  enums: []
  regex: '^\d+$'
  specials: []
  brief: "Timeout (in seconds) used after a boot failure or crash."
  full: "If a previous boot failed (e.g., failed shutdown, kernel panic), GRUB will wait this long to give the user a chance to recover. Setting this to 0 or a low number can speed up boot after a known failure condition."

GRUB_DISABLE_LINUX_UUID:
  section: "Kernel Arguments"
  type: boolean
  default: "false"
  enums:
    - value: "true"
      meaning: "Use device names (e.g., /dev/sda1) instead of UUIDs in boot entries."
    - value: "false"
      meaning: "Use Universally Unique Identifiers (UUIDs) for device paths."
  regex: '^(true|false)$'
  specials: []
  brief: "Force GRUB to use device names instead of UUIDs for mounting filesystems."
  full: "UUIDs are generally safer, but if you have a non-standard setup (like certain RAID/LVM) or are debugging, disabling UUIDs might be necessary."

GRUB_ENABLE_CRYPTODISK:
  section: "Security"
  type: boolean
  default: "n" # GRUB uses 'y'/'n' for this parameter
  enums:
    - value: "y"
      meaning: "Enable support for encrypted disks (LUKS/dm-crypt) in the GRUB environment."
    - value: "n"
      meaning: "Do not include support for encrypted disks."
  regex: '^(y|n)$'
  specials: []
  brief: "Enable support for booting from encrypted disks."
  full: "If your system's root partition is encrypted (LUKS), you must enable this parameter and run update-grub for the boot process to work correctly."

GRUB_THEME:
  section: "Appearance"
  type: input
  default: ""
  enums: []
  regex: '^(\/|\w).*$'
  specials: []
  brief: "Path to the directory containing a GRUB theme (optional)."
  full: "Specifies the full path to a directory containing a GRUB theme for a more polished graphical look. If unset, it uses the basic look defined by GRUB_GFXMODE."
"""
import yaml

def main():
  config_data = yaml.safe_load(GRUB_PAL_CONFIG)
  string = yaml.dump(config_data, default_flow_style=False)
  print("DATA=", string)

main()
