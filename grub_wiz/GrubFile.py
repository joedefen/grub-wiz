#!/usr/bin/env python3
"""
GrubFile:
  On READING:
    - parses /etc/default/grub (or substitute)
    - associates lines (commented or not) with supported params
    - creates special values for params w/o a read value:
      - '#comment' if commented out
      - '#absent' if entirely missing
  On WRITING (after params are edited):
    - if multiple uncommented lines for same param, will
      comment out all but last when written (and the last
      could become commented out)
    - if a param has no uncommented lines but some comment lines, if
      that param is given a legal value, it replaces the
      last comment line when written
    - absent param given a legal value will be placed at
      the end as such:
        - an empty line
        - the "guidance" lines commented out
        - param=value
"""
# pylint: disable=line-too-long,broad-exception-caught
# pylint: disable=too-many-branches
import sys
import re
import textwrap
from typing import List, Dict, Optional, Any #, Union
from types import SimpleNamespace
from pathlib import Path
try:
    from .CannedConfig import CannedConfig
    from .DistroVars import DEFAULT_ETC_GRUB
    from .ParamDiscovery import ParamDiscovery
    from .UserConfigDir import UserConfigDir
except Exception:
    from CannedConfig import CannedConfig
    from DistroVars import DEFAULT_ETC_GRUB
    from ParamDiscovery import ParamDiscovery
    from UserConfigDir import UserConfigDir


