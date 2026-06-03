"""Guards for the item 277 real curated Zaahen loadout.

Zaahen (key 904, ddragon Fighter/Assassin) previously carried an all-Doran's
PLACEHOLDER primary ("ap-burst" / "Burst", AP) - the unresolved autogen stub.
Item 277 (tools/hotfix_zaahen_loadout_item277.py) rebuilt sr-collapsed +
aram-collapsed into coherent AD Bruiser-primary + Assassin paths (Kayn model);
arena-collapsed (already real) is left untouched. Zaahen has no DS ability
data so this is tag-driven hand-curation, not enemy-comp autogen.

Pins: entry preserved (172 champs), no all-Doran placeholder remains, the
2 AD paths per SR/ARAM exist + labeled + 6 items + clash-free, Arena untouched,
the hotfix is idempotent, ASCII-clean.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOADOUTS = ROOT / "data" / "champion_loadouts.json"
TOOL = ROOT / "tools" / "hotfix_zaahen_loadout_item277.py"

# Items that, as a whole-path set, mark the unresolved autogen stub.
_STUB_ITEMS = {
    "Doran's Shield", "Doran's Blade", "Doran's Ring", "Doran's Bow",
    "Cull", "Mercury's Treads", "Plated Steelcaps",
}


def _load() -> dict:
    return json.loads(LOADOUTS.read_text(encoding="utf-8"))


def _zaahen(data: dict) -> dict:
    return data["champions"]["Zaahen"]


def _paths(data: dict, variant_key: str) -> list:
    return _zaahen(data)["variants"][variant_key].get("build_paths", [])


class ZaahenPresentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = _load()

    def test_zaahen_present(self) -> None:
        self.assertIn("Zaahen", self.data["champions"])

    def test_champion_count_172(self) -> None:
        self.assertEqual(len(self.data["champions"]), 172)


class NoPlaceholderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = _load()

    def test_no_all_stub_path_remains(self) -> None:
        for vk, var in _zaahen(self.data)["variants"].items():
            for p in var.get("build_paths", []):
                items = p.get("items", [])
                self.assertTrue(items, f"{vk}/{p.get('key')}: empty items")
                all_stub = all(i in _STUB_ITEMS for i in items)
                self.assertFalse(
                    all_stub,
                    f"{vk}/{p.get('key')} is still an all-Doran's/boots stub: {items}",
                )

    def test_no_burst_ap_primary(self) -> None:
        # The old placeholder primary was labeled "Burst" (AP) - wrong for a
        # Fighter/Assassin. Primaries are now Bruiser.
        for vk in ("sr-collapsed", "aram-collapsed"):
            prim = next((p for p in _paths(self.data, vk) if p.get("_is_primary")), None)
            self.assertIsNotNone(prim, f"{vk}: no primary path")
            self.assertNotEqual(prim.get("label"), "Burst")
            self.assertEqual(prim.get("label"), "Bruiser")


class CuratedPathsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = _load()

    def test_sr_two_ad_paths(self) -> None:
        labels = [p.get("label") for p in _paths(self.data, "sr-collapsed")]
        self.assertEqual(labels, ["Bruiser", "Assassin"])

    def test_aram_two_ad_paths(self) -> None:
        labels = [p.get("label") for p in _paths(self.data, "aram-collapsed")]
        self.assertEqual(labels, ["Bruiser", "Assassin"])

    def test_all_curated_paths_have_6_items(self) -> None:
        for vk in ("sr-collapsed", "aram-collapsed"):
            for p in _paths(self.data, vk):
                self.assertEqual(len(p.get("items", [])), 6,
                                 f"{vk}/{p.get('key')} not 6 items")

    def test_ad_identity_not_ap(self) -> None:
        # Fighter/Assassin = AD. Black Cleaver in bruiser, Eclipse in assassin;
        # no AP mythic (Rabadon's / Liandry's / Nashor's) anywhere.
        ap_markers = {"Rabadon's Deathcap", "Liandry's Torment", "Nashor's Tooth",
                      "Shadowflame", "Void Staff", "Lich Bane"}
        for vk in ("sr-collapsed", "aram-collapsed"):
            allitems = [i for p in _paths(self.data, vk) for i in p.get("items", [])]
            self.assertFalse(ap_markers & set(allitems),
                             f"{vk} carries AP items on an AD Fighter/Assassin: "
                             f"{ap_markers & set(allitems)}")
            self.assertIn("Black Cleaver", allitems)
            self.assertIn("Eclipse", allitems)

    def test_primary_runes_are_conqueror(self) -> None:
        for vk in ("sr-collapsed", "aram-collapsed"):
            prim = next(p for p in _paths(self.data, vk) if p.get("_is_primary"))
            self.assertEqual(prim.get("runes", {}).get("keystone"), "Conqueror")


class ArenaUntouchedTests(unittest.TestCase):
    """Arena was already real (non-placeholder) - the hotfix must not rebuild
    it into the sr/aram shape; it keeps its original arena-bruiser items."""

    def setUp(self) -> None:
        self.data = _load()

    def test_arena_keeps_void_immolation_bruiser(self) -> None:
        prim = next((p for p in _paths(self.data, "arena-collapsed")
                     if p.get("_is_primary")), None)
        self.assertIsNotNone(prim)
        self.assertIn("Void Immolation", prim.get("items", []),
                      "arena-collapsed primary should keep its original real items")


class IdempotencyTests(unittest.TestCase):
    def test_apply_is_idempotent(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("zhotfix277", TOOL)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        data = _load()
        # Already applied on disk -> apply() over the loaded data is a no-op.
        self.assertEqual(mod.apply(data), 0,
                         "hotfix should be a no-op on already-curated data")


class AsciiHygieneTests(unittest.TestCase):
    def _scan(self, p: Path) -> list:
        return [(i, b) for i, b in enumerate(p.read_bytes()) if b > 0x7F]

    def test_tool_is_ascii(self) -> None:
        self.assertEqual(self._scan(TOOL), [])

    def test_this_file_is_ascii(self) -> None:
        self.assertEqual(self._scan(Path(__file__)), [])


if __name__ == "__main__":
    unittest.main()
