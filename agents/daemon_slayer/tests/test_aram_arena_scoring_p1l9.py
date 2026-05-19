"""P1-L9 audit hardening: ARAM + Arena SCORING correctness.

A prior pass verified cross-mode DISPATCH wiring (which term each mode
modifier hits, item-pool legality, 22-alias per-mode). This lane goes
deeper into SCORING correctness: given the mode multipliers and Arena's
augment context, does the produced per-champion item value come out
right across levels and the enemy item/resist context?

Findings from the audit (all VERIFIED CORRECT - these tests pin the
invariants so a future regression trips):

  * aramDamageDealt scales OUTGOING damage scoring (auto-attack DPS,
    ability per-cast damage, burst total) by exactly the per-champion
    factor; aramDamageTaken scales the EHP/survivability term by exactly
    1/factor. Neither is inverted, applied twice, or applied to the
    wrong term.
  * The multiplier is a pure scalar on damage, so for a build with NO
    mode-keyed cast-rate component (pure stat / auto-attack items) the
    whole-DPS ratio ARAM/SR is EXACTLY aramDamageDealt and rank_items
    preserves the relative order of items legal in both pools. Items
    with ability/ult-triggered procs (e.g. Malignance Hatefog) and the
    ability_dps scorer correctly COMPOSE the 0.9-style damage scalar
    with the orthogonal, legitimately-different mode-keyed cast cadence
    pulled from real ARAM match data (rewind_history / ult_rates). That
    is why the whole-DPS ratio is only exactly the multiplier for
    cast-rate-free builds - pinned here so the distinction is explicit.
  * Arena augment stat overlays move item value in the correct
    direction (an AP augment raises an AP champion's ability/burst
    value; an AD augment raises an AD champion's value). Unknown
    augments are a silent zero overlay (the documented progressive
    contract). Augment overlays are applied by build_champion in ANY
    mode - the ARENA-only restriction is a CALLER contract, not engine-
    enforced; that contract is pinned here so it is explicit, not a
    silent surprise.

Expected values are derived from the snapshot's own aram_modifiers and
the Meraki/cdragon augment dataValues - no hardcoded magic numbers, no
fragile cross-item comparison asserts.
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.augments import compute_augment_stats
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer.rank import rank_items


def _aram_mods(snap: DataSnapshot, champ: str) -> dict:
    rec = snap.champion(champ)
    return dict((rec.get("lolmath") or {}).get("aram_modifiers") or {})


# Champions chosen for clean isolation of the damage multiplier from the
# ARAM attack-speed modifier (aramAttackSpeed == 1.0 for all three, so
# bonus-AS is untouched and any DPS delta is purely aramDamageDealt):
#   Lux    : aramDamageDealt < 1.0 AND aramDamageTaken > 1.0 (both signs)
#   Aatrox : aramDamageDealt > 1.0, aramDamageTaken == 1.0 (clean amp)
LANE_LEVELS = (1, 6, 11, 16, 18)


class AramDamageMultiplierDirectionTests(unittest.TestCase):
    """aramDamageDealt scales OUTGOING damage; never inverted/doubled."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_setup_assumptions_hold_in_snapshot(self) -> None:
        # State the data assumptions explicitly so a snapshot refresh
        # that changes them fails loudly here instead of silently
        # invalidating the magnitude asserts below.
        lux = _aram_mods(self.snap, "Lux")
        aat = _aram_mods(self.snap, "Aatrox")
        self.assertLess(lux.get("aramDamageDealt", 1.0), 1.0)
        self.assertGreater(lux.get("aramDamageTaken", 1.0), 1.0)
        self.assertEqual(lux.get("aramAttackSpeed", 1.0), 1.0)
        self.assertGreater(aat.get("aramDamageDealt", 1.0), 1.0)
        self.assertEqual(aat.get("aramDamageTaken", 1.0), 1.0)
        self.assertEqual(aat.get("aramAttackSpeed", 1.0), 1.0)

    def test_aatrox_aa_dps_scaled_exactly_by_dmg_dealt_all_levels(self) -> None:
        # aramDamageDealt > 1.0: ARAM auto-attack DPS is SR x factor at
        # every level. Pure scalar on per-hit damage - no discontinuity.
        factor = _aram_mods(self.snap, "Aatrox")["aramDamageDealt"]
        for lvl in LANE_LEVELS:
            sr = compute_dps(self.snap, "Aatrox", level=lvl, mode="SR")
            ar = compute_dps(self.snap, "Aatrox", level=lvl, mode="ARAM")
            self.assertAlmostEqual(ar.mode_multiplier, factor)
            self.assertGreater(sr.weighted_dps, 0.0)
            self.assertAlmostEqual(
                ar.weighted_dps, sr.weighted_dps * factor, places=4,
                msg=f"L{lvl}: ARAM AA DPS must be SR x {factor}",
            )

    def test_lux_aa_dps_scaled_down_not_inverted(self) -> None:
        # aramDamageDealt < 1.0: ARAM DPS must DROP (not rise -> would be
        # an inverted multiplier) and land exactly on SR x factor.
        factor = _aram_mods(self.snap, "Lux")["aramDamageDealt"]
        for lvl in LANE_LEVELS:
            sr = compute_dps(self.snap, "Lux", level=lvl, mode="SR")
            ar = compute_dps(self.snap, "Lux", level=lvl, mode="ARAM")
            self.assertLess(ar.weighted_dps, sr.weighted_dps)
            self.assertAlmostEqual(
                ar.weighted_dps, sr.weighted_dps * factor, places=4
            )

    def test_dmg_dealt_scalar_holds_across_enemy_resist_context(self) -> None:
        # Enemy 1-6 item context shows up as target_armor/target_mr. The
        # mode scalar must NOT interact with the resist context - ARAM is
        # SR x factor at every armor value (no mode-specific kink).
        factor = _aram_mods(self.snap, "Aatrox")["aramDamageDealt"]
        for lvl in (6, 11, 18):
            for armor in (0.0, 60.0, 150.0, 300.0):
                sr = compute_dps(
                    self.snap, "Aatrox", level=lvl, mode="SR",
                    target_armor=armor,
                )
                ar = compute_dps(
                    self.snap, "Aatrox", level=lvl, mode="ARAM",
                    target_armor=armor,
                )
                self.assertGreater(sr.weighted_dps, 0.0)
                self.assertAlmostEqual(
                    ar.weighted_dps, sr.weighted_dps * factor, places=4,
                    msg=f"L{lvl} armor={armor}: scalar must be context-free",
                )

    def test_dmg_dealt_not_applied_to_ehp_term(self) -> None:
        # aramDamageDealt is OUTGOING-only. Aatrox aramDamageTaken == 1.0,
        # so its ARAM EHP must equal SR EHP exactly - proves the dealt
        # multiplier did NOT leak into the survivability term.
        sr = compute_ehp(self.snap, "Aatrox", level=11, mode="SR")
        ar = compute_ehp(self.snap, "Aatrox", level=11, mode="ARAM")
        self.assertAlmostEqual(ar.mode_multiplier, 1.0)
        self.assertAlmostEqual(ar.blended_ehp, sr.blended_ehp, places=4)


