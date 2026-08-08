"""R7 (2026-06-19) - per-stack champion self-Attack-Speed passive seam.

Characterization tests for ``_passive_as_overrides`` (the registry) + the
``dps.compute_dps(assume_passive_as_stacks=...)`` seam. Ground truth =
data/daemon_slayer/16.12.1/champion_abilities.json (Meraki content patch 25.15)
effects_descriptions, verified 2026-06-19:

  * Irelia Ionian Fervor:    10% : 25% (by level) bonus AS/stack, max 4 -> 40% : 100%
  * Jax Relentless Assault:  5% : 12.5% (by level) bonus AS/stack, max 8 -> 40% : 100%
  * Ezreal Rising Spell Force: 10% (flat) bonus AS/stack, max 5 -> 50%
  * Volibear The Relentless Storm: (5% + 4% per 100 AP) bonus AS/stack, max 5 -> 25% + 20% per 100 AP

The seam is DEFAULT-OFF (byte-identical); the live default-ON flip is
operator-gated (docs/LIVE_GAME_GATED_SYNC.md, CLAUDE-Settled "per-stack
assumed_stacks").
"""
from __future__ import annotations

import unittest

from agents import daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._passive_as_overrides import (
    passive_as_bonus,
    passive_as_entry,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import (
    _ASSUMED_PASSIVE_AS_STACK_FRACTION,
    compute_dps,
)


class EngineVersion(unittest.TestCase):
    def test_engine_version_pinned(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.275.1")
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.275.1")


class RegistryGroundTruth(unittest.TestCase):
    """Per-stack low/high + max stacks pin to the Meraki effects_descriptions."""

    def test_irelia_pins(self) -> None:
        e = passive_as_entry("Irelia")
        self.assertIsNotNone(e)
        self.assertAlmostEqual(e.per_stack_low, 0.10)
        self.assertAlmostEqual(e.per_stack_high, 0.25)
        self.assertEqual(e.max_stacks, 4)
        self.assertEqual(e.ap_per_stack_per_100, 0.0)

    def test_jax_pins(self) -> None:
        e = passive_as_entry("Jax")
        self.assertAlmostEqual(e.per_stack_low, 0.05)
        self.assertAlmostEqual(e.per_stack_high, 0.125)
        self.assertEqual(e.max_stacks, 8)

    def test_ezreal_flat(self) -> None:
        e = passive_as_entry("Ezreal")
        self.assertAlmostEqual(e.per_stack_low, 0.10)
        self.assertAlmostEqual(e.per_stack_high, 0.10)  # flat (no level scaling)
        self.assertEqual(e.max_stacks, 5)

    def test_volibear_ap_scaled(self) -> None:
        e = passive_as_entry("Volibear")
        self.assertAlmostEqual(e.per_stack_low, 0.05)
        self.assertAlmostEqual(e.per_stack_high, 0.05)  # flat base
        self.assertAlmostEqual(e.ap_per_stack_per_100, 0.04)
        self.assertEqual(e.max_stacks, 5)

    def test_unregistered_is_none(self) -> None:
        self.assertIsNone(passive_as_entry("Garen"))
        self.assertIsNone(passive_as_entry("Caitlyn"))


class FullStackMaxMatchesDocumented(unittest.TestCase):
    """per_stack * max_stacks == the documented max bonus AS, both endpoints."""

    def test_full_stack_level1(self) -> None:
        self.assertAlmostEqual(passive_as_bonus("Irelia", 1), 0.40)
        self.assertAlmostEqual(passive_as_bonus("Jax", 1), 0.40)
        self.assertAlmostEqual(passive_as_bonus("Ezreal", 1), 0.50)
        self.assertAlmostEqual(passive_as_bonus("Volibear", 1), 0.25)

    def test_full_stack_level18(self) -> None:
        self.assertAlmostEqual(passive_as_bonus("Irelia", 18), 1.00)
        self.assertAlmostEqual(passive_as_bonus("Jax", 18), 1.00)
        self.assertAlmostEqual(passive_as_bonus("Ezreal", 18), 0.50)  # flat
        self.assertAlmostEqual(passive_as_bonus("Volibear", 18, ap=0.0), 0.25)

    def test_level_interpolation_midpoint(self) -> None:
        # Jax per-stack at L11 = 0.05 + (0.125-0.05)*(11-1)/17; *8 stacks.
        per_stack = 0.05 + (0.125 - 0.05) * 10 / 17.0
        self.assertAlmostEqual(passive_as_bonus("Jax", 11), per_stack * 8)


class VolibearApScaling(unittest.TestCase):
    """The one AP-scaled passive: bonus rises with caster AP."""

    def test_ap_term(self) -> None:
        # (5% + 4% per 100 AP) * 5 stacks.
        self.assertAlmostEqual(passive_as_bonus("Volibear", 1, ap=100.0), 0.45)
        self.assertAlmostEqual(passive_as_bonus("Volibear", 1, ap=200.0), 0.65)

    def test_ap_ignored_for_non_ap_passive(self) -> None:
        # Jax/Irelia/Ezreal ignore AP entirely.
        self.assertAlmostEqual(passive_as_bonus("Jax", 18, ap=500.0), 1.00)
        self.assertAlmostEqual(passive_as_bonus("Ezreal", 1, ap=500.0), 0.50)


class StackFractionClamp(unittest.TestCase):
    def test_default_fraction_is_full(self) -> None:
        self.assertEqual(_ASSUMED_PASSIVE_AS_STACK_FRACTION, 1.0)

    def test_half_stacks(self) -> None:
        self.assertAlmostEqual(passive_as_bonus("Jax", 18, stack_fraction=0.5), 0.50)

    def test_fraction_clamped_0_1(self) -> None:
        self.assertAlmostEqual(passive_as_bonus("Jax", 18, stack_fraction=2.0), 1.00)
        self.assertAlmostEqual(passive_as_bonus("Jax", 18, stack_fraction=-1.0), 0.0)

    def test_unregistered_zero(self) -> None:
        self.assertEqual(passive_as_bonus("Garen", 11), 0.0)
        self.assertEqual(passive_as_bonus("Caitlyn", 18), 0.0)


class ComputeDpsSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_off_byte_identical(self) -> None:
        for cid in ("Jax", "Ezreal", "Irelia", "Volibear"):
            base = compute_dps(self.snap, cid, level=11, item_ids=["3031"],
                               target_armor=80)
            off = compute_dps(self.snap, cid, level=11, item_ids=["3031"],
                              target_armor=80, assume_passive_as_stacks=False)
            self.assertEqual(base.weighted_dps, off.weighted_dps, msg=cid)
            self.assertEqual(base.phase_dps, off.phase_dps, msg=cid)
            self.assertEqual(base.raw_attack_dps, off.raw_attack_dps, msg=cid)
            # No passive-AS note leaks into the default path.
            self.assertFalse(
                any("per-stack self-AS passive" in n for n in off.notes), msg=cid
            )

    def test_registered_champ_raises_dps(self) -> None:
        for cid in ("Jax", "Ezreal", "Irelia", "Volibear"):
            off = compute_dps(self.snap, cid, level=11, item_ids=["3031"],
                              target_armor=80)
            on = compute_dps(self.snap, cid, level=11, item_ids=["3031"],
                             target_armor=80, assume_passive_as_stacks=True)
            self.assertGreater(on.weighted_dps, off.weighted_dps, msg=cid)
            self.assertTrue(
                any("per-stack self-AS passive" in n for n in on.notes), msg=cid
            )

    def test_unregistered_champ_byte_identical_even_on(self) -> None:
        # A champion with no registered passive is byte-identical with the flag ON.
        off = compute_dps(self.snap, "Caitlyn", level=11, item_ids=["3031"],
                          target_armor=80)
        on = compute_dps(self.snap, "Caitlyn", level=11, item_ids=["3031"],
                         target_armor=80, assume_passive_as_stacks=True)
        self.assertEqual(off.weighted_dps, on.weighted_dps)
        self.assertEqual(off.phase_dps, on.phase_dps)

    def test_volibear_ap_item_raises_passive_more(self) -> None:
        # Volibear's passive scales with AP, so an AP item lifts the seam credit.
        # Rabadon's Deathcap (3089) gives a large AP block.
        no_ap = compute_dps(self.snap, "Volibear", level=11, item_ids=["3031"],
                            target_armor=80, assume_passive_as_stacks=True)
        with_ap = compute_dps(self.snap, "Volibear", level=11, item_ids=["3089"],
                              target_armor=80, assume_passive_as_stacks=True)
        # Both ON; the AP build's passive-AS credit (and thus its AS) is higher.
        self.assertGreater(with_ap.stats.get("ap", 0.0), no_ap.stats.get("ap", 0.0))


class SeamAddsBaseAsScaledFraction(unittest.TestCase):
    """R7 regression guard: ``passive_as_bonus`` returns a bonus-AS FRACTION
    (Jax L11 full stacks ~= 0.75 = +75%), but ``stats['as']`` is FINAL attacks
    per second (engine.py: ``base_as * (1 + bonus_pct)``). The seam must fold
    the passive in as ``base_as * fraction``, NOT add the raw fraction to the
    final AS - otherwise it over-credits AS by a factor of ``1 / base_as``.

    ``weighted_dps`` is exactly affine in rotation AS (``total_attacks =
    basic + basic_time * as``; ``base_dps = total_attacks * avg_dmg / duration``;
    duration is AS-independent), so three builds that differ ONLY in attack speed
    are colinear. Infinity Edge (3031) adds no AS and no every_n_attacks proc;
    Dagger (1042) is pure +12% AS (no AD/crit/AP/on-hit), the AS calibration
    point. The ON build's DPS gain must match a ``base_as * fraction`` AS delta,
    not a raw ``fraction`` delta.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_seam_gain_matches_base_as_scaled_fraction(self) -> None:
        cid, level = "Jax", 11  # AP-independent passive; AS bruiser with autos
        off = compute_dps(self.snap, cid, level=level, item_ids=["3031"],
                          target_armor=80)
        cal = compute_dps(self.snap, cid, level=level, item_ids=["3031", "1042"],
                          target_armor=80)
        on = compute_dps(self.snap, cid, level=level, item_ids=["3031"],
                         target_armor=80, assume_passive_as_stacks=True)
        a0 = off.stats["as"]
        a_cal = cal.stats["as"]
        base_as = float((self.snap.champion(cid).get("stats") or {}).get("attackspeed", 0.0))
        pa = passive_as_bonus(cid, level, ap=off.stats.get("ap", 0.0),
                              stack_fraction=_ASSUMED_PASSIVE_AS_STACK_FRACTION)
        # Preconditions (fail loudly if the fixture stops exercising the seam).
        self.assertGreater(pa, 0.0)
        self.assertGreater(base_as, 0.0)
        self.assertLess(base_as, 1.0)          # base AS < 1, so the bug is large
        self.assertGreater(a_cal, a0)          # Dagger really raised AS
        self.assertNotEqual(on.weighted_dps, off.weighted_dps)  # seam did fire
        self.assertLess(a0 + base_as * pa, 2.5)   # stays under the AS hard cap
        # weighted_dps = c0 + c1*AS; c1 from the pure-AS calibration build.
        c1 = (cal.weighted_dps - off.weighted_dps) / (a_cal - a0)
        predicted_correct = off.weighted_dps + c1 * (base_as * pa)
        predicted_wrong = off.weighted_dps + c1 * pa  # the regression
        # The fix must land on the base_as-scaled prediction...
        self.assertAlmostEqual(
            on.weighted_dps, predicted_correct,
            delta=abs(predicted_correct) * 0.005,
        )
        # ...and be unambiguously NOT the raw-fraction (buggy) magnitude.
        self.assertLess(
            abs(on.weighted_dps - predicted_correct),
            abs(on.weighted_dps - predicted_wrong),
        )


if __name__ == "__main__":
    unittest.main()
