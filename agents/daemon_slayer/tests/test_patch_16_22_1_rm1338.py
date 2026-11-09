"""RM-1338 (s156): Daemon Slayer patch 16.21.1 -> 16.22.1 and the lolmath 26.21 changelog.

Red first: every class below except ``LolmathSharedBugGuards`` fails on the
16.21.1 snapshot and passes once the 16.22.1 refresh lands.

Ground truth (measured s156, DDragon 16.22.1 + CDragon 16.22 kiwi.bin +
lolmath.net chunks, scratch extract diffed with tools/ds_patch_diff.py):

* Items (DDragon prose wins, RM-808 - Meraki is frozen at 25.15): Overlord's
  Bloodmail 2501 AD 30 -> 40 and Retribution "up to 12%" -> "up to 10%";
  Doran's Bow 1086 AD 8 -> 7.
* Champions: Mel hp 630 -> 590, hpperlevel 99 -> 107, mp 480 -> 455,
  mpperlevel 28 -> 38, armorperlevel 5.2 -> 5.4, attackdamage 54 -> 52,
  attackspeedperlevel 2.5 -> 2.75; Thresh attackdamage 56 -> 54; Viktor
  hpperlevel 100 -> 105.
* lolmath cooldowns: Kayle Q 12..8 -> 10..8, R 160/120/80 -> 140/110/80; Mel
  W 38..26 -> 30..24, R 120/100/80 -> 120/90/60; Zaahen Q 10..6 -> 8..6.
* lolmath ARAM table is non-neutral again and equals the carried 16.20.1 block
  for all 173 champions, so the RM-766 carry ends (its own "Reverses if:").
* Mayhem (CDragon 16.22 kiwi.bin): the lolmath 10-28 / 11-02 augment fixes
  (Mercy's Strike +300 range / +75% AS, Mind to Matter cap 99999, Upgrade
  Stormsurge 10% max HP + 0.02% per AP, Draw Your Sword melee range 200) are
  the values the game data already carries; Adamant (1327) and Void Dash
  (2097) are gone from the bin, matching lolmath's 10-23 removal.

The lolmath engine fixes of 11-04 ("restore scenario ult values after Back To
Basics", "reset item stats before the no-items baseline") were runtime state
leaks in lolmath's own calculator. DS does not model Back To Basics and builds
every compute_dps from scratch, so the bug is NOT shared; the guards below pin
that (they pass today and must keep passing).
"""
from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps, total_missing_hp_bonus_ad
from agents.daemon_slayer.effects import ITEM_EFFECTS
from agents.daemon_slayer.rank import (
    RANGED_ONLY_ITEM_IDS,
    _champion_is_melee,
    rank_items,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DS_DATA = _REPO_ROOT / "data" / "daemon_slayer"
_PATCH = "16.22.1"


def _current_patch() -> str:
    return (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()


def _load_json(name: str) -> dict:
    return json.loads((_DS_DATA / _current_patch() / name).read_text(encoding="utf-8"))


def _items() -> dict:
    doc = _load_json("items.json")
    return doc.get("data", doc)


class PatchPointer(unittest.TestCase):
    def test_current_patch(self) -> None:
        self.assertEqual(_current_patch(), _PATCH)

    def test_engine_version(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.291.0")

    def test_feed_watch_high_water_acked(self) -> None:
        doc = json.loads((_DS_DATA / "ds_feed_watch.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(doc["changelog_high_water"], "2026-11-04")


class ItemDeltas(unittest.TestCase):
    def test_bloodmail_flat_ad_40(self) -> None:
        self.assertEqual(_items()["2501"]["stats"]["FlatPhysicalDamageMod"], 40)

    def test_dorans_bow_flat_ad_7(self) -> None:
        self.assertEqual(_items()["1086"]["stats"]["FlatPhysicalDamageMod"], 7)

    def test_bloodmail_retribution_prose_10(self) -> None:
        m = re.search(r"Retribution</passive><br>Gain up to (\d+)% increased",
                      _items()["2501"]["description"])
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), 10)

    def test_registry_matches_ddragon_prose(self) -> None:
        # RM-808: live DDragon prose is the authority for the Retribution cap.
        m = re.search(r"Retribution</passive><br>Gain up to (\d+)% increased",
                      _items()["2501"]["description"])
        self.assertIsNotNone(m)
        self.assertAlmostEqual(
            ITEM_EFFECTS["2501"].missing_hp_ad_amp_max_pct, int(m.group(1)) / 100.0)

    def test_retribution_magnitude(self) -> None:
        # 0.10 max * (0.35 / 0.70) realized * 200 total AD = 10.0.
        self.assertAlmostEqual(
            total_missing_hp_bonus_ad(["2501"], 200.0, assume_caster_lowhp=True), 10.0)

    def test_arena_bloodmail_unchanged(self) -> None:
        # The 16.22 change is SR-only: Arena 447111 still reads 17.5%.
        self.assertIn("17.5% increased AD", _items()["447111"]["description"])
        self.assertAlmostEqual(ITEM_EFFECTS["447111"].missing_hp_ad_amp_max_pct, 0.175)

    def test_notes_match_patch(self) -> None:
        self.assertIn("0-10% of total AD", ITEM_EFFECTS["2501"].note)
        note = ITEM_EFFECTS["1086"].note
        self.assertIn("7 AD", note)
        self.assertNotIn("12 AD", note)

    def test_bloodmail_resolves_40_more_ad_than_naked(self) -> None:
        snap = DataSnapshot.load()
        naked = compute_dps(snap, "Garen", 11, item_ids=[])
        with_bm = compute_dps(snap, "Garen", 11, item_ids=["2501"])
        bonus_hp = with_bm.stats["hp"] - naked.stats["hp"]
        self.assertAlmostEqual(
            with_bm.stats["ad"] - naked.stats["ad"], 40.0 + 0.025 * bonus_hp, places=4)


class ChampionDeltas(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.champs = _load_json("champions.json")["data"]

    def test_mel_stats(self) -> None:
        s = self.champs["Mel"]["stats"]
        self.assertEqual(
            (s["hp"], s["hpperlevel"], s["mp"], s["mpperlevel"], s["armorperlevel"],
             s["attackdamage"], s["attackspeedperlevel"]),
            (590, 107, 455, 38, 5.4, 52, 2.75))

    def test_thresh_viktor_stats(self) -> None:
        self.assertEqual(self.champs["Thresh"]["stats"]["attackdamage"], 54)
        self.assertEqual(self.champs["Viktor"]["stats"]["hpperlevel"], 105)

    def test_lolmath_cooldowns(self) -> None:
        cd = {k: self.champs[k]["lolmath"]["cooldowns"] for k in ("Kayle", "Mel", "Zaahen")}
        self.assertEqual(cd["Kayle"]["Q"][:5], [10, 9.5, 9, 8.5, 8])
        self.assertEqual(cd["Kayle"]["R"][:3], [140, 110, 80])
        self.assertEqual(cd["Mel"]["W"][:5], [30, 28.5, 27, 25.5, 24])
        self.assertEqual(cd["Mel"]["R"][:3], [120, 90, 60])
        self.assertEqual(cd["Zaahen"]["Q"][:5], [8, 7.5, 7, 6.5, 6])

    def test_aram_carry_ended_with_non_neutral_table(self) -> None:
        manifest = _load_json("manifest.json")
        self.assertFalse(manifest.get("aram_modifiers_carry"))
        non_neutral = 0
        for rec in self.champs.values():
            mods = (rec.get("lolmath") or {}).get("aram_modifiers") or {}
            if any(float(v) != (0.0 if k == "aramAbilityHaste" else 1.0)
                   for k, v in mods.items()):
                non_neutral += 1
        self.assertGreaterEqual(non_neutral, 100)


class MayhemAugments(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = _load_json("mayhem_augments.json")
        cls.rows = cls.doc["augments"]

    def _value(self, aug_id: str, name: str) -> float:
        for v in self.rows[aug_id]["values"]:
            if v["name"] == name:
                return v["per_rank"][0]
        raise AssertionError(f"{aug_id} has no {name}")

    def test_header(self) -> None:
        self.assertEqual(self.doc["rc_patch"], _PATCH)
        self.assertEqual(self.doc["cdragon_patch"], "16.22")

    def test_lolmath_fixed_augments_match_game_data(self) -> None:
        self.assertEqual(self._value("2133", "AttackRangeInc"), 300.0)
        self.assertAlmostEqual(self._value("2133", "ASBonus"), 0.75)
        self.assertEqual(self._value("1056", "ConvertCap"), 99999.0)
        self.assertAlmostEqual(self._value("3150", "PercentHealthBase"), 0.10, places=6)
        self.assertAlmostEqual(self._value("3150", "PercentHealthPerAP"), 0.0002, places=8)
        self.assertEqual(self._value("1134", "MeleeAttackRange"), 200.0)

    def test_disabled_augments_gone(self) -> None:
        for gone in ("1327", "2097"):  # Adamant, Void Dash
            self.assertNotIn(gone, self.rows)

    def test_16_22_value_changes(self) -> None:
        self.assertEqual(self._value("1001", "Stacks_Max"), 7.0)
        self.assertEqual(self._value("1375", "HealthGainPerStack"), 30.0)
        self.assertEqual(self._value("3081", "UpgradeArmorPenFlat"), 20.0)


class LolmathSharedBugGuards(unittest.TestCase):
    """lolmath 11-04 fixed two state leaks; DS must stay free of both."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_no_items_baseline_does_not_leak(self) -> None:
        before = compute_dps(self.snap, "Jinx", 13, item_ids=[]).weighted_dps
        compute_dps(self.snap, "Jinx", 13, item_ids=["3031", "3094", "3036", "3072"],
                    target_armor=100.0, target_max_hp=2500.0, target_bonus_hp=1200.0)
        after = compute_dps(self.snap, "Jinx", 13, item_ids=[]).weighted_dps
        self.assertGreater(before, 0.0)
        self.assertEqual(before, after)

    def test_rank_does_not_mutate_scenarios_or_items(self) -> None:
        champ = "Jinx"
        scen = copy.deepcopy(self.snap.scenarios_by_id.get(champ))
        rec = copy.deepcopy(self.snap.champions[champ])
        items = copy.deepcopy(self.snap.items)
        rank_items(self.snap, champ, 13, current_item_ids=["3031", "3094"],
                   target_armor=100.0, target_mr=60.0, target_max_hp=2500.0,
                   target_bonus_hp=1200.0)
        self.assertEqual(self.snap.scenarios_by_id.get(champ), scen)
        self.assertEqual(self.snap.champions[champ], rec)
        self.assertEqual(self.snap.items, items)

    def test_draw_your_sword_still_melee_conversion(self) -> None:
        # lolmath 11-02 "Draw Your Sword = melee, Runaan's rejected": DS has
        # done this since 16.13.1 (rank._MELEE_CONVERSION_AUGMENT_IDS); pin the
        # live arena row still says so at the current patch.
        desc = self.snap.arena_augments_by_id[134].get("desc", "")
        self.assertIn("You are now melee", desc)
        self.assertTrue(_champion_is_melee(self.snap.champions["Jinx"], [134]))
        self.assertFalse(_champion_is_melee(self.snap.champions["Jinx"], None))
        self.assertIn("3085", RANGED_ONLY_ITEM_IDS)


if __name__ == "__main__":
    unittest.main()
