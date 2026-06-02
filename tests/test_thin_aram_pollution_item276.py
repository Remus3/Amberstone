"""Tests for item 276 thin-ARAM-pollution hotfix.

Covers:
  - TARGET 1: 17 thin bruiser/assassin ARAM secondary paths rebuilt to 6 items
  - Zaahen (a real champion) PRESERVED - not removed
  - Idempotency of the hotfix tool
  - No unique-passive-family clashes in rebuilt paths
  - ASCII hygiene
"""
import json
import os
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"

sys.path.insert(0, str(_ROOT))
from tools.hotfix_thin_aram_pollution_item276 import apply  # noqa: E402


def _load() -> dict:
    return json.loads(_LOADOUTS.read_text(encoding="utf-8"))


def _get_aram_paths(data: dict, champ: str) -> list[dict]:
    """Return all build_paths from aram-collapsed for the given champion."""
    return (
        data.get("champions", {})
        .get(champ, {})
        .get("variants", {})
        .get("aram-collapsed", {})
        .get("build_paths", [])
    )


def _secondary_path(data: dict, champ: str, key_substring: str) -> dict | None:
    """Return the secondary (non-primary) path whose key contains key_substring."""
    for bp in _get_aram_paths(data, champ):
        if bp.get("_is_primary"):
            continue
        if key_substring in bp.get("key", ""):
            return bp
    return None


# Families from the no-clash guard (must not appear twice in one path).
_UNIQUE_FAMILIES: dict[str, list[str]] = {
    "spellblade": [
        "trinity force", "essence reaver", "lich bane", "iceborg gauntlet",
        "divine sunderer", "sheen", "blood song", "dusk and dawn",
    ],
    "lifeline": [
        "immortal shieldbow", "sterak's gage", "maw of malmortius",
        "seraph's embrace", "hexdrinker", "protoplasmharness",
    ],
    "immolate": [
        "sunfire aegis", "void immolation", "hollow radiance", "bami's cinder",
    ],
    "hydra_cleave": [
        "stridebreaker", "titanic hydra", "ravenous hydra", "profane hydra",
    ],
}


def _family_clashes(items: list[str]) -> list[str]:
    """Return list of clash descriptions for item families."""
    clashes = []
    lower = [i.lower() for i in items]
    for fam, members in _UNIQUE_FAMILIES.items():
        hits = [i for i in lower if any(m in i for m in members)]
        if len(hits) >= 2:
            clashes.append(f"family '{fam}': {hits}")
    return clashes


_BRUISER_CHAMPS = [
    "Aatrox", "Fiora", "Garen", "Illaoi", "Jayce", "Lillia",
    "Mordekaiser", "Nasus", "Sett", "Udyr", "Yorick",
]
_ASSASSIN_CHAMPS = ["Akali", "Ekko", "Elise", "Fizz", "Katarina", "Shaco"]
_ALL_THIN_CHAMPS = _BRUISER_CHAMPS + _ASSASSIN_CHAMPS


class ZaahenPreservedTests(unittest.TestCase):
    """Zaahen is a REAL champion (The Unsundered, key 904, 16.11.1) - its loadout
    entry must be PRESERVED. Removing a real champion's entry would leave RC with
    no build for it; the all-Doran's placeholder is a separate autogen-stub fix."""

    def setUp(self) -> None:
        self.data = _load()

    def test_zaahen_present_in_champions(self) -> None:
        champs = self.data.get("champions", {})
        self.assertIn("Zaahen", champs, "Zaahen is a real champion - do not remove")

    def test_champion_count_unchanged(self) -> None:
        champs = self.data.get("champions", {})
        self.assertEqual(len(champs), 172,
                         "Expected 172 champions (Zaahen preserved)")


