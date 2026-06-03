"""Item 289 - effects-text ALLY-TARGETED survivability grant registry.

The SIXTH survivability axis, and the FIRST that scores a DIFFERENT champion than
the caster. The five self axes (heal/shield throughput, DR denominator
multiplier, resist denominator add, revive numerator multiplier) all raise the
CASTER's own Effective HP; an ally-targeted grant rides a TEAMMATE - the value
the granter confers is added to the PROTECTED ALLY's Effective HP. This is the
"the grant rides an ally, not the caster - the Orianna-E ball-attached class"
that the item-264..272 resist registry AND the item-288 revive registry both
flagged as the remaining survivability exclusion.

Two ally sub-axes (the ally analogs of self resist 264-272 + self revive 288):
  - ALLY RESIST: Orianna E (6/12/18/24/30 armor+MR flat), Braum W (20..40 base),
    Taric W (6..10% of the GRANTER's total armor). Raises the protected ally's
    armor/MR denominator.
  - ALLY REVIVE: Renata W (restored to 100% max health -> fraction 1.0). A
    numerator multiplier on the protected ally's EHP.

Generic consumer seam: ``compute_ehp(external_resist_armor=, external_resist_mr=,
external_revive_multiplier=)`` (default 0.0/0.0/1.0 = byte-identical). The grant
value is sourced from the granter-side registry and fed into the protected ally's
``compute_ehp``. ``apply_ally_grant`` defaults False -> aggregators return
(0,0)/1.0. EXHAUSTIVE scan documented (ally shields/heals = ability_hps;
invuln/death-prevent windows = a different seam; flat-heal revives need the ally
max HP; Ornn P = a false positive).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer._passive_ally_grant_overrides import (
    _ALLY_REVIVE_PROB,
    _PASSIVE_ALLY_GRANT_OVERRIDES,
    AllyGrantEntry,
    ally_resist_grant,
    ally_revive_multiplier,
)
from agents.daemon_slayer._passive_resist_overrides import _ACTIVE_RESIST_PROB

_ORIANNA = ("Orianna", "E", 0)
_BRAUM = ("Braum", "W", 0)
_TARIC = ("Taric", "W", 0)
_RENATA = ("Renata", "W", 0)


class AllyReviveProbConstantTests(unittest.TestCase):
    def test_midpoint_value(self):
        self.assertEqual(_ALLY_REVIVE_PROB, 0.3)

    def test_below_self_revive_midpoint(self):
        # Renata's revive is more conditional than a self revive (burn-gated), so
        # the ally midpoint is below the self _REVIVE_PROB (0.4).
        from agents.daemon_slayer._passive_revive_overrides import _REVIVE_PROB
        self.assertLess(_ALLY_REVIVE_PROB, _REVIVE_PROB)
        self.assertGreater(_ALLY_REVIVE_PROB, 0.0)


class RegistryShapeTests(unittest.TestCase):
    def test_four_clean_entries(self):
        # EXHAUSTIVE scan: the clean ally-grant set is exactly these 4.
        self.assertEqual(len(_PASSIVE_ALLY_GRANT_OVERRIDES), 4)
        self.assertEqual(
            {k[0] for k in _PASSIVE_ALLY_GRANT_OVERRIDES},
            {"Orianna", "Braum", "Taric", "Renata"},
        )

    def test_orianna_is_flat_resist(self):
        e = _PASSIVE_ALLY_GRANT_OVERRIDES[_ORIANNA]
        self.assertEqual(e.armor, (6.0, 12.0, 18.0, 24.0, 30.0))
        self.assertEqual(e.mr, (6.0, 12.0, 18.0, 24.0, 30.0))
        self.assertTrue(e.rank_scaled)
        self.assertEqual(e.conditional_probability, 1.0)
        self.assertEqual(e.revived_hp_fraction, 0.0)

    def test_braum_is_flat_resist_active(self):
        e = _PASSIVE_ALLY_GRANT_OVERRIDES[_BRAUM]
        self.assertEqual(e.armor, (20.0, 25.0, 30.0, 35.0, 40.0))
        self.assertEqual(e.mr, (20.0, 25.0, 30.0, 35.0, 40.0))
        self.assertEqual(e.conditional_probability, _ACTIVE_RESIST_PROB)

    def test_taric_is_percent_of_granter_armor_only(self):
        e = _PASSIVE_ALLY_GRANT_OVERRIDES[_TARIC]
        self.assertEqual(e.armor_pct, (6.0, 7.0, 8.0, 9.0, 10.0))
        self.assertEqual(e.mr_pct, 0.0)  # ARMOR ONLY
        self.assertEqual(e.pct_base, "total")
        self.assertEqual(e.armor, 0.0)  # no flat half

    def test_renata_is_full_hp_ally_revive(self):
        e = _PASSIVE_ALLY_GRANT_OVERRIDES[_RENATA]
        self.assertEqual(e.revived_hp_fraction, 1.0)
        self.assertEqual(e.conditional_probability, _ALLY_REVIVE_PROB)
        self.assertEqual(e.armor, 0.0)
        self.assertEqual(e.mr, 0.0)


class AllyResistGrantMathTests(unittest.TestCase):
    def test_flag_off_is_zero(self):
        for c in ("Orianna", "Braum", "Taric", "Caitlyn"):
            self.assertEqual(ally_resist_grant(c, 18, False), (0.0, 0.0))

    def test_orianna_flat_at_max_e_rank(self):
        # E rank-scaled; at lvl 18 E is maxed (rank 4) -> 30 armor + 30 MR, prob 1.
        a, m = ally_resist_grant("Orianna", 18, True)
        self.assertAlmostEqual(a, 30.0, places=3)
        self.assertAlmostEqual(m, 30.0, places=3)

    def test_orianna_self_contained_ignores_granter_resists(self):
        # The flat grant does not depend on any granter/ally build resist.
        a0, m0 = ally_resist_grant("Orianna", 18, True)
        a1, m1 = ally_resist_grant(
            "Orianna", 18, True, granter_total_armor=300.0, granter_total_mr=300.0
        )
        self.assertEqual((a0, m0), (a1, m1))

    def test_braum_amortized_by_active_prob(self):
        # Ally base maxed (40 by W rank at lvl 18) * _ACTIVE_RESIST_PROB.
        a, m = ally_resist_grant("Braum", 18, True)
        self.assertAlmostEqual(a, 40.0 * _ACTIVE_RESIST_PROB, places=3)
        self.assertAlmostEqual(m, 40.0 * _ACTIVE_RESIST_PROB, places=3)

    def test_taric_percent_needs_granter_armor(self):
        # Percent-of-GRANTER mode: 0 until the granter's resolved armor is given.
        a0, m0 = ally_resist_grant("Taric", 18, True)
        self.assertEqual((a0, m0), (0.0, 0.0))
        # W maxed (rank 4) -> 10% of Taric's 200 total armor = 20; MR 0 (armor only).
        a1, m1 = ally_resist_grant("Taric", 18, True, granter_total_armor=200.0)
        self.assertAlmostEqual(a1, 20.0, places=3)
        self.assertEqual(m1, 0.0)

    def test_non_entry_champ_is_zero_on(self):
        for c in ("Caitlyn", "Garen", "Anivia"):
            self.assertEqual(ally_resist_grant(c, 16, True), (0.0, 0.0))


class AllyReviveMultiplierMathTests(unittest.TestCase):
    def test_flag_off_is_identity(self):
        for c in ("Renata", "Zilean", "Caitlyn"):
            self.assertEqual(ally_revive_multiplier(c, 11, False), 1.0)

    def test_renata_full_revive_is_one_plus_prob(self):
        # 1 + 1.0 * 0.3 = 1.30, flat at every level.
        for lvl in (1, 6, 11, 16, 18):
            self.assertAlmostEqual(
                ally_revive_multiplier("Renata", lvl, True), 1.0 + _ALLY_REVIVE_PROB
            )

    def test_non_revive_entry_champ_is_identity(self):
        # Orianna / Braum / Taric grant resist, not a revive -> multiplier 1.0.
        for c in ("Orianna", "Braum", "Taric", "Caitlyn"):
            self.assertEqual(ally_revive_multiplier(c, 16, True), 1.0)

    def test_synthetic_entry_math(self):
        for frac, prob in ((1.0, 0.3), (0.5, 0.4)):
            e = AllyGrantEntry(revived_hp_fraction=frac, conditional_probability=prob)
            self.assertAlmostEqual(
                1.0 + frac * e.conditional_probability, 1.0 + frac * prob
            )


class EhpExternalSeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_external_defaults_byte_identical(self):
        # The seam defaults (0/0/1.0) leave a non-entry champ untouched, and the
        # default call (params omitted) matches the explicit no-op.
        base = compute_ehp(self.snap, "Caitlyn", 16, item_ids=[])
        noop = compute_ehp(
            self.snap, "Caitlyn", 16, item_ids=[],
            external_resist_armor=0.0, external_resist_mr=0.0,
            external_revive_multiplier=1.0,
        )
        self.assertEqual(noop.blended_ehp, base.blended_ehp)
        self.assertEqual(noop.ally_grant_armor, 0.0)
        self.assertEqual(noop.ally_grant_mr, 0.0)
        self.assertEqual(noop.ally_grant_revive_mult, 1.0)

    def test_external_resist_raises_ally_ehp(self):
        # Feed Orianna's ally grant into a protected ally's EHP: a positive resist
        # add lowers the resistance curve -> a larger physical/magical EHP.
        a, m = ally_resist_grant("Orianna", 18, True)
        off = compute_ehp(self.snap, "Caitlyn", 18, item_ids=[])
        on = compute_ehp(
            self.snap, "Caitlyn", 18, item_ids=[],
            external_resist_armor=a, external_resist_mr=m,
        )
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertEqual(on.ally_grant_armor, a)
        self.assertEqual(on.ally_grant_mr, m)
        # True EHP is resist-independent -> unchanged by an armor/MR add.
        self.assertAlmostEqual(on.true_ehp, off.true_ehp, places=3)

    def test_external_resist_matches_self_resist_curve(self):
        # An external armor add must move EHP identically to the same self bonus
        # armor: feed +30 externally and confirm physical EHP matches a hand
        # computation off the reported curve (numerator unchanged, denom via armor).
        off = compute_ehp(self.snap, "Caitlyn", 11, item_ids=[])
        on = compute_ehp(
            self.snap, "Caitlyn", 11, item_ids=[], external_resist_armor=30.0
        )
        # physical_ehp scales by armor_factor(armor) / armor_factor(armor+30).
        f_off = 1.0 + off.armor / 100.0
        f_on = 1.0 + (off.armor + 30.0) / 100.0
        self.assertAlmostEqual(
            on.physical_ehp, off.physical_ehp * (f_on / f_off), places=2
        )

    def test_external_revive_scales_all_axes_uniformly(self):
        mult = ally_revive_multiplier("Renata", 11, True)  # 1.30
        off = compute_ehp(self.snap, "Caitlyn", 11, item_ids=[])
        on = compute_ehp(
            self.snap, "Caitlyn", 11, item_ids=[], external_revive_multiplier=mult
        )
        self.assertAlmostEqual(on.physical_ehp, off.physical_ehp * mult, places=3)
        self.assertAlmostEqual(on.magical_ehp, off.magical_ehp * mult, places=3)
        self.assertAlmostEqual(on.true_ehp, off.true_ehp * mult, places=3)
        self.assertAlmostEqual(on.blended_ehp, off.blended_ehp * mult, places=3)
        self.assertAlmostEqual(on.ally_grant_revive_mult, mult, places=4)

    def test_external_revive_is_distinct_from_self_revive_field(self):
        # The ally revive surfaces on ally_grant_revive_mult; the SELF
        # passive_revive_mult stays 1.0 (Caitlyn has no self revive).
        on = compute_ehp(
            self.snap, "Caitlyn", 11, item_ids=[], external_revive_multiplier=1.3
        )
        self.assertAlmostEqual(on.ally_grant_revive_mult, 1.3, places=4)
        self.assertEqual(on.passive_revive_mult, 1.0)

    def test_to_dict_carries_ally_grant_fields(self):
        a, m = ally_resist_grant("Orianna", 18, True)
        d = compute_ehp(
            self.snap, "Caitlyn", 18, item_ids=[],
            external_resist_armor=a, external_resist_mr=m,
            external_revive_multiplier=1.3,
        ).to_dict()
        self.assertEqual(d["ally_grant_armor"], a)
        self.assertEqual(d["ally_grant_mr"], m)
        self.assertAlmostEqual(d["ally_grant_revive_mult"], 1.3, places=4)

    def test_negative_external_resist_clamped(self):
        # Defensive: a negative external add is clamped to 0 (never lowers EHP).
        off = compute_ehp(self.snap, "Caitlyn", 11, item_ids=[])
        on = compute_ehp(
            self.snap, "Caitlyn", 11, item_ids=[], external_resist_armor=-50.0
        )
        self.assertEqual(on.blended_ehp, off.blended_ehp)
        self.assertEqual(on.ally_grant_armor, 0.0)


class ExclusionDocTests(unittest.TestCase):
    def test_ally_shields_heals_not_in_registry(self):
        # Ally shields/heals are ability_hps THROUGHPUT, not this axis.
        cids = {k[0] for k in _PASSIVE_ALLY_GRANT_OVERRIDES}
        for c in ("Janna", "Lulu", "Karma", "Yuumi", "Soraka"):
            self.assertNotIn(c, cids)

    def test_invuln_death_prevention_windows_excluded(self):
        # Binary "cannot die / cannot be hit" windows are a different seam (would
        # be infinite EHP), NOT modeled as a finite EHP multiplier.
        cids = {k[0] for k in _PASSIVE_ALLY_GRANT_OVERRIDES}
        for c in ("Kindred", "Kayle", "Galio", "TahmKench", "Kalista", "Ryze"):
            self.assertNotIn(c, cids)
        # Taric appears only for W (Bastion resist), never R (Cosmic Radiance invuln).
        self.assertIn(("Taric", "W", 0), _PASSIVE_ALLY_GRANT_OVERRIDES)
        self.assertNotIn(("Taric", "R", 0), _PASSIVE_ALLY_GRANT_OVERRIDES)

    def test_flat_heal_ally_revives_deferred(self):
        # Zilean R / Akshan W revive to a flat heal / base HP -> the second-life
        # fraction needs the protected ally's max HP (not a granter-side constant)
        # AND the value is absent from the parsed block. Renata W (100% -> 1.0) is
        # the only ally revive with no ally-HP dependency, so the only one seeded.
        cids = {k[0] for k in _PASSIVE_ALLY_GRANT_OVERRIDES}
        for c in ("Zilean", "Akshan"):
            self.assertNotIn(c, cids)
        self.assertIn("Renata", cids)

    def test_ornn_false_positive_excluded(self):
        # Ornn P Living Forge upgrades ITEMS (Masterwork), it does not grant an
        # ally a resist - a false-positive scan hit.
        cids = {k[0] for k in _PASSIVE_ALLY_GRANT_OVERRIDES}
        self.assertNotIn("Ornn", cids)


if __name__ == "__main__":
    unittest.main()
