"""core/live_game_gate.py - the single "is a game actually running" predicate.

B4 (RM-189). Riot's third-party rules ban "notifications that dictate player
action based on the current game state", so several unrelated layers now need
to ask the same question: the served-envelope suppression in
``dashboard/_state_builder.py``, the voice output in ``coaches/voice_coach.py``,
and anything added later. The predicate lives here rather than in any one of
them because a second private copy is exactly how a fix stops reaching its
consumers - ``dashboard._state_builder`` re-exports this function rather than
defining its own.

Design + measurements: ``docs/OVERLAY_B4_DESIGN.md``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("rc.live_game_gate")

# Project root is one level above core/.
_APP_DIR = Path(__file__).parent.parent
HEALTH_PATH: Path = _APP_DIR / "ops" / "runtime" / "health.json"

# Any of these on health means a game is actually running. brawl_mode is
# included even though resolve_mode_key does not test it: the brawl coach is
# live-reachable (URF / ARURF / ONEFORALL / GAMEMODEX / NEXUSBLITZ route to
# MODE_BRAWL in core/game_snapshot.py) and issues live Haiku calls.
LIVE_GAME_FLAGS = ("has_game", "aram_mode", "arena_mode", "tft_mode",
                   "brawl_mode")


def is_live_game(health: dict | None, preflip_active: bool = False) -> bool:
    """True when a game is actually running (not champ select, not idle).

    ``preflip_active`` is load-bearing for the SERVED envelope:
    ``dashboard._state_builder.apply_preflip_mirror`` stamps a per-mode flag
    onto its copy of ``health`` during LCU champ select, so the flags alone
    cannot distinguish "in an ARAM" from "sitting in an ARAM lobby". Champ
    select is PRE-game, where coaching stays allowed.

    Callers reading ``ops/runtime/health.json`` off disk do NOT need to pass
    it: the mirror is applied to the served copy only, so the file always
    carries the raw flags. See ``live_game_now``.
    """
    if preflip_active or not isinstance(health, dict):
        return False
    return any(bool(health.get(f)) for f in LIVE_GAME_FLAGS)


def _read_health() -> dict | None:
    """Read ops/runtime/health.json, or None when it is unreadable."""
    return json.loads(HEALTH_PATH.read_text(encoding="utf-8"))


def live_game_now() -> bool:
    """True when health.json says a game is running right now.

    For callers that have no ``/api/state`` envelope in hand (the voice path,
    background workers). FAIL-SAFE by design: an unreadable or missing
    health.json answers False, because "I cannot tell" is not evidence of a
    game, and failing closed would permanently silence the legitimate pre-game
    and post-game surfaces the first time the file went away. The compliance
    guarantee rests on the producer-side suppression, which reads the health
    dict it already holds.
    """
    try:
        return is_live_game(_read_health())
    except Exception:  # noqa: BLE001
        log.debug("live_game_now: health read failed", exc_info=True)
        return False
