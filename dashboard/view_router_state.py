"""View-router state machine - Python mirror of `web/js/main.js:_viewAutoDerive`.

**TEST MIRROR - NOT IMPORTED AT RUNTIME.** The JS function in `main.js`
remains the canonical runtime implementation. This module exists so the
pure state-transition logic can be exercised under pytest without
spinning up a headless browser. If you change one, change both - both
should agree on the same transition table.

The state machine has two layers:

1. **Sticky guard** (`gameStarted`): tracks the highest game-state observed
   this session. ChampSelect → champ-select → in-progress → None. Rides
   through transient LCU phase=null/Lobby blips during the CS→game flip.
   Cleared on stable post-game phases.
2. **View derivation**: maps (phase, mode, gameStarted, feature flags) to
   one of `VIEW_IDS` per the precedence rules in `_viewAutoDerive`.

s209 changes:
- Dropped the `loading` view tier entirely. GameStart now routes directly
  to `active-match` (games load too fast for a dedicated loading screen
  to be useful; active-match renders its own waiting state).
- Dropped the `game-start` sticky tier. GameStart sets sticky directly
  to `in-progress`; CS→null inference advances to `in-progress` as well,
  so the CS-end → InProgress gap renders active-match.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

VIEW_IDS = (
    "home", "lobby", "champ-select", "active-match", "last-match",
    "session", "history", "replay",
    "user-builds", "settings",
)

IN_GAME_MODES = frozenset({"sr", "aram", "arena", "brawl", "tft"})

# Stable post-game phases - once observed after in-progress, clear sticky.
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
    *,
    live: bool = True,
) -> Optional[str]:
    """Advance the sticky `gameStarted` flag per the JS transition table.

    s209: GameStart now maps to "in-progress" (was "game-start" pre-s209
    when the loading view existed). CS→null inference also advances to
    "in-progress" rather than the dropped "game-start" tier.

    ``live`` gates ONLY the CS→null inference (see below). ``lcu.phase`` is a
    polled, relay-forwarded value that reads null/empty on any agent request
    fail, stale relay push, or empty frontend poll. During champ select those
    blips are frequent; pre-gate, a single one promoted the sticky to
    in-progress and flipped the view to the in-game page (active-match) and
    could stick there until a stable post-game phase. Defaults True so direct
    callers / the s209 inference are unchanged; the runtime passes the real
    value. The genuine CS→game flip is still caught by the ungated
    GameStart/InProgress phase arms, so gating the null-only inference on
    ``live`` loses no real promotion.
    """
    if phase == "ChampSelect":
        return "champ-select"
    if phase == "GameStart":
        return "in-progress"
    if phase == "InProgress":
        return "in-progress"

    if phase in _STICKY_CLEAR_PHASES:
        # In-progress -> stable post-game: clear sticky.
        if prior == "in-progress" and phase in _POSTGAME_PHASES:
            return None
        # ChampSelect dodge: user backed out, clear sticky.
        if prior == "champ-select" and phase in _DODGE_PHASES:
            return None
        return prior

    # s209 sticky-guard inference: ChampSelect ended but phase not stable -
    # must be the gap between CS ending and InProgress firing. Advance to
    # "in-progress" so the gap renders active-match. Gated on ``live`` so a
    # transient null-phase blip DURING champ select (no game running) does
    # not misfire into the in-game view.
    if prior == "champ-select" and not phase and live:
        return "in-progress"

    return prior


def derive_view(
    phase: Optional[str],
    mode: Optional[str],
    prior_game_started: Optional[str],
    *,
    active_match_enabled: bool = True,
    live: bool = True,
) -> DeriveResult:
    """Pure mirror of `_viewAutoDerive(lcu, mode)` from main.js.

    Returns the resolved view ID and the updated sticky-guard value.
    Caller is responsible for persisting the new `game_started` for the
    next tick (the JS version mutates `_VIEW.gameStarted` in place).

    ``live`` (item 281): is a real game running? Cross-mode signal =
    liveclient non-empty. Defaults True so existing callers and the s209
    null-after-CS loading inference are unchanged; the runtime passes the
    real value. Guards the two paths that would otherwise promote an
    in-game view off a STALE mode flag with no game: the null-phase +
    in-game-mode promotion, and the in-game-mode catch-all fallthrough.
    An explicit GameStart/InProgress phase is itself a live signal, so
    those are NOT gated on ``live`` (the game may be loading before
    LiveClient :2999 answers).
    """
    game_started = update_game_started(phase, prior_game_started, live=live)

    # s209: GameStart routes to active-match (was "loading" pre-s209).
    if phase == "GameStart" and active_match_enabled:
        return DeriveResult("active-match", game_started)
    if active_match_enabled and phase == "InProgress":
        return DeriveResult("active-match", game_started)
    # item 281: only infer active-match from a null phase + in-game mode
    # when a game is actually live. Without this, a stale aram/sr mode flag
    # during an idle lobby (LCU phase blipped to null) promoted a phantom
    # active-match rendering an old coach payload as a live match.
    if active_match_enabled and not phase and mode in IN_GAME_MODES and live:
        return DeriveResult("active-match", game_started)
    if phase == "ChampSelect":
        return DeriveResult("champ-select", game_started)
    if phase == "GameStart":
        # active_match_enabled=False fallback.
        return DeriveResult("last-match", game_started)
    if phase == "InProgress":
        # active_match_enabled=False fallback.
        return DeriveResult("last-match", game_started)

    # Sticky-guard fallbacks during transient null/Lobby blips. The sticky
    # is only set via an observed ChampSelect/GameStart/InProgress this
    # session, so it legitimately carries a real game through a null blip
    # (liveclient may briefly lag) - not gated on ``live``.
    if game_started == "in-progress":
        return DeriveResult(
            "active-match" if active_match_enabled else "last-match",
            game_started,
        )
    if game_started == "champ-select":
        return DeriveResult("champ-select", game_started)

    if phase in _LOBBY_PHASES:
        return DeriveResult("lobby", game_started)
    # item 281: when no game is live, an in-game mode flag (left stale from
    # a prior game) must fall back to home, not the in-game last-match grid.
    if mode in (None, "", "client", "lobby") or not live:
        return DeriveResult("home", game_started)
    return DeriveResult("last-match", game_started)


def is_urgent(target_view: str) -> bool:
    """Mirror of `_viewIsUrgent` - auto-promotes past manual selection.

    s209: dropped "loading"; replaced with "active-match".
    """
    return target_view in ("lobby", "champ-select", "active-match", "last-match")
