#!/usr/bin/env python3
""" TBD """

import os
import subprocess
import json
from types import SimpleNamespace
from typing import Tuple, Optional
from copy import deepcopy
# pylint: disable=line-too-long,invalid-name,too-many-locals
# pylint: disable=too-many-branches,too-many-statements


class WizValidator:
    """ TBD """
    def __init__(self, param_cfg):
        # Cache for the disk probe results
        self._disk_layout_cache: Optional[SimpleNamespace] = None
        self.param_cfg = param_cfg
        # ... other initializations ...

    def probe_disk_layout(self) -> SimpleNamespace:
        """
        Performs a quick heuristic scan using lsblk to determine key disk layout flags.
        The result is cached to ensure the subprocess is run only once.

        Returns:
            SimpleNamespace(has_another_os: bool, is_luks_active: bool, is_lvm_active: bool)
        """
        # 1. Check Cache
        if self._disk_layout_cache is not None:
            return self._disk_layout_cache

        # 2. Set Initial State
        result = SimpleNamespace(
            has_another_os=False,
            is_luks_active=False,
            is_lvm_active=False
        )

        # lsblk is fast and outputs in JSON format
        cmd = ['lsblk', '-o', 'FSTYPE,PARTTYPE', '-J']

        try:
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False
            )

            if process.returncode != 0:
                # If lsblk fails (e.g., permissions), return the default 'False' result
                self._disk_layout_cache = result
                return result

            data = json.loads(process.stdout)

            # 3. Scan Partitions
            for device in data.get('blockdevices', []):
                if 'children' in device:
                    for partition in device['children']:
                        fstype = partition.get('FSTYPE', '').lower()
                        parttype = partition.get('PARTTYPE', '').lower()

                        # --- A. Other OS Detection (Windows/Other) ---
                        if fstype in ('ntfs', 'vfat', 'fat32', 'exfat'):
                            result.has_another_os = True

                        # Windows Recovery Partition GUID
                        if 'de94bba4-06d9-4d40-a16a-bfd50179d6ac' in parttype:
                            result.has_another_os = True

                        # --- B. LUKS/LVM Detection (Requires Special Kernel Args) ---

                        # LUKS Check
                        if fstype in ('crypto_luks', 'crypto_luks2'):
                            result.is_luks_active = True

                        # LVM Check (FSTYPE or PARTTYPE)
                        if fstype == 'lvm2_member' or \
                           'e6d6d379-f507-44c2-a23c-238f2a3df928' in parttype:
                            result.is_lvm_active = True

                        # Optimization: If all flags are True, we can stop early
                        if result.has_another_os and result.is_luks_active and result.is_lvm_active:
                            break

        except (FileNotFoundError, json.JSONDecodeError):
            # If lsblk is missing or JSON output is bad, the default 'False' result will be cached.
            pass

        # --- D. UEFI Boot Entry Detection (more accurate for multi-boot) ---
        # Supplement partition-based detection with firmware boot entries
        if not result.has_another_os:  # Only check if not already detected
            try:
                efi_process = subprocess.run(
                    ['efibootmgr'],
                    capture_output=True,
                    text=True,
                    check=False
                )
                if efi_process.returncode == 0:
                    # Use positive filtering: look for valid device patterns
                    # Real OS entries have: HD(...)/File(\EFI\{OS}\...)
                    # Generic entries have: /File(\EFI\BOOT\...) or no device info
                    #
                    # Examples:
                    #   Boot0001* ubuntu   HD(1,GPT,...)/File(\EFI\UBUNTU\SHIMX64.EFI)  <- Real OS
                    #   Boot0002* UEFI OS  HD(4,GPT,...)/File(\EFI\BOOT\BOOTX64.EFI)    <- Generic fallback
                    #   Boot0003* UEFI:CD/DVD Drive                                      <- No device info

                    os_boot_entries = []
                    for line in efi_process.stdout.split('\n'):
                        if line.startswith('Boot') and '*' in line:
                            # Must have device info (HD(...))
                            has_device = 'HD(' in line

                            # Must NOT be the generic BOOT fallback directory
                            # Check both Windows-style and Unix-style path separators
                            is_generic_boot = r'\EFI\BOOT\BOOT' in line.upper() or '/EFI/BOOT/BOOT' in line.upper()

                            # Valid OS entry: has device info AND not generic fallback
                            if has_device and not is_generic_boot:
                                os_boot_entries.append(line)

                    # If 2+ OS-specific boot entries, likely multi-boot setup
                    if len(os_boot_entries) >= 2:
                        result.has_another_os = True
            except (FileNotFoundError, PermissionError):
                # efibootmgr not installed or insufficient permissions
                pass

        # 4. Cache and Return
        self._disk_layout_cache = result
        return result

    def get_full_path_and_check_existence(self, path: str) -> Tuple[bool, str]:
        """
        Resolves a GRUB path, checks for existence in common locations,
        and returns a tuple: (exists: bool, resolved_path: str).
        """
        base_dirs = [
            '/boot/grub',      # Common for Debian/Ubuntu
            '/boot/grub2',     # Common for Fedora/CentOS/openSUSE
            '/usr/share/grub', # Fallback for some assets
            '/'                # The root filesystem, for paths starting with simple components
        ]

        if not path:
            return False, ''

        # 1. Strip surrounding quotes
        resolved_path = path.strip().strip('"').strip("'")

        # 2. Simplified $prefix expansion
        if resolved_path.startswith('$prefix'):
            resolved_path = resolved_path.replace('$prefix', base_dirs[0])

        # 3. Handle Absolute Path Check
        if os.path.isabs(resolved_path):
            # If it's absolute, check it directly
            if os.path.exists(resolved_path):
                return True, resolved_path
            return False, resolved_path # Doesn't exist, but this is the path

        # 4. Handle Relative Path Check (Try Multiple Base Directories)
        for base_dir in base_dirs:
            # Construct the full path using the base directory
            full_path = os.path.join(base_dir, resolved_path)

            # Check for existence (can be file or directory)
            if os.path.exists(full_path):
                return True, full_path

        # If we reach here, the file was not found in any common base directory.
        # Return False and the most commonly expected full path (using the primary base dir)
        fallback_path = os.path.join(base_dirs[0], resolved_path)
        return False, fallback_path


    def make_warns(self, vals: dict):
        """
        Arguments:
            * vals: param_name -> current value
            * param_dict: param_name -> param configuration
        Returns:
            * warnings dict:
                key: param
                value: list of (severity, message)
        """
        def unquote(value):
            if isinstance(value, str):
                if value.startswith("'"):
                    return value[1:].rstrip("'")
                if value.startswith('"'):
                    return value[1:].rstrip('"')
            return value
        def quotes(param): # all forms of simple value in grub config
            return (param, f'"{param}"', f"'{param}'")
        def sh(param): # "ShortHand": reduce GRUB_TIMEOUT to TIMEOUT
            return param[5:]
        def hey(param, severity, message):
            nonlocal warns, stars
            if param not in warns:
                warns[param] = []
            warns[param].append((stars[severity], message))

        def getvals(*keys):
            """ Returns (k1, v1, k2, v2, ...), or a sequence of
                 None values if a key is missing. """
            nonlocal vals
            num_keys = len(keys)
            if all(key in vals for key in keys):
                result_pairs = ((key, vals[key]) for key in keys)
                return sum(result_pairs, ())
            return tuple([None] * (num_keys * 2))

        def hey_if(bad, param_name, severity, message):
            nonlocal all_warn_keys
            if bad:
                hey(param_name, severity, message)
            if param_name:
                all_warn_keys.add(f'{param_name} {message}')
        # ------------------------------------------------ #

        stars = [''] + '* ** *** ****'.split()
        warns, all_warn_keys = {}, set()
        layout = self.probe_disk_layout()

        # if _DEFAULT is saved, then _SAVEDEFAULT must be true
        p1, v1, p2, v2 = getvals('GRUB_DEFAULT', 'GRUB_SAVEDEFAULT')
        bad = p1 and v1 in quotes('saved') and v2 not in quotes('true')
        hey_if(bad, p2, 4, f'must be "true" since {sh(p1)} is "saved"')

        # TIMEOUT=0 & TIMEOUT_STYLE=hidden (critical - unrecoverable state)
        p1, v1, p2, v2 = getvals('GRUB_TIMEOUT', 'GRUB_TIMEOUT_STYLE')
        bad = p1 and (v1 in quotes('0') or v1 in quotes('0.0')) and v2 in quotes('hidden')
        hey_if(bad, p1, 4, f'should be positive int when {sh(p2)}="hidden"')

        # TIMEOUT > 0 but TIMEOUT_STYLE is NOT menu
        p1, v1, p2, v2 = getvals('GRUB_TIMEOUT', 'GRUB_TIMEOUT_STYLE')
        is_positive = False
        try:
            is_positive = p1 and float(unquote(v1)) > 0
        except (ValueError, TypeError):
            pass
        bad = is_positive and v2 not in quotes('menu')
        hey_if(bad, p2, 4, f'should be "menu" when {sh(p1)} > 0')

        # 'quiet' belongs only in GRUB_CMDLINE_LINUX_DEFAULT
        p1, v1, p2, v2 = getvals('GRUB_CMDLINE_LINUX_DEFAULT', 'GRUB_CMDLINE_LINUX')
        bad = p2 and 'quiet' in v2
        hey_if(bad, p2, 3, f'"quiet" belongs only in {sh(p1)}')

        # 'splash' belongs only in GRUB_CMDLINE_LINUX_DEFAULT
        p1, v1, p2, v2 = getvals('GRUB_CMDLINE_LINUX_DEFAULT', 'GRUB_CMDLINE_LINUX')
        bad = p2 and 'splash' in v2
        hey_if(bad, p2, 3, f'"splash" belongs only in {sh(p1)}')

        # LUKS active but no rd.luks.uuid in GRUB_CMDLINE_LINUX
        p1, v1 = getvals('GRUB_CMDLINE_LINUX')
        bad = p1 and layout.is_luks_active and 'rd.luks.uuid=' not in v1
        hey_if(bad, p1, 3, 'no "rd.luks.uuid=" but LUKS seems active')

        # LVM active but no rd.lvm.vg in GRUB_CMDLINE_LINUX
        p1, v1 = getvals('GRUB_CMDLINE_LINUX')
        bad = p1 and layout.is_lvm_active and 'rd.lvm.vg=' not in v1
        hey_if(bad, p1, 3, 'no "rd.lvm.vg=" but LVM seems active')

        # ENABLE_CRYPTODISK without LUKS
        p1, v1 = getvals('GRUB_ENABLE_CRYPTODISK')
        bad = p1 and v1 in quotes('true') and not layout.is_luks_active
        hey_if(bad, p1, 1, 'enabled but no LUKS encryption detected')

        # Recovery cmdline set but recovery disabled
        p1, v1, p2, v2 = getvals('GRUB_CMDLINE_LINUX_RECOVERY', 'GRUB_DISABLE_RECOVERY')
        bad = p1 and v1 and v2 in quotes('true')
        hey_if(bad, p1, 2, f'set but {sh(p2)}="true" disables recovery mode')

        # UUID types disabled (both or individually)
        p1, v1, p2, v2 = getvals('GRUB_DISABLE_LINUX_UUID', 'GRUB_DISABLE_LINUX_PARTUUID')
        both_disabled = p1 and v1 in quotes('true') and v2 in quotes('true')
        only_p1 = p1 and v1 in quotes('true') and v2 not in quotes('true')
        only_p2 = p2 and v2 in quotes('true') and v1 not in quotes('true')
        hey_if(both_disabled, p1, 2, 'using device names for everything is fragile')
        hey_if(both_disabled, p2, 2, 'using device names for everything is fragile')
        hey_if(only_p1, p1, 1, 'disabling UUID may cause boot issues')
        hey_if(only_p2, p2, 1, 'disabling PARTUUID may cause boot issues')

        # Terminal INPUT should match OUTPUT when serial
        p1, v1, p2, v2 = getvals('GRUB_TERMINAL_INPUT', 'GRUB_TERMINAL_OUTPUT')
        val_in = unquote(v1) if v1 else 'console'
        val_out = unquote(v2) if v2 else ''
        bad = p1 and val_out and val_in != val_out and 'serial' in val_out
        hey_if(bad, p1, 2, f'should match {sh(p2)} when it is "serial"')

        # Terminal OUTPUT should match INPUT when serial
        p1, v1, p2, v2 = getvals('GRUB_TERMINAL_INPUT', 'GRUB_TERMINAL_OUTPUT')
        val_in = unquote(v1) if v1 else 'console'
        val_out = unquote(v2) if v2 else ''
        bad = p2 and val_out and val_in != val_out and 'serial' in val_in
        hey_if(bad, p2, 2, f'should match {sh(p1)} when it is "serial"')

        # SERIAL_COMMAND set but neither terminal is serial
        p1, v1, p2, v2, p3, v3 = getvals('GRUB_SERIAL_COMMAND', 'GRUB_TERMINAL_INPUT', 'GRUB_TERMINAL_OUTPUT')
        term_in = unquote(v2) if v2 else 'console'
        term_out = unquote(v3) if v3 else ''
        bad = p1 and v1 and 'serial' not in term_out and 'serial' not in term_in
        hey_if(bad, p1, 2, f'set but neither {sh(p2)} or {sh(p3)} are "serial"')

        # TERMINAL_INPUT is serial but no SERIAL_COMMAND
        p1, v1, p2, v2 = getvals('GRUB_SERIAL_COMMAND', 'GRUB_TERMINAL_INPUT')
        term_in = unquote(v2) if v2 else 'console'
        bad = p2 and 'serial' in term_in and not v1
        hey_if(bad, p2, 2, f'"serial" requires {sh(p1)} to be set')

        # TERMINAL_OUTPUT is serial but no SERIAL_COMMAND
        p1, v1, p2, v2 = getvals('GRUB_SERIAL_COMMAND', 'GRUB_TERMINAL_OUTPUT')
        term_out = unquote(v2) if v2 else ''
        bad = p2 and 'serial' in term_out and not v1
        hey_if(bad, p2, 2, f'"serial" requires {sh(p1)} to be set')

        # SAVEDEFAULT=true but DEFAULT is numeric (menu can reorder)
        p1, v1, p2, v2 = getvals('GRUB_SAVEDEFAULT', 'GRUB_DEFAULT')
        default_value = v2 if v2 else '0'
        bad = p1 and v1 in quotes('true') and unquote(default_value).isdigit()
        hey_if(bad, p2, 1, f'avoid numeric when {sh(p1)}="true"')

        # GRUB_CMDLINE_LINUX has spaces but not quoted
        p1, v1 = getvals('GRUB_CMDLINE_LINUX')
        bad = p1 and v1 is not None and ' ' in v1 and v1 not in quotes(unquote(v1))
        hey_if(bad, p1, 2, 'has spaces and thus must be quoted')

        # GRUB_CMDLINE_LINUX_DEFAULT has spaces but not quoted
        p1, v1 = getvals('GRUB_CMDLINE_LINUX_DEFAULT')
        bad = p1 and v1 is not None and ' ' in v1 and v1 not in quotes(unquote(v1))
        hey_if(bad, p1, 2, 'has spaces and thus must be quoted')

        # GRUB_BACKGROUND path doesn't exist
        p1, v1 = getvals('GRUB_BACKGROUND')
        exists, _ = self.get_full_path_and_check_existence(v1) if v1 else (True, '')
        bad = p1 and v1 and not exists
        hey_if(bad, p1, 2, 'path does not seem to exist')

        # GRUB_THEME path doesn't exist
        p1, v1 = getvals('GRUB_THEME')
        exists, _ = self.get_full_path_and_check_existence(v1) if v1 else (True, '')
        bad = p1 and v1 and not exists
        hey_if(bad, p1, 2, 'path does not seem to exist')

        # GFXMODE set but not a known safe value
        p1, v1 = getvals('GRUB_GFXMODE')
        safe_modes = {'640x480', '800x600', '1024x768', 'auto', 'keep'}
        modes = [m.strip().lower() for m in unquote(v1).split(',')] if v1 else []
        unsafe_modes = [m for m in modes if m not in safe_modes]
        bad = p1 and v1 and len(unsafe_modes) > 0
        hey_if(bad, p1, 1, 'perhaps unsupported; stick to common values')

        # GRUB_DISTRIBUTOR missing or empty (not a shell command)
        p1, v1 = getvals('GRUB_DISTRIBUTOR')
        val = v1 if v1 else ''
        is_shell_cmd = val.startswith('$(') or val.startswith('`')
        bad = p1 and ((val and not is_shell_cmd and not val.strip()) or not val)
        hey_if(bad, p1, 2, 'should be distro name (it is missing/empty)')

        # OS-PROBER disabled on dual-boot system
        p1, v1 = getvals('GRUB_DISABLE_OS_PROBER')
        bad = p1 and v1 in quotes('true') and layout.has_another_os
        hey_if(bad, p1, 2, 'suggest setting "false" since multi-boot detected')

        # OS-PROBER enabled but no multi-boot detected
        p1, v1 = getvals('GRUB_DISABLE_OS_PROBER')
        bad = p1 and v1 not in quotes('true') and not layout.has_another_os
        hey_if(bad, p1, 1, 'perhaps set "true" since no multi-boot detected?')

        # Check parameters with fixed list of possible values (enums)
        for param_name, cfg in self.param_cfg.items():
            enums = cfg.get('enums', None)
            regex = cfg.get('edit_re', None)
            has_enums = isinstance(enums, dict) and len(enums) > 0
            has_no_regex = not regex or (isinstance(regex, (list, dict)) and len(regex) == 0)

            p1, v1 = getvals(param_name)
            if p1 and has_enums and has_no_regex:
                value = str(unquote(v1))
                found = any(value == unquote(str(k)) for k in enums.keys())
                bad = not found
                hey_if(bad, p1, 3, 'value not in list of allowed values')

        # GRUB_TIMEOUT over recommended limit
        p1, v1 = getvals('GRUB_TIMEOUT')
        val = str(unquote(v1)) if v1 else ''
        bad = p1 and val and val.isdigit() and int(val) > 60
        hey_if(bad, p1, 1, 'over 60s seems ill advised')

        # GRUB_RECORDFAIL_TIMEOUT over recommended limit
        p1, v1 = getvals('GRUB_RECORDFAIL_TIMEOUT')
        val = str(unquote(v1)) if v1 else ''
        bad = p1 and val and val.isdigit() and int(val) > 120
        hey_if(bad, p1, 1, 'over 120s seems ill advised')

        return warns, all_warn_keys

    def demo(self, param_defaults):
        """ TBD """
        def dump(title):
            nonlocal warnings
            print(f'\n{title}')
            if not warnings:
                print('  (no warnings)')
            else:
                for param, pairs in warnings.items():
                    for pair in pairs:
                        print(f'{param:>30} {pair[0]:>4} {pair[1]}')

        changes = [
            ('DEFAULT=saved without SAVEDEFAULT=true',
             {'GRUB_DEFAULT': 'saved', 'GRUB_SAVEDEFAULT': 'false'}),

            ('TIMEOUT=0 with TIMEOUT_STYLE=hidden',
             {'GRUB_TIMEOUT': '0', 'GRUB_TIMEOUT_STYLE': 'hidden'}),

            ('SAVEDEFAULT=true with numeric DEFAULT',
             {'GRUB_SAVEDEFAULT': 'true', 'GRUB_DEFAULT': '2'}),

            ('quiet/splash in CMDLINE_LINUX (recovery)',
             {'GRUB_CMDLINE_LINUX': '"quiet splash"'}),

            ('Invalid boolean value',
             {'GRUB_SAVEDEFAULT': 'maybe'}),

            ('TIMEOUT=5 with TIMEOUT_STYLE=countdown',
             {'GRUB_TIMEOUT': '5', 'GRUB_TIMEOUT_STYLE': 'countdown'}),

            ('TIMEOUT=500 being excessive',
             {'GRUB_TIMEOUT': 500}),

            ('Nonexistent background path',
             {'GRUB_BACKGROUND': '/nonexistent/image.png'}),

            ('Recovery cmdline but recovery disabled',
             {'GRUB_CMDLINE_LINUX_RECOVERY': '"nomodeset"', 'GRUB_DISABLE_RECOVERY': 'true'}),

            ('Both UUID types disabled (fragile)',
             {'GRUB_DISABLE_LINUX_UUID': 'true', 'GRUB_DISABLE_LINUX_PARTUUID': 'true'}),

            ('Terminal I/O mismatch',
             {'GRUB_TERMINAL_INPUT': 'serial', 'GRUB_TERMINAL_OUTPUT': 'console'}),

            ('Serial terminal without SERIAL_COMMAND',
             {'GRUB_TERMINAL_INPUT': 'serial'}),

            ('SERIAL_COMMAND without serial terminal',
             {'GRUB_SERIAL_COMMAND': '"serial --unit=0 --speed=115200"'}),

            ('Invalid VIDEO_BACKEND value',
             {'GRUB_VIDEO_BACKEND': 'invalid_backend'}),

            ('Clean config - no issues',
             {}),
        ]

        for title, overrides in changes:
            vals = deepcopy(param_defaults)
            for param, val in overrides.items():
                vals[param] = val
            warnings = self.make_warns(vals)
            dump(title)