class GrubFile:
    """
    Manages reading, modifying, and writing the /etc/default/grub configuration file.

    It preserves unmanaged lines and correctly handles comment detection (ignoring
    # inside quotes) and the 'Zap' (remove/reset to default) action.
    """
    COMMENT = '∎' # "value" of comment lines
    ABSENT = '≡' # "value" of absent lines
    # Keep a single source of truth for the fallback path (audit M10);
    # ``DistroVars.etc_grub`` is the value the application actually uses.
    std_location = DEFAULT_ETC_GRUB

    def __init__(self,  supported_params: Dict[str, Any], file_path: Optional[str]=None):
        """
        Initializes the parser and reads the file immediately.
        """
        self.file_path = file_path if file_path else GrubFile.std_location
        # Work on a copy: read_file() adopts unvalidated params by adding them
        # to supported_params, and callers reuse their config dict (e.g. the
        # compare screen builds several GrubFile instances from gw.param_cfg).
        self.supported_params = dict(supported_params)
        self.lines: List[str] = []
        self.param_of: List[Optional[str]] = []
        # Structure: {PARAM: {'line_num': int/None, 'value': str, 'new_value': str/None}}
        self.param_data: Dict[str, Dict[str, Any]] = {}
        # Unvalidated params discovered in grub file
        self.extra_params: Dict[str, Dict[str, Any]] = {}
        # Params using variable expansion - don't manage these
        self.blacklisted_params: set = set()
        self.discovery = ParamDiscovery.get_singleton()

        self.read_file()

    def _initialize_param_data(self):
        """Pre-fills the data structure with all supported params set to ABSENT."""
        for param in self.supported_params:
            self.param_data[param] = SimpleNamespace(
                line_num=None,
                value=self.ABSENT, # current value unless parameter in file
                                   # or parameter is in comment (then self.COMMENT)
                new_value=None,    # updated value by user (later)
                out_value=None,    # value if in comment (and .value==self.COMMENT)
                )

    # --- Core Parsing Methods ---

    def _cleanse(self, value_part: str) -> str:
        """
        Extracts the parameter value from a line, correctly clipping any unquoted comments.

        Example: 'GRUB_TIMEOUT=5 # 10 seconds default' -> '5'
        Example: 'GRUB_CMDLINE="has #hash" #comment' -> '"has #hash"'
        """
        value_part = value_part.strip()

        # Look for the first UNQUOTED '#' to find the comment start
        in_single_quotes = False
        in_double_quotes = False
        comment_index = len(value_part)

        for i, char in enumerate(value_part):
            if char == "'" and not in_double_quotes:
                in_single_quotes = not in_single_quotes
            elif char == '"' and not in_single_quotes:
                in_double_quotes = not in_double_quotes
            elif char == '#' and not in_single_quotes and not in_double_quotes:
                comment_index = i
                break

        # Clip the string at the comment index and strip trailing whitespace
        return value_part[:comment_index].rstrip()

    def _collect_guidance(self, line_index: int) -> str:
        """
        Collects guidance from consecutive comment lines immediately above the given line.
        Preserves hard newlines between comment lines.

        Returns: Multi-line string with # stripped from each line, or empty string if no comments found.
        """
        guidance_lines = []
        idx = line_index - 1

        while idx >= 0:
            line = self.lines[idx].strip()
            # Stop at blank line or non-comment line
            if not line or not line.startswith('#'):
                break
            # Strip # and any leading space after it
            comment_text = line[1:].lstrip()
            guidance_lines.insert(0, comment_text)
            idx -= 1

        return '\n'.join(guidance_lines)

    def _join_continuation_lines(self):
        """
        Pass 1a: Join backslash continuation lines physically in self.lines.
        Pattern: PARAM="value \
                 continued"

        Modifies self.lines in place, replacing continuation sequences with single lines.
        Works for both commented and uncommented lines.
        """
        i = 0
        while i < len(self.lines):
            line = self.lines[i]
            stripped = line.rstrip()

            # Check if line ends with backslash (potential continuation)
            if not stripped.endswith('\\'):
                i += 1
                continue

            # Check if it's a parameter assignment with quoted value and backslash continuation
            # Pattern: [#]GRUB_XXX="...text \
            # Look for = followed by " anywhere in the line
            if '=' not in line or '"' not in line:
                i += 1
                continue

            # Extract the part after the first = sign
            try:
                equals_parts = line.split('=', 1)
                if len(equals_parts) < 2:
                    i += 1
                    continue
                value_part = equals_parts[1].rstrip()
                # Check if value starts with " and ends with \
                if not (value_part.startswith('"') and value_part.endswith('\\')):
                    i += 1
                    continue
            except Exception:
                i += 1
                continue

            # Collect continuation lines
            combined = stripped
            lines_consumed = 0

            # Check if the first line is commented
            is_commented = stripped.lstrip().startswith('#')

            while combined.endswith('\\') and (i + lines_consumed + 1) < len(self.lines):
                next_line = self.lines[i + lines_consumed + 1].rstrip()
                next_stripped = next_line.strip()

                # For commented continuations, expect # at start of continuation
                # For uncommented continuations, # at start means malformed
                if is_commented:
                    # Continuation line should also be commented
                    if not next_stripped.startswith('#'):
                        break
                    # Strip the leading # from the continuation line
                    next_line = next_line.lstrip()
                    if next_line.startswith('#'):
                        next_line = next_line[1:]
                else:
                    # Uncommented continuation shouldn't start with #
                    if next_stripped.startswith('#'):
                        break

                # Remove backslash and append next line
                combined = combined[:-1] + next_line.rstrip()
                lines_consumed += 1

            # Replace the first line with combined value
            self.lines[i] = combined + '\n'

            # Remove the consumed continuation lines
            if lines_consumed > 0:
                del self.lines[i + 1:i + 1 + lines_consumed]

            i += 1

    def _scan_for_variable_expansion(self):
        """
        Pass 1b: Scan for uncommented lines using variable expansion.
        Blacklist the left-side PARAM (which uses expansion).
        Right-side referenced params remain editable - changes will be picked up when sourced.
        Pattern: PARAM=...${GRUB_...} or PARAM=...$GRUB_...
        """
        for line in self.lines:
            stripped = line.strip()

            # Skip comments and empty lines
            if not stripped or stripped.startswith('#'):
                continue

            # Match PARAM=value pattern
            mat = re.match(r"\s*(GRUB(_[A-Z]+)+)\s*=(.*)$", stripped)
            if not mat:
                continue

            left_param = mat.group(1)
            value_part = mat.group(3)

            # Check if value contains $GRUB_ or ${GRUB_...}
            if '$GRUB_' in value_part or '${GRUB_' in value_part:
                # Blacklist only the left-side parameter (the one using expansion)
                # Right-side params remain editable and changes propagate when sourced
                self.blacklisted_params.add(left_param)

    def read_file(self):
        """Reads the GRUB file and populates the internal data structures."""
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.lines = f.readlines()

        except FileNotFoundError:
            print(f"Warning: File not found at {self.file_path}. Starting with empty configuration.")
            self.lines = []
            return

        # Pass 1a: Join backslash continuation lines (modifies self.lines)
        self._join_continuation_lines()

        # Now initialize structures based on the modified line count
        self.param_of = [None] * len(self.lines)
        self._initialize_param_data()

        # Pass 1b: Scan for variable expansion and build blacklist
        self._scan_for_variable_expansion()

        # Pass 2: Parse parameters (continuation lines already joined)
        for i, line in enumerate(self.lines):
            line = line.strip()

            if not line:
                continue

            mat = re.match(r"\s*(#)?\s*(GRUB(_[A-Z]+)+)\s*=(.*)$", line)
            if not mat:
                continue # not a line with a parameter (commented out or not)

            param = mat.group(2)
            is_comment = bool(mat.group(1))
            value_part = mat.group(4)

            # Skip blacklisted params (using variable expansion) - passthrough only
            if param in self.blacklisted_params:
                continue

            if param not in self.supported_params:
                if self.discovery.get_absent([param]):
                    continue  # looks like a param but not on this system
                # Unvalidated parameter - adopt it with minimal config
                if param not in self.extra_params:
                    # Collect guidance from comment lines above
                    guidance = self._collect_guidance(i)
                    value = self._cleanse(value_part)

                    # Create config based on default_cfg template
                    param_cfg = CannedConfig.default_cfg.copy()
                    param_cfg['default'] = value
                    param_cfg['guidance'] = guidance

                    # Add to extra_params and supported_params
                    self.extra_params[param] = param_cfg
                    self.supported_params[param] = param_cfg

                    # Initialize param_data entry
                    self.param_data[param] = SimpleNamespace(
                        line_num=None, value=self.ABSENT, new_value=None,
                        out_value=None)

            data = self.param_data[param]

            # Handle duplicate parameters - last uncommented line wins
            if data.line_num is not None:  # We've seen this param before
                # If current line is commented but previous wasn't, skip current
                if is_comment and data.value != self.COMMENT:
                    continue

                # Mark the previous line as superseded
                prev_line_num = data.line_num
                if data.value != self.COMMENT:
                    # Comment out the previous uncommented line
                    self.lines[prev_line_num] = '#' + self.lines[prev_line_num]
                self.param_of[prev_line_num] = None

            # Record this line as the current value for this parameter
            data.line_num = i
            self.param_of[i] = param
            value = self._cleanse(value_part)
            data.value = self.COMMENT if is_comment else value
            data.out_value = value if is_comment else None


    # --- TUI Interaction Methods ---
    def get_current_state(self, param: str) -> str:
        """Returns the current effective value or state for a TUI display."""
        return self.param_data[param].value

    def set_new_value(self, param: str, value: str):
        """Sets a new, legal value (via Cycle/Edit)."""
        self.param_data[param].new_value = value

    def del_parameter(self, param: str):
        """Sets the parameter to commented out"""
        self.param_data[param].new_value = self.COMMENT

    # --- File Writing Method ---
    def write_file(self, output_path: Optional[str] = None, use_stdout: bool = False):
        """Writes the modified configuration to a new file or stdout."""
        output_path = output_path or self.file_path
        new_lines: List[str] = []

        # 1. Process existing lines
        for i, line in enumerate(self.lines):
            param = self.param_of[i]
            if not param:
                new_lines.append((' ', line))  # unsupported param or any non-param line
                continue

            # Blacklisted params passthrough (not in param_data)
            if param not in self.param_data:
                new_lines.append((' ', line))
                continue

            data = self.param_data[param]
            new_value = data.new_value
            if new_value is None or new_value == self.ABSENT:
                # ABSENT means "no line for this parameter".  If a caller
                # assigns it to a parameter that *does* have a line, the state
                # is inconsistent; leaving the line untouched is the only safe
                # action.  This must not be an ``assert``: assertions vanish
                # under ``python -O``, and writing the sentinel would corrupt
                # the config (audit M9).
                new_lines.append(('=', line))  # unchanged supported param
                continue
            if new_value == self.COMMENT:
                # Don't write commented lines for originally absent params
                if data.value == self.ABSENT:
                    continue
                if data.value != self.COMMENT:
                    line = '#' + line
                new_lines.append(('~', line))  # commented out param
                continue
            new_lines.append(('~', param + '=' + str(new_value) + '\n'))  # changed param


        # 2. Append new parameters (that were absent in the original file)
        # Note: We append them at the very end of the existing content.

        # A simple separator for appended content
        for param, cfg in self.supported_params.items():
            data = self.param_data[param]
            if data.value == self.ABSENT:
                new_value = data.new_value

                # COMMENT means "stay absent"; ABSENT is the absence sentinel
                # itself and must never be written literally (audit M9).
                if new_value is None or new_value in (self.COMMENT, self.ABSENT):
                    continue

                # Have a parameter formerly ABSENT now with legal value
                new_lines.append(('+ ', '\n'))
                guidance = cfg.get('guidance', '')
                if guidance:
                    # Wrap guidance text to 70 chars including '# ' prefix
                    wrapped_lines = textwrap.wrap(
                        guidance,
                        width=68,  # 70 - len('# ') = 68
                        break_long_words=False,
                        break_on_hyphens=False
                    )
                    for line in wrapped_lines:
                        new_lines.append(('+', '# ' + line + '\n'))
                new_lines.append(('+', f"{param}={new_value}\n"))

        # 3. Write the new content to the file or stdout
        try:
            if use_stdout:
                for prefix, line in new_lines:
                    sys.stdout.write(prefix + '  ' + line)
            else:
                # Atomic, symlink-safe write.  Safe whether the destination is
                # a root-owned staging file in /etc/default or a plain path.
                text = ''.join(line for _, line in new_lines)
                UserConfigDir.get_singleton().atomic_write(
                    Path(output_path), text, mode=0o644)
                print(f"OK: wrote '{output_path}'")
            return True
        except Exception as wr_ex:
            print(f"ERR: cannot write '{output_path}' [{wr_ex}]")
            return False


