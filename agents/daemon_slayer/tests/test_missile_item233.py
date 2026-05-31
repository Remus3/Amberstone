"""Tests for agents/daemon_slayer/missile.py (item 233).

All live values probed at 16.11.1 DataSnapshot.load() before pinning.

Pinned live values (verified 2026-05-31):
  Lux  Q: missile_speed=1200.0, geometry cone_distance=100.0 (conflated radius)
  Lux  E: missile_speed=1300.0, geometry cone_distance=100.0, cast_radius=295 not conflated
  Lux  W: missile_speed=1200.0, geometry cone_distance=100.0, cast_radius=299.3 not conflated
  Jhin W: missile_speed=10000.0 (instant, >=5000)
  Aatrox E: missile_speed=20.0 (artifact, <400)
  Aatrox Q: missile_speed=None (no missile)
  Aphelios Q: missile_speed=1850.0, geometry cone_distance=None, cast_radius=175 not conflated
  Morgana Q: missile_speed=1200.0, geometry cone_distance=100.0, cast_radius=210 conflated
"""

from __future__ import annotations

import pytest
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.missile import (
    _DEFAULT_DISTANCE,
    _INSTANT_SPEED,
    _MIN_PROJECTILE_SPEED,
    _distance_from_geometry,
    is_projectile,
    spell_travel_time,
)


@pytest.fixture(scope="module")
def snap() -> DataSnapshot:
    return DataSnapshot.load()


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

class TestModuleConstants:
    def test_min_projectile_speed(self) -> None:
        assert _MIN_PROJECTILE_SPEED == 400.0

    def test_instant_speed(self) -> None:
        assert _INSTANT_SPEED == 5000.0

    def test_default_distance(self) -> None:
        assert _DEFAULT_DISTANCE == 1000.0


# ---------------------------------------------------------------------------
# is_projectile
# ---------------------------------------------------------------------------

class TestIsProjectile:
    def test_real_projectile_lux_q(self, snap: DataSnapshot) -> None:
        # Lux Q missile_speed=1200 >= 400
        assert is_projectile(snap, "Lux", "Q") is True

    def test_real_projectile_morgana_q(self, snap: DataSnapshot) -> None:
        # Morgana Q missile_speed=1200
        assert is_projectile(snap, "Morgana", "Q") is True

    def test_instant_jhin_w_is_projectile(self, snap: DataSnapshot) -> None:
        # Jhin W 10000 >= 400, so is_projectile=True (instant, travel=0.0)
        assert is_projectile(snap, "Jhin", "W") is True

    def test_artifact_aatrox_e_false(self, snap: DataSnapshot) -> None:
        # Aatrox E missile_speed=20 < 400
        assert is_projectile(snap, "Aatrox", "E") is False

    def test_no_missile_aatrox_q_false(self, snap: DataSnapshot) -> None:
        # Aatrox Q has no missile (None)
        assert is_projectile(snap, "Aatrox", "Q") is False

    def test_unknown_champ_false(self, snap: DataSnapshot) -> None:
        assert is_projectile(snap, "FakeChamp999", "Q") is False

    def test_absent_slot_false(self, snap: DataSnapshot) -> None:
        # Aatrox W missile_speed=None
        assert is_projectile(snap, "Aatrox", "W") is False


# ---------------------------------------------------------------------------
# spell_travel_time - real projectile (finite positive)
# ---------------------------------------------------------------------------

