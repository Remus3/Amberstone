# arch: Mission Control route tables (imports, never forks, the loop routes) | section=mc | frozen=no
"""GET/POST tables for the Mission Control server.

These are the SAME route modules the dashboard used to serve, imported
directly. There is no second copy of any handler, and there must never be:
the repo already carries one byte-identical-by-contract pair and does not
need a second class of them.

Import safety is load-bearing and guarded. Both modules import their path
matcher from dashboard._matchers (NOT dashboard._dispatch), which is what
keeps pydantic and the game route tree out of this process. See
tests/test_mission_control_server.py::test_mc_package_imports_no_game_code.
"""
from __future__ import annotations

from dashboard import routes_loop_control, routes_loop_status

GET_ROUTES: list = (
    list(routes_loop_status.GET_ROUTES) + list(routes_loop_control.GET_ROUTES)
)
POST_ROUTES: list = (
    list(routes_loop_status.POST_ROUTES) + list(routes_loop_control.POST_ROUTES)
)
