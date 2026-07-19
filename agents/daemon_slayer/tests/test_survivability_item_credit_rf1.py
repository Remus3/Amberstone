"""RF1 (generic-bruiser-template) - survivability item-credit seam (hybrid ranker).

The hybrid/bruiser scorer (``rank_items_by_hybrid``) emits a near-fixed generic
AD-DPS template for every bruiser (Void Immolation / BotRK / Trinity / Heartsteel
/ Essence Reaver / Runaan's) because its sort key
``hybrid_delta_pct = alpha*dps_pct + beta*ehp_pct`` is alpha-weighted toward damage
and its default mixed-damage target preset under-credits the pure resist/sustain
axis, so the WIN-correlated survivability items the player base wins ARAM on
(Spirit Visage / Jak'Sho / Sterak's Gage / Death's Dance / Force of Nature /
Randuin's Omen / Thornmail / Titanic Hydra / Fimbulwinter) sink below it (DSP10
consolidated buried winners). The DEFAULT-OFF ``prefer_survivability_by_win`` seam
reads the WIN-anchored ``survivability_item_credit`` table and, when ON, floats
those items above the generic template BY TABLE MEMBERSHIP.

ROOT-CAUSE distinction (verify-before-redo vs DSP2/DSP11): DSP11's
``prefer_kit_axis_by_win`` floats in the DPS/burst rankers GATED ON
``delta_dps > 0``; survivability items add EHP not DPS so their delta is ~0 and
would never float there. RF1 lives in the HYBRID ranker and floats by membership.

Contract (mirrors the DSP11 seam convention):

* DEFAULT-OFF: ``prefer_survivability_by_win=False`` is byte-identical to today
  (``survivability_score`` stays 0.0, sort unchanged).
* A champ ABSENT from the table is a no-op even when the flag is ON.
* When ON for a tabled champ, the ranking is PARTITIONED: every surfaced
  survivability row (``survivability_score==1.0``) precedes every other row, with
  model order preserved within each tier.

Assertions are partition / membership invariants + computed-quantity checks,
NOT fragile absolute cross-item rank pins.
"""
from __future__ import annotations

import unittest

from agents import daemon_slayer
from agents.daemon_slayer import survivability_credit
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.hybrid import rank_items_by_hybrid
from agents.daemon_slayer.data_loader import DataSnapshot

_LEVEL = 13


def _snap() -> DataSnapshot:
    reset_default_cache()
    survivability_credit.reset_cache()
    return DataSnapshot.load()


def _ids(res) -> list[str]:
    return [r.item_id for r in res.ranked]


def _partitioned(res) -> bool:
    """True iff all survivability_score==1.0 rows precede all 0.0 rows."""
    seen_zero = False
    for r in res.ranked:
        if r.survivability_score <= 0.0:
            seen_zero = True
        elif seen_zero:
            return False
    return True


class TestSurvivabilityLoader(unittest.TestCase):
    def setUp(self) -> None:
        survivability_credit.reset_cache()

    def test_darius_ids(self) -> None:
        ids = survivability_credit.survivability_item_ids("Darius")
        # Force of Nature / Sterak's Gage / Death's Dance.
        self.assertTrue({"4401", "3053", "6333"} <= ids)

    def test_udyr_ids(self) -> None:
        ids = survivability_credit.survivability_item_ids("Udyr")
        # Jak'Sho / Spirit Visage.
        self.assertTrue({"6665", "3065"} <= ids)

    def test_yasuo_ids(self) -> None:
        ids = survivability_credit.survivability_item_ids("Yasuo")
        self.assertTrue({"6665", "3091"} <= ids)  # Jak'Sho / Wit's End

    def test_masteryi_absent(self) -> None:
        # MasterYi's buried winners are pure DPS (IE / Guinsoo's) - a DSP11 /
        # within-axis matter, NOT a survivability defect, so he is NOT tabled.
        self.assertEqual(survivability_credit.survivability_item_ids("MasterYi"), frozenset())

    def test_unknown_and_blank_empty(self) -> None:
        self.assertEqual(survivability_credit.survivability_item_ids("Garen"), frozenset())
        self.assertEqual(survivability_credit.survivability_item_ids(""), frozenset())


class TestHybridSeam(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = _snap()

    def test_off_is_byte_identical(self) -> None:
        a = rank_items_by_hybrid(self.snap, "Darius", _LEVEL, mode="ARAM", top_n=30)
        b = rank_items_by_hybrid(self.snap, "Darius", _LEVEL, mode="ARAM", top_n=30,
                                 prefer_survivability_by_win=False)
        self.assertEqual(_ids(a), _ids(b))
        self.assertTrue(all(r.survivability_score == 0.0 for r in b.ranked))

    def test_on_floats_survivability_items(self) -> None:
        off = rank_items_by_hybrid(self.snap, "Darius", _LEVEL, mode="ARAM", top_n=30)
        on = rank_items_by_hybrid(self.snap, "Darius", _LEVEL, mode="ARAM", top_n=30,
                                  prefer_survivability_by_win=True)
        self.assertTrue(_partitioned(on))
        surfaced = {r.item_id for r in on.ranked if r.survivability_score > 0.0}
        # Force of Nature (4401, +18.7 lift) is a pure-MR survivability winner the
        # damage-biased hybrid sort buries; it surfaces under the seam.
        self.assertIn("4401", surfaced)
        self.assertNotIn("4401", set(_ids(off)[:4]))   # buried before the seam
        self.assertIn("4401", set(_ids(on)[:4]))        # floated after

    def test_on_floats_by_membership_not_delta(self) -> None:
        # The defining RF1 property: a surfaced survivability item floats even
        # though its hybrid_delta_pct is NOT the top of the model order (the
        # damage-biased scorer rates the generic template higher). Prove at least
        # one floated item has a lower hybrid_delta_pct than the off-seam #1.
        off = rank_items_by_hybrid(self.snap, "Udyr", _LEVEL, mode="ARAM", top_n=30)
        on = rank_items_by_hybrid(self.snap, "Udyr", _LEVEL, mode="ARAM", top_n=30,
                                  prefer_survivability_by_win=True)
        self.assertTrue(_partitioned(on))
        off_top_pct = off.ranked[0].hybrid_delta_pct
        floated = [r for r in on.ranked if r.survivability_score > 0.0]
        self.assertTrue(floated)
        self.assertTrue(any(r.hybrid_delta_pct < off_top_pct for r in floated))

    def test_untabled_champ_is_noop(self) -> None:
        off = rank_items_by_hybrid(self.snap, "Garen", _LEVEL, mode="ARAM", top_n=20)
        on = rank_items_by_hybrid(self.snap, "Garen", _LEVEL, mode="ARAM", top_n=20,
                                  prefer_survivability_by_win=True)
        self.assertEqual(_ids(off), _ids(on))
        self.assertTrue(all(r.survivability_score == 0.0 for r in on.ranked))


class TestEnginePin(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.227.0")


if __name__ == "__main__":
    unittest.main()
