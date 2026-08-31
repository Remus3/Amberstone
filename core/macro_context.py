# arch: fog-only macro snapshot for the deterministic decision tree | section=core | frozen=no
"""core.macro_context - frozen fog/objective snapshot for the macro tree.

ZOI Wave-2 agent-macro (docs/ZOI_DISTRICT_ORCHESTRATION_PLAN.md, spec D,
fog-only decision-tree v0). ``MacroContext`` is the ONE input shape the
rule registry in ``core.macro_decision_tree`` evaluates: a frozen snapshot
of the enemy fog/MIA state (the ``core.vision_tracker`` per-enemy track
shape - vision_tracker.py:376-388), the SR objective schedule (imported
from ``core.event_callouts`` so the served callout path, the vision-gated
decision detector, and this macro tree can never drift on spawn math),
the lead-projection state, and the game clock/phase.

v0 is FOG-ONLY: NO district/CV dependency. The ``zoi`` kwarg on
``build_macro_context`` is a documented v1 seam - a later wave enriches
the context with district-weight fields from ``zoi.districts``; v0
accepts and IGNORES it so the call-site wiring lands now.

FAIL-SOFT CONTRACT: ``build_macro_context`` never raises on any input
(bad numerics, unknown mode, malformed enemies/events/lead) - it degrades
to defaults, matching the ``core.zoi_influence`` pure-module pattern.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ONE cited source for SR epic spawn timings (core/event_callouts.py:67-70).
# _last_kill_t is the same events-shape reader the served dynamic-ETA path
# uses ({name, killer_team, down_at_s[, dragon_type]} rows from
# dashboard/_liveclient.py) - importing it keeps the respawn anchor math
# identical to the served callouts (same precedent as the private
# _sort_key import in dashboard/_deterministic_coaching.py:50).
from core.event_callouts import (
    SR_BARON_FIRST_S,
    SR_BARON_RESPAWN_S,
    SR_DRAGON_FIRST_S,
    SR_DRAGON_RESPAWN_S,
    _last_kill_t,
)
from core.lead_projection import phase_for

_LEAD_STATES = ("ahead", "even", "behind")


@dataclass(frozen=True)
class EnemyFog:
    """One enemy's fog-of-war track (vision_tracker per-enemy subset)."""

    champion: str = ""
    visible: bool = False
    is_dead: bool = False
    missing_for_s: Optional[float] = None
    last_seen_zone: str = ""


@dataclass(frozen=True)
class MacroContext:
    """Frozen fog + objective + lead snapshot the macro rules read."""

    mode: str = "sr"
    game_time_s: float = 0.0
    phase: str = "early"
    lead_state: str = "even"
    enemies: tuple = field(default_factory=tuple)
    next_dragon_eta_s: Optional[float] = None
    next_baron_eta_s: Optional[float] = None

    def missing_enemies(self, min_missing_s: float = 0.0) -> tuple:
        """Enemies MIA for at least ``min_missing_s``: alive, not visible,
        with a numeric missing-duration. Fail-soft () on bad threshold."""
        try:
            floor = float(min_missing_s)
        except (TypeError, ValueError):
            floor = 0.0
        return tuple(
            e for e in self.enemies
            if not e.is_dead and not e.visible
            and e.missing_for_s is not None and e.missing_for_s >= floor
        )


def _coerce_float(value: object) -> Optional[float]:
    """Numeric -> float, everything else (incl. bool/NaN) -> None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    if f != f:  # NaN
        return None
    return f


def _enemy_fog(entry: object) -> Optional[EnemyFog]:
    """One vision-tracker enemy dict -> EnemyFog, or None when malformed."""
    if not isinstance(entry, dict):
        return None
    return EnemyFog(
        champion=str(entry.get("champion") or ""),
        visible=bool(entry.get("visible")),
        is_dead=bool(entry.get("is_dead")),
        missing_for_s=_coerce_float(entry.get("missing_for_s")),
        last_seen_zone=str(entry.get("last_seen_zone") or ""),
    )


def _fog_enemies(enemies: object) -> tuple:
    """Accept the vision_state ``enemies`` dict-of-dicts OR a list of the
    compact fog dicts; skip malformed entries."""
    if isinstance(enemies, dict):
        rows = list(enemies.values())
    elif isinstance(enemies, (list, tuple)):
        rows = list(enemies)
    else:
        return ()
    out = []
    for row in rows:
        fog = _enemy_fog(row)
        if fog is not None:
            out.append(fog)
    return tuple(out)


def _next_spawn_eta(objective_events: object, game_time_s: float, *,
                    name: str, first_at: float, respawn: float,
                    elemental_only: bool = False) -> Optional[float]:
    """Seconds until the next spawn of ``name`` (same last-kill + respawn
    math as event_callouts._dynamic_epic_callouts / the decision detector).
    Negative = the spawn time is already past. None only on internal error."""
    try:
        last = _last_kill_t(objective_events, name=name,
                            elemental_only=elemental_only)
        base = first_at if last is None else last + respawn
        return base - game_time_s
    except Exception:  # noqa: BLE001 - fail-soft contract
        return None


def build_macro_context(mode: object, game_time_s: object, *,
                        enemies: object = None,
                        objective_events: object = None,
                        lead: object = None,
                        zoi: object = None) -> MacroContext:
    """Assemble the frozen fog-only MacroContext. NEVER raises.

    Args:
        mode: mode spelling ("sr"/"SR"/"CLASSIC"/"aram"/...); coerced str.
        game_time_s: game clock seconds; bad input -> 0.0.
        enemies: vision_state["enemies"] dict OR the compact fog list the
            dashboard resolver stamps (gs["fog_enemies"]).
        objective_events: dashboard/_liveclient objective_events rows
            ({name, killer_team, down_at_s[, dragon_type]}).
        lead: core.lead_projection.project_lead dict ({"state": ...}).
        zoi: v1 district seam - ACCEPTED AND IGNORED in fog-only v0.
    """
    del zoi  # v0 is fog-only; the kwarg is the documented v1 seam.
    try:
        mode_str = mode.strip() if isinstance(mode, str) else ""
        gt = _coerce_float(game_time_s)
        if gt is None or gt < 0.0:
            gt = 0.0
        lead_state = "even"
        if isinstance(lead, dict):
            raw_state = lead.get("state")
            if isinstance(raw_state, str) and raw_state in _LEAD_STATES:
                lead_state = raw_state
        return MacroContext(
            mode=mode_str,
            game_time_s=gt,
            phase=phase_for(gt),
            lead_state=lead_state,
            enemies=_fog_enemies(enemies),
            next_dragon_eta_s=_next_spawn_eta(
                objective_events, gt, name="dragon",
                first_at=SR_DRAGON_FIRST_S, respawn=SR_DRAGON_RESPAWN_S,
                elemental_only=True),
            next_baron_eta_s=_next_spawn_eta(
                objective_events, gt, name="baron",
                first_at=SR_BARON_FIRST_S, respawn=SR_BARON_RESPAWN_S),
        )
    except Exception:  # noqa: BLE001 - fail-soft contract, never raise
        return MacroContext()
