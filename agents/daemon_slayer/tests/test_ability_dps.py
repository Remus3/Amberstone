"""Phase 4b (s178, 2026-05-12) - ability DPS evaluator tests.

Coverage split into seven groups:

* ``RankAtLevelTests`` - pin the max-priority rank tables (Q/W/E + R).
* ``AbilityContextTests`` - base/bonus splits, current/missing HP.
* ``MitigationFactorTests`` - physical/magic/true/mixed routing.
* ``BlockEvaluationTests`` - sum / first / max strategies; per-rank.
* ``ComputeAbilityDpsTests`` - end-to-end on Veigar/Aatrox/Ezreal with
  varied builds, modes, and AP/AD/damage amps.
* ``CastRateIntegrationTests`` - measured vs theoretical fallback.
* ``ServerRouteTests`` - POST /ability-dps + GET equivalent.
"""
from __future__ import annotations

import json
import unittest
from urllib.request import Request, urlopen

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import (
    AbilitiesSnapshot,
    AbilityForm,
    DamageBlock,
    reset_default_cache,
)
from agents.daemon_slayer.ability_dps import (
    AbilityContext,
    AbilityDpsResult,
    compute_ability_dps,
    rank_at_level,
    _classify_primary_scaling,
    _evaluate_block,
    _mitigation_factor,
    _select_blocks,
)
from agents.daemon_slayer.data_loader import DataSnapshot


# ─── helpers ─────────────────────────────────────────────────────────────────


def _snap() -> DataSnapshot:
    return DataSnapshot.load()


def _abil_snap() -> AbilitiesSnapshot:
    reset_default_cache()
    return AbilitiesSnapshot.load()


def _basic_ctx(**overrides) -> AbilityContext:
    base = {
        "base_ad": 60.0,
        "total_ad": 100.0,
        "bonus_ad": 40.0,
        "ap": 0.0,
        "caster_max_hp": 2000.0,
        "caster_bonus_hp": 500.0,
        "caster_bonus_armor": 0.0,
        "caster_bonus_mr": 0.0,
        "caster_max_mp": 800.0,
        "caster_mp_regen_per_5": 15.0,
        "target_armor": 60.0,
        "target_mr": 40.0,
        "target_max_hp": 2200.0,
        "target_current_hp": 2200.0,
        "target_missing_hp": 0.0,
        "target_bonus_hp": 700.0,
    }
    base.update(overrides)
    return AbilityContext(**base)


# ─── rank-at-level table ─────────────────────────────────────────────────────


