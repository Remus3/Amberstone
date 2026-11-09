"""s144 true-audit cycle 262 (S144-T-693): core/comp_coverage.py hardening.

Each class pins one audited weakness. Every class holds at least one test
that was RED against the pre-hardening module (18 of 24 at authoring; the
other 6 are positive / no-regression controls), and each fix was
mutation-checked against the tests named for it.

  F1 a failed champion_abilities.json load was cached for the process
     lifetime (lru_cache on {}), and every profile derived meanwhile was
     frozen in _PROFILE_CACHE without its true / heal / anti_heal / aoe facts.
  F2 a BOM-prefixed champion_abilities.json read as a parse failure (the
     sibling champions.json reader already reads utf-8-sig).
  F3 a junk ability-row shape raised (an int damage_blocks dropped a real
     champion into ``unresolved``) or misread (a string effects_descriptions
     was joined char by char, so its Grievous Wounds wording never matched).
  F4 a missing / junk DDragon info.defense defaulted to 0.0 and ASSERTED
     weak_to_burst from no data.
  F5 a champion with no DS rows at all (Locke and Zaahen, 2026-11-09) was
     ASSERTED weak_to_cc_chain / weak_to_kite / weak_to_dive from absent
     mobility data; weak_to_poke already gated on DS data being present.
  F6 vuln members were the RAW input spelling, so a duplicate pick in two
     spellings made the result depend on pick order.
  F7 ``unresolved`` repeated duplicates and echoed an unbounded junk name.
  F8 a non-string mode_key leaked into the output ("5") and one whose truth
     test raises escaped compute_coverage.
  F9 compute_enemy_coverage swallowed a damage-profile failure without a log.
"""
from __future__ import annotations

import copy
import json
import logging
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from core import aram_comp_verdict as cv
from core import comp_coverage as cc
from core.failed_load_gate import DEFAULT_RETRY_AFTER_S

_PATCH = "99.1.1"


def _fresh() -> None:
    if hasattr(cc, "_reset_cache"):
        cc._reset_cache()
        cc._AB_GATE.retry_after_s = DEFAULT_RETRY_AFTER_S
    else:  # pre-hardening module
        cc._abilities.cache_clear()
        cc._PROFILE_CACHE.clear()


def _open_gate() -> None:
    gate = getattr(cc, "_AB_GATE", None)
    if gate is not None:
        gate.retry_after_s = 0.0


class _Base(unittest.TestCase):

    def setUp(self):
        _fresh()
        self.addCleanup(_fresh)


class _FakeDsDir(_Base):
    """A temp DS data dir holding one champion_abilities.json."""

    def write_doc(self, doc, *, bom=False) -> None:
        raw = json.dumps(doc).encode("utf-8")
        if bom:
            raw = b"\xef\xbb\xbf" + raw
        (self.root / _PATCH).mkdir(parents=True, exist_ok=True)
        (self.root / _PATCH / "champion_abilities.json").write_bytes(raw)

    def setUp(self):
        super().setUp()
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for target, value in (("_DS_DATA_DIR", self.root),
                              ("_resolve_patch", lambda: _PATCH)):
            p = mock.patch.object(cc, target, value)
            p.start()
            self.addCleanup(p.stop)


class FailedAbilityLoadNotCachedTests(_Base):
    """F1."""

    def test_failed_load_recovers_and_profile_is_not_frozen(self):
        self.assertIn("true", cc.champion_profile("Vayne")["cover"])
        _fresh()
        with mock.patch.object(cc, "_resolve_patch", lambda: "0.0.0-missing"):
            degraded = cc.champion_profile("Vayne")
        self.assertIsNotNone(degraded)
        self.assertNotIn("true", degraded["cover"])
        _open_gate()
        self.assertIn("true", cc.champion_profile("Vayne")["cover"])

    def test_failed_load_is_logged_once_per_streak(self):
        with mock.patch.object(cc, "_resolve_patch", lambda: "0.0.0-missing"), \
                self.assertLogs("rc.core.comp_coverage", logging.WARNING) as cm:
            _open_gate()
            cc.champion_profile("Vayne")
            cc.champion_profile("Lux")
        self.assertEqual(len(cm.records), 1)
        self.assertIn("champion_abilities.json", cm.records[0].getMessage())


