"""RM-101 - Bone Plating (rune 8473) rune-keyed flat per-instance mitigation.

Pins the registry that closes the RUNE-side hole in the flat per-instance
damage-block lane. The champion sibling
``_passive_flat_mitigation_overrides`` is keyed by ``champion_id``, so a RUNE
can never match it - the same structural gap ``_rune_resist_grants`` filled for
the resist axis. ``_rune_resist_grants.py:55-57`` names 8473 explicitly as
rejected from THAT registry because it is "a flat per-instance damage BLOCK",
which is this lane.

WHAT MAKES 8473 SPECIAL, and what this file exists to guard: the champion
sibling's single largest assumption is ``_ASSUMED_FLAT_DR_INSTANCES = 6.0``
(``_passive_flat_mitigation_overrides.py:92``) - an operator-tunable proxy for a
per-instance damage feed the engine does not have. Bone Plating STATES its
instance count in the rune text ("the next 3 spells or attacks"), so this
registry REPLACES that assumption with an exact number rather than adding a new
one. GUARD 3 pins that the 3.0 is the stated count and is NOT the assumed 6.0.

THE ROUNDING TRAP (GUARD 2b): ``_lerp_per_level`` rounds to 6 decimal places
(``_passive_damage_overrides.py:215-220``), so the level-13 element is
51.176471 while the raw formula 30 + 30*12/17 gives 51.17647058823529. Every
magnitude assertion here pins against the ENGINE PRIMITIVE or against the
ROUNDED literal - never against a hand-recomputed float.

Ground truth, quoted VERBATIM from
``data/meta_build/ddragon/16.14.1/runesReforged.json`` (id 8473 longDesc):
  "After taking damage from an enemy champion, the next 3 spells or attacks you
   receive from them deal 30-60 (based on level) less damage.<br><br>Duration:
   1.5s<br>Cooldown: 55s"
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._passive_damage_overrides import _lerp_per_level
from agents.daemon_slayer._passive_flat_mitigation_overrides import (
    _ASSUMED_FLAT_DR_INSTANCES,
    ANY as SIBLING_ANY,
    MAG as SIBLING_MAG,
    PHYS as SIBLING_PHYS,
    TRUE as SIBLING_TRUE,
)
from agents.daemon_slayer._rune_flat_mitigation import (
    _BONE_PLATING_INSTANCES,
    _BONE_PLATING_PROB,
    _RUNE_FLAT_MITIGATION,
    ANY,
    MAG,
    PHYS,
    TRUE,
    RuneFlatMitigationEntry,
    rune_flat_mitigation_hp,
)

BONE_PLATING = "8473"


class TestRuneFlatMitigationSeed(unittest.TestCase):
    """GUARD 1 - the registry is seeded from the verbatim DDragon text."""

    def test_bone_plating_is_the_only_seeded_id(self):
        # A deliberate ALLOWLIST, not a tree-wide sweep - the same convention
        # _rune_resist_grants uses. Any future id is a deliberate seeding act.
        self.assertEqual(set(_RUNE_FLAT_MITIGATION), {BONE_PLATING})

    def test_entry_is_the_registry_dataclass(self):
        entry = _RUNE_FLAT_MITIGATION[BONE_PLATING]
        self.assertIsInstance(entry, RuneFlatMitigationEntry)

    def test_note_carries_the_verbatim_ddragon_clause(self):
        # The magnitude, the instance count and the cooldown must all be
        # traceable to the quoted longDesc, so a patch re-extract can re-verify.
        note = _RUNE_FLAT_MITIGATION[BONE_PLATING].note
        self.assertIn("next 3 spells or attacks", note)
        self.assertIn("30-60 (based on level)", note)
        self.assertIn("55s", note)

    def test_axis_vocabulary_matches_the_champion_sibling(self):
        # The two lanes fold into the same three EHP numerators, so the axis
        # tokens must be identical strings or a term would silently miss.
        self.assertEqual((PHYS, MAG, TRUE, ANY),
                         (SIBLING_PHYS, SIBLING_MAG, SIBLING_TRUE, SIBLING_ANY))


class TestBonePlatingMagnitude(unittest.TestCase):
    """GUARD 2 - magnitude is the engine lerp 30 -> 60, not a hand float."""

    def _flat_tuple(self):
        entry = _RUNE_FLAT_MITIGATION[BONE_PLATING]
        self.assertEqual(len(entry.terms), 1, "Bone Plating carries one term")
        flat, _dtype = entry.terms[0]
        return flat

    def test_magnitude_is_the_engine_lerp_30_to_60(self):
        self.assertEqual(self._flat_tuple(), _lerp_per_level(30.0, 60.0))

    def test_magnitude_is_an_18_element_per_level_tuple(self):
        self.assertEqual(len(self._flat_tuple()), 18)

    def test_documented_level_endpoints_and_midpoint(self):
        # The three adjudicated values. 51.176471 is the ROUNDED level-13
        # element, which is what the tuple actually carries.
        flat = self._flat_tuple()
        self.assertEqual(flat[0], 30.0)
        self.assertEqual(flat[12], 51.176471)
        self.assertEqual(flat[17], 60.0)

    def test_rounding_trap_guard(self):
        # GUARD 2b - _lerp_per_level ROUNDS to 6dp. The tuple value is NOT the
        # raw formula. A later pass that "corrects" this to the unrounded float
        # breaks parity with every other per-level registry in the engine.
        raw = 30.0 + 30.0 * 12.0 / 17.0
        flat = self._flat_tuple()
        self.assertNotEqual(flat[12], raw)
        self.assertEqual(flat[12], round(raw, 6))

    def test_axis_is_any_all_three_damage_types(self):
        # "spells or attacks" is untyped in the rune text - the block applies to
        # physical, magical AND true alike.
        _flat, dtype = _RUNE_FLAT_MITIGATION[BONE_PLATING].terms[0]
        self.assertEqual(dtype, ANY)


class TestStatedInstanceCount(unittest.TestCase):
    """GUARD 3 - the instance count is STATED, replacing the sibling's assumption."""

    def test_instances_is_exactly_three(self):
        self.assertEqual(_BONE_PLATING_INSTANCES, 3.0)
        self.assertEqual(_RUNE_FLAT_MITIGATION[BONE_PLATING].instances, 3.0)

    def test_instances_is_not_the_champion_assumed_midpoint(self):
        # The whole point of RM-101: the champion lane GUESSES 6.0 because it has
        # no feed; the rune TEXT states 3. These must never be the same number.
        self.assertEqual(_ASSUMED_FLAT_DR_INSTANCES, 6.0)
        self.assertNotEqual(_BONE_PLATING_INSTANCES, _ASSUMED_FLAT_DR_INSTANCES)


