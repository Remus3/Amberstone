"""WP-D3 tests for the server-side item-override store (replan.py).

Proves that the operator's per-item build-order overrides (the client store
web/js/lib/item_overrides.js, mirrored into core.build_planner.replan as
``ItemOverrideStore``) are HONORED by the re-plan loop so a manual pin survives
the re-rank tick:

  1. SHIFT (Build-Earlier / Build-Later) survives the re-plan and shows in the
     display tail - identical across ticks (held, not re-ranked away).
  2. DEFER-ONCE sinks an item until exactly one full item completes, then the
     item RE-ENTERS (the server makes the client's approximate timing exact).
  3. SILENCE drops an item from swap / sell suggestions until reset.
  4. RESET (clear) wipes every override + baseline and logs ONE reset line.
  5. apply_ordering is a pure port of the client reorder (eff = i + shift +
     nudge + deferBias; stable on (eff, original_index); input not mutated).
  6. the LIVE route (/api/build-plan) honors a client-serialized snapshot.

Mirrors tests/test_replan_hysteresis.py: a local ``make_seed_fn`` returning the
{ok, ranked[], order[]} envelope (ranked rows are DICTS with keys item_id /
item_name / delta_dps / gold / unique_passive_key; order is []), the REAL
ddragon catalog for recipe / antiheal facts, and the contract-test route
injection (routes_build_plan._seed_fn_factory + the _Handler shim).

ASCII only - use " - " for a clause break (repo hard rule). Ordinal /
structural asserts only - never assert a raw float total.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from dashboard import routes_build_plan

from core.build_planner.replan import (
    ItemOverrideStore,
    ReplanLoop,
)
from core.build_planner.situational import EnemyProfile

_ROOT = Path(__file__).resolve().parent.parent
_CHAMP = "Miss Fortune"


# --------------------------------------------------------------------------- #
# Fake seed_fn - mirrors the {ranked[], order[]} envelope (and
# tests/test_replan_hysteresis.py:make_seed_fn). Each ranked row is a DICT - a
# bare-string order[] entry raises at planner.py:170, so order stays []. The
# seed only needs ids ownable / rankable; recipe + antiheal facts come from the
# REAL catalog via component_ids_of / classify_item.
# id: (name, delta_dps, gold, unique_passive_key)
# --------------------------------------------------------------------------- #
def make_seed_fn(catalog):
    """Return a deterministic seed_fn(champion, owned_ids, **kw) -> dict.

    ``catalog`` is an id -> (name, delta_dps, gold, unique_passive_key) map.
    Owned ids are excluded from the emitted ranked rows (the planner pool also
    excludes owned, but the seed mirrors the live ranker behavior).
    """

    def seed_fn(champion, owned_ids=None, **kw):
        owned = {str(i) for i in (owned_ids or ())}
        ranked: list[dict] = []
        for iid, (name, delta, gold, fam) in catalog.items():
            if iid in owned:
                continue
            ranked.append({
                "item_id": iid,
                "item_name": name,
                "delta_dps": float(delta),
                "gold": int(gold),
                "unique_passive_key": fam,
            })
        ranked.sort(key=lambda r: r["delta_dps"], reverse=True)
        return {"ok": True, "ranked": ranked, "order": []}

    return seed_fn


# Three distinct tail items (Z=200 > Y=88 > X=80 by delta_dps) - the planner
# orders the tail Z, Y, X, so a Build-Earlier on a mid item is observable.
_TAIL_CATALOG = {
    "X": ("Xitem", 80.0, 3000, ""),
    "Y": ("Yitem", 88.0, 3000, ""),
    "Z": ("Zitem", 200.0, 3000, ""),
}


# --------------------------------------------------------------------------- #
# 1: SHIFT persists across ticks
# --------------------------------------------------------------------------- #
class ShiftPersistsAcrossTicks(unittest.TestCase):
    def test_build_earlier_survives_replan_and_is_stable(self):
        seed = make_seed_fn(_TAIL_CATALOG)
        # Baseline (no overrides): record the mid item's index in plan_tail.
        base_loop = ReplanLoop()
        base = base_loop.tick(champion=_CHAMP, owned_item_ids=[], seed_fn=seed,
                              clock_s=1400, stage="late")
        tail = list(base.plan_tail)
        self.assertGreaterEqual(len(tail), 3)
        mid = tail[1]  # a mid-tail item (Y) - not already first.
        base_idx = base.plan_tail.index(mid)

        # Build-Earlier the mid item, then run TWO ticks with the same owned set.
        ov = ItemOverrideStore()
        ov.build_earlier(mid)
        loop = ReplanLoop()
        r1 = loop.tick(champion=_CHAMP, owned_item_ids=[], seed_fn=seed,
                       clock_s=1400, stage="late", overrides=ov)
        r2 = loop.tick(champion=_CHAMP, owned_item_ids=[], seed_fn=seed,
                       clock_s=1400, stage="late", overrides=ov)

        idx1 = r1.plan_tail.index(mid)
        idx2 = r2.plan_tail.index(mid)
        # The shift moved it earlier than the un-overridden order.
        self.assertLess(idx1, base_idx)
        # And the shift is HELD across the re-plan (identical tick-1 vs tick-2).
        self.assertEqual(idx1, idx2)


# --------------------------------------------------------------------------- #
# 2: DEFER-ONCE re-enters after exactly one full item completes
# --------------------------------------------------------------------------- #
class DeferReentersAfterOneItem(unittest.TestCase):
    def test_deferred_item_reenters_after_one_purchase(self):
        seed = make_seed_fn(_TAIL_CATALOG)
        loop = ReplanLoop()
        ov = ItemOverrideStore()
        # Prep tick establishes the would-be next item + the defer baseline
        # owned-count (reconcile sets _last_owned_count from len(owned)).
        prep = loop.tick(champion=_CHAMP, owned_item_ids=[], seed_fn=seed,
                         clock_s=1400, stage="late", overrides=ov)
        nxt = prep.next_item_id
        self.assertIsNotNone(nxt)

        # Defer the would-be next item.
        ov.defer(nxt)

        # tick(owned=K): next is NOT the deferred id and it is still deferred.
        r1 = loop.tick(champion=_CHAMP, owned_item_ids=[], seed_fn=seed,
                       clock_s=1400, stage="late", overrides=ov)
        self.assertNotEqual(r1.next_item_id, nxt)
        self.assertTrue(ov.is_deferred(nxt))

        # tick again, same owned -> still deferred (one item has NOT completed).
        r2 = loop.tick(champion=_CHAMP, owned_item_ids=[], seed_fn=seed,
                       clock_s=1400, stage="late", overrides=ov)
        self.assertNotEqual(r2.next_item_id, nxt)
        self.assertTrue(ov.is_deferred(nxt))

        # One full item completes (owned grows by one OTHER item, not nxt) ->
        # reconcile (driven by tick) RE-ENTERS the deferred item.
        other = next(i for i in _TAIL_CATALOG if i != nxt)
        loop.tick(champion=_CHAMP, owned_item_ids=[other], seed_fn=seed,
                  clock_s=1400, stage="late", overrides=ov)
        self.assertFalse(ov.is_deferred(nxt))


# --------------------------------------------------------------------------- #
# 3: SILENCE suppresses a swap suggestion until reset
# --------------------------------------------------------------------------- #
class SilencedSuppressedUntilReset(unittest.TestCase):
    def test_silenced_item_has_no_swap_then_reappears_after_reset(self):
        # 3033 (Mortal Reminder) is antiheal; an enemy with heal_sources == 0
        # makes it a wasted-antiheal swap candidate (mirrors the
        # test_replan_hysteresis antiheal-wasted setup). A tanky kill target
        # keeps ONLY the antiheal predicate in play.
        seed = make_seed_fn({"6672": ("Kraken Slayer", 85.0, 3000, "")})
        ep = EnemyProfile(heal_sources=0, kill_target_armor=150.0)

        loop = ReplanLoop()
        ov = ItemOverrideStore()
        ov.silence("3033")
        # Silenced tick (mid): no swap targets 3033.
        r1 = loop.tick(champion=_CHAMP, owned_item_ids=["3033"], seed_fn=seed,
                       clock_s=900, stage="mid", enemy_profile=ep,
                       surplus_gold=2000, overrides=ov)
        self.assertFalse(any(a.item_id == "3033" for a in r1.actions))

        # Reset every override, then a later-stage tick (the stage change resets
        # the per-stage sell counter, mirroring test_sell_rate_limit_and_stage_
        # reset): the swap action REAPPEARS for 3033.
        ov.clear()
        r2 = loop.tick(champion=_CHAMP, owned_item_ids=["3033"], seed_fn=seed,
                       clock_s=1400, stage="late", enemy_profile=ep,
                       surplus_gold=2000, overrides=ov)
        self.assertTrue(any(a.kind == "swap" and a.item_id == "3033"
                            for a in r2.actions))


# --------------------------------------------------------------------------- #
# 4: RESET clears every override + logs one reset line
# --------------------------------------------------------------------------- #
class ResetClearsAll(unittest.TestCase):
    def test_clear_wipes_state_and_logs_reset(self):
        ov = ItemOverrideStore()
        ov.build_earlier("A")    # shift -1 on A
        ov.defer("B")            # deferred B
        ov.keep("C")             # keep C
        ov.silence("D")          # silence D
        # Sanity: the overrides took.
        self.assertEqual(ov.shift_of("A"), -1)
        self.assertTrue(ov.is_deferred("B"))
        self.assertTrue(ov.is_kept("C"))
        self.assertTrue(ov.is_silenced("D"))

        ov.clear()
        # Every query is back to the default (0 / False).
        self.assertEqual(ov.shift_of("A"), 0)
        self.assertFalse(ov.is_deferred("B"))
        self.assertFalse(ov.is_kept("C"))
        self.assertFalse(ov.is_silenced("D"))
        # The internal store + defer baselines are empty.
        self.assertEqual(ov._ov, {})
        self.assertEqual(ov._defer_baseline, {})
        # A reset action-log line exists.
        self.assertTrue(any(e.get("action") == "reset" for e in ov.action_log))


# --------------------------------------------------------------------------- #
# 5: apply_ordering is a pure port of the client reorder
# --------------------------------------------------------------------------- #
class ApplyOrderingPure(unittest.TestCase):
    def test_single_build_earlier_overtakes_neighbor(self):
        ov = ItemOverrideStore()
        ov.build_earlier("c")  # c shifts one slot toward the front.
        out = ov.apply_ordering(["a", "b", "c", "d"])
        # c (idx 2, shift -1, eff 1.5) sorts strictly ahead of b (idx 1, eff 1).
        self.assertEqual(out, ["a", "c", "b", "d"])

    def test_deferred_id_sinks_last(self):
        ov = ItemOverrideStore()
        ov.defer("a")  # a sinks to the back (deferBias 1000).
        out = ov.apply_ordering(["a", "b", "c"])
        self.assertEqual(out, ["b", "c", "a"])

    def test_unoverridden_order_is_stable_and_input_not_mutated(self):
        ov = ItemOverrideStore()
        src = ["a", "b", "c", "d"]
        out = ov.apply_ordering(src)
        # No overrides -> identical order (stable on original_index).
        self.assertEqual(out, ["a", "b", "c", "d"])
        # A NEW list is returned; the input is not mutated.
        self.assertIsNot(out, src)
        self.assertEqual(src, ["a", "b", "c", "d"])


# --------------------------------------------------------------------------- #
# Route doubles - mirror tests/test_build_plan_contract.py (_Handler + the
# _seed_fn_factory injection + the _Cap/handler-shim _send capture).
# --------------------------------------------------------------------------- #
_FAKE_CATALOG = {
    "3031": ("Infinity Edge", 95.0, 3450, ""),
    "6672": ("Kraken Slayer", 85.0, 3000, ""),
    "3072": ("Bloodthirster", 80.0, 3400, ""),
    "3094": ("Rapid Firecannon", 70.0, 2500, "energized"),
    "3036": ("Lord Dominik's", 62.0, 3000, ""),
}


def _route_seed_fn(champion, owned_ids=None, **kw):
    owned = {str(i) for i in (owned_ids or ())}
    ranked = []
    for iid, (name, delta, gold, fam) in _FAKE_CATALOG.items():
        if iid in owned:
            continue
        ranked.append({
            "item_id": iid, "item_name": name,
            "delta_dps": delta, "gold": gold,
            "unique_passive_key": fam,
        })
    ranked.sort(key=lambda r: r["delta_dps"], reverse=True)
    return {
        "ok": True, "ranked": ranked, "order": [],
        "scorer": "dps",
        "target_stats": {"source": "live-items"},
        "defensive": [],
    }


class _Handler:
    """Stub handler capturing ``_send`` - mirrors the contract test's shim."""

    def __init__(self, path: str = "/api/build-plan") -> None:
        self.path = path
        self.status = 0
        self.body = b""
        self.content_type = ""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.status = status
        self.body = body
        self.content_type = content_type

    def json(self) -> dict:
        return json.loads(self.body.decode())


