"""R143 - wielder-HSP mirror-id coverage + Moonstone ally-chain separation.

Two defects this file locks down:

1. ``core/daemon_slayer_resolver.name_to_id`` hands the live coach path MIRROR
   ids (``32xxxx`` for mode="sr", ``22xxxx`` for mode="arena"), which were
   absent from ``enchanter_items.json`` - so ``sum_wielder_hsp_pct`` silently
   contributed 0.0 for every real enchanter item in a live inventory.
   The mirrors are NOT numerically identical to the SR line (Arena Redemption
   is 12% vs SR 10%; ARAM Mikael's is 15% vs SR 12%), so this is an explicit
   per-id truth table parsed from ``items.json``, never a prefix strip.

2. Moonstone Renewer (6617) carries ``heal_shield_amp_pct`` 0.30 which is NOT a
   Heal-and-Shield-Power stat - it is the Starlit Grace CHAIN-TO-ALLY ratio and
   the catalog text excludes the wielder. It must read 0.0 on the wielder-self
   path (``_hsp_amp``) while keeping 0.30 for the ally-throughput path
   (``hps.py``). The ``ally_chain_only`` flag carries that split.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._hsp_amp import sum_wielder_hsp_pct
from agents.daemon_slayer.hps import (
    EnchanterFormulasSnapshot,
    EnchanterItemFormula,
)

# (bare_id, name, sr_pct, mirror32_pct, mirror22_pct)
# Measured from data/daemon_slayer/16.14.1/items.json via the
# "<attention>N%</attention> Heal and Shield Power" stat line.
TRUTH: tuple[tuple[str, str, float, float, float], ...] = (
    ("2526", "Whispering Circlet", 0.08, 0.08, 0.08),
    ("3107", "Redemption", 0.10, 0.10, 0.12),
    ("3109", "Knight's Vow", 0.0, 0.0, 0.0),
    ("3190", "Locket of the Iron Solari", 0.0, 0.0, 0.0),
    ("3222", "Mikael's Blessing", 0.12, 0.15, 0.12),
    ("3504", "Ardent Censer", 0.10, 0.10, 0.12),
    ("4005", "Imperial Mandate", 0.0, 0.0, 0.0),
    ("6616", "Staff of Flowing Water", 0.10, 0.10, 0.14),
    ("6620", "Echoes of Helia", 0.0, 0.0, 0.0),
    ("6621", "Dawncore", 0.16, 0.20, 0.12),
)

# Forbidden Idol has NO mode mirror in the catalog - bare id only.
BARE_ONLY: tuple[tuple[str, str, float], ...] = (
    ("3114", "Forbidden Idol", 0.08),
)

MOONSTONE_IDS = ("6617", "326617", "226617")


class MirrorIdCoverageTests(unittest.TestCase):
    """Defect 1 - every live-reachable mirror id resolves to its measured amp."""

    def test_bare_ids_unchanged(self) -> None:
        for bare, name, sr, _m32, _m22 in TRUTH:
            with self.subTest(item=name, id=bare):
                self.assertAlmostEqual(sum_wielder_hsp_pct([bare]), sr, places=6)

    def test_aram_32_mirrors(self) -> None:
        for bare, name, _sr, m32, _m22 in TRUTH:
            iid = "32" + bare
            with self.subTest(item=name, id=iid):
                self.assertAlmostEqual(sum_wielder_hsp_pct([iid]), m32, places=6)

    def test_arena_22_mirrors(self) -> None:
        for bare, name, _sr, _m32, m22 in TRUTH:
            iid = "22" + bare
            with self.subTest(item=name, id=iid):
                self.assertAlmostEqual(sum_wielder_hsp_pct([iid]), m22, places=6)

    def test_bare_only_items_have_no_mirror_entry(self) -> None:
        snap = EnchanterFormulasSnapshot.load()
        for bare, name, pct in BARE_ONLY:
            with self.subTest(item=name):
                self.assertAlmostEqual(sum_wielder_hsp_pct([bare]), pct, places=6)
                self.assertFalse(snap.has_item("32" + bare))
                self.assertFalse(snap.has_item("22" + bare))

    def test_mixed_arena_inventory_sums_additively(self) -> None:
        # Arena enchanter shell: Redemption + Staff + Mikael's + Moonstone.
        # 0.12 + 0.14 + 0.12 + 0.0 (chain-only) = 0.38
        inv = ["223107", "226616", "223222", "226617"]
        self.assertAlmostEqual(sum_wielder_hsp_pct(inv), 0.38, places=6)

    def test_mixed_aram_inventory_sums_additively(self) -> None:
        # 0.15 (Mikael's) + 0.20 (Dawncore) + 0.10 (Ardent) = 0.45
        inv = ["323222", "326621", "323504"]
        self.assertAlmostEqual(sum_wielder_hsp_pct(inv), 0.45, places=6)

    def test_unknown_id_fails_soft_to_zero(self) -> None:
        self.assertAlmostEqual(sum_wielder_hsp_pct(["9999999"]), 0.0, places=6)
        self.assertAlmostEqual(
            sum_wielder_hsp_pct(["9999999", "223107"]), 0.12, places=6
        )
        self.assertAlmostEqual(sum_wielder_hsp_pct([]), 0.0, places=6)
        self.assertAlmostEqual(sum_wielder_hsp_pct(None), 0.0, places=6)


class MoonstoneAllyChainTests(unittest.TestCase):
    """Defect 2 - 0.30 is an ally-chain ratio, not a wielder-self HSP stat."""

    def test_moonstone_contributes_zero_to_wielder_self_amp(self) -> None:
        for iid in MOONSTONE_IDS:
            with self.subTest(id=iid):
                self.assertAlmostEqual(sum_wielder_hsp_pct([iid]), 0.0, places=6)

    def test_moonstone_does_not_pollute_a_mixed_inventory(self) -> None:
        without = sum_wielder_hsp_pct(["3107", "3222"])
        with_moon = sum_wielder_hsp_pct(["3107", "3222", "6617"])
        self.assertAlmostEqual(without, 0.22, places=6)
        self.assertAlmostEqual(with_moon, 0.22, places=6)

    def test_hps_path_still_sees_moonstone_030(self) -> None:
        snap = EnchanterFormulasSnapshot.load()
        f = snap.get_formula("6617")
        self.assertAlmostEqual(f.heal_shield_amp_pct, 0.30, places=6)
        self.assertIs(f.ally_chain_only, True)

    def test_from_dict_parses_ally_chain_only(self) -> None:
        f = EnchanterItemFormula.from_dict(
            "6617", {"name": "Moonstone Renewer", "heal_shield_amp_pct": 0.30,
                     "ally_chain_only": True},
        )
        self.assertIs(f.ally_chain_only, True)

    def test_ally_chain_only_defaults_false(self) -> None:
        f = EnchanterItemFormula.from_dict("3107", {"name": "Redemption"})
        self.assertIs(f.ally_chain_only, False)
        snap = EnchanterFormulasSnapshot.load()
        self.assertIs(snap.get_formula("3107").ally_chain_only, False)


class RegistryMetadataTests(unittest.TestCase):
    """Defect 3 - the shipped snapshot declares the directory it lives in."""

    def test_meta_patch_matches_directory(self) -> None:
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        # Resolve the LIVE patch: a hardcoded dir goes stale on every refresh,
        # and only the current snapshot is guaranteed on disk, so the pin then
        # breaks the self-contained guard rather than this assertion.
        patch = (root / "data" / "daemon_slayer" / "current.txt").read_text(
            encoding="utf-8"
        ).strip()
        path = root / "data" / "daemon_slayer" / patch / "enchanter_items.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["_meta"]["patch"], patch)


if __name__ == "__main__":
    unittest.main()