class TestConditionalProbabilityPin(unittest.TestCase):
    """GUARD 4 - the ONE judgement call, pinned so it cannot be quietly raised."""

    def test_seed_is_the_conservative_documented_value(self):
        self.assertEqual(_BONE_PLATING_PROB, 0.25)
        self.assertEqual(
            _RUNE_FLAT_MITIGATION[BONE_PLATING].conditional_probability, 0.25
        )

    def test_seed_is_strictly_below_the_short_active_midpoint(self):
        # 0.3 is the engine-wide "short defensive ACTIVE" midpoint
        # (_passive_resist_overrides._ACTIVE_RESIST_PROB, adopted by
        # _rune_resist_grants._RUNE_ACTIVE_RESIST_PROB and by the champion
        # sibling's Leona W seed). Bone Plating must price BELOW it: its 55s
        # cooldown allows at most one proc per modeled fight (Leona W re-fires on
        # 10-14s), and its block is scoped to a SINGLE attacker ("from them"),
        # which Leona W's ANY term is not. This assertion is the ratchet - a
        # later pass cannot raise the seed to or above 0.3 without deleting it.
        self.assertLess(_BONE_PLATING_PROB, 0.3)

    def test_seed_is_a_real_amortization_not_a_disable(self):
        self.assertGreater(_BONE_PLATING_PROB, 0.0)


