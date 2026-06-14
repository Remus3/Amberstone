"""FU01 - minimap bbox resolver tests.

Covers `agents._minimap_bbox.resolve()` across:
  * persisted file missing -> hardcoded fallback
  * persisted file present + malformed shape -> hardcoded fallback
  * persisted file present + valid entry -> persisted wins
  * persisted file present + degenerate bbox (r<=l, b<=t) -> fallback
  * unsupported mode (arena) -> None
  * tracked support set matches the existing modes (sr / aram / brawl)
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from agents import _minimap_bbox as mb  # noqa: E402


class _RegionsFileSwap:
    """Context manager that patches mb._REGIONS_FILE for the test duration."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._orig: Path | None = None

    def __enter__(self) -> "_RegionsFileSwap":
        self._orig = mb._REGIONS_FILE
        mb._REGIONS_FILE = self._path
        return self

    def __exit__(self, *args: object) -> None:
        mb._REGIONS_FILE = self._orig  # type: ignore[assignment]


class MinimapBboxResolveTests(unittest.TestCase):
    def setUp(self) -> None:
        # All file-system interactions live under a temp path to avoid
        # touching the real data/vision_regions.json during tests.
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self._regions = Path(self._tmpdir.name) / "vision_regions.json"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    # -- supported_modes ---------------------------------------------------

    def test_supported_modes_known_set(self) -> None:
        self.assertEqual(set(mb.supported_modes()), {"sr", "aram", "brawl"})

    # -- resolve: unsupported mode -----------------------------------------

    def test_resolve_arena_returns_none(self) -> None:
        with _RegionsFileSwap(self._regions):
            self.assertIsNone(mb.resolve("arena"))

    def test_resolve_unknown_mode_returns_none(self) -> None:
        with _RegionsFileSwap(self._regions):
            self.assertIsNone(mb.resolve("tft"))

    def test_resolve_empty_mode_returns_none(self) -> None:
        with _RegionsFileSwap(self._regions):
            self.assertIsNone(mb.resolve(""))

    def test_resolve_none_mode_returns_none(self) -> None:
        with _RegionsFileSwap(self._regions):
            # `None` is coerced via `mode or ""` - should not raise.
            self.assertIsNone(mb.resolve(None))  # type: ignore[arg-type]

    # -- resolve: persisted file missing -> hardcoded -----------------------

    def test_resolve_no_file_uses_fallback(self) -> None:
        # Point to a path that does not exist.
        missing = Path(self._tmpdir.name) / "nope.json"
        with _RegionsFileSwap(missing):
            self.assertEqual(mb.resolve("sr"), (1565, 735, 1905, 1075))
            self.assertEqual(mb.resolve("aram"), (1565, 735, 1905, 1075))
            self.assertEqual(mb.resolve("brawl"), (1565, 735, 1905, 1075))

    # -- resolve: persisted entries win ------------------------------------

    def test_resolve_persisted_overrides_fallback(self) -> None:
        self._regions.write_text(
            json.dumps({
                "_minimap_sr":    [10, 20, 30, 40],
                "_minimap_aram":  [50, 60, 70, 80],
                "_minimap_brawl": [90, 100, 110, 120],
                "timer":          [1857, 4, 1903, 26],  # unrelated OCR region
            }),
            encoding="utf-8",
        )
        with _RegionsFileSwap(self._regions):
            self.assertEqual(mb.resolve("sr"),    (10, 20, 30, 40))
            self.assertEqual(mb.resolve("aram"),  (50, 60, 70, 80))
            self.assertEqual(mb.resolve("brawl"), (90, 100, 110, 120))

    def test_resolve_partial_persisted_falls_through_per_mode(self) -> None:
        # Only sr is persisted; aram + brawl should fall back.
        self._regions.write_text(
            json.dumps({"_minimap_sr": [11, 22, 33, 44]}),
            encoding="utf-8",
        )
        with _RegionsFileSwap(self._regions):
            self.assertEqual(mb.resolve("sr"),    (11, 22, 33, 44))
            self.assertEqual(mb.resolve("aram"),  (1565, 735, 1905, 1075))
            self.assertEqual(mb.resolve("brawl"), (1565, 735, 1905, 1075))

    # -- resolve: malformed persisted entries -> fallback -------------------

    def test_resolve_persisted_wrong_arity_falls_back(self) -> None:
        self._regions.write_text(
            json.dumps({"_minimap_sr": [10, 20, 30]}),  # 3-tuple
            encoding="utf-8",
        )
        with _RegionsFileSwap(self._regions):
            self.assertEqual(mb.resolve("sr"), (1565, 735, 1905, 1075))

    def test_resolve_persisted_wrong_type_falls_back(self) -> None:
        self._regions.write_text(
            json.dumps({"_minimap_sr": "1565,735,1905,1075"}),  # string
            encoding="utf-8",
        )
        with _RegionsFileSwap(self._regions):
            self.assertEqual(mb.resolve("sr"), (1565, 735, 1905, 1075))

    def test_resolve_persisted_non_numeric_entry_falls_back(self) -> None:
        self._regions.write_text(
            json.dumps({"_minimap_sr": [10, "twenty", 30, 40]}),
            encoding="utf-8",
        )
        with _RegionsFileSwap(self._regions):
            self.assertEqual(mb.resolve("sr"), (1565, 735, 1905, 1075))

    def test_resolve_persisted_degenerate_l_ge_r_falls_back(self) -> None:
        self._regions.write_text(
            json.dumps({"_minimap_sr": [100, 20, 100, 40]}),
            encoding="utf-8",
        )
        with _RegionsFileSwap(self._regions):
            self.assertEqual(mb.resolve("sr"), (1565, 735, 1905, 1075))

    def test_resolve_persisted_degenerate_t_ge_b_falls_back(self) -> None:
        self._regions.write_text(
            json.dumps({"_minimap_sr": [10, 40, 30, 40]}),
            encoding="utf-8",
        )
        with _RegionsFileSwap(self._regions):
            self.assertEqual(mb.resolve("sr"), (1565, 735, 1905, 1075))

    def test_resolve_corrupted_json_falls_back(self) -> None:
        self._regions.write_text("{ not valid json", encoding="utf-8")
        with _RegionsFileSwap(self._regions):
            self.assertEqual(mb.resolve("sr"), (1565, 735, 1905, 1075))

    def test_resolve_top_level_not_object_falls_back(self) -> None:
        self._regions.write_text("[1, 2, 3]", encoding="utf-8")
        with _RegionsFileSwap(self._regions):
            self.assertEqual(mb.resolve("sr"), (1565, 735, 1905, 1075))

    # -- load_persisted: direct API ----------------------------------------

    def test_load_persisted_returns_none_for_unset_mode(self) -> None:
        self._regions.write_text(
            json.dumps({"_minimap_sr": [10, 20, 30, 40]}),
            encoding="utf-8",
        )
        with _RegionsFileSwap(self._regions):
            self.assertIsNone(mb.load_persisted("aram"))
            self.assertEqual(mb.load_persisted("sr"), (10, 20, 30, 40))

    def test_load_persisted_coerces_numeric_strings_to_ints(self) -> None:
        # int("123") works; the resolver normalizes the tuple to ints.
        self._regions.write_text(
            json.dumps({"_minimap_sr": ["10", "20", "30", "40"]}),
            encoding="utf-8",
        )
        with _RegionsFileSwap(self._regions):
            result = mb.load_persisted("sr")
            self.assertEqual(result, (10, 20, 30, 40))
            self.assertTrue(all(isinstance(v, int) for v in result))

    # -- resolve: case insensitivity ---------------------------------------

    def test_resolve_mode_is_lowercased(self) -> None:
        with _RegionsFileSwap(self._regions):
            self.assertEqual(mb.resolve("SR"), (1565, 735, 1905, 1075))
            self.assertEqual(mb.resolve("Aram"), (1565, 735, 1905, 1075))

    # -- load_persisted: file-read exceptions are swallowed ----------------

    def test_load_persisted_read_error_returns_none(self) -> None:
        # File exists per the path check but read_text raises.
        # We patch the Path.read_text method on the swapped instance.
        self._regions.write_text("{}", encoding="utf-8")
        with _RegionsFileSwap(self._regions):
            with mock.patch.object(
                Path, "read_text", side_effect=OSError("boom"),
            ):
                self.assertIsNone(mb.load_persisted("sr"))


if __name__ == "__main__":
    unittest.main()
