#!/usr/bin/env python3
""" TBD """

import os
import re
import subprocess
import json
from types import SimpleNamespace
from typing import Tuple, Optional
from copy import deepcopy
from .GrubFile import GrubFile
from .WarnDB import WarnDB
# pylint: disable=line-too-long,invalid-name,too-many-locals
# pylint: disable=too-many-branches,too-many-statements
# pylint: disable=too-many-nested-blocks


class WizValidator:
    """ TBD """

    # GPT partition-type GUIDs (lowercase) used by the disk-layout heuristics.
    GPT_WINDOWS_RECOVERY = 'de94bba4-06d9-4d40-a16a-bfd50179d6ac'
    GPT_MICROSOFT_BASIC_DATA = 'ebd0a0a2-b9e5-4433-87c0-68b6b72699c7'
    GPT_LINUX_LVM = 'e6d6d379-f507-44c2-a23c-238f2a3df928'
    # Filesystems only another OS is likely to use.
    OTHER_OS_FSTYPES = ('ntfs', 'exfat')
    WINDOWS_PARTTYPES = (GPT_WINDOWS_RECOVERY, GPT_MICROSOFT_BASIC_DATA)
    LUKS_FSTYPES = ('crypto_luks', 'crypto_luks2')
    LVM_FSTYPES = ('lvm2_member',)

    def __init__(self, param_cfg, initramfs_tool: Optional[str] = None):
        # Cache for the disk probe results
        self._disk_layout_cache: Optional[SimpleNamespace] = None
        self.param_cfg = param_cfg
        # Basename of the initramfs generator (e.g. ``dracut``,
        # ``update-initramfs``, ``mkinitcpio``).  The ``rd.*`` kernel
        # arguments only exist on dracut systems; callers that do not pass
        # this get no ``rd.*`` advice rather than a wrong one.
        self.initramfs_tool = (os.path.basename(initramfs_tool)
                               if initramfs_tool else None)

    @staticmethod
    def _walk_block_devices(devices):
        """Yield every device in an ``lsblk -J`` tree, including nested ones.

        ``lsblk`` normally nests partitions under their disk in ``children``,
        but a flat list is also possible (containers, ZFS, loop/rom devices,
        single-partition hosts), so both shapes must be handled.
        """
        for device, _ancestors in WizValidator._walk_block_devices_with_ancestors(devices):
            yield device

    @staticmethod
    def _walk_block_devices_with_ancestors(devices):
        """Yield ``(device, ancestors)`` pairs from an ``lsblk -J`` tree.

        ``ancestors`` runs from the outermost disk down to the device's
        parent, so a mounted filesystem can be checked for the LUKS/LVM
        layers it sits on.
        """
        stack = [(device, ()) for device in devices]
        while stack:
            device, ancestors = stack.pop()
            if not isinstance(device, dict):
                continue
            yield device, ancestors
            children = device.get('children')
            if isinstance(children, list):
                stack.extend((child, ancestors + (device,))
                             for child in children)

    @staticmethod
    def _mountpoints(device):
        """Return the mountpoints lsblk reported for one device node.

        util-linux >= 2.37 emits ``mountpoints`` (a list, because btrfs
        subvolumes can be mounted several times); older versions emit the
        singular ``mountpoint`` string.
        """
        mounts = device.get('mountpoints')
        if mounts is None:
            mounts = device.get('mountpoint')
        if isinstance(mounts, str):
            mounts = [mounts]
        elif not isinstance(mounts, list):
            mounts = []
        return [mount for mount in mounts if isinstance(mount, str) and mount]

    @classmethod
    def _is_luks(cls, device):
        """True when this node is a LUKS container."""
        return str(device.get('fstype') or '').lower() in cls.LUKS_FSTYPES

    @classmethod
    def _is_lvm(cls, device):
        """True when this node is an LVM physical volume."""
        return (str(device.get('fstype') or '').lower() in cls.LVM_FSTYPES
                or str(device.get('parttype') or '').lower() == cls.GPT_LINUX_LVM)

    def probe_disk_layout(self) -> SimpleNamespace:
        """
        Performs a quick heuristic scan using lsblk to determine key disk layout flags.
        The result is cached to ensure the subprocess is run only once.

        Returns:
            SimpleNamespace with ``has_another_os``, ``is_luks_active`` and
            ``is_lvm_active`` (any device on the machine) plus
            ``root_is_luks`` and ``root_is_lvm`` (only when the filesystem
            mounted at ``/`` sits on that layer).
        """
        # 1. Check Cache
        if self._disk_layout_cache is not None:
            return self._disk_layout_cache

        # 2. Set Initial State
        result = SimpleNamespace(
            has_another_os=False,
            is_luks_active=False,
            is_lvm_active=False,
            # True only when the *root* filesystem sits on that layer.
            # A LUKS/LVM data disk needs no boot-time kernel argument.
            root_is_luks=False,
            root_is_lvm=False,
        )

        # lsblk is fast and outputs in JSON format.  The JSON keys are always
        # lowercase ("fstype", "parttype", "rm", "type") even though the -o
        # column names are conventionally written in uppercase.
        # MOUNTPOINTS exists in util-linux >= 2.37; fall back to the singular
        # column so older distros still get root-chain detection.
        try:
            process = subprocess.run(
                ['lsblk', '-o', 'FSTYPE,PARTTYPE,RM,TYPE,MOUNTPOINTS', '-J'],
                capture_output=True,
                text=True,
                check=False
            )
            if process.returncode != 0:
                process = subprocess.run(
                    ['lsblk', '-o', 'FSTYPE,PARTTYPE,RM,TYPE,MOUNTPOINT', '-J'],
                    capture_output=True,
                    text=True,
                    check=False
                )

            if process.returncode != 0:
                # If lsblk fails (e.g., permissions), return the default 'False' result
                self._disk_layout_cache = result
                return result

            data = json.loads(process.stdout)

            # 3. Scan every block device, flat or nested
            for device, ancestors in self._walk_block_devices_with_ancestors(
                    data.get('blockdevices', [])):
                fstype = str(device.get('fstype') or '').lower()
                parttype = str(device.get('parttype') or '').lower()
                device_type = str(device.get('type') or '').lower()
                removable = device.get('rm') in (True, 1, '1')

                # Optical and loop devices never indicate another OS.
                if device_type in ('loop', 'rom'):
                    continue

                # --- A. Other OS Detection (Windows/Other) ---
                # Every UEFI system has a vfat EFI System Partition, so vfat
                # alone proves nothing.  Only filesystems/partition types that
                # are essentially Windows-specific count, and removable media
                # (USB sticks, SD cards) is ignored to avoid false positives.
                if not removable and (fstype in self.OTHER_OS_FSTYPES
                                      or parttype in self.WINDOWS_PARTTYPES):
                    result.has_another_os = True

                # --- B. LUKS/LVM Detection (Requires Special Kernel Args) ---

                # LUKS Check
                if fstype in self.LUKS_FSTYPES:
                    result.is_luks_active = True

                # LVM Check (FSTYPE or PARTTYPE)
                if fstype in self.LVM_FSTYPES or parttype == self.GPT_LINUX_LVM:
                    result.is_lvm_active = True

                # --- C. Root filesystem backing (for rd.* validation) ---
                # Only the root chain needs a boot-time rd.luks.uuid /
                # rd.lvm.vg; a LUKS or LVM data disk elsewhere does not.
                if '/' in self._mountpoints(device):
                    result.root_is_luks = result.root_is_luks or any(
                        self._is_luks(node) for node in ancestors)
                    result.root_is_lvm = result.root_is_lvm or any(
                        self._is_lvm(node) for node in ancestors)

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

                    # Collect one key per OS (its \EFI\<dir> directory).
                    # A single OS often registers several loaders (shim, grub,
                    # fallback) that point at the same directory, and counting
                    # those separately would report a false multi-boot.
                    os_boot_dirs = set()
                    for line in efi_process.stdout.split('\n'):
                        upper_line = line.upper()
                        if not (line.startswith('Boot') and '*' in line):
                            continue

                        # Must have device info (HD(...))
                        if 'HD(' not in line:
                            continue

                        # Must NOT be the generic BOOT fallback directory
                        # Check both Windows-style and Unix-style path separators
                        if r'\EFI\BOOT\BOOT' in upper_line or '/EFI/BOOT/BOOT' in upper_line:
                            continue

                        loader_dir = re.search(r'[\\/]EFI[\\/]([^\\/]+)[\\/]', upper_line)
                        os_boot_dirs.add(loader_dir.group(1) if loader_dir else upper_line)

                    # If 2+ OS-specific boot directories, likely multi-boot setup
                    if len(os_boot_dirs) >= 2:
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
        def exist(value):
            """Returns True if value is set (not #comment, #absent, or None)"""
            return value not in (GrubFile.ABSENT, GrubFile.COMMENT, None, '')
        def avi(value):
            """Returns value if not void, else '#' (won't match any real GRUB value)"""
            return value if exist(value) else '#'
        def empty(value):
            return avi(value) in ('#', '', '""', "''")
        def unquote(value):
            if isinstance(value, str):
                if value.startswith("'"):
                    return value[1:].rstrip("'")
                if value.startswith('"'):
                    return value[1:].rstrip('"')
            return value
        def quotes(param): # all forms of simple value in grub config
            return (param, f'"{param}"', f"'{param}'")
        def has_unquoted_space(value):
            """True when value has whitespace outside single/double quotes.

                ``quotes(unquote(v))`` cannot be used to detect quoting: it also
                returns the bare (unquoted) form, so every value matched and the
                "must be quoted" rules could never fire.
                """
            if not isinstance(value, str):
                return False
            in_single = in_double = False
            for char in value:
                if char == "'" and not in_double:
                    in_single = not in_single
                elif char == '"' and not in_single:
                    in_double = not in_double
                elif char.isspace() and not in_single and not in_double:
                    return True
            return False
        def sh(param, fallback=None): # "ShortHand": reduce GRUB_TIMEOUT to TIMEOUT
            # ``getvals`` yields None for a cross-referenced parameter that is
            # absent from the active set, so never index a missing name blindly.
            if isinstance(param, str) and param.startswith('GRUB_'):
                return param[5:]
            return fallback if fallback is not None else str(param)
        def hey(param, severity, message):
            nonlocal warns, stars
            if param not in warns:
                warns[param] = []
            warns[param].append((stars[severity], message))

        def getvals(*keys):
            """ Returns (k1, v1, k2, v2, ...) pairs.

                 A key absent from the active parameter set yields (None, None)
                 for its own pair, but the remaining requested keys are still
                 returned normally.  Collapsing the whole tuple to Nones when
                 *any* key was missing hid present values, so discovery removing
                 one parameter silently disabled every rule that referenced it.
            """
            nonlocal vals
            result = []
            for key in keys:
                if key in vals:
                    result.extend((key, vals[key]))
                else:
                    result.extend((None, None))
            return tuple(result)

        def hey_if(bad, param_name, severity, message):
            nonlocal all_warn_info
            if bad:
                hey(param_name, severity, message)
            if param_name:
                key = WarnDB.make_key(param_name, message)
                all_warn_info[key] = severity
        # ------------------------------------------------ #

        stars = [''] + '* ** *** ****'.split()
        warns, all_warn_info = {}, {}
        layout = self.probe_disk_layout()

        # if _DEFAULT is saved, then _SAVEDEFAULT cannot be false
        p1, v1, p2, v2 = getvals('GRUB_DEFAULT', 'GRUB_SAVEDEFAULT')
        bad = p1 and avi(v1) in quotes('saved') and avi(v2) in quotes('false')
        hey_if(bad, p1, 4, f'when "saved", {sh(p2)} cannot be "false"')
        hey_if(bad, p2, 4, f'when "false", {sh(p1)} cannot be "saved"')

        # TIMEOUT=0 & TIMEOUT_STYLE=hidden (critical - unrecoverable state)
        p1, v1, p2, v2 = getvals('GRUB_TIMEOUT', 'GRUB_TIMEOUT_STYLE')
        bad = p1 and (avi(v1) in quotes('0') or avi(v1) in quotes('0.0')) and avi(v2) in quotes('hidden')
        hey_if(bad, p1, 4, f'when 0, {sh(p2)} cannot be "hidden"')
        hey_if(bad, p2, 4, f'when "hidden", {sh(p1)} cannot be 0')

        # 'splash' belongs only in GRUB_CMDLINE_LINUX_DEFAULT
        p1, v1, p2, v2 = getvals('GRUB_CMDLINE_LINUX_DEFAULT', 'GRUB_CMDLINE_LINUX')
        bad = p2 and re.search(r'\b(splash|quiet|rhgb)\b', avi(v2))
        hey_if(bad, p2, 3,
               f'splash/quiet/rhgb belong only in {sh(p1, "GRUB_CMDLINE_LINUX_DEFAULT")}')

        # ``rd.luks.uuid=`` / ``rd.lvm.vg=`` are dracut's interface.  Debian
        # and Ubuntu unlock through /etc/crypttab (initramfs-tools) and Arch
        # uses ``cryptdevice=`` (mkinitcpio), so their absence is normal on
        # those systems.  Even on dracut the argument is only needed when the
        # root filesystem itself is encrypted; an encrypted data disk needs
        # nothing at boot.  Both cmdline variables are read because dracut
        # consumes the merged /proc/cmdline.
        uses_dracut = self.initramfs_tool == 'dracut'
        p1, v1, p2, v2 = getvals('GRUB_CMDLINE_LINUX',
                                 'GRUB_CMDLINE_LINUX_DEFAULT')
        boot_args = f'{avi(v1)} {avi(v2)}'

        bad = (bool(p1) and uses_dracut
               and getattr(layout, 'root_is_luks', False)
               and 'rd.luks.uuid=' not in boot_args)
        hey_if(bad, p1, 3,
               'root is on LUKS but no "rd.luks.uuid=" (dracut needs it)')

        bad = (bool(p1) and uses_dracut
               and getattr(layout, 'root_is_lvm', False)
               and 'rd.lvm.vg=' not in boot_args)
        hey_if(bad, p1, 3,
               'root is on LVM but no "rd.lvm.vg=" (dracut needs it)')

        # ENABLE_CRYPTODISK without LUKS
        p1, v1 = getvals('GRUB_ENABLE_CRYPTODISK')
        bad = p1 and avi(v1) in quotes('true') and not layout.is_luks_active
        hey_if(bad, p1, 1, 'enabled but no LUKS encryption detected')

        # Recovery cmdline set but recovery disabled
        p1, v1, p2, v2 = getvals('GRUB_CMDLINE_LINUX_RECOVERY', 'GRUB_DISABLE_RECOVERY')
        bad = p1 and not empty(v1) and avi(v2) in quotes('true')
        hey_if(bad, p1, 2, f'when set, {sh(p2)} must not be "true"')
        hey_if(bad, p2, 2, f'when "true", {sh(p1)} should not be set')

        # UUID types disabled (both or individually)
        p1, v1, p2, v2 = getvals('GRUB_DISABLE_LINUX_UUID', 'GRUB_DISABLE_LINUX_PARTUUID')
        both_disabled = p1 and avi(v1) in quotes('true') and avi(v2) in quotes('true')
        only_p1 = p1 and avi(v1) in quotes('true') and avi(v2) not in quotes('true')
        only_p2 = p2 and avi(v2) in quotes('true') and avi(v1) not in quotes('true')
        hey_if(both_disabled, p1, 2, 'using device names for everything is fragile')
        hey_if(both_disabled, p2, 2, 'using device names for everything is fragile')
        hey_if(only_p1, p1, 1, 'disabling UUID may cause boot issues')
        hey_if(only_p2, p2, 1, 'disabling PARTUUID may cause boot issues')

        # Terminal INPUT should match OUTPUT when serial
        p1, v1, p2, v2 = getvals('GRUB_TERMINAL_INPUT', 'GRUB_TERMINAL_OUTPUT')
        val_in = unquote(avi(v1)) if exist(v1) else 'console'
        val_out = unquote(avi(v2)) if exist(v2) else ''
        bad = p1 and exist(v1) and val_out and val_in != val_out and 'serial' in val_out
        hey_if(bad, p1, 2, f'{sh(p2)} must have matching value')

        # Terminal OUTPUT should match INPUT when serial
        p1, v1, p2, v2 = getvals('GRUB_TERMINAL_INPUT', 'GRUB_TERMINAL_OUTPUT')
        val_in = unquote(avi(v1)) if exist(v1) else 'console'
        val_out = unquote(avi(v2)) if exist(v2) else ''
        bad = p2 and exist(v2) and val_out and val_in != val_out and 'serial' in val_in
        hey_if(bad, p2, 2, f'{sh(p1)} must have matching value')

        # SERIAL_COMMAND set but neither terminal is serial
        p1, v1, p2, v2, p3, v3 = getvals('GRUB_SERIAL_COMMAND', 'GRUB_TERMINAL_INPUT', 'GRUB_TERMINAL_OUTPUT')
        term_in = unquote(avi(v2)) if exist(v2) else 'console'
        term_out = unquote(avi(v3)) if exist(v3) else ''
        bad = p1 and exist(v1) and 'serial' not in term_out and 'serial' not in term_in
        hey_if(bad, p1, 2,
               f'set but neither {sh(p2, "GRUB_TERMINAL_INPUT")} or '
               f'{sh(p3, "GRUB_TERMINAL_OUTPUT")} are "serial"')

        # TERMINAL_INPUT is serial but no SERIAL_COMMAND
        p1, v1, p2, v2 = getvals('GRUB_SERIAL_COMMAND', 'GRUB_TERMINAL_INPUT')
        term_in = unquote(avi(v2)) if exist(v2) else 'console'
        # Only warn when SERIAL_COMMAND is itself part of the active set;
        # otherwise the warning would be attached to a non-existent parameter.
        bad = p1 and p2 and 'serial' in term_in and not exist(v1)
        hey_if(bad, p1, 2, f'when not set, {sh(p2)} cannot be "serial"')
        hey_if(bad, p2, 2, f'when "serial", {sh(p1)} must be set')

        # TERMINAL_OUTPUT is serial but no SERIAL_COMMAND
        p1, v1, p2, v2 = getvals('GRUB_SERIAL_COMMAND', 'GRUB_TERMINAL_OUTPUT')
        term_out = unquote(avi(v2)) if exist(v2) else ''
        bad = p1 and p2 and 'serial' in term_out and not exist(v1)
        hey_if(bad, p1, 2, f'when not set, {sh(p2)} cannot be "serial"')
        hey_if(bad, p2, 2, f'when "serial", {sh(p1)} must be set')

        # GRUB_TERMINAL contains serial but no SERIAL_COMMAND
        p1, v1, p2, v2 = getvals('GRUB_SERIAL_COMMAND', 'GRUB_TERMINAL')
        terminal = unquote(avi(v2))
        bad = p1 and p2 and 'serial' in terminal and not exist(v1)
        hey_if(bad, p1, 2, f'when not set, {sh(p2)} cannot be "serial"')
        hey_if(bad, p2, 2, f'when "serial", {sh(p1)} must be configured')

        # GRUB_TERMINAL=console with graphical settings (GFXMODE, BACKGROUND, THEME)
        p1, v1, p2, v2, p3, v3, p4, v4 = getvals('GRUB_TERMINAL', 'GRUB_GFXMODE', 'GRUB_BACKGROUND', 'GRUB_THEME')
        terminal = unquote(avi(v1))
        has_gfx = (p2 and exist(v2)) or (p3 and exist(v3)) or (p4 and exist(v4))
        bad = p1 and terminal == 'console' and has_gfx
        hey_if(bad, p1, 1, 'console mode ignores graphical settings')

        # GRUB_TERMINAL contains gfxterm but GFXMODE not set
        p1, v1, p2, v2 = getvals('GRUB_TERMINAL', 'GRUB_GFXMODE')
        terminal = unquote(avi(v1))
        bad = p1 and 'gfxterm' in terminal and not exist(v2)
        hey_if(bad, p1, 1, f'when gfxterm, {sh(p2, "GRUB_GFXMODE")} should be set')

        # SAVEDEFAULT=true but DEFAULT is numeric (menu can reorder)
        p1, v1, p2, v2 = getvals('GRUB_SAVEDEFAULT', 'GRUB_DEFAULT')
        default_value = avi(v2) if exist(v2) else '0'
        # Require DEFAULT to be active: otherwise the second warning would be
        # filed under a None key for a parameter discovery already removed.
        bad = p1 and p2 and avi(v1) in quotes('true') and unquote(default_value).isdigit()
        hey_if(bad, p1, 1, f'when "true", {sh(p2, "GRUB_DEFAULT")} should not be numeric')
        hey_if(bad, p2, 1, f'avoid numeric when {sh(p1, "GRUB_SAVEDEFAULT")}="true"')

        # GRUB_CMDLINE_LINUX has spaces but not quoted
        p1, v1 = getvals('GRUB_CMDLINE_LINUX')
        bad = p1 and exist(v1) and has_unquoted_space(str(avi(v1)))
        hey_if(bad, p1, 2, 'has spaces and thus must be quoted')

        # GRUB_CMDLINE_LINUX_DEFAULT has spaces but not quoted
        p1, v1 = getvals('GRUB_CMDLINE_LINUX_DEFAULT')
        bad = p1 and exist(v1) and has_unquoted_space(str(avi(v1)))
        hey_if(bad, p1, 2, 'has spaces and thus must be quoted')

        # GRUB_BACKGROUND path doesn't exist
        p1, v1 = getvals('GRUB_BACKGROUND')
        exists, _ = self.get_full_path_and_check_existence(v1) if exist(v1) else (True, '')
        bad = p1 and exist(v1) and not exists
        hey_if(bad, p1, 2, 'path does not seem to exist')

        # GRUB_THEME path doesn't exist
        p1, v1 = getvals('GRUB_THEME')
        exists, _ = self.get_full_path_and_check_existence(v1) if exist(v1) else (True, '')
        bad = p1 and exist(v1) and not exists
        hey_if(bad, p1, 2, 'path does not seem to exist')

        # GFXMODE set but not a known safe value
        p1, v1 = getvals('GRUB_GFXMODE')
        safe_modes = {'640x480', '800x600', '1024x768', 'auto', 'keep'}
        modes = [m.strip().lower() for m in unquote(v1).split(',')] if exist(v1) else []
        unsafe_modes = [m for m in modes if m not in safe_modes]
        bad = p1 and exist(v1) and len(unsafe_modes) > 0
        hey_if(bad, p1, 1, 'perhaps unsupported; stick to common values')

        # GRUB_DISTRIBUTOR missing or empty (not a shell command)
        p1, v1 = getvals('GRUB_DISTRIBUTOR')
        # Do not require ``exist(v1)``: this rule exists precisely for the
        # missing value, and ABSENT, COMMENT and '' all fail ``exist``.  Only a
        # non-empty value (or a command substitution) is acceptable.
        val = unquote(v1) if exist(v1) else ''
        val = str(val).strip()
        is_shell_cmd = val.startswith('$(') or val.startswith('`')
        bad = bool(p1) and not is_shell_cmd and not val
        hey_if(bad, p1, 2, 'should be distro name (it is missing/empty)')

        # OS-PROBER disabled on dual-boot system
        p1, v1 = getvals('GRUB_DISABLE_OS_PROBER')
        bad = p1 and avi(v1) in quotes('true') and layout.has_another_os
        hey_if(bad, p1, 2, 'suggest setting "false" since multi-boot detected')

        # OS-PROBER enabled but no multi-boot detected
        p1, v1 = getvals('GRUB_DISABLE_OS_PROBER')
        bad = p1 and exist(v1) and v1 not in quotes('true') and not layout.has_another_os
        hey_if(bad, p1, 1, 'perhaps set "true" since no multi-boot detected?')

        # Check parameters with fixed list of possible values (enums)
        for param_name, cfg in self.param_cfg.items():
            enums = cfg.get('enums', None)
            regex = cfg.get('edit_re', None)
            has_enums = isinstance(enums, dict) and len(enums) > 0
            has_no_regex = not regex

            if has_enums and has_no_regex:
                p1, v1 = getvals(param_name)
                # Reset per parameter: `bad` otherwise carries over from the
                # previous rule and can emit a warning for an absent parameter.
                bad = False
                if p1 and exist(v1):
                    value = str(unquote(v1))
                    found = any(value == unquote(str(k)) for k in enums.keys())
                    bad = not found
                hey_if(bad, p1, 3, 'value not in list of allowed values')

        # GRUB_TIMEOUT over recommended limit
        p1, v1 = getvals('GRUB_TIMEOUT')
        val = str(unquote(v1)) if exist(v1) else ''
        bad = p1 and exist(v1) and val and val.isdigit() and int(val) > 60
        hey_if(bad, p1, 1, 'over 60s seems ill advised')

        # GRUB_TIMEOUT set to -1 (wait indefinitely)
        p1, v1 = getvals('GRUB_TIMEOUT')
        val = str(unquote(v1)) if exist(v1) else ''
        bad = p1 and exist(v1) and val in ('-1', '"-1"', "'-1'")
        hey_if(bad, p1, 1, '-1 (wait indefinitely) seems ill advised')

        # GRUB_RECORDFAIL_TIMEOUT over recommended limit
        p1, v1 = getvals('GRUB_RECORDFAIL_TIMEOUT')
        val = str(unquote(v1)) if exist(v1) else ''
        bad = p1 and exist(v1) and val and val.isdigit() and int(val) > 120
        hey_if(bad, p1, 1, 'over 120s seems ill advised')

        return warns, all_warn_info

    def demo(self, param_defaults):
        """ TBD """
        def dump(title):
            nonlocal warnings
            print(f'\n{title}')
            if not warnings:
                print('  (no warnings)')
            else:
                for param, pairs in warnings:
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
