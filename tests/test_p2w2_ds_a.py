"""P2-W2 cycle 11 DS-engine audit (slice A) - regression tests.

Covers the FIX-NOW hardening landed in this slice:

* ``missile.spell_travel_time`` rejects a non-finite explicit ``distance``
  (inf / NaN) instead of returning a bare ``Infinity`` travel time that
  serializes to a JSON token breaking downstream ``JSON.parse``.
* ``dps_sweep.compute_dps_sweep`` finite-filters caller-supplied
  ``axis_values`` on BOTH the level axis (where ``int(inf)`` raised
  OverflowError and sank the whole fail-soft sweep) and the resist axes
  (where a NaN armor/MR produced a NaN-bearing ``weighted_dps`` AND a NaN
  ``x``, both bare-token JSON hazards).

Every emitted scorer number must be JSON-finite. Each test asserts the
OLD behavior would have failed (a non-finite leak) and the NEW behavior is
finite / dropped.

Symbols grep-confirmed against the live tree before use:
  data_loader.DataSnapshot.load        (data_loader.py:67)
  missile.spell_travel_time            (missile.py:112)
  dps_sweep.compute_dps_sweep          (dps_sweep.py:151)
  dps_sweep.SweepResult                (dps_sweep.py:88)
  objdamage.compute_objdamage          (objdamage.py:719)
  objdamage._mechanism_value           (objdamage.py:132)
  objdamage.ObjDamageEntry             (objdamage.py:112)
  dps._armor_factor                    (dps.py:196)
"""

from __future__ import annotations

import json
import math

import pytest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import _armor_factor
from agents.daemon_slayer.dps_sweep import (
    AXIS_LEVEL,
    AXIS_TARGET_ARMOR,
    AXIS_TARGET_MR,
    compute_dps_sweep,
)
from agents.daemon_slayer.missile import spell_travel_time
from agents.daemon_slayer.objdamage import (
    ObjDamageEntry,
    _mechanism_value,
    compute_objdamage,
)


@pytest.fixture(scope="module")
def snap() -> DataSnapshot:
    return DataSnapshot.load()


# ---------------------------------------------------------------------------
# missile.spell_travel_time - non-finite explicit distance
# ---------------------------------------------------------------------------


class TestMissileNonFiniteDistance:
    def test_inf_distance_does_not_return_infinity(self, snap: DataSnapshot) -> None:
        # Lux Q is a real projectile (~1200 u/s). Pre-fix, distance=inf
        # passed the ``distance > 0`` gate and returned inf -> a bare
        # ``Infinity`` JSON token. Post-fix it falls back to geometry /
        # default, yielding a finite travel time.
        t = spell_travel_time(snap, "Lux", "Q", distance=float("inf"))
        assert t is not None
        assert math.isfinite(t), f"expected finite travel, got {t!r}"
        # The fallback distance/speed is small and positive.
        assert t > 0.0

    def test_inf_distance_matches_geometry_fallback(self, snap: DataSnapshot) -> None:
        # inf distance must resolve to exactly the same value as omitting
        # distance entirely (both take the geometry / _DEFAULT_DISTANCE path).
        t_inf = spell_travel_time(snap, "Lux", "Q", distance=float("inf"))
        t_default = spell_travel_time(snap, "Lux", "Q")
        assert t_inf == t_default

    def test_nan_distance_falls_back_finite(self, snap: DataSnapshot) -> None:
        # NaN was already rejected by ``nan > 0`` being False, but pin the
        # behavior so a future refactor can't regress it to a NaN return.
        t = spell_travel_time(snap, "Lux", "Q", distance=float("nan"))
        assert t is not None
        assert math.isfinite(t)

    def test_finite_distance_still_honored(self, snap: DataSnapshot) -> None:
        # A finite explicit distance must still compute dist/speed directly.
        t = spell_travel_time(snap, "Lux", "Q", distance=1200.0)
        assert t is not None and math.isfinite(t)
        assert t == pytest.approx(1200.0 / 1200.0, abs=1e-3)

    def test_travel_time_is_json_serializable(self, snap: DataSnapshot) -> None:
        # The whole point: the returned value must round-trip through strict
        # JSON (no NaN/Infinity bare tokens).
        t = spell_travel_time(snap, "Lux", "Q", distance=float("inf"))
        encoded = json.dumps({"travel": t}, allow_nan=False)
        assert "Infinity" not in encoded


# ---------------------------------------------------------------------------
# dps_sweep.compute_dps_sweep - non-finite axis values
# ---------------------------------------------------------------------------