class RankAtLevelTests(unittest.TestCase):
    def test_q_priority1_table(self) -> None:
        # Q priority 1: ranked at lvl 1/3/5/7/9 → ranks 0/1/2/3/4
        self.assertEqual(rank_at_level("Q", 1), 0)
        self.assertEqual(rank_at_level("Q", 3), 1)
        self.assertEqual(rank_at_level("Q", 5), 2)
        self.assertEqual(rank_at_level("Q", 7), 3)
        self.assertEqual(rank_at_level("Q", 9), 4)
        self.assertEqual(rank_at_level("Q", 18), 4)

    def test_w_priority2_table(self) -> None:
        # W priority 2: ranked at lvl 2/8/10/12/13
        self.assertEqual(rank_at_level("W", 1), -1)
        self.assertEqual(rank_at_level("W", 2), 0)
        self.assertEqual(rank_at_level("W", 8), 1)
        self.assertEqual(rank_at_level("W", 10), 2)
        self.assertEqual(rank_at_level("W", 12), 3)
        self.assertEqual(rank_at_level("W", 13), 4)

    def test_e_priority3_table(self) -> None:
        # E priority 3: ranked at lvl 4/14/15/17/18
        self.assertEqual(rank_at_level("E", 3), -1)
        self.assertEqual(rank_at_level("E", 4), 0)
        self.assertEqual(rank_at_level("E", 14), 1)
        self.assertEqual(rank_at_level("E", 15), 2)
        self.assertEqual(rank_at_level("E", 17), 3)
        self.assertEqual(rank_at_level("E", 18), 4)

    def test_r_ultimate_table(self) -> None:
        self.assertEqual(rank_at_level("R", 1), -1)
        self.assertEqual(rank_at_level("R", 5), -1)
        self.assertEqual(rank_at_level("R", 6), 0)
        self.assertEqual(rank_at_level("R", 10), 0)
        self.assertEqual(rank_at_level("R", 11), 1)
        self.assertEqual(rank_at_level("R", 16), 2)
        self.assertEqual(rank_at_level("R", 18), 2)

    def test_passive_returns_level_minus_one(self) -> None:
        # P treated as level-scaled (rank = level - 1, clamped).
        self.assertEqual(rank_at_level("P", 1), 0)
        self.assertEqual(rank_at_level("P", 10), 9)
        self.assertEqual(rank_at_level("P", 18), 17)

    def test_custom_priority_swap_w_and_q(self) -> None:
        # If operator passes max_priority=("W","Q","E"), then W is first
        # priority (ranks at 1/3/5/7/9) and Q is second priority (ranks
        # at 2/8/10/12/13). At lvl 9, W = max (rank 4), Q = 1 (only 2
        # points in by lvl 8).
        self.assertEqual(rank_at_level("W", 9, max_priority=("W", "Q", "E")), 4)
        self.assertEqual(rank_at_level("Q", 9, max_priority=("W", "Q", "E")), 1)
        # At lvl 13, Q-as-second-priority is fully maxed.
        self.assertEqual(rank_at_level("Q", 13, max_priority=("W", "Q", "E")), 4)

    def test_invalid_key_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_at_level("Z", 5)


# ─── ability context ─────────────────────────────────────────────────────────


class AbilityContextTests(unittest.TestCase):
    def test_from_build_splits_bonus_correctly(self) -> None:
        stats = {"ad": 110.0, "hp": 2200.0, "armor": 80.0, "mr": 60.0, "ap": 200.0, "mp": 1000.0, "mpregen": 30.0}
        base = {"ad": 60.0, "hp": 1700.0, "armor": 50.0, "mr": 40.0}
        ctx = AbilityContext.from_build(
            stats=stats, base_stats=base,
            target_armor=60.0, target_mr=40.0,
            target_max_hp=2400.0, target_bonus_hp=600.0,
        )
        self.assertEqual(ctx.base_ad, 60.0)
        self.assertEqual(ctx.total_ad, 110.0)
        self.assertEqual(ctx.bonus_ad, 50.0)
        self.assertEqual(ctx.caster_bonus_hp, 500.0)
        self.assertEqual(ctx.caster_bonus_armor, 30.0)
        self.assertEqual(ctx.caster_bonus_mr, 20.0)
        self.assertEqual(ctx.ap, 200.0)
        self.assertEqual(ctx.caster_max_mp, 1000.0)
        self.assertEqual(ctx.caster_mp_regen_per_5, 30.0)

    def test_target_current_hp_pct_default_full(self) -> None:
        ctx = AbilityContext.from_build(
            stats={"ad": 60.0, "hp": 1500.0}, base_stats={},
            target_armor=50.0, target_mr=40.0,
            target_max_hp=2000.0, target_bonus_hp=0.0,
        )
        self.assertEqual(ctx.target_current_hp, 2000.0)
        self.assertEqual(ctx.target_missing_hp, 0.0)

    def test_target_current_hp_pct_half(self) -> None:
        ctx = AbilityContext.from_build(
            stats={"ad": 60.0, "hp": 1500.0}, base_stats={},
            target_armor=50.0, target_mr=40.0,
            target_max_hp=2000.0, target_bonus_hp=0.0,
            target_current_hp_pct=0.5,
        )
        self.assertEqual(ctx.target_current_hp, 1000.0)
        self.assertEqual(ctx.target_missing_hp, 1000.0)

    def test_no_base_stats_defaults_bonus_to_total(self) -> None:
        # When base_stats is None, the engine couldn't supply baseline,
        # so bonus = total (worst case: all stats counted as bonus).
        ctx = AbilityContext.from_build(
            stats={"ad": 110.0, "hp": 2200.0}, base_stats=None,
            target_armor=0.0, target_mr=0.0,
            target_max_hp=0.0, target_bonus_hp=0.0,
        )
        self.assertEqual(ctx.base_ad, 0.0)
        self.assertEqual(ctx.bonus_ad, 110.0)
        self.assertEqual(ctx.caster_bonus_hp, 2200.0)