class TestSpellTravelTimeRealProjectile:
    def test_lux_q_positive_finite(self, snap: DataSnapshot) -> None:
        # Lux Q: speed=1200, cone_distance=100 -> travel=100/1200=0.0833
        t = spell_travel_time(snap, "Lux", "Q")
        assert t is not None
        assert t > 0.0

    def test_lux_q_all_sentinel_geometry_uses_default(self, snap: DataSnapshot) -> None:
        # Lux Q: cone_distance=100 (sentinel) + cast_radius=210 conflated ->
        # geometry yields no real distance -> _DEFAULT_DISTANCE 1000 / 1200 = 0.8333.
        t = spell_travel_time(snap, "Lux", "Q")
        assert t == pytest.approx(1000.0 / 1200.0, abs=1e-3)

    def test_morgana_q_all_sentinel_geometry_uses_default(self, snap: DataSnapshot) -> None:
        # Morgana Q: cone_distance=100 sentinel + cast_radius=210 conflated ->
        # _DEFAULT_DISTANCE 1000 / 1200 = 0.8333.
        t = spell_travel_time(snap, "Morgana", "Q")
        assert t == pytest.approx(1000.0 / 1200.0, abs=1e-3)

    def test_lux_e_real_cast_radius_geometry(self, snap: DataSnapshot) -> None:
        # Lux E: cast_radius=295 non-conflated (>= _MIN_REAL_DISTANCE) ->
        # a REAL geometry distance -> 295 / 1300 = 0.2269.
        t = spell_travel_time(snap, "Lux", "E")
        assert t == pytest.approx(295.0 / 1300.0, abs=1e-3)


# ---------------------------------------------------------------------------
# spell_travel_time - explicit distance arg (linear, parametrized)
# ---------------------------------------------------------------------------

class TestSpellTravelTimeExplicitDistance:
    @pytest.mark.parametrize("dist,expected", [
        (600,  round(600 / 1200.0, 4)),
        (1200, round(1200 / 1200.0, 4)),
        (2400, round(2400 / 1200.0, 4)),
    ])
    def test_lux_q_explicit_distance_linear(
        self, snap: DataSnapshot, dist: float, expected: float
    ) -> None:
        # Lux Q speed=1200; explicit distance overrides geometry
        t = spell_travel_time(snap, "Lux", "Q", distance=dist)
        assert t == pytest.approx(expected, rel=1e-4)

    def test_explicit_distance_1200_equals_one_second(
        self, snap: DataSnapshot
    ) -> None:
        # 1200 units at 1200 u/s = 1.0 s
        t = spell_travel_time(snap, "Lux", "Q", distance=1200)
        assert t == pytest.approx(1.0, rel=1e-4)

    def test_explicit_distance_2400_equals_two_seconds(
        self, snap: DataSnapshot
    ) -> None:
        t = spell_travel_time(snap, "Lux", "Q", distance=2400)
        assert t == pytest.approx(2.0, rel=1e-4)

    def test_explicit_distance_overrides_geometry(
        self, snap: DataSnapshot
    ) -> None:
        # geometry would give cone_distance=100 -> 0.0833; explicit 1200 -> 1.0
        t_geo = spell_travel_time(snap, "Lux", "Q")
        t_exp = spell_travel_time(snap, "Lux", "Q", distance=1200)
        assert t_exp != pytest.approx(t_geo, abs=0.01)

    def test_zero_distance_falls_back_to_geometry(
        self, snap: DataSnapshot
    ) -> None:
        # distance=0 treated as "no explicit distance"
        t_zero = spell_travel_time(snap, "Lux", "Q", distance=0)
        t_none = spell_travel_time(snap, "Lux", "Q")
        assert t_zero == t_none

    def test_negative_distance_falls_back_to_geometry(
        self, snap: DataSnapshot
    ) -> None:
        t_neg = spell_travel_time(snap, "Lux", "Q", distance=-100)
        t_none = spell_travel_time(snap, "Lux", "Q")
        assert t_neg == t_none


# ---------------------------------------------------------------------------
# spell_travel_time - instant / global (0.0)
# ---------------------------------------------------------------------------

class TestSpellTravelTimeInstant:
    def test_jhin_w_instant_zero(self, snap: DataSnapshot) -> None:
        # Jhin W missile_speed=10000 >= _INSTANT_SPEED=5000 -> 0.0
        t = spell_travel_time(snap, "Jhin", "W")
        assert t == 0.0

    def test_instant_is_float_zero(self, snap: DataSnapshot) -> None:
        t = spell_travel_time(snap, "Jhin", "W")
        assert isinstance(t, float)

    def test_instant_with_explicit_distance_still_zero(
        self, snap: DataSnapshot
    ) -> None:
        # instant check happens before distance computation
        t = spell_travel_time(snap, "Jhin", "W", distance=5000)
        assert t == 0.0


