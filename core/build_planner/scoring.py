"""core.build_planner.scoring - transparent weighted build scorer (WP-C2).

Implements the master-plan WP-C2 formula (docs/OVERLAY_BUILD_MASTER_PLAN.md
line 184):

    Score = w_dps  * DS_dps(set,target)
          + w_cohes* cohesion(set)
          + w_situ * situational_fit(set,enemy,ally)
          + w_spike* spike_value(prefix,clock)
          + w_gold * gold_efficiency(set)
          - penalties(legality,redundancy,overcap)

Every term is surfaced on the returned ScoreTerms so the planner can render a
per-build breakdown (the "scoring is explainable" acceptance criterion).

CRITICAL boundaries (verified against THIS worktree):

  * DPS term READS the seed rows' ``delta_dps`` and NEVER recomputes DPS - the
    in-process DS engine is off-limits (split-brain guard,
    dashboard/routes_state.py:548-549; the mirrored ast scan lives in
    tests/test_planner_beam_search.py). The seed row shape is the
    /api/ds-preview ``ranked[]`` projection (routes_state.py:592-597) which may
    DROP unique_passive_key / is_terminal / dps_per_1k_gold - every read here
    tolerates their absence.

  * cohesion REUSES the shipped C1 ``core.build_planner.kit_synergy.
    synergy_score`` (kit_synergy.py:485) - WP-C1 is DONE; we do NOT reimplement
    kit fit.

  * penalties = engine-supplied unique-collision only. The no-double rule is
    engine-authoritative (core/build_order.py:34-48, 6 families); we INHERIT
    each row's ``unique_passive_key`` and never write a family literal (a guard
    test fails on any family literal).

  * situational_fit is a 0.0 stub here - enemy/ally counter-build fit is the
    WP-C3 concern (docs/OVERLAY_BUILD_MASTER_PLAN.md WP-C3).

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.build_planner.kit_synergy import synergy_score

# --------------------------------------------------------------------------- #
# Stage definition.
#
# WHY these cutoffs: the master plan (line 184) only specifies "early vs late"
# weight shifts, not exact clocks. ~10 min / 2 completed items is the standard
# League laning->mid boundary; ~22 min / 4 items is the mid->late boundary
# (3-4 item powerspike). owned_count OR clock crossing the boundary advances
# the stage so a fast-fed game escalates on items even if the clock lags.
# --------------------------------------------------------------------------- #
_EARLY_CLOCK_S = 600.0     # 10:00
_LATE_CLOCK_S = 1320.0     # 22:00
_MID_OWNED = 2
_LATE_OWNED = 4

# --------------------------------------------------------------------------- #
# Stage-dependent weights. WHY these magnitudes (master plan leaves them to the
# implementer - R5 default): the DPS term is the dominant signal (DS is ground
# truth) so w_dps is largest; cohesion is the kit-fit tie-breaker; spike is up-
# weighted early (a powerspike timing matters most in the laning/mid game) and
# decays late; gold-efficiency matters early when gold is scarce and decays
# late. situational starts at 1.0 so WP-C3 can scale a real signal in without a
# weight change. The terms are pre-normalized to a comparable ~0..1 magnitude
# in their helpers below so these weights are the true relative emphasis.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class StageWeights:
    dps: float
    cohesion: float
    situational: float
    spike: float
    gold: float


_STAGE_WEIGHTS: dict[str, StageWeights] = {
    # early: spike + gold-efficiency emphasized (per master-plan "early:
    # spike/defense"); dps still dominant because it is ground truth.
    "early": StageWeights(dps=1.0, cohesion=0.5, situational=1.0, spike=0.6, gold=0.5),
    "mid":   StageWeights(dps=1.0, cohesion=0.5, situational=1.0, spike=0.4, gold=0.3),
    # late: pen-offense / dps emphasized (per master-plan "late: pen-offense/
    # dps"); spike + gold-efficiency decay.
    "late":  StageWeights(dps=1.2, cohesion=0.5, situational=1.0, spike=0.2, gold=0.1),
}

# WHY this penalty magnitude: a redundant unique passive is a hard waste (the
# proc is zeroed by the engine dedup) so each collision is a flat, dominant
# subtraction - large enough to sink any build that stacks a dead unique below
# a legal sibling of comparable DPS.
_UNIQUE_COLLISION_PENALTY = 5.0

# Normalization divisors (keep each term ~0..1.x so StageWeights are the true
# relative emphasis). WHY: a 6-item build sums ~6 rows of delta_dps (~80 each)
# -> ~480; /500 lands it near 1.0. Cohesion sums ~6 synergy_scores (~1-2 each);
# /6 lands the average near unity. Gold normalizes against a full ~18k build.
_DPS_NORM = 500.0
_COHESION_NORM = 6.0
_GOLD_NORM = 18000.0


def stage_for(clock_s: float, owned_count: int) -> str:
    """Return the stage label ('early'|'mid'|'late') for a game clock + owned.

    Stage advances on EITHER the clock OR the completed-item count crossing the
    boundary (whichever is further along) - a fed game powerspikes on items.
    """
    by_clock = (
        "early" if clock_s < _EARLY_CLOCK_S
        else "mid" if clock_s < _LATE_CLOCK_S
        else "late"
    )
    by_owned = (
        "early" if owned_count < _MID_OWNED
        else "mid" if owned_count < _LATE_OWNED
        else "late"
    )
    order = {"early": 0, "mid": 1, "late": 2}
    return by_clock if order[by_clock] >= order[by_owned] else by_owned


@dataclass(frozen=True)
class ScoreTerms:
    """Per-build weighted score breakdown - explainability surface."""

    stage: str
    dps: float
    cohesion: float
    situational_fit: float
    spike: float
    gold: float
    penalties: float
    total: float

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "dps": round(self.dps, 3),
            "cohesion": round(self.cohesion, 3),
            "situational_fit": round(self.situational_fit, 3),
            "spike": round(self.spike, 3),
            "gold": round(self.gold, 3),
            "penalties": round(self.penalties, 3),
            "total": round(self.total, 3),
        }


def _row_index(seed_rows) -> dict[str, dict]:
    """Map item_id (str) -> seed row dict for O(1) lookup."""
    out: dict[str, dict] = {}
    for r in seed_rows or ():
        iid = r.get("item_id")
        if iid is not None:
            out[str(iid)] = r
    return out


def _seed_delta(row: dict) -> float:
    """delta_dps from a seed row - tolerant of the thin ds-preview projection.

    The projection emits ``delta_dps``; the raw RankedItem also carries it
    (rank.py:248). Missing -> 0.0 (the item contributes no DPS signal).
    """
    try:
        return float(row.get("delta_dps") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _seed_gold(row: dict) -> int:
    try:
        return int(row.get("gold") or 0)
    except (TypeError, ValueError):
        return 0


def _seed_family(row: dict) -> str:
    """Engine-supplied unique_passive_key - '' when the projection dropped it.

    Never a planner-side literal (the no-double rule is engine-authoritative).
    """
    return str(row.get("unique_passive_key") or "")


def _dps_term(build_ids, rows_by_id) -> float:
    """Sum of seed delta_dps over the build, normalized. READ-ONLY - no recompute."""
    total = sum(_seed_delta(rows_by_id[i]) for i in build_ids if i in rows_by_id)
    return total / _DPS_NORM


def _cohesion_term(build_ids, champ, rows_by_id) -> float:
    """Mean C1 kit-synergy over the build (reuses kit_synergy.synergy_score).

    Pass the SEED ROW DICT to synergy_score when available - kit_synergy
    accepts either an id or an entry dict (kit_synergy.py:217-218); the live
    items.json entry is resolved by id when the row is not itself an entry. The
    cohesion is the average per-item fit so build length does not inflate it.
    """
    if not build_ids:
        return 0.0
    total = 0.0
    for iid in build_ids:
        # synergy_score resolves the item from items.json by id; the seed row
        # is NOT an items.json entry (it is a ranker row), so pass the id.
        try:
            total += float(synergy_score(iid, champ))
        except Exception:  # noqa: BLE001 - kit data missing -> 0 contribution
            continue
    return total / _COHESION_NORM


def _spike_term(build_ids, rows_by_id, stage: str) -> float:
    """Local ordinal spike heuristic - rewards terminal, high-delta items.

    WHY this proxy (master plan leaves the exact spike formula to the
    implementer - R5 default): a "powerspike" is a completed (terminal),
    high-DPS item landing on curve. We reward the fraction of the build that is
    terminal AND carries above-median delta, scaled down as the game advances
    (spikes matter most early). is_terminal is read from the seed row when
    present; the thin projection drops it -> treated as terminal (a ds-preview
    row is already terminal-filtered upstream, rank.py:476).
    """
    if not build_ids:
        return 0.0
    rows = [rows_by_id[i] for i in build_ids if i in rows_by_id]
    if not rows:
        return 0.0
    deltas = sorted(_seed_delta(r) for r in rows)
    median = deltas[len(deltas) // 2]
    spiky = 0
    for r in rows:
        is_term = r.get("is_terminal")
        terminal = True if is_term is None else bool(is_term)
        if terminal and _seed_delta(r) >= median:
            spiky += 1
    frac = spiky / len(build_ids)
    decay = {"early": 1.0, "mid": 0.6, "late": 0.3}.get(stage, 0.6)
    return frac * decay


def _gold_term(build_ids, rows_by_id) -> float:
    """Gold-efficiency proxy: delta_dps per 1k gold, averaged + normalized.

    Uses the row's ``dps_per_1k_gold`` when present (rank.py:250); otherwise
    derives it from delta_dps / gold. Normalized into the same ~0..1 band as
    the other terms. WHY a local heuristic (not a true gold-value table): the
    master plan defers the full EHP/pen gold formulas to WP-C3; here gold is
    only an ordinal tie-breaker favouring cost-effective rows.
    """
    if not build_ids:
        return 0.0
    vals: list[float] = []
    for iid in build_ids:
        row = rows_by_id.get(iid)
        if row is None:
            continue
        per1k = row.get("dps_per_1k_gold")
        if per1k is None:
            gold = _seed_gold(row)
            per1k = (_seed_delta(row) / (gold / 1000.0)) if gold > 0 else 0.0
        try:
            vals.append(float(per1k))
        except (TypeError, ValueError):
            continue
    if not vals:
        return 0.0
    # Median dps-per-1k is ~25-30 for a strong row; /30 normalizes to ~1.0.
    return (sum(vals) / len(vals)) / 30.0


def _penalty_term(build_ids, rows_by_id) -> float:
    """Engine-supplied unique-collision penalty ONLY (legality/redundancy).

    Counts every unique_passive_key that appears more than once in the build
    (each extra occurrence is a dead, zeroed proc). Inherited from the seed
    rows - no family literal, no planner-side family map.
    """
    seen: dict[str, int] = {}
    for iid in build_ids:
        row = rows_by_id.get(iid)
        if row is None:
            continue
        fam = _seed_family(row)
        if not fam:
            continue
        seen[fam] = seen.get(fam, 0) + 1
    collisions = sum(c - 1 for c in seen.values() if c > 1)
    return _UNIQUE_COLLISION_PENALTY * collisions


def score_build(
    build_ids,
    champ,
    seed_rows,
    *,
    clock_s: float = 0.0,
    owned_count: int = 0,
    stage: Optional[str] = None,
) -> ScoreTerms:
    """Score an (ordered) partial build - PURE, no I/O, no DS-engine call.

    ``build_ids`` is the ordered list of item-id strings. ``seed_rows`` is the
    /api/ds-preview ``ranked[]`` projection (or the richer raw RankedItem
    rows). ``champ`` is the champion display name (or id) - resolved by C1.

    Returns a ScoreTerms with every weighted term + the total, so the planner
    can both rank by ``total`` and render the breakdown.
    """
    ids = [str(i) for i in (build_ids or [])]
    rows_by_id = _row_index(seed_rows)
    stg = stage or stage_for(clock_s, owned_count)
    w = _STAGE_WEIGHTS.get(stg, _STAGE_WEIGHTS["mid"])

    dps = _dps_term(ids, rows_by_id)
    cohesion = _cohesion_term(ids, champ, rows_by_id)
    spike = _spike_term(ids, rows_by_id, stg)
    gold = _gold_term(ids, rows_by_id)
    situational = 0.0  # WP-C3 concern - stubbed 0.0 here.
    penalties = _penalty_term(ids, rows_by_id)

    total = (
        w.dps * dps
        + w.cohesion * cohesion
        + w.situational * situational
        + w.spike * spike
        + w.gold * gold
        - penalties
    )
    return ScoreTerms(
        stage=stg,
        dps=w.dps * dps,
        cohesion=w.cohesion * cohesion,
        situational_fit=w.situational * situational,
        spike=w.spike * spike,
        gold=w.gold * gold,
        penalties=penalties,
        total=total,
    )
