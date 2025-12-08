#!/usr/bin/env
"""
{parameter-name}:
  section: {TUI grouping}
  type: {cycle | input | boolean | special_list} # Controls Curses interaction
  default: {default value from GRUB docs}
  enums: # list of values for 'type: cycle' or 'type: special_list'
    - value: meaning
  regex: {regex} # Optional, for 'type: input' validation
  specials: # Optional, for 'type: special_list' population
    - {special_key} # e.g., "get-res-list", "get-disk-uuid"
  brief: {text} # < 60 char description
  full: {text} # < 400 char detailed explanation
"""
from importlib.resources import files
from ruamel.yaml import YAML

yaml = YAML()
yaml.preserve_quotes = True
yaml.default_flow_style = False

class CannedConfig:
    """ TBD"""
    def __init__(self):
        # 1. Get a Traversable object for the 'grub_wiz' package directory
        resource_path = files('grub_wiz') / 'canned_config.yaml'
        
        # 2. Open the file resource for reading
        # We use resource_path.read_text() to get the content as a string
        yaml_string = resource_path.read_text()
        self.data = yaml.load(yaml_string)
        
    def dump(self):
      """ Dump the wired/initial configuration"""
      string = yaml.dump(self.data)
      print(string)

def main():
    """ TBD """
    string = yaml.dump(config_data)
    print(string)

if __name__ == '__main__':
    main()