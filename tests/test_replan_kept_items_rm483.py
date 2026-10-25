"""RM-483 residue: ``ReplanLoop.tick`` honours the operator's KEPT items.

``plan_build(forced_item_ids=...)`` (core/build_planner/planner.py:236-248,
normalized by ``_resolve_forced`` :189-222) already plans AROUND a locked item
the player does not own yet. Before this fix ``ReplanLoop.tick`` called
``plan_build`` without it (core/build_planner/replan.py:605-607 at a18bdb66a),
and the override store's keep flag (``ItemOverrideStore.is_kept`` :298-300)
was read only for the current incumbent, so a kept item outside the beam's
plan never entered ``plan_tail``.

The forced-item semantics are plan_build's, not re-implemented here: caller
order is priority, owned ids are already satisfied, an id outside the
candidate pool is noted and never invented, and a second forced id in an
already-forced unique family is dropped. The owned-family conflict is the
engine's: DS filters a candidate whose ``unique_passive_key`` an owned item
already holds (``filter_shared_uniques``, core/build_order.py:34-48), so that
kept id is out of the pool and plan_build notes it.

Family names below are neutral test tokens - the no-family-literal guard
(tests/test_planner_beam_search.py) scans the planner sources, not tests.
"""
from __future__ import annotations

import json

import core.build_planner.replan as replan_mod
from core.build_planner.planner import plan_build
from core.build_planner.replan import ItemOverrideStore, ReplanLoop

_CHAMP = "Ahri"
_DEPTH = 3


def _row(iid, dps, gold=3000, fam=""):
    return {"item_id": iid, "item_name": f"I{iid}", "delta_dps": dps,
            "gold": gold, "unique_passive_key": fam, "is_terminal": True}


RANKED = [
    _row("1", 100.0), _row("2", 90.0), _row("3", 80.0),
    _row("4", 70.0), _row("5", 60.0, fam="fam_a"), _row("6", 5.0),
    _row("7", 4.0, fam="fam_a"),
]


def _seed(champion, owned, mode="SR"):
    """Seed boundary that mirrors the engine's owned-unique filter.

    A row whose family an OWNED item already holds is dropped, the way DS
    drops it server-side with ``filter_shared_uniques`` on (the default).
    """
    owned_set = {str(i) for i in (owned or ())}
    owned_fams = {r["unique_passive_key"] for r in RANKED
                  if r["item_id"] in owned_set and r["unique_passive_key"]}
    rows = [dict(r) for r in RANKED
            if not (r["unique_passive_key"]
                    and r["unique_passive_key"] in owned_fams
                    and r["item_id"] not in owned_set)]
    return {"ranked": rows}


def _spy(monkeypatch) -> list:
    """Record every kwargs dict ``tick`` passes to plan_build, then delegate."""
    calls: list = []
    real = replan_mod.plan_build

    def _wrapped(*args, **kwargs):
        calls.append(dict(kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(replan_mod, "plan_build", _wrapped)
    return calls


def _tick(owned=(), overrides=None):
    return ReplanLoop().tick(
        champion=_CHAMP, owned_item_ids=list(owned), seed_fn=_seed,
        depth=_DEPTH, overrides=overrides)


def _store(*kept):
    store = ItemOverrideStore()
    for iid in kept:
        store.keep(iid)
    return store


def test_kept_item_missing_from_the_normal_plan_enters_plan_tail(monkeypatch):
    baseline = _tick()
    assert "6" not in baseline.plan_tail  # the weak row is outranked
    assert len(baseline.plan_tail) == _DEPTH

    calls = _spy(monkeypatch)
    result = _tick(overrides=_store("6"))
    assert calls and calls[0].get("forced_item_ids") == ["6"]
    assert "6" in result.plan_tail
    assert len(result.plan_tail) == _DEPTH
    for cand in result.plan.beam:  # plan_build's every-survivor guarantee
        assert "6" in {pi.item_id for pi in cand.items}


def test_nothing_kept_leaves_the_plan_byte_identical(monkeypatch):
    calls = _spy(monkeypatch)
    plain = _tick()
    # A store with overrides but NO keep (toggled on then off, plus a
    # silence) must not change the plan.
    store = ItemOverrideStore()
    store.keep("6")
    store.keep("6")
    store.silence("2")
    with_store = _tick(overrides=store)

    assert [c.get("forced_item_ids", "ABSENT") for c in calls] == [None, None]
    old = plan_build(_CHAMP, seed_fn=_seed, owned_item_ids=[], clock_s=0.0,
                     beam_width=6, depth=_DEPTH, mode="SR")
    old_bytes = json.dumps(old.to_dict(), sort_keys=True)
    assert json.dumps(plain.plan.to_dict(), sort_keys=True) == old_bytes
    assert json.dumps(with_store.plan.to_dict(), sort_keys=True) == old_bytes
    assert (json.dumps(plain.to_dict(), sort_keys=True)
            == json.dumps(with_store.to_dict(), sort_keys=True))


def test_owned_kept_item_is_not_forced_again(monkeypatch):
    calls = _spy(monkeypatch)
    result = _tick(owned=["4"], overrides=_store("4", "6"))
    assert calls[0].get("forced_item_ids") == ["6"]  # owned "4" stripped
    assert "4" not in result.plan_tail  # owned ids are the fixed prefix
    assert result.owned_prefix == ("4",)
    assert "6" in result.plan_tail


def test_only_owned_kept_items_force_nothing(monkeypatch):
    calls = _spy(monkeypatch)
    result = _tick(owned=["4"], overrides=_store("4"))
    assert calls[0].get("forced_item_ids", "ABSENT") is None
    old = plan_build(_CHAMP, seed_fn=_seed, owned_item_ids=["4"],
                     clock_s=0.0, beam_width=6, depth=_DEPTH, mode="SR")
    assert (json.dumps(result.plan.to_dict(), sort_keys=True)
            == json.dumps(old.to_dict(), sort_keys=True))


def test_kept_item_in_an_owned_unique_family_is_noted_not_planned(monkeypatch):
    """Owned "5" holds fam_a, so the engine filters kept "7" (fam_a) out of
    the pool; plan_build notes the out-of-pool forced id and never invents
    it - no double unique passive reaches the plan."""
    calls = _spy(monkeypatch)
    result = _tick(owned=["5"], overrides=_store("7"))
    assert calls[0].get("forced_item_ids") == ["7"]
    assert "7" not in result.plan_tail
    assert len(result.plan_tail) == _DEPTH
    assert any("7" in n and "not in candidate pool" in n
               for n in result.plan.notes)


def test_two_kept_items_sharing_a_family_keep_the_first_in_store_order():
    """Caller order is plan_build's priority; the store passes kept ids in
    the order the operator first touched them."""
    result = _tick(overrides=_store("7", "5"))
    assert "7" in result.plan_tail and "5" not in result.plan_tail
    assert any("5" in n and "family" in n for n in result.plan.notes)
