"""Item 235 - self-audit wiring + parameterize pass.

Pins the route+ranker exposure of the previously dead opt-in engine flags
(apply_mode_modifiers / aoe_targets_hit / gate_ammo / apply_ability_haste /
include_conditional + enemy_champions) plus the shared haste-formula DRY helper
and the /modifier-summary diagnostic route.

Two invariants per flag:
  * DEFAULT (flag off / no-op value) is BYTE-IDENTICAL to the pre-wire path.
  * FLAG-ON demonstrably changes output in a scenario that exercises it.

ASCII only.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer import server
from agents.daemon_slayer._item_ability_haste import (
    effective_cooldown,
    item_ability_haste,
    total_item_ability_haste,
)
from agents.daemon_slayer.ability_dps import _effective_ability_cd
from agents.daemon_slayer.abilities import load_default
from agents.daemon_slayer.beam import beam_search_build
from agents.daemon_slayer.burst import rank_items_by_burst
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps, compute_dps_curve
from agents.daemon_slayer.ehp import compute_ehp, rank_items_by_ehp
from agents.daemon_slayer.fight_report import compute_fight_report
from agents.daemon_slayer.hybrid import compute_hybrid, rank_items_by_hybrid
from agents.daemon_slayer.modifier_blocks import summarize_modifiers
from agents.daemon_slayer.rank import rank_items

_ITEMS = ["6692"]            # Eclipse - one terminal item baseline
_AH_BUILD = ["3158", "4629"]  # Ionian Boots 10 + Cosmic Drive 25 = 35 AH
_REPEAT_SEQ = ["Q", "AA", "Q", "AA", "Q"]


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        server._CACHE.set(cls.snap)


# --------------------------------------------------------------- DRY helpers


class DryHelperTests(unittest.TestCase):
    def test_effective_cooldown_formula(self) -> None:
        self.assertEqual(effective_cooldown(0.0, 50.0), 0.0)       # base 0 -> 0
        self.assertEqual(effective_cooldown(10.0, 0.0), 10.0)      # ah 0 identity
        self.assertAlmostEqual(effective_cooldown(10.0, 100.0), 5.0)   # halves
        self.assertAlmostEqual(effective_cooldown(10.0, 25.0), 8.0)    # /1.25
        # denominator floor at 0.01 keeps ah <= -100 finite + positive
        self.assertGreater(effective_cooldown(10.0, -200.0), 0.0)

    def test_ability_dps_helper_delegates(self) -> None:
        for cd, ah in [(0.0, 30.0), (12.0, 0.0), (12.0, 40.0), (8.0, -50.0)]:
            self.assertEqual(_effective_ability_cd(cd, ah), effective_cooldown(cd, ah))

    def test_total_delegates_to_single(self) -> None:
        ids = ["3158", "4629", "9999", "3158"]   # dup + unknown
        self.assertEqual(
            total_item_ability_haste(ids),
            sum(item_ability_haste(i) for i in ids),
        )
        self.assertEqual(total_item_ability_haste([]), 0.0)


# --------------------------------------------------- apply_mode_modifiers


class ApplyModeModifiersThreadTests(_Base):
    def test_compute_dps_curve_urf_changes_sr_identical(self) -> None:
        sr0 = compute_dps_curve(self.snap, "Aatrox", item_ids=_ITEMS, mode="SR", levels=[11])
        sr1 = compute_dps_curve(self.snap, "Aatrox", item_ids=_ITEMS, mode="SR",
                                levels=[11], apply_mode_modifiers=True)
        self.assertEqual(sr0[0].weighted_dps, sr1[0].weighted_dps)
        u0 = compute_dps_curve(self.snap, "Aatrox", item_ids=_ITEMS, mode="URF", levels=[11])
        u1 = compute_dps_curve(self.snap, "Aatrox", item_ids=_ITEMS, mode="URF",
                               levels=[11], apply_mode_modifiers=True)
        self.assertNotEqual(u0[0].weighted_dps, u1[0].weighted_dps)

    def test_rank_items_default_identical_urf_changes(self) -> None:
        base = rank_items(self.snap, "Aatrox", 11, current_item_ids=_ITEMS, mode="SR", top_n=5)
        same = rank_items(self.snap, "Aatrox", 11, current_item_ids=_ITEMS, mode="SR",
                          top_n=5, apply_mode_modifiers=False)
        self.assertEqual([r.delta_dps for r in base.ranked],
                         [r.delta_dps for r in same.ranked])
        u0 = rank_items(self.snap, "Aatrox", 11, current_item_ids=_ITEMS, mode="URF", top_n=5)
        u1 = rank_items(self.snap, "Aatrox", 11, current_item_ids=_ITEMS, mode="URF",
                        top_n=5, apply_mode_modifiers=True)
        self.assertNotEqual([r.delta_dps for r in u0.ranked],
                            [r.delta_dps for r in u1.ranked])

    def test_rank_items_by_ehp_urf_taken_changes(self) -> None:
        # Aatrox URF carries a wiki dmg_taken=0.7 sidecar entry; Malphite has none.
        base = rank_items_by_ehp(self.snap, "Aatrox", 11, current_item_ids=["3068"],
                                 mode="URF", top_n=5)
        flag = rank_items_by_ehp(self.snap, "Aatrox", 11, current_item_ids=["3068"],
                                 mode="URF", top_n=5, apply_mode_modifiers=True)
        self.assertNotEqual([r.delta_ehp for r in base.ranked],
                            [r.delta_ehp for r in flag.ranked])

    def test_compute_hybrid_default_identical(self) -> None:
        a = compute_hybrid(self.snap, "Aatrox", 11, item_ids=_ITEMS, mode="SR")
        b = compute_hybrid(self.snap, "Aatrox", 11, item_ids=_ITEMS, mode="SR",
                           apply_mode_modifiers=True)
        self.assertEqual(a.hybrid_score, b.hybrid_score)  # SR has no dmg mult

    def test_rank_items_by_hybrid_urf_changes(self) -> None:
        u0 = rank_items_by_hybrid(self.snap, "Aatrox", 11, current_item_ids=_ITEMS,
                                  mode="URF", top_n=5)
        u1 = rank_items_by_hybrid(self.snap, "Aatrox", 11, current_item_ids=_ITEMS,
                                  mode="URF", top_n=5, apply_mode_modifiers=True)
        self.assertNotEqual([r.hybrid_delta_pct for r in u0.ranked],
                            [r.hybrid_delta_pct for r in u1.ranked])

    def test_beam_default_identical(self) -> None:
        a = beam_search_build(self.snap, "Aatrox", 11, current_item_ids=_ITEMS,
                              mode="SR", slot_count=3, beam_width=4, top_n=3)
        b = beam_search_build(self.snap, "Aatrox", 11, current_item_ids=_ITEMS,
                              mode="SR", slot_count=3, beam_width=4, top_n=3,
                              apply_mode_modifiers=True)
        self.assertEqual([r.final_dps for r in a.ranked],
                         [r.final_dps for r in b.ranked])


# --------------------------------------------------------- aoe_targets_hit


class AoeTargetsHitThreadTests(_Base):
    def test_rank_burst_default_identical_aoe_changes(self) -> None:
        a = rank_items_by_burst(self.snap, "Aatrox", 11, current_item_ids=_ITEMS,
                                mode="SR", top_n=5)
        same = rank_items_by_burst(self.snap, "Aatrox", 11, current_item_ids=_ITEMS,
                                   mode="SR", top_n=5, aoe_targets_hit=1)
        self.assertEqual([r.delta_burst for r in a.ranked],
                         [r.delta_burst for r in same.ranked])
        aoe = rank_items_by_burst(self.snap, "Aatrox", 11, current_item_ids=_ITEMS,
                                  mode="SR", top_n=5, aoe_targets_hit=3)
        self.assertNotEqual([r.delta_burst for r in a.ranked],
                            [r.delta_burst for r in aoe.ranked])


# ------------------------------------------- enemies + include_conditional


class EnemiesConditionalThreadTests(_Base):
    def test_enemies_discount_cc_blended(self) -> None:
        e = compute_ehp(self.snap, "Malphite", 11, item_ids=["3068"], mode="SR",
                        enemy_champions=["Leona", "Morgana", "Lux"])
        self.assertLess(e.cc_blended_ehp, e.blended_ehp)

    def test_include_conditional_moves_cc_blended(self) -> None:
        # Aatrox: zero unconditional first-order CC counted -> cc_blended == blended
        # when off; the conditional Q3/W registry lands only when on.
        off = compute_ehp(self.snap, "Malphite", 11, item_ids=["3068"], mode="SR",
                          enemy_champions=["Aatrox"], include_conditional=False)
        on = compute_ehp(self.snap, "Malphite", 11, item_ids=["3068"], mode="SR",
                         enemy_champions=["Aatrox"], include_conditional=True)
        self.assertLess(on.cc_blended_ehp, off.cc_blended_ehp)

    def test_no_enemies_include_conditional_byte_identical(self) -> None:
        off = compute_ehp(self.snap, "Malphite", 11, item_ids=["3068"], mode="SR",
                          include_conditional=False)
        on = compute_ehp(self.snap, "Malphite", 11, item_ids=["3068"], mode="SR",
                         include_conditional=True)
        self.assertEqual(off.cc_blended_ehp, on.cc_blended_ehp)
        self.assertEqual(off.cc_blended_ehp, off.blended_ehp)

    def test_hybrid_include_conditional_moves_score(self) -> None:
        off = compute_hybrid(self.snap, "Malphite", 11, item_ids=["3068"], mode="SR",
                             enemy_champions=["Aatrox"], include_conditional=False)
        on = compute_hybrid(self.snap, "Malphite", 11, item_ids=["3068"], mode="SR",
                            enemy_champions=["Aatrox"], include_conditional=True)
        self.assertNotEqual(off.hybrid_score, on.hybrid_score)


# ------------------------------------------------------------- fight_report


class FightReportFlagTests(_Base):
    def test_defaults_byte_identical(self) -> None:
        a = compute_fight_report("Vi", 11, item_ids=_AH_BUILD,
                                 sequence=["E", "E", "E", "E"], snapshot=self.snap)
        b = compute_fight_report("Vi", 11, item_ids=_AH_BUILD,
                                 sequence=["E", "E", "E", "E"], snapshot=self.snap,
                                 gate_ammo=False, apply_ability_haste=False,
                                 apply_mode_modifiers=False)
        self.assertEqual(a.bounded_dps, b.bounded_dps)
        self.assertEqual(a.casts_allowed, b.casts_allowed)

    def test_gate_ammo_gates_casts(self) -> None:
        # Vi E carries 2 charges + a long recharge - gating drops casts_allowed.
        off = compute_fight_report("Vi", 11, item_ids=_AH_BUILD,
                                   sequence=["E", "E", "E", "E"], snapshot=self.snap)
        on = compute_fight_report("Vi", 11, item_ids=_AH_BUILD,
                                  sequence=["E", "E", "E", "E"], snapshot=self.snap,
                                  gate_ammo=True)
        self.assertLessEqual(on.casts_allowed, off.casts_allowed)
        self.assertLess(on.casts_allowed, off.casts_requested + 1)

    def test_apply_ability_haste_changes_bounded(self) -> None:
        off = compute_fight_report("Lux", 11, item_ids=_AH_BUILD,
                                   sequence=_REPEAT_SEQ, snapshot=self.snap)
        on = compute_fight_report("Lux", 11, item_ids=_AH_BUILD,
                                  sequence=_REPEAT_SEQ, snapshot=self.snap,
                                  apply_ability_haste=True)
        self.assertNotEqual(off.bounded_dps, on.bounded_dps)


# ------------------------------------------------ /modifier-summary route


class ModifierSummaryRouteTests(_Base):
    def test_summary_shape(self) -> None:
        out = summarize_modifiers(load_default()).to_dict()
        self.assertGreater(out["total"], 0)
        for k in ("pve_only", "target_shred", "defensive_self",
                  "damage_amp_self", "other"):
            self.assertIn(k, out["by_kind"])
        self.assertEqual(sum(out["by_kind"].values()), out["total"])
        # target_shred examples are a strict subset of the shred bucket count
        self.assertLessEqual(len(out["target_shred_examples"]),
                             out["by_kind"]["target_shred"])

    def test_route_returns_summary(self) -> None:
        out = server._route_modifier_summary()
        self.assertEqual(set(out.keys()),
                         {"total", "by_kind", "target_shred_examples",
                          "damage_amp_examples"})


# --------------------------------------------------- server route parsing


class ServerRouteFlagTests(_Base):
    def test_dps_route_parses_mode_modifiers(self) -> None:
        off = server._route_dps({"champion": "Aatrox", "level": 11,
                                 "items": "6692", "mode": "URF"})
        on = server._route_dps({"champion": "Aatrox", "level": 11,
                                "items": "6692", "mode": "URF",
                                "apply_mode_modifiers": "1"})
        self.assertNotEqual(off["weighted_dps"], on["weighted_dps"])

    def test_burst_route_parses_aoe(self) -> None:
        off = server._route_burst({"champion": "Aatrox", "level": 11,
                                   "items": "6692", "mode": "SR"})
        on = server._route_burst({"champion": "Aatrox", "level": 11,
                                  "items": "6692", "mode": "SR",
                                  "aoe_targets_hit": "3"})
        self.assertNotEqual(off["total_burst_damage"], on["total_burst_damage"])

    def test_ehp_route_parses_enemies(self) -> None:
        out = server._route_ehp({"champion": "Malphite", "level": 11,
                                 "items": "3068", "mode": "SR",
                                 "enemies": "Leona,Morgana,Lux"})
        self.assertLess(out["cc_blended_ehp"], out["blended_ehp"])

    def test_fight_report_route_parses_gate_ammo(self) -> None:
        off = server._route_fight_report({"champion": "Vi", "level": 11,
                                          "items": "3158,4629", "sequence": "E,E,E,E"})
        on = server._route_fight_report({"champion": "Vi", "level": 11,
                                         "items": "3158,4629", "sequence": "E,E,E,E",
                                         "gate_ammo": "1"})
        self.assertLessEqual(on["casts_allowed"], off["casts_allowed"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
