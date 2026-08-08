"""RM-176 (2026-08-08, ENGINE 1.275.1 / patch 16.15.1) - PROPERTY-STYLE EHP invariants.

Three property sweeps over ``agents.daemon_slayer.ehp``. None of them assert a
magnitude; each asserts a RELATION that must survive any future engine term, so
they keep paying after the number they would otherwise have pinned has moved.

INVARIANT 1 - ``_blend_with_heal`` mirror parity under EVERY armed seam.
    ``compute_ehp`` assembles the per-type numerator/denominator TWICE: the main
    ``physical_ehp`` / ``magical_ehp`` / ``true_ehp`` block, and the
    ``_blend_with_heal`` closure that produces ``effective_ehp_with_sustain``. A
    term added to one and not the other diverges the two silently. RM-105 is the
    proof this is not hypothetical - the permanent-HP family was missing from the
    mirror for 147 engine revisions and cost 618.33 EHP on Sion L13 the moment
    ``apply_rune_health_grants`` was armed.
    The existing guard (``test_ehp_sustain_contract`` LifestealSustainTests) arms
    only three seams by NAME; every other parity assertion in the suite runs at
    DEFAULT flags, where every optional term is 0.0 and the equality is vacuous.
    This sweep enumerates the seams from ``inspect.signature`` instead of naming
    them, so a seam added next month is covered on the day it lands - a hardcoded
    list is exactly how RM-105 stayed invisible.

INVARIANT 2 - EHP monotonicity, roster-wide.
    The suite's only monotonicity assertion (``test_ehp.ConsistencyTests``) is
    three fixed builds on Malphite L11. It never varies level, flat HP, or enemy
    penetration, and it never leaves one champion. This sweeps all 173 champions
    across four independent axes.

INVARIANT 3 - ``rank_items_by_ehp`` rows reproduce a direct ``compute_ehp``.
    ``test_rank_tank.test_top_1_delta_equals_new_minus_baseline`` compares two
    numbers the ranker itself produced, so it is internally tautological and can
    never catch a build-assembly divergence. The ranker assembles
    ``current_item_ids + [candidate]`` through a filter pipeline (purchasable /
    mode-legal / budget / terminal-only / filter_shared_uniques); nothing asserts
    the row a caller reads back equals what that caller would get calling
    ``compute_ehp`` on the same list. This does.

Runtime: the full file runs in under 1 second (measured 0.79s, 15 tests / 5972
subtests). No sweep is sampled or narrowed - every axis listed above is evaluated
at its full stated breadth.
"""
from __future__ import annotations

import inspect
import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp, rank_items_by_ehp

# The mirror-parity build is deliberately VAMP-FREE (no Bloodthirster-family
# lifesteal item, and above all no Riftmaker 4633). ``assume_max_stacks_omnivamp``
# is one of the enumerated boolean seams, and arming it on a Riftmaker build
# injects an omnivamp fraction that lands on ``effective_ehp_with_sustain`` ONLY -
# by design, since the vamp extra is a sustain-axis credit that blended_ehp is
# never meant to carry. That intended asymmetry would read as a mirror defect and
# there is no way to tell the two apart from the outside, so the build excludes
# the vamp source and the sweep sees only genuine assembly divergence.
# Every id verified present in DataSnapshot.load().items (706 entries, 16.15.1):
# Heartsteel / Sunfire Aegis / Zhonya's Hourglass / Guardian Angel / Jak'Sho /
# Banshee's Veil - chosen so the item revive, stasis, resist-grant, spell-shield
# and health-stack seams have something in the build to actually credit.
_PARITY_BUILD = ("3084", "3068", "3157", "3026", "6665", "3102")

# One id from each defensive rune registry that the EHP seams read, so no rune
# lane is inert: 8437 Grasp + 8451 Overgrowth (_rune_health_grants), 8242 / 8429 /
# 8439 (_rune_resist_grants), 8453 (_rune_hsp_amp), 8444 (_rune_self_heal),
# 8465 (_rune_shield_grants), 8473 (_rune_flat_mitigation).
_PARITY_RUNES = ("8437", "8451", "8242", "8429", "8439", "8453", "8444", "8465", "8473")