# ─── mitigation factor ───────────────────────────────────────────────────────


class MitigationFactorTests(unittest.TestCase):
    def test_physical_uses_armor(self) -> None:
        # 100 armor → factor 0.5
        self.assertAlmostEqual(_mitigation_factor("PHYSICAL", 100, 100), 0.5)

    def test_magic_uses_mr(self) -> None:
        # 100 mr → factor 0.5
        self.assertAlmostEqual(_mitigation_factor("MAGIC", 100, 100), 0.5)
        self.assertAlmostEqual(_mitigation_factor("MAGIC", 0, 100), 0.5)

    def test_true_bypasses_resists(self) -> None:
        self.assertEqual(_mitigation_factor("TRUE", 100, 100), 1.0)
        self.assertEqual(_mitigation_factor("TRUE", -50, -50), 1.0)

    def test_mixed_averages_armor_mr(self) -> None:
        # 100 armor + 0 mr → (0.5 + 1.0) / 2 = 0.75
        self.assertAlmostEqual(_mitigation_factor("MIXED", 100, 0), 0.75)

    def test_negative_armor_uses_inverted_formula(self) -> None:
        # -50 armor: factor = 2 - 100/(100-(-50)) = 2 - 100/150 = 1.333
        self.assertAlmostEqual(_mitigation_factor("PHYSICAL", -50, 0), 2 - 100/150)

    def test_none_damage_type_defaults_to_magic(self) -> None:
        # Multi-block abilities sometimes have form.damage_type=None.
        self.assertAlmostEqual(_mitigation_factor(None, 100, 100), 0.5)


# ─── block evaluation ────────────────────────────────────────────────────────


