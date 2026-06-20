# arch: RC2-P5.5 deterministic objective playbook callout | section=core | frozen=no
"""Deterministic mid/late-game objective playbook callout (RC2 P5.5, WS3).

PURPOSE
    docs/research/RC2_COACHING_SPEC.md Workstream 3. RC already has the objective
    SCHEDULE (``core.event_callouts.next_callouts`` - drake 5:00, herald 14:00,
    baron 20:00, elder) and the macro lead read (``core.lead_projection.
    project_lead`` - ahead / even / behind). The GAP is the deterministic
    playbook that JOINS them into one directive: "given (objective spawning in T)
    x (you are ahead/even/behind) x phase, here is the setup + the fight/concede
    rule". This module is that join.

WHY additive (no flip gate)
    Unlike the laning A/B chips (WS1/WS2, which REPLACE a Haiku output and so are
    shadow-gated), this is a NEW advisory ROW the coach did not previously emit -
    it adds a surface rather than replacing a paid call (spec cross-cutting
    conventions). So the callout row ships now; only a future flip of the served
    ``objective`` FIELD onto this row is gated (logged via
    core.objective_playbook_shadow for the do-not-flip-blind re-measure).

PURE
    No engine, no network, no LLM, no file reads (same contract as
    ``core.event_callouts`` / ``core.lead_projection``). The impure
    ``vision_state.json`` read lives in the dashboard resolver, which passes the
    summary counts in. Fail-soft: any bad / missing input -> ``None`` (no row),
    never raises (the coach hot path contract).
"""
from __future__ import annotations

from typing import Optional

# The neutral objectives this playbook coaches. ``plates`` (a gold/shove event,
# no fight/concede decision) and every spike/recall/inhib row are deliberately
# excluded - they have no (setup, fight rule) entry.
_PLAYBOOK_OBJECTIVES: tuple[str, ...] = ("dragon", "baron", "herald", "elder")

# Short display titles (the objective row above uses "Drake ..."; the playbook
# row self-identifies with the same word so the pair reads as one block).
_TITLE: dict[str, str] = {
    "dragon": "Drake", "baron": "Baron", "herald": "Herald", "elder": "Elder",
}

# Phase gating: an objective only earns a playbook row in a phase where it is
# actually contestable. Baron is a mid/late call; Elder is late only; Drake and
# Herald can be coached in any phase (the first drake is an early-game fight).
# An objective missing here is unrestricted. Phases mirror lead_projection._phase.
_PHASE_ALLOWED: dict[str, frozenset[str]] = {
    "baron": frozenset({"mid", "late"}),
    "elder": frozenset({"late"}),
}

# The three exhaustive macro states project_lead emits; anything else -> "even".
_LEAD_STATES: frozenset[str] = frozenset({"ahead", "even", "behind"})

# An objective whose ETA is at/under this many seconds (or already active, eta
# <= 0) is "near" enough that a live CV read (enemy dead / enemies missing) is
# still relevant to THIS objective's fight. A far objective (baron 9 min out)
# does not get a CV upgrade off the current fog state.
_NEAR_S: float = 60.0

# At/above this many missing enemies near an objective, assume the enemy is
# grouping to contest it (spec 3.3 selector).
_CONTEST_MISSING_N: int = 3

# (objective, lead_state) -> ONE directive line (<= 12 words, ASCII, " - " clause
# break). Elder uses the "*" wildcard (its call does not vary by lead - it is the
# game either way). Derived from spec 3.3's (setup, fight rule) pairs, phrased as
# one clean line so the dashboard callout row stays a single glanceable string.
OBJECTIVE_PLAYBOOK: dict[tuple[str, str], str] = {
    ("dragon", "ahead"):  "Drake: set deep vision, force them off - you have tempo",
    ("dragon", "even"):   "Drake: match prio, ward both pits - fight only with numbers",
    ("dragon", "behind"): "Drake: trade it for a lane - do not contest down",
    ("baron", "ahead"):   "Baron: ward early, zone them off - start on a pick",
    ("baron", "even"):    "Baron: get a pick first - no pick, no baron",
    ("baron", "behind"):  "Baron: do not face-check - defend, take on their mistake",
    ("herald", "ahead"):  "Herald: take it, slam a plate - keep prio",
    ("herald", "even"):   "Herald: contest only with prio - else trade for scuttle",
    ("herald", "behind"): "Herald: give it, catch side waves - avoid the 50/50",
    ("elder", "*"):       "Elder: group as five, full vision - no greed",
}