# Kayle at 16 because her level-16 form is the last one the form-occupancy lanes
# resolve; the rest sit at 13 where the ramping item/rune stacks are live.
_PARITY_CHAMPS = (("Sion", 13), ("Anivia", 13), ("Zac", 13), ("Leona", 13), ("Kayle", 16))

# Measured 40 on 1.275.1. A FLOOR, not an equality: a new seam must not fail this
# file, but ``inspect.signature`` silently returning a shorter list would make the
# entire sweep pass by evaluating nothing, which is the failure this pins against.
_BOOL_SEAM_FLOOR = 40

# The roster is operator-CLOSED at 173/173. A floor for the same reason as above -
# a truncated snapshot must not let the monotonicity sweep pass vacuously.
_ROSTER_FLOOR = 173


def _boolean_seams() -> list[str]:
    """Enumerate compute_ehp's boolean opt-in seams from the live signature."""
    return [
        name
        for name, p in inspect.signature(compute_ehp).parameters.items()
        if isinstance(p.default, bool)
    ]


class _SnapBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()


# ---------------- INVARIANT 1: _blend_with_heal mirror parity ----------------


class BlendWithHealMirrorParityTests(_SnapBase):
    def test_seam_enumeration_is_not_empty_and_meets_the_pinned_floor(self) -> None:
        seams = _boolean_seams()
        self.assertGreater(len(seams), 0)
        self.assertGreaterEqual(
            len(seams), _BOOL_SEAM_FLOOR,
            msg=(f"only {len(seams)} boolean seams enumerated (floor "
                 f"{_BOOL_SEAM_FLOOR}) - if a seam was genuinely retired, lower "
                 f"the floor deliberately; otherwise the signature walk broke "
                 f"and every parity subTest below is now evaluating nothing"),
        )
        # The three RM-105 seams must still be reachable by this walk - they are
        # the ones that actually fired, so losing them is the worst case.
        for known in ("assume_passive_health_stacks", "assume_item_health_stacks",
                      "apply_rune_health_grants"):
            self.assertIn(known, seams)

    def test_every_boolean_seam_armed_alone_preserves_mirror_parity(self) -> None:
        params = inspect.signature(compute_ehp).parameters
        seams = _boolean_seams()
        evaluated = 0
        for champ, level in _PARITY_CHAMPS:
            for flag in seams:
                with self.subTest(champion=champ, level=level, seam=flag):
                    e = compute_ehp(
                        self.snap, champ, level=level,
                        item_ids=list(_PARITY_BUILD), rune_ids=list(_PARITY_RUNES),
                        **{flag: not params[flag].default},
                    )
                    self.assertAlmostEqual(
                        e.effective_ehp_with_sustain, e.blended_ehp, places=6,
                        msg=(f"{champ} L{level} with {flag} armed: the sustain "
                             f"mirror diverges from the main blend by "
                             f"{e.blended_ehp - e.effective_ehp_with_sustain:.4f} "
                             f"EHP - a term landed in one numerator assembly and "
                             f"not the other (ehp.py main block vs "
                             f"_blend_with_heal)"),
                    )
                evaluated += 1
        self.assertGreater(evaluated, 0)
        self.assertEqual(evaluated, len(_PARITY_CHAMPS) * len(seams))

    def test_all_seams_armed_together_preserves_mirror_parity(self) -> None:
        # Single-flag arming can miss a term that only materialises when two
        # seams interact (a shield that needs its amp armed, a stack that needs
        # its pool armed), so the composite case is not redundant with the sweep.
        params = inspect.signature(compute_ehp).parameters
        flipped = {f: not params[f].default for f in _boolean_seams()}
        for champ, level in _PARITY_CHAMPS:
            with self.subTest(champion=champ, level=level, seam="ALL"):
                e = compute_ehp(
                    self.snap, champ, level=level,
                    item_ids=list(_PARITY_BUILD), rune_ids=list(_PARITY_RUNES),
                    **flipped,
                )
                self.assertAlmostEqual(
                    e.effective_ehp_with_sustain, e.blended_ehp, places=6,
                    msg=(f"{champ} L{level} with ALL {len(flipped)} seams armed: "
                         f"mirror diverges by "
                         f"{e.blended_ehp - e.effective_ehp_with_sustain:.4f} EHP"),
                )

    def test_scalar_knobs_preserve_mirror_parity(self) -> None:
        # The boolean seams gate optional TERMS; these knobs move terms the
        # mirror already carries (numerator adds, denominator resists, the pen
        # curve, the revive multiplier, the mode block). A mirror that copied a
        # term but not its scaling fails here and nowhere else.
        knobs = (
            ("external_flat_hp", 750.0),
            ("external_resist_armor", 60.0),
            ("external_resist_mr", 45.0),
            ("external_revive_multiplier", 1.5),
            ("enemy_lethality", 25.0),
            ("enemy_armor_pen_pct", 0.35),
            ("enemy_shred_pct", 0.30),
            ("enemy_magic_pen_flat", 18.0),
            ("enemy_magic_pen_pct", 0.40),
            ("caster_current_hp_pct", 0.25),
            ("mode", "ARAM"),
            ("resist_coupling_strength", 0.5),
        )
        evaluated = 0
        for champ, level in _PARITY_CHAMPS:
            for knob, value in knobs:
                with self.subTest(champion=champ, level=level, knob=knob):
                    e = compute_ehp(
                        self.snap, champ, level=level,
                        item_ids=list(_PARITY_BUILD), rune_ids=list(_PARITY_RUNES),
                        **{knob: value},
                    )
                    self.assertAlmostEqual(
                        e.effective_ehp_with_sustain, e.blended_ehp, places=6,
                        msg=(f"{champ} L{level} with {knob}={value}: mirror "
                             f"diverges by "
                             f"{e.blended_ehp - e.effective_ehp_with_sustain:.4f} "
                             f"EHP"),
                    )
                evaluated += 1
        self.assertEqual(evaluated, len(_PARITY_CHAMPS) * len(knobs))


