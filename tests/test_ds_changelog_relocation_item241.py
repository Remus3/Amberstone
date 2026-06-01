"""Item 241 A1 (repo-structure guard): the embedded engine __init__.py changelog
is relocated to agents/daemon_slayer/CHANGELOG.md; __init__.py stays lean and the
engine CHANGELOG.md is excluded from the Share/src deterministic mirror (the Share
package carries its own authored Share/CHANGELOG.md, and its __init__ is stubbed).

Lives in the repo (RC) suite, not the DS engine suite: it asserts repo-internal
structure + the ds_share_sync mirror policy, neither of which ships in Share/src.
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


class ShareMirrorExclusionTests(unittest.TestCase):
    def test_engine_changelog_not_in_share_mirror(self):
        from tools import ds_share_sync

        expected = ds_share_sync._build_expected()
        self.assertNotIn("agents/daemon_slayer/CHANGELOG.md", expected)
        self.assertIn("agents/daemon_slayer/__init__.py", expected)


if __name__ == "__main__":
    unittest.main()
