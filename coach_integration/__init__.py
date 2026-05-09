# arch: coach_integration package facade | section=coaching | frozen=no
"""Re-exports for backwards compatibility. All callers import from this namespace."""

from ._profiles import CHAMPION_PROFILES, GENERIC_PROFILE, GAME_SENSE_VOCAB  # noqa: F401
from ._sr_prompt import _build_user_prompt, WaveTracker, SR_SYSTEM_PROMPT  # noqa: F401
from ._coach import CoachIntegration  # noqa: F401
