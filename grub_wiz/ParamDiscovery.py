#!/usr/bin/env python3
"""
Discovers which GRUB parameters are supported on this system by parsing
the installed GRUB documentation (info pages).

The result depends on the machine (installed GRUB docs, distro), not on the
invoking user, so the cache lives in the root-owned system state directory
(/var/lib/grub-wiz/system-params.yaml) rather than in a user's home.
"""
# pylint: disable=broad-exception-caught,

import io
import re
import argparse
import subprocess
import time
from typing import Optional, Set
from ruamel.yaml import YAML

try:
    from .UserConfigDir import UserConfigDir
except Exception:
    from UserConfigDir import UserConfigDir

yaml = YAML()
yaml.preserve_quotes = True
yaml.default_flow_style = False

# Discovery status states
STATE_NO_INFO = "NO_INFO"              # info command not found or GRUB docs not installed
STATE_CANNOT_PARSE = "CANNOT_PARSE_INFO"  # info ran but parsing failed
STATE_OK = "OK"                        # Successfully discovered parameters

# Cache refresh interval (1 week in seconds)
WEEK_IN_SECONDS = 7 * 24 * 60 * 60

# Threshold for considering discovered params valid (80% coverage)
ABSENT_THRESHOLD = 0.20


class ParamDiscovery:
    """Discovers and caches system-supported GRUB parameters"""
    singleton = None

    def __init__(self):
        """
        Args:
            user_config: UserConfigDir instance (uses singleton if not provided)
        """
        if ParamDiscovery.singleton:
            raise RuntimeError("ParamDiscovery is a singleton. Use get_singleton() instead.")
        ParamDiscovery.singleton = self
        
        self.user_config = UserConfigDir.get_singleton("grub-wiz")
        # Machine-wide derived state: root-owned, never inside a user's home.
        self.system_state_dir = self.user_config.system_state_dir
        self.cache_file = self.system_state_dir / 'system-params.yaml'
        # Pre-split cache location, read once for backward compatibility.
        self._legacy_cache_file = self.user_config.user_state_dir / 'system-params.yaml'
        self.cached_data = None
        self._manual_disabled = False

        # all member vars inited ... do dynamic init...
        self.cached_data = self.load_cached_data()
        self._manual_disabled = self.cached_data['manual_disabled'] if self.cached_data else False        

    @staticmethod
    def get_singleton():
        """ Gets the singleton object ... do not use constructor directly.
        """
        if not ParamDiscovery.singleton:
            ParamDiscovery()
        return ParamDiscovery.singleton

    def manual_enable(self, state: Optional[bool] = None) -> bool:
        """
        Set or get the manual enable/disable state.

        Args:
            state: True to enable discovery, False to disable, None to query

        Returns:
            Current state (True=enabled, False=disabled)
        """
        if state is not None:
            new_disabled = not state  # Convert enable to disabled flag
            if new_disabled != self._manual_disabled:
                self._manual_disabled = new_disabled
                # Save updated state - preserve existing params and state
                cached_data = self.load_cached_data()
                if cached_data:
                    self.save_params(cached_data['params'], cached_data['state'])
                else:
                    # No cache yet, create minimal entry
                    self.save_params(set(), STATE_NO_INFO)

        return not self._manual_disabled  # Return as "enabled" flag

    def discover_params(self) -> tuple[Set[str], str]:
        """
        Parse 'info grub' to discover system-supported GRUB parameters.

        Returns:
            Tuple of (parameter_set, status_state)
            - parameter_set: Set of parameter names
            - status_state: One of STATE_NO_INFO, STATE_CANNOT_PARSE, STATE_OK
        """
        params = set()

        try:
            # Get the "Simple configuration" section from GRUB info pages
            result = subprocess.run(
                ['info', '-f', 'grub', '-n', 'Simple configuration', '--output=-'],
                capture_output=True,
                text=True,
                check=False,
                timeout=5
            )

            if result.returncode != 0:
                print(f"Warning: info command failed (return code {result.returncode})")
                print("GRUB documentation may not be installed.")
                return params, STATE_NO_INFO

            # Parse output for GRUB parameter references
            # Common patterns in info pages:
            # 'GRUB_TIMEOUT'
            # `GRUB_DEFAULT'
            # GRUB_CMDLINE_LINUX

            # Pattern 1: Quoted parameters 'GRUB_*' or `GRUB_*'
            for match in re.finditer(r"[`']?(GRUB_[A-Z_0-9]+)[`']?", result.stdout):
                param = match.group(1)
                # Sanity check: reasonable length (avoid false positives)
                if 10 <= len(param) <= 40:
                    params.add(param)

            # Filter out likely false positives (rare but possible)
            # Real parameters don't have multiple underscores in a row
            params = {p for p in params if '__' not in p}

            # Determine status based on parsing results
            if len(params) > 0:
                return params, STATE_OK
            # Info ran but we couldn't parse any parameters
            print("Warning: Could not parse any parameters from info output")
            return params, STATE_CANNOT_PARSE

        except subprocess.TimeoutExpired:
            print("Warning: info command timed out")
            return params, STATE_NO_INFO
        except FileNotFoundError:
            print("Warning: 'info' command not found on system")
            return params, STATE_NO_INFO
        except Exception as e:
            print(f"Warning: Unexpected error during parameter discovery: {e}")
            return params, STATE_CANNOT_PARSE

    def save_params(self, params: Set[str], state: str) -> None:
        """
        Save discovered parameters and status to YAML cache file.

        Args:
            params: Set of parameter names
            state: Discovery state (STATE_NO_INFO, STATE_CANNOT_PARSE, or STATE_OK)
        """
        # Convert set to sorted list for readable YAML
        params_list = sorted(params)
        current_time = int(time.time())

        data = {
            'discovered_params': params_list,
            'status': {
                'state': state,
                'unixtime': current_time
            },
            'source': 'info grub',
            'note': 'Parameters not in this list will be hard-hidden by default',
            'manual_disabled': self._manual_disabled
        }

        stream = io.StringIO()
        yaml.dump(data, stream)

        # Root-owned atomic write; the destination directory is verified to be
        # root-owned and the temp file is installed with os.replace().
        self.user_config.atomic_root_write(
            self.cache_file, stream.getvalue(), mode=0o600)

    def load_cached_data(self) -> Optional[dict]:
        """
        Load cached discovery data including params, status, and manual_disabled flag.

        Returns:
            Dictionary with 'params', 'state', 'timestamp', and 'manual_disabled',
            or None if cache doesn't exist
        """
        if self.cached_data:
            return self.cached_data

        try:
            try:
                text = self.user_config.safe_read_text(self.cache_file)
            except FileNotFoundError:
                # One-time fallback to the old per-user cache location.
                text = self.user_config.safe_read_text(self._legacy_cache_file)
        except FileNotFoundError:
            return None
        except OSError as e:
            print(f"Warning: Refusing to read cache file {self.cache_file}: {e}")
            return None

        try:
            data = yaml.load(io.StringIO(text))

            if not data:
                return None

            # Extract status info
            status = data.get('status', {})
            state = status.get('state', STATE_NO_INFO)
            timestamp = status.get('unixtime', 0)

            # Extract params and manual_disabled flag
            params = set(data.get('discovered_params', []))
            manual_disabled = data.get('manual_disabled', False)

            self.cached_data = {
                'params': params,
                'state': state,
                'timestamp': timestamp,
                'manual_disabled': manual_disabled
            }
            return self.cached_data
        except Exception as e:
            print(f"Warning: Failed to load cache file: {e}")
            return None

    def should_regenerate(self, cached_data: Optional[dict]) -> bool:
        """
        Determine if discovery should be re-run based on cached status.

        Logic:
        - If NO_INFO: Retry to see if info/docs are now installed
        - If CANNOT_PARSE or OK: Only retry if > 1 week old

        Args:
            cached_data: Cached discovery data from load_cached_data()

        Returns:
            True if discovery should be re-run
        """
        if cached_data is None:
            return True  # No cache exists, must run

        state = cached_data['state']
        timestamp = cached_data['timestamp']
        age_seconds = int(time.time()) - timestamp

        if state == STATE_NO_INFO:
            # Always retry - maybe docs were installed
            return True

        if state in (STATE_CANNOT_PARSE, STATE_OK):
            # Retry if > 1 week old
            return age_seconds > WEEK_IN_SECONDS

        # Unknown state, play it safe and regenerate
        return True

    def get_system_params(self, force_regenerate: bool = False) -> Set[str]:
        """
        Get system-supported parameters, using cache if available.

        Args:
            force_regenerate: If True, ignore cache and re-discover

        Returns:
            Set of parameter names supported on this system
        """
        # If manually disabled, return empty set (behave as NO_INFO)
        if self._manual_disabled:
            return set()

        # Load cached data
        cached_data = self.load_cached_data()

        # Check if we should use cache
        if not force_regenerate and cached_data is not None:
            if not self.should_regenerate(cached_data):
                # Cache is valid, use it
                return cached_data['params']

        # Need to run discovery
        print("Discovering GRUB parameters from system documentation...")
        params, new_state = self.discover_params()

        if params:
            print(f"Found {len(params)} parameters (state: {new_state})")
        else:
            print(f"Warning: No parameters discovered (state: {new_state})")
            if new_state == STATE_NO_INFO:
                print("GRUB documentation may not be installed:")
                print("  Ubuntu/Debian: sudo apt install grub-doc")
                print("  Fedora/RHEL:   sudo dnf install grub2-common")

        # Don't replace OK with non-OK
        if cached_data and cached_data['state'] == STATE_OK and new_state != STATE_OK:
            print(f"Keeping previous OK status (current attempt: {new_state})")
            # Return cached params but update timestamp
            self.save_params(cached_data['params'], STATE_OK)
            return cached_data['params']

        # Save new results
        self.save_params(params, new_state)
        return params

    def dump(self, param_list: Optional[list] = None) -> None:
        """
        Display discovered parameters and optionally compare against a list.

        Args:
            param_list: Optional list of parameters to compare against.
                       If provided, shows comparison (missing/extra/match).
                       If None, shows simple dump of discovered params.
        """
        # Load cached data
        cached_data = self.load_cached_data()
        params = cached_data['params'] if cached_data else set()

        if param_list is None:
            # Simple dump
            print(f"{'='*60}")
            print(f"Discovered Parameters ({len(params)} total):")
            print(f"{'='*60}")

            if cached_data:
                print(f"Status: {cached_data['state']}")
                age_days = (int(time.time()) - cached_data['timestamp']) / (24 * 60 * 60)
                print(f"Cache age: {age_days:.1f} days")
                print(f"Manual: {'disabled' if self._manual_disabled else 'enabled'}")
                print()

            for param in sorted(params):
                print(f"  {param}")

            print(f"\nCache location: {self.cache_file}")
        else:
            def print_set(header, tag, items):
                print(header + f': {len(items)}:')
                for p in sorted(items):
                    print(f"  {tag} {p}")
                print()

            # Comparison mode
            expected = set(param_list)
            missing = expected - params
            extra = params - expected

            print(f"{'='*60}")
            print("Comparison Results:")
            print(f"{'='*60}")

            if cached_data:
                print(f"Status: {cached_data['state']}")
                age_days = (int(time.time()) - cached_data['timestamp']) / (24 * 60 * 60)
                print(f"Cache age: {age_days:.1f} days")
                print(f"Manual: {'disabled' if self._manual_disabled else 'enabled'}")
                print()

            if missing:
                print_set("Missing (known but not found)", '-', missing)

            if extra:
                print_set('Extra (found but unknown)', '+', extra)

            if expected:
                print_set("✓ Perfect match", '=', expected)

    def get_absent(self, param_list: list) -> Set[str]:
        """
        Get parameters from param_list that are not supported on this system.

        Only returns results if:
        - Discovery is manually enabled
        - Discovery state is OK
        - Less than 20% of params are absent (validates probe quality)
          ONLY IF the given number of probes is > 1 (so you can do single
          param probes w/o being dismissed for being incomplete)

        Args:
            param_list: List of parameter names to check

        Returns:
            Set of unsupported parameters, or empty set if conditions not met
        """
        # Must be enabled
        if self._manual_disabled:
            return set()

        # Load cached data
        cached_data = self.load_cached_data()
        if not cached_data:
            return set()

        # Must be in OK state
        if cached_data['state'] != STATE_OK:
            return set()

        params = cached_data['params']
        param_set = set(param_list)
        absent = param_set - params

        # Validate probe quality: no more than 20% absent
        # (unless single param probe)
        if len(param_list) > 1 and len(param_set) > 0:
            absent_ratio = len(absent) / len(param_set)
            if absent_ratio > ABSENT_THRESHOLD:
                # Probe results seem unreliable
                return set()

        return absent


def main():
    """CLI entry point for standalone testing"""

    parser = argparse.ArgumentParser(
        description='Discover GRUB parameters supported on this system'
    )
    parser.add_argument(
        '--regenerate', '-r',
        action='store_true',
        help='Force regeneration, ignore cached results'
    )
    parser.add_argument(
        '--compare',
        type=str,
        help='Compare against comma-separated list of expected params'
    )
    parser.add_argument(
        '--disable',
        action='store_true',
        help='Disable parameter discovery'
    )
    parser.add_argument(
        '--enable',
        action='store_true',
        help='Enable parameter discovery'
    )

    args = parser.parse_args()

    # Initialize discovery
    discovery = ParamDiscovery.get_singleton()

    # Handle enable/disable
    if args.disable:
        discovery.manual_enable(False)
        print("Parameter discovery disabled")
        return
    if args.enable:
        discovery.manual_enable(True)
        print("Parameter discovery enabled")

    # Run discovery (ensures cache is fresh)
    discovery.get_system_params(force_regenerate=args.regenerate)

    # Display results using dump() method
    print()
    if args.compare:
        param_list = [p.strip() for p in args.compare.split(',')]
        discovery.dump(param_list)
    else:
        discovery.dump()


if __name__ == '__main__':
    main()
