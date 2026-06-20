# arch: RC2-P5.7 deterministic lost-objective + stagnation response | section=core | frozen=no
"""Deterministic lost-objective + stagnation macro response (RC2 P5.7, WS4).

PURPOSE
    docs/research/RC2_COACHING_SPEC.md Workstream 4. P5.5/P5.6 (WS3) coach the
    objective SCHEDULE proactively (drake/baron is spawning, here is the setup).
    WS4 is the REACTIVE half: you just LOST an objective, or the game has
    STALLED, so here is the recovery directive. Two trigger families, both off
    data RC already reads every tick:

      A) LOST-OBJECTIVE - an ENEMY-team kill of dragon/baron/herald within the
         last ~LOSS_WINDOW_S, surfaced as ``objective_events`` from the same Live
         Client events stream that feeds ``inhib_events``
         (dashboard/_liveclient.py). The line is keyed (objective x lead-state)
         with a baron/herald wildcard.
      B) STAGNATION - past 20 min, the macro lead has been STABLE (no swing) for
         a sustained window, no objective was taken recently, and no inhibitor is
         down. The "nothing is happening, make a play" nudge, keyed by the stable
         lead state (ahead -> force a pick, even -> take a side lane, behind ->
         keep scaling).

WHY additive (no flip gate)
    Like the WS3 playbook row, these are NEW advisory ROWS the coach did not
    previously emit - they add a surface rather than replacing a paid Haiku call
    (spec cross-cutting conventions), so the row ships now; only a future flip of
    a served Haiku FIELD onto these directives would be shadow-gated (logged via
    core.macro_response_shadow for the do-not-flip-blind re-measure).

PURE
    No engine, no network, no LLM, no file reads (same contract as
    ``core.event_callouts`` / ``core.lead_projection`` / ``core.objective_playbook``).
    The impure Live Client read (objective_events / inhib_events) lives in the
    dashboard resolver, which passes the lists in. The stagnation WINDOW memory
    (how long the lead has been stable) also lives in the resolver and is passed
    in as ``stable_for_s`` so this function stays stateless + testable with
    explicit timestamps. Fail-soft: any bad / missing input -> ``None`` (no row),
    never raises (the coach hot path contract).
"""
from __future__ import annotations

from typing import Optional

# The neutral objectives a LOST kill event coaches (turrets/inhibs are handled
# elsewhere - inhibs gate stagnation; plates have no recovery directive).
_LOST_OBJECTIVES: frozenset[str] = frozenset({"dragon", "baron", "herald"})

# An enemy objective kill within this many seconds of now is a "fresh loss" worth
# a recovery directive; older losses have already been absorbed into the game
# state (lead/objective schedule) and need no special row.
LOSS_WINDOW_S: float = 45.0

# Stagnation: the game must be past this mark (mid/late) before "nothing is
# happening" is a coachable state - early game is supposed to be quiet.
STAGNATION_MIN_GAME_S: float = 1200.0  # 20:00

# The lead must have been STABLE (no state swing) AND no objective taken for at
# least this long for the game to read as genuinely stalled.
STALL_S: float = 150.0

# An inhibitor counts as "down" (objective pressure exists -> not stalled) for
# this long after it falls (the Live Client InhibKilled respawn window).
INHIB_DOWN_WINDOW_S: float = 300.0

# The three exhaustive macro states project_lead emits; anything else -> "even".
_LEAD_STATES: frozenset[str] = frozenset({"ahead", "even", "behind"})

# (objective, lead_state) -> ONE recovery line (<= 12 words, ASCII, " - " clause
# break). Dragon varies by lead; baron + herald use the "*" wildcard (the
# recovery is the same regardless of lead - defend the buff / match the plates).
LOST_OBJECTIVE_RESPONSE: dict[tuple[str, str], str] = {
    ("dragon", "ahead"):  "Lost drake but ahead - pressure a side lane, next obj",
    ("dragon", "even"):   "Lost drake - catch waves, do not force, match next",
    ("dragon", "behind"): "Lost drake - catch waves, do not force, scale up",
    ("baron", "*"):       "Baron lost - group, defend, clear waves, wait it out",
    ("herald", "*"):      "Herald lost - match their plates, hold mid prio",
}

# Stalled-game directive keyed by the stable lead state (spec 4.2). The four
# canonical break-the-stall actions map here: SPLIT/side-lane (even), PICK +
# vision (ahead), SCALE/wait (behind).
STAGNATION_RESPONSE: dict[str, str] = {
    "ahead":  "Stalled but ahead - force vision and a pick, then objective",
    "even":   "Stalled - take a side lane for a pick, do not coinflip",
    "behind": "Stalled and behind is fine - keep scaling, safe CS",
}


def _lead_state(lead: object) -> str:
    """Extract the macro state from a project_lead dict, defaulting to 'even'.

    A non-dict lead, a missing state, or an out-of-band value all fall back to
    the neutral 'even' read (never raises)."""
    if isinstance(lead, dict):
        state = lead.get("state")
        if isinstance(state, str) and state in _LEAD_STATES:
            return state
    return "even"


