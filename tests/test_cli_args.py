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


def test_run_cli_tears_down_curses_on_system_exit(monkeypatch):
    """``sys.exit()`` from a curses-active path still restores the terminal."""
    fake_grubwiz, stopped = _fake_grubwiz_singleton()
    monkeypatch.setattr(cli, 'GrubWiz', fake_grubwiz)

    def quit_now():
        raise SystemExit(0)

    monkeypatch.setattr(cli, 'main', quit_now)

    with pytest.raises(SystemExit) as excinfo:
        cli.run_cli()

    assert excinfo.value.code == 0
    assert stopped == ['stop']


def _fake_grubwiz_singleton():
    """Return a fake ``GrubWiz`` holder and the list of cleanup calls."""
    stopped = []

    class FakeWindow:
        def stop_curses(self):
            stopped.append('stop')

    return SimpleNamespace(singleton=SimpleNamespace(win=FakeWindow())), stopped


def test_run_cli_tears_down_curses_on_exception(monkeypatch):
    """The console entry point must clean up when ``main()`` raises (M14)."""
    fake_grubwiz, stopped = _fake_grubwiz_singleton()
    monkeypatch.setattr(cli, 'GrubWiz', fake_grubwiz)

    def explode():
        raise RuntimeError('boom')

    monkeypatch.setattr(cli, 'main', explode)

    with pytest.raises(SystemExit) as excinfo:
        cli.run_cli()

    assert excinfo.value.code == 15
    assert stopped == ['stop']


def test_run_cli_tears_down_curses_on_interrupt(monkeypatch):
    """Ctrl-C exits 130 and still leaves curses mode."""
    fake_grubwiz, stopped = _fake_grubwiz_singleton()
    monkeypatch.setattr(cli, 'GrubWiz', fake_grubwiz)

    def interrupt():
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, 'main', interrupt)

    with pytest.raises(SystemExit) as excinfo:
        cli.run_cli()

    assert excinfo.value.code == 130
    assert stopped == ['stop']
