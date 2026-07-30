"""
tft/tft_roll_odds.py
Deterministic TFT shop-hit probability. No LLM, no network, no third-party
dependency - stdlib only.

WHY THIS EXISTS
---------------
"Should I roll?" is currently answered by formatting the tier-odds table into
prompt TEXT (tft/tft_coach_engine.py:442-452) and letting Haiku read it out
loud. The table alone cannot answer the question: the number a player needs is
not "3-cost odds are 33 percent", it is "what are the odds I see my unit in
this shop, given how contested it is". That is arithmetic, so it belongs here
and not in a token budget.

THE MODEL
---------
A shop rolls SHOP_SLOTS independent slots. Each slot:
  1. picks a COST c with probability tier_odds[level][c];
  2. then picks uniformly at random from the copies of cost c still in the
     shared pool.

So for a single slot, with T copies of the target unit and C total copies of
that cost still in the pool:

    p_slot = tier_odds[level][cost] * T / C

and over independent slots:

    p_shop = 1 - (1 - p_slot) ** slots

Slots are treated as independent draws from the pool. That is the standard
model and the error is negligible while C >> slots (C is in the hundreds even
late); it is stated here rather than hidden because it IS an approximation.

Pool arithmetic:
    C = pool_sizes[cost] * units_per_cost[cost] - cost_copies_taken
    T = pool_sizes[cost]                        - target_copies_taken
where *_taken counts every copy removed from the shared pool by ANY player
(bought, benched, on a board, or upgraded), including your own.

STALENESS
---------
The constants this module reads may be WRONG - see constants_health() and
tests/test_tft_constants_staleness.py. The math here is correct for whatever
the constants say; it does not silently repair them. Source of truth for tier
odds and pool sizes is the in-client display, which is live-gated.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from types import ModuleType
from typing import Mapping

__all__ = [
    "SHOP_SLOTS",
    "SetConstants",
    "load_constants",
    "default_constants",
    "remaining_pool",
    "slot_probability",
    "shop_hit_probability",
    "expected_copies_per_shop",
    "rolls_for_confidence",
    "constants_health",
]

SHOP_SLOTS = 5


@dataclass(frozen=True)
class SetConstants:
    """One TFT set's roll constants, plus how much they can be trusted."""

    source: str
    set_number: int
    verified_in_client: bool
    tier_odds: Mapping[int, Mapping[int, float]]
    pool_sizes: Mapping[int, int]
    units_per_cost: Mapping[int, int] | None

    @property
    def complete(self) -> bool:
        """False when the module is missing a table the odds math needs."""
        return bool(self.tier_odds and self.pool_sizes and self.units_per_cost)


def load_constants(module: ModuleType) -> SetConstants:
    """Build a SetConstants from a TFT data module (tft_data / tft_pbe_data).

    A module missing UNITS_PER_COST yields units_per_cost=None rather than a
    guess; probability calls against it then raise. Inventing that table would
    be exactly the silent third-party correction this slice must not make.
    """
    return SetConstants(
        source=getattr(module, "__name__", repr(module)),
        set_number=getattr(module, "CONSTANTS_SET", -1),
        verified_in_client=bool(getattr(module, "CONSTANTS_SET_VERIFIED", False)),
        tier_odds=getattr(module, "TIER_ODDS", {}),
        pool_sizes=getattr(module, "POOL_SIZES", {}),
        units_per_cost=getattr(module, "UNITS_PER_COST", None),
    )


def default_constants() -> SetConstants:
    """The only COMPLETE bundle in the repo today - and it declares Set 14.

    That is not a preference, it is the measured state: tft_pbe_data.py (the
    Set 17 module) ships no UNITS_PER_COST, so it cannot answer a pool
    question at all. constants_health() reports this.
    """
    from tft import tft_data

    return load_constants(tft_data)


def _tables(consts: SetConstants | None) -> SetConstants:
    c = consts if consts is not None else default_constants()
    if not c.complete:
        raise ValueError(
            f"{c.source} cannot answer roll odds: missing "
            + ", ".join(
                n
                for n, v in (
                    ("TIER_ODDS", c.tier_odds),
                    ("POOL_SIZES", c.pool_sizes),
                    ("UNITS_PER_COST", c.units_per_cost),
                )
                if not v
            )
        )
    return c


def _validate(level: int, cost: int, consts: SetConstants) -> None:
    if level not in consts.tier_odds:
        raise ValueError(
            f"level {level} not in {consts.source} TIER_ODDS "
            f"(have {sorted(consts.tier_odds)})"
        )
    if cost not in consts.pool_sizes:
        raise ValueError(
            f"cost {cost} not in {consts.source} POOL_SIZES "
            f"(have {sorted(consts.pool_sizes)})"
        )


def remaining_pool(
    cost: int,
    *,
    target_copies_taken: int = 0,
    cost_copies_taken: int = 0,
    consts: SetConstants | None = None,
) -> tuple[int, int]:
    """(copies of the target unit left, total copies of that cost left).

    Both are floored at 0. Over-reporting removals cannot make a pool
    negative, it just makes the odds zero.
    """
    c = _tables(consts)
    if cost not in c.pool_sizes:
        raise ValueError(
            f"cost {cost} not in {c.source} POOL_SIZES (have {sorted(c.pool_sizes)})"
        )
    if target_copies_taken < 0 or cost_copies_taken < 0:
        raise ValueError("copies taken cannot be negative")
    per_unit = c.pool_sizes[cost]
    assert c.units_per_cost is not None  # guaranteed by _tables
    total = per_unit * c.units_per_cost[cost]
    return max(0, per_unit - target_copies_taken), max(0, total - cost_copies_taken)


