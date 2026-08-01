"""RM-41 - kit-axis-aware off-class exclusion in the burst (assassin) ranker.

The ``ds.burst`` scorer ranks every purchasable, mode-legal item by raw
burst-damage delta. For a PURE-AP assassin that surfaces AD spellblade /
on-hit / crit items on the ability-empowered auto - measured on the live
engine at 1.239.0, Akali's top-12 carried Essence Reaver, Trinity Force,
Blade of The Ruined King and Infinity Edge, burying her dominant first-item
Hextech Gunblade below all four. The mirror defect (RM-35) puts dead AP items
in an AD burst champ's list.

The DEFAULT-OFF ``exclude_off_axis_items`` seam strips candidates whose
OFFENSIVE stat block is entirely on the champion's off axis. Contract:

* DEFAULT-OFF is byte-identical - omitting the flag equals passing False.
* The gate is DATA-DRIVEN, not a champion list: the axis comes from the
  snapshot's own ``lolmath.damage_distribution`` and a champion without a
  decisive split (Shaco) is a no-op even when the flag is ON.
* Only items carrying off-axis offense AND no on-axis offense are stripped.
  Hybrid items (Hextech Gunblade: 80 AP + 40 AD) and pure-defensive /
  utility items survive on both axes.

Assertions are membership / partition invariants and computed quantities,
not fragile absolute cross-item rank pins.
"""
from __future__ import annotations

import json
import unittest
from urllib.request import Request, urlopen

from agents.daemon_slayer._burst_off_axis import (
    champion_burst_axis,
    is_off_axis_candidate,
)
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.burst import rank_items_by_burst
from agents.daemon_slayer.data_loader import DataSnapshot

_LEVEL = 13
# Sweep-standard squishy target (memory reference_ds_probe_zero_target_defaults:
# the route defaults are all 0.0 and a zero-HP target nullifies %max-HP effects).
_TARGET = dict(
    target_armor=30.0, target_mr=30.0,
    target_max_hp=1900.0, target_bonus_hp=800.0,
)

# The AP-assassin cohort routed to ds.burst (core/archetype_picks._AP_ASSASSIN_IDS).
_AP_ASSASSINS = ("Akali", "Diana", "Ekko", "Evelynn", "Fizz", "Katarina", "Leblanc")

# Pure-AD items measured polluting the AP cohort's list at 1.239.0.
_PURE_AD_IDS = {
    "3078",   # Trinity Force        333 HP / 36 AD / 30% AS
    "3508",   # Essence Reaver       25% crit / 50 AD
    "3153",   # Blade of The Ruined King
    "3031",   # Infinity Edge
    "3036",   # Lord Dominik's Regards
    "6610",   # Sundered Sky
    "6692",   # Eclipse
    "3072",   # Bloodthirster
}
# Pure-AP items an AD burst champ should not be sold (the RM-35 mirror).
_PURE_AP_IDS = {"3089", "4645", "3135", "3137"}  # Rabadon's / Shadowflame / Void Staff / Cryptbloom
_GUNBLADE = "3146"  # 80 AP + 40 AD - hybrid, must survive on BOTH axes


def _snap() -> DataSnapshot:
    reset_default_cache()
    return DataSnapshot.load()


def _ids(res) -> list[str]:
    return [r.item_id for r in res.ranked]


def _rank(snap, champion: str, *, exclude: bool, top: int = 200) -> list[str]:
    return _ids(rank_items_by_burst(
        snap, champion_id=champion, level=_LEVEL, current_item_ids=[],
        mode="SR", top_n=top, exclude_off_axis_items=exclude, **_TARGET,
    ))


class ChampionAxisGateTests(unittest.TestCase):
    """The axis gate is read from the snapshot, not from a curated roster."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_ap_assassin_cohort_resolves_ap(self) -> None:
        for champ in _AP_ASSASSINS:
            with self.subTest(champ=champ):
                rec = self.snap.champion(champ)
                self.assertEqual(champion_burst_axis(rec), "ap")

    def test_ad_assassin_fences_resolve_ad(self) -> None:
        # The standing AD-assassin fence set - these must never take the AP branch.
        for champ in ("Zed", "Talon", "Qiyana", "Khazix", "Naafiri", "Pyke", "Rengar"):
            with self.subTest(champ=champ):
                rec = self.snap.champion(champ)
                self.assertEqual(champion_burst_axis(rec), "ad")

    def test_indecisive_split_is_none(self) -> None:
        # Shaco is 0.521 magical / 0.347 physical - dominant but inside the
        # margin, so he has NO decisive axis and must never be stripped.
        self.assertIsNone(champion_burst_axis(self.snap.champion("Shaco")))

    def test_missing_or_malformed_record_is_none(self) -> None:
        for rec in (None, {}, {"lolmath": {}}, {"lolmath": {"damage_distribution": {}}},
                    {"lolmath": {"damage_distribution": {"magical": "x"}}}):
            with self.subTest(rec=rec):
                self.assertIsNone(champion_burst_axis(rec))


class OffAxisItemPredicateTests(unittest.TestCase):
    """Only items whose OFFENSE is entirely off-axis are stripped."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _rec(self, item_id: str) -> dict:
        return self.snap.items[item_id]

    def test_pure_ad_items_are_off_axis_for_an_ap_champ(self) -> None:
        for item_id in sorted(_PURE_AD_IDS):
            with self.subTest(item=item_id):
                self.assertTrue(is_off_axis_candidate(self._rec(item_id), "ap"))
                self.assertFalse(is_off_axis_candidate(self._rec(item_id), "ad"))

    def test_pure_ap_items_are_off_axis_for_an_ad_champ(self) -> None:
        for item_id in sorted(_PURE_AP_IDS):
            with self.subTest(item=item_id):
                self.assertTrue(is_off_axis_candidate(self._rec(item_id), "ad"))
                self.assertFalse(is_off_axis_candidate(self._rec(item_id), "ap"))

    def test_hybrid_item_survives_both_axes(self) -> None:
        rec = self._rec(_GUNBLADE)
        self.assertFalse(is_off_axis_candidate(rec, "ap"))
        self.assertFalse(is_off_axis_candidate(rec, "ad"))

    def test_defensive_and_utility_items_survive_both_axes(self) -> None:
        # No offensive stat on EITHER axis -> never an off-class strip. The
        # burst scorer already prices these at ~0 delta; excluding them would
        # be a scope creep beyond the pollution this seam targets.
        for item_id in ("3143", "3047", "3006", "3020"):  # Randuin's / Steelcaps / Berserker's / Sorcs
            with self.subTest(item=item_id):
                self.assertFalse(is_off_axis_candidate(self._rec(item_id), "ap"))
                self.assertFalse(is_off_axis_candidate(self._rec(item_id), "ad"))

    def test_none_axis_never_strips(self) -> None:
        for item_id in sorted(_PURE_AD_IDS | _PURE_AP_IDS):
            with self.subTest(item=item_id):
                self.assertFalse(is_off_axis_candidate(self._rec(item_id), None))