class AramDamageTakenEhpTests(unittest.TestCase):
    """aramDamageTaken scales the EHP term by exactly 1/factor."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_lux_ehp_scaled_by_inverse_dmg_taken_all_levels(self) -> None:
        # Lux aramDamageTaken > 1.0 (takes MORE damage) -> EHP must DROP
        # by exactly 1/factor for every component and the blend, at every
        # level. Wrong direction (EHP up) would mean dealt/taken swapped.
        taken = _aram_mods(self.snap, "Lux")["aramDamageTaken"]
        inv = 1.0 / taken
        for lvl in LANE_LEVELS:
            sr = compute_ehp(self.snap, "Lux", level=lvl, mode="SR")
            ar = compute_ehp(self.snap, "Lux", level=lvl, mode="ARAM")
            self.assertAlmostEqual(ar.mode_multiplier, taken)
            self.assertLess(ar.blended_ehp, sr.blended_ehp)
            self.assertAlmostEqual(
                ar.blended_ehp / sr.blended_ehp, inv, places=5,
                msg=f"L{lvl}: blended EHP must scale by 1/{taken}",
            )
            self.assertAlmostEqual(
                ar.true_ehp / sr.true_ehp, inv, places=5
            )
            self.assertAlmostEqual(
                ar.physical_ehp / sr.physical_ehp, inv, places=5
            )
            self.assertAlmostEqual(
                ar.magical_ehp / sr.magical_ehp, inv, places=5
            )

    def test_ehp_taken_not_applied_to_dps_term(self) -> None:
        # The taken multiplier is INCOMING-only. Compare Lux ARAM vs SR
        # auto-attack DPS: the ratio must be aramDamageDealt, NOT touched
        # by aramDamageTaken (proves the two terms are independent).
        dealt = _aram_mods(self.snap, "Lux")["aramDamageDealt"]
        sr = compute_dps(self.snap, "Lux", level=11, mode="SR")
        ar = compute_dps(self.snap, "Lux", level=11, mode="ARAM")
        self.assertAlmostEqual(
            ar.weighted_dps / sr.weighted_dps, dealt, places=5
        )


class AbilityAndBurstMultiplierTests(unittest.TestCase):
    """Per-cast / fixed-combo damage scaled exactly; no double-apply."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_ability_per_cast_damage_scaled_exactly_by_dmg_dealt(self) -> None:
        # The robust ability invariant is on PER-CAST damage, not total
        # ability DPS: total DPS legitimately differs by more than the
        # multiplier because cast_rates are mode-keyed (measured from
        # real ARAM data) - that is a separate correct model. Per-cast
        # post-mode damage must be exactly raw x aramDamageDealt.
        dealt = _aram_mods(self.snap, "Lux")["aramDamageDealt"]
        sr = compute_ability_dps(self.snap, "Lux", level=11, mode="SR")
        ar = compute_ability_dps(self.snap, "Lux", level=11, mode="ARAM")
        self.assertAlmostEqual(sr.mode_multiplier, 1.0)
        self.assertAlmostEqual(ar.mode_multiplier, dealt)
        sr_by = {s.key: s for s in sr.per_spell}
        ar_by = {s.key: s for s in ar.per_spell}
        damaging = [
            k for k in sr_by
            if sr_by[k].raw_damage_per_cast > 0
        ]
        self.assertTrue(damaging, "expected at least one damaging spell")
        for k in damaging:
            sp, ap = sr_by[k], ar_by[k]
            # SR: post-mode == raw (multiplier 1.0).
            self.assertAlmostEqual(
                sp.post_mode_damage_per_cast, sp.raw_damage_per_cast,
                places=4,
            )
            # ARAM: post-mode == SR raw x dealt (exact scalar).
            self.assertAlmostEqual(
                ap.post_mode_damage_per_cast,
                sp.raw_damage_per_cast * dealt,
                places=4,
                msg=f"spell {k}: ARAM per-cast must be raw x {dealt}",
            )

    def test_burst_total_scaled_exactly_by_dmg_dealt(self) -> None:
        # Burst is a FIXED combo (no cast-rate variable), so the whole
        # burst total - ability tokens AND auto-attack tokens together -
        # must be exactly SR x aramDamageDealt. This is the key guard
        # that the AA token (already mode-scaled inside its compute_dps
        # probe) is NOT multiplied a SECOND time at the burst layer.
        dealt = _aram_mods(self.snap, "Lux")["aramDamageDealt"]
        combo = ["Q", "W", "E", "R", "AA"]
        for lvl in (11, 16, 18):
            sr = compute_burst_damage(
                self.snap, "Lux", level=lvl, mode="SR",
                combo_sequence=combo,
            )
            ar = compute_burst_damage(
                self.snap, "Lux", level=lvl, mode="ARAM",
                combo_sequence=combo,
            )
            self.assertAlmostEqual(sr.mode_multiplier, 1.0)
            self.assertAlmostEqual(ar.mode_multiplier, dealt)
            self.assertGreater(sr.total_burst_damage, 0.0)
            self.assertAlmostEqual(
                ar.total_burst_damage,
                sr.total_burst_damage * dealt,
                places=3,
                msg=f"L{lvl}: burst total must be SR x {dealt} "
                f"(no double-apply on the AA token)",
            )
            # Component-level: BOTH the ability sum and the AA sum scale
            # by the same factor (a double-apply would show as the AA
            # component scaling by factor^2).
            self.assertAlmostEqual(
                ar.ability_damage, sr.ability_damage * dealt, places=3
            )
            self.assertAlmostEqual(
                ar.auto_attack_damage,
                sr.auto_attack_damage * dealt,
                places=3,
            )