class BomTests(_FakeDsDir):
    """F2."""

    def test_bom_prefixed_abilities_file_is_read(self):
        self.assertNotIn("true", cc.champion_profile("Malphite")["cover"])
        _fresh()
        self.write_doc({"data": {"Malphite": {"Q": [{"damage_type": "TRUE"}]}}},
                       bom=True)
        self.assertIn("true", cc.champion_profile("Malphite")["cover"])


class JunkAbilityShapeTests(_FakeDsDir):
    """F3."""

    def test_int_damage_blocks_does_not_drop_the_champion(self):
        self.write_doc({"data": {"Malphite": {"Q": [
            {"damage_blocks": 7}, {"damage_type": "TRUE"}]}}})
        prof = cc.champion_profile("Malphite")
        self.assertIsNotNone(prof)
        self.assertIn("true", prof["cover"])
        res = cc.compute_team_coverage(["Malphite"], mode_key="sr")
        self.assertEqual(res["unresolved"], [])
        self.assertEqual(res["n"], 1)

    def test_int_effects_descriptions_does_not_drop_the_champion(self):
        self.write_doc({"data": {"Malphite": {"Q": [
            {"effects_descriptions": 7, "damage_type": "TRUE"}]}}})
        prof = cc.champion_profile("Malphite")
        self.assertIsNotNone(prof)
        self.assertIn("true", prof["cover"])

    def test_string_effects_description_matches_grievous_wounds(self):
        self.write_doc({"data": {"Malphite": {"Q": [
            {"effects_descriptions": "Hits inflict Grievous Wounds."}]}}})
        self.assertIn("anti_heal", cc.champion_profile("Malphite")["cover"])

    def test_list_effects_descriptions_still_matches(self):
        self.write_doc({"data": {"Malphite": {"Q": [
            {"effects_descriptions": ["Hits inflict Grievous Wounds."]}]}}})
        self.assertIn("anti_heal", cc.champion_profile("Malphite")["cover"])

    def test_string_damage_block_attribute_is_not_iterated(self):
        self.write_doc({"data": {"Malphite": {"Q": [
            {"damage_blocks": "true damage"}]}}})
        self.assertNotIn("true", cc.champion_profile("Malphite")["cover"])

    def test_non_dict_data_is_unavailable_not_a_raise(self):
        self.write_doc({"data": ["Malphite"]})
        self.assertIsNotNone(cc.champion_profile("Malphite"))

    def test_deeply_nested_file_is_a_gated_failure(self):
        (self.root / _PATCH).mkdir(parents=True, exist_ok=True)
        (self.root / _PATCH / "champion_abilities.json").write_bytes(
            b"[" * 200_000 + b"]" * 200_000)
        with self.assertLogs("rc.core.comp_coverage", logging.WARNING) as cm:
            self.assertIsNotNone(cc.champion_profile("Malphite"))
            cc.champion_profile("Lux")
        self.assertEqual(len(cm.records), 1)


def _champ(name: str, **overrides) -> dict:
    champ = copy.deepcopy(cv._lookup(name))
    champ.update(overrides)
    return champ


class DefenseRatingTests(_Base):
    """F4. Lux is not frontline; a real rating at or under
    BURST_DEFENSE_MAX (set here to 2) must still assert the vuln."""

    def test_real_low_rating_asserts_burst(self):
        champ = _champ("Lux")
        champ["info"] = dict(champ["info"], defense=2)
        self.assertIn("weak_to_burst", cc._derive(champ)[1])

    def test_missing_or_junk_rating_asserts_nothing(self):
        base = _champ("Lux")
        junk = (None, True, False, "2", float("nan"), float("inf"), -1, 11,
                [], {}, 10 ** 400)
        for bad in junk:
            champ = copy.deepcopy(base)
            champ["info"] = dict(champ["info"], defense=bad)
            self.assertNotIn("weak_to_burst", cc._derive(champ)[1], repr(bad))
        for info in (None, "x", 5, {}):
            champ = copy.deepcopy(base)
            champ["info"] = info
            self.assertNotIn("weak_to_burst", cc._derive(champ)[1], repr(info))


