"""View-router state machine — Python mirror of `web/js/main.js:_viewAutoDerive`.

**TEST MIRROR — NOT IMPORTED AT RUNTIME.** The JS function in `main.js`
remains the canonical runtime implementation. This module exists so the
pure state-transition logic can be exercised under pytest without
spinning up a headless browser. If you change one, change both — both
should agree on the same transition table.

The state machine has two layers:

1. **Sticky guard** (`gameStarted`): tracks the highest game-state observed
   this session. ChampSelect → champ-select → game-start → in-progress →
   None. Rides through transient LCU phase=null/Lobby blips during the
   CS→loading→game flip. Cleared on stable post-game phases.
2. **View derivation**: maps (phase, mode, gameStarted, feature flags) to
   one of `VIEW_IDS` per the precedence rules in `_viewAutoDerive`.

s171.8 additions covered here:
- Sticky-guard inference: ChampSelect→null (no GameStart observed) advances
  gameStarted to "game-start" so the loading view shows during the
  ChampSelect-end → InProgress gap.
- Dodge clearing: ChampSelect→Lobby/Matchmaking/ReadyCheck/None clears the
  sticky guard (user backed out before game start).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

VIEW_IDS = (
    "home", "lobby", "champ-select", "loading", "active-match", "last-match",
    "session", "history", "replay",
    "user-builds", "settings", "dev",
)

IN_GAME_MODES = frozenset({"sr", "aram", "arena", "brawl", "tft"})

# Stable post-game phases — once observed after in-progress, clear sticky.
_POSTGAME_PHASES = frozenset({
    "EndOfGame", "PreEndOfGame", "WaitingForStats", "TerminatedInError", "Lobby",
})

# Phases that signal a dodge when prior sticky was champ-select.
_DODGE_PHASES = frozenset({"Lobby", "Matchmaking", "ReadyCheck", "None"})

# Phases that trigger sticky-clear evaluation (the "else if" arm in JS).
_STICKY_CLEAR_PHASES = frozenset({
    "EndOfGame", "PreEndOfGame", "WaitingForStats", "TerminatedInError",
    "Lobby", "Matchmaking", "ReadyCheck", "None",
})

_LOBBY_PHASES = frozenset({"Lobby", "Matchmaking", "ReadyCheck"})


@dataclass
class DeriveResult:
    """Output of `derive_view`: the resolved view ID + the updated sticky guard."""
    view: str
    game_started: Optional[str]


def update_game_started(
    phase: Optional[str],
    prior: Optional[str],
) -> Optional[str]:
    """Advance the sticky `gameStarted` flag per the JS transition table.

    Maps to the `_VIEW.gameStarted` mutations in `_viewAutoDerive` lines
    491-525. Pure function: returns the new value; never mutates inputs.
    """
    if phase == "ChampSelect":
        return "champ-select"
    if phase == "GameStart":
        return "game-start"
    if phase == "InProgress":
        return "in-progress"

    if phase in _STICKY_CLEAR_PHASES:
        # In-progress → stable post-game: clear sticky.
        if prior == "in-progress" and phase in _POSTGAME_PHASES:
            return None
        # ChampSelect dodge: user backed out, clear sticky.
        if prior == "champ-select" and phase in _DODGE_PHASES:
            return None
        return prior

    # s171.8 sticky-guard inference: ChampSelect ended but phase not stable —
    # must be the loading-screen window (LCU drops phase to null/empty for
    # ~hundred ms between CS ending and GameStart firing).
    if prior == "champ-select" and not phase:
        return "game-start"

    return prior


def derive_view(
    phase: Optional[str],
    mode: Optional[str],
    prior_game_started: Optional[str],
    *,
    active_match_enabled: bool = True,
) -> DeriveResult:
    """Pure mirror of `_viewAutoDerive(lcu, mode)` from main.js.

    Returns the resolved view ID and the updated sticky-guard value.
    Caller is responsible for persisting the new `game_started` for the
    next tick (the JS version mutates `_VIEW.gameStarted` in place).
    """
    game_started = update_game_started(phase, prior_game_started)

    # Phase-driven explicit returns first.
    if phase == "GameStart":
        return DeriveResult("loading", game_started)
    if active_match_enabled and phase == "InProgress":
        return DeriveResult("active-match", game_started)
    if active_match_enabled and not phase and mode in IN_GAME_MODES:
        return DeriveResult("active-match", game_started)
    if phase == "ChampSelect":
        return DeriveResult("champ-select", game_started)
    if phase == "InProgress":
        # active_match_enabled=False fallback.
        return DeriveResult("last-match", game_started)

    # Sticky-guard fallbacks during transient null/Lobby blips.
    if game_started == "game-start":
        return DeriveResult("loading", game_started)
    if game_started == "in-progress":
        return DeriveResult(
            "active-match" if active_match_enabled else "last-match",
            game_started,
        )
    if game_started == "champ-select":
        return DeriveResult("champ-select", game_started)

    if phase in _LOBBY_PHASES:
        return DeriveResult("lobby", game_started)
    if mode in (None, "", "client", "lobby"):
        return DeriveResult("home", game_started)
    return DeriveResult("last-match", game_started)


def is_urgent(target_view: str) -> bool:
    """Mirror of `_viewIsUrgent` — auto-promotes past manual selection.

    Used by the JS view-router to decide whether an urgent game-state
    transition should override a sticky manual view choice and surface a
    banner instead.
    """
    return target_view in ("lobby", "champ-select", "loading", "last-match")
