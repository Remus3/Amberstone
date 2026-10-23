# arch: Mission Control standalone serving layer (S10) | section=mc | frozen=no
"""Mission Control - the RC control plane, served as its own process.

S10 (2026-07-31) moved the SERVING layer out of the RC game dashboard. The
LOGIC did not move: lanes, launcher, steer, interrupt and intents all still
live in ops/loop/*, and the HTTP routes are the existing
dashboard.routes_loop_{status,control} modules, imported rather than forked.

Nothing in this package may import game-dashboard code. See
tests/test_mission_control_server.py for the guard that enforces it.

RM-811 residuals (2026-10-23): this package's loggers carry the
core.log_scrub backstop (the route modules' logger gets it from
dashboard/__init__). Guarded by tests/test_log_scrub_residuals_rm811b.py.
"""
from core.log_scrub import install_scrub_filter as _install_scrub_filter

LOGGER_NAMES = ("rc.mc.handler", "rc.mc.server")

_install_scrub_filter(*LOGGER_NAMES)