# ---------------------------------------------------------------------------
# spell_travel_time - artifact / non-projectile -> None
# ---------------------------------------------------------------------------

class TestSpellTravelTimeArtifact:
    def test_aatrox_e_artifact_none(self, snap: DataSnapshot) -> None:
        # Aatrox E missile_speed=20 < 400 -> None
        assert spell_travel_time(snap, "Aatrox", "E") is None

    def test_aatrox_q_no_missile_none(self, snap: DataSnapshot) -> None:
        # Aatrox Q missile_speed=None -> None
        assert spell_travel_time(snap, "Aatrox", "Q") is None

    def test_unknown_champ_none(self, snap: DataSnapshot) -> None:
        assert spell_travel_time(snap, "FakeChamp999", "Q") is None

    def test_aatrox_w_no_missile_none(self, snap: DataSnapshot) -> None:
        # Aatrox W missile_speed=None
        assert spell_travel_time(snap, "Aatrox", "W") is None


# ---------------------------------------------------------------------------
# _distance_from_geometry
# ---------------------------------------------------------------------------

class TestDistanceFromGeometry:
    def test_none_geometry_returns_none(self) -> None:
        assert _distance_from_geometry(None) is None

    def test_empty_dict_returns_none(self) -> None:
        assert _distance_from_geometry({}) is None

    def test_cone_distance_preferred(self) -> None:
        # cone_distance present and non-null -> returns it
        geo = {
            "cast_radius": 300.0,
            "cast_radius_conflated": False,
            "cone_angle": 45.0,
            "cone_distance": 800.0,
            "line_width": None,
        }
        assert _distance_from_geometry(geo) == pytest.approx(800.0)

    def test_cone_distance_beats_non_conflated_radius(self) -> None:
        # Even when cast_radius is non-conflated, cone_distance wins
        geo = {
            "cast_radius": 500.0,
            "cast_radius_conflated": False,
            "cone_angle": None,
            "cone_distance": 200.0,
            "line_width": None,
        }
        assert _distance_from_geometry(geo) == pytest.approx(200.0)

    def test_fallback_to_non_conflated_cast_radius(self) -> None:
        # cone_distance=None, cast_radius non-conflated AND >= _MIN_REAL_DISTANCE
        # (200) -> returns cast_radius.
        geo = {
            "cast_radius": 295.0,
            "cast_radius_conflated": False,
            "cone_angle": None,
            "cone_distance": None,
            "line_width": 60.0,
        }
        assert _distance_from_geometry(geo) == pytest.approx(295.0)

    def test_small_cast_radius_below_floor_rejected(self) -> None:
        # cast_radius=175 < _MIN_REAL_DISTANCE (200) -> artifact, rejected (None).
        geo = {
            "cast_radius": 175.0,
            "cast_radius_conflated": False,
            "cone_angle": None,
            "cone_distance": None,
            "line_width": 60.0,
        }
        assert _distance_from_geometry(geo) is None

    def test_cone_distance_sentinel_rejected(self) -> None:
        # cone_distance=100.0 is the CDragon placeholder sentinel -> rejected;
        # falls to the non-conflated cast_radius (300 >= floor).
        geo = {
            "cast_radius": 300.0,
            "cast_radius_conflated": False,
            "cone_angle": None,
            "cone_distance": 100.0,
            "line_width": None,
        }
        assert _distance_from_geometry(geo) == pytest.approx(300.0)

    def test_conflated_radius_not_used(self) -> None:
        # cone_distance=None, cast_radius conflated -> returns None
        geo = {
            "cast_radius": 210.0,
            "cast_radius_conflated": True,
            "cone_angle": None,
            "cone_distance": None,
            "line_width": 80.0,
        }
        assert _distance_from_geometry(geo) is None

    def test_line_width_only_returns_none(self) -> None:
        # line_width is a WIDTH not a travel length; no cone_distance, no radius
        geo = {
            "cast_radius": None,
            "cast_radius_conflated": False,
            "cone_angle": None,
            "cone_distance": None,
            "line_width": 80.0,
        }
        assert _distance_from_geometry(geo) is None

    def test_lux_q_geometry_sentinel_returns_none(self, snap: DataSnapshot) -> None:
        # Lux Q: cone_distance=100 (sentinel) + cast_radius=210 conflated ->
        # no real distance -> None (caller falls to _DEFAULT_DISTANCE).
        geo = snap.spell_geometry("Lux", "Q")
        assert _distance_from_geometry(geo) is None

    def test_lux_e_geometry_gives_real_cast_radius(
        self, snap: DataSnapshot
    ) -> None:
        # Lux E: cast_radius=295 non-conflated (>= floor) -> 295.
        geo = snap.spell_geometry("Lux", "E")
        assert _distance_from_geometry(geo) == pytest.approx(295.0)

    def test_aphelios_q_small_radius_returns_none(
        self, snap: DataSnapshot
    ) -> None:
        # Aphelios Q: cast_radius=175 < _MIN_REAL_DISTANCE (200) -> None.
        geo = snap.spell_geometry("Aphelios", "Q")
        assert _distance_from_geometry(geo) is None

    def test_aatrox_w_line_only_returns_none(
        self, snap: DataSnapshot
    ) -> None:
        # Aatrox W: cast_radius=None, cone_distance=None, line_width=80 -> None
        geo = snap.spell_geometry("Aatrox", "W")
        result = _distance_from_geometry(geo)
        assert result is None


