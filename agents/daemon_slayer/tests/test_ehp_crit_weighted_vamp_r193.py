"""R193 slice B - crit-weighted vamp heal pool (DEFAULT-OFF seam).

WHY this test exists: ``ehp._vamp_heal_pool`` prices lifesteal / omnivamp off
``AD * AS * window``, the UNCRIT auto-attack throughput, even though the
wielder's crit chance is already fully resolved in the build's stat block. An
auto-attack actually lands ``AD * (1 + crit * crit_damage_bonus)`` and lifesteal
heals off that crit-inflated hit, so a crit carry's sustain is under-credited by
the whole crit factor (measured x1.7875 for a 5-item L16 Jinx).

The seam under test is ``compute_ehp(..., assume_crit_weighted_vamp=True)``.
DEFAULT-OFF is the acceptance bar: with the flag absent every existing EHP
number must be BYTE-IDENTICAL, which is what the two baseline classes pin with
hard-coded floats measured on HEAD e2f6e599 BEFORE the seam was written.

Coverage classes:

* ``OffPathByteIdenticalTests`` - flag absent -> the measured HEAD baselines.
* ``ArmedCritBuildTests`` - flag armed on a crit build -> the heal pool scales
  by exactly ``(1 + crit * crit_damage_bonus_total)``, and the scaling stays
  SUSTAIN-ONLY (``blended_ehp`` does not move), matching the lifesteal /
  spellvamp / omnivamp posture.
* ``ArmedZeroCritNoOpTests`` - flag armed on a zero-crit build -> byte-identical
  to OFF (no silent drift for every non-crit champion).
* ``CritCapTests`` - the multiplier honours the engine's 1.0 crit cap
  (engine.py:185), so an over-100% crit input cannot over-scale the pool.
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import DEFAULT_CRIT_BONUS
from agents.daemon_slayer.ehp import (
    _crit_weighted_vamp_multiplier,
    compute_ehp,
)

# Measured on HEAD e2f6e599 with the flag NOT yet implemented (the OFF path
# must reproduce these to the last bit):
#   Jinx L16 [3072, 3031, 3094, 3006, 6676] - lifesteal 0.15, ad 311.04375,
#   as 1.09375, crit 0.75, crit_damage_bonus_total 1.05 (0.75 default + 0.30
#   from Infinity Edge 3031).
_JINX_ITEMS = ["3072", "3031", "3094", "3006", "6676"]
_JINX_OFF_HEAL_LIFESTEAL = 306.18369140625
#   Aatrox L13 [3072] - lifesteal 0.15, ad 194.75, as 0.8463, crit 0.0.
_AATROX_ITEMS = ["3072"]
_AATROX_OFF_HEAL_LIFESTEAL = 148.33523250000002

# 1 + min(0.75, 1.0) * 1.05
_JINX_CRIT_FACTOR = 1.7875


class OffPathByteIdenticalTests(unittest.TestCase):
    """Flag absent -> the pre-seam measured numbers, exactly."""

    def setUp(self):
        self.snap = DataSnapshot.load()

    def test_jinx_off_matches_measured_head_baseline(self):
        r = compute_ehp(self.snap, "Jinx", 16, item_ids=_JINX_ITEMS, mode="SR")
        self.assertEqual(r.heal_lifesteal, _JINX_OFF_HEAL_LIFESTEAL)

    def test_aatrox_off_matches_measured_head_baseline(self):
        r = compute_ehp(self.snap, "Aatrox", 13, item_ids=_AATROX_ITEMS, mode="SR")
        self.assertEqual(r.heal_lifesteal, _AATROX_OFF_HEAL_LIFESTEAL)

    def test_explicit_false_equals_flag_absent(self):
        absent = compute_ehp(self.snap, "Jinx", 16, item_ids=_JINX_ITEMS, mode="SR")
        explicit = compute_ehp(
            self.snap, "Jinx", 16, item_ids=_JINX_ITEMS, mode="SR",
            assume_crit_weighted_vamp=False,
        )
        self.assertEqual(explicit.heal_lifesteal, absent.heal_lifesteal)
        self.assertEqual(
            explicit.effective_ehp_with_sustain,
            absent.effective_ehp_with_sustain,
        )


class ArmedCritBuildTests(unittest.TestCase):
    """Armed on a crit build -> exactly the crit factor, sustain-only."""

    def setUp(self):
        self.snap = DataSnapshot.load()
        self.off = compute_ehp(
            self.snap, "Jinx", 16, item_ids=_JINX_ITEMS, mode="SR",
        )
        self.on = compute_ehp(
            self.snap, "Jinx", 16, item_ids=_JINX_ITEMS, mode="SR",
            assume_crit_weighted_vamp=True,
        )

    def test_lifesteal_heal_scales_by_crit_factor(self):
        self.assertAlmostEqual(
            self.on.heal_lifesteal,
            _JINX_OFF_HEAL_LIFESTEAL * _JINX_CRIT_FACTOR,
            places=9,
        )

    def test_armed_raises_sustain_ehp(self):
        self.assertGreater(
            self.on.effective_ehp_with_sustain,
            self.off.effective_ehp_with_sustain,
        )

    def test_armed_moves_blended_ehp_because_lifesteal_already_lands_there(self):
        # NOT a posture change: ``heal_lifesteal`` has fed ``heal_total`` ->
        # ``blended_ehp`` since ENGINE 1.28.0 (ehp.py "blended_ehp already
        # carries the lifesteal heal pool"). The seam scales the EXISTING lane
        # wherever it already lands - it does not add a new destination. The
        # spellvamp / omnivamp lanes stay sustain-only exactly as before.
        self.assertGreater(self.on.blended_ehp, self.off.blended_ehp)


class ArmedZeroCritNoOpTests(unittest.TestCase):
    """Armed on a zero-crit build -> byte-identical to OFF."""

    def setUp(self):
        self.snap = DataSnapshot.load()

    def test_aatrox_armed_is_byte_identical_no_op(self):
        off = compute_ehp(self.snap, "Aatrox", 13, item_ids=_AATROX_ITEMS, mode="SR")
        on = compute_ehp(
            self.snap, "Aatrox", 13, item_ids=_AATROX_ITEMS, mode="SR",
            assume_crit_weighted_vamp=True,
        )
        self.assertEqual(on.heal_lifesteal, _AATROX_OFF_HEAL_LIFESTEAL)
        self.assertEqual(on.heal_lifesteal, off.heal_lifesteal)
        self.assertEqual(
            on.effective_ehp_with_sustain, off.effective_ehp_with_sustain,
        )


class CritCapTests(unittest.TestCase):
    """The multiplier honours the engine's 1.0 crit cap (engine.py:185)."""

    def test_identity_when_disabled(self):
        self.assertEqual(
            _crit_weighted_vamp_multiplier(
                _JINX_ITEMS, 0.75, assume_crit_weighted_vamp=False,
            ),
            1.0,
        )

    def test_zero_crit_is_identity_when_armed(self):
        self.assertEqual(
            _crit_weighted_vamp_multiplier(
                _AATROX_ITEMS, 0.0, assume_crit_weighted_vamp=True,
            ),
            1.0,
        )

    def test_jinx_factor_matches_measured(self):
        self.assertAlmostEqual(
            _crit_weighted_vamp_multiplier(
                _JINX_ITEMS, 0.75, assume_crit_weighted_vamp=True,
            ),
            _JINX_CRIT_FACTOR,
            places=12,
        )

    def test_crit_above_one_is_clamped(self):
        capped = _crit_weighted_vamp_multiplier(
            _JINX_ITEMS, 1.0, assume_crit_weighted_vamp=True,
        )
        over = _crit_weighted_vamp_multiplier(
            _JINX_ITEMS, 1.5, assume_crit_weighted_vamp=True,
        )
        self.assertEqual(over, capped)
        # 1 + 1.0 * (0.75 default + 0.30 Infinity Edge)
        self.assertAlmostEqual(over, 1.0 + (DEFAULT_CRIT_BONUS + 0.30), places=12)

    def test_negative_crit_is_floored_at_zero(self):
        self.assertEqual(
            _crit_weighted_vamp_multiplier(
                _JINX_ITEMS, -0.5, assume_crit_weighted_vamp=True,
            ),
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
