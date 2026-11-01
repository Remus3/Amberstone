# arch: coach_integration package facade | section=coaching | frozen=no
"""Re-exports for backwards compatibility. All callers import from this namespace."""

from agents.daemon_slayer._log_names import LOGGER_NAMES as _DS_LOGGER_NAMES
from core.log_scrub import install_scrub_filter as _install_scrub_filter

from ._profiles import CHAMPION_PROFILES, GENERIC_PROFILE, GAME_SENSE_VOCAB  # noqa: F401
from ._sr_prompt import _build_user_prompt, WaveTracker, SR_SYSTEM_PROMPT  # noqa: F401
from ._coach import CoachIntegration  # noqa: F401

# RM-1282: _sr_prompt loads the DS engine in the RC main process, where the
# dashboard installer (RM-1280) runs only if main.py's guarded web_dashboard
# import succeeds. main.py imports this package unconditionally, so the engine
# loggers get the backstop here too (idempotent: one filter per logger). No
# engine module logs while it is imported (RM-1281), so installing after the
# re-exports misses nothing.
_install_scrub_filter(*_DS_LOGGER_NAMES)