def main():
    """Test the GrubFile class with some example modifications."""

    # Define supported parameters with guidance
    supported_params = {
        "GRUB_TIMEOUT": {
            "guidance": "Set the timeout in seconds before the default entry boots. Use -1 to wait indefinitely, 0 to boot immediately."
        },
        "GRUB_DEFAULT": {
            "guidance": "Set the default menu entry to boot. 0 = first entry, 'saved' = last selected entry"
        },
        "GRUB_CMDLINE_LINUX_DEFAULT": {
            "guidance": "Kernel command line arguments for normal boot. Common: quiet splash, nomodeset, etc."
        },
        "GRUB_CMDLINE_LINUX": {
            "guidance": "Kernel command line arguments for all boot modes."
        },
        "GRUB_DISABLE_RECOVERY": {
            "guidance": "Set true to disable generation of recovery mode menu entries"
        },
        "GRUB_THEME": {
            "guidance": "Path to GRUB theme directory. Example: /boot/grub/themes/mytheme"
        },
        "GRUB_DISABLE_OS_PROBER": {
            "guidance": "Set to 'true' to prevent scanning for other operating systems."
        },
        "GRUB_IMAGINARY_PARAM": {
            "guidance": "This is a completely made-up parameter to demonstrate adding a new parameter with guidance text that gets properly wrapped to 70 characters including the comment prefix."
        }
    }

    # Read the default grub configuration
    grub_file = GrubFile(supported_params)

    print("=== Original State ===")
    for param in supported_params:
        state = grub_file.get_current_state(param)
        print(f"{param}: {state}")

    print("\n=== Making Modifications ===")

    # 1. Change timeout
    grub_file.set_new_value("GRUB_TIMEOUT", "10")
    print("- Set GRUB_TIMEOUT to 10")

    # 2. Comment out OS_PROBER if present
    if grub_file.get_current_state("GRUB_DISABLE_OS_PROBER") != grub_file.ABSENT:
        grub_file.del_parameter("GRUB_DISABLE_OS_PROBER")
        print("- Commented out GRUB_DISABLE_OS_PROBER")

    # 3. Add theme if absent
    if grub_file.get_current_state("GRUB_THEME") == grub_file.ABSENT:
        grub_file.set_new_value("GRUB_THEME", "/boot/grub/themes/custom")
        print("- Added GRUB_THEME (was absent)")

    # 4. Modify cmdline if present
    cmdline_state = grub_file.get_current_state("GRUB_CMDLINE_LINUX_DEFAULT")
    if cmdline_state not in (grub_file.ABSENT, grub_file.COMMENT):
        grub_file.set_new_value("GRUB_CMDLINE_LINUX_DEFAULT", '"quiet splash nomodeset"')
        print("- Modified GRUB_CMDLINE_LINUX_DEFAULT")

    # 5. Add imaginary parameter (will always be absent)
    grub_file.set_new_value("GRUB_IMAGINARY_PARAM", '"test-value"')
    print("- Added GRUB_IMAGINARY_PARAM (demonstrates guidance wrapping)")

    print("\n=== Modified Output ===\n")

    # Write to stdout
    grub_file.write_file(use_stdout=True)

if __name__ == '__main__':
    main()
