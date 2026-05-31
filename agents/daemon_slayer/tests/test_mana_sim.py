"""Tests for the V2 mana-bounded combat simulator (agents.daemon_slayer.mana_sim).

Property + fail-soft style, grounded against the live 16.11.1 snapshot. Real
champion ids: Lux + Anivia (partype Mana, real pools), Katarina (partype None,
manaless), Zed (partype Energy). Real mana item ids: Tear 3070 (+240 mana),
Archangel's 3003 (+600 mana).

The walk is a bounded ROTATION (waits for cooldowns, accrues regen) so a long
cast list genuinely drains a finite mana pool - the V1 burst walker assumes
infinite mana, this one does not.
"""

from __future__ import annotations

import dataclasses
import math
import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.mana_sim import (
    ManaBoundedResult,
    ManaLedgerHit,
    compute_mana_bounded_combo,
)

# A long rotation: six full Q-W-E-R cycles. Long enough that a mana champion
# without a mana item runs dry, while a big-mana-item build sustains more.
_LONG_SEQ = ["Q", "W", "E", "R"] * 6

# Item ids verified present in 16.11.1 items.json with FlatMPPoolMod.
_TEAR = "3070"          # +240 mana
_ARCHANGELS = "3003"    # +600 mana


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def run_combo(self, champ, level, items=None, seq=None):
        return compute_mana_bounded_combo(
            champ, level, item_ids=items, sequence=seq or _LONG_SEQ,
            snapshot=self.snap,
        )


class ManaChampionGatingTests(_Base):
    """A real mana champion goes OOM on a long combo; a big mana item sustains
    strictly more casts."""

    def test_lux_is_mana_resource_with_positive_pool(self):
        r = self.run_combo("Lux", 9, items=[])
        self.assertEqual(r.resource_type, "Mana")
        self.assertGreater(r.mana_pool, 0.0)
        self.assertFalse(math.isinf(r.mana_pool))
        self.assertGreater(r.mana_regen_per_s, 0.0)

    def test_lux_long_combo_goes_oom_itemless(self):
        r = self.run_combo("Lux", 9, items=[])
        self.assertLess(
            r.casts_allowed, r.casts_requested,
            "itemless mana champ on a long combo should run dry",
        )
        self.assertIsNotNone(r.oom_at_t)
        # An oom row must exist in the ledger.
        self.assertTrue(any(h.status == "oom" for h in r.hits))

    def test_mana_item_sustains_strictly_more_casts(self):
        itemless = self.run_combo("Lux", 9, items=[])
        with_archangels = self.run_combo("Lux", 9, items=[_ARCHANGELS])
        self.assertGreater(
            with_archangels.casts_allowed, itemless.casts_allowed,
            "a +600 mana item must let the rotation land more casts",
        )
        # Archangel's also lifts the pool itself.
        self.assertGreater(with_archangels.mana_pool, itemless.mana_pool)

    def test_anivia_also_gates_and_archangels_lifts(self):
        itemless = self.run_combo("Anivia", 9, items=[])
        self.assertEqual(itemless.resource_type, "Mana")
        self.assertLess(itemless.casts_allowed, itemless.casts_requested)
        with_archangels = self.run_combo("Anivia", 9, items=[_ARCHANGELS])
        self.assertGreaterEqual(
            with_archangels.casts_allowed, itemless.casts_allowed,
        )

    def test_oom_row_does_not_spend_mana(self):
        r = self.run_combo("Lux", 9, items=[])
        for h in r.hits:
            if h.status == "oom":
                self.assertEqual(h.mana_before, h.mana_after)
                self.assertEqual(h.raw, 0.0)
                self.assertEqual(h.mitigated, 0.0)


class ManalessChampionTests(_Base):
    """A manaless / energy champion is never gated; bounded == unbounded."""

    def test_katarina_resource_is_not_mana(self):
        r = self.run_combo("Katarina", 9, items=[])
        self.assertNotEqual(r.resource_type, "Mana")

    def test_katarina_no_oom_and_bounded_equals_unbounded(self):
        r = self.run_combo("Katarina", 9, items=[])
        self.assertIsNone(r.oom_at_t)
        self.assertFalse(any(h.status == "oom" for h in r.hits))
        self.assertEqual(r.bounded_dps, r.unbounded_dps)

    def test_zed_energy_is_not_gated(self):
        r = self.run_combo("Zed", 9, items=[])
        self.assertNotEqual(r.resource_type, "Mana")
        self.assertIsNone(r.oom_at_t)
        self.assertEqual(r.bounded_dps, r.unbounded_dps)
        # Energy pool is treated as effectively infinite.
        self.assertTrue(math.isinf(r.mana_pool))


