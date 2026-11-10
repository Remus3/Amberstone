"""S144-D-160..162 - the ability heal/shield scorer reads only sane HP fractions.

Measured at HEAD (lane/ds, 2026-11-08) through the public Python API:

* S144-D-160: ``_missing_hp_heal_amp_factor`` clamps to [0, 1] with two ``<``
  / ``>`` compares, and NaN fails both, so ``caster_missing_hp_pct=nan`` with
  ``assume_missing_hp_heal_amp=True`` returned a NaN factor and a NaN Master Yi
  heal total (``compute_hps`` / ``rank_items_by_hps`` forward the same value).
* S144-D-161: under ``resolve_target_relative=True`` the caster-missing-HP
  units resolve ``caster_max_hp * caster_missing_hp_pct`` with no clamp: Tahm
  Kench L11 ``total_heal_per_sec`` read 7.43 at 1.0 missing but 30.68 at 5.0
  (more than his whole HP missing), 0.0 at -1.0 (the heal erased) and NaN at
  NaN (``total_ability_hps``, heal plus shield: 13.18 / 36.43 / 5.75 / NaN,
  re-measured by the verifier). The same product
  feeds the bilinear ``caster_missing_hp`` / ``target_missing_hp`` terms.
* S144-D-162: ``target_max_hp`` non-finite under the same opt-in made Taric's
  target-relative shield NaN (nan) or +inf (inf).

Contract after the fix: a missing-HP fraction is clamped to [0, 1] (the clamp
the amp helper already documents), a non-finite one reads as 0.0 (full HP, no
assumption), and a non-finite or negative ``target_max_hp`` reads as 0.0 (the
documented lower bound). Every finite in-range value is unchanged.
"""
from __future__ import annotations

import math
import unittest

