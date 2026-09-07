"""Item 262 - bruiser mitigation-aware hybrid scorer (symmetric to item 261).

Item 261 wired the item-261 effects-text DAMAGE-REDUCTION layer
(``apply_passive_mitigation``) into the TANK EHP scorer
(``compute_ehp`` + ``rank_items_by_ehp`` + ``/ehp`` + ``/rank-tank``).
The BRUISER scorer (``compute_hybrid`` + ``rank_items_by_hybrid`` +
``/hybrid`` + ``/rank-bruiser``) was mitigation-blind. This threads the
flag through so a champion with a registered mitigation passive gets a
DR-boosted ``ehp`` + ``cc_blended_ehp`` + ``hybrid_score`` scalar.

Mitigation is a CHAMPION passive (build-independent) -> it scales the EHP
denominator uniformly across baseline + every candidate, so the
ratio-based ``hybrid_delta_pct`` sort is INVARIANT (does NOT re-rank);
enabling it makes the per-row scalars accurate. This mirrors item 261's
tank ``rank_items_by_ehp`` (a champ passive cannot differentiate one
candidate from another the way the build-dependent tenacity term does).

DEFAULT (apply_passive_mitigation=False) BYTE-IDENTICAL to 1.91.0.
Registered mitigation champs at 16.11.1: Kassadin / KSante / Briar /
Irelia / Nilah. ASCII only.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hybrid import compute_hybrid, rank_items_by_hybrid

_SUNFIRE = ["3068"]            # Sunfire Aegis - a sensible bruiser/tank terminal
_KSANTE = "KSante"            # W Path Maker 30% ALL active -> mit 0.91 all 3 @ prob 0.3
_BRIAR = "Briar"             # E Chilling Scream 35% ALL active -> mit 0.895 all 3
_IRELIA = "Irelia"           # W Defiant Dance phys 0.8271 / mag 0.9135 / true 1.0 level_scaled
_NO_DR_CHAMP = "Caitlyn"           # NO DR in either registry -> byte-identical flag-on (R35: Garen moved out - its W now folds a snapshot percent-DR block)
_LIGHT_CC = ["Ashe"]         # ~1.5s CC - below the 6s saturation cap


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        server._CACHE.set(cls.snap)


class ComputeHybridMitigationTests(_Base):
    def test_default_off_byte_identical(self) -> None:
        a = compute_hybrid(self.snap, _KSANTE, 11, item_ids=_SUNFIRE, mode="SR")
        b = compute_hybrid(self.snap, _KSANTE, 11, item_ids=_SUNFIRE, mode="SR",
                           apply_passive_mitigation=False)
        self.assertEqual(a.hybrid_score, b.hybrid_score)
        self.assertEqual(a.ehp, b.ehp)
        self.assertEqual(a.cc_blended_ehp, b.cc_blended_ehp)

    def test_mitigation_raises_hybrid_score(self) -> None:
        # Unlike tenacity (cc_blended-only), a flat-% DR folds into the EHP
        # denominator DIRECTLY -> blended_ehp grows even with NO enemies.
        off = compute_hybrid(self.snap, _KSANTE, 11, item_ids=_SUNFIRE, mode="SR",
                             apply_passive_mitigation=False)
        on = compute_hybrid(self.snap, _KSANTE, 11, item_ids=_SUNFIRE, mode="SR",
                            apply_passive_mitigation=True)
        self.assertGreater(on.hybrid_score, off.hybrid_score)
        self.assertGreater(on.ehp, off.ehp)

    def test_ksante_ehp_is_exact_dr_boost(self) -> None:
        # KSante W = 30% ALL DR amortized at prob 0.3 -> mit 0.91 on all 3
        # damage types -> blended_ehp scales by exactly 1/0.91.
        off = compute_hybrid(self.snap, _KSANTE, 11, item_ids=_SUNFIRE, mode="SR",
                             apply_passive_mitigation=False)
        on = compute_hybrid(self.snap, _KSANTE, 11, item_ids=_SUNFIRE, mode="SR",
                            apply_passive_mitigation=True)
        self.assertAlmostEqual(on.ehp / off.ehp, 1.0 / 0.91, places=4)

    def test_no_entry_champ_byte_identical(self) -> None:
        off = compute_hybrid(self.snap, _NO_DR_CHAMP, 11, item_ids=_SUNFIRE, mode="SR",
                             apply_passive_mitigation=False)
        on = compute_hybrid(self.snap, _NO_DR_CHAMP, 11, item_ids=_SUNFIRE, mode="SR",
                            apply_passive_mitigation=True)
        self.assertEqual(off.hybrid_score, on.hybrid_score)
        self.assertEqual(off.ehp, on.ehp)

    def test_cc_blended_field_also_dr_boosted(self) -> None:
        # cc_blended_ehp derives from blended_ehp, so the DR boost propagates.
        on = compute_hybrid(self.snap, _BRIAR, 11, item_ids=_SUNFIRE, mode="SR",
                            enemy_champions=_LIGHT_CC, include_conditional=True,
                            apply_passive_mitigation=True)
        off = compute_hybrid(self.snap, _BRIAR, 11, item_ids=_SUNFIRE, mode="SR",
                             enemy_champions=_LIGHT_CC, include_conditional=True,
                             apply_passive_mitigation=False)
        self.assertGreater(on.cc_blended_ehp, off.cc_blended_ehp)

    def test_irelia_level_scaled_dr_boosts(self) -> None:
        # Irelia W is level_scaled (phys 0.8271 / mag 0.9135 / true 1.0 @ L11);
        # default enemy mix 50/50 -> blended grows but by less than 1/0.8271.
        off = compute_hybrid(self.snap, _IRELIA, 11, item_ids=_SUNFIRE, mode="SR",
                             apply_passive_mitigation=False)
        on = compute_hybrid(self.snap, _IRELIA, 11, item_ids=_SUNFIRE, mode="SR",
                            apply_passive_mitigation=True)
        self.assertGreater(on.ehp, off.ehp)


class RankHybridMitigationTests(_Base):
    def test_default_equals_explicit_false(self) -> None:
        a = rank_items_by_hybrid(self.snap, _KSANTE, 11, current_item_ids=_SUNFIRE,
                                 mode="SR", top_n=10)
        b = rank_items_by_hybrid(self.snap, _KSANTE, 11, current_item_ids=_SUNFIRE,
                                 mode="SR", top_n=10, apply_passive_mitigation=False)
        self.assertEqual([r.item_id for r in a.ranked], [r.item_id for r in b.ranked])
        self.assertEqual([r.hybrid_delta_pct for r in a.ranked],
                         [r.hybrid_delta_pct for r in b.ranked])

    def test_mitigation_does_not_rerank(self) -> None:
        # A champion passive scales baseline + every candidate EHP denominator
        # by the SAME constant -> the ratio-based delta_pct sort is invariant.
        off = rank_items_by_hybrid(self.snap, _KSANTE, 11, current_item_ids=_SUNFIRE,
                                   mode="SR", top_n=10, apply_passive_mitigation=False)
        on = rank_items_by_hybrid(self.snap, _KSANTE, 11, current_item_ids=_SUNFIRE,
                                  mode="SR", top_n=10, apply_passive_mitigation=True)
        self.assertEqual([r.item_id for r in off.ranked], [r.item_id for r in on.ranked])
        self.assertEqual(
            [round(r.hybrid_delta_pct, 6) for r in off.ranked],
            [round(r.hybrid_delta_pct, 6) for r in on.ranked],
        )

    def test_mitigation_dr_boosts_per_row_scalar(self) -> None:
        # The per-row hybrid_score scalar (NOT the sort key) IS DR-boosted.
        off = rank_items_by_hybrid(self.snap, _KSANTE, 11, current_item_ids=_SUNFIRE,
                                   mode="SR", top_n=10, apply_passive_mitigation=False)
        on = rank_items_by_hybrid(self.snap, _KSANTE, 11, current_item_ids=_SUNFIRE,
                                  mode="SR", top_n=10, apply_passive_mitigation=True)
        self.assertGreater(on.ranked[0].hybrid_score, off.ranked[0].hybrid_score)
        self.assertGreater(on.ranked[0].cc_blended_ehp, off.ranked[0].cc_blended_ehp)

    def test_no_entry_champ_rank_byte_identical(self) -> None:
        off = rank_items_by_hybrid(self.snap, _NO_DR_CHAMP, 11, current_item_ids=_SUNFIRE,
                                   mode="SR", top_n=10, apply_passive_mitigation=False)
        on = rank_items_by_hybrid(self.snap, _NO_DR_CHAMP, 11, current_item_ids=_SUNFIRE,
                                  mode="SR", top_n=10, apply_passive_mitigation=True)
        self.assertEqual([r.hybrid_score for r in off.ranked],
                         [r.hybrid_score for r in on.ranked])


class RouteHybridMitigationTests(_Base):
    def test_route_hybrid_accepts_flag(self) -> None:
        off = server._route_hybrid(
            {"champion": _KSANTE, "level": 11, "items": _SUNFIRE, "mode": "SR"}
        )
        on = server._route_hybrid(
            {"champion": _KSANTE, "level": 11, "items": _SUNFIRE, "mode": "SR",
             "apply_passive_mitigation": True}
        )
        self.assertGreater(on["hybrid_score"], off["hybrid_score"])

    def test_route_hybrid_default_byte_identical(self) -> None:
        a = server._route_hybrid(
            {"champion": _KSANTE, "level": 11, "items": _SUNFIRE, "mode": "SR"}
        )
        b = server._route_hybrid(
            {"champion": _KSANTE, "level": 11, "items": _SUNFIRE, "mode": "SR",
             "apply_passive_mitigation": False}
        )
        self.assertEqual(a["hybrid_score"], b["hybrid_score"])

    def test_route_rank_bruiser_accepts_flag(self) -> None:
        on = server._route_rank_bruiser(
            {"champion": _KSANTE, "level": 11, "items": _SUNFIRE, "mode": "SR",
             "top": 5, "apply_passive_mitigation": True}
        )
        off = server._route_rank_bruiser(
            {"champion": _KSANTE, "level": 11, "items": _SUNFIRE, "mode": "SR",
             "top": 5}
        )
        # order invariant (champ-passive uniform scale) but scalar DR-boosted
        self.assertEqual(
            [r["item_id"] for r in on["ranked"]],
            [r["item_id"] for r in off["ranked"]],
        )
        self.assertGreater(on["ranked"][0]["hybrid_score"], off["ranked"][0]["hybrid_score"])


class AsciiHygieneTests(unittest.TestCase):
    def test_new_test_file_is_ascii(self) -> None:
        # Anchored on __file__, not the process CWD, so this hygiene test
        # runs from any directory.
        path = Path(__file__).resolve()
        with open(path, "rb") as fh:
            raw = fh.read()
        # decode raises on the first non-ASCII byte
        self.assertTrue(raw.decode("ascii"))


if __name__ == "__main__":
    unittest.main()