# --------------------------------------------------------------------------- #
# 6: the LIVE route honors a client-serialized shift snapshot
# --------------------------------------------------------------------------- #
class RouteHonorsShift(unittest.TestCase):
    def setUp(self):
        self._orig = routes_build_plan._seed_fn_factory
        routes_build_plan._seed_fn_factory = lambda **_kw: _route_seed_fn

    def tearDown(self):
        routes_build_plan._seed_fn_factory = self._orig

    def _post(self, payload: dict) -> dict:
        h = _Handler()
        routes_build_plan._serve_build_plan(h, payload)
        return h.json()

    def test_overrides_snapshot_shifts_a_tail_item_earlier(self):
        # Baseline order with nothing owned + no overrides.
        base = self._post({"champion": _CHAMP, "items": []})
        base_ids = [r["item_id"] for r in base["live"]]
        self.assertGreaterEqual(len(base_ids), 3)
        target = base_ids[2]  # a mid-tail item.
        base_idx = base_ids.index(target)

        # POST a client snapshot that shifts the target item strongly earlier.
        snap = {target: {"shift": -3, "deferred": False,
                         "keep": False, "silenced": False}}
        shifted = self._post({"champion": _CHAMP, "items": [],
                              "overrides": snap})
        shifted_ids = [r["item_id"] for r in shifted["live"]]
        self.assertLess(shifted_ids.index(target), base_idx)

    def test_reset_overrides_flag_ignores_the_snapshot(self):
        # reset_overrides truthy -> the snapshot is NOT honored (baseline order).
        base = self._post({"champion": _CHAMP, "items": []})
        base_ids = [r["item_id"] for r in base["live"]]
        target = base_ids[2]
        snap = {target: {"shift": -3, "deferred": False,
                         "keep": False, "silenced": False}}
        reset = self._post({"champion": _CHAMP, "items": [],
                            "overrides": snap, "reset_overrides": True})
        reset_ids = [r["item_id"] for r in reset["live"]]
        self.assertEqual(reset_ids, base_ids)


# --------------------------------------------------------------------------- #
# 7: ASCII hygiene (byte-level) on the touched + new files
# --------------------------------------------------------------------------- #
class AsciiHygiene(unittest.TestCase):
    def test_authored_bytes_are_7bit_ascii(self):
        targets = (
            _ROOT / "core" / "build_planner" / "replan.py",
            _ROOT / "dashboard" / "routes_build_plan.py",
            _ROOT / "tests" / "test_item_overrides_persist.py",
        )
        for path in targets:
            raw = path.read_bytes()
            offenders = [(i, b) for i, b in enumerate(raw) if b >= 0x80]
            self.assertEqual(
                offenders, [],
                f"{path.name} has non-ASCII bytes: {offenders[:5]!r}")


if __name__ == "__main__":
    unittest.main()
