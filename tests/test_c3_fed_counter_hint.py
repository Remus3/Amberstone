"""C3 fed counter-hint tests - core/build_planner/fed_threat.py + the
/api/build-plan wiring (hint-only, mirrors the shipped C2/C6 pattern).

Module half: the fed estimator (combat lead AND estimated-economy lead over
the active player, LEAP-08 formula) + the per-threat damage-axis read.
Route half: the fed/SURVIVE chip on counter_hints[], the axis-directed
enrichment, and the load-bearing invariant that live[]/meta[] stay
BYTE-IDENTICAL with vs without the fed inputs (loop.tick untouched).

Self-contained: copies the tiny _Handler/_post harness from
tests/test_build_plan_contract.py:46-124 so this slice touches no shared test
file. Spec: docs/specs/2026-07-17-ds-c3-fed-counter-hint-design.md.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import core.build_planner.fed_threat as ft
from dashboard import routes_build_plan

_ROOT = Path(__file__).resolve().parent.parent

# Draven info.attack=9 / info.magic=1 -> axis "ad"; Annie 2/10 -> "ap";
# Seraphine is DDragon-zeroed and resolves "ap" ONLY via the
# champion_info_overrides overlay (probed data/meta/ddragon_champions.json
# this session). Item 3031 (Infinity Edge) gold.total 3450 clears
# GOLD_LEAD_CUT (2000) on its own vs an item-less baseline.
_IE = "3031"


def _scores(k, d, a=0):
    return {"kills": k, "deaths": d, "assists": a}


# --------------------------------------------------------------------------- #
# Module half - estimate_player_gold / assess_fed_threat / compute_fed.
# --------------------------------------------------------------------------- #
class EstimateGoldTests(unittest.TestCase):
    def test_additive_decomposition(self):
        # est(items, lvl) == est(items, 0) + LEVEL_GOLD * lvl - the level fold
        # is a pure additive term (no magic-float assertion).
        items = ["1001", "1004"]
        self.assertEqual(
            ft.estimate_player_gold(items, 5),
            ft.estimate_player_gold(items, 0) + 5 * ft.LEVEL_GOLD)
        self.assertGreater(ft.estimate_player_gold(items, 0), 0.0)

    def test_unknown_id_contributes_zero(self):
        base = ft.estimate_player_gold(["1001"], 0)
        self.assertEqual(ft.estimate_player_gold(["1001", "99999999"], 0), base)

    def test_int_ids_accepted(self):
        self.assertEqual(ft.estimate_player_gold([1001], 0),
                         ft.estimate_player_gold(["1001"], 0))

    def test_failsoft_bad_input(self):
        self.assertEqual(ft.estimate_player_gold(None, None), 0.0)
        self.assertEqual(ft.estimate_player_gold("junk", "junk"), 0.0)


class AssessFedThreatTests(unittest.TestCase):
    def _fed_draven(self, **kw):
        """A comp where Draven 7/1 owns an Infinity Edge vs an item-less me -
        clears BOTH cuts (net 6 >= 3; lead 3450 + level-fold >= 2000)."""
        args = dict(
            enemies=["Draven", "Leona"],
            enemy_items_by_player=[[_IE], []],
            enemy_scores=[_scores(7, 1, 2), _scores(1, 3, 8)],
            enemy_levels=[11, 9],
            my_item_ids=[],
            my_level=11,
        )
        args.update(kw)
        return ft.assess_fed_threat(**args)

    def test_fed_fires_and_names_the_threat(self):
        got = self._fed_draven()
        self.assertIsNotNone(got)
        self.assertEqual(got["champion"], "Draven")
        self.assertEqual(got["kills"], 7)
        self.assertEqual(got["deaths"], 1)

    def test_axis_ad(self):
        self.assertEqual(self._fed_draven()["axis"], "ad")

    def test_axis_ap(self):
        got = self._fed_draven(enemies=["Annie", "Leona"])
        self.assertEqual(got["champion"], "Annie")
        self.assertEqual(got["axis"], "ap")

    def test_axis_via_zeroed_info_overlay(self):
        # Seraphine's DDragon info block is all-zero; merged_info restores ap.
        got = self._fed_draven(enemies=["Seraphine", "Leona"])
        self.assertEqual(got["axis"], "ap")

    def test_axis_unknown_champ_blank(self):
        got = self._fed_draven(enemies=["Bogus Champ", "Leona"])
        self.assertIsNotNone(got)
        self.assertEqual(got["axis"], "")

    def test_combat_only_does_not_fire(self):
        # Net kills clear the cut but I own the same item - no economy lead.
        self.assertIsNone(self._fed_draven(my_item_ids=[_IE]))

    def test_economy_only_does_not_fire(self):
        # Big item lead but net kills 2 < KDA_LEAD_CUT - the AND boundary.
        self.assertIsNone(
            self._fed_draven(enemy_scores=[_scores(2, 0), _scores(0, 0)]))

    def test_level_fold_boundary(self):
        # Equal (empty) items: a 17-vs-1 level lead is 16 * 130 = 2080 >= 2000
        # (fires); 16-vs-1 is 1950 (does not) - proves LEVEL_GOLD folds in.
        base = dict(
            enemies=["Draven"], enemy_items_by_player=[[]],
            enemy_scores=[_scores(5, 0)], my_item_ids=[], my_level=1,
        )
        self.assertIsNotNone(
            ft.assess_fed_threat(enemy_levels=[17], **base))
        self.assertIsNone(
            ft.assess_fed_threat(enemy_levels=[16], **base))

    def test_top_fed_enemy_by_net_kills(self):
        got = self._fed_draven(
            enemies=["Draven", "Zed"],
            enemy_items_by_player=[[_IE], [_IE]],
            enemy_scores=[_scores(7, 1), _scores(12, 0)],
            enemy_levels=[11, 11],
        )
        self.assertEqual(got["champion"], "Zed")

    def test_short_or_missing_scores_never_fire(self):
        # A missing scores row reads kills=deaths=0 - the combat gate can
        # never clear without real scoreboard data.
        self.assertIsNone(self._fed_draven(enemy_scores=[]))
        self.assertIsNone(self._fed_draven(enemy_scores=None))

    def test_missing_levels_read_zero_not_guessed(self):
        # With levels absent the enemy reads level 0 (an honest undercount,
        # never an invented level): vs a level-12 me the bare Infinity Edge
        # lead (3450 - 1560 = 1890) no longer clears GOLD_LEAD_CUT.
        self.assertIsNone(self._fed_draven(enemy_levels=None, my_level=12))

    def test_failsoft_junk_inputs(self):
        self.assertIsNone(ft.assess_fed_threat(
            "junk", "junk", "junk", "junk", "junk", "junk"))
        self.assertFalse(ft.compute_fed(None, None, None, None, None, None))

    def test_compute_fed_mirrors_assess(self):
        self.assertTrue(ft.compute_fed(
            ["Draven"], [[_IE]], [_scores(7, 1)], [11], [], 11))


# --------------------------------------------------------------------------- #
# Route half - harness copied from tests/test_build_plan_contract.py:46-124.
# --------------------------------------------------------------------------- #
class _Handler:
    def __init__(self, path: str = "/api/build-plan") -> None:
        self.path = path
        self.status = 0
        self.body = b""
        self.content_type = ""

    def _send(self, status, body, content_type) -> None:
        self.status = status
        self.body = body
        self.content_type = content_type

    def json(self) -> dict:
        return json.loads(self.body.decode())


_FAKE_CATALOG = {
    "3031": ("Infinity Edge", 95.0, 3450, ""),
    "6672": ("Kraken Slayer", 85.0, 3000, ""),
    "3072": ("Bloodthirster", 80.0, 3400, ""),
}

_FAKE_ORDER = [
    {"slot": 1, "item_id": "6672", "item_name": "Kraken Slayer",
     "delta": 85.0, "gold": 3000, "scorer": "dps", "unit": "dps",
     "locked_family": ""},
    {"slot": 2, "item_id": "3031", "item_name": "Infinity Edge",
     "delta": 95.0, "gold": 3450, "scorer": "dps", "unit": "dps",
     "locked_family": ""},
]


def _fake_seed_fn(champion, owned_ids=None, **kw):
    owned = {str(i) for i in (owned_ids or ())}
    ranked = [
        {"item_id": iid, "item_name": name, "delta_dps": delta,
         "gold": gold, "unique_passive_key": fam}
        for iid, (name, delta, gold, fam) in _FAKE_CATALOG.items()
        if iid not in owned
    ]
    ranked.sort(key=lambda r: r["delta_dps"], reverse=True)
    return {
        "ok": True, "ranked": ranked, "order": list(_FAKE_ORDER),
        "scorer": "dps",
        "target_stats": {"target_armor": 80.0, "target_mr": 40.0,
                         "target_max_hp": 2000.0, "target_bonus_hp": 1200.0,
                         "source": "live-items", "n_enemies": 2},
        "threat": {"summary": "AD-heavy", "ad_threat": 8.0, "ap_threat": 2.0},
        "defensive": [],
    }


def _post(payload: dict, seed_fn=_fake_seed_fn) -> dict:
    orig = routes_build_plan._seed_fn_factory
    routes_build_plan._seed_fn_factory = lambda **_kw: seed_fn
    try:
        h = _Handler()
        routes_build_plan._serve_build_plan(h, payload)
        return h.json()
    finally:
        routes_build_plan._seed_fn_factory = orig


def _fed_payload(**kw):
    """A build-plan POST where enemy Draven 7/1 + Infinity Edge is fed vs an
    item-less level-6 me."""
    p = {
        "champion": "Miss Fortune",
        "level": 6,
        "items": [],
        "enemies": ["Draven", "Leona"],
        "enemy_items": [["3031"], []],
        "enemy_scores": [_scores(7, 1, 2), _scores(1, 3, 8)],
        "enemy_levels": [11, 9],
    }
    p.update(kw)
    return p


def _hint(resp: dict, criterion: str):
    for hint in resp.get("counter_hints") or []:
        if hint.get("criterion") == criterion:
            return hint
    return None


class FedRouteContractTests(unittest.TestCase):
    def test_fed_comp_surfaces_axis_directed_survive_chip(self):
        resp = _post(_fed_payload())
        self.assertTrue(resp["ok"])
        fed = _hint(resp, "fed")
        self.assertIsNotNone(fed, "fed comp must surface the fed hint")
        self.assertEqual(fed["label"], "SURVIVE")
        self.assertEqual(fed["severity"], "high")
        self.assertFalse(fed["satisfied"])  # item-less build owns no defense
        # Axis-directed enrichment: Draven is AD -> armor direction, and the
        # detail names the fed threat + scoreline.
        self.assertEqual(fed["suggest_class"], "armor")
        self.assertIn("Draven", fed["detail"])
        self.assertIn("7/1", fed["detail"])
        self.assertIn("armor", fed["detail"])

    def test_fed_ap_threat_directs_mr(self):
        resp = _post(_fed_payload(
            enemies=["Annie", "Leona"],
            enemy_scores=[_scores(9, 2, 1), _scores(1, 3, 8)]))
        fed = _hint(resp, "fed")
        self.assertIsNotNone(fed)
        self.assertEqual(fed["suggest_class"], "mr")
        self.assertIn("Annie", fed["detail"])
        self.assertIn("mr", fed["detail"])

    def test_unknown_axis_keeps_generic_detail(self):
        resp = _post(_fed_payload(enemies=["Bogus Champ", "Leona"]))
        fed = _hint(resp, "fed")
        self.assertIsNotNone(fed)
        # The locked situational text survives untouched when no axis is known.
        self.assertEqual(fed["suggest_class"], "resist")
        self.assertEqual(fed["detail"], "fed enemy - itemize defense")

    def test_no_fed_comp_no_chip(self):
        resp = _post(_fed_payload(
            enemy_scores=[_scores(1, 2, 0), _scores(0, 1, 2)]))
        self.assertIsNone(_hint(resp, "fed"))

    def test_absent_fed_fields_no_chip(self):
        p = _fed_payload()
        p.pop("enemy_scores")
        p.pop("enemy_levels")
        self.assertIsNone(_hint(_post(p), "fed"))

    def test_live_meta_byte_identical_with_vs_without_fed_inputs(self):
        # The load-bearing HINT-ONLY invariant: the DS-scored plan must not
        # move when the fed inputs appear (loop.tick profile untouched).
        with_fed = _post(_fed_payload())
        without = _fed_payload()
        without.pop("enemy_scores")
        without.pop("enemy_levels")
        no_fed = _post(without)
        self.assertTrue(_hint(with_fed, "fed"))
        self.assertEqual(json.dumps(with_fed["live"], sort_keys=True),
                         json.dumps(no_fed["live"], sort_keys=True))
        self.assertEqual(json.dumps(with_fed["meta"], sort_keys=True),
                         json.dumps(no_fed["meta"], sort_keys=True))

    def test_junk_fed_fields_never_raise(self):
        resp = _post(_fed_payload(enemy_scores="garbage",
                                  enemy_levels={"a": 1}))
        self.assertEqual(resp.get("ok"), True)
        self.assertIsInstance(resp.get("counter_hints"), list)
        self.assertIsNone(_hint(resp, "fed"))


# --------------------------------------------------------------------------- #
# ASCII hygiene (repo hard rule) - mirrors tests/test_cc_threat.py:60.
# --------------------------------------------------------------------------- #
class AsciiHygieneTests(unittest.TestCase):
    def _assert_ascii(self, rel: str) -> None:
        raw = (_ROOT / rel).read_bytes()
        nonascii = [b for b in raw if b > 0x7F]
        self.assertEqual(nonascii, [], f"{rel} has {len(nonascii)} non-ASCII bytes")

    def test_module_ascii(self) -> None:
        self._assert_ascii("core/build_planner/fed_threat.py")

    def test_test_file_ascii(self) -> None:
        self._assert_ascii("tests/test_c3_fed_counter_hint.py")

    def test_spec_ascii(self) -> None:
        self._assert_ascii("docs/specs/2026-07-17-ds-c3-fed-counter-hint-design.md")


if __name__ == "__main__":
    unittest.main()