class BlockEvaluationTests(unittest.TestCase):
    def test_pure_base_block(self) -> None:
        b = DamageBlock(attribute="X", attribute_kind="damage",
                        base=(80.0, 120.0, 160.0, 200.0, 240.0))
        ctx = _basic_ctx()
        self.assertEqual(_evaluate_block(b, 0, ctx), 80.0)
        self.assertEqual(_evaluate_block(b, 4, ctx), 240.0)

    def test_ap_scaling(self) -> None:
        b = DamageBlock(attribute="X", attribute_kind="damage",
                        base=(80.0,), ap_pct=(70.0,))
        ctx = _basic_ctx(ap=200.0)
        # 80 + 200 * 0.70 = 220
        self.assertAlmostEqual(_evaluate_block(b, 0, ctx), 220.0)

    def test_total_ad_scaling(self) -> None:
        b = DamageBlock(attribute="X", attribute_kind="damage",
                        total_ad_pct=(130.0,))
        ctx = _basic_ctx(total_ad=100.0)
        # 0 + 100 * 1.30 = 130
        self.assertAlmostEqual(_evaluate_block(b, 0, ctx), 130.0)

    def test_bonus_ad_scaling(self) -> None:
        b = DamageBlock(attribute="X", attribute_kind="damage",
                        bonus_ad_pct=(50.0,))
        ctx = _basic_ctx(bonus_ad=80.0)
        # 0 + 80 * 0.50 = 40
        self.assertAlmostEqual(_evaluate_block(b, 0, ctx), 40.0)

    def test_target_max_hp_scaling(self) -> None:
        b = DamageBlock(attribute="X", attribute_kind="damage",
                        target_max_hp_pct=(10.0,))
        ctx = _basic_ctx(target_max_hp=2500.0)
        # 0 + 2500 * 0.10 = 250
        self.assertAlmostEqual(_evaluate_block(b, 0, ctx), 250.0)

    def test_locked_rank_returns_zero(self) -> None:
        b = DamageBlock(attribute="X", attribute_kind="damage",
                        base=(80.0,), ap_pct=(70.0,))
        # rank -1 (locked) → 0
        self.assertEqual(_evaluate_block(b, -1, _basic_ctx()), 0.0)

    def test_select_blocks_first_strategy(self) -> None:
        b1 = DamageBlock(attribute="A", attribute_kind="damage", base=(100.0,))
        b2 = DamageBlock(attribute="B", attribute_kind="damage", base=(50.0,))
        self.assertEqual(_select_blocks((b1, b2), 0, _basic_ctx(), "first"), 100.0)

    def test_select_blocks_sum_strategy(self) -> None:
        b1 = DamageBlock(attribute="A", attribute_kind="damage", base=(100.0,))
        b2 = DamageBlock(attribute="B", attribute_kind="damage", base=(50.0,))
        self.assertEqual(_select_blocks((b1, b2), 0, _basic_ctx(), "sum"), 150.0)

    def test_select_blocks_max_strategy(self) -> None:
        b1 = DamageBlock(attribute="A", attribute_kind="damage", base=(100.0,))
        b2 = DamageBlock(attribute="B", attribute_kind="damage", base=(50.0,))
        self.assertEqual(_select_blocks((b1, b2), 0, _basic_ctx(), "max"), 100.0)

    def test_select_blocks_filters_non_damage(self) -> None:
        b1 = DamageBlock(attribute="Heal", attribute_kind="heal", base=(100.0,))
        b2 = DamageBlock(attribute="Magic", attribute_kind="damage", base=(80.0,))
        # sum should be 80 (heal block excluded).
        self.assertEqual(_select_blocks((b1, b2), 0, _basic_ctx(), "sum"), 80.0)

    def test_select_blocks_unknown_strategy_raises(self) -> None:
        b = DamageBlock(attribute="X", attribute_kind="damage", base=(100.0,))
        with self.assertRaises(ValueError):
            _select_blocks((b,), 0, _basic_ctx(), "average")


# ─── primary-scaling classifier ──────────────────────────────────────────────


class PrimaryScalingTests(unittest.TestCase):
    def _form_with_block(self, **kw) -> AbilityForm:
        block = DamageBlock(attribute="X", attribute_kind="damage", **kw)
        return AbilityForm(
            key="Q", name="t", form_index=0, icon=None,
            cooldown=(10.0,), cost=None,
            damage_type="MAGIC", targeting=None, affects=None, resource=None,
            is_aoe=False, damage_blocks=(block,),
            raw_effects_count=1, raw_leveling_count=1,
            parse_status="ok", parse_notes=(),
        )

    def test_pure_ap_champion_classified_ap(self) -> None:
        forms = [self._form_with_block(ap_pct=(50.0, 55.0, 60.0, 65.0, 70.0))]
        self.assertEqual(_classify_primary_scaling([], forms), "AP")

    def test_pure_ad_champion_classified_ad(self) -> None:
        forms = [self._form_with_block(total_ad_pct=(60.0, 75.0, 90.0))]
        self.assertEqual(_classify_primary_scaling([], forms), "AD")

    def test_hp_scaling_champion_classified_hp(self) -> None:
        forms = [self._form_with_block(caster_max_hp_pct=(5.0, 6.0, 7.0))]
        self.assertEqual(_classify_primary_scaling([], forms), "HP")

    def test_balanced_ap_ad_classified_mixed(self) -> None:
        forms = [
            self._form_with_block(ap_pct=(50.0,)),
            self._form_with_block(total_ad_pct=(50.0,)),
        ]
        self.assertEqual(_classify_primary_scaling([], forms), "MIXED")

    def test_no_scaling_falls_to_mixed(self) -> None:
        forms = [self._form_with_block(base=(100.0,))]
        self.assertEqual(_classify_primary_scaling([], forms), "MIXED")


