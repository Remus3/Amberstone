# arch: 1-variable DPS stat-sweep (target_armor / target_mr / level) | section=daemon_slayer | frozen=no
"""DPS stat-sweep - loop ``compute_dps`` over ONE swept variable.

Competitor lift #3 (calc.gg stat-sweep graphs; DEPTH spec
``docs/COMPETITOR_LIFT_2026-05-30.md`` "Lift 3"). Pure presentation over the
EXISTING DS auto-attack DPS engine - NO new compute, NO ENGINE math change,
NO schema lift, NO new external dependency. This module is a thin loop that
re-calls ``agents.daemon_slayer.dps.compute_dps`` (or delegates to its
sibling ``compute_dps_curve`` for the level axis) with ONE input varied and
everything else held fixed, then collects ``(x, weighted_dps, phase)`` points
to chart.

The sweep primitive already exists in one axis: ``compute_dps_curve``
(``dps.py``) sweeps LEVEL and returns ``DpsCurvePoint[]``. This module mirrors
that pattern for the target_armor / target_mr axes (level held fixed) and
delegates the level axis straight to ``compute_dps_curve`` so the two surfaces
agree by construction.

Axes (v1):
  * ``target_armor`` - vary target armor, hold level fixed (default 11).
    The DPS curve is monotonic NON-increasing in armor (more armor = same or
    less physical DPS); the breakpoint where anti-armor (LDR / Black Cleaver)
    overtakes raw damage is the actionable read.
  * ``target_mr``    - vary target magic resist, hold level fixed. Monotonic
    non-increasing for any champ with a magic-damage component; flat for a
    pure-physical auto-attacker (MR does not touch physical hits).
  * ``level``        - delegate to ``compute_dps_curve`` (the existing
    level-swept curve). target_armor / target_mr held at the call's fixed
    values across all levels.

Honesty contract:
  * The Y value is exactly the number ``compute_dps`` returns - the same
    ``weighted_dps`` the rest of RC surfaces. No re-derivation, no smoothing.
  * For the armor / mr axes the level is FIXED (default 11 = the credible
    mid-game body); only the swept target resist varies. So the curve answers
    "at level N, how does my DPS scale vs their armor/MR" - the calc.gg
    single-axis read.
  * Fail-soft on an unknown champion / degenerate build: ``compute_dps``
    raises a KeyError when the champion is absent from the snapshot; this
    module catches it and returns an EMPTY points list (the route degrades to
    ok=false reason=no_points rather than 503).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from .data_loader import DataSnapshot
from .dps import compute_dps, compute_dps_curve

# Default fixed level for the resist-axis sweeps. Level 11 = the credible
# mid-game body (post-second-item, ult unlocked) - the same anchor
# routes_spike_curve uses for its mid-game enemy profile. The level axis
# ignores this (it sweeps level itself).
DEFAULT_SWEEP_LEVEL = 11

# Canonical axis names. ``target_armor`` / ``target_mr`` sweep the named
# target resist with level fixed; ``level`` delegates to compute_dps_curve.
AXIS_TARGET_ARMOR = "target_armor"
AXIS_TARGET_MR = "target_mr"
AXIS_LEVEL = "level"
SWEEP_AXES: tuple[str, ...] = (AXIS_TARGET_ARMOR, AXIS_TARGET_MR, AXIS_LEVEL)


@dataclass(frozen=True)
class SweepPoint:
    """One (x, y) sample on a stat-sweep curve.

    ``x`` is the swept variable's value at this sample (target armor / MR for
    the resist axes; level for the level axis). ``weighted_dps`` is the same
    number ``compute_dps`` returns at that sample; ``phase`` is the
    auto-selected rotation phase the engine used.
    """

    x: float
    weighted_dps: float
    phase: str

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "weighted_dps": self.weighted_dps,
            "phase": self.phase,
        }


@dataclass(frozen=True)
class SweepResult:
    """A 1-variable DPS stat-sweep curve for one champion + build.

    ``points`` is in input order (ascending swept value for the standard
    callers). ``axis`` echoes the swept variable name. ``empty`` is True when
    no points resolved (unknown champion / degenerate build) so a consumer can
    branch without inspecting the list length.
    """

    champion_id: str
    axis: str
    level: int
    points: tuple[SweepPoint, ...] = field(default_factory=tuple)

    @property
    def empty(self) -> bool:
        return not self.points

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "axis": self.axis,
            "level": self.level,
            "points": [p.to_dict() for p in self.points],
        }


def _one_dps(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids,
    mode: str,
    target_armor: float,
    target_mr: float,
    target_max_hp: float,
    target_bonus_hp: float,
):
    """Single ``compute_dps`` call. Returns the DpsResult or None on any
    engine-internal failure for this one sample (one bad point should not
    sink the whole curve)."""
    try:
        return compute_dps(
            snapshot,
            champion_id,
            level=level,
            item_ids=item_ids,
            mode=mode,
            target_armor=target_armor,
            target_mr=target_mr,
            target_max_hp=target_max_hp,
            target_bonus_hp=target_bonus_hp,
        )
    except KeyError:
        # Unknown champion - the caller-facing fail-soft. Re-raised so
        # compute_dps_sweep can short-circuit to an empty result rather than
        # emit a curve of None-holes.
        raise
    except Exception:
        return None


def compute_dps_sweep(
    snapshot: DataSnapshot,
    champion_id: str,
    item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    axis: str = AXIS_TARGET_ARMOR,
    axis_values: Optional[Iterable[float]] = None,
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    level: int = DEFAULT_SWEEP_LEVEL,
) -> SweepResult:
    """Return a 1-variable DPS stat-sweep curve for ``champion_id``.

    Loops ``compute_dps`` over the values in ``axis_values``, varying the one
    input named by ``axis`` and holding everything else fixed. For
    ``target_armor`` / ``target_mr`` the level is held at ``level``; the named
    target resist is overwritten by each ``axis_values`` entry (so the
    ``target_armor`` / ``target_mr`` keyword for the swept axis is the sweep
    floor and is replaced per-sample). For the ``level`` axis the call
    delegates to :func:`compute_dps_curve` with the same fixed build + target
    resists, so the level-axis output agrees with the existing level curve by
    construction.

    ``axis`` not in :data:`SWEEP_AXES` raises ``ValueError`` (caller 400s).
    An unknown ``champion_id`` (absent from the snapshot) fail-softs to an
    EMPTY :class:`SweepResult` - the standard "no data" degenerate that the
    route maps to ok=false reason=no_points.

    ``axis_values`` defaults are per-axis sensible ranges when None:
      * target_armor / target_mr -> 0, 25, 50, ... , 300 (13 samples)
      * level                    -> :data:`agents.daemon_slayer.dps.DPS_CURVE_LEVELS`
    """
    if axis not in SWEEP_AXES:
        raise ValueError(f"axis must be one of {SWEEP_AXES}, got {axis!r}")

    items = tuple(item_ids) if item_ids is not None else ()

    # ----- level axis: delegate to the existing level-swept curve. -----
    if axis == AXIS_LEVEL:
        levels = (
            tuple(int(v) for v in axis_values)
            if axis_values is not None
            else None
        )
        try:
            curve = compute_dps_curve(
                snapshot,
                champion_id,
                item_ids=items,
                mode=mode,
                target_armor=target_armor,
                target_mr=target_mr,
                target_max_hp=target_max_hp,
                target_bonus_hp=target_bonus_hp,
                levels=levels,
            )
        except KeyError:
            return SweepResult(champion_id=champion_id, axis=axis, level=level)
        pts = tuple(
            SweepPoint(
                x=float(p.level),
                weighted_dps=float(p.weighted_dps),
                phase=p.phase,
            )
            for p in curve
        )
        return SweepResult(
            champion_id=champion_id, axis=axis, level=level, points=pts
        )

    # ----- resist axes: hold level fixed, sweep the named target resist. -----
    if axis_values is not None:
        values = [float(v) for v in axis_values]
    else:
        values = [float(a) for a in range(0, 301, 25)]

    pts_list: List[SweepPoint] = []
    for v in values:
        a = v if axis == AXIS_TARGET_ARMOR else target_armor
        m = v if axis == AXIS_TARGET_MR else target_mr
        try:
            r = _one_dps(
                snapshot,
                champion_id,
                level,
                items,
                mode,
                a,
                m,
                target_max_hp,
                target_bonus_hp,
            )
        except KeyError:
            # Unknown champion - bail to empty result (no partial curve).
            return SweepResult(champion_id=champion_id, axis=axis, level=level)
        if r is None:
            continue
        pts_list.append(
            SweepPoint(
                x=v,
                weighted_dps=float(r.weighted_dps),
                phase=r.phase,
            )
        )

    return SweepResult(
        champion_id=champion_id,
        axis=axis,
        level=level,
        points=tuple(pts_list),
    )


__all__ = [
    "SweepPoint",
    "SweepResult",
    "compute_dps_sweep",
    "DEFAULT_SWEEP_LEVEL",
    "SWEEP_AXES",
    "AXIS_TARGET_ARMOR",
    "AXIS_TARGET_MR",
    "AXIS_LEVEL",
]
