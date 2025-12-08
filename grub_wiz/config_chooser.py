import os
from pathlib import Path
from importlib.resources import files
from ruamel.yaml import YAML

APP_NAME = "grub-wiz"
CONFIG_DIR = Path.home() / ".config" / APP_NAME
DEFAULT_CONFIG_NAME = "canned_config.yaml"
CUSTOM_CONFIG_NAME = "custom_config.yaml"

def get_config_data():
    # 1. Ensure the user config directory exists
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    # 2. Copy the latest default config resource to the user's config directory
    # Get the source file from the installed package
    default_source = files(APP_NAME) / DEFAULT_CONFIG_NAME
    
    # Copy the default config. This overwrites an existing default with the latest version.
    default_target = CONFIG_DIR / DEFAULT_CONFIG_NAME
    default_target.write_bytes(default_source.read_bytes())
    
    yaml = YAML()
    config_data = {}
    
    # 3. Load the default config (as the base)
    with open(default_target, 'r') as f:
        config_data = yaml.load(f)
        
    # 4. Check for and load the custom config (to override)
    custom_target = CONFIG_DIR / CUSTOM_CONFIG_NAME
    if custom_target.is_file():
        # NOTE: This simple load REPLACES, not MERGES. 
        # For a full merge, you'd need recursive dictionary update logic.
        print("Using custom configuration.")
        with open(custom_target, 'r') as f:
            custom_data = yaml.load(f)
            # Simple merge: custom_data keys overwrite config_data keys
            config_data.update(custom_data)
    
    return config_data

# Example of how to use it
config = get_config_data()

##############################
##############################
##############################

# ~/.config/grub-wiz/custom_config.yaml

# 1. DELETE Section: Parameters listed here will be removed from the base config.
delete:
  section_name_1:
    - param_to_suppress_1
    - param_to_suppress_2
  section_name_2:
    - another_param_to_remove

# 2. OVERRIDE Section: Parameters listed here will REPLACE (or add to) 
#    the base config. The structure MUST exactly match the base config.
override:
  section_name_1:
    param_to_suppress_1: "new_value"    # Replaces value in base config
    new_param: "value"                  # Adds a new parameter
  section_name_3:
    param_a: "value_a"

##############################
##############################
##############################

def deep_merge(base_dict, patch_dict):
    """
    Recursively updates base_dict with items from patch_dict.
    This is used for the 'override' section.
    """
    for key, value in patch_dict.items():
        if isinstance(value, dict) and key in base_dict and isinstance(base_dict[key], dict):
            # If both values are dictionaries, merge them recursively
            base_dict[key] = deep_merge(base_dict[key], value)
        else:
            # Otherwise, overwrite the value in the base dictionary
            base_dict[key] = value
    return base_dict

def apply_config_patch(base_config, patch_config):
    """Applies the delete and override sections from the patch."""
    
    # --- 1. Apply DELETIONS ---
    deletes = patch_config.get('delete', {})
    for section_name, params_to_delete in deletes.items():
        if section_name in base_config:
            # Ensure the section exists and is a dictionary
            if isinstance(base_config[section_name], dict):
                for param in params_to_delete:
                    # Remove the parameter if it exists in the base config section
                    base_config[section_name].pop(param, None)
            else:
                # Handle error: delete section targets a non-dictionary in base
                print(f"Warning: Cannot apply delete for '{param}' in '{section_name}'. Not a dictionary.")
        # Note: If section_name doesn't exist, we just ignore it.

    # --- 2. Apply OVERRIDES/ADDITIONS ---
    overrides = patch_config.get('override', {})
    # Use the recursive merge function
    final_config = deep_merge(base_config, overrides)
    
    return final_config

##############################
##############################
##############################

# Before applying overrides:
overrides = patch_config.get('override', {})
for section, patch_data in overrides.items():
    if section not in base_config:
        print(f"Error: Override section '{section}' is not present in the default config. Tossing.")
        overrides.pop(section)
        continue
    
    # Optional: Basic type check (e.g., ensure it's still a dictionary)
    if not isinstance(patch_data, type(base_config[section])):
        print(f"Error: Type mismatch for section '{section}'. Expected {type(base_config[section])}, got {type(patch_data)}. Tossing.")
        overrides.pop(section)
        continue
    
    # If it passes checks, then proceed to the deep_merge(base_config, overrides)

##############################
##############################
##############################

##############################
##############################
##############################