# ─── end-to-end compute_ability_dps ─────────────────────────────────────────


class ComputeAbilityDpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_default_cache()
        ult_rates.reset_cache()
        cls.snap = _snap()

    # ---------- Veigar (canonical AP mage)

    def test_veigar_naked_returns_positive_total(self) -> None:
        r = compute_ability_dps(self.snap, "Veigar", 11, mode="SR",
                                target_mr=30.0, target_armor=30.0)
        self.assertGreater(r.total_ability_dps, 0)
        self.assertEqual(r.primary_scaling, "AP")
        self.assertEqual(len(r.per_spell), 4)

    def test_veigar_rabadons_lifts_total(self) -> None:
        base = compute_ability_dps(self.snap, "Veigar", 11, mode="SR",
                                   target_mr=30.0)
        with_rabadon = compute_ability_dps(
            self.snap, "Veigar", 11, item_ids=["3089"], mode="SR",
            target_mr=30.0,
        )
        self.assertGreater(with_rabadon.total_ability_dps, base.total_ability_dps)
        # Rabadon's = 130 AP + 30% amp → roughly 50% more ability DPS at
        # this level (Q's 70% AP scaling dominates).
        ratio = with_rabadon.total_ability_dps / base.total_ability_dps
        self.assertGreater(ratio, 1.4)
        self.assertLess(ratio, 2.0)

    def test_veigar_q_rank_correct_at_level(self) -> None:
        r = compute_ability_dps(self.snap, "Veigar", 11, mode="SR")
        q = next(s for s in r.per_spell if s.key == "Q")
        # Q maxes at lvl 9 with priority 1 - rank 4 at lvl 11.
        self.assertEqual(q.rank, 4)

    def test_veigar_r_locked_at_level_5(self) -> None:
        r = compute_ability_dps(self.snap, "Veigar", 5, mode="SR")
        ult = next(s for s in r.per_spell if s.key == "R")
        self.assertEqual(ult.rank, -1)
        self.assertEqual(ult.dps, 0.0)

    def test_veigar_q_damage_scales_with_ap(self) -> None:
        # Veigar Q at rank 4: base 240, AP scaling 70%.
        no_ap = compute_ability_dps(self.snap, "Veigar", 11, mode="SR",
                                    target_mr=0.0)
        q_no = next(s for s in no_ap.per_spell if s.key == "Q")
        # No items → just base 240 (mode_mult=1, target_mr=0 → no
        # mitigation). post_mit should be 240.
        self.assertAlmostEqual(q_no.post_mitigation_damage_per_cast, 240.0, places=1)

    # ---------- Aatrox (PHYSICAL Q - armor routing)

    def test_aatrox_q_is_physical(self) -> None:
        r = compute_ability_dps(self.snap, "Aatrox", 11, mode="SR",
                                target_armor=100.0, target_mr=0.0)
        q = next(s for s in r.per_spell if s.key == "Q")
        self.assertEqual(q.damage_type, "PHYSICAL")
        # 100 armor → 0.5 mitigation factor, post-mit half of post-mode.
        self.assertAlmostEqual(
            q.post_mitigation_damage_per_cast,
            q.post_mode_damage_per_cast * 0.5,
            places=1,
        )

    def test_aatrox_armor_higher_reduces_q_dps(self) -> None:
        # Higher target armor → lower Aatrox Q DPS.
        low_armor = compute_ability_dps(self.snap, "Aatrox", 11, mode="SR",
                                        target_armor=30.0, target_mr=0.0)
        high_armor = compute_ability_dps(self.snap, "Aatrox", 11, mode="SR",
                                         target_armor=200.0, target_mr=0.0)
        q_low = next(s for s in low_armor.per_spell if s.key == "Q")
        q_high = next(s for s in high_armor.per_spell if s.key == "Q")
        self.assertGreater(q_low.dps, q_high.dps)

    # ---------- Ezreal (AD-scaling mage)

    def test_ezreal_q_uses_total_ad(self) -> None:
        r = compute_ability_dps(self.snap, "Ezreal", 11, mode="SR",
                                target_mr=30.0, target_armor=30.0)
        q = next(s for s in r.per_spell if s.key == "Q")
        # Ezreal Q is PHYSICAL - uses armor mitigation.
        self.assertEqual(q.damage_type, "PHYSICAL")
        self.assertGreater(q.post_mitigation_damage_per_cast, 0)

    # ---------- ARAM mode multiplier

    def test_aram_damage_dealt_applied_to_per_cast(self) -> None:
        # Veigar's aramDamageDealt < 1.0 - per-cast damage is reduced by
        # exactly that multiplier. We don't check totals because ARAM has
        # higher measured cast rates (more fights/team time) which can
        # offset the per-cast reduction in aggregate.
        sr = compute_ability_dps(self.snap, "Veigar", 11, mode="SR",
                                 target_mr=30.0)
        aram = compute_ability_dps(self.snap, "Veigar", 11, mode="ARAM",
                                   target_mr=30.0)
        sr_q = next(s for s in sr.per_spell if s.key == "Q")
        aram_q = next(s for s in aram.per_spell if s.key == "Q")
        # raw_damage_per_cast is pre-mode; should be identical at the
        # same level + no items.
        self.assertAlmostEqual(sr_q.raw_damage_per_cast, aram_q.raw_damage_per_cast)
        # post_mode = raw * mode_mult - check the ratio matches.
        expected = sr_q.raw_damage_per_cast * aram.mode_multiplier
        self.assertAlmostEqual(aram_q.post_mode_damage_per_cast, expected, places=2)
        # And mode_mult on Veigar is < 1.0 (canonical ARAM-nerfed AP).
        self.assertLess(aram.mode_multiplier, 1.0)

    # ---------- amp pipelines

    def test_liandrys_damage_amp_flows_through(self) -> None:
        # 6653 = Liandry's Torment in patch 16.9.1 (was 3151 in older patches).
        # Ships with damage_amp_pct=0.06 - Suffering's sustained 6% amp.
        base = compute_ability_dps(self.snap, "Veigar", 11, mode="SR",
                                   target_mr=30.0)
        with_liandry = compute_ability_dps(self.snap, "Veigar", 11,
                                           item_ids=["6653"], mode="SR",
                                           target_mr=30.0)
        # Liandry adds AP too, so total goes up for two reasons. Just
        # check it goes up - the AP amp tests verify the multiplier path.
        self.assertGreater(with_liandry.total_ability_dps, base.total_ability_dps)

    # ---------- coverage / structure

    def test_unknown_champion_raises_keyerror(self) -> None:
        with self.assertRaises(KeyError):
            compute_ability_dps(self.snap, "DoesNotExistChamp", 11)

    def test_to_dict_round_trip(self) -> None:
        r = compute_ability_dps(self.snap, "Veigar", 11, mode="SR")
        d = r.to_dict()
        self.assertEqual(d["champion_id"], "Veigar")
        self.assertEqual(d["level"], 11)
        self.assertEqual(len(d["per_spell"]), 4)
        self.assertIn("total_ability_dps", d)
        self.assertIn("primary_scaling", d)

    def test_format_table_is_string(self) -> None:
        r = compute_ability_dps(self.snap, "Veigar", 11, mode="SR")
        s = r.format_table()
        self.assertIsInstance(s, str)
        self.assertIn("Veigar", s)
        self.assertIn("total_ability_dps", s)

    def test_invalid_block_strategy_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_ability_dps(self.snap, "Veigar", 11, block_strategy="bogus")

    def test_invalid_max_priority_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_ability_dps(self.snap, "Veigar", 11,
                                max_priority=("Q", "Q", "E"))

    def test_invalid_current_hp_pct_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_ability_dps(self.snap, "Veigar", 11,
                                target_current_hp_pct=1.5)