class TestSweepNonFiniteAxisValues:
    def test_resist_axis_drops_nan_and_inf(self, snap: DataSnapshot) -> None:
        # Pre-fix: a NaN armor produced SweepPoint(x=nan, weighted_dps=nan)
        # and inf produced x=inf - both bare-token JSON hazards. Post-fix
        # both are dropped, leaving only the two finite samples.
        res = compute_dps_sweep(
            snap,
            "Ashe",
            axis=AXIS_TARGET_ARMOR,
            axis_values=[0.0, float("inf"), float("nan"), 50.0],
        )
        xs = [p.x for p in res.points]
        assert xs == [0.0, 50.0], f"non-finite axis values leaked: {xs!r}"
        for p in res.points:
            assert math.isfinite(p.x)
            assert math.isfinite(p.weighted_dps)

    def test_resist_axis_output_is_strict_json(self, snap: DataSnapshot) -> None:
        res = compute_dps_sweep(
            snap,
            "Ashe",
            axis=AXIS_TARGET_MR,
            axis_values=[0.0, float("nan"), 60.0],
        )
        # allow_nan=False raises ValueError if any bare NaN/Infinity leaks.
        encoded = json.dumps(res.to_dict(), allow_nan=False)
        assert "NaN" not in encoded and "Infinity" not in encoded

    def test_level_axis_inf_does_not_sink_sweep(self, snap: DataSnapshot) -> None:
        # Pre-fix: int(inf) raised OverflowError out of compute_dps_sweep,
        # turning the documented fail-soft into a 500. Post-fix the inf is
        # filtered and the finite levels still produce points.
        res = compute_dps_sweep(
            snap,
            "Ashe",
            axis=AXIS_LEVEL,
            axis_values=[1, float("inf"), 11, float("nan"), 18],
        )
        assert not res.empty
        levels = sorted(int(p.x) for p in res.points)
        assert levels == [1, 11, 18]
        for p in res.points:
            assert math.isfinite(p.weighted_dps)

    def test_clean_axis_values_unchanged(self, snap: DataSnapshot) -> None:
        # A clean axis list must be byte-identical to pre-fix behavior.
        res = compute_dps_sweep(
            snap, "Ashe", axis=AXIS_TARGET_ARMOR, axis_values=[0.0, 25.0, 100.0]
        )
        assert [p.x for p in res.points] == [0.0, 25.0, 100.0]
        # DPS must be monotonic non-increasing in armor (sanity, not pinned).
        dps = [p.weighted_dps for p in res.points]
        assert dps[0] >= dps[1] >= dps[2]


# ---------------------------------------------------------------------------
# objdamage - characterization (no production change; lock JSON-safety +
# the top_kind/total invariants the slice relied on while auditing).
# ---------------------------------------------------------------------------


class TestObjDamageInvariants:
    def test_armor_factor_total_safe(self) -> None:
        # _armor_factor never divides by zero across the full real domain
        # (the proc/AA mitigation curve the scorers share).
        for a in (-300.0, -99.9, -1.0, 0.0, 1.0, 100.0, 300.0, 1000.0):
            assert math.isfinite(_armor_factor(a))

    def test_unknown_champion_is_zero_not_raise(self) -> None:
        r = compute_objdamage("NotAChampion")
        assert r.objdamage_score == 0.0
        assert r.top_kind == ""
        assert r.pressures_structures is False
        assert r.sources == ()

    def test_blank_champion_is_zero(self) -> None:
        r = compute_objdamage("")
        assert r.objdamage_score == 0.0
        assert r.top_kind == ""

    def test_zero_magnitude_entry_contributes_nothing(self) -> None:
        # A 0-magnitude mechanism scores 0; it must never set top_kind on a
        # champion whose total is otherwise 0 (the -1.0 sentinel edge).
        e = ObjDamageEntry("Q", "SUSTAINED_DPS", "BOTH", magnitude=0.0)
        assert _mechanism_value(e) == 0.0

    def test_unknown_kind_scope_score_zero(self) -> None:
        assert _mechanism_value(ObjDamageEntry("Q", "BOGUS", "BOTH", magnitude=1.0)) == 0.0
        assert _mechanism_value(ObjDamageEntry("Q", "SUSTAINED_DPS", "BOGUS", magnitude=1.0)) == 0.0

    def test_known_champion_json_safe(self) -> None:
        r = compute_objdamage("Ziggs")
        assert r.objdamage_score > 0.0
        encoded = json.dumps(r.to_dict(), allow_nan=False)
        assert "NaN" not in encoded and "Infinity" not in encoded
