# arch: ordered pure-rule registry for deterministic macro callouts | section=core | frozen=no
"""core.macro_decision_tree - fog-only deterministic macro callouts (v0).

ZOI Wave-2 agent-macro (docs/ZOI_DISTRICT_ORCHESTRATION_PLAN.md, spec D,
operator decision 3: fog-only v0). Mirrors the DECISION_REGISTRY
registry-of-pure-predicates doctrine (core/decision_detector.py:133-142):
an ORDERED registry of pure rules per mode, each rule a
``(predicate(ctx) -> bool, emit(ctx) -> callout)`` pair. ``evaluate``
walks the mode's rules first-match-wins and returns at most ONE callout
in the canonical ``{tag, line, eta_s, kind}`` schema
(core/event_callouts.py:265-274) with ``kind="macro"`` - deliberately
distinct from the WS4 ``kind="macro_response"`` row
(core/macro_response.py:267), no naming collision.

MODE REGISTRY: SR carries the v0 rules. ARAM and ARENA are registered as
EMPTY-but-present modes (shared vision / no fog - no rule can ever apply)
and there is NO fallback to the SR rules for them or for unknown modes.

WARD GATE: action text says "ward" ONLY when
``core.mode_capabilities.has_capability(mode, "has_wards")`` is True
(fail-CLOSED); otherwise the action degrades to group/back off.

v1 SEAM: ``evaluate(ctx, zoi=None, districts=None)`` accepts and IGNORES
the district kwargs in v0; a later wave adds district-weight predicates
without changing the call sites.

FAIL-SOFT CONTRACT: ``evaluate`` never raises - unknown mode, garbage
context, or a raising rule degrades to None (no callout).

NORTH-STAR: every macro read this tree precomputes is a read the coach
otherwise pays an LLM for. This module makes ZERO network/LLM calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from core.mode_capabilities import has_capability

# MIA floors (seconds). A blip of fog is not a macro signal: the objective
# rule wants a real rotation (>= MIN_MIA_S), the gank warning wants the
# longer lane-roam-grade absence the decision detector also uses
# (core/decision_detector.py:362 uses >= 12s).
MIN_MIA_S = 8.0
GANK_MIN_MIA_S = 12.0

# Objective-danger window: the spawn is "live" from OBJECTIVE_WINDOW_S out
# down to a short post-spawn grace (same -5..60 shape as
# core/decision_detector.py:209).
OBJECTIVE_WINDOW_S = 60.0
OBJECTIVE_GRACE_S = 5.0

# The gank warning is a LANING-phase read (core.lead_projection phase
# boundaries: early < 600s).
_LANING_PHASE = "early"

_OBJECTIVE_LABELS = {"dragon": "Drake", "baron": "Baron"}


@dataclass(frozen=True)
class MacroRule:
    """One pure rule: fires ``emit(ctx)`` when ``predicate(ctx)`` holds."""

    name: str
    predicate: Callable
    emit: Callable


def _soonest_objective(ctx) -> Optional[tuple]:
    """(tag, eta_s) of the soonest dragon/baron inside the danger window,
    or None when neither is live."""
    candidates = []
    for tag, eta in (("dragon", ctx.next_dragon_eta_s),
                     ("baron", ctx.next_baron_eta_s)):
        if not isinstance(eta, (int, float)) or isinstance(eta, bool):
            continue
        if -OBJECTIVE_GRACE_S <= eta <= OBJECTIVE_WINDOW_S:
            candidates.append((float(eta), tag))
    if not candidates:
        return None
    eta, tag = min(candidates)
    return tag, eta


def _objective_action(mode: object) -> str:
    """The action clause: "ward" ONLY when the mode has wards (fail-CLOSED
    truth table); otherwise group/back off."""
    if has_capability(mode, "has_wards"):
        return "ward the pit and group"
    return "group up or back off"


def _objective_danger_pred(ctx) -> bool:
    return (len(ctx.missing_enemies(MIN_MIA_S)) >= 2
            and _soonest_objective(ctx) is not None)


def _objective_danger_emit(ctx) -> dict:
    tag, eta = _soonest_objective(ctx) or ("dragon", 0.0)
    label = _OBJECTIVE_LABELS.get(tag, tag)
    n = len(ctx.missing_enemies(MIN_MIA_S))
    when = f"in {int(eta)}s" if eta > 0 else "UP now"
    action = _objective_action(ctx.mode)
    return {
        "tag": "macro_objective_danger",
        "line": f"{label} {when} - {n} missing, {action}",
        "eta_s": round(eta, 1),
        "kind": "macro",
    }


def _is_gank_zone(zone: str) -> bool:
    """River / jungle-adjacent last-seen zones (vision_tracker _sr_zone
    vocabulary: *_river, *_jungle, dragon_pit/baron_pit)."""
    z = (zone or "").lower()
    return ("river" in z) or ("jungle" in z) or ("pit" in z)


def _gank_missing(ctx) -> tuple:
    return tuple(e for e in ctx.missing_enemies(GANK_MIN_MIA_S)
                 if _is_gank_zone(e.last_seen_zone))


def _gank_warning_pred(ctx) -> bool:
    return ctx.phase == _LANING_PHASE and len(_gank_missing(ctx)) >= 2


def _gank_warning_emit(ctx) -> dict:
    n = len(_gank_missing(ctx))
    return {
        "tag": "macro_gank_warning",
        "line": f"{n} missing near river/jungle - care ganks, hug tower",
        "eta_s": None,
        "kind": "macro",
    }


_OBJECTIVE_DANGER_RULE = MacroRule(
    name="objective_danger",
    predicate=_objective_danger_pred,
    emit=_objective_danger_emit,
)
_GANK_WARNING_RULE = MacroRule(
    name="gank_warning",
    predicate=_gank_warning_pred,
    emit=_gank_warning_emit,
)

# Ordered, per-mode. ARAM/ARENA are EMPTY-but-present (shared vision / no
# fog); adding a mode-specific rule later is purely additive. NO mode ever
# falls back to another mode's rules.
MACRO_RULE_REGISTRY: dict = {
    "sr": (_OBJECTIVE_DANGER_RULE, _GANK_WARNING_RULE),
    "aram": (),
    "arena": (),
}

# Mode-spelling map into the registry keyspace. Mirrors the dashboard
# resolver's _MODE_KEY_TO_LOWER (sr/client/game -> sr) plus the raw Riot
# strings core.mode_capabilities normalizes (CLASSIC/KIWI/CHERRY).
_MODE_SPELLINGS: dict = {
    "sr": "sr", "classic": "sr", "client": "sr", "game": "sr",
    "aram": "aram", "kiwi": "aram",
    "arena": "arena", "cherry": "arena",
}


def rules_for(mode: object) -> tuple:
    """The ordered rule tuple for ``mode``; () for empty/unknown modes
    (fail-CLOSED, no SR fallback). Never raises."""
    try:
        if not isinstance(mode, str):
            return ()
        key = _MODE_SPELLINGS.get(mode.strip().lower())
        if key is None:
            return ()
        rules = MACRO_RULE_REGISTRY.get(key)
        return rules if isinstance(rules, tuple) else ()
    except Exception:  # noqa: BLE001 - fail-soft contract
        return ()


def evaluate(ctx, *, zoi: object = None,
             districts: object = None) -> Optional[dict]:
    """Walk the mode's ordered rules first-match-wins; return at most ONE
    ``{tag, line, eta_s, kind="macro"}`` callout, else None.

    ``zoi`` / ``districts`` are the documented district-enrichment seam
    for v1 - accepted and IGNORED in fog-only v0. NEVER raises: garbage
    context, unknown mode, or a raising rule -> None (a broken rule is
    skipped, the rest of the registry still runs).
    """
    del zoi, districts  # v0 is fog-only; kwargs are the v1 seam.
    try:
        mode = getattr(ctx, "mode", None)
        for rule in rules_for(mode):
            try:
                if rule.predicate(ctx):
                    out = rule.emit(ctx)
                    return out if isinstance(out, dict) else None
            except Exception:  # noqa: BLE001 - skip the broken rule
                continue
        return None
    except Exception:  # noqa: BLE001 - fail-soft contract, never raise
        return None
