"""Regression tests for the command-line switches in ``grub_wiz.main``.

``main()`` normally re-executes itself through ``sudo`` and builds the full
curses UI.  Both are stubbed here so the argument-handling branches can be
exercised without root privileges or a terminal.
"""

import sys
from types import SimpleNamespace

import pytest

import grub_wiz.main as cli


class FakeDiscovery:
    """Minimal stand-in for ``ParamDiscovery``."""

    cache_file = '/nonexistent/system-params.yaml'

    def __init__(self):
        self.state = None
        self.dumped_with = None

    def manual_enable(self, state=None):
        self.state = state
        return state

    def dump(self, defined_param_names=None):
        self.dumped_with = defined_param_names

    def get_absent(self, defined_param_names):
        return set()


@pytest.fixture(name='fake_wiz')
def fixture_fake_wiz(monkeypatch):
    """Replace ``GrubWiz`` and the sudo re-exec with an inert fake."""
    discovery = FakeDiscovery()
    wiz = SimpleNamespace(
        param_discovery=discovery,
        defined_param_names=['quiet', 'splash'],
    )
    monkeypatch.setattr(cli, 'rerun_module_as_root', lambda module_name: None)
    monkeypatch.setattr(cli, 'GrubWiz', lambda cli_opts=None: wiz)
    return wiz


@pytest.mark.parametrize('flag, expected', [('enable', True), ('disable', False)])
def test_discovery_enable_disable_sets_manual_state(monkeypatch, fake_wiz, flag, expected):
    """``--discovery=enable|disable`` calls ``manual_enable`` with a bool.

    Previously this branch read ``opts.paramd`` and raised
    ``AttributeError: 'Namespace' object has no attribute 'paramd'``.
    """
    monkeypatch.setattr(sys, 'argv', ['grub-wiz', f'--discovery={flag}'])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 0
    assert fake_wiz.param_discovery.state is expected


def test_discovery_show_dumps_defined_params(monkeypatch, fake_wiz):
    """``--discovery=show`` dumps the known parameter names."""
    monkeypatch.setattr(sys, 'argv', ['grub-wiz', '--discovery=show'])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 0
    assert fake_wiz.param_discovery.dumped_with == ['quiet', 'splash']
    assert fake_wiz.param_discovery.state is None
