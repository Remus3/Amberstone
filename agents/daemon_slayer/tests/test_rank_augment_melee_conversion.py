"""Arena/Cherry augment-aware ranged-only purchasability gate (2026-07-11).

Follow-up to the 2026-07-02 base-range ranged-only gate
(``test_rank_ranged_only_purchasability.py``): that gate correctly blocks
Runaan's Hurricane (``RANGED_ONLY_ITEM_IDS = {"3085","223085"}``) for
BASE-melee champions, but it keys ONLY on the champion's base attackrange and is
AUGMENT-BLIND. In Arena/Cherry the augment "Draw Your Sword" (id 134, apiName
``DrawYourSword``, rarity 2, "You are now melee.") CONVERTS a ranged champion to
melee - after which Runaan's bonus bolts do nothing, exactly like a base-melee
champ - yet the augment-blind gate still classifies the wielder ranged and still
offers the now-useless item.

Live repro (2026-07-11 ranged-only investigation, LEDGER 855 side-quest):
``rank_items(snap, "Caitlyn", 11, mode="ARENA", augments=[134])`` still surfaced
Runaan's Arena alias ``223085`` (identical to the no-augment baseline).

Fix: an augment-aware ``_champion_is_melee(champ_rec, augments=None)`` -
``base_range_melee OR _augment_forces_melee(augments)`` - fed the ``augments``
already threaded into every scorer lane's ``rank_items*`` signature. SR/ARAM (no
augment set) and base-melee handling are UNCHANGED (``augments`` defaults None).
Scoped to the melee-CONVERSION augment set (currently just DrawYourSword / 134);
a non-conversion augment must NOT force melee (no over-filter of a real ranged
carry's Runaan's).

This is a PURCHASABILITY / functionality correctness gate (Runaan's is
non-functional in melee form), the same class as the base-range gate and the
Ornn-masterwork deny - distinct from the default-OFF ``apply_melee_aa_gate``
(B7, an AA-DPS valuation seam).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import (
    _MELEE_CONVERSION_AUGMENT_APINAMES,
    _MELEE_CONVERSION_AUGMENT_IDS,
    _augment_forces_melee,
    _champion_is_melee,
    rank_items,
)

_RUNAAN = "3085"
_RUNAAN_ARENA = "223085"
_DRAW_ID = 134
_DRAW_API = "DrawYourSword"


class ConversionSetShapeTests(unittest.TestCase):
    def test_sets_carry_draw_your_sword(self) -> None:
        self.assertIn(_DRAW_ID, _MELEE_CONVERSION_AUGMENT_IDS)
        self.assertIn(_DRAW_API, _MELEE_CONVERSION_AUGMENT_APINAMES)

    def test_apinames_are_ascii_str(self) -> None:
        self.assertIsInstance(_MELEE_CONVERSION_AUGMENT_APINAMES, frozenset)
        for a in _MELEE_CONVERSION_AUGMENT_APINAMES:
            self.assertIsInstance(a, str)
            self.assertTrue(a.isascii(), f"non-ascii apiName: {a!r}")


class AugmentForcesMeleeUnitTests(unittest.TestCase):
    def test_int_id(self) -> None:
        self.assertTrue(_augment_forces_melee([_DRAW_ID]))

    def test_apiname_str(self) -> None:
        self.assertTrue(_augment_forces_melee([_DRAW_API]))

    def test_numeric_string_id(self) -> None:
        self.assertTrue(_augment_forces_melee([str(_DRAW_ID)]))

    def test_record_dict(self) -> None:
        self.assertTrue(
            _augment_forces_melee([{"id": _DRAW_ID, "apiName": _DRAW_API}])
        )

    def test_mixed_list_with_conversion_present(self) -> None:
        self.assertTrue(_augment_forces_melee(["TheBrutalizer", _DRAW_ID]))

    def test_none_is_false(self) -> None:
        self.assertFalse(_augment_forces_melee(None))

    def test_empty_is_false(self) -> None:
        self.assertFalse(_augment_forces_melee([]))

    def test_non_conversion_augment_is_false(self) -> None:
        # A real, unrelated augment must NOT force melee (no over-filter).
        self.assertFalse(_augment_forces_melee(["TheBrutalizer"]))
        self.assertFalse(_augment_forces_melee([9999]))


class MeleePredicateAugmentAwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        cls.cait = cls.snap.champions.get("Caitlyn")
        cls.garen = cls.snap.champions.get("Garen")

    def test_ranged_champ_no_augment_stays_ranged(self) -> None:
        self.assertFalse(_champion_is_melee(self.cait))
        self.assertFalse(_champion_is_melee(self.cait, augments=None))
        self.assertFalse(_champion_is_melee(self.cait, augments=["TheBrutalizer"]))

    def test_ranged_champ_with_conversion_augment_becomes_melee(self) -> None:
        # THE core RED: base-ranged + Draw Your Sword -> treated as melee.
        self.assertTrue(_champion_is_melee(self.cait, augments=[_DRAW_ID]))
        self.assertTrue(_champion_is_melee(self.cait, augments=[_DRAW_API]))

    def test_base_melee_unchanged_regardless_of_augments(self) -> None:
        self.assertTrue(_champion_is_melee(self.garen))
        self.assertTrue(_champion_is_melee(self.garen, augments=None))
        self.assertTrue(_champion_is_melee(self.garen, augments=[_DRAW_ID]))


class ArenaRankAugmentGateTests(unittest.TestCase):
    """End-to-end repro + fix oracle at the live ranking entry point."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    @staticmethod
    def _runaan_ids(result) -> set:
        return {r.item_id for r in result.ranked if r.item_id in (_RUNAAN, _RUNAAN_ARENA)}

    def test_arena_converted_ranged_drops_runaan(self) -> None:
        # RED before fix: Caitlyn ARENA + Draw Your Sword still surfaces 223085.
        res = rank_items(self.snap, "Caitlyn", 11, mode="ARENA", top_n=80, augments=[_DRAW_ID])
        self.assertFalse(
            self._runaan_ids(res),
            "Runaan's surfaced for a ranged champ converted to melee by Draw Your Sword (ARENA)",
        )

    def test_cherry_converted_ranged_drops_runaan(self) -> None:
        res = rank_items(self.snap, "Caitlyn", 11, mode="CHERRY", top_n=80, augments=[_DRAW_API])
        self.assertFalse(
            self._runaan_ids(res),
            "Runaan's surfaced for a ranged champ converted to melee by Draw Your Sword (CHERRY)",
        )

    def test_arena_ranged_no_augment_keeps_runaan(self) -> None:
        # Regression guard: without the conversion augment, a ranged carry MUST
        # keep Runaan's (do not over-filter).
        res = rank_items(self.snap, "Caitlyn", 11, mode="ARENA", top_n=80)
        self.assertIn(
            _RUNAAN_ARENA, {r.item_id for r in res.ranked},
            "Runaan's wrongly dropped for a ranged Caitlyn without a conversion augment (ARENA)",
        )

    def test_arena_ranged_non_conversion_augment_keeps_runaan(self) -> None:
        res = rank_items(self.snap, "Caitlyn", 11, mode="ARENA", top_n=80, augments=["TheBrutalizer"])
        self.assertIn(
            _RUNAAN_ARENA, {r.item_id for r in res.ranked},
            "A non-conversion augment wrongly gated Runaan's for ranged Caitlyn (ARENA)",
        )

    def test_arena_base_melee_drops_runaan_regardless(self) -> None:
        for augs in (None, [_DRAW_ID]):
            res = rank_items(self.snap, "Garen", 11, mode="ARENA", top_n=80, augments=augs)
            self.assertFalse(
                self._runaan_ids(res),
                f"Runaan's surfaced for base-melee Garen in ARENA (augments={augs})",
            )


class ModuleAsciiTests(unittest.TestCase):
    def test_module_file_is_ascii(self) -> None:
        from pathlib import Path

        raw = Path(__file__).read_bytes()
        bad = [(i, b) for i, b in enumerate(raw) if b > 127]
        self.assertFalse(bad, f"non-ascii bytes at {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