# ---------------------------------------------------------------------------
# Default distance fallback
# ---------------------------------------------------------------------------

class TestDefaultDistanceFallback:
    def test_morgana_q_sentinel_geometry_uses_default(
        self, snap: DataSnapshot
    ) -> None:
        # Morgana Q: cone_distance=100 sentinel + cast_radius conflated ->
        # _DEFAULT_DISTANCE 1000 / 1200 = 0.8333.
        t = spell_travel_time(snap, "Morgana", "Q")
        expected = round(1000.0 / 1200.0, 4)
        assert t == pytest.approx(expected, rel=1e-4)

    def test_aphelios_q_small_radius_uses_default(
        self, snap: DataSnapshot
    ) -> None:
        # Aphelios Q: cast_radius=175 < floor -> _DEFAULT_DISTANCE 1000,
        # speed=1850 -> 1000/1850 = 0.5405.
        t = spell_travel_time(snap, "Aphelios", "Q")
        expected = round(1000.0 / 1850.0, 4)
        assert t == pytest.approx(expected, rel=1e-3)


# ---------------------------------------------------------------------------
# Fail-soft behavior
# ---------------------------------------------------------------------------

class TestFailSoft:
    def test_no_exception_on_unknown_champ(self, snap: DataSnapshot) -> None:
        # Should not raise; returns None
        result = spell_travel_time(snap, "DoesNotExist99", "Q")
        assert result is None

    def test_is_projectile_no_exception_unknown(
        self, snap: DataSnapshot
    ) -> None:
        result = is_projectile(snap, "DoesNotExist99", "Q")
        assert result is False


# ---------------------------------------------------------------------------
# ASCII hygiene
# ---------------------------------------------------------------------------

class TestAsciiHygiene:
    def test_missile_module_is_ascii(self) -> None:
        import pathlib
        src = pathlib.Path(__file__).parent.parent / "missile.py"
        content = src.read_bytes()
        assert all(b < 128 for b in content), "missile.py contains non-ASCII bytes"

    def test_this_test_file_is_ascii(self) -> None:
        import pathlib
        content = pathlib.Path(__file__).read_bytes()
        assert all(b < 128 for b in content), "test file contains non-ASCII bytes"
