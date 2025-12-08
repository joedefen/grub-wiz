#!/usr/bin/env python3
"""
grub_wiz.GrubParser: A utility class for safely parsing and manipulating
the /etc/default/grub configuration file.
"""
# pylint: disable=invalid-name,redefined-outer-name,too-few-public-methods

import os
import re
from typing import List, Optional

class GrubParser:
    """ TBD """
    # Define the configuration file path
    GRUB_FILE_PATH = "/etc/default/grub"

    def __init__(self, params: List[str]):
        """Initializes the parser."""
        # lines will store the content of /etc/default/grub
        # self.lines: List[str] = []
        self.params = params # list of params of concern
        self.vals = {}    # for those params with values
        self.other_lines = []    # original lines of params of no concern

    def get_etc_default_grub(self) -> bool:
        """
        Reads the content of the /etc/default/grub file into self.lines.
        """
        # Check if the file exists before attempting to open it
        if not os.path.exists(self.GRUB_FILE_PATH):
            print(f"Error: GRUB configuration file not found at {self.GRUB_FILE_PATH}")
            return False

        try:
            # Open the file and read all lines
            with open(self.GRUB_FILE_PATH, 'r', encoding='utf-8') as f:
                lines = f.readlines()

        except IOError as e:
            print(f"Error reading {self.GRUB_FILE_PATH}: {e}")
            return False

        # - we assume the file is a sequence of blocks that look like this:
        #       {empty-line}
        #       # {zero-or-more-plan-comments}
        #       GRUB_{SOMETHING}={VALUE} # OR COMMENTED OUT LIKE...
        #       #GRUB_{SOMETHING}={VALUE}
        # - anything not like that is discarded
        # - if the parameter is in params, then save the value
        block_lines = []
        param_line_re = r'^\s*(#)?\s*(GRUB\_[A-Z_]+)=(.+?)\s*(?:#.*)?$'
        for line in lines:
            mat = re.match(param_line_re, line)
            if mat:
                # print(f'PARAM-LINE: {line}')
                block_lines.append(line)
                is_comment = bool(mat.group(1))
                param = mat.group(2)
                if param in self.params:
                    if not is_comment:
                        self.vals[param] = mat.group(3)
                else:
                    self.other_lines += block_lines
                block_lines = []
            elif not line.startswith('#--#'): # strip "our" comments
                block_lines.append(line)
        self.other_lines += block_lines

        return True

def main():
    """ TBD """
    params = 'GRUB_DEFAULT'
    params += ' GRUB_TIMEOUT_STYLE GRUB_TIMEOUT GRUB_DISTRIBUTOR'
    params += ' GRUB_CMDLINE_LINUX_DEFAULT GRUB_CMDLINE_LINUX'
    params = params.split()

    parser = GrubParser(params=params)
    parser.get_etc_default_grub()

    print('#-'*25 + '#')
    for param in parser.params:
        if param in parser.vals:
            val = parser.vals[param]
            print(f'PARAM {param}={val}')
        else:
            print(f'PARAM {param}=None')
    print('#-'*25 + '#')
    print(''.join(parser.other_lines), end='')


# --- Example Usage (Optional, for testing the module) ---
if __name__ == '__main__':
    main()
