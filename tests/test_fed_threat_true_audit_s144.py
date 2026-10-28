"""s144 true-audit (lane 8, cycle 48) - core/build_planner/fed_threat.py.

The C3 fed estimator promises "never raises" and "absent / junk data never
fires a wrong chip". Each class below pins one finding that broke one of
those promises (red against the pre-audit module), plus characterization
tests that valid input is unchanged:

  F1  one junk item id (NaN / inf float, an int past 4300 digits) raised out
      of estimate_player_gold, and inside assess_fed_threat the outer except
      then dropped the WHOLE fed read (another enemy's real lead included).
  F2  a fractional float id was truncated into a real item (3072.9 -> the
      Bloodthirster's 3400 gold). Ids now share core.heal_threat._id_strs.
  F3  a level of inf / 10**400 raised (OverflowError), a fractional level was
      truncated, "1_0" read as 10, and a level of 10**6 forged a 130M-gold
      economy lead. A level outside 1.._MAX_LEVEL is now a missing level (0).
  F4  a negative deaths count inflated the net lead (0 kills / -5 deaths
      read as +5), and a fractional / signed-string / overflowing kills count
      was coerced into a count. A present-but-junk kills or deaths now skips
      the row; an absent one still reads 0 (unchanged).
  F5  a non-str, blank or over-long champion was still named fed (str() of a
      dict became the "champion" field the hint detail prints).
  F6  a catalog gold.total that was NaN / inf / negative / a bool was taken
      as a price (inf made every enemy fed, NaN made none).
  R1  dashboard/routes_build_plan._coerce_enemy_levels and the active-player
      level parse raised OverflowError on a JSON Infinity, so one level
      turned the whole /api/build-plan answer into ok:false.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

import core.build_planner.fed_threat as ft
from dashboard import routes_build_plan
from tests.test_c3_fed_counter_hint import _fed_payload, _hint, _post

_ROOT = Path(__file__).resolve().parent.parent

_BT = "3072"  # Bloodthirster, gold.total 3400 in data/meta/ddragon_items.json
_IE = "3031"  # Infinity Edge


def _scores(k, d, a=0):
    return {"kills": k, "deaths": d, "assists": a}


def _gold(item_id: str) -> float:
    return ft._load_gold_map()[item_id]


class F1JunkItemIdNeverRaisesTests(unittest.TestCase):
    def test_nonfinite_and_huge_ids_never_raise(self):
        for junk in (float("nan"), float("inf"), float("-inf"), 10 ** 5000):
            with self.subTest(junk=type(junk).__name__):
                self.assertEqual(ft.estimate_player_gold([junk, _IE], 0),
                                 _gold(_IE))

    def test_one_junk_id_does_not_drop_another_enemys_lead(self):
        out = ft.assess_fed_threat(
            enemies=["Leona", "Draven"],
            enemy_items_by_player=[[float("nan")], [_IE]],
            enemy_scores=[_scores(6, 0), _scores(7, 1)],
            enemy_levels=[9, 11], my_item_ids=[], my_level=6)
        self.assertIsNotNone(out)
        self.assertEqual(out["champion"], "Draven")

    def test_junk_my_item_id_does_not_drop_the_read(self):
        out = ft.assess_fed_threat(
            enemies=["Draven"], enemy_items_by_player=[[_IE]],
            enemy_scores=[_scores(7, 1)], enemy_levels=[11],
            my_item_ids=[float("inf")], my_level=6)
        self.assertIsNotNone(out)


class F2FractionalIdIsNotARealItemTests(unittest.TestCase):
    def test_fractional_float_id_contributes_nothing(self):
        self.assertEqual(ft.estimate_player_gold([3072.9], 0), 0.0)
        self.assertEqual(ft.estimate_player_gold([3072.5, 3031.0], 0), 0.0)

    def test_junk_string_ids_contribute_nothing(self):
        for junk in ("3072.9", "+3072", "3_072", "\u0663\u0660\u0667\u0662",
                     "-3072", "0", ""):
            with self.subTest(junk=junk):
                self.assertEqual(ft.estimate_player_gold([junk], 0), 0.0)

    def test_valid_ids_unchanged(self):
        want = _gold(_BT) + _gold(_IE)
        for ids in ([_BT, _IE], [3072, 3031], [" 3072 ", 3031]):
            with self.subTest(ids=ids):
                self.assertEqual(ft.estimate_player_gold(ids, 0), want)
        # Two copies of one item are two purchases (unchanged).
        self.assertEqual(ft.estimate_player_gold([_BT, _BT], 0),
                         2 * _gold(_BT))


class F3LevelVocabularyTests(unittest.TestCase):
    def test_overflowing_level_never_raises(self):
        for junk in (float("inf"), float("-inf"), 10 ** 400, float("nan")):
            with self.subTest(junk=repr(junk)[:12]):
                self.assertEqual(ft.estimate_player_gold([], junk), 0.0)

    def test_out_of_range_level_is_missing(self):
        for junk in (10 ** 6, ft._MAX_LEVEL + 1, -3, 0):
            with self.subTest(junk=junk):
                self.assertEqual(ft.estimate_player_gold([], junk), 0.0)

    def test_fractional_or_odd_string_level_is_missing(self):
        for junk in (11.5, "11.5", "1_0", "+5", " ", "\u0661\u0661", True,
                     [11], {"l": 11}):
            with self.subTest(junk=junk):
                self.assertEqual(ft.estimate_player_gold([], junk), 0.0)

    def test_valid_levels_unchanged(self):
        for lv in (1, 11, "11", " 11 ", 11.0, ft._MAX_LEVEL):
            with self.subTest(lv=lv):
                want = ft.LEVEL_GOLD * int(float(str(lv).strip()))
                self.assertEqual(ft.estimate_player_gold([], lv), want)
        self.assertEqual(ft.estimate_player_gold([], None), 0.0)

    def test_huge_enemy_level_cannot_forge_a_lead(self):
        self.assertIsNone(ft.assess_fed_threat(
            enemies=["Draven"], enemy_items_by_player=[[]],
            enemy_scores=[_scores(5, 0)], enemy_levels=[10 ** 6],
            my_item_ids=[], my_level=1))

    def test_one_inf_level_does_not_drop_another_enemys_lead(self):
        out = ft.assess_fed_threat(
            enemies=["Leona", "Draven"],
            enemy_items_by_player=[[], [_IE]],
            enemy_scores=[_scores(6, 0), _scores(7, 1)],
            enemy_levels=[float("inf"), 11], my_item_ids=[], my_level=6)
        self.assertIsNotNone(out)
        self.assertEqual(out["champion"], "Draven")

    def test_inf_my_level_never_raises(self):
        self.assertIsNotNone(ft.assess_fed_threat(
            enemies=["Draven"], enemy_items_by_player=[[_IE]],
            enemy_scores=[_scores(7, 1)], enemy_levels=[11],
            my_item_ids=[], my_level=float("inf")))


class F4ScoreVocabularyTests(unittest.TestCase):
    def _assess(self, row):
        return ft.assess_fed_threat(
            enemies=["Draven"], enemy_items_by_player=[[_IE]],
            enemy_scores=[row], enemy_levels=[11],
            my_item_ids=[], my_level=6)

    def test_negative_deaths_does_not_inflate_the_lead(self):
        self.assertIsNone(self._assess(_scores(0, -5)))
        self.assertIsNone(self._assess(_scores(1, -2)))

    def test_junk_kills_or_deaths_skips_the_row(self):
        for row in (_scores(3.9, 0), _scores("+5", 0), _scores("5_0", 0),
                    _scores(10 ** 400, 0), _scores(float("inf"), 0),
                    _scores(5, float("nan")), _scores(5, "x"),
                    _scores(5, [0]), _scores(-7, -10)):
            with self.subTest(row=repr(row)[:40]):
                self.assertIsNone(self._assess(row))

    def test_over_long_digit_string_never_raises(self):
        # int() raises ValueError past 4300 digits; the digit cap stops it.
        self.assertIsNone(self._assess(_scores("9" * 5000, 0)))
        self.assertEqual(ft.estimate_player_gold([], "9" * 5000), 0.0)

    def test_junk_row_does_not_drop_another_enemys_lead(self):
        out = ft.assess_fed_threat(
            enemies=["Leona", "Draven"],
            enemy_items_by_player=[[_IE], [_IE]],
            enemy_scores=[_scores(5, [0]), _scores(7, 1)],
            enemy_levels=[11, 11], my_item_ids=[], my_level=6)
        self.assertEqual(out["champion"], "Draven")

    def test_valid_scores_unchanged(self):
        for row in (_scores(7, 1), _scores("7", "1"), _scores(7.0, 1.0),
                    _scores(" 7 ", 1)):
            with self.subTest(row=row):
                out = self._assess(row)
                self.assertIsNotNone(out)
                self.assertEqual((out["kills"], out["deaths"]), (7, 1))
        # An ABSENT deaths (or kills) key still reads 0 - unchanged.
        out = self._assess({"kills": 5})
        self.assertEqual((out["kills"], out["deaths"]), (5, 0))
        out = self._assess({"kills": 5, "deaths": None})
        self.assertEqual((out["kills"], out["deaths"]), (5, 0))

    def test_reported_counts_are_ints(self):
        out = self._assess(_scores("7", 1.0))
        self.assertIs(type(out["kills"]), int)
        self.assertIs(type(out["deaths"]), int)


class F5ChampionNameTests(unittest.TestCase):
    def _assess(self, champ):
        return ft.assess_fed_threat(
            enemies=[champ], enemy_items_by_player=[[_IE]],
            enemy_scores=[_scores(7, 1)], enemy_levels=[11],
            my_item_ids=[], my_level=6)

    def test_non_str_blank_or_long_champion_is_never_named_fed(self):
        for junk in ({"a": 1}, ["Draven"], 7, None, True, "", "   ",
                     "D" * (ft._MAX_NAME_LEN + 1)):
            with self.subTest(junk=repr(junk)[:20]):
                self.assertIsNone(self._assess(junk))

    def test_valid_name_is_stripped_and_unchanged(self):
        out = self._assess("  Draven ")
        self.assertEqual(out, {"champion": "Draven", "kills": 7,
                               "deaths": 1, "axis": "ad"})
        self.assertIsNotNone(self._assess("D" * ft._MAX_NAME_LEN))

    def test_junk_name_does_not_shadow_a_real_fed_enemy(self):
        out = ft.assess_fed_threat(
            enemies=[{"a": 1}, "Draven"],
            enemy_items_by_player=[[_IE, _BT], [_IE]],
            enemy_scores=[_scores(12, 0), _scores(7, 1)],
            enemy_levels=[11, 11], my_item_ids=[], my_level=6)
        self.assertEqual(out["champion"], "Draven")


class F6CatalogPriceTests(unittest.TestCase):
    def setUp(self):
        self._saved = (ft._GOLD_MAP, ft._GOLD_MAP_GATE)
        ft._GOLD_MAP = None
        ft._GOLD_MAP_GATE = ft.FailedLoadGate()

    def tearDown(self):
        ft._GOLD_MAP, ft._GOLD_MAP_GATE = self._saved

    def test_nonfinite_negative_or_bool_price_is_skipped(self):
        import tempfile
        body = ('{"data": {"1": {"gold": {"total": NaN}},'
                ' "2": {"gold": {"total": -5}},'
                ' "3": {"gold": {"total": Infinity}},'
                ' "4": {"gold": {"total": true}},'
                ' "5": {"gold": {"total": 300}},'
                ' "6": {"gold": {"total": 0}},'
                ' "7": {"gold": {"total": "450"}},'
                ' "8": {"gold": "junk"}}}')
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "items.json"
            path.write_bytes(body.encode("ascii"))
            with mock.patch.object(ft, "_ITEMS_PATH", path):
                got = ft._load_gold_map()
        self.assertEqual(got, {"5": 300.0, "6": 0.0, "7": 450.0})
        self.assertEqual(ft.estimate_player_gold(["3", "1", "5"], 0), 300.0)

    def test_real_catalog_every_price_finite_and_non_negative(self):
        got = ft._load_gold_map()
        self.assertGreater(len(got), 100)
        self.assertTrue(all(isinstance(v, float) and 0.0 <= v < 1e6
                            for v in got.values()))


class R1RouteLevelNeverRaisesTests(unittest.TestCase):
    def test_coerce_enemy_levels_inf_reads_zero(self):
        # RM-1113: the route passes levels through raw and fed_threat owns
        # the coercion; the junk ones read as a missing level (0) there.
        raw = [float("inf"), 11, float("-inf"), "x"]
        passed = routes_build_plan._coerce_enemy_levels(raw)
        self.assertEqual([ft._level(v) for v in passed], [0, 11, 0, 0])

    def test_inf_enemy_level_keeps_the_plan_ok(self):
        resp = _post(_fed_payload(enemy_levels=[float("inf"), 9]))
        self.assertIs(resp.get("ok"), True)
        self.assertIsInstance(resp.get("counter_hints"), list)

    def test_inf_my_level_keeps_the_plan_ok(self):
        resp = _post(_fed_payload(level=float("inf")))
        self.assertIs(resp.get("ok"), True)

    def test_json_infinity_body_parses_to_inf(self):
        # The POST body reaches the route through json.loads, which accepts
        # the bare Infinity token - so R1 is reachable from the wire.
        self.assertEqual(json.loads('{"l": [Infinity]}')["l"][0], float("inf"))

    def test_valid_route_fed_chip_unchanged(self):
        fed = _hint(_post(_fed_payload()), "fed")
        self.assertIsNotNone(fed)
        self.assertEqual(fed["suggest_class"], "armor")
        self.assertIn("Draven 7/1", fed["detail"])


class AsciiTests(unittest.TestCase):
    def test_touched_files_ascii_lf(self):
        for rel in ("core/build_planner/fed_threat.py",
                    "tests/test_fed_threat_true_audit_s144.py"):
            raw = (_ROOT / rel).read_bytes()
            with self.subTest(rel=rel):
                self.assertTrue(raw.isascii())
                self.assertNotIn(b"\r", raw)


if __name__ == "__main__":
    unittest.main()
