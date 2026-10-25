#!/usr/bin/env python3
"""
Handles updating /etc/default/grub and running grub-install
"""
# pylint: disable=line-too-long,invalid-name

import os
import sys
import shutil
import subprocess
import glob
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from .DistroVars import DistroVars
from .UserConfigDir import UserConfigDir

class GrubWriter:
    """
    A class for safely writing and updating GRUB configuration files.

    This class caches the system's GRUB update command on initialization,
    avoiding repeated lookups during the session.
    """

    def __init__(self, distro_vars: DistroVars, user_config=None):
        """
        Initialize the GrubWriter.

        Args:
            distro_vars: DistroVars instance containing distribution-specific paths and commands
            user_config: optional UserConfigDir-compatible object (dependency
                injection for tests); defaults to the singleton.
        """
        self.distro_vars = distro_vars
        self.etc_grub = self.distro_vars.etc_grub
        self.user_config = user_config if user_config else UserConfigDir.get_singleton()

        # Cache the grub update command and config file path at initialization
        self.update_grub = distro_vars.update_grub
        self.grub_cfg = distro_vars.grub_cfg

        # Snapshot of the target captured by the last successful commit.
        # ``commit_and_update()`` restores this snapshot when the GRUB update
        # fails, so a rejected change never survives a reboot.
        self._rollback_target: Optional[Path] = None
        self._rollback_bytes: bytes = b''
        self._rollback_existed: bool = False
        self._rollback_captured: bool = False

    def run_grub_update(self) -> Tuple[bool, str]:
        """
        Executes the appropriate GRUB update command found on the system.
        This step is MANDATORY after modifying /etc/default/grub.

        Returns:
            A tuple (success: bool, message: str)
        """
        if os.geteuid() != 0:
            return False, "ERROR: root required to run GRUB update command"

        if not self.update_grub:
            return False, "ERROR: cannot find GRUB update cmd"

        # Build the command array
        command_to_run: List[str] = [self.update_grub]

        if self.update_grub.endswith('-mkconfig') and self.grub_cfg:
            # If using grub-mkconfig or grub2-mkconfig,
            # we must provide the output flag and path
            command_to_run.extend(["-o", str(self.grub_cfg)])

        print(f"+  {' '.join(command_to_run)}")
        try:
            # Execute the command - output streams directly to terminal
            result = subprocess.run(command_to_run, check=False)

            # Check for success
            if result.returncode != 0:
                return False, (
                    f"GRUB Update Failed: Command returned exit code {result.returncode}"
                )

            print("OK: GRUB config rebuilt")
            return True, 'OK'

        except (OSError, subprocess.SubprocessError) as e:
            return False, f"An unexpected error occurred during GRUB update execution: {e}"

    def should_rebuild_initramfs(self, diffs: dict) -> Tuple[bool, str, str]:
        """
        Determines if initramfs rebuild is needed based on parameter changes.

        Checks if changes to GRUB_CMDLINE_LINUX, GRUB_CMDLINE_LINUX_DEFAULT,
        or GRUB_CMDLINE_LINUX_RECOVERY contain keywords that affect early boot
        (GPU drivers, KMS, module loading, etc.).

        Args:
            diffs: Dictionary of parameter changes {param_name: (old_value, new_value)}

        Returns:
            Tuple of (needs_rebuild: bool, trigger_keyword: str, category: str)
            - needs_rebuild: True if initramfs rebuild is recommended
            - trigger_keyword: The specific keyword that triggered the recommendation
            - category: The category of the trigger (e.g., 'gpu_drivers', 'kernel_mode_setting')
        """
        # Parameters that affect early boot
        initramfs_params = {
            'GRUB_CMDLINE_LINUX',
            'GRUB_CMDLINE_LINUX_DEFAULT',
            'GRUB_CMDLINE_LINUX_RECOVERY',
        }

        # Flatten all trigger keywords from distro_vars
        triggers = self.distro_vars.initramfs_triggers
        if not triggers:
            return False, '', ''

        for param_name, (old_val, new_val) in diffs.items():
            if param_name not in initramfs_params:
                continue

            # Combine old and new values to check for any trigger keywords
            combined_cmdline = f"{old_val} {new_val}".lower()

            # Check each category of triggers
            for category, keywords in triggers.items():
                for keyword in keywords:
                    if keyword.lower() in combined_cmdline:
                        return True, keyword, category

        return False, '', ''

    def check_initramfs_space(self) -> Dict[str, any]:
        """
        Check if there's enough disk space in /boot to rebuild initramfs.

        Calculates space needed based on existing initramfs file sizes.
        Initramfs rebuild creates new files before deleting old ones,
        so we need approximately 2x the current size + safety margin.

        Returns:
            Dictionary with:
            - 'boot_path': Path to boot directory
            - 'free_mb': Free space in MB
            - 'needed_mb': Estimated space needed for rebuild in MB
            - 'existing_size_mb': Current size of all initramfs files in MB
            - 'existing_files': List of initramfs file paths found
            - 'is_sufficient': True if enough space available
            - 'is_critical': True if space is critically low
            - 'message': Human-readable status message
        """
        # Determine boot partition path from grub_cfg location
        boot_path = Path('/boot')
        if self.grub_cfg:
            grub_cfg_path = Path(self.grub_cfg)
            # grub.cfg is usually in /boot/grub or /boot/grub2
            # Find the /boot ancestor
            for parent in grub_cfg_path.parents:
                if parent.name == 'boot':
                    boot_path = parent
                    break

        try:
            # Find all initramfs/initrd files in /boot
            # Different distros use different naming conventions
            patterns = [
                str(boot_path / 'initrd.img-*'),
                str(boot_path / 'initrd-*'),
                str(boot_path / 'initramfs-*'),
                str(boot_path / 'initramfs.img-*'),
            ]

            existing_files = []
            for pattern in patterns:
                existing_files.extend(glob.glob(pattern))

            # Calculate total size of existing initramfs files
            total_size_bytes = 0
            for filepath in existing_files:
                try:
                    total_size_bytes += os.path.getsize(filepath)
                except OSError:
                    pass  # Skip files we can't stat

            existing_size_mb = total_size_bytes / (1024 * 1024)

            # Calculate space needed:
            # - 2x existing size (new files created before old ones deleted)
            # - +50MB safety margin for temp files and overhead
            safety_margin_mb = 50
            needed_mb = (existing_size_mb * 2) + safety_margin_mb

            # Check available space
            stat = os.statvfs(boot_path)
            free_bytes = stat.f_bavail * stat.f_frsize
            free_mb = free_bytes / (1024 * 1024)

            is_sufficient = free_mb >= needed_mb
            # Critical if we don't even have 1x the size (will likely fail mid-rebuild)
            is_critical = free_mb < existing_size_mb

            # Generate message
            if is_critical:
                message = (
                    f"CRITICAL: Only {free_mb:.0f}MB free in {boot_path}, "
                    f"but need ~{needed_mb:.0f}MB for rebuild.\n"
                    f"  Existing initramfs files: {existing_size_mb:.0f}MB\n"
                    f"  Rebuild creates new files before deleting old ones.\n"
                    f"  FREE UP SPACE or system may become unbootable!"
                )
            elif not is_sufficient:
                message = (
                    f"WARNING: Only {free_mb:.0f}MB free in {boot_path}, "
                    f"recommend {needed_mb:.0f}MB.\n"
                    f"  May work, but cutting it close. Consider freeing space first."
                )
            else:
                surplus_mb = free_mb - needed_mb
                message = (
                    f"OK: {free_mb:.0f}MB free in {boot_path} "
                    f"(need ~{needed_mb:.0f}MB, surplus: {surplus_mb:.0f}MB)"
                )

            return {
                'boot_path': str(boot_path),
                'free_mb': free_mb,
                'needed_mb': needed_mb,
                'existing_size_mb': existing_size_mb,
                'existing_files': existing_files,
                'is_sufficient': is_sufficient,
                'is_critical': is_critical,
                'message': message,
            }

        except (OSError, ValueError) as e:
            # If we can't check space, return safe defaults (assume it's risky)
            return {
                'boot_path': str(boot_path),
                'free_mb': -1,
                'needed_mb': -1,
                'existing_size_mb': -1,
                'existing_files': [],
                'is_sufficient': False,
                'is_critical': False,
                'message': f"Unable to check disk space: {e}",
            }

    def run_initramfs_update(self) -> Tuple[bool, str]:
        """
        Executes the appropriate initramfs update command for this distribution.

        Returns:
            A tuple (success: bool, message: str)
        """
        if os.geteuid() != 0:
            return False, "ERROR: root required to rebuild initramfs"

        initramfs_cmd = self.distro_vars.update_initramfs
        if not initramfs_cmd:
            return False, "WARNING: No initramfs update command found on this system"

        # Determine command name (basename) to choose proper arguments
        cmd_name = os.path.basename(initramfs_cmd)

        # Build command with distribution-specific arguments
        if cmd_name == 'update-initramfs':
            # Debian/Ubuntu: update all kernels
            command_to_run = [initramfs_cmd, '-u', '-k', 'all']
        elif cmd_name == 'dracut':
            # RHEL/Fedora/SUSE: regenerate all kernels, force overwrite
            command_to_run = [initramfs_cmd, '--regenerate-all', '--force']
        elif cmd_name == 'mkinitcpio':
            # Arch: process all presets
            command_to_run = [initramfs_cmd, '-P']
        elif cmd_name == 'mkinitfs':
            # Alpine: regenerate for current kernel
            command_to_run = [initramfs_cmd]
        elif cmd_name == 'genkernel':
            # Gentoo: regenerate initramfs
            command_to_run = [initramfs_cmd, '--install', 'initramfs']
        else:
            # Unknown command, try with no arguments
            command_to_run = [initramfs_cmd]

        print(f"+  {' '.join(command_to_run)}")
        try:
            # Execute the command - output streams directly to terminal
            result = subprocess.run(command_to_run, check=False)

            # Check for success
            if result.returncode != 0:
                return False, (
                    f"Initramfs rebuild failed: {' '.join(command_to_run)} "
                    f"returned exit code {result.returncode}"
                )

            print("OK: Initramfs rebuilt")
            return True, 'OK'

        except (OSError, subprocess.SubprocessError) as e:
            return False, f"Unexpected error during initramfs rebuild: {e}"

    def _validate_candidate(self, temp_path: Path, data: bytes) -> Tuple[bool, str]:
        """
        Reject a candidate that would break the bootloader configuration.

        ``/etc/default/grub`` is not GRUB script: distro GRUB scripts *source*
        it with a POSIX shell, so the authoritative syntax check is
        ``sh -n`` (parse without executing).  ``grub-script-check`` is run too
        when present, but only as an advisory diagnostic: it rejects valid
        files such as Ubuntu's stock ``GRUB_DISTRIBUTOR=`lsb_release ...```
        line (verified), so it must not gate the commit.

        Returns:
            A tuple (valid: bool, message: str)
        """
        if b'\x00' in data:
            return False, f"Validation Error: {temp_path} contains NUL bytes."

        shell = shutil.which('sh') or ('/bin/sh' if os.path.exists('/bin/sh') else None)
        checker = shutil.which('grub-script-check')

        if shell:
            check = subprocess.run(
                [shell, '-n', str(temp_path)],
                capture_output=True, text=True, check=False)
            if check.returncode != 0:
                detail = (check.stderr or check.stdout or '').strip()
                return False, (
                    f"Validation Error: shell syntax check failed "
                    f"({shell} -n {temp_path}): {detail}")
        elif checker:
            # No shell available (very unusual): fall back to the GRUB parser.
            check = subprocess.run(
                [checker, str(temp_path)],
                capture_output=True, text=True, check=False)
            if check.returncode != 0:
                detail = (check.stderr or check.stdout or '').strip()
                return False, f"Validation Error: grub-script-check failed: {detail}"
        else:
            print(f"Warning: no 'sh' or 'grub-script-check' found; "
                  f"{temp_path} was not syntax-checked", file=sys.stderr)

        # Advisory only - see the docstring for why this cannot be a gate.
        if shell and checker:
            check = subprocess.run(
                [checker, str(temp_path)],
                capture_output=True, text=True, check=False)
            if check.returncode != 0:
                detail = (check.stderr or check.stdout or '').strip().splitlines()
                detail = detail[0] if detail else ''
                print(f"Warning: grub-script-check rejected the candidate "
                      f"(advisory; {self.etc_grub} is shell, not GRUB script): {detail}",
                      file=sys.stderr)

        return True, 'OK'

    def commit_validated_grub_config(self, temp_path: Path) -> Tuple[bool, str]:
        """
        Validate and atomically install a staged GRUB defaults file.

        The process is:
        1. Read the staging file without following symlinks.
        2. Reject NUL bytes and fail when ``sh -n`` rejects the candidate.
        3. Snapshot the current target in memory and write a durable rollback
           copy in the root-owned system state directory.
        4. Atomically replace the target with ``os.replace()`` (same directory,
           mode 0644), restoring the previous content if the replace fails.

        The snapshot is retained so that ``rollback_last_commit()`` can undo the
        change after ``run_grub_update()`` fails.  Prefer ``commit_and_update()``,
        which sequences this correctly.

        Args:
            temp_path: Path to the staged candidate (should live in the same
                directory as the target so the rename is atomic).

        Returns:
            A tuple (success: bool, message: str)
        """
        # 1. Check for root permissions
        if os.geteuid() != 0:
            return False, f"Permission Error: Root access is required to modify {self.etc_grub} and run validation/update tools."

        temp_path = Path(temp_path)
        previous: bytes = b''
        have_previous = False

        try:
            # --- Step 2: Read and validate the candidate ---
            data = self.user_config.safe_read_bytes(temp_path)
            valid, why_not = self._validate_candidate(temp_path, data)
            if not valid:
                return False, why_not

            # --- Step 3: Snapshot the current target ---
            try:
                previous = self.user_config.safe_read_bytes(self.etc_grub)
                have_previous = True
            except FileNotFoundError:
                have_previous = False

            if have_previous:
                rollback = self.user_config.system_state_dir / 'last-known-good.grub'
                try:
                    self.user_config.atomic_root_write(rollback, previous, mode=0o600)
                except OSError as e:
                    print(f"Warning: could not write rollback copy: {e}", file=sys.stderr)

            # --- Step 4: Atomic install ---
            print(f'+ install {str(temp_path)!r} -> {str(self.etc_grub)!r}')
            self.user_config.atomic_root_write(self.etc_grub, data, mode=0o644)

            # Remember what to restore if the GRUB update rejects this file.
            self._rollback_target = Path(self.etc_grub)
            self._rollback_bytes = previous
            self._rollback_existed = have_previous
            self._rollback_captured = True

            return True, f"OK: replaced {self.etc_grub!r}"

        except PermissionError:
            return False, f"Permission Error: Cannot write to {self.etc_grub} or execute GRUB utilities."

        except (OSError, ValueError, subprocess.SubprocessError) as e:
            # Best-effort rollback: never leave a partially written target.
            if have_previous:
                try:
                    self.user_config.atomic_root_write(self.etc_grub, previous, mode=0o644)
                    return False, (f"Commit failed ({e}); previous {self.etc_grub} restored.")
                except (OSError, ValueError) as restore_exc:
                    msg = (f"CRITICAL: commit failed ({e}) and restoring the previous "
                           f"{self.etc_grub!r} also failed ({restore_exc}). "
                           f"A rollback copy should be in {self.user_config.system_state_dir}.")
                    print(msg, file=sys.stderr)
                    return False, msg
            return False, f"An unexpected error occurred during commit: {e}"

        finally:
            # --- Step 5: Clean up the staging file ---
            if temp_path and os.path.lexists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError as e:
                    print(f"Warning: Failed to rm temp file {temp_path}: {e}",
                          file=sys.stderr)

    def rollback_last_commit(self) -> Tuple[bool, str]:
        """
        Undo the most recent successful ``commit_validated_grub_config()``.

        Restores the exact bytes (or the absence) of the target that were
        captured before the commit.  Safe to call once per commit.

        Returns:
            A tuple (success: bool, message: str)
        """
        if os.geteuid() != 0:
            return False, "ERROR: root required to roll back the GRUB defaults file"

        if not self._rollback_captured or self._rollback_target is None:
            return False, "ERROR: no committed change is available to roll back"

        target = self._rollback_target
        try:
            if self._rollback_existed:
                self.user_config.atomic_root_write(
                    target, self._rollback_bytes, mode=0o644)
                return True, f"OK: restored the previous {target!r}"
            os.unlink(target)
            return True, f"OK: removed {target!r} (it did not exist before the commit)"
        except OSError as e:
            return False, f"ERROR: could not restore {target!r}: {e}"

    def commit_and_update(self, temp_path: Path,
                          update_runner=None) -> Tuple[bool, str]:
        """
        Commit a staged file, run the GRUB update, and roll back if it fails.

        Sequence:
        1. ``commit_validated_grub_config()`` (validate + atomic replace).
        2. Run the GRUB update command.
        3. On failure, restore the previous defaults file and re-run the update
           so ``grub.cfg`` matches the restored file.  The rejected file is
           never left in place for the next boot.

        Args:
            temp_path: Path to the staged candidate.
            update_runner: optional callable returning (success, message);
                defaults to ``self.run_grub_update`` (test seam).

        Returns:
            A tuple (success: bool, message: str)
        """
        update_runner = update_runner or self.run_grub_update

        committed, commit_msg = self.commit_validated_grub_config(temp_path)
        if not committed:
            return False, commit_msg

        updated, update_msg = update_runner()
        if updated:
            return True, commit_msg

        rollback_ok, rollback_msg = self.rollback_last_commit()
        if not rollback_ok:
            return False, (
                f"{update_msg}\n"
                f"CRITICAL: {self.etc_grub} was replaced but the GRUB update failed, "
                f"and the automatic rollback failed: {rollback_msg}\n"
                f"Do not reboot until {self.etc_grub} has been restored, e.g. from a "
                f"grub-wiz backup.")

        reupdated, reupdate_msg = update_runner()
        if not reupdated:
            return False, (
                f"{update_msg}\n"
                f"{rollback_msg}\n"
                f"WARNING: re-running the GRUB update after the rollback also failed: "
                f"{reupdate_msg}\n"
                f"{self.etc_grub} is back to its previous content, but {self.grub_cfg} "
                f"may still reflect the rejected change.")

        return False, (
            f"{update_msg}\n"
            f"{rollback_msg}\n"
            f"Rolled back and re-ran the GRUB update; {self.grub_cfg} matches the "
            f"previous {self.etc_grub}.")