# RC2 P5.6 (WS3 late-game): in the LATE phase the objective calculus shifts to
# CLOSING - baron is a game-ending tool (not just a buff) and a late drake is
# soul-stakes (group-five territory). These escalations are consulted FIRST when
# phase == "late" and fall back to OBJECTIVE_PLAYBOOK when absent. Only baron +
# dragon escalate: elder is ALREADY a closing call (its base "*" line stands) and
# herald is gone by late (one-shot 14:00), so neither earns a late entry - a late
# herald lookup correctly falls back to its base line. Same conventions: <= 12
# words, ASCII, " - " clause break.
LATE_OBJECTIVE_PLAYBOOK: dict[tuple[str, str], str] = {
    ("baron", "ahead"):   "Baron: take it and close - end on the buff",
    ("baron", "even"):    "Baron: land a pick first - then take to end",
    ("baron", "behind"):  "Baron: do not contest - defend and clear waves",
    ("dragon", "ahead"):  "Late drake: group five, take it - then push",
    ("dragon", "even"):   "Late drake: full vision - fight only even or ahead",
    ("dragon", "behind"): "Late drake: do not throw - defend, deny the catch",
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


def _phase_ok(tag: str, phase: object) -> bool:
    """Is ``tag`` contestable in ``phase``? Unrestricted objectives always pass;
    a non-str phase fails any restricted objective (conservative)."""
    allowed = _PHASE_ALLOWED.get(tag)
    if allowed is None:
        return True
    return isinstance(phase, str) and phase in allowed


def _select_objective(callouts: object, phase: object) -> Optional[dict]:
    """The soonest covered + phase-allowed objective row from a callouts list.

    ``callouts`` is already eta-sorted (active-first) by the caller
    (next_callouts), so the first matching row is the most imminent. Garbage
    entries are skipped. Returns the callout dict or ``None``."""
    if not isinstance(callouts, list):
        return None
    for row in callouts:
        if not isinstance(row, dict):
            continue
        tag = row.get("tag")
        if tag in _PLAYBOOK_OBJECTIVES and _phase_ok(tag, phase):
            return row
    return None


def _is_near(eta_s: object) -> bool:
    """True when an objective ETA is active (<= 0) or within _NEAR_S seconds."""
    if eta_s is None or isinstance(eta_s, bool):
        return False
    if not isinstance(eta_s, (int, float)):
        return False
    return eta_s <= _NEAR_S


def _count(summary: object, key: str) -> int:
    """Fail-soft non-negative int read of a vision-summary count (0 on garbage)."""
    if not isinstance(summary, dict):
        return 0
    val = summary.get(key)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return 0
    n = int(val)
    return n if n > 0 else 0


def playbook_callout(
    callouts: object,
    lead: object,
    vision_summary: object,
    phase: object,
) -> Optional[dict]:
    """Return one ``kind="playbook"`` objective directive row, or ``None``.

    Joins the objective schedule (``callouts`` from next_callouts) with the macro
    lead read (``lead`` from project_lead) into a single, lead-aware directive for
    the soonest contestable objective. A live CV read (``vision_summary`` counts
    from vision_state.json) upgrades the line when the objective is NEAR: an enemy
    dead while you are ahead -> "free objective, take it now"; >= 3 enemies
    missing -> "assume contest".

    Args:
        callouts: the eta-sorted callout list (next_callouts output).
        lead: the project_lead dict ({state, magnitude, line, source_tag}).
        vision_summary: vision_state.json ``summary`` ({visible_count,
            missing_count, dead_count, total}) or None.
        phase: the early/mid/late phase string (lead_projection.phase_for).

    Returns:
        ``{tag, line, eta_s, kind}`` with kind == "playbook", tag ==
        "playbook_<objective>", eta_s == the objective's eta (so it sorts
        adjacent to its schedule row), or ``None`` when no contestable objective
        is in range. Fail-soft: any error -> None.
    """
    try:
        obj = _select_objective(callouts, phase)
        if obj is None:
            return None
        tag = str(obj.get("tag"))
        eta_s = obj.get("eta_s")
        state = _lead_state(lead)

        # Late-game escalation (P5.6): closing-focused baron/dragon directives win
        # in the late phase; everything else (and a missing late entry) falls back
        # to the base table + the elder "*" wildcard.
        base = None
        if phase == "late":
            base = LATE_OBJECTIVE_PLAYBOOK.get((tag, state))
        if not base:
            base = OBJECTIVE_PLAYBOOK.get((tag, state)) or OBJECTIVE_PLAYBOOK.get((tag, "*"))
        if not base:
            return None

        title = _TITLE.get(tag, tag.title())
        line = base

        # CV upgrades only when the objective is near (the fog read is about THIS
        # fight). Enemy-dead-while-ahead is the highest-signal upgrade and wins
        # over the missing-contest warning.
        if _is_near(eta_s):
            if state == "ahead" and _count(vision_summary, "dead_count") >= 1:
                line = f"{title}: free objective, enemy down - take it now"
            elif _count(vision_summary, "missing_count") >= _CONTEST_MISSING_N:
                line = f"{title}: enemies missing - group and assume contest"

        return {
            "tag": f"playbook_{tag}",
            "line": line,
            "eta_s": eta_s,
            "kind": "playbook",
        }
    except Exception:  # noqa: BLE001 - the coach hot path must never raise
        return None


__all__ = ["OBJECTIVE_PLAYBOOK", "LATE_OBJECTIVE_PLAYBOOK", "playbook_callout"]