def _as_float(val: object) -> Optional[float]:
    """Fail-soft float read (None on garbage / bool)."""
    if isinstance(val, bool) or val is None:
        return None
    if not isinstance(val, (int, float, str)):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _recent_enemy_loss(objective_events: object, now_s: float) -> Optional[str]:
    """The objective name of the most-recent ENEMY kill within the loss window.

    Scans ``objective_events`` ({name, killer_team, down_at_s}) for enemy-team
    kills of a coached objective whose ``down_at_s`` is in
    ``[now_s - LOSS_WINDOW_S, now_s]`` and returns the name of the latest one,
    or ``None``. Garbage entries are skipped."""
    if not isinstance(objective_events, list):
        return None
    best_name: Optional[str] = None
    best_t = float("-inf")
    for ev in objective_events:
        if not isinstance(ev, dict):
            continue
        name = ev.get("name")
        if name not in _LOST_OBJECTIVES:
            continue
        if ev.get("killer_team") != "enemy":
            continue
        t = _as_float(ev.get("down_at_s"))
        if t is None:
            continue
        if t > now_s or (now_s - t) > LOSS_WINDOW_S:
            continue
        if t > best_t:
            best_t = t
            best_name = name
    return best_name


def _any_recent_objective(objective_events: object, now_s: float,
                          window_s: float) -> bool:
    """True if ANY team's objective kill falls within the last ``window_s``."""
    if not isinstance(objective_events, list):
        return False
    for ev in objective_events:
        if not isinstance(ev, dict):
            continue
        t = _as_float(ev.get("down_at_s"))
        if t is None:
            continue
        if 0 <= (now_s - t) <= window_s:
            return True
    return False


def _any_inhib_down(inhib_events: object, now_s: float) -> bool:
    """True if any inhibitor is currently down (fell within the respawn window)."""
    if not isinstance(inhib_events, list):
        return False
    for ev in inhib_events:
        if not isinstance(ev, dict):
            continue
        t = _as_float(ev.get("down_at_s"))
        if t is None:
            continue
        if 0 <= (now_s - t) <= INHIB_DOWN_WINDOW_S:
            return True
    return False


def lost_objective_response(
    objective_events: object,
    lead: object,
    game_time_s: object,
) -> Optional[str]:
    """The recovery line for a freshly-lost neutral objective, or ``None``.

    Args:
        objective_events: the {name, killer_team, down_at_s} list (from
            dashboard/_liveclient.py).
        lead: the project_lead dict ({state, ...}).
        game_time_s: current game time in seconds.

    Returns the directive string or ``None`` (no recent enemy loss). Fail-soft.
    """
    try:
        now_s = _as_float(game_time_s)
        if now_s is None:
            return None
        name = _recent_enemy_loss(objective_events, now_s)
        if name is None:
            return None
        state = _lead_state(lead)
        return (LOST_OBJECTIVE_RESPONSE.get((name, state))
                or LOST_OBJECTIVE_RESPONSE.get((name, "*")))
    except Exception:  # noqa: BLE001 - the coach hot path must never raise
        return None


def stagnation_response(
    objective_events: object,
    lead: object,
    game_time_s: object,
    inhib_events: object,
    *,
    stable_for_s: float = 0.0,
) -> Optional[str]:
    """The "break the stall" line when the game has genuinely stalled, else None.

    Gates (all must hold): past STAGNATION_MIN_GAME_S; the lead has been stable
    for >= STALL_S (``stable_for_s``, tracked by the resolver); no objective
    taken by either team in the last STALL_S; no inhibitor currently down. The
    line is keyed by the (stable) lead state.

    ``stable_for_s`` defaults to 0.0 so a caller without window memory never
    produces a false stall (the row simply never fires until the resolver feeds
    a real duration). Fail-soft.
    """
    try:
        now_s = _as_float(game_time_s)
        if now_s is None or now_s <= STAGNATION_MIN_GAME_S:
            return None
        if _as_float(stable_for_s) is None or stable_for_s < STALL_S:
            return None
        if _any_recent_objective(objective_events, now_s, STALL_S):
            return None
        if _any_inhib_down(inhib_events, now_s):
            return None
        return STAGNATION_RESPONSE.get(_lead_state(lead))
    except Exception:  # noqa: BLE001 - the coach hot path must never raise
        return None


def macro_response_callout(
    objective_events: object,
    lead: object,
    game_time_s: object,
    inhib_events: object,
    *,
    stable_for_s: float = 0.0,
) -> Optional[dict]:
    """Return ONE ``kind="macro_response"`` reactive macro row, or ``None``.

    A concrete lost-objective directive takes precedence over the generic
    stagnation nudge (a fresh event is more actionable than a stall). The row is
    a standing advisory (``eta_s`` None) like the heal-threat row, so the dashboard
    callouts renderer paints it with no web change.

    Returns ``{tag, line, eta_s: None, kind: "macro_response"}`` where tag is
    "macro_lost_objective" or "macro_stagnation", or ``None`` when neither fires.
    Fail-soft: any error -> None.
    """
    try:
        lost = lost_objective_response(objective_events, lead, game_time_s)
        line = lost or stagnation_response(
            objective_events, lead, game_time_s, inhib_events,
            stable_for_s=stable_for_s,
        )
        if not line:
            return None
        return {
            "tag": "macro_lost_objective" if lost else "macro_stagnation",
            "line": line,
            "eta_s": None,
            "kind": "macro_response",
        }
    except Exception:  # noqa: BLE001 - the coach hot path must never raise
        return None


__all__ = [
    "LOST_OBJECTIVE_RESPONSE",
    "STAGNATION_RESPONSE",
    "lost_objective_response",
    "stagnation_response",
    "macro_response_callout",
]
