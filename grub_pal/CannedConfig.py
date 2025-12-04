#!/usr/bin/env
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

YAML_STRING = r"""
GRUB_TIMEOUT:
  section: Timeout & Menu
  default: 5
  enums:
    -1: infinite wait
    0: no wait
    2: short wait
    5: medium wait
    15: healthy wait
    60: long wait
  guidance: "The timeout for the GRUB menu display.
    \n -1: wait indefinitely until a key is pressed.
    \n  0: instant boot (quickly type ESC or hold shift for menu)
    \n>=1: seconds to wait until auto boot"
  checks:
    regex: ^-?\d+$
    min: -1
  specials: []
GRUB_TIMEOUT_STYLE:
  section: Timeout & Menu
  default: menu
  enums:
    menu: Show the full menu during the timeout period.
    countdown: Show a countdown display instead of the menu.
    hidden: Menu is hidden until a key is pressed.
  guidance: "What to show during TIMEOUT period. Choices:
    \n%ENUMS%"
  checks: []
  specials: []
GRUB_BACKGROUND:
  section: Appearance
  default: ''
  enums: {}
  guidance: "Full path and filename to a background image.
    \nMust be a JPEG or PNG file. Recommended size is screen resolution.
    \nLeave blank for no background image."
  checks:
    regex: ^/.*(\.png|\.jpg|\.jpeg)$|^$ # Must be a file path ending in an image extension, or empty
  specials: []

GRUB_CMDLINE_LINUX:
  section: Kernel Arguments
  default: ''
  enums: {}
  guidance: "Arguments passed to the Linux kernel ONLY on normal boot (not recovery).
    \nTypical uses: video options, disabling specific drivers, or custom parameters.
    \nValues here are combined with GRUB_CMDLINE_LINUX_DEFAULT."
  checks: []
  specials: []

GRUB_CMDLINE_LINUX_DEFAULT:
  section: Kernel Arguments
  default: "quiet splash"
  enums:
    "quiet splash": Default Ubuntu/Debian setting (hides boot messages).
    "": Show all boot messages (no options).
    "text": Force text mode display.
    "nomodeset": Disable kernel mode setting (useful for graphics troubleshooting).
  guidance: "Arguments passed to the Linux kernel for all boot entries (normal and recovery).
    \nUsed for system-wide options. Separate multiple options with a space.
    \nValues here are combined with GRUB_CMDLINE_LINUX."
  checks: []
  specials: []

GRUB_DEFAULT:
  section: Timeout & Menu
  default: 0
  enums:
    0: The first entry in the menu (usually the latest OS).
    saved: The last operating system successfully booted.
  guidance: "Sets the default menu entry to boot. Can be:
    \n - An index number (starting from 0).
    \n - The keyword 'saved' to remember the last choice.
    \n - A full menu entry title (case-sensitive)."
  checks:
    regex: ^\d+$|^saved$|^[^\s].*$ # Matches number, 'saved', or a non-empty string
  specials:
    - 'get_menu_entries' # Flag to suggest dynamically fetching available entries

GRUB_DISABLE_LINUX_UUID:
  section: Kernel Arguments
  default: 'false'
  enums:
    true: Use device names (e.g., /dev/sda1) instead of UUIDs.
    false: Use UUIDs (Recommended - less prone to breaking when disks are moved).
  guidance: "Setting to 'true' stops GRUB from using the unique disk UUID (Universal Unique Identifier)
    \nfor the root filesystem. Use 'false' unless you have a specific reason."
  checks: []
  specials: []

GRUB_DISABLE_OS_PROBER:
  section: Discovery
  default: 'false'
  enums:
    true: Do not search for other operating systems.
    false: Search for and automatically add other operating systems to the menu.
  guidance: "Setting to 'true' prevents GRUB from automatically scanning other partitions
    \nfor installed operating systems (like Windows, other Linux distros)
    \nand adding them to the boot menu."
  checks: []
  specials: []

GRUB_DISTRIBUTOR:
  section: Appearance
  default: $(lsb_release -i -s)
  enums: {}
  guidance: "Sets the visible name of the operating system in the boot menu.
    \nBy default, it uses the Linux Standard Base (LSB) name (e.g., 'Ubuntu').
    \nSet to a custom string to change the display name."
  checks: []
  specials: []

GRUB_ENABLE_CRYPTODISK:
  section: Security & Advanced
  default: 'false'
  enums:
    true: Enable detection and unlocking of encrypted drives (e.g., LUKS).
    false: Disable encrypted disk support.
  guidance: "Enables GRUB's ability to unlock encrypted disks to access
    \nGRUB files or the boot partition. Essential for systems with full disk encryption."
  checks: []
  specials: []

GRUB_GFXMODE:
  section: Appearance
  default: 640x480
  enums:
    "640x480": Standard lowest common denominator resolution.
    "800x600": Older standard resolution.
    "1024x768": Common monitor resolution.
    "auto": Choose the highest available resolution for your display.
  guidance: "Sets the resolution for the GRUB menu display.
    \nUse 'auto' to let GRUB pick the best available mode for your monitor.
    \nSeparate multiple preferred resolutions with commas (e.g., 1024x768,auto)."
  checks:
    regex: ^(auto|\d+x\d+)(,\s*(auto|\d+x\d+))*$
  specials: []

GRUB_RECORDFAIL_TIMEOUT:
  section: Timeout & Menu
  default: 30
  enums:
    10: Short wait for error.
    30: Default error wait.
    60: Long wait for error.
  guidance: "If the previous boot failed (e.g., kernel panic), GRUB shows a recovery menu.
    \nThis sets the timeout (in seconds) for that specific recovery menu."
  checks:
    regex: ^\d+$
    min: 0
  specials: []

GRUB_TERMINAL_INPUT:
  section: Advanced
  default: console
  enums:
    console: Use the standard terminal/monitor.
    serial: Use a serial port for input.
  guidance: "Defines the input device for the GRUB command line and menu.
    \nMost desktop users should use 'console'."
  checks: []
  specials: []

GRUB_THEME:
  section: Appearance
  default: ''
  enums: {}
  guidance: "Path to the theme.txt file for a custom GRUB theme.
    \nThis overrides the background image setting (GRUB_BACKGROUND)."
  checks:
    regex: ^/.*theme\.txt$|^$ # Must be a file path ending in theme.txt, or empty
  specials: []
"""

from ruamel.yaml import YAML

yaml = YAML()
yaml.preserve_quotes = True
yaml.default_flow_style = False

class CannedConfig:
    """ TBD"""
    def __init__(self):
        self.data = yaml.load(YAML_STRING)
        
    def dump(self):
      """ Dump the wired/initial configuration"""
      string = yaml.dump(self.data)
      print(string)

def main():
    """ TBD """
    string = yaml.dump(config_data)
    print(string)

if __name__ == '__main__':
    main()