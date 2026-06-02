"""Item 269 - sibling build-data pollution fix characterization + post-conditions.

RED before tools/hotfix_sibling_pollution_item269.py runs (the live data still
carries the mislabeled / thin paths), GREEN after. The test imports the hotfix
tables so it asserts exactly the fixed state the tool produces - no drift.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import tools.hotfix_sibling_pollution_item269 as hf  # noqa: E402

_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"

# Known flat-AP items appearing in the fixed AP sets (verified vs the DS catalog).
_AP_ITEMS = {
    "Rabadon's Deathcap", "Nashor's Tooth", "Void Staff", "Zhonya's Hourglass",
    "Riftmaker", "Cosmic Drive", "Liandry's Torment", "Shadowflame",
    "Hextech Rocketbelt", "Spirit Visage", "Archangel's Staff", "Lich Bane",
}


def _load():
    return json.loads(_LOADOUTS.read_text(encoding="utf-8"))["champions"]


def _paths(champs, champ, vk):
    return champs.get(champ, {}).get("variants", {}).get(vk, {}).get("build_paths", [])


class FixedPathsTests(unittest.TestCase):
    def setUp(self):
        self.champs = _load()

    def test_ap_ad_corki_paths_match_fixed_state(self):
        for (champ, vk, _old), (new_key, label, items) in {
            **hf._AP, **hf._AD, **hf._CORKI,
        }.items():
            match = [p for p in _paths(self.champs, champ, vk) if p.get("key") == new_key]
            self.assertTrue(match, f"{champ} {vk} {new_key} not found")
            bp = match[0]
            self.assertEqual(bp["items"], items, f"{champ} {vk} {new_key} items")
            self.assertEqual(bp["label"], label, f"{champ} {vk} {new_key} label")

    def test_ap_labeled_paths_carry_real_ap(self):
        for (champ, vk, _old), (new_key, label, _items) in {**hf._AP, **hf._CORKI}.items():
            if "AP" not in label:
                continue
            bp = [p for p in _paths(self.champs, champ, vk) if p.get("key") == new_key][0]
            n_ap = sum(1 for it in bp["items"] if it in _AP_ITEMS)
            self.assertGreaterEqual(n_ap, 3, f"{champ} {vk} {new_key} only {n_ap} AP items")

    def test_mage_mislabel_gone_on_ad_champs(self):
        for champ in ("Jhin", "Smolder", "Kha'Zix", "Qiyana", "Talon", "Zed"):
            keys = [p.get("key") for p in _paths(self.champs, champ, "sr-collapsed")]
            self.assertNotIn("sr-mage", keys, f"{champ} still has sr-mage")

    def test_removed_assassins_keep_lethality(self):
        for champ, vk, _key in hf._REMOVE:
            keys = [p.get("key") for p in _paths(self.champs, champ, vk)]
            self.assertIn("lethality", keys, f"{champ} lost its lethality path")

    def test_thin_aram_carry_extended(self):
        for champ, items in hf._ARAM_CARRY.items():
            bp = [p for p in _paths(self.champs, champ, "aram-collapsed")
                  if p.get("key") == "aram-carry"]
            self.assertTrue(bp, f"{champ} aram-carry missing")
            self.assertGreaterEqual(len(bp[0]["items"]), 6, f"{champ} aram-carry thin")
            self.assertEqual(bp[0]["items"], items, f"{champ} aram-carry items")

    def test_variant_primary_items_resynced(self):
        # When a fixed path is the variant primary, the variant-level items mirror it.
        for (champ, vk, _old), (new_key, _label, items) in {**hf._AP}.items():
            var = self.champs.get(champ, {}).get("variants", {}).get(vk, {})
            paths = var.get("build_paths", [])
            prim = next((p for p in paths if p.get("_is_primary")), None)
            if prim and prim.get("key") == new_key:
                self.assertEqual(var.get("items"), items, f"{champ} {vk} variant items stale")


class AsciiHygieneTests(unittest.TestCase):
    def test_tool_is_ascii(self):
        raw = Path(hf.__file__).read_bytes()
        self.assertEqual(raw.decode("ascii", "strict"), raw.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