# ---------------- INVARIANT 2: roster-wide monotonicity ----------------


class EhpMonotonicityRosterTests(_SnapBase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.champs = sorted(cls.snap.champions)

    def test_roster_meets_the_pinned_floor(self) -> None:
        # Every sweep below iterates this list; an empty or truncated roster
        # would let all four pass without evaluating a single champion.
        self.assertGreaterEqual(len(self.champs), _ROSTER_FLOOR)

    def test_blended_ehp_non_decreasing_in_level(self) -> None:
        # Naked build, default flags: nothing but base-stat growth moves, and
        # no champion's growth curve is negative on any stat that feeds EHP.
        for cid in self.champs:
            prev = None
            for level in range(1, 19):
                value = compute_ehp(self.snap, cid, level=level).blended_ehp
                if prev is not None:
                    with self.subTest(champion=cid, level=level, axis="level"):
                        self.assertGreaterEqual(
                            value, prev - 1e-9,
                            msg=(f"{cid}: blended_ehp fell from {prev:.4f} at "
                                 f"L{level - 1} to {value:.4f} at L{level}"),
                        )
                prev = value

    def test_physical_ehp_non_decreasing_in_external_armor(self) -> None:
        # Pure-AD incoming, so physical_ehp IS the whole story: an ally-granted
        # armor add can only raise the armor denominator.
        for cid in self.champs:
            prev = None
            for armor in (0.0, 25.0, 50.0, 100.0, 200.0, 400.0):
                value = compute_ehp(
                    self.snap, cid, level=13, external_resist_armor=armor,
                    enemy_ad_share=1.0, enemy_ap_share=0.0,
                ).physical_ehp
                if prev is not None:
                    with self.subTest(champion=cid, external_resist_armor=armor,
                                      axis="armor"):
                        self.assertGreaterEqual(
                            value, prev - 1e-9,
                            msg=(f"{cid}: physical_ehp fell to {value:.4f} at "
                                 f"+{armor:.0f} armor (was {prev:.4f})"),
                        )
                prev = value

    def test_blended_ehp_non_decreasing_in_external_flat_hp(self) -> None:
        # A flat HP add sits at the top of the damage stack for all three
        # types, so it lifts the blend whatever the enemy shares are.
        for cid in self.champs:
            prev = None
            for flat_hp in (0.0, 250.0, 1000.0, 4000.0):
                value = compute_ehp(
                    self.snap, cid, level=13, external_flat_hp=flat_hp,
                ).blended_ehp
                if prev is not None:
                    with self.subTest(champion=cid, external_flat_hp=flat_hp,
                                      axis="flat_hp"):
                        self.assertGreaterEqual(
                            value, prev - 1e-9,
                            msg=(f"{cid}: blended_ehp fell to {value:.4f} at "
                                 f"+{flat_hp:.0f} flat HP (was {prev:.4f})"),
                        )
                prev = value

    def test_physical_ehp_non_increasing_in_enemy_lethality(self) -> None:
        # The one DECREASING axis. Flat armor pen can only shrink the effective
        # armor denominator, and the pen floor means it bottoms out rather than
        # rebounding - an increase anywhere means the pen curve inverted.
        for cid in self.champs:
            prev = None
            for lethality in (0.0, 10.0, 30.0, 60.0, 100.0):
                value = compute_ehp(
                    self.snap, cid, level=13, enemy_lethality=lethality,
                    enemy_ad_share=1.0, enemy_ap_share=0.0,
                ).physical_ehp
                if prev is not None:
                    with self.subTest(champion=cid, enemy_lethality=lethality,
                                      axis="lethality"):
                        self.assertLessEqual(
                            value, prev + 1e-9,
                            msg=(f"{cid}: physical_ehp ROSE to {value:.4f} at "
                                 f"{lethality:.0f} lethality (was {prev:.4f})"),
                        )
                prev = value


# ---------------- INVARIANT 3: ranker rows reproduce compute_ehp ----------------


class RankRowReproducesComputeEhpTests(_SnapBase):
    CURRENT = ["3068", "3075"]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.result = rank_items_by_ehp(
            cls.snap, "Leona", level=13,
            current_item_ids=list(cls.CURRENT), top_n=300,
        )
        cls.baseline = compute_ehp(
            cls.snap, "Leona", level=13, item_ids=list(cls.CURRENT),
        ).blended_ehp

    def _direct(self, item_id: str) -> float:
        return compute_ehp(
            self.snap, "Leona", level=13,
            item_ids=[*self.CURRENT, item_id],
        ).blended_ehp

    def test_row_count_is_not_vacuous(self) -> None:
        # Every per-row assertion below is a no-op on an empty ranked list, and
        # the filter pipeline has several ways to empty it silently.
        self.assertGreater(len(self.result.ranked), 0)
        self.assertGreater(self.result.candidates_considered, 0)

    def test_baseline_matches_a_direct_compute_on_the_current_build(self) -> None:
        self.assertAlmostEqual(self.result.baseline_ehp, self.baseline, places=6)

    def test_new_ehp_reproduces_a_direct_compute_on_current_plus_candidate(self) -> None:
        # The claim the tautological delta==new-baseline check cannot make: the
        # build the ranker actually scored is current_item_ids + [candidate].
        for row in self.result.ranked:
            with self.subTest(item_id=row.item_id, item=row.item_name):
                self.assertAlmostEqual(
                    row.new_ehp, self._direct(row.item_id), places=6,
                    msg=(f"row {row.item_id} ({row.item_name}) reports "
                         f"new_ehp={row.new_ehp:.4f} but a direct compute_ehp on "
                         f"{[*self.CURRENT, row.item_id]} gives "
                         f"{self._direct(row.item_id):.4f}"),
                )

    def test_delta_ehp_is_the_direct_gain_over_the_direct_baseline(self) -> None:
        for row in self.result.ranked:
            with self.subTest(item_id=row.item_id):
                self.assertAlmostEqual(
                    row.delta_ehp, self._direct(row.item_id) - self.baseline,
                    places=6,
                )

    def test_sibling_axes_collapse_to_new_ehp_with_no_enemy_comp(self) -> None:
        # compute_ehp's identity contract: with no enemy_champions and no ally
        # grant, cc_blended / team_blended / sustain sit exactly on the blend.
        # A row where one of them drifts means the ranker populated it from a
        # different build than the one it reported.
        for row in self.result.ranked:
            for field in ("cc_blended_ehp", "sustain_ehp", "team_blended_ehp"):
                with self.subTest(item_id=row.item_id, field=field):
                    self.assertAlmostEqual(
                        getattr(row, field), row.new_ehp, places=6,
                    )

    def test_rows_sorted_descending_by_delta_ehp(self) -> None:
        deltas = [row.delta_ehp for row in self.result.ranked]
        self.assertEqual(deltas, sorted(deltas, reverse=True))


if __name__ == "__main__":
    unittest.main()
