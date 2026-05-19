"""P1-L17 (2026-05-19) - deep math-correctness audit of the 3 less-audited
archetype scorers: ``hps`` (enchanter), ``hybrid`` (bruiser), ``burst``
(assassin).

The DPS scorer + penetration + AS + stat-growth were deeply verified in
prior passes; these three were not. This module hand-derives every
expected value FROM the documented formula / the shipped Meraki+registry
source read at test time (no hardcoded magic numbers, no fragile
cross-item comparison asserts - every assertion is against the computed
scorer output recomputed independently in-test).

Hunt targets (all came back clean - these tests lock the correctness in):
  * hps: heal vs damage sign/term confusion; 0-AP handling; the
    documented ``per_proc = base + per_level*(L-1) + ap_scaling*AP``
    scaling; amp applied to direct throughput only (buff credit additive).
  * hybrid: ``hybrid_score == alpha*dps + beta*ehp`` with the EXACT
    archetype_weights.json default; the two components are the SAME
    numbers the standalone dps/ehp scorers produce (no divergent
    recompute); convex weighting (alpha+beta==1, both in [0,1]) for the
    shipped table; a pure-tank vs pure-AD item move the score the right
    way.
  * burst: fixed-combo total == sum of selected ability blocks + AA
    tokens; the AA token is not double-counted (mode/armor already folded
    into compute_dps.avg_attack_dmg, burst.py must NOT re-apply); combo
    window has no cast-time / cooldown gating in a single rotation (the
    documented Phase 5 design).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer.abilities import load_default as _load_abilities
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.ability_dps import (
    _armor_factor,
    _mitigation_factor,
    rank_at_level,
)
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer.hps import compute_hps
from agents.daemon_slayer.hybrid import (
    _hybrid_delta_pct,
    _load_archetype_weights,
    compute_hybrid,
    get_weights_for,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"


def _current_patch() -> str:
    return (_DATA_ROOT / "current.txt").read_text(encoding="utf-8").strip()


def _enchanter_registry() -> dict:
    """Read the shipped enchanter_items.json as raw JSON (the documented
    formula source - we recompute expected HPS from this, not from the
    scorer's own loader)."""
    path = _DATA_ROOT / _current_patch() / "enchanter_items.json"
    return json.loads(path.read_text(encoding="utf-8"))["items"]


# --- HPS: heal/shield throughput ---


class HpsDerivationTests(unittest.TestCase):
    """Hand-derive HPS straight from the registry formula and assert the
    scorer reproduces it. The documented model (hps.py docstring +
    enchanter_items.json schema):

        per_proc(L, AP) = base + per_level*(L-1) + ap_scaling*max(0,AP)
        raw_hps         = per_proc * procs_per_second * targets
        total           = (heal_raw + shield_raw)*amp*mode_mult + buff
        amp             = product(1 + heal_shield_amp_pct)
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        cls.reg = _enchanter_registry()

    def _per_proc(self, f: dict, key: str, level: int, ap: float) -> float:
        return (
            f[f"{key}_per_proc_base"]
            + f[f"{key}_per_proc_per_level"] * max(0, level - 1)
            + f[f"{key}_per_proc_ap_scaling"] * max(0.0, ap)
        )

    def test_redemption_hps_derived_from_registry(self) -> None:
        # Soraka has 0 AP naked at lvl 13; Redemption (3107) is pure heal.
        f = self.reg["3107"]
        level = 13
        r = compute_hps(self.snap, "Soraka", level=level, item_ids=["3107"])
        ap = r.ap
        heal_pp = self._per_proc(f, "heal", level, ap)
        exp_raw = heal_pp * f["heal_procs_per_second"] * f["heal_targets_per_proc"]
        exp_amp = 1.0 + f["heal_shield_amp_pct"]
        self.assertAlmostEqual(r.healing_hps_raw, exp_raw, places=4)
        self.assertAlmostEqual(r.amp_multiplier, exp_amp, places=6)
        self.assertAlmostEqual(r.healing_hps, exp_raw * exp_amp, places=4)
        # Redemption has NO shield terms - shield side must be exactly 0
        # (heal is never miscounted as shield or vice-versa).
        self.assertEqual(r.shielding_hps_raw, 0.0)
        self.assertEqual(r.shielding_hps, 0.0)
        # No buff credit on Redemption - total is purely the amped heal.
        self.assertAlmostEqual(
            r.total_throughput, exp_raw * exp_amp, places=4
        )

    def test_locket_is_pure_shield_not_heal(self) -> None:
        # Sign/term-confusion guard: Locket (3190) has shield terms only.
        f = self.reg["3190"]
        level = 11
        r = compute_hps(self.snap, "Soraka", level=level, item_ids=["3190"])
        shield_pp = self._per_proc(f, "shield", level, r.ap)
        exp_raw = (
            shield_pp
            * f["shield_procs_per_second"]
            * f["shield_targets_per_proc"]
        )
        self.assertAlmostEqual(r.shielding_hps_raw, exp_raw, places=4)
        # Heal side stays exactly 0 - shield output is not added to heal.
        self.assertEqual(r.healing_hps_raw, 0.0)
        self.assertEqual(r.healing_hps, 0.0)

    def test_helia_ap_scaling_zero_ap_vs_high_ap(self) -> None:
        # Helia (6620) is the only registry item with heal AP scaling.
        # 0-AP must use base+level only; high AP adds ap_scaling*AP exactly.
        f = self.reg["6620"]
        self.assertGreater(f["heal_per_proc_ap_scaling"], 0.0)
        level = 11
        # Naked Soraka (0 item AP). Derive with the scorer's own resolved AP.
        r0 = compute_hps(self.snap, "Soraka", level=level, item_ids=["6620"])
        pp0 = self._per_proc(f, "heal", level, r0.ap)
        exp0 = pp0 * f["heal_procs_per_second"] * f["heal_targets_per_proc"]
        self.assertAlmostEqual(r0.healing_hps_raw, exp0, places=4)
        # Rabadon's Deathcap (3089) injects raw AP -> ap term must grow the
        # per-proc by exactly ap_scaling * delta_ap.
        rA = compute_hps(
            self.snap, "Soraka", level=level, item_ids=["6620", "3089"]
        )
        ppA = self._per_proc(f, "heal", level, rA.ap)
        expA = ppA * f["heal_procs_per_second"] * f["heal_targets_per_proc"]
        self.assertAlmostEqual(rA.healing_hps_raw, expA, places=4)
        self.assertGreater(rA.ap, r0.ap)
        # The exact analytic delta in raw HPS attributable to AP scaling.
        analytic_delta = (
            f["heal_per_proc_ap_scaling"]
            * (rA.ap - r0.ap)
            * f["heal_procs_per_second"]
            * f["heal_targets_per_proc"]
        )
        self.assertAlmostEqual(
            rA.healing_hps_raw - r0.healing_hps_raw, analytic_delta, places=4
        )

    def test_amp_is_multiplicative_and_buff_is_additive(self) -> None:
        # Moonstone (6617, +30% amp, 0 direct) + Redemption (3107, heal +
        # 10% amp) + Ardent (3504, 0 direct, 15 buff, +10% amp).
        ids = ["6617", "3107", "3504"]
        level = 13
        r = compute_hps(self.snap, "Soraka", level=level, item_ids=ids)
        exp_amp = 1.0
        exp_buff = 0.0
        for iid in ids:
            f = self.reg[iid]
            exp_amp *= 1.0 + f["heal_shield_amp_pct"]
            exp_buff += f["ally_buff_credit_per_second"]
        self.assertAlmostEqual(r.amp_multiplier, exp_amp, places=6)
        self.assertAlmostEqual(r.ally_buff_credit, exp_buff, places=4)
        # total = direct(amped) + buff(NOT amped). Prove buff is not inside
        # the amp product by reconstructing total both ways.
        self.assertAlmostEqual(
            r.total_throughput,
            r.healing_hps_raw * r.amp_multiplier * r.mode_multiplier
            + r.shielding_hps_raw * r.amp_multiplier * r.mode_multiplier
            + exp_buff,
            places=4,
        )
        # Sanity: buff is NOT scaled by the 1.573x amp.
        self.assertNotAlmostEqual(
            r.total_throughput,
            (r.healing_hps_raw + exp_buff) * r.amp_multiplier,
            places=2,
        )

    def test_no_registry_item_has_a_damage_term(self) -> None:
        # Structural guard against heal/damage confusion: the enchanter
        # registry schema has zero damage fields. If a 'damage' key ever
        # leaks in, the scorer could silently treat it as healing.
        for iid, f in self.reg.items():
            keys = set(f.keys())
            self.assertFalse(
                any("damage" in k or "dps" in k for k in keys),
                msg=f"item {iid} unexpectedly carries a damage term: {keys}",
            )

    def test_naked_build_is_exactly_zero_throughput(self) -> None:
        r = compute_hps(self.snap, "Soraka", level=11)
        self.assertEqual(r.total_throughput, 0.0)
        self.assertEqual(r.healing_hps, 0.0)
        self.assertEqual(r.shielding_hps, 0.0)
        self.assertEqual(r.ally_buff_credit, 0.0)


# --- HYBRID: alpha*dps + beta*ehp ---


class HybridCompositionTests(unittest.TestCase):
    """Prove the bruiser score is a CONVEX blend of the SAME numbers the
    standalone dps/ehp scorers emit - no divergent recompute."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_weights_are_exactly_table_default(self) -> None:
        table = _load_archetype_weights()
        default = table["default"]
        # Aatrox is intentionally NOT in the bruiser override table.
        self.assertNotIn("Aatrox", table.get("champions") or {})
        a, b = get_weights_for("Aatrox")
        self.assertEqual([a, b], [float(default[0]), float(default[1])])
        self.assertEqual([a, b], [0.5, 0.5])

    def test_shipped_table_is_convex(self) -> None:
        # Every shipped pair (default + all overrides) must be a convex
        # combination: alpha,beta in [0,1] AND alpha+beta == 1.
        table = _load_archetype_weights()
        pairs = [table["default"]] + list(
            (table.get("champions") or {}).values()
        )
        for p in pairs:
            a, b = float(p[0]), float(p[1])
            self.assertGreaterEqual(a, 0.0)
            self.assertLessEqual(a, 1.0)
            self.assertGreaterEqual(b, 0.0)
            self.assertLessEqual(b, 1.0)
            self.assertAlmostEqual(a + b, 1.0, places=6)

    def test_hybrid_score_equals_alpha_dps_plus_beta_ehp_same_inputs(
        self,
    ) -> None:
        # Use identical inputs for hybrid and the two standalone scorers;
        # the hybrid components must be byte-identical, and the score must
        # be exactly alpha*dps + beta*ehp.
        kw = dict(
            champion_id="Aatrox", level=11, item_ids=["3071"], mode="SR",
            target_armor=60.0, target_mr=40.0,
            target_max_hp=2200.0, target_bonus_hp=900.0,
        )
        h = compute_hybrid(
            self.snap,
            enemy_ad_share=0.6, enemy_ap_share=0.3,
            **kw,
        )
        d = compute_dps(self.snap, **kw)
        e = compute_ehp(
            self.snap,
            champion_id="Aatrox", level=11, item_ids=["3071"], mode="SR",
            enemy_ad_share=0.6, enemy_ap_share=0.3,
        )
        self.assertEqual(h.dps, d.weighted_dps)
        self.assertEqual(h.ehp, e.blended_ehp)
        self.assertAlmostEqual(
            h.hybrid_score, h.alpha * d.weighted_dps + h.beta * e.blended_ehp,
            places=6,
        )
        # Default convex weights => score is bounded by the component
        # extremes (a true weighted average property).
        lo, hi = sorted((d.weighted_dps, e.blended_ehp))
        self.assertGreaterEqual(h.hybrid_score, lo - 1e-6)
        self.assertLessEqual(h.hybrid_score, hi + 1e-6)

    def test_alpha_one_collapses_to_pure_dps(self) -> None:
        h = compute_hybrid(
            self.snap, "Darius", level=11, item_ids=["3071"],
            alpha=1.0, beta=0.0,
        )
        d = compute_dps(self.snap, "Darius", level=11, item_ids=["3071"])
        self.assertAlmostEqual(h.hybrid_score, d.weighted_dps, places=6)

    def test_beta_one_collapses_to_pure_ehp(self) -> None:
        h = compute_hybrid(
            self.snap, "Darius", level=11, item_ids=["3071"],
            alpha=0.0, beta=1.0,
        )
        e = compute_ehp(self.snap, "Darius", level=11, item_ids=["3071"])
        self.assertAlmostEqual(h.hybrid_score, e.blended_ehp, places=6)

    def test_pure_ad_item_moves_dps_component_up_only(self) -> None:
        # B.F. Sword (1038): pure AD, zero defensive stats. DPS component
        # must rise; EHP component must be unchanged.
        base = compute_hybrid(self.snap, "Darius", level=11)
        aditem = compute_hybrid(self.snap, "Darius", level=11,
                                item_ids=["1038"])
        self.assertGreater(aditem.dps, base.dps)
        self.assertAlmostEqual(aditem.ehp, base.ehp, places=4)

    def test_pure_tank_item_moves_ehp_component_up_only(self) -> None:
        # Giant's Belt (1011): pure health, zero offensive stats. EHP
        # component must rise; DPS component unchanged.
        base = compute_hybrid(self.snap, "Darius", level=11)
        tank = compute_hybrid(self.snap, "Darius", level=11,
                              item_ids=["1011"])
        self.assertGreater(tank.ehp, base.ehp)
        self.assertAlmostEqual(tank.dps, base.dps, places=4)

    def test_delta_pct_is_convex_when_weights_sum_to_one(self) -> None:
        # alpha*x + beta*y with alpha+beta=1 lies between min(x,y) and
        # max(x,y) - the defining convexity property the ranker relies on.
        dps_pct = 50.0 / 200.0   # 0.25
        ehp_pct = 600.0 / 3000.0  # 0.20
        for a in (0.0, 0.25, 0.5, 0.55, 0.7, 1.0):
            b = 1.0 - a
            s = _hybrid_delta_pct(50.0, 600.0, 200.0, 3000.0, a, b)
            self.assertAlmostEqual(s, a * dps_pct + b * ehp_pct, places=9)
            self.assertGreaterEqual(s, min(dps_pct, ehp_pct) - 1e-9)
            self.assertLessEqual(s, max(dps_pct, ehp_pct) + 1e-9)


# --- BURST: fixed-combo total ---


class BurstDerivationTests(unittest.TestCase):
    """Hand-derive the full combo total for a clean champion straight from
    the abilities snapshot + the documented per-cast pipeline:

        raw       = sum(selected damage blocks at resolved rank)
        post_mode = raw * mode_mult            (1.0 on SR)
        post_amps = post_mode * damage_amp * (magic_amp if MAGIC else 1)
        final     = post_amps * mitigation_factor(type, armor_eff, mr_eff)
        AA token  = compute_dps.avg_attack_dmg  (already post-armor+mode;
                    NOT re-mitigated / re-mode'd inside burst)
        total     = sum(per_cast.final)
    """

    @classmethod
    def setUpClass(cls) -> None:
        reset_default_cache()
        cls.snap = DataSnapshot.load()
        cls.abil = _load_abilities()

    def test_total_is_exact_sum_of_per_cast(self) -> None:
        r = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80, target_mr=30,
            combo_sequence=("Q", "W", "E", "AA", "R", "AA"),
        )
        self.assertAlmostEqual(
            r.total_burst_damage,
            sum(c.final_damage for c in r.per_cast),
            places=6,
        )
        self.assertAlmostEqual(
            r.ability_damage,
            sum(c.final_damage for c in r.per_cast if c.is_ability),
            places=6,
        )
        self.assertAlmostEqual(
            r.auto_attack_damage,
            sum(c.final_damage for c in r.per_cast if not c.is_ability),
            places=6,
        )
        self.assertAlmostEqual(
            r.total_burst_damage,
            r.ability_damage + r.auto_attack_damage,
            places=6,
        )

    def test_aa_token_not_double_counted_mode_or_armor(self) -> None:
        # The AA per-hit damage comes from compute_dps.avg_attack_dmg which
        # is ALREADY post effective-armor + post mode_mult. burst.py must
        # surface it verbatim (raw==post_mode==post_amps==final) and NOT
        # re-apply mitigation or the mode multiplier. Probe with the same
        # inputs and assert exact equality + no second armor_factor.
        target_armor = 80.0
        naked_combo = ("AA",)
        r = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=target_armor,
            combo_sequence=naked_combo,
        )
        probe = compute_dps(
            self.snap, champion_id="Zed", level=11, item_ids=(),
            target_armor=target_armor,
        )
        aa = r.per_cast[0]
        self.assertFalse(aa.is_ability)
        # Verbatim pass-through: every stage equals the next (no extra
        # mode/armor multiply applied on top inside the burst walker).
        self.assertAlmostEqual(aa.raw_damage, aa.post_mode_damage, places=9)
        self.assertAlmostEqual(aa.post_mode_damage, aa.post_amps_damage,
                               places=9)
        self.assertAlmostEqual(aa.post_amps_damage, aa.final_damage,
                               places=9)
        # And it equals the compute_dps per-hit (base + on-hit), proving
        # burst did not apply a second armor_factor (which would shrink it
        # by ~100/(100+80) = 0.555x).
        expected_aa = (
            max(0.0, probe.avg_attack_dmg)
            + max(0.0, probe.per_attack_on_hit_damage)
        )
        self.assertAlmostEqual(aa.final_damage, expected_aa, places=6)
        # Explicitly assert it is NOT the double-mitigated value.
        double_mitigated = expected_aa * _armor_factor(
            r.target_armor_after_pen
        )
        self.assertNotAlmostEqual(aa.final_damage, double_mitigated, places=2)

    def test_zed_q_block_matches_handderived_pipeline(self) -> None:
        # Zed Q "Razor Shuriken" is a single physical damage block. Derive
        # its final damage straight from the abilities snapshot block list
        # and the documented mitigation pipeline; assert the scorer's Q
        # per-cast row matches.
        level = 11
        target_armor = 70.0
        target_mr = 25.0
        r = compute_burst_damage(
            self.snap, "Zed", level=level,
            target_armor=target_armor, target_mr=target_mr,
            combo_sequence=("Q",),
        )
        q = r.per_cast[0]
        self.assertEqual(q.ability_key, "Q")
        self.assertGreater(q.raw_damage, 0.0)
        # No item amps on a naked build => post_mode == raw (SR mode_mult
        # 1.0), post_amps == post_mode (damage_amp 1.0, and even if MAGIC
        # there is no magic_amp item).
        self.assertAlmostEqual(q.post_mode_damage, q.raw_damage, places=6)
        self.assertAlmostEqual(q.post_amps_damage, q.post_mode_damage,
                               places=6)
        # final == post_amps * mitigation_factor(type, armor_eff, mr_eff).
        # Naked build => effective resists equal the raw targets.
        self.assertEqual(r.target_armor_after_pen, target_armor)
        self.assertEqual(r.target_mr_after_pen, target_mr)
        mit = _mitigation_factor(q.damage_type, target_armor, target_mr)
        self.assertAlmostEqual(q.final_damage, q.post_amps_damage * mit,
                               places=6)
        # Zed Q is PHYSICAL => mitigation must be the armor curve exactly.
        self.assertEqual((q.damage_type or "").upper(), "PHYSICAL")
        self.assertAlmostEqual(mit, _armor_factor(target_armor), places=9)

    def test_q_repeat_token_doubles_with_no_cooldown_gating(self) -> None:
        # Documented Phase 5 design: a single combo window has NO cooldown
        # / cast-time gating - every spell is ready at combo start. So
        # Q then Q2 (same rank, same block) must be EXACTLY 2x a lone Q.
        single = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80,
            combo_sequence=("Q",),
        )
        doubled = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80,
            combo_sequence=("Q", "Q2"),
        )
        self.assertAlmostEqual(
            doubled.total_burst_damage,
            2.0 * single.total_burst_damage,
            places=6,
        )
        # The Q2 cast carries the SAME resolved rank as Q (no level-up
        # inside the window) - proves "repeat at same rank".
        q1 = single.per_cast[0]
        q2 = doubled.per_cast[1]
        self.assertEqual(q1.rank, q2.rank)
        self.assertAlmostEqual(q1.final_damage, q2.final_damage, places=9)

    def test_locked_ult_contributes_zero_below_level_6(self) -> None:
        # Combo-window correctness: an ability that is not yet unlockable
        # at the resolved level must contribute exactly 0 (rank == -1),
        # not a rank-0 phantom cast.
        level = 5
        rank = rank_at_level("R", level, max_priority=("Q", "E", "W"))
        self.assertEqual(rank, -1)
        r = compute_burst_damage(
            self.snap, "Zed", level=level, target_armor=40,
            combo_sequence=("R",),
        )
        r_cast = r.per_cast[0]
        self.assertEqual(r_cast.rank, -1)
        self.assertEqual(r_cast.final_damage, 0.0)
        self.assertEqual(r.total_burst_damage, 0.0)

    def test_aa_only_combo_has_zero_ability_damage(self) -> None:
        r = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80,
            combo_sequence=("AA", "AA", "AA"),
        )
        self.assertEqual(r.ability_damage, 0.0)
        self.assertGreater(r.auto_attack_damage, 0.0)
        # 3 identical AA tokens -> total is exactly 3x one AA (no proc
        # state machine fires without a preceding ability cast, so no
        # spellblade/lightshield contamination on a naked build).
        per = r.per_cast[0].final_damage
        self.assertAlmostEqual(r.total_burst_damage, 3.0 * per, places=6)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
