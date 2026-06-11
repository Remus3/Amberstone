"""Guard: the DS Share package's authored handoff docs keep their MECHANICAL
version/patch anchors in lock-step with the live engine.

``tools/ds_share_sync.py`` mirrors ``Share/src`` deterministically and ALSO
rewrites + verifies the ``ENGINE_VERSION = "X"`` literal and the explicit
``data patch `X` `` / ``"patch": "X"`` anchor phrases in ``Share/README.md`` +
``Share/docs/*.md``. CI runs ``ds_share_sync.py --check`` so an engine bump that
forgets the authored docs fails the build (the same hard gate as the src mirror).

This test pins the invariant from the repo (RC) suite: it asserts the live docs
are fresh, that the changelog history is correctly EXCLUDED (it legitimately
carries old versions), and that the rewrite/check machinery detects + repairs a
planted drift.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import agents.daemon_slayer as ds
from tools import ds_share_sync as sync

_VERSION_LITERAL = re.compile(r'ENGINE_VERSION = "(\d+\.\d+\.\d+)"')


class LiveDocsFreshTests(unittest.TestCase):
    def test_check_doc_anchors_reports_zero_drift(self):
        """The committed authored docs are in sync with the live engine."""
        self.assertEqual(
            sync._check_doc_anchors(), 0,
            "authored-doc version/patch anchors drifted - run "
            "`C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/ds_share_sync.py` and commit Share/",
        )

    def test_every_version_literal_equals_live(self):
        """Independent re-derivation (not via the tool's own regex): every
        `ENGINE_VERSION = "X"` literal in the numbered docs + README == live."""
        live = ds.ENGINE_VERSION
        for rel in sync._DOC_FILES:
            p = sync._SHARE / rel
            if not p.exists():
                continue
            for m in _VERSION_LITERAL.finditer(p.read_text(encoding="utf-8")):
                self.assertEqual(
                    m.group(1), live,
                    f"{rel} pins ENGINE_VERSION {m.group(1)!r}, live is {live!r}",
                )

    def test_doc_files_excludes_changelog_and_manifest(self):
        """The changelog (release history) + machine-generated manifest are NOT
        auto-maintained; they legitimately carry old versions."""
        self.assertNotIn("CHANGELOG.md", sync._DOC_FILES)
        self.assertNotIn("MANIFEST.md", sync._DOC_FILES)

    def test_changelog_history_form_is_not_matched_by_version_rule(self):
        """The changelog uses `## ENGINE_VERSION A -> B`, a different form from the
        auto-maintained `ENGINE_VERSION = "X"` literal, so its history is safe."""
        version_rule = next(r for r in sync._doc_anchor_rules() if r[0] == "engine version")
        _label, pat, _live = version_rule
        sample = "## ENGINE_VERSION 1.77.0 -> 1.86.0 - 2026-06-01"
        self.assertEqual(list(pat.finditer(sample)), [])


class RewriteAndCheckMechanismTests(unittest.TestCase):
    def setUp(self):
        self.live = ds.ENGINE_VERSION

    def _plant(self, tmp: Path, stale_version: str) -> Path:
        doc = tmp / "docs" / "01_OVERVIEW.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(
            f'Live anchors: `ENGINE_VERSION = "{stale_version}"`, data patch `0.0.0`.\n',
            encoding="utf-8",
        )
        return doc

    def test_check_detects_planted_drift(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._plant(tmp, "0.0.0")
            orig = sync._SHARE
            try:
                sync._SHARE = tmp
                self.assertGreater(
                    sync._check_doc_anchors(), 0,
                    "a planted stale version anchor must be reported as drift",
                )
            finally:
                sync._SHARE = orig

    def test_rewrite_repairs_planted_drift(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            doc = self._plant(tmp, "0.0.0")
            orig = sync._SHARE
            try:
                sync._SHARE = tmp
                changed = sync._rewrite_doc_anchors()
                self.assertIn("docs/01_OVERVIEW.md", changed)
                self.assertEqual(sync._check_doc_anchors(), 0)
            finally:
                sync._SHARE = orig
            text = doc.read_text(encoding="utf-8")
            self.assertIn(f'ENGINE_VERSION = "{self.live}"', text)
            self.assertIn(f"data patch `{sync._PATCH}`", text)

    def test_rewrite_is_a_noop_when_already_fresh(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._plant(tmp, self.live)  # already-live version, stale patch
            orig = sync._SHARE
            try:
                sync._SHARE = tmp
                sync._rewrite_doc_anchors()  # fixes the patch token
                self.assertEqual(sync._rewrite_doc_anchors(), [],
                                 "a second rewrite over fresh docs must change nothing")
            finally:
                sync._SHARE = orig


class AsciiHygieneTests(unittest.TestCase):
    def test_new_tool_region_and_test_are_ascii(self):
        for p in (Path(sync.__file__), Path(__file__)):
            raw = p.read_bytes()
            self.assertTrue(
                all(b < 128 for b in raw),
                f"{p.name} carries a non-ASCII byte",
            )


if __name__ == "__main__":
    unittest.main()
