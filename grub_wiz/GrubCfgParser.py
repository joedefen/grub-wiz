#!/usr/bin/env python3
import re
import os
import sys
from typing import List, Dict

GRUB_CFG_PATH = '/boot/grub/grub.cfg'
# Keywords that mark a bootable entry or a sub-menu.
ENTRY_KEYWORDS = ['menuentry', 'submenu']

# Entries that are typically administrative, recovery, or non-OS-specific 
SPECIAL_EXCLUSIONS = [
    'Setup',         # UEFI/BIOS Setup entry
    'Memtest',              # Memory test entry (often in submenus)
    'Recovery',        # Linux recovery entries
    'Advanced',      # General advanced options submenu (if included in title)
    'Firmware',      # e.g, UEFI Firmware Settings
]


def get_top_level_grub_entries(only_very_top=True) -> List[Dict[str, str]]:
    """
    Parses the /boot/grub/grub.cfg file to find all top-level menuentry and 
    submenu titles, excluding special administrative entries.

    Returns:
        A list of dictionaries, where each dict has 'type' (menuentry/submenu)
        and 'title' (the exact string used in grub.cfg).
    """
    try:
        # Regex to capture both 'menuentry' and 'submenu' titles.
        # Captures: 1=keyword (menuentry/submenu), 2=title (quoted string)
        # It's highly important to only parse the top-level structure.
        # The line must start with the keyword, followed by one or more spaces, 
        # followed by the single-quoted title.
        with open(GRUB_CFG_PATH, 'r', encoding='utf-8') as f:
            content = f.read()

    except Exception as e:
        print(f"ERROR: cannot read {GRUB_CFG_PATH}: {e}", file=sys.stderr)
        return []
        
    entry_pattern = re.compile(r"^(\s*)(menuentry)\s+('[^']+')")
    entries = {}
    
    for line in content.splitlines():
        match = entry_pattern.match(line)
        if match:
            leading_spaces = match.group(1)
            entry_type = match.group(2)
            entry_title = match.group(3)
            
            if only_very_top and leading_spaces:
                # Skip indented entries if only_very_top is True
                continue
            
            is_special = any(ex.lower() in entry_title.lower() for ex in SPECIAL_EXCLUSIONS)
            
            if not is_special:
                entries[entry_title] = entry_type
                
    return entries


# --- Example Usage (Using Mock for safety) ---
if __name__ == '__main__':
    available_entries = get_top_level_grub_entries()
    
    print("\nAvailable GRUB Menu Entries (for GRUB_DEFAULT):")
    
    if not available_entries:
        print("No top-level boot entries found after exclusion.")
    else:
        # 2. List the discovered entries
        for entry in available_entries:
            print(f"[{entry['type'].upper():<9}] '{entry['title']}'")