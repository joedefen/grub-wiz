#!/usr/bin/env python3
"""Helpers for reading the boot entries out of a generated ``grub.cfg``."""
import re
import sys

ENTRY_KEYWORDS = ['menuentry', 'submenu']

SPECIAL_EXCLUSIONS = [
    'Setup',         # UEFI/BIOS Setup entry
    'Memtest',              # Memory test entry (often in submenus)
    'Recovery',        # Linux recovery entries
    'Advanced',      # General advanced options submenu (if included in title)
    'Firmware',      # e.g, UEFI Firmware Settings
]

ENUM_DESCRIPTIONS = {
    'menuentry': 'Boot this GRUB menu entry.',
    'submenu': 'Sub-menu; use "title>entry" to boot an entry inside it.',
}

_ENTRY_PATTERN = re.compile(
    r"^(\s*)(" + '|'.join(ENTRY_KEYWORDS) + r")\s+('[^']+')"
)


def get_top_level_grub_entries(grub_cfg, only_very_top=False) -> list[dict[str, str]]:
    """Parse a generated ``grub.cfg`` for its ``menuentry`` and ``submenu`` titles.

    Special administrative entries (see :data:`SPECIAL_EXCLUSIONS`) are skipped,
    and duplicate titles are reported once so the resulting
    values remain unique keys in the ``GRUB_DEFAULT`` enum.

    Args:
      * grub_cfg: Path to the ``grub.cfg`` file, or ``None``.
      * only_very_top: When true, ignore indented entries and keep only
            entries defined at the top level of the menu.

    Returns: A list of dictionaries, where each dict has 'type' (menuentry/submenu)
        and 'title' (the exact string used in grub.cfg).
    """
    if grub_cfg is None:
        return []
    try:
        with open(grub_cfg, encoding='utf-8') as f:
            content = f.read()
    except (OSError, UnicodeDecodeError) as e:
        print(f"ERROR: cannot read {grub_cfg}: {e}", file=sys.stderr)
        return []

    entries = []
    seen_titles = set()

    for line in content.splitlines():
        match = _ENTRY_PATTERN.match(line)
        if not match:
            continue

        leading_spaces = match.group(1)
        entry_type = match.group(2)
        entry_title = match.group(3)

        if only_very_top and leading_spaces:
            # Skip indented entries if only_very_top is True
            continue

        is_special = any(ex.lower() in entry_title.lower()
                         for ex in SPECIAL_EXCLUSIONS)
        if is_special or entry_title in seen_titles:
            continue

        seen_titles.add(entry_title)
        entries.append({'type': entry_type, 'title': entry_title})

    return entries


def entries_to_enums(entries: list[dict[str, str]]) -> dict[str, str]:
    """Convert parsed entries to the ``{value: description}`` enum mapping."""
    enums = {}
    for entry in entries:
        entry_type = entry.get('type', '')
        title = entry.get('title', '')
        if not title:
            continue
        enums[title] = ENUM_DESCRIPTIONS.get(
            entry_type, f'A GRUB {entry_type or "menu"} entry.')
    return enums


def main(argv=None):
    """Print the entries found in the ``grub.cfg`` named on the command line."""
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(f"usage: {sys.argv[0]} /path/to/grub.cfg", file=sys.stderr)
        return 2

    available_entries = get_top_level_grub_entries(argv[0])

    print("\nAvailable GRUB Menu Entries (for GRUB_DEFAULT):")

    if not available_entries:
        print("No top-level boot entries found after exclusion.")
    else:
        for entry in available_entries:
            print(f"[{entry['type'].upper():<9}] {entry['title']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
