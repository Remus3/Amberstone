"""RM-2126 (s172): Daemon Slayer patch 16.22.1 -> 16.23.1, landed WITH the DDragon refresh.

s170 refreshed the DDragon mirror to 16.23.1 (ad15cedf11) without the DS bump,
and the full ci went red on 172 setup errors in the live-rows guard
(test_enemy_runes_live_text_s144d402: current.txt must equal the newest
vendored DDragon dir); s171 reverted it. This batch lands both together.

Ground truth (measured s172, DDragon 16.23.1 + CDragon 16.23 + lolmath.net
chunks, diffed with tools/ds_patch_diff.py against the 16.22.1 snapshot):

* Items: 699 -> 699, no ``<stats>`` change; one passive-prose move the s170
  DDragon commit did not name: Turbo Chemtank (Arena) 443079 canister heal
  20% -> 16% max HP (CommunityDragon 16.23 PickupHealthGain 0.16; not
  modeled, engine note synced).
* Champions: Azir attackrange 525 -> 550 (the only DDragon stat delta).
* lolmath: Syndra E cooldown 15 flat -> 17 / 16.5 / 16 / 15.5 / 15; Kalista
  ARAM modifiers taken 0.9 -> 1, dealt 1.1 -> 1.05; scenario Azir W onHit
  0.5 -> 0.67. The lolmath parser needed the minified-export enum fix
  (``h.f.ahri``; tools/daemon_slayer_extract.py) to read any scenario at all.
* Mayhem (CDragon 16.23 kiwi.bin): 242 -> 243 rows.

Data reads are pinned to the 16.23.1 snapshot directory, so these stay true
after the next bump; the pointer test only asserts the live patch is at or
past 16.23.1, plus the pairing invariant that broke s170.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.effects import ITEM_EFFECTS

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DS_DATA = _REPO_ROOT / "data" / "daemon_slayer"
_DDRAGON = _REPO_ROOT / "data" / "meta_build" / "ddragon"
_PATCH = "16.23.1"


def _patch_key(patch: str) -> tuple[int, ...]:
    return tuple(int(x) for x in patch.split("."))


def _current_patch() -> str:
    return (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()


def _load_json(name: str) -> dict:
    return json.loads((_DS_DATA / _PATCH / name).read_text(encoding="utf-8"))


class PatchPointer(unittest.TestCase):
    def test_current_patch_at_or_past(self) -> None:
        self.assertGreaterEqual(_patch_key(_current_patch()), _patch_key(_PATCH))

    def test_current_patch_is_the_newest_vendored_ddragon(self) -> None:
        vendored = [p.name for p in _DDRAGON.iterdir()
                    if p.is_dir() and p.name[:1].isdigit()]
        self.assertIn(_PATCH, vendored)
        self.assertEqual(_current_patch(), max(vendored, key=_patch_key))

    def test_engine_version(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.292.0")

    def test_feed_watch_high_water_acked(self) -> None:
        doc = json.loads((_DS_DATA / "ds_feed_watch.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(doc["changelog_high_water"], "2026-11-19")


class SnapshotDeltas(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.champs = _load_json("champions.json")["data"]

    def test_azir_attackrange(self) -> None:
        self.assertEqual(self.champs["Azir"]["stats"]["attackrange"], 550)

    def test_item_roster_unchanged(self) -> None:
        items = _load_json("items.json")
        self.assertEqual(len(items.get("data", items)), 699)

    def test_turbo_chemtank_arena_heal_16(self) -> None:
        items = _load_json("items.json")
        desc = items.get("data", items)["443079"]["description"]
        self.assertIn("16% max Health", desc)
        self.assertIn("16% max HP", ITEM_EFFECTS["443079"].note)

    def test_syndra_e_cooldown(self) -> None:
        cd = self.champs["Syndra"]["lolmath"]["cooldowns"]["E"]
        self.assertEqual(cd[:5], [17, 16.5, 16, 15.5, 15])

    def test_kalista_aram(self) -> None:
        mods = self.champs["Kalista"]["lolmath"]["aram_modifiers"]
        self.assertEqual((mods["aramDamageTaken"], mods["aramDamageDealt"]), (1, 1.05))


class LolmathScenarios(unittest.TestCase):
    """The minified-export enum fix: every scenario parsed, keys are strings."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = _load_json("scenarios.json")

    def test_full_roster(self) -> None:
        self.assertEqual(len(self.doc["byDDragonId"]), 173)
        self.assertEqual(len(self.doc["byLolmathKey"]), 173)

    def test_champion_keys_are_the_enum_leaf(self) -> None:
        for key, recs in self.doc["byLolmathKey"].items():
            self.assertEqual(recs[0]["settings"]["championKey"], key)

    def test_damage_types_resolved(self) -> None:
        q = self.doc["byDDragonId"]["Ahri"][0]["settings"]["abilities"]["Q"]
        self.assertIn(q["damageType"], {"magical", "true", "physical", "mixed"})
        self.assertIn(q["targetType"], {"multi", "single"})

    def test_azir_w_onhit(self) -> None:
        w = self.doc["byDDragonId"]["Azir"][0]["settings"]["abilities"]["W"]
        self.assertEqual(w["onHit"], 0.67)

    def test_manifest_counts(self) -> None:
        counts = _load_json("manifest.json")["lolmath_counts"]
        self.assertEqual(counts["scenarios"], 173)
        self.assertEqual(counts["lane_positions"], 5)


class MayhemAugments(unittest.TestCase):
    def test_header(self) -> None:
        doc = _load_json("mayhem_augments.json")
        self.assertEqual(doc["rc_patch"], _PATCH)
        self.assertEqual(doc["cdragon_patch"], "16.23")
        self.assertEqual(doc["count"], 243)


if __name__ == "__main__":
    unittest.main()
