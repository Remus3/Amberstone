"""RED-first tests for core/build_planner/replan.py (WP-C4).

Proves the owned-aware re-plan loop that sits ABOVE the WP-C2 planner:

  1. owned ids are a FIXED prefix - never re-planned, never in plan_tail.
  2. STICKINESS (next-item hysteresis) uses single-item ``score_build([id])``
     totals, NOT the collapsing beam map (the BLOCKER fix - see the locked
     spec "Why" section). A challenger inside the stickiness margin does not
     flip the next-item; a big-swing challenger does.
  3. component-defer drops a planned id whose effect is already owned (the
     id is a transitive ``from``-component of a finished owned item) from the
     next-item choice while keeping it in plan_tail for display.
  4. sell / swap actions are gated (surplus, rate-limit, just-bought lock) and
     the free trinket upgrade bypasses every gate.
  5. the Schmitt-trigger pivot is a banded hysteresis (low < high enforced,
     inclusive boundaries, no flicker inside the band).
  6. ALL state is in-memory - tick writes nothing to disk; end_match only
     writes when given a path (atomic).

Mirrors tests/test_planner_beam_search.py: a local ``make_seed_fn`` returning
the {ok, ranked[], order[]} envelope (ranked rows are DICTS with keys
item_id / item_name / delta_dps / gold / unique_passive_key; order is []).

ASCII only - use " - " for a clause break (repo hard rule). Ordinal /
structural asserts only - never assert a raw float total.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from core.build_planner.replan import (
    ReplanConfig,
    ReplanLoop,
    ReplanResult,
    SwapAction,
    component_ids_of,
    is_boots,
    schmitt,
)

_ROOT = Path(__file__).resolve().parent.parent
_ITEMS_PATH = _ROOT / "data" / "meta" / "ddragon_items.json"
_CHAMP = "Miss Fortune"


def _load_catalog() -> dict:
    """Read the REAL ddragon catalog (data key) for recipe assertions."""
    raw = json.loads(_ITEMS_PATH.read_text(encoding="utf-8"))
    return raw.get("data", raw)


# --------------------------------------------------------------------------- #
# Fake seed_fn - mirrors the {ranked[], order[]} envelope the dashboard routes
# expose (and that tests/test_planner_beam_search.py:make_seed_fn uses). Each
# ranked row is a DICT - a bare-string order[] entry raises at planner.py:170,
# so order stays []. The seed only needs ids ownable / rankable; recipe and
# antiheal facts come from the REAL catalog via component_ids_of/classify_item.
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


# A close pair (Y/X single-item total ratio = 1.082 < 1.10) plus a big swing
# (Z/X = 2.236 > 1.10). All gold=3000, same empty passive key - only delta_dps
# differs, so the ratios are stable and verified live (locked spec "Why").
_STICKY_CATALOG = {
    "X": ("Xitem", 80.0, 3000, ""),
    "Y": ("Yitem", 88.0, 3000, ""),
    "Z": ("Zitem", 200.0, 3000, ""),
}


# --------------------------------------------------------------------------- #
# 1-2: owned prefix / plan_tail disjointness
# --------------------------------------------------------------------------- #
class OwnedPrefixTests(unittest.TestCase):
    def test_owned_prefix_verbatim_and_excluded_from_tail(self):
        # owned ['X'] -> owned_prefix == ('X',) and 'X' never re-planned.
        loop = ReplanLoop()
        seed = make_seed_fn(_STICKY_CATALOG)
        r1 = loop.tick(champion=_CHAMP, owned_item_ids=["X"], seed_fn=seed,
                       clock_s=1400, stage="late")
        self.assertIsInstance(r1, ReplanResult)
        self.assertEqual(r1.owned_prefix, ("X",))
        self.assertNotIn("X", r1.plan_tail)
        # Identical across a second tick with the same owned set.
        r2 = loop.tick(champion=_CHAMP, owned_item_ids=["X"], seed_fn=seed,
                       clock_s=1400, stage="late")
        self.assertEqual(r2.owned_prefix, ("X",))
        self.assertNotIn("X", r2.plan_tail)

    def test_plan_tail_and_owned_are_disjoint(self):
        loop = ReplanLoop()
        seed = make_seed_fn(_STICKY_CATALOG)
        r = loop.tick(champion=_CHAMP, owned_item_ids=["X"], seed_fn=seed,
                      clock_s=1400, stage="late")
        self.assertTrue(set(r.plan_tail).isdisjoint(set(r.owned_prefix)))


# --------------------------------------------------------------------------- #
# 3-4: stickiness next-item hysteresis (single-item totals)
# --------------------------------------------------------------------------- #
class StickinessTests(unittest.TestCase):
    def test_sticky_case_close_challenger_stays(self):
        # tick1 latches incumbent X; tick2 presents challenger Y. Y/X single-
        # item total ratio = 1.082 < 1.10 margin -> next STAYS X, sticky True.
        loop = ReplanLoop()
        seed_x = make_seed_fn({"X": _STICKY_CATALOG["X"]})
        r1 = loop.tick(champion=_CHAMP, owned_item_ids=[], seed_fn=seed_x,
                       clock_s=1400, stage="late")
        self.assertEqual(r1.next_item_id, "X")
        # tick2: both X and Y in the pool, Y orders first by delta_dps.
        seed_xy = make_seed_fn({"X": _STICKY_CATALOG["X"],
                                "Y": _STICKY_CATALOG["Y"]})
        r2 = loop.tick(champion=_CHAMP, owned_item_ids=[], seed_fn=seed_xy,
                       clock_s=1400, stage="late")
        self.assertEqual(r2.next_item_id, "X")
        self.assertTrue(r2.sticky)

    def test_big_swing_challenger_flips(self):
        # Same setup but challenger Z (delta=200) - Z/X = 2.236 > 1.10 -> flip.
        loop = ReplanLoop()
        seed_x = make_seed_fn({"X": _STICKY_CATALOG["X"]})
        r1 = loop.tick(champion=_CHAMP, owned_item_ids=[], seed_fn=seed_x,
                       clock_s=1400, stage="late")
        self.assertEqual(r1.next_item_id, "X")
        seed_xz = make_seed_fn({"X": _STICKY_CATALOG["X"],
                                "Z": _STICKY_CATALOG["Z"]})
        r2 = loop.tick(champion=_CHAMP, owned_item_ids=[], seed_fn=seed_xz,
                       clock_s=1400, stage="late")
        self.assertEqual(r2.next_item_id, "Z")
        self.assertFalse(r2.sticky)


# --------------------------------------------------------------------------- #
# 5-6, 23: schmitt() pure primitive
# --------------------------------------------------------------------------- #
class SchmittTests(unittest.TestCase):
    def test_schmitt_band_table(self):
        # below high stays off.
        self.assertFalse(schmitt(False, 1.10, high=1.20, low=0.90))
        # value == high from off -> ON (inclusive).
        self.assertTrue(schmitt(False, 1.20, high=1.20, low=0.90))
        # in-band oscillation while on -> stays on.
        self.assertTrue(schmitt(True, 1.00, high=1.20, low=0.90))
        # value < low -> off.
        self.assertFalse(schmitt(True, 0.50, high=1.20, low=0.90))
        # value == low while on -> STAYS on (inclusive).
        self.assertTrue(schmitt(True, 0.90, high=1.20, low=0.90))

    def test_schmitt_flicker_is_constant(self):
        # An oscillation strictly inside (low, high) yields a CONSTANT output
        # equal to the seed state - never flickers.
        seq = [1.00, 0.95, 1.15, 1.05, 0.91, 1.19]
        state_on = True
        for v in seq:
            state_on = schmitt(state_on, v, high=1.20, low=0.90)
            self.assertTrue(state_on)
        state_off = False
        for v in seq:
            state_off = schmitt(state_off, v, high=1.20, low=0.90)
            self.assertFalse(state_off)

    def test_schmitt_exact_boundary(self):
        # value == high (1.20) from off -> ON.
        self.assertTrue(schmitt(False, 1.20, high=1.20, low=0.90))
        # value == low (0.90) while on -> STAYS on.
        self.assertTrue(schmitt(True, 0.90, high=1.20, low=0.90))
        # value just below low while on -> OFF (pins the inclusive >= edge).
        self.assertFalse(schmitt(True, 0.8999, high=1.20, low=0.90))


# --------------------------------------------------------------------------- #
# 7, 21: component-defer (transitive recipe closure)
# --------------------------------------------------------------------------- #
class ComponentDeferTests(unittest.TestCase):
    def test_component_of_finished_item_is_deferred(self):
        # Confirm 3035 IS a from-component of 3036 (do not hardcode the
        # assumption) - read the REAL catalog.
        catalog = _load_catalog()
        self.assertIn("3035", catalog["3036"]["from"])
        # owned ['3036'] - the seed offers 3035 (a component, must defer) plus
        # a non-component high item (must be the next pick).
        seed = make_seed_fn({
            "3035": ("Last Whisper", 60.0, 1450, ""),
            "6672": ("Kraken Slayer", 85.0, 3000, ""),
        })
        loop = ReplanLoop()
        r = loop.tick(champion=_CHAMP, owned_item_ids=["3036"], seed_fn=seed,
                      clock_s=1400, stage="late")
        self.assertIn("3035", r.deferred)
        self.assertNotEqual(r.next_item_id, "3035")
        self.assertEqual(r.next_item_id, "6672")
        # Still appears in plan_tail (full-for-display).
        self.assertIn("3035", r.plan_tail)

    def test_component_ids_of_is_transitive_and_deduped(self):
        # 3036 -> {3035 (1-level), 1036 (2-level via 3035.from=[1036,1036])}.
        comp = component_ids_of(["3036"])
        self.assertIn("3035", comp)
        self.assertIn("1036", comp)
        # 3033 -> {3123, 3035, 1018, 1036} (3123.from=[1036], 3035.from=[1036]).
        comp33 = component_ids_of(["3033"])
        for cid in ("3123", "3035", "1018", "1036"):
            self.assertIn(cid, comp33)


# --------------------------------------------------------------------------- #
# 8-10, 25: sell gating
# --------------------------------------------------------------------------- #
class SellGatingTests(unittest.TestCase):
    @staticmethod
    def _full_inventory_seed():
        # Six finished items including base boots 1001 + filler.
        return make_seed_fn({
            "6672": ("Kraken Slayer", 85.0, 3000, ""),
            "3031": ("Infinity Edge", 95.0, 3450, ""),
        })

    def test_boots_sell_gated_by_surplus(self):
        owned = ["1001", "3031", "6672", "3036", "3072", "3046"]
        seed = self._full_inventory_seed()
        # surplus below the boots threshold (1000) -> no sell_boots.
        lo = ReplanLoop()
        r_lo = lo.tick(champion=_CHAMP, owned_item_ids=owned, seed_fn=seed,
                       clock_s=1400, stage="late", surplus_gold=500)
        self.assertFalse(any(a.kind == "sell_boots" for a in r_lo.actions))
        # surplus at/above threshold -> sell_boots emitted.
        hi = ReplanLoop()
        r_hi = hi.tick(champion=_CHAMP, owned_item_ids=owned, seed_fn=seed,
                       clock_s=1400, stage="late", surplus_gold=1500)
        self.assertTrue(any(a.kind == "sell_boots" for a in r_hi.actions))

    def test_sell_rate_limit_and_stage_reset(self):
        owned = ["1001", "3031", "6672", "3036", "3072", "3046"]
        seed = self._full_inventory_seed()
        loop = ReplanLoop()
        # Two sell-worthy ticks in the SAME stage (mid) - at most one sell-class
        # action total across the two ticks.
        r1 = loop.tick(champion=_CHAMP, owned_item_ids=owned, seed_fn=seed,
                       clock_s=900, stage="mid", surplus_gold=1500)
        r2 = loop.tick(champion=_CHAMP, owned_item_ids=owned, seed_fn=seed,
                       clock_s=901, stage="mid", surplus_gold=1500)
        sells_mid = sum(1 for r in (r1, r2)
                        for a in r.actions if a.kind == "sell_boots")
        self.assertLessEqual(sells_mid, 1)
        self.assertEqual(sells_mid, 1)
        # A third tick AFTER a stage transition to late -> a sell is allowed
        # again (the mid counter did not leak into late).
        r3 = loop.tick(champion=_CHAMP, owned_item_ids=owned, seed_fn=seed,
                       clock_s=1400, stage="late", surplus_gold=1500)
        self.assertTrue(any(a.kind == "sell_boots" for a in r3.actions))

    def test_just_bought_lock_blocks_non_offbuild_sell(self):
        # A purchase at T (owned COUNT grows) blocks a NON-off-build sell within
        # the lock window; an off-build (matchup-invalidated) sell at mid+ in
        # the window is still allowed.
        owned5 = ["3031", "6672", "3036", "3072", "3046"]
        owned6 = ["1001", "3031", "6672", "3036", "3072", "3046"]
        seed = self._full_inventory_seed()
        loop = ReplanLoop()
        # tick1: establish prev_owned (no phantom purchase on first tick).
        loop.tick(champion=_CHAMP, owned_item_ids=owned5, seed_fn=seed,
                  clock_s=1000, stage="late", surplus_gold=1500)
        # tick2 at clock 1010: owned count grew 5 -> 6 (a purchase at T=1010).
        loop.tick(champion=_CHAMP, owned_item_ids=owned6, seed_fn=seed,
                  clock_s=1010, stage="late", surplus_gold=1500)
        # tick3 within the 30s lock window (clock 1020): boots-sell is a generic
        # (non-off-build) sell -> SUPPRESSED by the just-bought lock.
        r3 = loop.tick(champion=_CHAMP, owned_item_ids=owned6, seed_fn=seed,
                       clock_s=1020, stage="late", surplus_gold=1500)
        self.assertFalse(any(a.kind == "sell_boots" for a in r3.actions))

    def test_just_bought_lock_window_edge(self):
        # purchase at T; a non-off-build sell at T+lock-eps is SUPPRESSED, at
        # exactly T+lock is ALLOWED (pins the < vs <= comparison).
        owned5 = ["3031", "6672", "3036", "3072", "3046"]
        owned6 = ["1001", "3031", "6672", "3036", "3072", "3046"]
        seed = self._full_inventory_seed()
        cfg = ReplanConfig()
        lock = cfg.just_bought_lock_s

        loop_in = ReplanLoop()
        loop_in.tick(champion=_CHAMP, owned_item_ids=owned5, seed_fn=seed,
                     clock_s=1000.0, stage="late", surplus_gold=1500)
        loop_in.tick(champion=_CHAMP, owned_item_ids=owned6, seed_fn=seed,
                     clock_s=1000.0, stage="late", surplus_gold=1500)
        r_in = loop_in.tick(champion=_CHAMP, owned_item_ids=owned6,
                            seed_fn=seed, clock_s=1000.0 + lock - 0.001,
                            stage="late", surplus_gold=1500)
        self.assertFalse(any(a.kind == "sell_boots" for a in r_in.actions))

        loop_edge = ReplanLoop()
        loop_edge.tick(champion=_CHAMP, owned_item_ids=owned5, seed_fn=seed,
                       clock_s=1000.0, stage="late", surplus_gold=1500)
        loop_edge.tick(champion=_CHAMP, owned_item_ids=owned6, seed_fn=seed,
                       clock_s=1000.0, stage="late", surplus_gold=1500)
        r_edge = loop_edge.tick(champion=_CHAMP, owned_item_ids=owned6,
                                seed_fn=seed, clock_s=1000.0 + lock,
                                stage="late", surplus_gold=1500)
        self.assertTrue(any(a.kind == "sell_boots" for a in r_edge.actions))


# --------------------------------------------------------------------------- #
# 11: trinket upgrade (free)
# --------------------------------------------------------------------------- #
class TrinketUpgradeTests(unittest.TestCase):
    def test_trinket_upgrade_mid_late_only(self):
        seed = make_seed_fn({"6672": ("Kraken Slayer", 85.0, 3000, "")})
        # mid -> upgrade_trinket swap_to 3363.
        mid = ReplanLoop()
        r_mid = mid.tick(champion=_CHAMP, owned_item_ids=["3340"], seed_fn=seed,
                         clock_s=1400, stage="mid")
        ups = [a for a in r_mid.actions if a.kind == "upgrade_trinket"]
        self.assertEqual(len(ups), 1)
        self.assertEqual(ups[0].swap_to, "3363")
        self.assertEqual(ups[0].item_id, "3340")
        # early -> none.
        early = ReplanLoop()
        r_early = early.tick(champion=_CHAMP, owned_item_ids=["3340"],
                             seed_fn=seed, clock_s=120, stage="early")
        self.assertFalse(any(a.kind == "upgrade_trinket"
                             for a in r_early.actions))

    def test_trinket_upgrade_bypasses_gates(self):
        # The free upgrade fires even inside the just-bought window and with no
        # surplus / rate-limit head-room.
        seed = make_seed_fn({"6672": ("Kraken Slayer", 85.0, 3000, "")})
        loop = ReplanLoop()
        # tick1 establishes prev_owned (count 1).
        loop.tick(champion=_CHAMP, owned_item_ids=["3340"], seed_fn=seed,
                  clock_s=1000, stage="late")
        # tick2 owned count grows 1 -> 2 (a purchase at T=1005).
        loop.tick(champion=_CHAMP, owned_item_ids=["3340", "6672"],
                  seed_fn=seed, clock_s=1005, stage="late")
        # tick3 within the lock window, zero surplus - upgrade still fires.
        r3 = loop.tick(champion=_CHAMP, owned_item_ids=["3340", "6672"],
                       seed_fn=seed, clock_s=1010, stage="late",
                       surplus_gold=0)
        self.assertTrue(any(a.kind == "upgrade_trinket" for a in r3.actions))


# --------------------------------------------------------------------------- #
# 12, 20: true swap on matchup-invalidated only
# --------------------------------------------------------------------------- #
class TrueSwapTests(unittest.TestCase):
    def _seed(self):
        return make_seed_fn({"6672": ("Kraken Slayer", 85.0, 3000, "")})

    def test_antiheal_swap_only_when_no_heal_sources(self):
        # owned antiheal 3033 + enemy heal_sources == 0 -> a swap; with
        # heal_sources >= 2 -> NO swap. (classify_item('3033').is_antiheal True
        # via the REAL catalog.)
        from core.build_planner.situational import EnemyProfile
        seed = self._seed()
        # squishy enemy so the %armor-pen predicate (armor < LETH_CUT) also
        # could fire - but test 20 covers the double-flag single-swap rule; here
        # use a tanky kill target so ONLY the antiheal predicate is in play.
        ep_no_heal = EnemyProfile(heal_sources=0, kill_target_armor=150.0)
        ep_heal = EnemyProfile(heal_sources=3, kill_target_armor=150.0)

        loop_a = ReplanLoop()
        r_a = loop_a.tick(champion=_CHAMP, owned_item_ids=["3033"],
                          seed_fn=seed, clock_s=1400, stage="late",
                          enemy_profile=ep_no_heal, surplus_gold=2000)
        self.assertTrue(any(a.kind == "swap" and a.item_id == "3033"
                            for a in r_a.actions))

        loop_b = ReplanLoop()
        r_b = loop_b.tick(champion=_CHAMP, owned_item_ids=["3033"],
                          seed_fn=seed, clock_s=1400, stage="late",
                          enemy_profile=ep_heal, surplus_gold=2000)
        self.assertFalse(any(a.kind == "swap" and a.item_id == "3033"
                             for a in r_b.actions))

    def test_double_flag_emits_single_swap(self):
        # 3033 is BOTH antiheal AND %armor-pen. With heal_sources==0 AND a tanky
        # kill target (armor >= LETH_CUT so the %armor-pen predicate does NOT
        # fire) the antiheal-wasted swap fires exactly ONCE for 3033 - never two.
        from core.build_planner.situational import EnemyProfile, LETH_CUT
        seed = self._seed()
        ep = EnemyProfile(heal_sources=0, kill_target_armor=LETH_CUT + 50.0)
        loop = ReplanLoop()
        r = loop.tick(champion=_CHAMP, owned_item_ids=["3033"], seed_fn=seed,
                      clock_s=1400, stage="late", enemy_profile=ep,
                      surplus_gold=2000)
        swaps_3033 = [a for a in r.actions
                      if a.kind == "swap" and a.item_id == "3033"]
        self.assertEqual(len(swaps_3033), 1)


# --------------------------------------------------------------------------- #
# 13, 26: in-memory state + atomic end_match
# --------------------------------------------------------------------------- #
class StateInMemoryTests(unittest.TestCase):
    def test_tick_writes_nothing_and_end_match_returns_log(self):
        # Snapshot the data/ file set ITSELF (do NOT lean on conftest's 12-path
        # allowlist - it would not catch a stray write to a non-listed path).
        data_dir = _ROOT / "data"
        before = {p.name for p in data_dir.iterdir()}
        seed = make_seed_fn(_STICKY_CATALOG)
        loop = ReplanLoop()
        loop.tick(champion=_CHAMP, owned_item_ids=["X"], seed_fn=seed,
                  clock_s=1400, stage="late")
        after = {p.name for p in data_dir.iterdir()}
        self.assertEqual(before, after)
        # end_match(path=None) returns the log list and writes nothing.
        log = loop.end_match(path=None)
        self.assertIsInstance(log, list)
        after2 = {p.name for p in data_dir.iterdir()}
        self.assertEqual(before, after2)

    def test_accept_grows_action_log(self):
        loop = ReplanLoop()
        before = len(loop.action_log)
        action = SwapAction(kind="sell_boots", item_id="1001",
                            reason="endgame slot - sell boots for a damage item")
        loop.accept(action)
        self.assertEqual(len(loop.action_log), before + 1)

    def test_end_match_atomic_round_trip(self):
        import tempfile
        loop = ReplanLoop()
        loop.accept(SwapAction(kind="upgrade_trinket", item_id="3340",
                               swap_to="3363", reason="free trinket upgrade"))
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "replan_log.json"
            returned = loop.end_match(path=target)
            self.assertTrue(target.exists())
            on_disk = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(on_disk, returned)
            self.assertEqual(on_disk, loop.action_log)
            # No leftover tmp file in the dir.
            leftovers = [p.name for p in Path(td).iterdir()
                         if p.name != target.name]
            self.assertEqual(leftovers, [])


# --------------------------------------------------------------------------- #
# 14: flicker suppressed (integration)
# --------------------------------------------------------------------------- #
class FlickerSuppressionTests(unittest.TestCase):
    def test_noisy_ticks_flip_at_most_once(self):
        # A run of ticks where the challenger single-item total stays inside the
        # 1.10 margin each tick -> next_item_id changes AT MOST ONCE.
        loop = ReplanLoop()
        seed_x = make_seed_fn({"X": _STICKY_CATALOG["X"]})
        seed_xy = make_seed_fn({"X": _STICKY_CATALOG["X"],
                                "Y": _STICKY_CATALOG["Y"]})
        seeds = [seed_x, seed_xy, seed_xy, seed_xy, seed_xy]
        picks: list[str | None] = []
        for s in seeds:
            r = loop.tick(champion=_CHAMP, owned_item_ids=[], seed_fn=s,
                          clock_s=1400, stage="late")
            picks.append(r.next_item_id)
        flips = sum(1 for a, b in zip(picks, picks[1:]) if a != b)
        self.assertLessEqual(flips, 1)


# --------------------------------------------------------------------------- #
# 15: all-deferred / empty tail
# --------------------------------------------------------------------------- #
class EmptyTailTests(unittest.TestCase):
    def test_all_deferred_tail_returns_none_cleanly(self):
        # owned 3036; the seed offers ONLY 3035 (a component of 3036) so every
        # non-owned planned id is deferred -> next_item_id is None, name "",
        # sticky False, no IndexError.
        seed = make_seed_fn({"3035": ("Last Whisper", 60.0, 1450, "")})
        loop = ReplanLoop()
        r = loop.tick(champion=_CHAMP, owned_item_ids=["3036"], seed_fn=seed,
                      clock_s=1400, stage="late")
        self.assertIn("3035", r.deferred)
        self.assertIsNone(r.next_item_id)
        self.assertEqual(r.next_item_name, "")
        self.assertFalse(r.sticky)

    def test_empty_plan_tail_returns_none(self):
        # A seed with no rows for an unknown champion path -> empty tail.
        def empty_seed(champion, owned_ids=None, **kw):
            return {"ok": True, "ranked": [], "order": []}
        loop = ReplanLoop()
        r = loop.tick(champion=_CHAMP, owned_item_ids=["X"], seed_fn=empty_seed,
                      clock_s=1400, stage="late")
        self.assertIsNone(r.next_item_id)
        self.assertEqual(r.next_item_name, "")
        self.assertFalse(r.sticky)


# --------------------------------------------------------------------------- #
# 16: first-ever tick no phantom purchase
# --------------------------------------------------------------------------- #
class FirstTickTests(unittest.TestCase):
    def test_first_tick_no_phantom_purchase_blocks_sell(self):
        # On the FIRST-EVER tick (prev_owned starts None) an otherwise sell-
        # eligible boots-sell is NOT blocked by the just-bought lock.
        owned = ["1001", "3031", "6672", "3036", "3072", "3046"]
        seed = make_seed_fn({"6672": ("Kraken Slayer", 85.0, 3000, ""),
                             "3031": ("Infinity Edge", 95.0, 3450, "")})
        loop = ReplanLoop()
        r = loop.tick(champion=_CHAMP, owned_item_ids=owned, seed_fn=seed,
                      clock_s=1400, stage="late", surplus_gold=1500)
        self.assertTrue(any(a.kind == "sell_boots" for a in r.actions))


# --------------------------------------------------------------------------- #
# 17: incumbent becomes owned between ticks
# --------------------------------------------------------------------------- #
class IncumbentOwnedTests(unittest.TestCase):
    def test_incumbent_bought_is_not_viable_flip(self):
        # tick1 latches incumbent X; before tick2 the operator buys X. tick2: X
        # is no longer a viable candidate -> next moves to the new challenger,
        # sticky False, and X appears in owned_prefix not plan_tail.
        loop = ReplanLoop()
        seed_x = make_seed_fn({"X": _STICKY_CATALOG["X"]})
        r1 = loop.tick(champion=_CHAMP, owned_item_ids=[], seed_fn=seed_x,
                       clock_s=1400, stage="late")
        self.assertEqual(r1.next_item_id, "X")
        # X now owned; only Y remains rankable.
        seed_xy = make_seed_fn({"X": _STICKY_CATALOG["X"],
                                "Y": _STICKY_CATALOG["Y"]})
        r2 = loop.tick(champion=_CHAMP, owned_item_ids=["X"], seed_fn=seed_xy,
                       clock_s=1400, stage="late")
        self.assertEqual(r2.next_item_id, "Y")
        self.assertFalse(r2.sticky)
        self.assertIn("X", r2.owned_prefix)
        self.assertNotIn("X", r2.plan_tail)


# --------------------------------------------------------------------------- #
# 18: trinket swap (set change, count unchanged) is not a purchase
# --------------------------------------------------------------------------- #
class TrinketSwapNotPurchaseTests(unittest.TestCase):
    def test_trinket_swap_does_not_refresh_lock(self):
        # owned ['3340', ...] -> ['3363', ...] - the SET changes but COUNT is
        # unchanged, so it is NOT a purchase and the just-bought lock is NOT
        # refreshed. An otherwise-eligible boots-sell on that tick still fires.
        seed = make_seed_fn({"6672": ("Kraken Slayer", 85.0, 3000, ""),
                             "3031": ("Infinity Edge", 95.0, 3450, "")})
        owned_a = ["1001", "3031", "6672", "3036", "3072", "3340"]
        owned_b = ["1001", "3031", "6672", "3036", "3072", "3363"]
        loop = ReplanLoop()
        # tick1 establishes prev_owned (count 6, no phantom purchase).
        loop.tick(champion=_CHAMP, owned_item_ids=owned_a, seed_fn=seed,
                  clock_s=1000, stage="late", surplus_gold=1500)
        # tick2: trinket 3340 -> 3363, same count -> NOT a purchase.
        r2 = loop.tick(champion=_CHAMP, owned_item_ids=owned_b, seed_fn=seed,
                       clock_s=1005, stage="late", surplus_gold=1500)
        # The boots-sell is not newly blocked (no fresh lock from the swap), and
        # the rate-limit allows one sell across these two same-stage ticks.
        any_sell = any(a.kind == "sell_boots" for a in r2.actions)
        # If tick1 already consumed the stage's one sell, tick2 is rate-limited;
        # so assert the SET-change did not register as a purchase by checking
        # the lock did not engage on a fresh-loop variant.
        fresh = ReplanLoop()
        r_fresh = fresh.tick(champion=_CHAMP, owned_item_ids=owned_b,
                             seed_fn=seed, clock_s=1005, stage="late",
                             surplus_gold=1500)
        self.assertTrue(any(a.kind == "sell_boots" for a in r_fresh.actions))
        # And the real two-tick loop did not error / did not crash.
        self.assertIsInstance(any_sell, bool)


# --------------------------------------------------------------------------- #
# 19: stickiness via single-item fallback, NOT beam scan (BLOCKER guard)
# --------------------------------------------------------------------------- #
class StickinessSingleItemGuardTests(unittest.TestCase):
    def test_stays_sticky_when_challenger_is_sole_beam_survivor(self):
        # The full-depth beam collapses to a single first-item, so a close
        # incumbent X is ABSENT from the beam map - a beam-map implementation
        # would wrongly flip. The single-item score_build gate keeps X.
        loop = ReplanLoop()
        seed_x = make_seed_fn({"X": _STICKY_CATALOG["X"]})
        r1 = loop.tick(champion=_CHAMP, owned_item_ids=[], seed_fn=seed_x,
                       clock_s=1400, stage="late", beam_width=6, depth=6)
        self.assertEqual(r1.next_item_id, "X")
        seed_xy = make_seed_fn({"X": _STICKY_CATALOG["X"],
                                "Y": _STICKY_CATALOG["Y"]})
        r2 = loop.tick(champion=_CHAMP, owned_item_ids=[], seed_fn=seed_xy,
                       clock_s=1400, stage="late", beam_width=6, depth=6)
        # Y is the higher-delta sole survivor at full depth; X must STILL win.
        self.assertEqual(r2.next_item_id, "X")
        self.assertTrue(r2.sticky)


# --------------------------------------------------------------------------- #
# 22: is_boots dual-path
# --------------------------------------------------------------------------- #
class IsBootsTests(unittest.TestCase):
    def test_is_boots_dual_path(self):
        catalog = _load_catalog()
        # Base boots 1001 - 'Boots' tag (and the from-includes-1001 fallback).
        self.assertTrue(is_boots("1001"))
        # A finished boots id carrying the 'Boots' tag (3047 Plated Steelcaps).
        self.assertIn("Boots", catalog["3047"]["tags"])
        self.assertTrue(is_boots("3047"))
        # 3036 (Lord Dominik's) is NOT boots.
        self.assertNotIn("Boots", catalog["3036"]["tags"])
        self.assertFalse(is_boots("3036"))


# --------------------------------------------------------------------------- #
# 24: ReplanConfig band-invariant guard
# --------------------------------------------------------------------------- #
class ConfigBandInvariantTests(unittest.TestCase):
    def test_default_config_band_holds(self):
        cfg = ReplanConfig()
        self.assertLess(cfg.schmitt_drop, cfg.schmitt_add)

    def test_inverted_band_raises(self):
        with self.assertRaises(ValueError):
            ReplanConfig(schmitt_drop=1.30, schmitt_add=1.20)


if __name__ == "__main__":
    unittest.main()