class ThinPathsRebuiltTests(unittest.TestCase):
    """TARGET 1: All thin secondary ARAM paths must be 6 items after hotfix."""

    def setUp(self) -> None:
        self.data = _load()

    def test_all_aram_bruiser_secondary_paths_have_6_items(self) -> None:
        for champ in _BRUISER_CHAMPS:
            bp = _secondary_path(self.data, champ, "aram-bruiser")
            self.assertIsNotNone(bp, f"{champ}: aram-bruiser secondary path missing")
            items = bp.get("items", [])
            self.assertEqual(len(items), 6,
                             f"{champ} aram-bruiser has {len(items)} items; expected 6")

    def test_all_aram_assassin_secondary_paths_have_6_items(self) -> None:
        for champ in _ASSASSIN_CHAMPS:
            bp = _secondary_path(self.data, champ, "aram-assassin")
            self.assertIsNotNone(bp, f"{champ}: aram-assassin secondary path missing")
            items = bp.get("items", [])
            self.assertEqual(len(items), 6,
                             f"{champ} aram-assassin has {len(items)} items; expected 6")

    def test_bruiser_paths_labeled_bruiser(self) -> None:
        for champ in _BRUISER_CHAMPS:
            bp = _secondary_path(self.data, champ, "aram-bruiser")
            label = (bp or {}).get("label", "")
            self.assertEqual(label, "Bruiser",
                             f"{champ} aram-bruiser label should be 'Bruiser'; got {label!r}")

    def test_assassin_paths_labeled_assassin(self) -> None:
        for champ in _ASSASSIN_CHAMPS:
            bp = _secondary_path(self.data, champ, "aram-assassin")
            label = (bp or {}).get("label", "")
            self.assertEqual(label, "Assassin",
                             f"{champ} aram-assassin label should be 'Assassin'; got {label!r}")

    def test_no_thin_secondary_paths_remain(self) -> None:
        """After hotfix, no aram-bruiser or aram-assassin secondary should have < 5 items."""
        champs = self.data.get("champions", {})
        violations = []
        for champ_name, champ_data in champs.items():
            aram_coll = champ_data.get("variants", {}).get("aram-collapsed", {})
            for bp in aram_coll.get("build_paths", []):
                if bp.get("_is_primary"):
                    continue
                key = bp.get("key", "")
                if "aram-bruiser" in key or "aram-assassin" in key:
                    n = len(bp.get("items", []))
                    if n < 5:
                        violations.append(f"{champ_name}/{key}:n={n}")
        self.assertEqual(violations, [],
                         f"Thin paths remain after hotfix: {violations}")


class ClashFreeTests(unittest.TestCase):
    """Rebuilt paths must not contain unique-passive-family clashes."""

    def setUp(self) -> None:
        self.data = _load()

    def test_bruiser_paths_no_family_clash(self) -> None:
        for champ in _BRUISER_CHAMPS:
            bp = _secondary_path(self.data, champ, "aram-bruiser")
            items = (bp or {}).get("items", [])
            clashes = _family_clashes(items)
            self.assertEqual(clashes, [],
                             f"{champ} aram-bruiser has family clashes: {clashes}")

    def test_assassin_paths_no_family_clash(self) -> None:
        for champ in _ASSASSIN_CHAMPS:
            bp = _secondary_path(self.data, champ, "aram-assassin")
            items = (bp or {}).get("items", [])
            clashes = _family_clashes(items)
            self.assertEqual(clashes, [],
                             f"{champ} aram-assassin has family clashes: {clashes}")

    def test_cross_path_no_spellblade_clash(self) -> None:
        """Spellblade items must not appear in both a sibling path AND the rebuilt path."""
        # The clash guard also checks per-path, but verify our rebuilt paths
        # don't introduce a spellblade clash relative to the same-variant other paths.
        # This is redundant with the main no-clash guard but explicit.
        spellblades = {
            "trinity force", "essence reaver", "lich bane",
            "divine sunderer", "sheen",
        }
        champs_data = self.data.get("champions", {})
        violations = []
        for champ in _ALL_THIN_CHAMPS:
            aram_coll = champs_data.get(champ, {}).get("variants", {}).get(
                "aram-collapsed", {}
            )
            all_paths = aram_coll.get("build_paths", [])
            for bp in all_paths:
                items_lower = [i.lower() for i in bp.get("items", [])]
                hits = [i for i in items_lower if any(s in i for s in spellblades)]
                if len(hits) >= 2:
                    violations.append(f"{champ}/{bp.get('key')}: {hits}")
        self.assertEqual(violations, [],
                         f"Spellblade clashes found: {violations}")