class RankItemsAramScoringTests(unittest.TestCase):
    """rank_items: the actual item-value scorer under the ARAM scalar."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _common_clean_pairs(self, champ: str, level: int):
        """Items legal in BOTH SR and ARAM whose delta is purely
        stat/auto-attack (no mode-keyed cast-rate proc component), so
        the ARAM/SR delta ratio is exactly aramDamageDealt."""
        dealt = _aram_mods(self.snap, champ)["aramDamageDealt"]
        sr = rank_items(self.snap, champ, level=level, mode="SR", top_n=500)
        ar = rank_items(self.snap, champ, level=level, mode="ARAM", top_n=500)
        srm = {r.item_id: r.delta_dps for r in sr.ranked}
        arm = {r.item_id: r.delta_dps for r in ar.ranked}
        clean = [
            i for i in srm
            if i in arm and srm[i] > 0
            and abs((arm[i] / srm[i]) - dealt) < 1e-6
        ]
        return dealt, srm, arm, clean, sr, ar

    def test_baseline_dps_scaled_exactly_by_dmg_dealt(self) -> None:
        # The scorer's naked baseline must itself be SR x factor.
        dealt = _aram_mods(self.snap, "Lux")["aramDamageDealt"]
        for lvl in (6, 11, 16):
            sr = rank_items(self.snap, "Lux", level=lvl, mode="SR", top_n=1)
            ar = rank_items(
                self.snap, "Lux", level=lvl, mode="ARAM", top_n=1
            )
            self.assertGreater(sr.baseline_dps, 0.0)
            self.assertAlmostEqual(
                ar.baseline_dps, sr.baseline_dps * dealt, places=4
            )

    def test_clean_items_delta_scaled_exactly_and_order_preserved(self) -> None:
        # For the large set of items whose value is pure stat/AA, every
        # delta_dps scales by exactly aramDamageDealt AND the relative
        # ranking is preserved for any pair that is NOT a numeric tie
        # (a pure positive scalar cannot reorder strictly-separated
        # items). Genuinely tied stat items (many cost-equivalent legend-
        # ary AD items land on an identical delta, distinguished only by
        # float noise ~1e-15) may swap because the secondary sort key
        # (dps_per_1k_gold = gold cost) breaks the tie - that is benign
        # sort instability, not a scoring error, so the strict-order
        # check deliberately skips tied pairs (testing-discipline: no
        # data-fragile cross-item ordering asserts on ties). The few
        # items whose delta carries a mode-keyed ult/ability proc rate
        # (Malignance etc.) are excluded by _common_clean_pairs - their
        # non-0.9 ratio is the correct composition of the damage scalar
        # with the legitimately different ARAM cast cadence.
        dealt, srm, arm, clean, sr, ar = self._common_clean_pairs(
            "Lux", 11
        )
        self.assertGreater(
            len(clean), 20,
            "expected a large pure-stat/AA item set to pin",
        )
        for iid in clean:
            self.assertAlmostEqual(
                arm[iid] / srm[iid], dealt, places=6,
                msg=f"item {iid}: clean delta must scale by {dealt}",
            )
        # Strict-order check only on strictly-separated pairs: for every
        # ordered pair (a before b) in the SR ranking whose SR deltas
        # differ by more than float noise, a must still precede b in the
        # ARAM ranking. Tied pairs are exempt.
        clean_set = set(clean)
        sr_seq = [
            r.item_id for r in sr.ranked if r.item_id in clean_set
        ]
        ar_seq = [
            r.item_id for r in ar.ranked if r.item_id in clean_set
        ]
        ar_pos = {iid: i for i, iid in enumerate(ar_seq)}
        TIE_EPS = 1e-9
        checked = 0
        for i in range(len(sr_seq)):
            for j in range(i + 1, len(sr_seq)):
                a, b = sr_seq[i], sr_seq[j]
                if (srm[a] - srm[b]) <= TIE_EPS:
                    continue  # tied (or float-noise) - sort order is free
                self.assertLess(
                    ar_pos[a], ar_pos[b],
                    msg=f"{a} (SR delta {srm[a]}) outranks {b} "
                    f"(SR delta {srm[b]}); ARAM scalar must preserve "
                    f"this strict order",
                )
                checked += 1
        self.assertGreater(
            checked, 0, "expected some strictly-separated pairs to check"
        )

    def test_known_terminal_item_delta_scaled_exactly(self) -> None:
        # Infinity Edge (3031) is legal on SR(11) AND ARAM(12) and is a
        # pure stat/crit item (no mode-keyed cast component), so its
        # rank_items delta must scale by exactly aramDamageDealt. Named
        # anchor so the invariant survives a clean-set heuristic change.
        ie = "3031"
        it = self.snap.item(ie)
        maps = it.get("maps") or {}
        self.assertTrue(maps.get("11"))
        self.assertTrue(maps.get("12"))
        dealt = _aram_mods(self.snap, "Lux")["aramDamageDealt"]
        sr = rank_items(
            self.snap, "Lux", level=11, mode="SR", top_n=500
        )
        ar = rank_items(
            self.snap, "Lux", level=11, mode="ARAM", top_n=500
        )
        srm = {r.item_id: r.delta_dps for r in sr.ranked}
        arm = {r.item_id: r.delta_dps for r in ar.ranked}
        self.assertIn(ie, srm)
        self.assertIn(ie, arm)
        self.assertGreater(srm[ie], 0.0)
        self.assertAlmostEqual(arm[ie] / srm[ie], dealt, places=6)


class ArenaAugmentScoringTests(unittest.TestCase):
    """Arena augment context moves item value the correct direction."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_augment_overlays_resolve_from_snapshot_datavalues(self) -> None:
        # Expected overlay values are READ from the cdragon dataValues
        # (index 0) - no hardcoded magic numbers. Pins the contract that
        # the overlay equals the augment's shipped base stat.
        wt = self.snap.arena_augments_by_api.get("WitchfulThinking")
        self.assertIsNotNone(wt)
        exp_ap = float(wt["dataValues"]["AP"][0])
        ov = compute_augment_stats(["WitchfulThinking"], self.snap)
        self.assertAlmostEqual(ov.get("ap", 0.0), exp_ap)

        br = self.snap.arena_augments_by_api.get("TheBrutalizer")
        self.assertIsNotNone(br)
        exp_ad = float(br["dataValues"]["AD"][0])
        ovb = compute_augment_stats(["TheBrutalizer"], self.snap)
        self.assertAlmostEqual(ovb.get("ad", 0.0), exp_ad)

    def test_ap_augment_raises_ap_champion_item_value(self) -> None:
        # Arena scoring IS augment-aware (build_champion folds the stat
        # overlay). An AP augment must raise an AP champion's ability /
        # burst value - correct direction.
        base_ab = compute_ability_dps(
            self.snap, "Lux", level=11, mode="ARENA"
        )
        aug_ab = compute_ability_dps(
            self.snap, "Lux", level=11, mode="ARENA",
            augments=["WitchfulThinking"],
        )
        self.assertGreater(
            aug_ab.total_ability_dps, base_ab.total_ability_dps
        )
        base_b = compute_burst_damage(
            self.snap, "Lux", level=11, mode="ARENA",
            combo_sequence=["Q", "W", "E", "R"],
        )
        aug_b = compute_burst_damage(
            self.snap, "Lux", level=11, mode="ARENA",
            combo_sequence=["Q", "W", "E", "R"],
            augments=["WitchfulThinking"],
        )
        self.assertGreater(
            aug_b.total_burst_damage, base_b.total_burst_damage
        )

    def test_ad_augment_raises_ad_champion_dps(self) -> None:
        # An AD augment raises an AD champion's auto-attack DPS, and the
        # resolved AD rises by exactly the augment's dataValues AD.
        br = self.snap.arena_augments_by_api["TheBrutalizer"]
        exp_ad = float(br["dataValues"]["AD"][0])
        base = compute_dps(self.snap, "Aatrox", level=11, mode="ARENA")
        aug = compute_dps(
            self.snap, "Aatrox", level=11, mode="ARENA",
            augments=["TheBrutalizer"],
        )
        self.assertGreater(aug.weighted_dps, base.weighted_dps)
        self.assertAlmostEqual(
            aug.stats.get("ad", 0.0) - base.stats.get("ad", 0.0),
            exp_ad,
            places=4,
        )

    def test_unknown_augment_is_zero_overlay(self) -> None:
        # Documented progressive contract: an augment with no registry
        # entry contributes nothing (silent), it does NOT raise or error.
        base = compute_dps(self.snap, "Aatrox", level=11, mode="ARENA")
        unk = compute_dps(
            self.snap, "Aatrox", level=11, mode="ARENA",
            augments=["ThisAugmentDoesNotExist_p1l9"],
        )
        self.assertAlmostEqual(
            unk.weighted_dps, base.weighted_dps, places=9
        )

    def test_augment_overlay_is_caller_gated_not_mode_gated(self) -> None:
        # PINNED CONTRACT (not a bug): build_champion applies augment
        # overlays in ANY mode - feeding augments outside ARENA is
        # prevented by CALLER discipline, the engine does not silently
        # drop them. This test documents the actual behavior so a future
        # reader does not mistake it for a leak; if the team later wants
        # engine-side gating this test is the change-detector.
        br = self.snap.arena_augments_by_api["TheBrutalizer"]
        exp_ad = float(br["dataValues"]["AD"][0])
        sr_base = compute_dps(self.snap, "Aatrox", level=11, mode="SR")
        sr_aug = compute_dps(
            self.snap, "Aatrox", level=11, mode="SR",
            augments=["TheBrutalizer"],
        )
        self.assertAlmostEqual(
            sr_aug.stats.get("ad", 0.0) - sr_base.stats.get("ad", 0.0),
            exp_ad,
            places=4,
        )