class TestDefaultOffInertness(unittest.TestCase):
    """GUARD 5 - DEFAULT-OFF: absent or False flag contributes exactly 0.0."""

    def test_flag_absent_is_exactly_zero_even_with_the_rune_equipped(self):
        got = rune_flat_mitigation_hp([BONE_PLATING], level=13)
        self.assertEqual(got, (0.0, 0.0, 0.0))

    def test_flag_explicitly_false_is_exactly_zero(self):
        got = rune_flat_mitigation_hp(
            [BONE_PLATING], level=18, apply_rune_flat_mitigation=False
        )
        self.assertEqual(got, (0.0, 0.0, 0.0))

    def test_flag_off_is_zero_at_every_level(self):
        for lvl in range(1, 19):
            self.assertEqual(
                rune_flat_mitigation_hp([BONE_PLATING], level=lvl),
                (0.0, 0.0, 0.0),
                f"level {lvl} must be inert with the flag absent",
            )


class TestArmedDiscreteInstanceMath(unittest.TestCase):
    """GUARD 6 - armed, the value is instances * flat * prob on all three axes."""

    def _expected(self, level_index: int) -> float:
        flat = _lerp_per_level(30.0, 60.0)[level_index]
        return _BONE_PLATING_INSTANCES * flat * _BONE_PLATING_PROB

    def test_level_13_matches_the_discrete_instance_math(self):
        phys, mag, true = rune_flat_mitigation_hp(
            [BONE_PLATING], level=13, apply_rune_flat_mitigation=True
        )
        want = self._expected(12)
        self.assertAlmostEqual(phys, want, places=9)
        self.assertAlmostEqual(mag, want, places=9)
        self.assertAlmostEqual(true, want, places=9)

    def test_any_axis_credits_all_three_numerators_equally(self):
        phys, mag, true = rune_flat_mitigation_hp(
            [BONE_PLATING], level=18, apply_rune_flat_mitigation=True
        )
        self.assertEqual(phys, mag)
        self.assertEqual(mag, true)

    def test_level_1_and_18_endpoints_armed(self):
        p1, _m1, _t1 = rune_flat_mitigation_hp(
            [BONE_PLATING], level=1, apply_rune_flat_mitigation=True
        )
        p18, _m18, _t18 = rune_flat_mitigation_hp(
            [BONE_PLATING], level=18, apply_rune_flat_mitigation=True
        )
        self.assertAlmostEqual(p1, self._expected(0), places=9)
        self.assertAlmostEqual(p18, self._expected(17), places=9)
        self.assertGreater(p18, p1)

    def test_level_is_clamped_not_extrapolated(self):
        low, _m, _t = rune_flat_mitigation_hp(
            [BONE_PLATING], level=0, apply_rune_flat_mitigation=True
        )
        high, _m2, _t2 = rune_flat_mitigation_hp(
            [BONE_PLATING], level=99, apply_rune_flat_mitigation=True
        )
        self.assertAlmostEqual(low, self._expected(0), places=9)
        self.assertAlmostEqual(high, self._expected(17), places=9)


class TestLookupBehavior(unittest.TestCase):
    """GUARD 7 - allowlist lookup, id coercion, and family dedup."""

    def test_unregistered_runes_contribute_zero(self):
        # 8439 Aftershock / 8429 Conditioning / 8242 Unflinching belong to the
        # resist lane; 8451 Overgrowth to the health lane. None block damage.
        got = rune_flat_mitigation_hp(
            ["8439", "8429", "8242", "8451"],
            level=13,
            apply_rune_flat_mitigation=True,
        )
        self.assertEqual(got, (0.0, 0.0, 0.0))

    def test_empty_rune_page_is_zero(self):
        got = rune_flat_mitigation_hp([], level=13, apply_rune_flat_mitigation=True)
        self.assertEqual(got, (0.0, 0.0, 0.0))

    def test_int_id_matches_like_the_string_id(self):
        as_int = rune_flat_mitigation_hp(
            [8473], level=13, apply_rune_flat_mitigation=True
        )
        as_str = rune_flat_mitigation_hp(
            ["8473"], level=13, apply_rune_flat_mitigation=True
        )
        self.assertEqual(as_int, as_str)
        self.assertGreater(as_int[0], 0.0)

    def test_duplicate_id_is_credited_once(self):
        once = rune_flat_mitigation_hp(
            [BONE_PLATING], level=13, apply_rune_flat_mitigation=True
        )
        twice = rune_flat_mitigation_hp(
            [BONE_PLATING, 8473], level=13, apply_rune_flat_mitigation=True
        )
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
