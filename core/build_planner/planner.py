"""core.build_planner.planner - candidate gen + beam search (WP-C2).

The core adaptive-build planner: staged candidate generation, beam search over
ordered partial builds, and a transparent per-build score (scoring.py). This is
the planner ABOVE Daemon Slayer - DS answers "which set maxes DPS"; this answers
"best coherent, ordered PLAN given kit + clock + owned".

Mirrors the beam STRUCTURE of agents/daemon_slayer/beam.py (state = ordered
partial build, transition = append a candidate, prune to beam_width, dedupe by
frozenset, width validation, builds_evaluated / depth_reached accounting) but
does NOT import it: the DS-engine ``compute_dps`` call is swapped for the
multi-term ``scoring.score_build`` (whose DPS term READS the seed deltas), and
DS is reached only through an injectable ``seed_fn`` HTTP boundary - never the
in-process engine (split-brain guard, dashboard/routes_state.py:548-549; the
mirrored ast scan is in tests/test_planner_beam_search.py).

None-contract mirrors core/build_order.py:410-418 - ``seed_fn=None`` or a blank
champion yields an empty, seedless BuildPlan (the caller falls back to
"unavailable" without partial state).

Candidate generation = top-K of the seed ``ranked[]`` UNION the build-order
``order[]`` warm-start (the same {ranked[], order[]} the dashboard routes
expose). The unique-passive no-double rule is INHERITED from each row's
engine-supplied ``unique_passive_key`` (core/build_order.py:34-48) - a candidate
whose family is already in the partial build is dropped, so the plan is
unique-passive-safe by construction with no family literal here.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.build_planner.scoring import ScoreTerms, score_build, stage_for

logger = logging.getLogger("rc.build_planner.planner")

# Beam defaults. WHY these magnitudes: the master plan (WP-C2, line 183)
# specifies beam width 5-8 and depth 6; we clamp width to that band and default
# to 6 (the mid of the band, == a full SR build). depth 6 == 6 item slots.
DEFAULT_BEAM_WIDTH = 6
DEFAULT_DEPTH = 6
_WIDTH_MIN = 5
_WIDTH_MAX = 8

# Candidate-pool size: top-K of the seed ranked[]. WHY 15 (master plan says
# 12-15): the widest end keeps a strong-but-not-top situational item in reach
# while bounding the per-node branching factor.
DEFAULT_TOP_K = 15

# Relative-threshold prune (tau). An offspring whose total score is below
# tau * (best offspring at this depth) is culled before the width cut. WHY
# 0.85 (master plan tau~0.85): aggressive enough to cull clearly-dominated
# partials, loose enough to keep genuine alternatives for the width sort.
DEFAULT_PRUNE_THRESHOLD = 0.85

# Per-node offspring cap - at most this many children expand from one parent
# before the global prune. WHY: bounds builds_evaluated even when the pool is
# large; the width cut keeps only the best survivors anyway.
_OFFSPRING_CAP = 8


@dataclass(frozen=True)
class PlannedItem:
    """One item in a planned (ordered) build, with its score breakdown."""

    item_id: str
    item_name: str
    gold: int
    delta_dps: float
    unique_passive_key: str
    terms: ScoreTerms  # the build's ScoreTerms at the step this item was added

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "item_name": self.item_name,
            "gold": self.gold,
            "delta_dps": round(self.delta_dps, 2),
            "unique_passive_key": self.unique_passive_key,
            "terms": self.terms.to_dict(),
        }


@dataclass(frozen=True)
class _Candidate:
    """An ordered partial build (a beam state) + its score."""

    items: tuple[PlannedItem, ...]
    total: float

    @property
    def id_set(self) -> frozenset:
        return frozenset(pi.item_id for pi in self.items)

    @property
    def families(self) -> frozenset:
        return frozenset(pi.unique_passive_key for pi in self.items
                         if pi.unique_passive_key)


@dataclass
class BuildPlan:
    """Result of a beam search - the chosen ordered build + the survivor beam.

    ``items`` is the best ordered build (the top beam survivor). ``beam`` is the
    full set of survivors (for lookahead / alternative display). Empty + zeroed
    counters when seedless (None-contract).
    """

    champion: str
    items: list[PlannedItem] = field(default_factory=list)
    beam: list[_Candidate] = field(default_factory=list)
    beam_width: int = DEFAULT_BEAM_WIDTH
    depth: int = DEFAULT_DEPTH
    depth_reached: int = 0
    candidate_pool_size: int = 0
    builds_evaluated: int = 0
    stage: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "items": [pi.to_dict() for pi in self.items],
            "beam": [[pi.to_dict() for pi in c.items] for c in self.beam],
            "beam_width": self.beam_width,
            "depth": self.depth,
            "depth_reached": self.depth_reached,
            "candidate_pool_size": self.candidate_pool_size,
            "builds_evaluated": self.builds_evaluated,
            "stage": self.stage,
            "notes": list(self.notes),
        }


def _clamp_width(beam_width: int) -> int:
    """Clamp the requested beam width into the master-plan 5-8 band."""
    return max(_WIDTH_MIN, min(_WIDTH_MAX, int(beam_width)))


def _candidate_pool(seed: dict, owned_ids, top_k: int) -> list[dict]:
    """Build the candidate row pool: top-K ranked[] UNION order[] warm start.

    Rows are the /api/ds-preview ``ranked[]`` shape (+ the build-order
    ``order[]`` warm-start, normalized to the same row shape). Owned ids are
    excluded. Dedupe by item_id, preserving the ranked[] order then appending
    any order[] item not already present (the warm start seeds a known-good
    opening even if it sits outside the raw top-K).
    """
    owned = {str(i) for i in (owned_ids or ())}
    pool: list[dict] = []
    seen: set[str] = set()

    for row in (seed.get("ranked") or [])[:top_k]:
        iid = row.get("item_id")
        if iid is None:
            continue
        iid = str(iid)
        if iid in owned or iid in seen:
            continue
        seen.add(iid)
        pool.append(dict(row))

    # Warm start: build-order order[] (BuildStep.to_dict shape). Normalize the
    # 'delta' / 'locked_family' keys to the ranked-row keys the scorer reads.
    for step in (seed.get("order") or []):
        iid = step.get("item_id")
        if iid is None:
            continue
        iid = str(iid)
        if iid in owned or iid in seen:
            continue
        seen.add(iid)
        pool.append({
            "item_id": iid,
            "item_name": step.get("item_name", ""),
            "delta_dps": float(step.get("delta", 0.0) or 0.0),
            "gold": int(step.get("gold", 0) or 0),
            "unique_passive_key": str(step.get("locked_family") or ""),
            "is_terminal": True,  # an order[] pick is a completed item.
        })

    return pool


def _to_planned(row: dict, terms: ScoreTerms) -> PlannedItem:
    return PlannedItem(
        item_id=str(row.get("item_id")),
        item_name=str(row.get("item_name", "")),
        gold=int(row.get("gold", 0) or 0),
        delta_dps=float(row.get("delta_dps", 0.0) or 0.0),
        unique_passive_key=str(row.get("unique_passive_key") or ""),
        terms=terms,
    )


def plan_build(
    champion: str,
    *,
    seed_fn: Optional[Callable[..., Optional[dict]]] = None,
    owned_item_ids=None,
    beam_width: int = DEFAULT_BEAM_WIDTH,
    depth: int = DEFAULT_DEPTH,
    clock_s: float = 0.0,
    top_k: int = DEFAULT_TOP_K,
    prune_threshold: float = DEFAULT_PRUNE_THRESHOLD,
    mode: str = "SR",
) -> BuildPlan:
    """Plan an ordered build via beam search over the seed candidate pool.

    ``seed_fn(champion, owned_ids, mode=...)`` returns the {ranked[], order[]}
    envelope (the HTTP boundary to DS - injectable, defaults to None). When it
    is None, or returns no rows, or ``champion`` is blank, an empty seedless
    BuildPlan is returned (None-contract, mirrors core/build_order.py).

    The score is the multi-term ``scoring.score_build`` (DPS term READ from the
    seed deltas - never recomputed). The unique-passive no-double rule is
    inherited from each row's ``unique_passive_key``.
    """
    if beam_width < 1:
        raise ValueError(f"beam_width must be >= 1, got {beam_width}")
    width = _clamp_width(beam_width)
    depth = max(0, int(depth))

    plan = BuildPlan(champion=str(champion), beam_width=width, depth=depth)

    # None-contract: no seed boundary, or blank champion -> seedless result.
    if seed_fn is None or not str(champion).strip():
        plan.notes.append("seedless - no seed_fn or blank champion")
        return plan

    owned = [str(i) for i in (owned_item_ids or ()) if str(i).strip()]
    plan.stage = stage_for(clock_s, len(owned))

    try:
        seed = seed_fn(str(champion), owned, mode=mode)
    except Exception as exc:  # noqa: BLE001 - boundary down -> seedless
        logger.debug("plan_build: seed_fn raised: %s", exc)
        plan.notes.append("seedless - seed_fn raised")
        return plan
    if not seed or not seed.get("ranked") and not seed.get("order"):
        plan.notes.append("seedless - seed_fn returned no candidates")
        return plan

    pool = _candidate_pool(seed, owned, top_k)
    plan.candidate_pool_size = len(pool)
    if not pool:
        plan.notes.append("seedless - candidate pool empty after owned filter")
        return plan

    rows_by_id = {r["item_id"]: r for r in pool}
    owned_count = len(owned)

    def _score(id_seq: list[str]) -> ScoreTerms:
        return score_build(
            id_seq, str(champion), pool,
            clock_s=clock_s, owned_count=owned_count, stage=plan.stage,
        )

    # Seed beam = the single empty partial build (score 0).
    empty_terms = _score([])
    beams: list[_Candidate] = [_Candidate(items=(), total=empty_terms.total)]
    seen: set[frozenset] = {frozenset()}
    builds_evaluated = 0
    depth_reached = 0

    for d in range(1, depth + 1):
        offspring: list[_Candidate] = []
        for parent in beams:
            parent_ids = parent.id_set
            parent_fams = parent.families
            children_here = 0
            for row in pool:
                if children_here >= _OFFSPRING_CAP:
                    break
                iid = row["item_id"]
                if iid in parent_ids:
                    continue
                # Unique-passive-safe BY CONSTRUCTION: drop a candidate whose
                # engine-supplied family is already locked in this partial
                # build (inherited rule - no family literal here).
                fam = str(row.get("unique_passive_key") or "")
                if fam and fam in parent_fams:
                    continue
                new_seq = [pi.item_id for pi in parent.items] + [iid]
                key = frozenset(new_seq)
                if key in seen:  # dedupe-by-set (order-invariant).
                    continue
                seen.add(key)
                terms = _score(new_seq)
                builds_evaluated += 1
                children_here += 1
                new_items = parent.items + (_to_planned(row, terms),)
                offspring.append(_Candidate(items=new_items, total=terms.total))

        if not offspring:
            break  # search exhausted (pool consumed / all families locked).

        # Relative-threshold prune: cull offspring below tau * best, THEN take
        # the top ``width`` survivors. WHY this order: the threshold removes
        # clearly-dominated partials cheaply before the width sort.
        best = max(c.total for c in offspring)
        # WHY abs(best): a negative best (penalty-dominated) inverts the
        # multiply - guard by gating on the floor relative to best magnitude.
        floor = prune_threshold * best if best >= 0 else best / prune_threshold
        kept = [c for c in offspring if c.total >= floor]
        kept.sort(key=lambda c: c.total, reverse=True)
        beams = kept[:width]
        depth_reached = d

    plan.builds_evaluated = builds_evaluated
    plan.depth_reached = depth_reached
    plan.beam = sorted(beams, key=lambda c: c.total, reverse=True)
    plan.items = list(plan.beam[0].items) if plan.beam else []
    return plan
