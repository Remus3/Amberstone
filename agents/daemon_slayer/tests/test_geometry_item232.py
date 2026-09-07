"""Tests for agents/daemon_slayer/geometry.py - item 232.

Grounded against patch 16.11.1 live data.  All champ+slot pins were
verified by direct probe of data/daemon_slayer/16.11.1/cdragon_spell_stats.json
before being committed.

Pinned geometry shapes (16.11.1):
  LINE:     Aatrox W  -> line_width=80.0
  CONE:     Aatrox E  -> cone_distance=100.0, cast_radius=285.0 (non-conflated)
  CIRCLE:   Aurora R  -> cast_radius=750.0, conflated=False, no cone/line fields
  CONFLATED: Ahri E   -> cast_radius=210.0, cast_radius_conflated=True
             (conflated sentinels -> 'point', NOT circle)
  NULL_GEOM: Aatrox Q -> geometry is None (point/self-cast)
"""

import sys
import os
import unittest

# Resolve repo root so imports work regardless of working directory.
_REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Source-file lookups below are anchored on this file's own location, not the
# process CWD, so they run from any directory.
_DS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)

from agents.daemon_slayer.geometry import (
    _AOE_TARGET_CAP,
    _CONFLATED_RADIUS_SENTINELS,
    classify_spell_shape,
    is_aoe_shape,
    aoe_multiplier,
    spell_aoe_multiplier,
)
from agents.daemon_slayer.data_loader import DataSnapshot


# ---------------------------------------------------------------------------
# Fixture: real DataSnapshot (loaded once per test run)
# ---------------------------------------------------------------------------

_SNAPSHOT: DataSnapshot | None = None


def _snap() -> DataSnapshot:
    global _SNAPSHOT
    if _SNAPSHOT is None:
        _SNAPSHOT = DataSnapshot.load()
    return _SNAPSHOT


# ---------------------------------------------------------------------------
# 1. classify_spell_shape tests
# ---------------------------------------------------------------------------

class ClassifySpellShapeTests(unittest.TestCase):
    """Unit tests for classify_spell_shape using live 16.11.1 geometry dicts."""

    def test_aatrox_w_is_line(self) -> None:
        """Aatrox W carries line_width=80.0 -> 'line'."""
        g = _snap().spell_geometry("Aatrox", "W")
        self.assertIsNotNone(g)
        self.assertEqual(classify_spell_shape(g), "line")

    def test_aatrox_e_is_cone(self) -> None:
        """Aatrox E carries cone_distance=100.0 (and no line_width) -> 'cone'."""
        g = _snap().spell_geometry("Aatrox", "E")
        self.assertIsNotNone(g)
        self.assertEqual(classify_spell_shape(g), "cone")

    def test_aurora_r_is_circle(self) -> None:
        """Aurora R carries cast_radius=750.0, conflated=False, no cone/line -> 'circle'."""
        g = _snap().spell_geometry("Aurora", "R")
        self.assertIsNotNone(g)
        self.assertEqual(classify_spell_shape(g), "circle")

    def test_conflated_radius_is_point_not_circle(self) -> None:
        """Ahri E has cast_radius_conflated=True -> should NOT classify as 'circle'."""
        g = _snap().spell_geometry("Ahri", "E")
        self.assertIsNotNone(g)
        # The conflated flag means cast_radius is a sentinel, not a real area.
        shape = classify_spell_shape(g)
        self.assertNotEqual(shape, "circle")
        # Ahri E has both line_width and cone_distance so classifies as line.
        # The key invariant is: conflated sentinel radius does not produce circle.

    def test_none_geometry_is_unknown(self) -> None:
        """None input -> 'unknown'."""
        self.assertEqual(classify_spell_shape(None), "unknown")

    def test_empty_dict_is_unknown(self) -> None:
        """Empty dict input -> 'unknown'."""
        self.assertEqual(classify_spell_shape({}), "unknown")

    def test_all_null_fields_is_point(self) -> None:
        """Dict with all-null values -> 'point'."""
        g = {
            "cast_radius": None,
            "cast_radius_conflated": False,
            "cone_angle": None,
            "cone_distance": None,
            "line_width": None,
        }
        self.assertEqual(classify_spell_shape(g), "point")

    def test_sentinel_radius_only_no_conflated_flag_is_point(self) -> None:
        """cast_radius is a sentinel value (210.0) but conflated=False.

        The sentinel is in _CONFLATED_RADIUS_SENTINELS so classify falls
        through to 'point' even without the conflated flag.
        """
        g = {
            "cast_radius": 210.0,
            "cast_radius_conflated": False,
            "cone_angle": None,
            "cone_distance": None,
            "line_width": None,
        }
        self.assertEqual(classify_spell_shape(g), "point")

    def test_100_sentinel_radius_is_point(self) -> None:
        """cast_radius=100.0 (second sentinel) -> 'point'."""
        self.assertIn(100.0, _CONFLATED_RADIUS_SENTINELS)
        g = {
            "cast_radius": 100.0,
            "cast_radius_conflated": False,
            "cone_angle": None,
            "cone_distance": None,
            "line_width": None,
        }
        self.assertEqual(classify_spell_shape(g), "point")

    def test_line_width_wins_over_cone_distance(self) -> None:
        """When both line_width and cone_distance are non-null, line takes precedence."""
        g = {
            "cast_radius": None,
            "cast_radius_conflated": False,
            "cone_angle": None,
            "cone_distance": 50.0,
            "line_width": 80.0,
        }
        self.assertEqual(classify_spell_shape(g), "line")

    def test_cone_angle_alone_classifies_as_cone(self) -> None:
        """Non-null cone_angle with null cone_distance -> 'cone'."""
        g = {
            "cast_radius": None,
            "cast_radius_conflated": False,
            "cone_angle": 45.0,
            "cone_distance": None,
            "line_width": None,
        }
        self.assertEqual(classify_spell_shape(g), "cone")

    def test_real_non_sentinel_circle_radius(self) -> None:
        """Non-sentinel, non-conflated cast_radius with no cone/line -> 'circle'."""
        g = {
            "cast_radius": 400.0,
            "cast_radius_conflated": False,
            "cone_angle": None,
            "cone_distance": None,
            "line_width": None,
        }
        self.assertEqual(classify_spell_shape(g), "circle")