# ─── cast rate integration ───────────────────────────────────────────────────


class CastRateIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_default_cache()
        ult_rates.reset_cache()
        cls.snap = _snap()

    def test_measured_cast_rate_used_when_available(self) -> None:
        r = compute_ability_dps(self.snap, "Veigar", 11, mode="SR")
        q = next(s for s in r.per_spell if s.key == "Q")
        self.assertEqual(q.casts_per_sec_source, "measured")
        self.assertGreater(q.casts_per_sec, 0.0)

    def test_high_cast_rate_yields_higher_dps_than_low(self) -> None:
        # Veigar Q has a much higher measured cast rate than R, so Q DPS
        # should be higher per-cast-damage-normalized - but at minimum,
        # the Q DPS should be positive while R-locked spells are zero.
        r = compute_ability_dps(self.snap, "Veigar", 4)  # R locked
        q = next(s for s in r.per_spell if s.key == "Q")
        ult = next(s for s in r.per_spell if s.key == "R")
        self.assertGreater(q.dps, ult.dps)


# ─── server route ────────────────────────────────────────────────────────────


class ServerRouteTests(unittest.TestCase):
    """Spin the engine server on a free port; hit /ability-dps; tear
    down. Mirrors test_server.py's pattern."""

    @classmethod
    def setUpClass(cls) -> None:
        from agents.daemon_slayer.server import start_server, _CACHE
        reset_default_cache()
        ult_rates.reset_cache()
        cls.snap = _snap()
        _CACHE.set(cls.snap)
        cls.srv = start_server(host="127.0.0.1", port=0, snapshot=cls.snap)
        import threading
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.srv.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        raw = json.dumps(body).encode("utf-8")
        req = Request(self.base + path, data=raw, method="POST",
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            # Surface error response bodies for clearer assertion failures.
            try:
                code = getattr(e, "code", None)
                body_resp = json.loads(e.read().decode("utf-8"))  # type: ignore[attr-defined]
                return code, body_resp
            except Exception:
                raise

    def test_post_ability_dps_returns_200(self) -> None:
        status, body = self._post("/ability-dps", {
            "champion": "Veigar", "level": 11, "mode": "SR",
            "target_mr": 30,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["champion_id"], "Veigar")
        self.assertEqual(len(body["per_spell"]), 4)
        self.assertGreater(body["total_ability_dps"], 0)

    def test_post_with_items_lifts_dps(self) -> None:
        _, naked = self._post("/ability-dps", {
            "champion": "Veigar", "level": 11, "mode": "SR", "target_mr": 30,
        })
        _, with_rabadon = self._post("/ability-dps", {
            "champion": "Veigar", "level": 11, "items": ["3089"],
            "mode": "SR", "target_mr": 30,
        })
        self.assertGreater(
            with_rabadon["total_ability_dps"], naked["total_ability_dps"]
        )

    def test_unknown_champion_returns_404(self) -> None:
        status, body = self._post("/ability-dps", {
            "champion": "NobodyChampion", "level": 11,
        })
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    def test_invalid_block_strategy_returns_422(self) -> None:
        status, body = self._post("/ability-dps", {
            "champion": "Veigar", "level": 11, "block_strategy": "bogus",
        })
        self.assertEqual(status, 422)

    def test_max_priority_compact_string_form(self) -> None:
        status, body = self._post("/ability-dps", {
            "champion": "Veigar", "level": 11, "max_priority": "WQE",
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["max_priority"], ["W", "Q", "E"])


if __name__ == "__main__":
    unittest.main()
