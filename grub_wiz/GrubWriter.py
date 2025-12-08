#!/usr/bin/env python3

import os
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple, Optional, List

# --- Constants ---

# The target file (requires root permission for writing)
GRUB_DEFAULT_PATH = Path("/etc/default/grub")

# The required validation tool on most Linux distributions
GRUB_CHECK_COMMAND = "grub-script-check"

# The commands to attempt for updating the configuration, in order of preference/availability
GRUB_UPDATE_COMMANDS = [
    "update-grub",        # High-level wrapper (Debian/Ubuntu)
    "grub2-mkconfig",     # RHEL/Fedora core tool
    "grub-mkconfig"       # Universal core tool (requires -o path)
]


class GrubWriter:
    """
    A class for safely writing and updating GRUB configuration files.

    This class caches the system's GRUB update command on initialization,
    avoiding repeated lookups during the session.
    """

    def __init__(self, target_path: Path = GRUB_DEFAULT_PATH):
        """
        Initialize the GrubWriter.

        Args:
            target_path: The path to the GRUB default configuration file.
        """
        self.target_path = target_path
        self.check_command = GRUB_CHECK_COMMAND

        # Cache the grub update command at initialization
        self._update_command, self._update_output_path = self._find_grub_update_command()

    def _find_grub_update_command(self) -> Tuple[Optional[str], Optional[Path]]:
        """
        Finds the correct command and output path for generating the GRUB config.

        Returns:
            A tuple (command: str or None, output_path: Path or None)
        """
        if os.geteuid() != 0:
            return None, None

        for command in GRUB_UPDATE_COMMANDS:
            if shutil.which(command):
                # 1. High-level wrapper: update-grub
                if command == "update-grub":
                    # update-grub is self-contained and handles its own path
                    return command, None

                # 2. Low-level core tools: grub-mkconfig or grub2-mkconfig
                elif command in ["grub-mkconfig", "grub2-mkconfig"]:
                    # The output path varies by distro/UEFI/BIOS.
                    # We prioritize the RHEL/Fedora standard path for the 'grub2-' variant,
                    # and the Debian/Arch standard path for the 'grub-' variant.

                    # Note: Detecting the *absolute* correct path is complex (involving
                    # checking /etc/grub2.cfg symlinks, UEFI status, etc.).
                    # For robust code, we stick to the most common default paths.

                    if command == "grub2-mkconfig":
                        # RHEL/Fedora style: /boot/grub2/grub.cfg (BIOS/Legacy)
                        return command, Path("/boot/grub2/grub.cfg")
                    else:
                        # Debian/Arch style: /boot/grub/grub.cfg (Universal fallback)
                        return command, Path("/boot/grub/grub.cfg")

        return None, None

    def run_grub_update(self) -> Tuple[bool, str]:
        """
        Executes the appropriate GRUB update command found on the system.
        This step is MANDATORY after modifying /etc/default/grub.

        Returns:
            A tuple (success: bool, message: str)
        """
        if os.geteuid() != 0:
            return False, "ERROR: root required to run GRUB update command"

        if not self._update_command:
            return False, "ERROR: cannot find GRUB updater (update-grub, grub-mkconfig, and grub2-mkconfig) not on $PATH"

        # Build the command array
        command_to_run: List[str] = [self._update_command]

        if self._update_output_path:
            # If using grub-mkconfig or grub2-mkconfig, we must provide the output flag and path
            command_to_run.extend(["-o", str(self._update_output_path)])

        print(f"+  {' '.join(command_to_run)}")
        try:
            # Execute the command
            result = subprocess.run(
                command_to_run,
                capture_output=True,
                text=True,
                check=False
            )

            # Check for success
            if result.returncode != 0:
                error_output = result.stdout.strip() + "\n" + result.stderr.strip()
                return False, (
                    f"GRUB Update Failed: Command {' '.join(command_to_run)} returned an error (Exit code {result.returncode}).\n"
                    f"---------------------------------------------------\n"
                    f"{error_output}"
                )

            print(f"OK: GRUB config rebuilt: Output:\n{result.stdout.strip()}")
            return True, 'OK'

        except Exception as e:
            return False, f"An unexpected error occurred during GRUB update execution: {e}"

    def commit_validated_grub_config(self, contents: str) -> Tuple[bool, str]:
        """
        Safely commits new GRUB configuration contents to the target file.

        The process is:
        1. Write contents to a secure temporary file.
        2. Run 'grub-script-check' on the temporary file.
        3. If validation succeeds, copy the temporary file over the target_path.
        4. Explicitly set permissions to 644 (rw-r--r--) for security and readability.
        5. If validation fails, delete the temporary file and return the error.

        NOTE: The caller should call run_grub_update() immediately after this method
        if commit is successful.

        Args:
            contents: The new content of the /etc/default/grub file as a string.

        Returns:
            A tuple (success: bool, message: str)
            - If success is True, message is a confirmation.
            - If success is False, message contains the error and grub-script-check output.
        """
        # 1. Check for root permissions
        if os.geteuid() != 0:
            return False, f"Permission Error: Root access is required to modify {self.target_path} and run validation/update tools."

        temp_file: Optional[tempfile._TemporaryFileWrapper] = None

        try:
            # --- Step 1: Write to a Secure Temporary File ---
            temp_file = tempfile.NamedTemporaryFile(
                mode='w',
                delete=False,
                encoding='utf-8',
                suffix=".grub_check"
            )
            temp_file.write(contents)
            temp_file.close()

            temp_path = Path(temp_file.name)

            # --- Step 2: Run grub-script-check Validation ---

            cmd = [self.check_command, str(temp_path)]

            print(f'+ {cmd[0]} {str(cmd[1])!r}')

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode != 0:
                error_output = result.stdout.strip() + "\n" + result.stderr.strip()
                return False, (
                    f"FAILED: {self.check_command} returned {result.returncode}.\n"
                    f"Your changes were NOT saved to {self.target_path}.\n"
                    f"---------------------------------------------------\n"
                    f"{error_output}"
                )

            # --- Step 3: Commit/Copy the Validated File ---
            print(f'+ cp {str(temp_path)!r} {str(self.target_path)!r}')
            shutil.copy2(temp_path, self.target_path)

            # --- Step 4: Explicitly set permissions to 644 (rw-r--r--) ---
            # This guarantees the standard permissions for /etc/default/grub
            # The octal '0o644' means: owner (6=rw-), group (4=r--), others (4=r--)
            os.chmod(self.target_path, 0o644)

            return True, f"OK: replaced {self.target_path!r}"

        except FileNotFoundError:
            return False, f"Error: Required utility '{self.check_command}' not found. Please ensure GRUB is correctly installed."

        except PermissionError:
            return False, f"Permission Error: Cannot write to {self.target_path} or execute GRUB utilities."

        except Exception as e:
            return False, f"An unexpected error occurred during commit: {e}"

        finally:
            # --- Step 5: Clean up the temporary file ---
            if temp_file and os.path.exists(temp_file.name):
                try:
                    os.unlink(temp_file.name)
                except Exception as e:
                    print(f"Warning: Failed to clean up temporary file {temp_file.name}: {e}", file=sys.stderr)


# --- Example Usage (Not runnable without root/grub-script-check) ---
if __name__ == '__main__':
    print("--- Example: GRUB Configuration Writer ---")
    print("This requires root privileges and installed GRUB utilities to run successfully.")
    
    # Example of valid content
    valid_content = "GRUB_TIMEOUT=5\nGRUB_DEFAULT=0\nGRUB_CMDLINE_LINUX_DEFAULT=\"quiet splash\"\n"
    
    # Simulate commit to a non-critical file for testing (still needs root for permissions checks)
    # Note: If grub-mkconfig is found, it will try to write to /boot/grub/grub.cfg which needs root.
    
    # 1. Create a GrubWriter instance
    # writer = GrubWriter()

    # 2. Attempt commit (requires root)
    # success, message = writer.commit_validated_grub_config(valid_content)
    # print(f"Commit Success: {success}\nMessage: {message}")

    # 3. If commit succeeded, attempt update (requires root)
    # if success:
    #     update_success, update_message = writer.run_grub_update()
    #     print(f"\nUpdate Success: {update_success}\nMessage: {update_message}")
    # else:
    #     print("\nSkipping GRUB update due to failed commit.")