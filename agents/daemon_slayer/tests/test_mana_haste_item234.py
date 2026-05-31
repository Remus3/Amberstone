"""Item 234 - mana_sim opt-in ability-haste / CDR model.

apply_ability_haste (default False) reduces every cooldown-bearing slot via
Riot's canonical base_cd / (1 + AH/100), using the same total_item_ability_haste
registry the live ability scorer consumes. Byte-identical when off or when the
build carries no haste items. Haste only BINDS on a cooldown-repeating sequence
(a single-cast combo is cast-time-bound, not cooldown-bound).
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.mana_sim import compute_mana_bounded_combo

# Lux Q has a real cooldown; repeating it forces the WAIT-TO-READY gate so
# haste changes the wall-clock.
_REPEAT_SEQ = ["Q", "AA", "Q", "AA", "Q"]
_AH_BUILD = ["3158", "4629"]   # Ionian Boots 10 + Cosmic Drive 25 = 35 AH
_NO_AH_BUILD = ["3157", "3089"]  # Zhonya's + Rabadon's = 0 AH


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()


class ByteIdenticalTests(_Base):
    def test_default_off_equals_explicit_off(self) -> None:
        a = compute_mana_bounded_combo(
            "Lux", 11, _AH_BUILD, _REPEAT_SEQ, snapshot=self.snap,
        )
        b = compute_mana_bounded_combo(
            "Lux", 11, _AH_BUILD, _REPEAT_SEQ, snapshot=self.snap,
            apply_ability_haste=False,
        )
        self.assertEqual(a.duration_s, b.duration_s)
        self.assertEqual(a.bounded_dps, b.bounded_dps)
        self.assertEqual(a.casts_allowed, b.casts_allowed)

    def test_no_haste_build_byte_identical_even_with_flag(self) -> None:
        # A build with 0 ability haste -> flag-on is byte-identical to flag-off.
        off = compute_mana_bounded_combo(
            "Lux", 11, _NO_AH_BUILD, _REPEAT_SEQ, snapshot=self.snap,
        )
        on = compute_mana_bounded_combo(
            "Lux", 11, _NO_AH_BUILD, _REPEAT_SEQ, snapshot=self.snap,
            apply_ability_haste=True,
        )
        self.assertEqual(off.duration_s, on.duration_s)
        self.assertEqual(off.bounded_dps, on.bounded_dps)

    def test_single_cast_combo_haste_moot(self) -> None:
        # A single-cast sequence is cast-time-bound (no slot repeats), so haste
        # does not change the wall-clock even with an AH build.
        seq = ["Q", "AA", "W", "E", "R"]
        off = compute_mana_bounded_combo(
            "Lux", 11, _AH_BUILD, seq, snapshot=self.snap,
        )
        on = compute_mana_bounded_combo(
            "Lux", 11, _AH_BUILD, seq, snapshot=self.snap,
            apply_ability_haste=True,
        )
        self.assertEqual(off.duration_s, on.duration_s)


class HasteEffectTests(_Base):
    def test_haste_shortens_duration_raises_dps(self) -> None:
        off = compute_mana_bounded_combo(
            "Lux", 11, _AH_BUILD, _REPEAT_SEQ, snapshot=self.snap,
        )
        on = compute_mana_bounded_combo(
            "Lux", 11, _AH_BUILD, _REPEAT_SEQ, snapshot=self.snap,
            apply_ability_haste=True,
        )
        self.assertLess(on.duration_s, off.duration_s)
        self.assertGreater(on.bounded_dps, off.bounded_dps)

    def test_cdr_factor_exact(self) -> None:
        # 35 AH -> cooldown factor 100/135 = 0.7407. The cooldown-wait portion
        # of the wall-clock scales by that factor; verify the surfaced note.
        on = compute_mana_bounded_combo(
            "Lux", 11, _AH_BUILD, _REPEAT_SEQ, snapshot=self.snap,
            apply_ability_haste=True,
        )
        self.assertTrue(any("ability_haste=35" in n for n in on.notes))

    def test_invariant_bounded_le_unbounded_with_haste(self) -> None:
        on = compute_mana_bounded_combo(
            "Lux", 11, _AH_BUILD, _REPEAT_SEQ, snapshot=self.snap,
            apply_ability_haste=True,
        )
        self.assertLessEqual(on.bounded_dps, on.unbounded_dps + 1e-6)


class AsciiHygieneTests(unittest.TestCase):
    def test_source_ascii(self) -> None:
        with open(__file__, "rb") as fh:
            raw = fh.read()
        for i, b in enumerate(raw):
            self.assertLess(b, 128, f"non-ASCII byte 0x{b:02x} at {i}")


if __name__ == "__main__":
    unittest.main()