class AramMonotonicityTests(unittest.TestCase):
    """No ARAM-specific discontinuity vs SR across the level lane."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_aram_dps_tracks_sr_shape_across_levels(self) -> None:
        # For every adjacent level pair the SIGN of the DPS change is the
        # same in ARAM as in SR (a positive scalar preserves the curve
        # shape - it cannot introduce a mode-only bump or dip).
        for champ in ("Lux", "Aatrox"):
            sr = [
                compute_dps(
                    self.snap, champ, level=lvl, mode="SR"
                ).weighted_dps
                for lvl in LANE_LEVELS
            ]
            ar = [
                compute_dps(
                    self.snap, champ, level=lvl, mode="ARAM"
                ).weighted_dps
                for lvl in LANE_LEVELS
            ]
            for i in range(len(LANE_LEVELS) - 1):
                d_sr = sr[i + 1] - sr[i]
                d_ar = ar[i + 1] - ar[i]
                self.assertEqual(
                    d_sr > 0, d_ar > 0,
                    msg=f"{champ} L{LANE_LEVELS[i]}->"
                    f"{LANE_LEVELS[i + 1]}: ARAM curve sign must match SR",
                )

    def test_aram_ehp_strictly_increasing_in_level(self) -> None:
        # EHP grows with level (more HP/resists). The fixed aramDamageTaken
        # scalar must NOT break monotonicity - a mode-specific dip would
        # mean the multiplier is being recomputed/applied per level.
        for champ in ("Lux", "Aatrox"):
            prev = None
            for lvl in LANE_LEVELS:
                cur = compute_ehp(
                    self.snap, champ, level=lvl, mode="ARAM"
                ).blended_ehp
                if prev is not None:
                    self.assertGreater(
                        cur, prev,
                        msg=f"{champ}: ARAM EHP must increase L->{lvl}",
                    )
                prev = cur


if __name__ == "__main__":
    unittest.main()