class NoDsDataTests(_Base):
    """F5. A synthetic id carries no DS or ability rows at all."""

    _SYN = "S144T693Synthetic"

    def test_melee_without_ds_data_asserts_no_mobility_vuln(self):
        _cover, vuln = cc._derive(_champ("Zed", id=self._SYN))
        for axis in ("weak_to_cc_chain", "weak_to_kite", "weak_to_dive"):
            self.assertNotIn(axis, vuln)

    def test_ranged_without_ds_data_asserts_no_mobility_vuln(self):
        _cover, vuln = cc._derive(_champ("Xerath", id=self._SYN))
        for axis in ("weak_to_cc_chain", "weak_to_kite", "weak_to_dive"):
            self.assertNotIn(axis, vuln)

    def test_kit_facts_without_ds_data_are_kept(self):
        # Data-backed vulns still read: Xerath's DDragon defense rating.
        _cover, vuln = cc._derive(_champ("Xerath", id=self._SYN))
        self.assertIn("weak_to_burst", vuln)

    def test_real_ds_rows_still_assert_mobility_vulns(self):
        vuln = cc.champion_profile("Xerath")["vuln"]
        self.assertIn("weak_to_dive", vuln)
        self.assertIn("weak_to_cc_chain", vuln)


class CanonicalMembersTests(_Base):
    """F6."""

    def test_members_do_not_depend_on_pick_order(self):
        a = cc.compute_team_coverage(["lux", "Lux", "Xerath"], mode_key="sr")
        b = cc.compute_team_coverage(["Lux", "lux", "Xerath"], mode_key="sr")
        self.assertEqual(a, b)
        dive = {v["axis"]: v["members"] for v in a["vulns"]}["weak_to_dive"]
        self.assertEqual(dive, ["Lux", "Xerath"])

    def test_alias_input_reports_display_name(self):
        res = cc.compute_team_coverage(["MonkeyKing", "Wukong"], mode_key="sr")
        self.assertEqual(res["n"], 1)
        for row in res["vulns"]:
            self.assertEqual(row["members"], ["Wukong"])

    def test_profile_carries_display_name(self):
        self.assertEqual(cc.champion_profile("monkeyking")["name"], "Wukong")


class UnresolvedTests(_Base):
    """F7."""

    def test_duplicates_listed_once(self):
        res = cc.compute_team_coverage(["Foo", "Foo", "Lux"], mode_key="sr")
        self.assertEqual(res["unresolved"], ["Foo"])

    def test_long_name_is_bounded_and_never_looked_up(self):
        long_name = "x" * 10_000
        with mock.patch.object(cc, "_lookup", wraps=cc._lookup) as spy:
            res = cc.compute_team_coverage([long_name], mode_key="sr")
        spy.assert_not_called()
        self.assertEqual(len(res["unresolved"]), 1)
        self.assertLessEqual(len(res["unresolved"][0]), 64)
        self.assertIsNone(cc.champion_profile(long_name))


class _Hostile:
    def __bool__(self):
        raise RuntimeError("truth test")

    def __str__(self):
        raise RuntimeError("str")


class ModeKeyTests(_Base):
    """F8."""

    def test_non_string_mode_key_is_sr(self):
        for bad in (5, 0, 1.5, b"tft", ["tft"], _Hostile()):
            self.assertEqual(cc.cover_axes_for_mode(bad), cc.COVER_AXES, repr(bad))
            res = cc.compute_coverage(["Lux"], ["Jinx"], mode_key=bad)
            self.assertEqual(res["mode_key"], "sr", repr(bad))
            self.assertEqual(res["ours"]["n"], 1)

    def test_mode_key_is_trimmed(self):
        self.assertIsNone(cc.compute_coverage(["Lux"], ["Jinx"], mode_key=" TFT "))
        res = cc.compute_coverage(["Lux"], ["Jinx"], mode_key=" Arena ")
        self.assertEqual(res["mode_key"], "arena")
        self.assertNotIn("waveclear", res["axes"]["cover"])

    def test_blank_mode_key_is_sr(self):
        res = cc.compute_coverage(["Lux"], ["Jinx"], mode_key="   ")
        self.assertEqual(res["mode_key"], "sr")


class EnemyProfileLoggedTests(_Base):
    """F9."""

    def test_damage_profile_failure_is_logged(self):
        with mock.patch("composition_advisor.enemy_damage_profile",
                        side_effect=RuntimeError("boom")), \
                self.assertLogs("rc.core.comp_coverage", logging.DEBUG) as cm:
            res = cc.compute_enemy_coverage(["Lux"], mode_key="sr")
        self.assertIsNone(res["damage_profile"])
        self.assertEqual(res["n"], 1)
        self.assertTrue(any("enemy_damage_profile" in r.getMessage()
                            for r in cm.records))


if __name__ == "__main__":
    unittest.main()
