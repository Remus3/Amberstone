"""Golden end-to-end COMPOSITION regression tests (parallel-audit P1-L24).

Every other DS lane unit-audited a single subsystem (engine stat math,
ingestion, scorers, beam, gold, cross-mode, ability/item procs,
mode-legality) and found each piece correct in isolation. This file
audits the OTHER axis: does the WHOLE pipeline - composing all those
verified pieces - produce the correct number for realistic full builds?
A cross-component sign/order/double-count between two individually
correct units is exactly what a unit lane cannot see.

Method: every expected value is HAND-DERIVED in the test from Riot /
Meraki first principles - champion base-by-level using the Riot
quadratic growth multiplier ``(n-1)*(0.7025+0.0175*(n-1))``, item flat
stats from the snapshot stat block, the documented penetration /
reduction pipeline, the crit clamp, the 2.5 attack-speed cap, and the
ARAM ``aramDamageDealt`` / ``aramDamageTaken`` multipliers - and then
asserted equal (tight tolerance) to the engine's COMPOSED output. No
hardcoded magic number is copied out of engine output; no fragile
cross-item comparison assertion is used.

Golden scenarios (span the archetypes / modes / clamps):

  A. Crit ADC - Caitlyn L13, Infinity Edge + Phantom Dancer +
     Berserker's Greaves vs an 80-armor (two-armor-item) target. Full
     weighted DPS hand-derived: quadratic base AD + item AD, crit
     clamp, IE crit-damage bump, AS level+item stacking, the League
     armor factor, and the lolmath rotation weighting - all composed.
  B. Tank EHP - Malphite L11, Sunfire Aegis + Thornmail vs a 60/40
     AD/AP enemy mix. Quadratic base HP/armor/MR + item flats, the
     armor factor on each resist, blended by enemy shares.
  C. AP mage ability burst - Lux Q at L16 with Rabadon's Deathcap.
     The Rabadon's 1.30 AP amp composes with the rank-resolved ability
     base + AP ratio, then the shared MR mitigation factor.
  D. Cross-scorer AA-token identity - the burst scorer's "AA" token
     final damage IS exactly ``compute_dps(...).avg_attack_dmg`` for
     the same champion / target / build (Zed L13).
  E. ARAM damage multiplier ORDER - Jinx (aramDamageDealt=0.9,
     aramAttackSpeed=1.0 so the mult is isolated) - the 0.9 multiplies
     per-hit damage AFTER the armor factor, not before.
  F. Attack-speed cap - Kalista L18 with six attack-speed items whose
     hand-summed uncapped AS exceeds 2.5; the composed engine value
     must be clamped to exactly 2.5 (no scorer bypasses the cap).
  G. Negative-resist amp - Garen + Flesheater (30 flat armor
     REDUCTION) vs a 27-armor squishy: effective armor goes to -3 and
     the ``2 - 100/(100-R)`` amplification branch must fire end-to-end.
  H. Hybrid composition identity - ``hybrid_score`` ==
     ``alpha*dps + beta*ehp`` using the SAME ``weighted_dps`` /
     ``blended_ehp`` the standalone DPS / EHP scorers return for that
     exact build (Garen, archetype weights).
  I. Build-level gold / delta integrity - a ranked candidate's gold ==
     the Meraki ``gold.total``; its ``delta_dps`` == (new-build DPS -
     baseline DPS) recomputed independently; ``new_dps`` matches.
  J. Burst total integrity + /health version - total burst damage ==
     sum of per-cast final damage; the ``/health``-reported
     engine_version is the very ``ENGINE_VERSION`` the math imports.
  K. ARAM EHP multiplier - Jinx aramDamageTaken=1.05 scales EHP for
     ALL damage types (including true) end-to-end.

All scenarios PASS at the audited ENGINE_VERSION (no composition bug
found - a valid, strong saturation signal). This file trips loudly if
a future change introduces a cross-component order / sign /
double-count regression.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import DEFAULT_CRIT_BONUS, compute_dps
from agents.daemon_slayer.effects import collect_effects, effective_target_armor
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer.hybrid import compute_hybrid, get_weights_for
from agents.daemon_slayer.rank import rank_items

# Tight absolute tolerance - the engine is pure float arithmetic with no
# stochastic component, so a correct composition reproduces the
# hand-derived value to well within this. Loose enough only to absorb
# IEEE-754 last-bit ordering noise, NOT a real mismatch.
TOL = 1e-7


def _gm(level: int) -> float:
    """Riot per-level champion stat-growth multiplier (quadratic).

    Hand-recomputed here on purpose - the test must NOT import the
    engine's ``growth_multiplier`` (that would make the test pass
    tautologically if the engine helper itself regressed).
    """
    n = level - 1
    return n * (0.7025 + 0.0175 * n)


def _armor_factor(resist: float) -> float:
    """League resist -> damage multiplier. Hand form, not imported."""
    if resist >= 0:
        return 100.0 / (100.0 + resist)
    return 2.0 - 100.0 / (100.0 - resist)


class GoldenCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # ---------------------------------------------------------------- A
    def test_A_crit_adc_full_weighted_dps(self) -> None:
        """Caitlyn L13, IE+PD+Berserker's vs 80 armor - full DPS chain.

        IE, Phantom Dancer and Berserker's Greaves carry NO periodic
        procs / amps / pen (verified against the snapshot), so the
        rotation DPS is a clean closed form composing every stat layer.
        """
        snap = self.snap
        champ = snap.champion("Caitlyn")
        st = champ["stats"]
        lvl = 13
        gm = _gm(lvl)

        # Base AD (quadratic) + IE flat AD 75.
        base_ad = st["attackdamage"] + st["attackdamageperlevel"] * gm
        total_ad = base_ad + 75.0
        # Crit: IE 0.25 + PD 0.25 = 0.50 (below the 1.0 clamp).
        crit = 0.25 + 0.25
        # Crit bonus: engine default 0.75 + IE's +0.30.
        crit_bonus = DEFAULT_CRIT_BONUS + 0.30
        # AS: base 0.681, +4%/level bonus, items PD .65 + Berserker .25.
        base_as = st["attackspeed"]
        lvl_bonus = (st["attackspeedperlevel"] / 100.0) * (lvl - 1)
        item_as = 0.65 + 0.25
        as_val = base_as * (1.0 + lvl_bonus + item_as)
        self.assertLess(as_val, 2.5, "scenario must stay under the AS cap")

        armor_factor = _armor_factor(80.0)
        avg_hit = total_ad * (1.0 + crit * crit_bonus) * armor_factor * 1.0

        # Late-phase rotation weighting from the lolmath snapshot (the
        # SAME numbers the engine reads); level 13 -> late phase.
        sc = (snap.scenarios("Caitlyn")[0].get("settings", {}) or {}).get(
            "scenario", {}
        ) or {}
        late = sc["late"]

        def rot_dps(r: dict) -> float:
            dur = float(r["duration"])
            attacks = float(r["basic"]) + float(r["basicTime"]) * as_val
            return attacks * avg_hit / dur

        tw = sum(float(r["weight"]) for r in late)
        expected_weighted = sum(
            float(r["weight"]) * rot_dps(r) for r in late
        ) / tw

        res = compute_dps(
            snap, "Caitlyn", lvl,
            item_ids=["3031", "3046", "3006"], mode="SR",
            target_armor=80.0, target_mr=0.0,
        )
        self.assertEqual(res.phase, "late")
        self.assertAlmostEqual(res.stats["ad"], total_ad, delta=TOL)
        self.assertAlmostEqual(res.stats["as"], as_val, delta=TOL)
        self.assertEqual(res.stats["crit"], crit)
        self.assertAlmostEqual(res.avg_attack_dmg, avg_hit, delta=TOL)
        self.assertAlmostEqual(
            res.weighted_dps, expected_weighted, delta=1e-6
        )

    # ---------------------------------------------------------------- B
    def test_B_tank_ehp_blended(self) -> None:
        """Malphite L11, Sunfire+Thornmail vs 60/40 AD/AP - EHP chain."""
        snap = self.snap
        st = snap.champion("Malphite")["stats"]
        lvl = 11
        gm = _gm(lvl)

        # Sunfire: hp350 armor50.  Thornmail: hp150 armor75.
        hp = st["hp"] + st["hpperlevel"] * gm + 350.0 + 150.0
        armor = (st["armor"] + st["armorperlevel"] * gm) + 50.0 + 75.0
        mr = st["spellblock"] + st["spellblockperlevel"] * gm

        phys = hp / _armor_factor(armor)
        mag = hp / _armor_factor(mr)
        tru = hp
        ad_share, ap_share = 0.6, 0.4
        blended = phys * ad_share + mag * ap_share + tru * 0.0

        res = compute_ehp(
            snap, "Malphite", lvl,
            item_ids=["3068", "3075"], mode="SR",
            enemy_ad_share=ad_share, enemy_ap_share=ap_share,
        )
        self.assertAlmostEqual(res.hp, hp, delta=TOL)
        self.assertAlmostEqual(res.armor, armor, delta=TOL)
        self.assertAlmostEqual(res.mr, mr, delta=TOL)
        self.assertAlmostEqual(res.physical_ehp, phys, delta=1e-6)
        self.assertAlmostEqual(res.magical_ehp, mag, delta=1e-6)
        self.assertAlmostEqual(res.true_ehp, tru, delta=1e-6)
        self.assertAlmostEqual(res.blended_ehp, blended, delta=1e-6)

    # ---------------------------------------------------------------- C
    def test_C_ap_mage_ability_burst_vs_mr(self) -> None:
        """Lux Q at L16 with Rabadon's - AP amp composes with MR mit.

        Lux maxes Q; at L16 Q is at its 5th rank (base 240, 75% AP).
        Rabadon's Deathcap (130 AP) amplifies total AP x1.30 -> 169.
        The composed per-cast pre-mit = 240 + 0.75*169; post-mit
        applies the shared 100/(100+MR) factor.

        AP ratio re-pinned 0.65 -> 0.75 with the prefer_cdragon_ratios
        default-ON cutover: the live CommunityDragon 16.11 bin (and the
        wiki) carry 75% AP for Light Binding; the frozen Meraki dump was
        stale at 65%. CDragon is authoritative here.
        """
        from agents.daemon_slayer.ability_dps import compute_ability_dps

        snap = self.snap
        ap_base = 130.0  # Rabadon's flat AP from the snapshot stat block.
        ap_eff = ap_base * 1.30  # Rabadon's Magical Opus multiplier.
        q_base_rank5 = 240.0
        q_ap_ratio = 0.75
        raw_q = q_base_rank5 + q_ap_ratio * ap_eff
        mr = 50.0
        post_mit_q = raw_q * _armor_factor(mr)

        res = compute_ability_dps(
            snap, "Lux", 16, item_ids=["3089"], mode="SR",
            target_armor=0.0, target_mr=mr,
        )
        q = next(p for p in res.to_dict()["per_spell"] if p["key"] == "Q")
        self.assertAlmostEqual(
            q["raw_damage_per_cast"], raw_q, delta=1e-6
        )
        self.assertAlmostEqual(
            q["post_mitigation_damage_per_cast"], post_mit_q, delta=1e-6
        )

    # ---------------------------------------------------------------- D
    def test_D_burst_aa_token_equals_compute_dps_avg_hit(self) -> None:
        """The burst AA token IS compute_dps.avg_attack_dmg, same build.

        Cross-scorer contract: burst.py must not re-derive a different
        per-hit number than the canonical dps.py one for the identical
        champion / target / items.
        """
        snap = self.snap
        kw = dict(
            champion_id="Zed", level=13, item_ids=["3142", "3814"],
            mode="SR", target_armor=60.0, target_mr=40.0,
        )
        dps_res = compute_dps(snap, **kw)
        burst_res = compute_burst_damage(snap, **kw)
        aa_rows = [
            c for c in burst_res.to_dict()["per_cast"]
            if c["token"] == "AA"
        ]
        self.assertTrue(aa_rows, "combo must contain at least one AA")
        for row in aa_rows:
            self.assertAlmostEqual(
                row["final_damage"], dps_res.avg_attack_dmg, delta=TOL
            )

    # ---------------------------------------------------------------- E
    def test_E_aram_damage_mult_applied_after_armor(self) -> None:
        """Jinx ARAM - aramDamageDealt=0.9 multiplies AFTER the armor
        factor, and aramAttackSpeed=1.0 leaves AS untouched (isolating
        the damage multiplier so the order is unambiguous).
        """
        snap = self.snap
        champ = snap.champion("Jinx")
        aram = (champ.get("lolmath") or {}).get("aram_modifiers") or {}
        add = float(aram["aramDamageDealt"])
        aas = float(aram["aramAttackSpeed"])
        self.assertEqual(add, 0.9)
        self.assertEqual(aas, 1.0)

        st = champ["stats"]
        lvl = 13
        gm = _gm(lvl)
        total_ad = st["attackdamage"] + st["attackdamageperlevel"] * gm + 75.0
        crit = 0.50
        crit_bonus = DEFAULT_CRIT_BONUS + 0.30
        # mult applied AFTER armor factor (post-mitigation), not to AD.
        avg_hit = total_ad * (1.0 + crit * crit_bonus) \
            * _armor_factor(80.0) * add

        res = compute_dps(
            snap, "Jinx", lvl, item_ids=["3031", "3046", "3006"],
            mode="ARAM", target_armor=80.0,
        )
        self.assertEqual(res.mode_multiplier, add)
        self.assertAlmostEqual(res.avg_attack_dmg, avg_hit, delta=TOL)

    # ---------------------------------------------------------------- F
    def test_F_attack_speed_cap_hit_end_to_end(self) -> None:
        """Kalista L18 + 6 AS items - hand-uncapped AS > 2.5, so the
        composed engine output must be clamped to EXACTLY 2.5. No
        scorer path is allowed to bypass the cap.
        """
        snap = self.snap
        st = snap.champion("Kalista")["stats"]
        lvl = 18
        base_as = st["attackspeed"]
        lvl_bonus = (st["attackspeedperlevel"] / 100.0) * (lvl - 1)
        # PD .65, RFC .35, Guinsoo .25, BotRK .25, Berserker .25,
        # Rageknife .25 -> 2.00 item AS, hand-summed from the snapshot.
        item_as = 0.65 + 0.35 + 0.25 + 0.25 + 0.25 + 0.25
        uncapped = base_as * (1.0 + lvl_bonus + item_as)
        self.assertGreater(
            uncapped, 2.5,
            "scenario precondition: hand-uncapped AS must exceed the cap",
        )
        build = ["3046", "3094", "3124", "3153", "3006", "6677"]
        res = compute_dps(
            snap, "Kalista", lvl, item_ids=build, mode="SR",
            target_armor=0.0,
        )
        self.assertAlmostEqual(res.stats["as"], 2.5, delta=1e-12)

    # ---------------------------------------------------------------- G
    def test_G_negative_resist_amp_end_to_end(self) -> None:
        """Garen + Flesheater (30 flat armor REDUCTION) vs 27 armor.

        Effective armor = 27 - 30 = -3 (reduction can cross zero); the
        per-hit damage must use the ``2 - 100/(100-R)`` amplification
        branch, composed all the way through compute_dps.avg_attack_dmg.
        """
        snap = self.snap
        flesh_id = "667112"
        effs = collect_effects([flesh_id])
        post = effective_target_armor(27.0, effs, level=11)
        self.assertAlmostEqual(post, -3.0, delta=TOL)
        amp_factor = _armor_factor(post)
        self.assertGreater(amp_factor, 1.0, "negative armor must amplify")

        st = snap.champion("Garen")["stats"]
        item = snap.item(flesh_id)
        fl_ad = float(item.get("stats", {}).get("FlatPhysicalDamageMod", 0.0))
        lvl = 11
        gm = _gm(lvl)
        total_ad = st["attackdamage"] + st["attackdamageperlevel"] * gm + fl_ad
        crit = float(st["crit"])  # Garen base crit 0
        crit_bonus = DEFAULT_CRIT_BONUS  # Flesheater adds no crit damage
        avg_hit = total_ad * (1.0 + crit * crit_bonus) * amp_factor

        res = compute_dps(
            snap, "Garen", lvl, item_ids=[flesh_id], mode="SR",
            target_armor=27.0, target_mr=0.0,
        )
        self.assertAlmostEqual(res.avg_attack_dmg, avg_hit, delta=1e-6)

    # ---------------------------------------------------------------- H
    def test_H_hybrid_is_alpha_dps_plus_beta_ehp(self) -> None:
        """hybrid_score == alpha*dps + beta*ehp using the SAME
        weighted_dps / blended_ehp the standalone scorers return for
        the exact same build (no re-derivation drift between layers).
        """
        snap = self.snap
        champ, lvl = "Garen", 13
        items = ["3068", "3075", "3083"]
        alpha, beta = get_weights_for(champ)

        dps_res = compute_dps(
            snap, champ, lvl, item_ids=items, mode="SR",
            target_armor=80.0, target_mr=50.0,
        )
        ehp_res = compute_ehp(
            snap, champ, lvl, item_ids=items, mode="SR",
            enemy_ad_share=0.6, enemy_ap_share=0.4,
        )
        hyb = compute_hybrid(
            snap, champ, lvl, item_ids=items, mode="SR",
            target_armor=80.0, target_mr=50.0,
            enemy_ad_share=0.6, enemy_ap_share=0.4,
        )
        # The hybrid scorer must reuse the identical component numbers.
        self.assertAlmostEqual(
            hyb.dps, dps_res.weighted_dps, delta=TOL
        )
        self.assertAlmostEqual(
            hyb.ehp, ehp_res.blended_ehp, delta=TOL
        )
        expected = alpha * dps_res.weighted_dps + beta * ehp_res.blended_ehp
        self.assertAlmostEqual(hyb.hybrid_score, expected, delta=1e-6)

    # ---------------------------------------------------------------- I
    def test_I_build_level_gold_and_delta_integrity(self) -> None:
        """A ranked candidate's gold == Meraki gold.total; its
        delta_dps == (new-build DPS - baseline DPS) recomputed
        independently; new_dps matches the independent recompute.
        """
        snap = self.snap
        base_dps = compute_dps(
            snap, "Caitlyn", 13, item_ids=["3031"], mode="SR",
            target_armor=80.0,
        ).weighted_dps
        ranked = rank_items(
            snap, "Caitlyn", 13, current_item_ids=["3031"], mode="SR",
            target_armor=80.0, top_n=3,
        )
        self.assertTrue(ranked.ranked, "ranker returned no candidates")
        for it in ranked.ranked:
            meraki_gold = int(
                (snap.item(it.item_id).get("gold") or {}).get("total", 0)
            )
            self.assertEqual(
                it.gold, meraki_gold,
                f"{it.item_id}: ranker gold != Meraki gold.total",
            )
            recomputed = compute_dps(
                snap, "Caitlyn", 13,
                item_ids=["3031", it.item_id], mode="SR",
                target_armor=80.0,
            ).weighted_dps
            self.assertAlmostEqual(
                it.new_dps, recomputed, delta=1e-6
            )
            self.assertAlmostEqual(
                it.delta_dps, recomputed - base_dps, delta=1e-6
            )

    # ---------------------------------------------------------------- J
    def test_J_burst_total_and_health_version_integrity(self) -> None:
        """total_burst_damage == sum of per-cast final damage, and the
        /health-reported engine_version is the very ENGINE_VERSION the
        math imports (the reported version is the one doing the math).
        """
        snap = self.snap
        burst = compute_burst_damage(
            snap, "Zed", 13, item_ids=["3142", "3814"], mode="SR",
            target_armor=60.0, target_mr=40.0,
        )
        d = burst.to_dict()
        sum_final = sum(c["final_damage"] for c in d["per_cast"])
        self.assertAlmostEqual(
            d["total_burst_damage"], sum_final, delta=1e-6
        )

        # /health version provenance: the server imports ENGINE_VERSION
        # straight from the package the engine math lives in, and the
        # /health route reports that exact object - so the reported
        # version is provably the one doing the math.
        from agents.daemon_slayer import server as ds_server
        self.assertIs(ds_server.ENGINE_VERSION, ENGINE_VERSION)
        ds_server._CACHE.set(snap)
        health = ds_server._route_health()
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["engine_version"], ENGINE_VERSION)
        self.assertEqual(health["patch"], snap.patch)

    # ---------------------------------------------------------------- K
    def test_K_aram_ehp_multiplier_all_damage_types(self) -> None:
        """Jinx ARAM aramDamageTaken=1.05 - EHP scaled by 1/1.05 for
        physical, magical AND true damage (the multiplier touches every
        damage type, composed through the resolved build).
        """
        snap = self.snap
        champ = snap.champion("Jinx")
        aram = (champ.get("lolmath") or {}).get("aram_modifiers") or {}
        atk = float(aram["aramDamageTaken"])
        self.assertEqual(atk, 1.05)

        st = champ["stats"]
        lvl = 13
        gm = _gm(lvl)
        hp = st["hp"] + st["hpperlevel"] * gm + 1000.0  # Warmog's 1000 HP
        armor = st["armor"] + st["armorperlevel"] * gm
        mr = st["spellblock"] + st["spellblockperlevel"] * gm

        phys = hp / (_armor_factor(armor) * atk)
        mag = hp / (_armor_factor(mr) * atk)
        tru = hp / atk
        blended = phys * 0.6 + mag * 0.4 + tru * 0.0

        res = compute_ehp(
            snap, "Jinx", lvl, item_ids=["3083"], mode="ARAM",
            enemy_ad_share=0.6, enemy_ap_share=0.4,
        )
        self.assertEqual(res.mode_multiplier, atk)
        self.assertAlmostEqual(res.physical_ehp, phys, delta=1e-6)
        self.assertAlmostEqual(res.magical_ehp, mag, delta=1e-6)
        self.assertAlmostEqual(res.true_ehp, tru, delta=1e-6)
        self.assertAlmostEqual(res.blended_ehp, blended, delta=1e-6)


if __name__ == "__main__":
    unittest.main()
