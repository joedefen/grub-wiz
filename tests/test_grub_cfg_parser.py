"""Tests for the ``grub.cfg`` entry parser and its GRUB_DEFAULT consumer."""

import subprocess
import sys
from pathlib import Path

from grub_wiz.GrubCfgParser import (
    ENTRY_KEYWORDS,
    ENUM_DESCRIPTIONS,
    entries_to_enums,
    get_top_level_grub_entries,
)

SAMPLE_CFG = """\
menuentry 'Ubuntu' --class ubuntu {
    linux /boot/vmlinuz root=UUID=123 ro
}
submenu 'Advanced options for Ubuntu' $menuentry_id_option 'gnome' {
    menuentry 'Ubuntu, with Linux 6.8.0' --class ubuntu {
        linux /boot/vmlinuz-6.8.0 root=UUID=123 ro
    }
    menuentry 'Ubuntu, with Linux 6.8.0 (recovery mode)' {
        linux /boot/vmlinuz-6.8.0 root=UUID=123 ro single
    }
}
submenu 'Other operating systems' {
    menuentry 'Fedora Linux' {
        linux /boot/vmlinuz-fedora root=UUID=456 ro
    }
    menuentry 'Setup (firmware settings)' {
    }
}
menuentry 'Memory test (memtest86+)' {
    linux16 /boot/memtest86+.bin
}
menuentry 'Windows Boot Manager' --class windows {
    chainloader /EFI/Microsoft/Boot/bootmgfw.efi
}
"""


def _write_cfg(tmp_path, content=SAMPLE_CFG):
    """Write a sample grub.cfg and return its path."""
    path = tmp_path / 'grub.cfg'
    path.write_text(content, encoding='utf-8')
    return str(path)


def test_returns_list_of_entry_dicts(tmp_path):
    """The return value must match the documented List[Dict[str, str]] type."""
    entries = get_top_level_grub_entries(_write_cfg(tmp_path))

    assert isinstance(entries, list)
    assert entries
    for entry in entries:
        assert isinstance(entry, dict)
        assert set(entry) == {'type', 'title'}
        assert entry['type'] in ENTRY_KEYWORDS


def test_matches_menuentry_and_submenu(tmp_path):
    """Both ENTRY_KEYWORDS are parsed, not just menuentry."""
    entries = get_top_level_grub_entries(_write_cfg(tmp_path))
    types = {entry['type'] for entry in entries}

    assert types == {'menuentry', 'submenu'}
    assert {'type': 'submenu', 'title': "'Other operating systems'"} in entries


def test_titles_keep_grub_quoting(tmp_path):
    """Titles stay exactly as written, including the single quotes."""
    titles = [entry['title'] for entry in get_top_level_grub_entries(
        _write_cfg(tmp_path))]

    assert "'Ubuntu'" in titles
    assert "'Windows Boot Manager'" in titles


def test_excludes_special_entries_and_nested_duplicates(tmp_path):
    """Administrative entries are skipped; no duplicate titles are returned."""
    titles = [entry['title'] for entry in get_top_level_grub_entries(
        _write_cfg(tmp_path))]

    assert "'Advanced options for Ubuntu'" not in titles
    assert "'Ubuntu, with Linux 6.8.0 (recovery mode)'" not in titles
    assert "'Memory test (memtest86+)'" not in titles
    assert "'Setup (firmware settings)'" not in titles
    assert len(titles) == len(set(titles))


def test_only_very_top_skips_indented_entries(tmp_path):
    """``only_very_top`` keeps unindented top-level entries only."""
    entries = get_top_level_grub_entries(
        _write_cfg(tmp_path), only_very_top=True)
    titles = [entry['title'] for entry in entries]

    assert titles == [
        "'Ubuntu'",
        "'Other operating systems'",
        "'Windows Boot Manager'",
    ]


def test_none_and_unreadable_paths_return_empty_list(tmp_path):
    """Missing paths and ``None`` produce an empty list, not an exception."""
    missing = str(tmp_path / 'does-not-exist.cfg')

    assert get_top_level_grub_entries(None) == []
    assert get_top_level_grub_entries(missing) == []


def test_entries_to_enums_provides_real_descriptions(tmp_path):
    """The enum mapping keys on titles and does not repeat the raw keyword."""
    enums = entries_to_enums(get_top_level_grub_entries(_write_cfg(tmp_path)))

    assert "'Ubuntu'" in enums
    assert "'Other operating systems'" in enums
    assert enums["'Ubuntu'"] == ENUM_DESCRIPTIONS['menuentry']
    assert enums["'Other operating systems'"] == ENUM_DESCRIPTIONS['submenu']
    assert 'menuentry' not in enums.values()
    assert 'submenu' not in enums.values()


def test_module_main_accepts_a_path(tmp_path):
    """The __main__ block takes the cfg path and prints both entry types."""
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, '-m', 'grub_wiz.GrubCfgParser',
         _write_cfg(tmp_path)],
        cwd=repo_root, capture_output=True, text=True, check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "[MENUENTRY] 'Ubuntu'" in result.stdout
    assert "[SUBMENU  ] 'Other operating systems'" in result.stdout


def test_module_main_requires_a_path():
    """Calling the __main__ block without a path reports usage and exits 2."""
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, '-m', 'grub_wiz.GrubCfgParser'],
        cwd=repo_root, capture_output=True, text=True, check=False,
        timeout=60,
    )

    assert result.returncode == 2
    assert 'usage:' in result.stderr
