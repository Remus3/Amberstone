"""P2-W2 DS-B audit regression tests (cycle 11).

Covers the FIX-NOW landed in this slice:

  agents/daemon_slayer/antitank.py - ``_effective_magnitude`` / ``_finite_float``
  hardening (standing finding class 1/2). The P3.2 caster-stat path
  (``compute_antitank(..., stats=...)``) read ``stats.get("ap"/"ad")`` and folded
  it straight into ``base + ap * ap_ratio + ad * ad_ratio`` with NO finite guard.
  A degenerate stats mapping could carry:
    * a NaN -> ``antitank_score`` becomes NaN -> ``to_dict()`` -> ``json.dumps``
      emits a bare ``NaN`` token (invalid JSON; breaks the dashboard JSON.parse),
    * an inf -> same invalid-JSON failure,
    * a ``None`` -> ``None * ratio`` raises ``TypeError`` mid-tick.
  The fix coerces ap/ad through ``_finite_float`` and falls back to the static
  ``base`` when the scaled magnitude is non-finite, so the scorer stays fail-soft
  on a seeded (ratio != 0) row while every static path is byte-identical.

These FAIL on the pre-fix code (NaN/inf score, TypeError) and PASS on the fix.
Symbols grep-confirmed live:
  agents/daemon_slayer/antitank.py:_effective_magnitude, _finite_float,
    compute_antitank, AntiTankEntry (Gwen P is the AP-seeded ap_ratio=0.0005 row,
    antitank.py:274).
  agents/daemon_slayer/engine.py:26 ResolvedStats, :43 .get(key, default).
"""
from __future__ import annotations

import json
import math
import unittest

from agents.daemon_slayer.antitank import (
    AntiTankEntry,
    _effective_magnitude,
    _finite_float,
    compute_antitank,
)

# Gwen P: MAX_HP / SUSTAINED, magnitude 0.85, ap_ratio 0.0005 (antitank.py:274).
# Static antitank_score is the single P row's value = 0.85 (no other Gwen rows).
_GWEN_STATIC = 0.85


class FiniteFloatHelperTests(unittest.TestCase):
    """The new ``_finite_float`` coercion at the stat read."""

    def test_plain_value_passthrough(self):
        self.assertEqual(_finite_float(200), 200.0)
        self.assertEqual(_finite_float(0.0), 0.0)
        self.assertEqual(_finite_float(-3.5), -3.5)

    def test_nan_falls_back_to_default(self):
        self.assertEqual(_finite_float(float("nan")), 0.0)
        self.assertEqual(_finite_float(float("nan"), 7.0), 7.0)

    def test_inf_falls_back_to_default(self):
        self.assertEqual(_finite_float(float("inf")), 0.0)
        self.assertEqual(_finite_float(float("-inf")), 0.0)

    def test_none_falls_back_to_default(self):
        self.assertEqual(_finite_float(None), 0.0)

    def test_non_numeric_string_falls_back(self):
        self.assertEqual(_finite_float("not-a-number"), 0.0)


class EffectiveMagnitudeFiniteGuardTests(unittest.TestCase):
    """``_effective_magnitude`` must never emit NaN/inf or raise on a bad stat."""

    def _seeded(self) -> AntiTankEntry:
        return AntiTankEntry(
            "P", "MAX_HP", "SUSTAINED", magnitude=0.85, ap_ratio=0.0005
        )

    def test_nan_ap_returns_finite_base(self):
        m = _effective_magnitude(self._seeded(), {"ap": float("nan")})
        self.assertTrue(math.isfinite(m))
        self.assertAlmostEqual(m, 0.85, places=6)

    def test_inf_ap_returns_finite_base(self):
        m = _effective_magnitude(self._seeded(), {"ap": float("inf")})
        self.assertTrue(math.isfinite(m))
        self.assertAlmostEqual(m, 0.85, places=6)

    def test_none_ap_does_not_raise(self):
        # Pre-fix: None * ap_ratio -> TypeError.
        m = _effective_magnitude(self._seeded(), {"ap": None})
        self.assertAlmostEqual(m, 0.85, places=6)

    def test_finite_scaling_still_applies(self):
        # The guard must not break the normal path: 0.85 + 200*0.0005 = 0.95.
        m = _effective_magnitude(self._seeded(), {"ap": 200})
        self.assertAlmostEqual(m, 0.95, places=6)

    def test_no_stats_is_static_base(self):
        self.assertAlmostEqual(
            _effective_magnitude(self._seeded(), None), 0.85, places=6
        )


class ComputeAntitankFailSoftTests(unittest.TestCase):
    """End-to-end: a degenerate stats dict must not poison the result/JSON."""

    def test_nan_ap_score_is_finite(self):
        r = compute_antitank("Gwen", stats={"ap": float("nan")})
        self.assertTrue(math.isfinite(r.antitank_score))
        self.assertAlmostEqual(r.antitank_score, _GWEN_STATIC, places=6)

    def test_inf_ap_score_is_finite(self):
        r = compute_antitank("Gwen", stats={"ap": float("inf")})
        self.assertTrue(math.isfinite(r.antitank_score))
        self.assertAlmostEqual(r.antitank_score, _GWEN_STATIC, places=6)

    def test_none_ap_does_not_raise(self):
        r = compute_antitank("Gwen", stats={"ap": None})
        self.assertAlmostEqual(r.antitank_score, _GWEN_STATIC, places=6)

    def test_to_dict_emits_no_bare_nan_json_token(self):
        # Pre-fix: json.dumps(to_dict()) emitted a bare ``NaN`` token (invalid
        # JSON that breaks the dashboard parse).
        r = compute_antitank("Gwen", stats={"ap": float("nan")})
        serialized = json.dumps(r.to_dict())
        self.assertNotIn("NaN", serialized)
        self.assertNotIn("Infinity", serialized)
        # And it round-trips as strict JSON.
        json.loads(serialized)

    def test_finite_scaling_unaffected_by_guard(self):
        # 0.85 + 200*0.0005 = 0.95 (the live scaling path stays correct).
        r = compute_antitank("Gwen", stats={"ap": 200})
        self.assertAlmostEqual(r.antitank_score, 0.95, places=6)

    def test_static_path_byte_identical(self):
        self.assertAlmostEqual(
            compute_antitank("Gwen").antitank_score, _GWEN_STATIC, places=6
        )
        self.assertAlmostEqual(
            compute_antitank("Gwen", stats=None).antitank_score,
            _GWEN_STATIC,
            places=6,
        )


if __name__ == "__main__":
    unittest.main()