class BurstRankerSeamTests(unittest.TestCase):
    """End-to-end through rank_items_by_burst on the live snapshot."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_default_off_is_byte_identical(self) -> None:
        for champ in ("Akali", "Zed"):
            with self.subTest(champ=champ):
                omitted = _ids(rank_items_by_burst(
                    self.snap, champion_id=champ, level=_LEVEL,
                    current_item_ids=[], mode="SR", top_n=200, **_TARGET,
                ))
                explicit_off = _rank(self.snap, champ, exclude=False)
                self.assertEqual(omitted, explicit_off)

    def test_defect_reproduces_with_the_seam_off(self) -> None:
        # Characterization: this is the RM-41 defect, and it must stay visible
        # at the default so a future refactor cannot silently "fix" it here.
        off = _rank(self.snap, "Akali", exclude=False)
        self.assertTrue(_PURE_AD_IDS.intersection(off[:12]),
                        "expected AD pollution in Akali's flag-off top-12")

    def test_ap_cohort_loses_every_pure_ad_item_when_on(self) -> None:
        for champ in _AP_ASSASSINS:
            with self.subTest(champ=champ):
                on = set(_rank(self.snap, champ, exclude=True))
                self.assertEqual(on & _PURE_AD_IDS, set())

    def test_ap_cohort_keeps_its_ap_core_and_the_hybrid(self) -> None:
        for champ in _AP_ASSASSINS:
            with self.subTest(champ=champ):
                on = _rank(self.snap, champ, exclude=True)
                self.assertIn(_GUNBLADE, on)
                self.assertTrue(_PURE_AP_IDS.intersection(on))

    def test_gunblade_climbs_for_akali(self) -> None:
        off = _rank(self.snap, "Akali", exclude=False)
        on = _rank(self.snap, "Akali", exclude=True)
        self.assertLess(on.index(_GUNBLADE), off.index(_GUNBLADE))

    def test_ad_fence_loses_pure_ap_but_keeps_its_ad_core(self) -> None:
        on = set(_rank(self.snap, "Zed", exclude=True))
        self.assertEqual(on & _PURE_AP_IDS, set())
        self.assertTrue(on & _PURE_AD_IDS,
                        "an AD assassin must keep AD items when the seam is ON")

    def test_indecisive_champion_is_a_no_op_when_on(self) -> None:
        self.assertEqual(_rank(self.snap, "Shaco", exclude=False),
                         _rank(self.snap, "Shaco", exclude=True))

    def test_strip_only_removes_rows_it_never_adds_or_reorders(self) -> None:
        # The seam is a candidate STRIP, so the surviving rows must keep their
        # relative model order - it must not reweight anything.
        off = _rank(self.snap, "Akali", exclude=False)
        on = _rank(self.snap, "Akali", exclude=True)
        self.assertEqual(on, [i for i in off if i in set(on)])
        self.assertLess(len(on), len(off))


class RankAssassinRouteTests(unittest.TestCase):
    """The seam is reachable over /rank-assassin, DEFAULT-OFF when omitted."""

    BASE_URL = "http://127.0.0.1:8860"

    @classmethod
    def setUpClass(cls) -> None:
        try:
            urlopen(f"{cls.BASE_URL}/health", timeout=2).read()
        except Exception as e:  # pragma: no cover - env-dependent
            raise unittest.SkipTest(f"DS server unavailable: {e}")

    def _post(self, path: str, body: dict) -> dict:
        req = Request(
            f"{self.BASE_URL}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        return json.loads(urlopen(req, timeout=20).read())

    def _rank(self, **extra) -> list[str]:
        body = {
            "champion": "Akali", "level": _LEVEL, "items": [], "mode": "SR",
            "top": 200, **_TARGET, **extra,
        }
        return [r["item_id"] for r in self._post("/rank-assassin", body)["ranked"]]

    def test_route_default_matches_explicit_false(self) -> None:
        self.assertEqual(self._rank(), self._rank(exclude_off_axis_items=False))

    def test_route_strips_off_axis_when_on(self) -> None:
        on = set(self._rank(exclude_off_axis_items=True))
        self.assertEqual(on & _PURE_AD_IDS, set())
        self.assertIn(_GUNBLADE, on)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
