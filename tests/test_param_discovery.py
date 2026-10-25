"""Regression tests for audit finding H7.

Parameter discovery used to be reachable only through the module's own CLI:
the application called ``get_absent()``, which just read a cache and returned
an empty set when no cache existed.  A fresh install therefore never filtered
anything, and later runs could filter from an arbitrarily old cache.

The application now refreshes the cache at startup through
``ensure_discovered()``, and ``save_params()`` keeps the in-memory view in
sync so the refreshed result is what ``get_absent()`` sees.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import grub_wiz.main as main_mod
from grub_wiz.main import GrubWiz
from grub_wiz.ParamDiscovery import (
    STATE_NO_INFO,
    STATE_OK,
    ParamDiscovery,
)
from grub_wiz.UserConfigDir import UserConfigDir


class FakeUserConfig:
    """In-memory stand-in for the root-owned state directory."""

    def __init__(self, root):
        self.system_state_dir = Path(root) / 'var-lib-grub-wiz'
        self.user_state_dir = Path(root) / 'user-grub-wiz'
        self.system_state_dir.mkdir(parents=True, exist_ok=True)
        self.user_state_dir.mkdir(parents=True, exist_ok=True)

    def safe_read_text(self, path):
        """Read a cache file or raise FileNotFoundError, like production."""
        return Path(path).read_text(encoding='utf-8')

    def atomic_root_write(self, path, text, mode=0o600):
        """Write the cache file; atomicity is covered elsewhere."""
        Path(path).write_text(text, encoding='utf-8')
        Path(path).chmod(mode)


@pytest.fixture(name='discovery')
def fixture_discovery(tmp_path, monkeypatch):
    """Build a ParamDiscovery bound to a throwaway state directory."""
    ParamDiscovery.singleton = None
    fake_config = FakeUserConfig(tmp_path)
    monkeypatch.setattr(
        UserConfigDir,
        'get_singleton',
        staticmethod(lambda app_name='grub-wiz': fake_config),
    )
    obj = ParamDiscovery()
    yield obj
    ParamDiscovery.singleton = None


STALE_CACHE = """\
discovered_params:
- GRUB_OLD
status:
  state: OK
  unixtime: 0
source: info grub
note: stale test cache
manual_disabled: false
"""


def test_ensure_discovered_runs_on_fresh_install(discovery, monkeypatch):
    """A missing cache must trigger discovery before filtering."""
    calls = []

    def fake_discover():
        calls.append(True)
        return {'GRUB_TIMEOUT', 'GRUB_DEFAULT'}, STATE_OK

    monkeypatch.setattr(discovery, 'discover_params', fake_discover)

    assert discovery.ensure_discovered() == {'GRUB_TIMEOUT', 'GRUB_DEFAULT'}
    assert len(calls) == 1
    assert discovery.cache_file.is_file()

    # get_absent() must see the fresh result instead of "no cache -> nothing
    # is absent".
    assert discovery.get_absent(['GRUB_TIMEOUT']) == set()
    assert discovery.get_absent(['GRUB_MADE_UP']) == {'GRUB_MADE_UP'}


def test_stale_cache_is_refreshed_before_filtering(discovery, monkeypatch):
    """A regenerated cache must replace the stale in-memory snapshot."""
    discovery.cache_file.write_text(STALE_CACHE, encoding='utf-8')
    discovery.cached_data = None  # reload from the file on next use
    calls = []

    def fake_discover():
        calls.append(True)
        return {'GRUB_TIMEOUT'}, STATE_OK

    monkeypatch.setattr(discovery, 'discover_params', fake_discover)

    discovery.ensure_discovered()

    assert len(calls) == 1
    # The old cache claimed GRUB_OLD was supported; after the weekly refresh
    # it is absent.  This fails unless save_params() updates cached_data.
    assert discovery.get_absent(['GRUB_OLD']) == {'GRUB_OLD'}
    assert discovery.get_absent(['GRUB_TIMEOUT']) == set()


def test_ensure_discovered_attempts_only_once_per_process(discovery, monkeypatch):
    """NO_INFO is retried on the next start, not on every UI re-init."""
    calls = []

    def fake_discover():
        calls.append(True)
        return set(), STATE_NO_INFO

    monkeypatch.setattr(discovery, 'discover_params', fake_discover)

    assert discovery.ensure_discovered() == set()
    assert discovery.ensure_discovered() == set()
    assert len(calls) == 1


def test_reinit_runs_discovery_before_filtering(monkeypatch):
    """``GrubWiz.reinit_gw()`` must populate discovery before get_absent()."""

    class FakeGrubFile:
        """Minimal GrubFile; the real one reads the file in __init__."""

        def __init__(self, supported_params, file_path=None):
            self.supported_params = dict(supported_params)
            self.extra_params = {}
            self.param_data = {
                name: SimpleNamespace(value=cfg['default'])
                for name, cfg in supported_params.items()
            }

        def read_file(self):
            """No-op: param_data was built from supported_params."""

    class FakeWarnDB:
        """Minimal WarnDB; reinit only audits and flushes it."""

        def __init__(self, param_cfg, filename='warn-db.yaml'):
            self.param_cfg = param_cfg
            self.audited = None

        def audit_info(self, info):
            """Record the audit payload for completeness."""
            self.audited = info

        def write_if_dirty(self):
            """Nothing to persist in the fake."""

    class RecordingDiscovery:
        """Records the order and arguments of the discovery calls."""

        def __init__(self):
            self.ensure_calls = 0
            self.absent_calls = []

        def ensure_discovered(self):
            self.ensure_calls += 1
            return {'GRUB_TIMEOUT'}

        def get_absent(self, names):
            self.absent_calls.append(list(names))
            return {'GRUB_UNSUPPORTED'}

    class FakeValidator:
        """Validator whose warnings do not matter for this test."""

        def make_warns(self, values):
            """Return no warnings."""
            return [], {}

    monkeypatch.setattr(main_mod, 'GrubFile', FakeGrubFile)
    monkeypatch.setattr(main_mod, 'WarnDB', FakeWarnDB)
    monkeypatch.setattr(main_mod, 'get_top_level_grub_entries', lambda _path: {})

    discovery = RecordingDiscovery()
    gw = object.__new__(GrubWiz)
    gw.param_cfg = {}
    gw.param_values = {}
    gw.prev_values = {}
    gw.saved_active_param_values = {}
    gw.param_defaults = {}
    gw.must_reviews = None
    gw.ss = None
    gw.canned_config = SimpleNamespace(data={
        'Basic': {
            'GRUB_TIMEOUT': {
                'default': '5', 'enums': {}, 'guidance': '',
            },
            'GRUB_UNSUPPORTED': {
                'default': 'yes', 'enums': {}, 'guidance': '',
            },
        },
    })
    gw.distro_vars = SimpleNamespace(
        update_initramfs=None, grub_cfg='', etc_grub='/etc/default/grub')
    gw.param_discovery = discovery
    gw.wiz_validator = FakeValidator()
    gw.refresh_backup_list = lambda: None

    GrubWiz.reinit_gw(gw)

    assert discovery.ensure_calls == 1
    assert discovery.absent_calls  # the defined names were probed
    assert 'GRUB_TIMEOUT' in gw.param_cfg
    assert 'GRUB_UNSUPPORTED' not in gw.param_cfg
    assert 'GRUB_UNSUPPORTED' not in gw.param_names
