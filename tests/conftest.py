"""Shared pytest configuration for the grub-wiz test suite.

The production code uses process-wide singletons for user/system state.
``GrubFile`` asks ``ParamDiscovery`` which parameters are absent on the host,
and constructing ``ParamDiscovery`` creates the real ``~/.config/grub-wiz``
(and a system-state fallback) as a side effect.

For tests we replace the singleton accessor with a tiny in-memory object so
the suite never reads or writes the invoking user's configuration directory,
and so results do not depend on a stale ``system-params.yaml`` cache.
"""

from types import SimpleNamespace

import pytest

from grub_wiz.ParamDiscovery import ParamDiscovery


@pytest.fixture(autouse=True)
def isolated_param_discovery(monkeypatch):
    """Keep tests independent of the host's GRUB discovery cache."""
    fake_discovery = SimpleNamespace(
        # No parameter is considered absent on the test host.
        get_absent=lambda _params: set(),
        manual_enable=lambda _state=None: True,
        # Startup refreshes the discovery cache; tests must not shell out.
        ensure_discovered=lambda: set(),
    )
    monkeypatch.setattr(
        ParamDiscovery,
        "get_singleton",
        staticmethod(lambda: fake_discovery),
    )