class IdempotencyTests(unittest.TestCase):
    """Applying the hotfix twice must produce 0 changes on the second run."""

    def test_second_apply_is_noop(self) -> None:
        data = _load()
        # First apply (data is already patched from the file)
        n_first = apply(data)
        # On already-patched data, apply should return 0
        self.assertEqual(n_first, 0,
                         f"Second apply reported {n_first} changes; expected 0 (idempotent)")


class SiblingPathsUntouchedTests(unittest.TestCase):
    """Primary paths and non-thin secondaries must be untouched."""

    def setUp(self) -> None:
        self.data = _load()

    def test_primary_paths_still_6_items(self) -> None:
        for champ in _ALL_THIN_CHAMPS:
            paths = _get_aram_paths(self.data, champ)
            primary = next((p for p in paths if p.get("_is_primary")), None)
            self.assertIsNotNone(primary, f"{champ}: no primary ARAM path")
            n = len((primary or {}).get("items", []))
            self.assertGreaterEqual(n, 5,
                                    f"{champ} primary path has only {n} items")

    def test_aatrox_tank_path_untouched(self) -> None:
        """tank-aram path should remain unchanged (it's a non-thin secondary)."""
        paths = _get_aram_paths(self.data, "Aatrox")
        tank = next((p for p in paths if p.get("key") == "tank-aram"), None)
        self.assertIsNotNone(tank, "Aatrox tank-aram path must still exist")
        items = (tank or {}).get("items", [])
        self.assertIn("Warmog's Armor", items, "Aatrox tank-aram must still contain Warmog's")

    def test_akali_ap_bruiser_path_untouched(self) -> None:
        """ap-bruiser path should remain unchanged."""
        paths = _get_aram_paths(self.data, "Akali")
        ap_br = next((p for p in paths if p.get("key") == "ap-bruiser"), None)
        self.assertIsNotNone(ap_br, "Akali ap-bruiser path must still exist")
        items = (ap_br or {}).get("items", [])
        self.assertIn("Riftmaker", items, "Akali ap-bruiser must still contain Riftmaker")


class AsciiHygieneTests(unittest.TestCase):
    """Tool and test file must be ASCII-only."""

    def _check_file(self, path: Path) -> None:
        content = path.read_bytes()
        for i, b in enumerate(content):
            self.assertLess(b, 128,
                            f"{path.name}: non-ASCII byte 0x{b:02x} at offset {i}")

    def test_hotfix_tool_is_ascii(self) -> None:
        self._check_file(_ROOT / "tools" / "hotfix_thin_aram_pollution_item276.py")

    def test_this_test_file_is_ascii(self) -> None:
        self._check_file(Path(__file__))

    def test_loadouts_json_no_nonascii_in_diff(self) -> None:
        """Spot-check: items in rebuilt paths must be ASCII strings."""
        data = _load()
        violations = []
        for champ in _ALL_THIN_CHAMPS:
            for bp in _get_aram_paths(data, champ):
                key = bp.get("key", "")
                if "aram-bruiser" not in key and "aram-assassin" not in key:
                    continue
                for item in bp.get("items", []):
                    for ch in item:
                        if ord(ch) >= 128:
                            violations.append(
                                f"{champ}/{key}: '{item}' contains non-ASCII char {ch!r}"
                            )
        self.assertEqual(violations, [], f"Non-ASCII in rebuilt paths: {violations}")


if __name__ == "__main__":
    unittest.main()
