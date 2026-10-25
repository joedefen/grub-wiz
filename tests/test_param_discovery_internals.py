"""Parser, cache rules, and CLI behaviour of ``ParamDiscovery``.

The startup-hook tests in ``test_param_discovery.py`` cover the application
wiring.  These tests cover the parts that decide *what* discovery returns:
info-page parsing, cache compatibility and staleness, the absent-ratio guard,
manual enable/disable persistence, and the module CLI.
"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import grub_wiz.ParamDiscovery as pd_mod
from grub_wiz.ParamDiscovery import (
    STATE_CANNOT_PARSE,
    STATE_NO_INFO,
    STATE_OK,
    WEEK_IN_SECONDS,
    ParamDiscovery,
)
from grub_wiz.UserConfigDir import UserConfigDir


NOW = 1_000_000


class FakeUserConfig:
    def __init__(self, root):
        self.system_state_dir = Path(root) / 'var-lib-grub-wiz'
        self.user_state_dir = Path(root) / 'user-grub-wiz'
        self.system_state_dir.mkdir(parents=True, exist_ok=True)
        self.user_state_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def safe_read_text(path, max_bytes=1024 * 1024):
        del max_bytes
        return Path(path).read_text(encoding='utf-8')

    @staticmethod
    def atomic_root_write(path, text, mode=0o600):
        Path(path).write_text(text, encoding='utf-8')
        Path(path).chmod(mode)


@pytest.fixture(name='discovery')
def fixture_discovery(tmp_path, monkeypatch):
    ParamDiscovery.singleton = None
    fake = FakeUserConfig(tmp_path)
    monkeypatch.setattr(
        UserConfigDir, 'get_singleton',
        staticmethod(lambda app_name='grub-wiz': fake))
    obj = ParamDiscovery()
    obj._fake_user_config = fake
    yield obj
    ParamDiscovery.singleton = None


# --- info parsing ----------------------------------------------------------

def _info_result(stdout='', returncode=0):
    return SimpleNamespace(returncode=returncode, stdout=stdout)


@pytest.mark.parametrize('stdout', [
    "  'GRUB_TIMEOUT' controls the wait\n",
    "`GRUB_DEFAULT' selects an entry\n",
    'GRUB_CMDLINE_LINUX_DEFAULT\n',
])
def test_discover_parses_reasonable_parameter_names(discovery, monkeypatch,
                                                    stdout):
    monkeypatch.setattr(pd_mod.subprocess, 'run',
                        lambda *_a, **_k: _info_result(stdout))

    params, state = discovery.discover_params()

    assert state == STATE_OK
    assert len(params) == 1
    assert next(iter(params)).startswith('GRUB_')


def test_discover_filters_short_long_and_double_underscore_names(
        discovery, monkeypatch):
    stdout = (
        'GRUB_A\n'                       # too short
        'GRUB_TIMEOUT\n'                 # valid
        'GRUB_FOO__BAR\n'                # double underscore
        f"GRUB_{'X' * 50}\n"             # too long
        'GRUB_DEFAULT\n'                 # valid
    )
    monkeypatch.setattr(pd_mod.subprocess, 'run',
                        lambda *_a, **_k: _info_result(stdout))

    params, state = discovery.discover_params()

    assert state == STATE_OK
    assert params == {'GRUB_TIMEOUT', 'GRUB_DEFAULT'}


def test_discover_reports_no_docs_and_cannot_parse(discovery, monkeypatch):
    monkeypatch.setattr(pd_mod.subprocess, 'run',
                        lambda *_a, **_k: _info_result('', returncode=1))
    assert discovery.discover_params() == (set(), STATE_NO_INFO)

    monkeypatch.setattr(pd_mod.subprocess, 'run',
                        lambda *_a, **_k: _info_result('no parameters here'))
    assert discovery.discover_params() == (set(), STATE_CANNOT_PARSE)


@pytest.mark.parametrize('exception, expected', [
    (subprocess.TimeoutExpired('info', 5), STATE_NO_INFO),
    (FileNotFoundError('info'), STATE_NO_INFO),
    (OSError('boom'), STATE_CANNOT_PARSE),
])
def test_discover_maps_execution_failures(discovery, monkeypatch,
                                          exception, expected):
    def explode(*_a, **_k):
        raise exception

    monkeypatch.setattr(pd_mod.subprocess, 'run', explode)

    assert discovery.discover_params() == (set(), expected)


# --- cache compatibility and staleness -------------------------------------

def test_missing_cache_returns_none(discovery):
    assert discovery.cache_file.exists() is False
    assert discovery.load_cached_data() is None


def test_legacy_user_cache_is_read_once(discovery):
    discovery._legacy_cache_file.write_text(
        'discovered_params:\n- GRUB_TIMEOUT\n'
        'status:\n  state: OK\n  unixtime: 42\n'
        'manual_disabled: true\n',
        encoding='utf-8')

    data = discovery.load_cached_data()

    assert data['params'] == {'GRUB_TIMEOUT'}
    assert data['state'] == STATE_OK
    assert data['manual_disabled'] is True


@pytest.mark.parametrize('document', [
    'a: [unterminated\n',
    'just-a-scalar\n',
    '- a\n- list\n',
    '',
])
def test_unusable_cache_documents_return_none(discovery, document, capsys):
    discovery.cache_file.write_text(document, encoding='utf-8')
    discovery.cached_data = None

    assert discovery.load_cached_data() is None
    capsys.readouterr()


def test_unreadable_cache_is_reported_and_ignored(discovery, monkeypatch):
    def deny(*_a, **_k):
        raise OSError('permission denied')

    monkeypatch.setattr(discovery._fake_user_config, 'safe_read_text', deny)
    discovery.cached_data = None

    assert discovery.load_cached_data() is None


@pytest.fixture(name='clock')
def fixture_clock(monkeypatch):
    monkeypatch.setattr(pd_mod.time, 'time', lambda: NOW)


@pytest.mark.parametrize('state, age, expected', [
    (STATE_NO_INFO, 0, True),
    (STATE_OK, 0, False),
    (STATE_OK, WEEK_IN_SECONDS, False),
    (STATE_OK, WEEK_IN_SECONDS + 1, True),
    (STATE_CANNOT_PARSE, WEEK_IN_SECONDS + 1, True),
    ('SOMETHING_NEW', 0, True),
])
def test_should_regenerate_truth_table(discovery, clock, state, age, expected):
    cached = {'params': set(), 'state': state,
              'timestamp': NOW - age, 'manual_disabled': False}

    assert discovery.should_regenerate(cached) is expected


def test_should_regenerate_without_cache(discovery):
    assert discovery.should_regenerate(None) is True


# --- get_system_params -----------------------------------------------------

def test_manual_disable_short_circuits_discovery(discovery, monkeypatch):
    discovery._manual_disabled = True
    calls = []
    monkeypatch.setattr(discovery, 'discover_params',
                        lambda: calls.append(True) or (set(), STATE_OK))

    assert discovery.get_system_params() == set()
    assert calls == []


def test_fresh_cache_is_used_without_discovery(discovery, monkeypatch, clock):
    discovery.save_params({'GRUB_TIMEOUT'}, STATE_OK)
    calls = []
    monkeypatch.setattr(discovery, 'discover_params',
                        lambda: calls.append(True) or (set(), STATE_OK))

    assert discovery.get_system_params() == {'GRUB_TIMEOUT'}
    assert calls == []


def test_force_regenerate_ignores_fresh_cache(discovery, monkeypatch, clock):
    discovery.save_params({'GRUB_TIMEOUT'}, STATE_OK)
    monkeypatch.setattr(discovery, 'discover_params',
                        lambda: ({'GRUB_DEFAULT'}, STATE_OK))

    assert discovery.get_system_params(force_regenerate=True) == {'GRUB_DEFAULT'}
    assert discovery.cached_data['params'] == {'GRUB_DEFAULT'}


def test_previous_ok_result_is_kept_when_new_attempt_fails(
        discovery, monkeypatch, clock, capsys):
    discovery.save_params({'GRUB_TIMEOUT'}, STATE_OK)
    # Make the OK cache stale so discovery runs again.
    discovery.cached_data['timestamp'] = NOW - WEEK_IN_SECONDS - 1
    monkeypatch.setattr(discovery, 'discover_params',
                        lambda: (set(), STATE_NO_INFO))

    assert discovery.get_system_params() == {'GRUB_TIMEOUT'}
    assert discovery.cached_data['state'] == STATE_OK
    assert 'Keeping previous OK status' in capsys.readouterr().out


# --- get_absent ------------------------------------------------------------

def prime_cache(discovery, params, state=STATE_OK, disabled=False):
    discovery.cached_data = {
        'params': set(params),
        'state': state,
        'timestamp': NOW,
        'manual_disabled': disabled,
    }


def test_get_absent_returns_missing_params(discovery):
    prime_cache(discovery, {'GRUB_TIMEOUT', 'GRUB_DEFAULT',
                            'GRUB_A', 'GRUB_B'})

    assert discovery.get_absent(
        ['GRUB_TIMEOUT', 'GRUB_DEFAULT', 'GRUB_A', 'GRUB_B']) == set()
    # One absent of five is exactly the accepted 20% ratio.
    assert discovery.get_absent(
        ['GRUB_TIMEOUT', 'GRUB_DEFAULT', 'GRUB_A', 'GRUB_B',
         'GRUB_NEW']) == {'GRUB_NEW'}


def test_get_absent_single_probe_bypasses_ratio_guard(discovery):
    prime_cache(discovery, {'GRUB_TIMEOUT'})

    assert discovery.get_absent(['GRUB_MADE_UP']) == {'GRUB_MADE_UP'}


def test_get_absent_rejects_unreliable_probe_results(discovery):
    prime_cache(discovery, {'GRUB_A'})
    # 2 of 5 absent = 40%, above the 20% threshold.
    assert discovery.get_absent(
        ['GRUB_A', 'GRUB_B', 'GRUB_C', 'GRUB_D', 'GRUB_E']) == set()


def test_get_absent_accepts_exactly_twenty_percent(discovery):
    prime_cache(discovery, {'GRUB_A', 'GRUB_B', 'GRUB_C', 'GRUB_D'})

    assert discovery.get_absent(
        ['GRUB_A', 'GRUB_B', 'GRUB_C', 'GRUB_D', 'GRUB_E']) == {'GRUB_E'}


def test_get_absent_requires_ok_and_enabled(discovery):
    prime_cache(discovery, {'GRUB_A'}, state=STATE_NO_INFO)
    assert discovery.get_absent(['GRUB_B']) == set()

    prime_cache(discovery, {'GRUB_A'}, state=STATE_OK, disabled=True)
    discovery._manual_disabled = True
    assert discovery.get_absent(['GRUB_B']) == set()

    discovery._manual_disabled = False
    discovery.cached_data = None
    assert discovery.get_absent(['GRUB_B']) == set()


# --- manual_enable ---------------------------------------------------------

def test_manual_enable_creates_a_cache_when_none_exists(discovery):
    assert discovery.cache_file.exists() is False

    assert discovery.manual_enable(False) is False

    assert discovery.cache_file.is_file()
    assert discovery.cached_data['params'] == set()
    assert discovery.cached_data['state'] == STATE_NO_INFO
    assert discovery.cached_data['manual_disabled'] is True
    assert discovery.manual_enable() is False


def test_manual_enable_preserves_cached_params(discovery):
    discovery.save_params({'GRUB_TIMEOUT'}, STATE_OK)

    assert discovery.manual_enable(False) is False
    text = discovery.cache_file.read_text(encoding='utf-8')
    assert 'GRUB_TIMEOUT' in text
    assert 'manual_disabled: true' in text

    assert discovery.manual_enable(True) is True
    text = discovery.cache_file.read_text(encoding='utf-8')
    assert 'manual_disabled: false' in text


# --- module CLI ------------------------------------------------------------

class FakeCLIDiscovery:
    def __init__(self):
        self.manual = []
        self.force = None
        self.dumped = None

    def manual_enable(self, state=None):
        self.manual.append(state)
        return state

    def get_system_params(self, force_regenerate=False):
        self.force = force_regenerate
        return {'GRUB_TIMEOUT'}

    def dump(self, param_list=None):
        self.dumped = param_list


@pytest.fixture(name='cli_discovery')
def fixture_cli_discovery(monkeypatch):
    fake = FakeCLIDiscovery()
    monkeypatch.setattr(ParamDiscovery, 'get_singleton',
                        staticmethod(lambda: fake))
    return fake


def run_cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, 'argv', ['param-discovery', *argv])
    pd_mod.main()


def test_cli_disable_returns_after_saving_state(monkeypatch, cli_discovery,
                                                capsys):
    run_cli(monkeypatch, '--disable')

    assert cli_discovery.manual == [False]
    assert cli_discovery.force is None
    assert 'disabled' in capsys.readouterr().out


def test_cli_enable_runs_discovery_and_dumps(monkeypatch, cli_discovery):
    run_cli(monkeypatch, '--enable')

    assert cli_discovery.manual == [True]
    assert cli_discovery.force is False
    assert cli_discovery.dumped is None


def test_cli_regenerate_and_compare(monkeypatch, cli_discovery):
    run_cli(monkeypatch, '--regenerate', '--compare', 'GRUB_A, GRUB_B')

    assert cli_discovery.force is True
    assert cli_discovery.dumped == ['GRUB_A', 'GRUB_B']
