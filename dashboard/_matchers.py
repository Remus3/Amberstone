# arch: path-matcher factories (stdlib-only, importable without pydantic) | section=dashboard | frozen=no
"""The two route path matchers, split out of _dispatch.py on 2026-07-31.

Reason for the split, so it is not "simplified" back later: importing
dashboard._dispatch executes `from dashboard.api_schema import ...`, which
imports pydantic. Mission Control (mc/) imports the two loop-route modules in
its own process and must NOT inherit that dependency - the whole point of S10
is that the control plane does not share a failure domain with dashboard
schema code. Keep this module stdlib-only. It is guarded by
tests/test_mission_control_server.py::test_matchers_module_is_stdlib_only.

_dispatch re-exports both names, so the 40-plus route modules that do
`from dashboard._dispatch import equals` keep working unchanged.
"""
from __future__ import annotations

from typing import Callable


def equals(path: str) -> Callable[[str], bool]:
    """Match exactly `path`, or `path?...` (path with a query string)."""
    return lambda p: p == path or p.startswith(path + "?")


def prefix(p: str) -> Callable[[str], bool]:
    """Match anything starting with prefix `p`."""
    return lambda x: x.startswith(p)
