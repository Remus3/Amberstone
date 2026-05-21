"""tests/test_death_patterns_loader.py - loader fail-soft + format contract."""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.death_patterns_loader import personal_context_block, top_patterns  # noqa: E402


def _write(tmp: pathlib.Path, data: dict) -> pathlib.Path:
    p = tmp / "death_patterns.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


class FailSoftTests(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(top_patterns(pathlib.Path("nonexistent.json")), [])
        self.assertEqual(personal_context_block(pathlib.Path("nonexistent.json")), "")

    def test_malformed_json_returns_empty(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="dpl_"))
        try:
            p = tmp / "bad.json"
            p.write_text("not json {", encoding="utf-8")
            self.assertEqual(top_patterns(p), [])
            self.assertEqual(personal_context_block(p), "")
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_empty_top3_returns_empty(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="dpl_"))
        try:
            p = _write(tmp, {"schema_version": 1, "top3": [], "patterns": {}})
            self.assertEqual(top_patterns(p), [])
            self.assertEqual(personal_context_block(p), "")
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_top3_with_missing_pattern_meta_skipped(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="dpl_"))
        try:
            p = _write(tmp, {
                "schema_version": 1,
                "top3": ["solo_pickoff", "ghost_pattern_not_in_meta"],
                "patterns": {"solo_pickoff": {"label": "Solo pickoffs", "description": "x", "count": 5}},
            })
            patterns = top_patterns(p)
            self.assertEqual(len(patterns), 1)
            self.assertEqual(patterns[0]["key"], "solo_pickoff")
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)


class FormatTests(unittest.TestCase):
    def test_personal_context_block_contains_header_and_top3(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="dpl_"))
        try:
            p = _write(tmp, {
                "schema_version": 1,
                "top3": ["solo_pickoff", "caught_4plus", "rapid_repeat"],
                "patterns": {
                    "solo_pickoff": {"label": "Solo pickoffs", "description": "ward + rotate", "count": 100},
                    "caught_4plus": {"label": "Caught by 4+", "description": "minimap", "count": 80},
                    "rapid_repeat": {"label": "Rapid repeats", "description": "tilt reset", "count": 40},
                },
            })
            block = personal_context_block(p)
            self.assertIn("PERSONAL CONTEXT", block)
            self.assertIn("Solo pickoffs", block)
            self.assertIn("(100x)", block)
            self.assertIn("ward + rotate", block)
            self.assertIn("Caught by 4+", block)
            self.assertIn("Rapid repeats", block)
            self.assertTrue(block.startswith("\n"))
            self.assertTrue(block.endswith("when applicable."))
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_block_starts_with_newline_for_safe_append(self):
        """The block is appended to existing prompts; the leading newline
        keeps the existing trailing content separated. Cache-preservation
        requires the prefix above to stay byte-identical - never inserted
        mid-block."""
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="dpl_"))
        try:
            p = _write(tmp, {
                "schema_version": 1,
                "top3": ["solo_pickoff"],
                "patterns": {"solo_pickoff": {"label": "Solo pickoffs", "description": "x", "count": 1}},
            })
            self.assertTrue(personal_context_block(p).startswith("\n"))
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
