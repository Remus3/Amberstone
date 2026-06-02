"""Drift guard for item-263 loadout fix: Kai'Sa ARAM rebuild + Ashe SR ADC paths.

Carry from the 2026-06-02 live-watch note (DEFERRED, data-only):

  (1) Kai'Sa ``aram-collapsed`` carried an ``ap-hybrid`` path labeled
      "AP Hybrid" whose items were all AD (Bloodthirster / Lord
      Dominik's / Axiom Arc - 0 AP, only 4 items), plus a
      ``bruiser-trinity`` path labeled "Trinity" that carried no Trinity
      Force. Both are item-167 coverage-gap auto-seed junk.
  (2) Ashe ``sr-collapsed`` carried a thin 2-path set, one of which was
      ``sr-enchanter`` (Echoes of Helia / Ardent Censer / Staff of
      Flowing Water / Redemption / Moonstone) - a full enchanter build
      on a ranged ADC.

This test locks the post-fix invariants. Re-run
``tools/hotfix_kaisa_aram_ashe_sr_item263.py`` if any assertion trips.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"

# Real AP item NAMES (a build labeled AP must carry >= 2 of these).
_AP_ITEMS = {
    "rabadon's deathcap",
    "void staff",
    "shadowflame",
    "nashor's tooth",
    "hubris",
    "riftmaker",
    "luden's companion",
    "liandry's torment",
    "cryptbloom",
    "zhonya's hourglass",
    "lich bane",
    "horizon focus",
    "stormsurge",
    "malignance",
    "morellonomicon",
    "cosmic drive",
    "rod of ages",
    "archangel's staff",
}

# Enchanter / support item NAMES (>= 2 of these on a true ADC = pollution).
_ENCH_ITEMS = {
    "echoes of helia",
    "ardent censer",
    "staff of flowing water",
    "redemption",
    "moonstone renewer",
    "mikael's blessing",
    "imperial mandate",
    "locket of the iron solari",
    "knight's vow",
    "dream maker",
    "solstice sleigh",
}


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _ap_count(items: list) -> int:
    return sum(1 for i in items if _norm(i) in _AP_ITEMS)


def _ench_count(items: list) -> int:
    return sum(1 for i in items if _norm(i) in _ENCH_ITEMS)


class LoadoutFixItem263Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(_LOADOUTS.read_text(encoding="utf-8"))
        cls.champs = cls.data["champions"]

    def _paths(self, champ: str, variant_key: str) -> list:
        v = self.champs[champ]["variants"].get(variant_key)
        self.assertIsNotNone(v, f"{champ} missing variant {variant_key}")
        return v.get("build_paths", [])

    # -- Kai'Sa ARAM --------------------------------------------------

    def test_kaisa_aram_no_mislabeled_ap_path(self) -> None:
        for p in self._paths("Kai'Sa", "aram-collapsed"):
            lab = _norm(p.get("label"))
            key = _norm(p.get("key"))
            if "ap" in lab or "ap" in key:
                self.assertGreaterEqual(
                    _ap_count(p.get("items", [])), 2,
                    f"Kai'Sa ARAM path {key!r} labeled {p.get('label')!r} "
                    f"carries < 2 real AP items: {p.get('items')}",
                )

    def test_kaisa_aram_no_trinity_lie(self) -> None:
        for p in self._paths("Kai'Sa", "aram-collapsed"):
            lab = _norm(p.get("label"))
            key = _norm(p.get("key"))
            if "trinity" in lab or "trinity" in key:
                self.assertIn(
                    "Trinity Force", p.get("items", []),
                    f"Kai'Sa ARAM path {key!r} labeled {p.get('label')!r} "
                    "claims Trinity but has no Trinity Force",
                )

    def test_kaisa_aram_has_three_paths_each_min4(self) -> None:
        paths = self._paths("Kai'Sa", "aram-collapsed")
        self.assertGreaterEqual(len(paths), 3, "Kai'Sa ARAM should keep 3 paths")
        for p in paths:
            self.assertGreaterEqual(
                len(p.get("items", [])), 4,
                f"Kai'Sa ARAM path {p.get('key')!r} thin: {p.get('items')}",
            )

    def test_kaisa_aram_has_a_real_ap_path(self) -> None:
        paths = self._paths("Kai'Sa", "aram-collapsed")
        self.assertTrue(
            any(_ap_count(p.get("items", [])) >= 2 for p in paths),
            "Kai'Sa ARAM should offer one real AP build (>= 2 AP items)",
        )

    # -- Ashe SR ------------------------------------------------------

    def test_ashe_sr_no_enchanter_path(self) -> None:
        for p in self._paths("Ashe", "sr-collapsed"):
            self.assertLess(
                _ench_count(p.get("items", [])), 2,
                f"Ashe SR path {p.get('key')!r} carries enchanter items "
                f"on a ranged ADC: {p.get('items')}",
            )

    def test_ashe_sr_paths_are_adc_coherent(self) -> None:
        paths = self._paths("Ashe", "sr-collapsed")
        self.assertGreaterEqual(len(paths), 2, "Ashe SR should keep >= 2 paths")
        for p in paths:
            items = p.get("items", [])
            self.assertGreaterEqual(
                len(items), 4, f"Ashe SR path {p.get('key')!r} thin: {items}",
            )
            self.assertEqual(
                _ench_count(items), 0,
                f"Ashe SR path {p.get('key')!r} not ADC-coherent: {items}",
            )

    # -- name resolution + hygiene ------------------------------------

    def test_all_fixed_paths_resolve(self) -> None:
        from coaches import loadout_resolver as lr
        for champ, vk in (("Kai'Sa", "aram-collapsed"), ("Ashe", "sr-collapsed")):
            for p in self._paths(champ, vk):
                names = p.get("items", [])
                ids = lr._resolve_item_ids(names)
                bad = [n for n, i in zip(names, ids) if not i]
                self.assertEqual(
                    bad, [], f"{champ} {vk} {p.get('key')!r} unresolved item names: {bad}",
                )

    def test_data_file_ascii(self) -> None:
        raw = _LOADOUTS.read_bytes()
        nonascii = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        self.assertEqual(nonascii, [], "champion_loadouts.json must stay 7-bit ASCII")


if __name__ == "__main__":
    unittest.main()
