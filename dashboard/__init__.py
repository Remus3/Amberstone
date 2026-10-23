"""Dashboard package - extracted from web_dashboard.py.

Slice 2B (2026-05-01): pure-builder helpers carved out of
web_dashboard.py. Slice 2C will move route handlers into
`dashboard/routes_*.py` and adopt this package's `_context`
for the shared sqlite conn cache + APP_DIR.

RM-811 residuals (2026-10-23): every logger a dashboard module creates
carries the core.log_scrub backstop, installed here so it is in place before
any submodule logs - in the :8888 process and in Mission Control, which
imports routes_loop_{status,control}. The sweep measured 244 route call sites
logging exception (and request) text unscrubbed; per-site ``scrub_log``
stays the precise fix where it is applied, and this catches the rest and
every future one. LOGGER_NAMES is enumerated from source by
tests/test_log_scrub_residuals_rm811b.py, so a module that adds a new
logger name fails that guard until it is listed.
"""
from core.log_scrub import install_scrub_filter as _install_scrub_filter

LOGGER_NAMES = (
    "rc.web_dashboard",
    "rc.dispatch",
    "rc.moon_sync_status",
    "rc.party_mains",
    "rc.routes_champions",
    "rc.routes_events",
    "rc.routes_team_context",
    "dashboard.routes_ops_panels",
    "dashboard.routes_player_snapshot",
)

_install_scrub_filter(*LOGGER_NAMES)
