#!/usr/bin/env python3
"""Manages distribution-specific GRUB paths and commands."""
import os
import shutil
import sys

DEFAULT_ETC_GRUB = '/etc/default/grub'


class DistroVars:
    """
    Manages distribution-specific GRUB paths and commands.

    Automatically detects available components (grub.cfg, update commands,
    etc.) and provides graceful degradation when components are missing.
    """
    default_yaml = {
        '_distro_vars_': {
            'grub_cfg': ['/boot/grub/grub.cfg',
                         '/boot/grub2/grub.cfg',
                         '/boot/efi/EFI/fedora/grub.cfg',
                         ],
            'update_grub': ['grub-mkconfig',
                            'grub2-mkconfig',
                            'update-grub'],
            'update_initramfs': ['update-initramfs',
                                 'dracut',
                                 'mkinitcpio',
                                 'mkinitfs',
                                 'genkernel'],
            'etc_grub': [DEFAULT_ETC_GRUB]
        },
        '_update_initramfs_triggers_': {}
    }
    def __init__(self, yaml_data=None):
        """Initialize DistroVars with optional YAML configuration.

        Args:
            yaml_data: Optional YAML configuration dictionary containing '_distro_vars_' section.
                      If None, uses default_yaml configuration.
        """
        yaml_data = yaml_data if yaml_data else DistroVars.default_yaml
        vars_cfg = yaml_data.get('_distro_vars_', {})

        self.is_crippled = None
        # 1. Resolve Components
        self.grub_cfg = self._find_first_path(vars_cfg.get('grub_cfg', []))
        self.etc_grub = self._find_first_path(vars_cfg.get('etc_grub', []))
        self.update_grub = self._find_binary(vars_cfg.get('update_grub', []))
        self.update_initramfs = self._find_binary(vars_cfg.get('update_initramfs', []))

        # Load initramfs triggers for detecting when rebuild is needed
        self.initramfs_triggers = yaml_data.get('_update_initramfs_triggers_', {})

        # 2. Check and Prompt if needed
        self._check_and_confirm()

    def _find_first_path(self, paths):
        """Find the first existing path from a list of candidates."""
        for path in paths:
            if os.path.exists(path):
                return path
        return None

    def _find_binary(self, commands):
        """Find the first available command from a list of candidates."""
        for cmd in commands:
            resolved = shutil.which(cmd)
            if resolved:
                return resolved
        return None

    def _check_and_confirm(self):
        """Validate that critical components exist and prompt user
        if optional components are missing.

        Critical components (must exist):
            - etc_grub: /etc/default/grub (cannot edit without this)

        Important components (warn if missing):
            - grub_cfg: Main GRUB config (needed for menu entry enumeration)
            - update_grub: Update command (needed to apply changes)

        Sets self.is_crippled to True if any important
        (but non-critical) components are missing.
        Exits the program if critical components are missing.
        """
        missing = []
        if not self.etc_grub:
            print("\033[91mCRITICAL ERROR: /etc/default/grub not found.\033[0m")
            sys.exit(1)

        if not self.update_grub:
            print("\033[91mCRITICAL ERROR: No GRUB update command found.\033[0m")
            print("  Searched for: grub-mkconfig, grub2-mkconfig, update-grub")
            print("  Without this command, grub-wiz cannot apply changes to the system.")
            sys.exit(1)

        if not self.grub_cfg:
            missing.append("grub.cfg (Needed for DEFAULT choice list)")

        if missing:
            print("\033[93mWARNING: Some components were not found:\033[0m")
            for item in missing:
                print(f"  - {item}")

            print("\ngrub-wiz can continue in \033[1m'Crippled'\033[0m mode with limited features:")
            print("  - GRUB_DEFAULT menu entry enumeration will be unavailable")
            try:
                choice = input("Continue anyway? [y/N]: ").strip().lower()
            except EOFError:
                choice = ''

            if choice != 'y':
                print("Aborting.")
                sys.exit(0)

            self.is_crippled = True
        else:
            self.is_crippled = False

def main():
    """Exercise DistroVars by detecting and displaying system configuration."""
    distro_vars = DistroVars()
    print(f'{vars(distro_vars)=}')

if __name__ == "__main__":
    main()
