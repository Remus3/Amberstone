"""Characterization + regression tests for the target_current_hp_pct lever.

The lever scales ONLY the three genuine %-CURRENT-HP item procs by a
caller-supplied fraction of the target's current HP:
  - BotRK 3153 Mist's Edge (9% current HP on-hit)
  - Hellfire Hatchet 4017 Char ((5 + ...)% current HP over time)
  - Fulmination 443055 Dynamo (13% current HP every 100th attack)

Genuine %-MAX-HP procs (Eclipse 6692, Titanic Hydra 3748, etc.) must NOT
scale - they key off target_max_hp / caster_max_hp which are not the
target's current HP. The default value 1.0 is an identity multiply, so
every pre-change compute_dps result stays byte-identical.

Isolation method: hold a FIXED item build and difference its DPS across
two lever values. An item adds both stat-driven AA DPS (AD / AS / lethality
- lever-invariant) AND its proc DPS; only the proc's current-HP magnitude
moves with the lever, so the stat-driven portion cancels in the delta. The
lever-delta is therefore exactly the change in the proc's current-HP piece.
This avoids fragile absolute magic numbers - what is pinned is the linear
SCALING of the proc, not its patch-dependent absolute DPS.
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps


# Melee champion used across test_dps.py - no ranged-modifier divergence.
_CHAMP = "Aatrox"
_LEVEL = 11
_TARGET_MAX_HP = 3000.0


def _dps(snap, item_id, *, target_current_hp_pct=1.0):
    """weighted_dps for the FIXED single-item build at the given lever."""
    return compute_dps(
        snap, _CHAMP, level=_LEVEL, item_ids=[item_id],
        target_max_hp=_TARGET_MAX_HP,
        target_current_hp_pct=target_current_hp_pct,
    ).weighted_dps


def _item_contribution(snap, item_id):
    """Total DPS the item adds vs naked (proc + stat-driven AA gain).

    Used only to prove the current-HP procs measurably contribute; it is
    NOT used for scaling proofs (it mixes lever-invariant stat DPS in).
    """
    naked = compute_dps(
        snap, _CHAMP, level=_LEVEL, target_max_hp=_TARGET_MAX_HP,
    ).weighted_dps
    return _dps(snap, item_id) - naked


class TargetCurrentHpPctLeverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # (a) default 1.0 is byte-identical to NOT passing the param at all.
    def test_default_is_byte_identical_botrk(self) -> None:
        base = compute_dps(
            self.snap, _CHAMP, level=_LEVEL, item_ids=["3153"],
            target_max_hp=_TARGET_MAX_HP,
        ).weighted_dps
        explicit_one = _dps(self.snap, "3153", target_current_hp_pct=1.0)
        self.assertEqual(base, explicit_one)

    # The three current-HP procs must each have a measurable contribution
    # (guards against the harness silently measuring a zero-magnitude proc).
    def test_current_hp_procs_have_nonzero_contribution(self) -> None:
        for item_id in ("3153", "4017", "443055"):
            with self.subTest(item_id=item_id):
                self.assertGreater(
                    _item_contribution(self.snap, item_id), 0.0
                )

    # (b) The proc's current-HP DPS scales LINEARLY with the lever: the
    # 1.0 -> 0.5 lever-delta equals the 0.5 -> 0.0 lever-delta (each is half
    # the proc's full magnitude), and the delta is strictly positive. The
    # lever-invariant stat DPS cancels in every delta. Proven for all three
    # genuine current-HP procs including Hellfire (whose inner hp-diff term
    # is lever-invariant at a fixed target_max_hp, so the whole Char
    # magnitude is one linear multiple of the lever).
    def test_current_hp_procs_scale_linearly_with_lever(self) -> None:
        for item_id in ("3153", "4017", "443055"):
            with self.subTest(item_id=item_id):
                d_full = _dps(self.snap, item_id, target_current_hp_pct=1.0)
                d_half = _dps(self.snap, item_id, target_current_hp_pct=0.5)
                d_zero = _dps(self.snap, item_id, target_current_hp_pct=0.0)
                top_half = d_full - d_half     # proc DPS from 100% -> 50%
                bottom_half = d_half - d_zero  # proc DPS from 50% -> 0%
                self.assertGreater(top_half, 0.0)
                self.assertAlmostEqual(top_half, bottom_half, places=6)

    # (b cont.) Sanity: halving the lever halves the proc's contribution.
    # full proc DPS = d_full - d_zero; half-lever proc DPS = d_half - d_zero.
    def test_half_lever_halves_proc_magnitude_botrk(self) -> None:
        d_full = _dps(self.snap, "3153", target_current_hp_pct=1.0)
        d_half = _dps(self.snap, "3153", target_current_hp_pct=0.5)
        d_zero = _dps(self.snap, "3153", target_current_hp_pct=0.0)
        full_proc = d_full - d_zero
        half_proc = d_half - d_zero
        self.assertGreater(full_proc, 0.0)
        self.assertAlmostEqual(half_proc, full_proc * 0.5, places=6)

    # (c) Eclipse 6692 (% target MAX HP) is UNCHANGED across lever values -
    # it does not reference target_current_hp_pct.
    def test_eclipse_max_hp_proc_unchanged_across_lever(self) -> None:
        d_full = _dps(self.snap, "6692", target_current_hp_pct=1.0)
        d_half = _dps(self.snap, "6692", target_current_hp_pct=0.5)
        d_zero = _dps(self.snap, "6692", target_current_hp_pct=0.0)
        self.assertEqual(d_full, d_half)
        self.assertEqual(d_full, d_zero)
        # And Eclipse still actually procs (guards a false-equal on a
        # zero-magnitude proc).
        self.assertGreater(_item_contribution(self.snap, "6692"), 0.0)

    # (c) Titanic Hydra 3748 (% caster MAX HP) is UNCHANGED across lever.
    def test_titanic_max_hp_proc_unchanged_across_lever(self) -> None:
        d_full = _dps(self.snap, "3748", target_current_hp_pct=1.0)
        d_half = _dps(self.snap, "3748", target_current_hp_pct=0.5)
        d_zero = _dps(self.snap, "3748", target_current_hp_pct=0.0)
        self.assertEqual(d_full, d_half)
        self.assertEqual(d_full, d_zero)
        self.assertGreater(_item_contribution(self.snap, "3748"), 0.0)


if __name__ == "__main__":
    unittest.main()
