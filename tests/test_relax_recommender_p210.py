"""P2-10: constraint-relaxing recommender that says what it dropped.

Pins core/build_planner/relax.py (pure, DS-free) and the DS legality adapter
core/build_planner_legality.py:

  * strict query with results -> relaxed == [] (no relaxation)
  * empty strict result -> rung 1 dropped and reported
  * rung 1 insufficient -> rung 2 also dropped, reported IN LADDER ORDER
  * a ladder naming a HARD constraint (or the reserved legality name) is
    refused at the API boundary with ValueError
  * hard constraints alone empty -> empty result, relaxed == [], a reason
  * explain lists per-term contributions that sum to the score
  * deterministic tie-break (equal scores -> ascending key, input-order free)
  * the constraint state string round-trips exactly (both directions)
  * the adapter's legality predicate is the DS rank.py pool filter:
    ``_filter_candidates`` (agents/daemon_slayer/rank.py:730), which applies
    ``_NON_COACHABLE_ITEM_IDS`` (rank.py:200), ``_is_purchasable``
    (rank.py:658), ``_is_ornn_masterwork`` (rank.py:663) and
    ``_is_legal_in_mode`` over ``MODE_MAP_ID`` (rank.py:47, :715);
    ``canonical_mode`` is agents/daemon_slayer/data_loader.py:57.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import ast
import math
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.build_planner.relax import (
    LEGALITY,
    Constraint,
    decode_state,
    encode_state,
    recommend,
)

_ROOT = Path(__file__).resolve().parents[1]

# Candidate "builds": id, gold, a tag, a dps number.
_CANDS = [
    {"id": "a", "gold": 3000, "tag": "ap", "dps": 100.0, "legal": True},
    {"id": "b", "gold": 2500, "tag": "ad", "dps": 120.0, "legal": True},
    {"id": "c", "gold": 2000, "tag": "ad", "dps": 90.0, "legal": True},
    {"id": "d", "gold": 1000, "tag": "tank", "dps": 40.0, "legal": False},
]

_TERMS = {
    "dps": lambda c: c["dps"],
    "thrift": lambda c: -c["gold"] / 100.0,
}


def _legal(c) -> bool:
    return bool(c.get("legal"))


class StrictTests(unittest.TestCase):
    def test_no_relaxation_when_strict_has_results(self):
        cons = [Constraint("budget", "gold", "le", 3000)]
        res = recommend(_CANDS, cons, ["budget"], terms=_TERMS, legal=_legal)
        self.assertEqual(res.relaxed, [])
        self.assertTrue(res.results)
        # illegal 'd' never appears
        self.assertNotIn("d", [s.key for s in res.results])

    def test_hard_illegal_excluded_even_when_best(self):
        terms = {"cheap": lambda c: -c["gold"]}
        res = recommend(_CANDS, [], [], terms=terms, legal=_legal)
        self.assertEqual(res.results[0].key, "c")


class LadderTests(unittest.TestCase):
    def test_empty_triggers_rung_one_and_reports_it(self):
        cons = [
            Constraint("budget", "gold", "le", 2100),
            Constraint("ap_only", "tag", "eq", "ap"),
        ]
        # strict: none (c is ad, a costs 3000). Drop ap_only -> c fits.
        res = recommend(_CANDS, cons, ["ap_only", "budget"],
                        terms=_TERMS, legal=_legal)
        self.assertEqual(res.relaxed, ["ap_only"])
        self.assertEqual([s.key for s in res.results], ["c"])
        self.assertIn("ap_only", res.reason)

    def test_rung_two_also_reported_in_order(self):
        cons = [
            Constraint("budget", "gold", "le", 1500),
            Constraint("ap_only", "tag", "eq", "ap"),
        ]
        res = recommend(_CANDS, cons, ["ap_only", "budget"],
                        terms=_TERMS, legal=_legal)
        self.assertEqual(res.relaxed, ["ap_only", "budget"])
        self.assertTrue(res.results)

    def test_ladder_order_is_respected_not_constraint_order(self):
        cons = [
            Constraint("ap_only", "tag", "eq", "ap"),
            Constraint("budget", "gold", "le", 1500),
        ]
        # drop budget first -> 'a' (ap, 3000) fits, ap_only kept
        res = recommend(_CANDS, cons, ["budget", "ap_only"],
                        terms=_TERMS, legal=_legal)
        self.assertEqual(res.relaxed, ["budget"])
        self.assertEqual([s.key for s in res.results], ["a"])

    def test_soft_not_on_ladder_is_never_dropped(self):
        cons = [
            Constraint("budget", "gold", "le", 1500),
            Constraint("ap_only", "tag", "eq", "ap"),
        ]
        res = recommend(_CANDS, cons, ["budget"], terms=_TERMS, legal=_legal)
        # budget dropped -> 'a' satisfies ap_only
        self.assertEqual(res.relaxed, ["budget"])
        self.assertEqual([s.key for s in res.results], ["a"])

    def test_ladder_exhausted_reports_everything_dropped(self):
        cons = [
            Constraint("budget", "gold", "le", 10),
            Constraint("mage", "tag", "eq", "mage"),
        ]
        res = recommend(_CANDS, cons, ["budget"], terms=_TERMS, legal=_legal)
        self.assertEqual(res.results, ())
        self.assertEqual(res.relaxed, ["budget"])
        self.assertIn("exhausted", res.reason)


class HardTests(unittest.TestCase):
    def test_ladder_naming_hard_constraint_refused(self):
        cons = [Constraint("must_ad", "tag", "eq", "ad", hard=True)]
        with self.assertRaises(ValueError):
            recommend(_CANDS, cons, ["must_ad"], terms=_TERMS, legal=_legal)

    def test_ladder_naming_legality_refused(self):
        with self.assertRaises(ValueError):
            recommend(_CANDS, [], [LEGALITY], terms=_TERMS, legal=_legal)

    def test_ladder_unknown_name_refused(self):
        with self.assertRaises(ValueError):
            recommend(_CANDS, [], ["nope"], terms=_TERMS, legal=_legal)

    def test_hard_alone_empty_returns_empty_with_reason(self):
        cons = [
            Constraint("must_tank", "tag", "eq", "tank", hard=True),
            Constraint("budget", "gold", "le", 10),
        ]
        # only tank is 'd', which is illegal -> hard set alone is empty
        res = recommend(_CANDS, cons, ["budget"], terms=_TERMS, legal=_legal)
        self.assertEqual(res.results, ())
        self.assertEqual(res.relaxed, [])
        self.assertIn("hard", res.reason)

    def test_hard_declared_constraint_holds_after_relaxing(self):
        cons = [
            Constraint("must_ad", "tag", "eq", "ad", hard=True),
            Constraint("budget", "gold", "le", 100),
        ]
        res = recommend(_CANDS, cons, ["budget"], terms=_TERMS, legal=_legal)
        self.assertEqual(res.relaxed, ["budget"])
        self.assertEqual(sorted(s.key for s in res.results), ["b", "c"])

    def test_constraint_cannot_use_reserved_legality_name(self):
        with self.assertRaises(ValueError):
            Constraint(LEGALITY, "gold", "le", 1)


class ExplainTests(unittest.TestCase):
    def test_contributions_sum_to_score(self):
        res = recommend(_CANDS, [], [], terms=_TERMS,
                        weights={"dps": 2.0, "thrift": 0.5}, legal=_legal)
        for s in res.results:
            self.assertTrue(math.isclose(sum(dict(s.contributions).values()),
                                         s.score, abs_tol=1e-9))
        win = res.results[0]
        self.assertEqual(res.explain["winner"], win.key)
        self.assertEqual(set(res.explain["terms"]), {"dps", "thrift"})
        self.assertTrue(math.isclose(sum(res.explain["terms"].values()),
                                     res.explain["score"], abs_tol=1e-9))
        # weighted: b = 2*120 + 0.5*(-25) = 227.5
        self.assertEqual(win.key, "b")
        self.assertTrue(math.isclose(win.score, 227.5))
        self.assertEqual(res.explain["runner_up"], res.results[1].key)
        margins = res.explain["margin_by_term"]
        self.assertTrue(math.isclose(sum(margins.values()),
                                     res.explain["margin"], abs_tol=1e-9))

    def test_unknown_weight_refused(self):
        with self.assertRaises(ValueError):
            recommend(_CANDS, [], [], terms=_TERMS, weights={"zzz": 1.0})


class TieBreakTests(unittest.TestCase):
    def test_equal_scores_break_by_key_regardless_of_input_order(self):
        cands = [{"id": k, "v": 1.0} for k in ("z", "m", "a", "q")]
        terms = {"v": lambda c: c["v"]}
        r1 = recommend(cands, [], [], terms=terms, top_n=10)
        r2 = recommend(list(reversed(cands)), [], [], terms=terms, top_n=10)
        self.assertEqual([s.key for s in r1.results], ["a", "m", "q", "z"])
        self.assertEqual([s.key for s in r1.results],
                         [s.key for s in r2.results])

    def test_top_n_bounds_results(self):
        res = recommend(_CANDS, [], [], terms=_TERMS, legal=_legal, top_n=2)
        self.assertEqual(len(res.results), 2)


class StateStringTests(unittest.TestCase):
    _CONS = (
        Constraint("budget", "gold", "le", 2500),
        Constraint("tags", "tag", "in", ["ad", "ap"]),
        Constraint("must_ad", "tag", "eq", "ad", hard=True),
        Constraint("ratio", "dps", "ge", 0.5),
    )

    def test_round_trip_object_to_string_to_object(self):
        s = encode_state(self._CONS, ["budget", "tags"])
        cons, ladder = decode_state(s)
        self.assertEqual(cons, self._CONS)
        self.assertEqual(ladder, ("budget", "tags"))

    def test_round_trip_string_is_stable(self):
        s = encode_state(self._CONS, ["budget"])
        self.assertEqual(encode_state(*decode_state(s)), s)
        self.assertEqual(encode_state(self._CONS, ["budget"]), s)

    def test_state_is_urlsafe_ascii(self):
        s = encode_state(self._CONS, ["budget"])
        self.assertTrue(s.isascii())
        for ch in "+/= ":
            self.assertNotIn(ch, s)

    def test_garbage_state_refused(self):
        with self.assertRaises(ValueError):
            decode_state("!!not-a-state!!")

    def test_state_with_hard_on_ladder_refused(self):
        with self.assertRaises(ValueError):
            encode_state(self._CONS, ["must_ad"])


class StructuralGuardTests(unittest.TestCase):
    def test_relax_does_not_import_ds_engine(self):
        # build_planner reaches DS only through injected callables (the
        # split-brain guard mirrored in tests/test_planner_beam_search.py).
        src = _ROOT / "core" / "build_planner" / "relax.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertFalse(
                    (node.module or "").startswith("agents.daemon_slayer"))
            elif isinstance(node, ast.Import):
                for n in node.names:
                    self.assertFalse(n.name.startswith("agents.daemon_slayer"))


def _item(gold=1000, purchasable=True, maps=None, name=None, desc=""):
    return {
        "name": name or f"item{gold}",
        "gold": {"total": gold, "purchasable": purchasable},
        "maps": maps if maps is not None else {"11": True, "12": True},
        "description": desc,
        "into": [],
    }


class LegalityAdapterTests(unittest.TestCase):
    def setUp(self):
        from core.build_planner_legality import item_legality
        self.item_legality = item_legality
        self.snap = SimpleNamespace(items={
            "1001": _item(1001, name="sr_aram"),
            "1002": _item(1002, maps={"11": True, "12": False}, name="sr_only"),
            "1003": _item(1003, purchasable=False, name="unbuyable"),
            "994403": _item(1004, name="spatula"),
            "1005": _item(1005, name="ornn", desc="x <ornnBonus> y"),
        })

    def test_mode_legality_from_rank(self):
        legal = self.item_legality(self.snap, "aram")
        self.assertTrue(legal({"item_id": "1001"}))
        self.assertFalse(legal({"item_id": "1002"}))
        legal_sr = self.item_legality(self.snap, "SR")
        self.assertTrue(legal_sr({"item_id": "1002"}))

    def test_denies_unbuyable_noncoachable_ornn_and_unknown(self):
        legal = self.item_legality(self.snap, "SR")
        for iid in ("1003", "994403", "1005", "9999999"):
            self.assertFalse(legal({"item_id": iid}), iid)

    def test_combination_needs_every_item_legal(self):
        legal = self.item_legality(self.snap, "ARAM")
        self.assertTrue(legal({"item_ids": ["1001"]}))
        self.assertFalse(legal({"item_ids": ["1001", "1002"]}))
        self.assertFalse(legal({"item_ids": []}))
        self.assertFalse(legal({}))

    def test_adapter_drives_recommend_hard_constraint(self):
        legal = self.item_legality(self.snap, "ARAM")
        cands = [{"id": i, "item_id": i, "g": int(i)} for i in self.snap.items]
        res = recommend(cands, [Constraint("cheap", "g", "le", 1)], ["cheap"],
                        terms={"g": lambda c: c["g"]}, legal=legal, top_n=10)
        self.assertEqual([s.key for s in res.results], ["1001"])
        self.assertEqual(res.relaxed, ["cheap"])


if __name__ == "__main__":
    unittest.main()
