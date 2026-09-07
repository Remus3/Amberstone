"""Item 241 A1 (repo-structure guard): the embedded engine __init__.py changelog
is relocated to agents/daemon_slayer/CHANGELOG.md.

What this pins now:
  - __init__.py stays lean (the changelog does not creep back into it),
  - ENGINE_VERSION stays importable and stays a line-start assignment, which is
    what the version-bump tooling greps for,
  - __init__.py still points a reader at CHANGELOG.md,
  - CHANGELOG.md exists and preserves the relocated engine history verbatim.

Lives in the repo (RC) suite, not the DS engine suite: it asserts repo-internal
file structure rather than engine behaviour.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import agents.daemon_slayer as ds

_ENG = Path(ds.__file__).resolve().parent
_INIT = _ENG / "__init__.py"
_CHANGELOG = _ENG / "CHANGELOG.md"


class InitLeanTests(unittest.TestCase):
    def test_init_is_lean(self):
        n = _INIT.read_text(encoding="utf-8").count("\n") + 1
        self.assertLess(n, 60, f"__init__.py is {n} lines; changelog should be relocated")

    def test_engine_version_still_importable(self):
        self.assertRegex(ds.ENGINE_VERSION, r"^\d+\.\d+\.\d+$")

    def test_engine_version_is_line_start(self):
        text = _INIT.read_text(encoding="utf-8")
        self.assertIsNotNone(re.search(r'^ENGINE_VERSION\s*=\s*"[^"]+"', text, re.MULTILINE))

    def test_init_points_at_changelog(self):
        self.assertIn("CHANGELOG.md", _INIT.read_text(encoding="utf-8"))


class ChangelogFileTests(unittest.TestCase):
    def test_changelog_exists(self):
        self.assertTrue(_CHANGELOG.is_file())

    def test_changelog_carries_relocated_sections(self):
        body = _CHANGELOG.read_text(encoding="utf-8")
        self.assertIn("ENGINE version changelog", body)
        self.assertIn("Module overview", body)

    def test_changelog_preserves_engine_history(self):
        body = _CHANGELOG.read_text(encoding="utf-8")
        self.assertIn("1.75.0", body)
        self.assertIn("Phase 4 batch", body)


if __name__ == "__main__":
    unittest.main()