def slot_probability(
    level: int,
    cost: int,
    *,
    target_copies_taken: int = 0,
    cost_copies_taken: int = 0,
    consts: SetConstants | None = None,
) -> float:
    """Probability that ONE shop slot shows the target unit. In [0, 1]."""
    c = _tables(consts)
    _validate(level, cost, c)
    odds = float(c.tier_odds[level].get(cost, 0.0))
    if odds <= 0.0:
        return 0.0
    target_left, cost_left = remaining_pool(
        cost,
        target_copies_taken=target_copies_taken,
        cost_copies_taken=cost_copies_taken,
        consts=c,
    )
    if cost_left <= 0 or target_left <= 0:
        return 0.0
    # A target copy is by definition still in the cost pool, so a caller who
    # under-reports cost removals cannot be allowed to push the share past 1.
    share = min(1.0, target_left / cost_left)
    return max(0.0, min(1.0, odds * share))


def shop_hit_probability(
    level: int,
    cost: int,
    *,
    target_copies_taken: int = 0,
    cost_copies_taken: int = 0,
    slots: int = SHOP_SLOTS,
    consts: SetConstants | None = None,
) -> float:
    """Probability of AT LEAST ONE copy of the target in a fresh shop."""
    if slots < 0:
        raise ValueError("slots cannot be negative")
    p = slot_probability(
        level,
        cost,
        target_copies_taken=target_copies_taken,
        cost_copies_taken=cost_copies_taken,
        consts=consts,
    )
    if p <= 0.0 or slots == 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - (1.0 - p) ** slots))


def expected_copies_per_shop(
    level: int,
    cost: int,
    *,
    target_copies_taken: int = 0,
    cost_copies_taken: int = 0,
    slots: int = SHOP_SLOTS,
    consts: SetConstants | None = None,
) -> float:
    """Expected number of target copies in a fresh shop (may exceed 1)."""
    if slots < 0:
        raise ValueError("slots cannot be negative")
    return slots * slot_probability(
        level,
        cost,
        target_copies_taken=target_copies_taken,
        cost_copies_taken=cost_copies_taken,
        consts=consts,
    )


def rolls_for_confidence(
    level: int,
    cost: int,
    *,
    confidence: float = 0.5,
    target_copies_taken: int = 0,
    cost_copies_taken: int = 0,
    slots: int = SHOP_SLOTS,
    consts: SetConstants | None = None,
) -> int | None:
    """Fewest shops to hit the target with probability >= confidence.

    None when the target is unreachable (odds 0). Assumes the pool does not
    move between rolls, which is the optimistic direction: other players
    contest during a rolldown, so treat this as a floor.
    """
    if not 0.0 <= confidence < 1.0:
        raise ValueError("confidence must be in [0, 1)")
    p = shop_hit_probability(
        level,
        cost,
        target_copies_taken=target_copies_taken,
        cost_copies_taken=cost_copies_taken,
        slots=slots,
        consts=consts,
    )
    if p <= 0.0:
        return None
    if confidence <= 0.0:
        return 0
    if p >= 1.0:
        return 1
    return max(1, math.ceil(math.log(1.0 - confidence) / math.log(1.0 - p)))


def constants_health(lane_set: int | None = None) -> dict:
    """Report how stale / unverifiable the TFT roll constants are.

    lane_set defaults to the "_set" the TFT lane's live meta file declares.
    Returns a plain dict so a test can pin it and a caller can render it.
    """
    import json
    from pathlib import Path

    from tft import tft_data, tft_pbe_data

    if lane_set is None:
        meta = Path(__file__).parent.parent / "data" / "meta" / "tft_set17_meta.json"
        lane_set = int(json.loads(meta.read_text(encoding="utf-8"))["_set"])

    modules = [load_constants(m) for m in (tft_data, tft_pbe_data)]
    report = {
        "lane_set": lane_set,
        "modules": {},
        "problems": [],
    }
    for c in modules:
        report["modules"][c.source] = {
            "declared_set": c.set_number,
            "verified_in_client": c.verified_in_client,
            "complete": c.complete,
            "missing": [
                n
                for n, v in (
                    ("TIER_ODDS", c.tier_odds),
                    ("POOL_SIZES", c.pool_sizes),
                    ("UNITS_PER_COST", c.units_per_cost),
                )
                if not v
            ],
        }
        if c.set_number != lane_set:
            report["problems"].append(
                f"{c.source} declares set {c.set_number} but the lane is on "
                f"set {lane_set}: its constants are STALE"
            )
        if not c.verified_in_client:
            report["problems"].append(
                f"{c.source} is not in-client verified (live-gated)"
            )
        if not c.complete:
            report["problems"].append(
                f"{c.source} cannot answer roll odds, missing: "
                + ", ".join(report["modules"][c.source]["missing"])
            )

    a, b = modules
    if a.set_number != b.set_number:
        if dict(a.tier_odds) == dict(b.tier_odds):
            report["problems"].append(
                f"{a.source} (set {a.set_number}) and {b.source} "
                f"(set {b.set_number}) ship IDENTICAL TIER_ODDS - copied, "
                "not re-derived"
            )
        if dict(a.pool_sizes) == dict(b.pool_sizes):
            report["problems"].append(
                f"{a.source} (set {a.set_number}) and {b.source} "
                f"(set {b.set_number}) ship IDENTICAL POOL_SIZES - copied, "
                "not re-derived"
            )
    return report