class MonotonicityTests(_Base):
    """More mana -> casts_allowed non-decreasing; bounded_dps <= unbounded_dps."""

    def test_more_mana_items_never_decrease_casts_allowed(self):
        none = self.run_combo("Lux", 9, items=[])
        tear = self.run_combo("Lux", 9, items=[_TEAR])
        archangels = self.run_combo("Lux", 9, items=[_ARCHANGELS])
        self.assertLessEqual(none.casts_allowed, tear.casts_allowed)
        self.assertLessEqual(tear.casts_allowed, archangels.casts_allowed)

    def test_bounded_dps_never_exceeds_unbounded_dps(self):
        for champ, level, items in [
            ("Lux", 9, []),
            ("Lux", 9, [_TEAR]),
            ("Lux", 9, [_ARCHANGELS]),
            ("Anivia", 9, []),
            ("Anivia", 11, [_ARCHANGELS]),
            ("Katarina", 9, []),
            ("Zed", 9, []),
            ("Lux", 1, []),
            ("Anivia", 18, []),
        ]:
            r = self.run_combo(champ, level, items=items)
            self.assertLessEqual(
                r.bounded_dps, r.unbounded_dps + 1e-6,
                f"{champ} L{level} {items}: bounded {r.bounded_dps} "
                f"exceeded unbounded {r.unbounded_dps}",
            )

    def test_casts_allowed_never_exceeds_requested(self):
        for champ, level, items in [
            ("Lux", 9, []),
            ("Anivia", 9, []),
            ("Katarina", 9, []),
            ("Zed", 9, []),
        ]:
            r = self.run_combo(champ, level, items=items)
            self.assertLessEqual(r.casts_allowed, r.casts_requested)


class LedgerShapeTests(_Base):
    """Per-hit ledger invariants on an ok cast."""

    def test_ok_cast_deducts_cost(self):
        r = self.run_combo("Lux", 9, items=[_ARCHANGELS])
        ok_with_cost = [
            h for h in r.hits if h.status == "ok" and h.cost > 0.0
        ]
        self.assertTrue(ok_with_cost, "expected at least one ok cast with cost")
        for h in ok_with_cost:
            self.assertAlmostEqual(h.mana_after, h.mana_before - h.cost, places=2)

    def test_cumulative_is_running_sum_of_mitigated(self):
        r = self.run_combo("Lux", 9, items=[_ARCHANGELS])
        running = 0.0
        for h in r.hits:
            running = round(running + h.mitigated, 2)
            self.assertAlmostEqual(h.cumulative, running, places=2)

    def test_result_and_hit_are_frozen_dataclasses(self):
        r = self.run_combo("Lux", 9, items=[])
        self.assertIsInstance(r, ManaBoundedResult)
        self.assertTrue(all(isinstance(h, ManaLedgerHit) for h in r.hits))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.casts_allowed = 99  # frozen


class FailSoftTests(_Base):
    """No champion / empty sequence / unknown champion never raises."""

    def test_unknown_champion_returns_empty_with_note(self):
        r = self.run_combo("NotARealChampion", 9, items=[])
        self.assertEqual(r.hits, ())
        self.assertEqual(r.casts_allowed, 0)
        self.assertTrue(r.notes)

    def test_empty_sequence_returns_empty_with_note(self):
        r = compute_mana_bounded_combo("Lux", 9, sequence=[], snapshot=self.snap)
        self.assertEqual(r.hits, ())
        self.assertTrue(any("empty sequence" in n for n in r.notes))

    def test_blank_champion_returns_empty_with_note(self):
        r = compute_mana_bounded_combo("  ", 9, sequence=_LONG_SEQ, snapshot=self.snap)
        self.assertEqual(r.hits, ())
        self.assertTrue(any("no champion" in n for n in r.notes))

    def test_none_and_blank_tokens_are_stripped(self):
        r = compute_mana_bounded_combo(
            "Lux", 9, sequence=["Q", "", None, "  ", "W"], snapshot=self.snap,
        )
        self.assertEqual(r.sequence, ("Q", "W"))


class AsciiHygieneTests(unittest.TestCase):
    """mana_sim.py must be pure 7-bit ASCII (CLAUDE.md hard rule)."""

    def test_module_is_ascii(self):
        import agents.daemon_slayer.mana_sim as mod

        with open(mod.__file__, "rb") as fh:
            raw = fh.read()
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as exc:  # pragma: no cover - failure path
            self.fail(f"mana_sim.py has a non-ASCII byte: {exc}")


if __name__ == "__main__":
    unittest.main()
