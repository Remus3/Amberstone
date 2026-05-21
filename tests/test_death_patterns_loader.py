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

from core.death_patterns_loader import (  # noqa: E402
    personal_context_block,
    role_grades_summary,
    top_patterns,
)


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


class RoleGradesSummaryTests(unittest.TestCase):
    """role_grades_summary returns the role_grades envelope from the
    postmortem JSON; fail-soft when the section is absent (schema v1) or
    the file is missing/malformed."""

    def test_missing_file_returns_empty(self):
        self.assertEqual(role_grades_summary(pathlib.Path("nonexistent.json")), {})

    def test_malformed_json_returns_empty(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="dpl_rg_"))
        try:
            p = tmp / "bad.json"
            p.write_text("not json {", encoding="utf-8")
            self.assertEqual(role_grades_summary(p), {})
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_schema_v1_without_role_grades_returns_empty(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="dpl_rg_"))
        try:
            p = _write(tmp, {"schema_version": 1, "top3": [], "patterns": {}})
            self.assertEqual(role_grades_summary(p), {})
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_populated_returns_envelope(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="dpl_rg_"))
        try:
            payload = {
                "schema_version": 2,
                "top3": [],
                "patterns": {},
                "role_grades": {
                    "total_matches_scored": 7,
                    "overall": {
                        "count": 7,
                        "median_score": 42,
                        "tier_distribution": {"S+": 0, "S": 1, "A": 1, "B": 2, "C": 1, "D": 2},
                    },
                    "by_role": {
                        "ADC": {"count": 3, "median_score": 60, "tier_distribution": {"S+": 0, "S": 0, "A": 1, "B": 2, "C": 0, "D": 0}},
                        "SUP": {"count": 0, "median_score": 0, "tier_distribution": {"S+": 0, "S": 0, "A": 0, "B": 0, "C": 0, "D": 0}},
                        "JG": {"count": 0, "median_score": 0, "tier_distribution": {"S+": 0, "S": 0, "A": 0, "B": 0, "C": 0, "D": 0}},
                        "MID": {"count": 4, "median_score": 30, "tier_distribution": {"S+": 0, "S": 1, "A": 0, "B": 0, "C": 1, "D": 2}},
                        "TOP": {"count": 0, "median_score": 0, "tier_distribution": {"S+": 0, "S": 0, "A": 0, "B": 0, "C": 0, "D": 0}},
                    },
                },
            }
            p = _write(tmp, payload)
            rg = role_grades_summary(p)
            self.assertEqual(rg["total_matches_scored"], 7)
            self.assertEqual(rg["overall"]["median_score"], 42)
            self.assertEqual(rg["by_role"]["ADC"]["count"], 3)
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_role_grades_not_dict_returns_empty(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="dpl_rg_"))
        try:
            p = _write(tmp, {"schema_version": 2, "role_grades": "broken"})
            self.assertEqual(role_grades_summary(p), {})
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_no_isolation_from_top_patterns(self):
        """role_grades_summary + top_patterns read the SAME file without
        either helper holding any state - calling order is irrelevant."""
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="dpl_rg_"))
        try:
            p = _write(tmp, {
                "schema_version": 2,
                "top3": ["solo_pickoff"],
                "patterns": {"solo_pickoff": {"label": "Solo pickoffs", "description": "x", "count": 5}},
                "role_grades": {"total_matches_scored": 2, "overall": {"count": 2, "median_score": 50, "tier_distribution": {}}, "by_role": {}},
            })
            # call in both orders to confirm no shared mutable state
            self.assertEqual(len(top_patterns(p)), 1)
            self.assertEqual(role_grades_summary(p)["total_matches_scored"], 2)
            self.assertEqual(role_grades_summary(p)["total_matches_scored"], 2)
            self.assertEqual(len(top_patterns(p)), 1)
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