from agents.daemon_slayer.ability_hps import (
    _clamped_hp_fraction,
    _missing_hp_heal_amp_factor,
    compute_ability_hps,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hps import compute_hps

_SNAP = DataSnapshot.load()
_NAN = float("nan")
_INF = float("inf")


def _hps(champion: str, **kw) -> float:
    return compute_ability_hps(_SNAP, champion, 11, **kw).total_ability_hps


class AmpFactorNonFiniteTests(unittest.TestCase):
    """S144-D-160: the amp helper never returns a non-finite factor."""

    def test_nan_reads_as_no_amp(self):
        self.assertEqual(_missing_hp_heal_amp_factor("MasterYi", "W", _NAN), 1.0)

    def test_infinities_read_as_no_amp(self):
        for v in (_INF, -_INF):
            with self.subTest(v=v):
                self.assertEqual(
                    _missing_hp_heal_amp_factor("MasterYi", "W", v), 1.0,
                )

    def test_finite_clamp_unchanged(self):
        self.assertEqual(_missing_hp_heal_amp_factor("MasterYi", "W", 2.0), 2.0)
        self.assertEqual(_missing_hp_heal_amp_factor("MasterYi", "W", -1.0), 1.0)
        self.assertEqual(_missing_hp_heal_amp_factor("MasterYi", "W", 0.5), 1.5)
        self.assertAlmostEqual(
            _missing_hp_heal_amp_factor("Briar", "P", 0.5), 1.2,
        )

    def test_master_yi_heal_stays_finite_at_nan(self):
        base = _hps("MasterYi", assume_missing_hp_heal_amp=True,
                    caster_missing_hp_pct=0.0)
        self.assertGreater(base, 0.0)
        got = _hps("MasterYi", assume_missing_hp_heal_amp=True,
                   caster_missing_hp_pct=_NAN)
        self.assertTrue(math.isfinite(got), got)
        self.assertEqual(got, base)

    def test_compute_hps_forwards_a_finite_total(self):
        r = compute_hps(_SNAP, "MasterYi", 11, assume_missing_hp_heal_amp=True,
                        caster_missing_hp_pct=_NAN)
        self.assertTrue(math.isfinite(r.ability_hps_total), r.ability_hps_total)
        self.assertTrue(math.isfinite(r.total_throughput), r.total_throughput)


class ResolvedCasterMissingHpTests(unittest.TestCase):
    """S144-D-161: resolved caster-missing-HP units read a clamped fraction."""

    CHAMPS = ("TahmKench", "Gangplank")

    def test_consumers_really_read_the_fraction(self):
        # Anchor: without this a fix that zeroed the unit would pass the rest.
        for c in self.CHAMPS:
            with self.subTest(c=c):
                lo = _hps(c, resolve_target_relative=True,
                          caster_missing_hp_pct=0.0)
                hi = _hps(c, resolve_target_relative=True,
                          caster_missing_hp_pct=1.0)
                self.assertGreater(hi, lo)

    def test_above_one_clamps_to_one(self):
        for c in self.CHAMPS:
            with self.subTest(c=c):
                self.assertEqual(
                    _hps(c, resolve_target_relative=True,
                         caster_missing_hp_pct=5.0),
                    _hps(c, resolve_target_relative=True,
                         caster_missing_hp_pct=1.0),
                )

    def test_negative_clamps_to_zero(self):
        for c in self.CHAMPS:
            with self.subTest(c=c):
                self.assertEqual(
                    _hps(c, resolve_target_relative=True,
                         caster_missing_hp_pct=-1.0),
                    _hps(c, resolve_target_relative=True,
                         caster_missing_hp_pct=0.0),
                )

    def test_non_finite_reads_as_full_hp(self):
        for c in self.CHAMPS:
            base = _hps(c, resolve_target_relative=True,
                        caster_missing_hp_pct=0.0)
            for v in (_NAN, _INF, -_INF):
                with self.subTest(c=c, v=v):
                    self.assertEqual(
                        _hps(c, resolve_target_relative=True,
                             caster_missing_hp_pct=v),
                        base,
                    )

    def test_in_range_is_monotone(self):
        for c in self.CHAMPS:
            vals = [
                _hps(c, resolve_target_relative=True, caster_missing_hp_pct=p)
                for p in (0.0, 0.25, 0.5, 0.75, 1.0)
            ]
            with self.subTest(c=c):
                self.assertEqual(vals, sorted(vals))


class TargetMaxHpTests(unittest.TestCase):
    """S144-D-162: a non-finite or negative target_max_hp reads as 0.0."""

    def test_taric_reads_target_max_hp(self):
        self.assertGreater(
            _hps("Taric", resolve_target_relative=True, target_max_hp=2000.0),
            _hps("Taric", resolve_target_relative=True, target_max_hp=0.0),
        )

    def test_junk_target_max_hp_is_the_zero_lower_bound(self):
        base = _hps("Taric", resolve_target_relative=True, target_max_hp=0.0)
        for v in (_NAN, _INF, -_INF, -2000.0):
            with self.subTest(v=v):
                got = _hps("Taric", resolve_target_relative=True,
                           target_max_hp=v)
                self.assertTrue(math.isfinite(got), got)
                self.assertEqual(got, base)


class ClampedHpFractionTests(unittest.TestCase):
    """The shared normalizer (covers target_missing_hp_pct, which no snapshot
    block consumes today, so an end-to-end probe of it would be vacuous)."""

    def test_values(self):
        cases = {
            0.0: 0.0, 0.4: 0.4, 1.0: 1.0, 1.5: 1.0, -0.2: 0.0,
            _NAN: 0.0, _INF: 0.0, -_INF: 0.0,
        }
        for v, want in cases.items():
            with self.subTest(v=v):
                self.assertEqual(_clamped_hp_fraction(v), want)

    def test_unconvertible_reads_as_zero(self):
        for v in (None, "half", object()):
            with self.subTest(v=repr(v)):
                self.assertEqual(_clamped_hp_fraction(v), 0.0)

    def test_target_missing_hp_pct_is_clamped_before_resolution(self):
        # Every snapshot champion is unaffected (no consumer), so this pins
        # only that junk never raises and stays finite.
        for v in (_NAN, 5.0, -1.0):
            with self.subTest(v=v):
                got = _hps("Taric", resolve_target_relative=True,
                           target_max_hp=2000.0, target_missing_hp_pct=v)
                self.assertTrue(math.isfinite(got), got)


if __name__ == "__main__":
    unittest.main()
