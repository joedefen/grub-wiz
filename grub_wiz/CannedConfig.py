#!/usr/bin/env
"""
"""
import re
from importlib.resources import files
from ruamel.yaml import YAML
from .UserConfigDir import UserConfigDir

yaml = YAML()
yaml.preserve_quotes = True
yaml.default_flow_style = False

EXPERT_EDIT = '>>EXPERT_EDIT<<', # not a regex (SPECIAL MEANING)
class CannedConfig:
    """ TBD"""
    default_cfg = {  # config schema for a single parameter
        'default': '',  # usually string, can be integer
        'edit_re': EXPERT_EDIT,
        'edit_re_human': '',  # human-readable description of regex
        'enums': {},  # key: enum name, value enum description
        'guidance': '',  # often lengthy, may have embedded newlines
    }
    def OLD__init__(self):
        # 1. Get a Traversable object for the 'grub_wiz' package directory
        resource_path = files('grub_wiz') / 'canned_config.yaml'

        # 2. Open the file resource for reading
        # We use resource_path.read_text() to get the content as a string
        yaml_string = resource_path.read_text()
        self.data = yaml.load(yaml_string)
    # In CannedConfig.__init__()

    def __init__(self):
        # 1. Load packaged canned_config
        resource_path = files('grub_wiz') / 'canned_config.yaml'
        self.data = yaml.load(resource_path.read_text())
        self._process_config()
        self.using_path = resource_path

        user_config = UserConfigDir.get_singleton()
        config_dir = user_config.user_state_dir

        # 2. Dump reference copy to the user's config dir (atomic, user-owned).
        #    A pre-existing entry of any kind is left untouched.
        ref_path = config_dir / 'canned_config.yaml'
        if not ref_path.exists():
            user_config.atomic_user_write(
                ref_path, resource_path.read_text(), mode=0o644)

        # 3. Try to load user's custom config (never follow a symlink).
        custom_path = config_dir / 'custom_config.yaml'
        try:
            custom_text = user_config.safe_read_text(custom_path)
        except FileNotFoundError:
            custom_text = None
        except OSError as e:
            print(f"WARNING: Refusing to read {custom_path}: {e}")
            custom_text = None

        if custom_text is not None:
            try:
                custom_data = yaml.load(custom_text)
                err =  self.validate_schema(custom_data)
                if err is None:
                    self.data = custom_data  # Or merge if you prefer
                    self._process_config()
                    self.using_path = custom_path
                else:
                    print(f"WARNING: {custom_path} invalid ({err}), using canned config")
            except Exception as e:
                print(f"WARNING: Cannot yaml.load {custom_path}: {e}")

    def _process_config(self):
        """Post-process loaded config:
        1. Resolve regex name references to compiled patterns
        2. Add human descriptions from _re_specs_
        3. Substitute %ENUMS% in guidance strings
        """
        # Extract _re_specs_ if present
        re_specs = self.data.get('_re_specs_', {})

        # Build lookup dict: {re_name: {'pattern': compiled_re, 'human': description}}
        regex_lookup = {}
        for re_name, spec in re_specs.items():
            if isinstance(spec, dict) and 're' in spec:
                try:
                    regex_lookup[re_name] = {
                        'pattern': re.compile(spec['re']),
                        'human': spec.get('human', '')
                    }
                except re.error as e:
                    print(f"WARNING: Invalid regex in _re_specs_.{re_name}: {e}")
                    regex_lookup[re_name] = {'pattern': '', 'human': spec.get('human', '')}

        # Process each section and parameter
        for section_name, params in self.data.items():
            if section_name.startswith('_'):  # Skip special sections like _re_specs_
                continue

            if not isinstance(params, dict):
                continue

            for param_name, cfg in params.items():
                if not isinstance(cfg, dict):
                    continue

                # Process edit_re field
                edit_re = cfg.get('edit_re', '')
                if edit_re:
                    if isinstance(edit_re, str):
                        # Check if it's a reference to _re_specs_
                        if edit_re in regex_lookup:
                            # Resolve to compiled pattern and add human description
                            cfg['edit_re'] = regex_lookup[edit_re]['pattern']
                            cfg['edit_re_human'] = regex_lookup[edit_re]['human']
                        else:
                            # It's an inline pattern (backward compatibility)
                            try:
                                cfg['edit_re'] = re.compile(edit_re)
                                cfg['edit_re_human'] = ''
                            except re.error as e:
                                print(f"WARNING: Invalid inline regex for {param_name}: {e}")
                                cfg['edit_re'] = ''
                                cfg['edit_re_human'] = ''
                    elif edit_re in (EXPERT_EDIT, EXPERT_EDIT[0]):
                        # Keep EXPERT_EDIT as-is, add empty human description
                        cfg['edit_re_human'] = ''
                    else:
                        # Unknown type, set empty
                        cfg['edit_re_human'] = ''
                else:
                    # Empty edit_re - add empty human description
                    cfg['edit_re_human'] = ''

                # Note: We don't pre-expand %ENUMS% here because it needs to be
                # dynamic to show the current value marker in the UI

    def validate_schema(self, data):
        """Validate custom config has correct structure"""
        if not isinstance(data, dict):
            return False
        keys_set = set(self.default_cfg.keys())
        
        for section_name, params in data.items():
            if not isinstance(params, dict):
                return f'Section ({section_name!r} value not dict)'
            for param_name, cfg in params.items():
                if not param_name.startswith('GRUB_'):
                    return f'Param ({param_name!r} is not GRUB_*)'
                # Check required fields exist
                if not all(k in cfg for k in keys_set):
                    return f'Param ({param_name!r} dict missing keys'
                # Check no extra fields (strict)
                if set(cfg.keys()) - keys_set:
                    return f'Param ({param_name!r} dict extra keys'
        return None

    def dump(self):
      """ Dump the wired/initial configuration"""
      string = yaml.dump(self.data)
      print(string)

def main():
    """ TBD """
    cfg = CannedConfig()
    cfg.dump()

if __name__ == '__main__':
    main()