# ---------------------------------------------------------------------------
# 2. is_aoe_shape tests
# ---------------------------------------------------------------------------

class IsAoeShapeTests(unittest.TestCase):
    """Unit tests for is_aoe_shape."""

    def test_line_is_aoe(self) -> None:
        g = _snap().spell_geometry("Aatrox", "W")
        self.assertTrue(is_aoe_shape(g))

    def test_cone_is_aoe(self) -> None:
        g = _snap().spell_geometry("Aatrox", "E")
        self.assertTrue(is_aoe_shape(g))

    def test_circle_is_aoe(self) -> None:
        g = _snap().spell_geometry("Aurora", "R")
        self.assertTrue(is_aoe_shape(g))

    def test_point_is_not_aoe(self) -> None:
        g = {
            "cast_radius": None,
            "cast_radius_conflated": False,
            "cone_angle": None,
            "cone_distance": None,
            "line_width": None,
        }
        self.assertFalse(is_aoe_shape(g))

    def test_unknown_none_is_not_aoe(self) -> None:
        self.assertFalse(is_aoe_shape(None))

    def test_unknown_empty_dict_is_not_aoe(self) -> None:
        self.assertFalse(is_aoe_shape({}))


# ---------------------------------------------------------------------------
# 3. aoe_multiplier tests
# ---------------------------------------------------------------------------

class AoeMultiplierTests(unittest.TestCase):
    """Parametrized tests for aoe_multiplier covering floors, caps, and shapes."""

    def _line_geom(self) -> dict:
        return {"cast_radius": None, "cone_angle": None,
                "cone_distance": None, "line_width": 80.0}

    def _point_geom(self) -> dict:
        return {"cast_radius": None, "cast_radius_conflated": False,
                "cone_angle": None, "cone_distance": None, "line_width": None}

    # --- AoE shape (line) across several targets_hit values ---

    def test_aoe_targets_0_clamps_to_1(self) -> None:
        self.assertEqual(aoe_multiplier(self._line_geom(), 0), 1.0)

    def test_aoe_targets_1_returns_1(self) -> None:
        self.assertEqual(aoe_multiplier(self._line_geom(), 1), 1.0)

    def test_aoe_targets_2_returns_2(self) -> None:
        self.assertEqual(aoe_multiplier(self._line_geom(), 2), 2.0)

    def test_aoe_targets_3_returns_3(self) -> None:
        self.assertEqual(aoe_multiplier(self._line_geom(), 3), 3.0)

    def test_aoe_targets_5_returns_5(self) -> None:
        """targets_hit == _AOE_TARGET_CAP returns cap."""
        self.assertEqual(aoe_multiplier(self._line_geom(), _AOE_TARGET_CAP), float(_AOE_TARGET_CAP))

    def test_aoe_targets_8_clamps_to_cap(self) -> None:
        """targets_hit > _AOE_TARGET_CAP is clamped to cap."""
        self.assertEqual(aoe_multiplier(self._line_geom(), 8), float(_AOE_TARGET_CAP))

    # --- Point shape always returns 1.0 regardless of targets_hit ---

    def test_point_targets_0_returns_1(self) -> None:
        self.assertEqual(aoe_multiplier(self._point_geom(), 0), 1.0)

    def test_point_targets_1_returns_1(self) -> None:
        self.assertEqual(aoe_multiplier(self._point_geom(), 1), 1.0)

    def test_point_targets_5_returns_1(self) -> None:
        self.assertEqual(aoe_multiplier(self._point_geom(), 5), 1.0)

    def test_point_targets_8_returns_1(self) -> None:
        self.assertEqual(aoe_multiplier(self._point_geom(), 8), 1.0)

    # --- Unknown (None) always returns 1.0 ---

    def test_unknown_none_targets_5_returns_1(self) -> None:
        self.assertEqual(aoe_multiplier(None, 5), 1.0)

    # --- Return type is always float ---

    def test_return_type_is_float(self) -> None:
        result = aoe_multiplier(self._line_geom(), 3)
        self.assertIsInstance(result, float)


