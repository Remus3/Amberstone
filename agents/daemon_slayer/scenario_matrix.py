# arch: cross-interaction scenario sweep + invariant checker (harnesses existing scorers) | section=daemon_slayer | frozen=no
"""Cross-interaction scenario matrix - sweep an EXISTING scorer across a
grid of (champion x level x item_set x target_profile x mode) and assert
mathematical invariants hold across the WHOLE matrix.

This is the DS V2 "validating multiple & expansive scenarios of fights and
combinations" deliverable. It is a HARNESS, not a new scorer: every cell's
``value`` comes from one of three existing engine functions -

  * ``metric="dps"``   -> ``dps.compute_dps(...).weighted_dps``
  * ``metric="burst"`` -> ``burst.compute_burst_damage(...).total_burst_damage``
  * ``metric="combo"`` -> ``combo.compute_combo(...).total_mitigated``

No DPS / burst / mitigation math is duplicated or moved here. The module
adds the cross-product enumeration + an invariant checker over the
resulting cells.

Why a damage-type hint matters for the resistance invariants
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``compute_dps`` scores AUTO-ATTACK DPS, which is PHYSICAL for almost every
champion regardless of their kit's damage type - so a pure-AP mage's
``compute_dps`` value is only weakly MR-sensitive (on-hit procs), NOT a
clean MR-monotone curve. The clean MR-monotone signal for an AP champion
lives in ``compute_burst_damage`` (ability damage, MR-gated). Therefore:

  * Invariant (1) "physical dps non-increasing in target_armor" is asserted
    ONLY for cells the caller flags pure-AD (``ad_champions``) AND whose
    metric is armor-sensitive (``dps`` AA-DPS or ``burst`` AD ability dmg).
  * Invariant (2) "magic dmg non-increasing in target_mr" is asserted ONLY
    for cells the caller flags pure-AP (``ap_champions``) AND whose metric
    is MR-sensitive. For AP champs that is ``burst`` (ability dmg) - the
    test supplies the pure-AD/pure-AP set + the metric it measured them on.

The GENERIC invariants apply to EVERY cell regardless of damage type:

  * (3) value non-decreasing as level rises (fixed build + target + mode).
  * (4) no NaN, no negative value.
  * (5) mode-multiplier consistency: same champ+build+target+level+metric,
    ARAM vs SR differ only by a positive scalar (never a sign flip /
    NaN-vs-finite mismatch).

Fail-soft contract: a scorer raising on one cell records ``value=nan`` +
a note rather than aborting the sweep. ``check_invariants`` treats NaN as
an invariant-4 violation but does NOT use a NaN cell to fail the ordering
invariants (1/2/3) - a missing data point cannot prove a monotonicity
break.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .data_loader import DataSnapshot

# Metrics this harness can dispatch. Each maps to one existing scorer.
VALID_METRICS: Tuple[str, ...] = ("dps", "burst", "combo")

# Default combo sequence for metric="combo" cells (Q-AA-W-R). Short, fixed;
# the combo scorer is itself the authority on per-cast timing.
_DEFAULT_COMBO_SEQUENCE: Tuple[str, ...] = ("Q", "AA", "W", "R")

# Floating-point slack for the "non-increasing" / "non-decreasing" tests.
# Engine values are O(10-1000); 1e-6 absorbs round-trip float noise without
# masking a real reversal.
_MONO_EPS: float = 1e-6


@dataclass(frozen=True)
class ScenarioCell:
    """One evaluated point on the sweep matrix.

    ``value`` is the scorer output for ``metric`` (weighted_dps /
    total_burst_damage / total_mitigated). ``value`` is ``float('nan')``
    when the underlying scorer raised for this cell (fail-soft). ``note``
    carries the failure reason (empty on success).
    """

    champion: str
    level: int
    item_ids: Tuple[str, ...]
    target_armor: float
    target_mr: float
    mode: str
    metric: str
    value: float
    note: str = ""


@dataclass(frozen=True)
class InvariantViolation:
    """One detected breach of a cross-matrix invariant.

    ``invariant`` is the stable name (e.g. ``"dps_non_increasing_in_armor"``).
    ``detail`` is a human-readable description. ``cells`` are the offending
    cells (usually the adjacent pair whose ordering broke, or the single
    cell carrying a NaN / negative value).
    """

    invariant: str
    detail: str
    cells: Tuple[ScenarioCell, ...]


def _coerce_item_set(item_set: Sequence[str | int]) -> Tuple[str, ...]:
    """Normalize one item-id tuple to a tuple of str ids."""
    return tuple(str(i) for i in (item_set or ()))


def _coerce_profile(
    profile: Sequence[float],
) -> Tuple[float, float, float, float]:
    """Unpack a target profile (armor, mr[, max_hp, bonus_hp]) -> 4-tuple.

    Missing trailing entries default to 0.0 so a 2-tuple ``(armor, mr)``
    works as well as a 4-tuple. Extra entries past index 3 are ignored.
    """
    vals = list(profile or ())
    armor = float(vals[0]) if len(vals) > 0 else 0.0
    mr = float(vals[1]) if len(vals) > 1 else 0.0
    max_hp = float(vals[2]) if len(vals) > 2 else 0.0
    bonus_hp = float(vals[3]) if len(vals) > 3 else 0.0
    return (armor, mr, max_hp, bonus_hp)


def _score_cell(
    snapshot: DataSnapshot,
    champion: str,
    level: int,
    item_ids: Tuple[str, ...],
    armor: float,
    mr: float,
    max_hp: float,
    bonus_hp: float,
    mode: str,
    metric: str,
) -> Tuple[float, str]:
    """Dispatch one cell to the matching EXISTING scorer; fail-soft.

    Returns ``(value, note)``. On any scorer exception the value is
    ``float('nan')`` and the note carries a truncated reason; the sweep
    never aborts on a single bad cell.
    """
    try:
        if metric == "dps":
            from .dps import compute_dps  # noqa: PLC0415 - local keeps import graph thin
            r = compute_dps(
                snapshot, champion, int(level), item_ids=list(item_ids),
                mode=mode, target_armor=armor, target_mr=mr,
                target_max_hp=max_hp, target_bonus_hp=bonus_hp,
            )
            return (float(r.weighted_dps), "")
        if metric == "burst":
            from .burst import compute_burst_damage  # noqa: PLC0415
            r = compute_burst_damage(
                snapshot, champion, int(level), item_ids=list(item_ids),
                mode=mode, target_armor=armor, target_mr=mr,
                target_max_hp=max_hp, target_bonus_hp=bonus_hp,
            )
            return (float(r.total_burst_damage), "")
        if metric == "combo":
            from .combo import compute_combo  # noqa: PLC0415
            r = compute_combo(
                champion, int(level), item_ids=list(item_ids),
                sequence=list(_DEFAULT_COMBO_SEQUENCE),
                target_armor=armor, target_mr=mr, target_max_hp=max_hp,
                target_bonus_hp=bonus_hp, mode=mode, snapshot=snapshot,
            )
            return (float(r.total_mitigated), "")
        return (float("nan"), f"unknown metric {metric!r}")
    except Exception as exc:  # fail-soft: record NaN + reason, never raise
        return (float("nan"), f"scorer raised: {type(exc).__name__}: {str(exc)[:120]}")


def sweep_scenarios(
    champion: str,
    levels: Sequence[int],
    item_sets: Sequence[Sequence[str | int]],
    target_profiles: Sequence[Sequence[float]],
    modes: Sequence[str] = ("SR",),
    metric: str = "dps",
    snapshot: Optional[DataSnapshot] = None,
) -> List[ScenarioCell]:
    """Evaluate ``metric`` for ``champion`` over the full cross-product.

    The matrix is ``levels x item_sets x target_profiles x modes``. Each
    cell dispatches to the matching EXISTING scorer (``compute_dps`` /
    ``compute_burst_damage`` / ``compute_combo``). ``target_profiles`` are
    ``(armor, mr[, max_hp, bonus_hp])`` tuples (2- or 4-wide). ``item_sets``
    are item-id tuples (str or int ids).

    Fail-soft: a scorer raising on one cell yields a ``ScenarioCell`` with
    ``value=float('nan')`` + a note; the sweep continues. The returned list
    length is exactly ``len(levels) * len(item_sets) * len(target_profiles)
    * len(modes)`` - every cell is present even if its scorer failed.

    Cell order is deterministic: levels outer, then item_sets, then
    target_profiles, then modes innermost.
    """
    if metric not in VALID_METRICS:
        raise ValueError(
            f"metric must be one of {VALID_METRICS}, got {metric!r}"
        )
    snap = snapshot if snapshot is not None else DataSnapshot.load()
    champ = str(champion or "").strip()

    norm_item_sets = [_coerce_item_set(s) for s in (item_sets or [])]
    norm_profiles = [_coerce_profile(p) for p in (target_profiles or [])]
    norm_modes = [str(m) for m in (modes or ())]
    norm_levels = [int(lv) for lv in (levels or [])]

    cells: List[ScenarioCell] = []
    for lv in norm_levels:
        for item_ids in norm_item_sets:
            for (armor, mr, max_hp, bonus_hp) in norm_profiles:
                for mode in norm_modes:
                    value, note = _score_cell(
                        snap, champ, lv, item_ids, armor, mr, max_hp,
                        bonus_hp, mode, metric,
                    )
                    cells.append(ScenarioCell(
                        champion=champ,
                        level=lv,
                        item_ids=item_ids,
                        target_armor=armor,
                        target_mr=mr,
                        mode=mode,
                        metric=metric,
                        value=value,
                        note=note,
                    ))
    return cells


def _is_nan(x: float) -> bool:
    return isinstance(x, float) and math.isnan(x)


def _fixed_key(c: ScenarioCell) -> Tuple:
    """Key holding everything fixed EXCEPT target_armor (for invariant 1)."""
    return (c.champion, c.level, c.item_ids, c.target_mr, c.mode, c.metric)


def _fixed_key_mr(c: ScenarioCell) -> Tuple:
    """Key holding everything fixed EXCEPT target_mr (for invariant 2)."""
    return (c.champion, c.level, c.item_ids, c.target_armor, c.mode, c.metric)


def _fixed_key_level(c: ScenarioCell) -> Tuple:
    """Key holding everything fixed EXCEPT level (for invariant 3)."""
    return (c.champion, c.item_ids, c.target_armor, c.target_mr, c.mode, c.metric)


def _fixed_key_mode(c: ScenarioCell) -> Tuple:
    """Key holding everything fixed EXCEPT mode (for invariant 5)."""
    return (c.champion, c.level, c.item_ids, c.target_armor, c.target_mr, c.metric)


def _check_monotone(
    cells: List[ScenarioCell],
    key_fn,
    axis_attr: str,
    direction: str,
    invariant_name: str,
    restrict: Optional[set],
) -> List[InvariantViolation]:
    """Generic per-group monotonicity check along one swept axis.

    Groups ``cells`` by ``key_fn`` (everything fixed except the swept
    axis), sorts each group by ``axis_attr``, and asserts the value is
    ``direction`` (``"non_increasing"`` / ``"non_decreasing"``) across
    adjacent finite pairs. ``restrict`` (when not None) limits the check to
    cells whose champion is in the set - used to scope the resistance
    invariants to the test-supplied pure-AD / pure-AP champions. NaN cells
    are skipped (a missing point cannot prove an ordering break).
    """
    groups: Dict[Tuple, List[ScenarioCell]] = {}
    for c in cells:
        if restrict is not None and c.champion not in restrict:
            continue
        if _is_nan(c.value):
            continue
        groups.setdefault(key_fn(c), []).append(c)

    violations: List[InvariantViolation] = []
    for _, members in groups.items():
        ordered = sorted(members, key=lambda c: getattr(c, axis_attr))
        for prev, cur in zip(ordered, ordered[1:]):
            if direction == "non_increasing":
                broke = cur.value > prev.value + _MONO_EPS
            else:  # non_decreasing
                broke = cur.value < prev.value - _MONO_EPS
            if broke:
                violations.append(InvariantViolation(
                    invariant=invariant_name,
                    detail=(
                        f"{axis_attr} {getattr(prev, axis_attr)} -> "
                        f"{getattr(cur, axis_attr)}: value "
                        f"{prev.value:.4f} -> {cur.value:.4f} "
                        f"(expected {direction.replace('_', '-')})"
                    ),
                    cells=(prev, cur),
                ))
    return violations


def check_invariants(
    cells: Sequence[ScenarioCell],
    ad_champions: Optional[Sequence[str]] = None,
    ap_champions: Optional[Sequence[str]] = None,
) -> List[InvariantViolation]:
    """Assert the cross-matrix invariants; return every violation found.

    Invariants:
      1. ``dps_non_increasing_in_armor`` - for cells whose champion is in
         ``ad_champions`` (pure-AD), value is non-increasing as
         ``target_armor`` rises (everything else fixed). Scoped because
         only AD damage is cleanly armor-monotone.
      2. ``magic_non_increasing_in_mr`` - for cells whose champion is in
         ``ap_champions`` (pure-AP), value is non-increasing as
         ``target_mr`` rises (everything else fixed). Scoped because only
         magic damage (ability/burst) is cleanly MR-monotone.
      3. ``value_non_decreasing_in_level`` - for EVERY cell group, value is
         non-decreasing as level rises (fixed build + target + mode +
         metric). Applies to all champions.
      4. ``no_nan`` / ``no_negative`` - EVERY cell must carry a finite,
         non-negative value. A NaN cell (fail-soft scorer error) is a
         violation; so is a negative value.
      5. ``mode_multiplier_consistency`` - for a fixed
         champ+level+build+target+metric group with >1 mode, all finite
         values must share the same sign (no positive-vs-negative flip) and
         no finite-vs-NaN split. (The exact ARAM scalar is not pinned here;
         only that the modes do not disagree in kind.)

    NaN cells are skipped for the ordering invariants (1/2/3) - a missing
    data point cannot prove an ordering break - but DO trip invariant 4.
    """
    all_cells = list(cells)
    ad_set = set(ad_champions) if ad_champions is not None else None
    ap_set = set(ap_champions) if ap_champions is not None else None

    violations: List[InvariantViolation] = []

    # Invariant 4: no NaN, no negative. Per-cell.
    for c in all_cells:
        if _is_nan(c.value):
            violations.append(InvariantViolation(
                invariant="no_nan",
                detail=(
                    f"cell {c.champion} L{c.level} armor={c.target_armor} "
                    f"mr={c.target_mr} mode={c.mode} metric={c.metric} is NaN"
                    + (f" ({c.note})" if c.note else "")
                ),
                cells=(c,),
            ))
        elif c.value < 0.0:
            violations.append(InvariantViolation(
                invariant="no_negative",
                detail=(
                    f"cell {c.champion} L{c.level} armor={c.target_armor} "
                    f"mr={c.target_mr} mode={c.mode} metric={c.metric} "
                    f"value {c.value:.4f} < 0"
                ),
                cells=(c,),
            ))

    # Invariant 1: physical (pure-AD) value non-increasing in armor.
    if ad_set:
        violations.extend(_check_monotone(
            all_cells, _fixed_key, "target_armor", "non_increasing",
            "dps_non_increasing_in_armor", ad_set,
        ))

    # Invariant 2: magic (pure-AP) value non-increasing in MR.
    if ap_set:
        violations.extend(_check_monotone(
            all_cells, _fixed_key_mr, "target_mr", "non_increasing",
            "magic_non_increasing_in_mr", ap_set,
        ))

    # Invariant 3: value non-decreasing in level (ALL cells).
    violations.extend(_check_monotone(
        all_cells, _fixed_key_level, "level", "non_decreasing",
        "value_non_decreasing_in_level", None,
    ))

    # Invariant 5: mode-multiplier consistency. Group by everything-but-mode.
    mode_groups: Dict[Tuple, List[ScenarioCell]] = {}
    for c in all_cells:
        mode_groups.setdefault(_fixed_key_mode(c), []).append(c)
    for _, members in mode_groups.items():
        if len({m.mode for m in members}) < 2:
            continue  # single-mode group: nothing to compare
        finite = [m for m in members if not _is_nan(m.value)]
        nan_members = [m for m in members if _is_nan(m.value)]
        # finite-vs-NaN split across modes is an inconsistency.
        if finite and nan_members:
            violations.append(InvariantViolation(
                invariant="mode_multiplier_consistency",
                detail=(
                    "mode split: some modes finite, others NaN for fixed "
                    f"{members[0].champion} L{members[0].level} "
                    f"metric={members[0].metric}"
                ),
                cells=tuple(members),
            ))
            continue
        # sign disagreement (one positive, one negative) is a sign flip.
        signs = {(1 if m.value > 0 else (-1 if m.value < 0 else 0)) for m in finite}
        if 1 in signs and -1 in signs:
            violations.append(InvariantViolation(
                invariant="mode_multiplier_consistency",
                detail=(
                    "mode sign flip across modes for fixed "
                    f"{members[0].champion} L{members[0].level} "
                    f"metric={members[0].metric}"
                ),
                cells=tuple(finite),
            ))

    return violations


__all__ = [
    "ScenarioCell",
    "InvariantViolation",
    "sweep_scenarios",
    "check_invariants",
    "VALID_METRICS",
]
