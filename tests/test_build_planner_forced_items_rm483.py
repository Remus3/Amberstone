"""RM-483: locked / forced-item slots for items NOT YET OWNED (build planner).

A player who has decided on an item they do not own yet ("I am building
Zhonya's") needs the planner to plan AROUND it, not drop it because a higher
delta row outranks it. ``plan_build(forced_item_ids=...)`` guarantees every
forced id that is in the candidate pool appears in the planned build, by
feasibility pruning during the beam search (never by post-hoc splicing, which
would break the score terms and the unique-passive rule).
"""
from __future__ import annotations

from core.build_planner.planner import plan_build


def _row(iid, dps, gold=3000, fam=""):
    return {"item_id": iid, "item_name": f"I{iid}", "delta_dps": dps,
            "gold": gold, "unique_passive_key": fam, "is_terminal": True}


RANKED = [
    _row("1", 100.0), _row("2", 90.0), _row("3", 80.0),
    _row("4", 70.0), _row("5", 60.0, fam="lifeline"), _row("6", 5.0),
    _row("7", 4.0, fam="lifeline"),
]


def _seed(champion, owned, mode="SR"):
    return {"ranked": [dict(r) for r in RANKED]}


def _ids(plan):
    return [pi.item_id for pi in plan.items]


def test_baseline_without_forced_items_skips_the_weak_row():
    plan = plan_build("Ahri", seed_fn=_seed, depth=3)
    assert "6" not in _ids(plan)
    assert len(_ids(plan)) == 3


def test_forced_weak_item_is_planned():
    plan = plan_build("Ahri", seed_fn=_seed, depth=3, forced_item_ids=["6"])
    assert "6" in _ids(plan)
    assert len(_ids(plan)) == 3


def test_every_beam_survivor_carries_the_forced_items():
    plan = plan_build("Ahri", seed_fn=_seed, depth=3, forced_item_ids=["6", "4"])
    assert plan.beam
    for cand in plan.beam:
        ids = {pi.item_id for pi in cand.items}
        assert {"6", "4"} <= ids


def test_forced_item_reserves_its_unique_family():
    """A forced 'lifeline' item must not be blocked by a stronger row of the
    same family taking the slot first (no-double-unique rule inherited)."""
    plan = plan_build("Ahri", seed_fn=_seed, depth=3, forced_item_ids=["7"])
    ids = _ids(plan)
    assert "7" in ids
    assert "5" not in ids


def test_forced_item_outside_the_pool_is_noted_not_invented():
    plan = plan_build("Ahri", seed_fn=_seed, depth=3, forced_item_ids=["999"])
    assert "999" not in _ids(plan)
    assert any("999" in n and "not in candidate pool" in n for n in plan.notes)
    assert len(_ids(plan)) == 3


def test_owned_forced_item_is_already_satisfied():
    plan = plan_build("Ahri", seed_fn=_seed, depth=3,
                      owned_item_ids=["6"], forced_item_ids=["6"])
    assert "6" not in _ids(plan)  # owned items are never re-planned
    assert len(_ids(plan)) == 3


def test_more_forced_items_than_slots_is_noted_and_truncated():
    plan = plan_build("Ahri", seed_fn=_seed, depth=2,
                      forced_item_ids=["6", "4", "3"])
    assert set(_ids(plan)) == {"6", "4"}
    assert any("exceed" in n for n in plan.notes)


def test_two_forced_items_sharing_a_family_keep_the_first():
    plan = plan_build("Ahri", seed_fn=_seed, depth=3, forced_item_ids=["7", "5"])
    ids = _ids(plan)
    assert "7" in ids and "5" not in ids
    assert any("5" in n and "family" in n for n in plan.notes)