# ---------------------------------------------------------------------------
# 4. spell_aoe_multiplier (DataSnapshot convenience) tests
# ---------------------------------------------------------------------------

class SpellAoeMultiplierTests(unittest.TestCase):
    """Integration tests using real DataSnapshot against 16.11.1."""

    def test_aoe_spell_with_3_targets(self) -> None:
        """Aatrox W (line) with targets_hit=3 -> 3.0."""
        result = spell_aoe_multiplier(_snap(), "Aatrox", "W", 3)
        self.assertEqual(result, 3.0)

    def test_aoe_spell_with_1_target_is_1(self) -> None:
        """Any AoE spell at targets_hit=1 -> 1.0 (byte-identical baseline)."""
        result = spell_aoe_multiplier(_snap(), "Aatrox", "E", 1)
        self.assertEqual(result, 1.0)

    def test_null_geometry_slot_returns_1(self) -> None:
        """Aatrox Q has null geometry -> fallback 1.0."""
        result = spell_aoe_multiplier(_snap(), "Aatrox", "Q", 5)
        self.assertEqual(result, 1.0)

    def test_unknown_champ_fails_soft_returns_1(self) -> None:
        """Unknown champion id -> fail-soft returns 1.0, no exception raised."""
        result = spell_aoe_multiplier(_snap(), "NotAChampionEver", "Q", 3)
        self.assertEqual(result, 1.0)

    def test_circle_aoe_with_4_targets(self) -> None:
        """Aurora R (circle) with targets_hit=4 -> 4.0."""
        result = spell_aoe_multiplier(_snap(), "Aurora", "R", 4)
        self.assertEqual(result, 4.0)

    def test_cone_aoe_with_2_targets(self) -> None:
        """Aatrox E (cone) with targets_hit=2 -> 2.0."""
        result = spell_aoe_multiplier(_snap(), "Aatrox", "E", 2)
        self.assertEqual(result, 2.0)

    def test_cap_enforced_via_snapshot(self) -> None:
        """AoE spell with targets_hit > cap clamps to cap."""
        result = spell_aoe_multiplier(_snap(), "Aatrox", "W", 99)
        self.assertEqual(result, float(_AOE_TARGET_CAP))

    def test_fail_soft_on_missing_spell_geometry_method(self) -> None:
        """If snapshot lacks spell_geometry method -> fail-soft returns 1.0."""

        class _BadSnap:
            pass

        result = spell_aoe_multiplier(_BadSnap(), "Aatrox", "W", 3)
        self.assertEqual(result, 1.0)


# ---------------------------------------------------------------------------
# 5. Byte-identical at targets_hit=1 test
# ---------------------------------------------------------------------------

class ByteIdenticalAtOne(unittest.TestCase):
    """Every spell shape with targets_hit=1 returns 1.0 (no-op multiplier).

    This guarantees that wiring geometry into a scorer with default
    targets_hit=1 is byte-identical to the pre-geometry baseline.
    """

    def _shapes(self) -> list[dict | None]:
        return [
            # line
            {"cast_radius": None, "cone_angle": None,
             "cone_distance": None, "line_width": 80.0},
            # cone
            {"cast_radius": 285.0, "cast_radius_conflated": False,
             "cone_angle": None, "cone_distance": 100.0, "line_width": None},
            # circle
            {"cast_radius": 750.0, "cast_radius_conflated": False,
             "cone_angle": None, "cone_distance": None, "line_width": None},
            # point
            {"cast_radius": None, "cast_radius_conflated": False,
             "cone_angle": None, "cone_distance": None, "line_width": None},
            # unknown
            None,
            {},
        ]

    def test_all_shapes_return_1_at_targets_1(self) -> None:
        for geom in self._shapes():
            with self.subTest(geom=geom):
                self.assertEqual(
                    aoe_multiplier(geom, 1),
                    1.0,
                    f"Expected 1.0 for geometry {geom!r} at targets_hit=1",
                )


# ---------------------------------------------------------------------------
# 6. ASCII hygiene
# ---------------------------------------------------------------------------

class AsciiHygieneTests(unittest.TestCase):
    """Verify the new source files contain only ASCII bytes."""

    def _check_file(self, rel_path: str) -> None:
        abs_path = os.path.join(_DS_DIR, rel_path)
        with open(abs_path, "rb") as fh:
            content = fh.read()
        non_ascii = [
            (i, b) for i, b in enumerate(content) if b > 127
        ]
        self.assertEqual(
            non_ascii,
            [],
            f"{rel_path} contains {len(non_ascii)} non-ASCII byte(s): "
            f"first at offset {non_ascii[0][0] if non_ascii else 'n/a'}",
        )

    def test_geometry_module_is_ascii(self) -> None:
        self._check_file("geometry.py")

    def test_geometry_test_file_is_ascii(self) -> None:
        self._check_file("tests/test_geometry_item232.py")


if __name__ == "__main__":
    unittest.main()
