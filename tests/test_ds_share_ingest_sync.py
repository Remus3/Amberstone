"""Guard: the Share/lolmath_ingest calculator-ingest slice tracks the live
engine version + data patch, and the one-shot dist bundle is rebuilt in
lock-step with the Share/src data snapshot.

Item-378 sidequest finding: Share core was fully in sync (1.120.0/16.12.1) but
lolmath_ingest pinned 1.108.0/16.11.1 because ``ds_share_sync.py --check`` did
not cover that subdir. These tests pin the extension: ingest anchors + the
dist bundle are now part of both write mode and the --check drift gate.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import agents.daemon_slayer as ds
from tools import ds_share_sync as sync


class LiveIngestFreshTests(unittest.TestCase):
    def test_check_ingest_anchors_reports_zero_drift(self):
        """The committed lolmath_ingest authored files pin the live values."""
        self.assertEqual(
            sync._check_ingest_anchors(), 0,
            "lolmath_ingest version/patch anchors drifted - run "
            "`C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/ds_share_sync.py` and commit Share/",
        )

    def test_live_bundle_matches_expected(self):
        """The on-disk dist bundle (gitignored build artifact; absent on a
        clean checkout) is byte-identical to a rebuild from the live Share/src
        snapshot when present."""
        self.assertEqual(
            sync._check_ingest_bundle(), 0,
            "dist/daemon_slayer_bundle.json drifted - run "
            "`C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/ds_share_sync.py`",
        )

    def test_live_bundle_envelope_pins_live_values(self):
        """Independent re-derivation: the on-disk bundle envelope carries the
        live engine version + patch. Skipped on a clean checkout (the bundle
        is gitignored - see feedback_clean_checkout_probe)."""
        p = sync._INGEST / "dist" / "daemon_slayer_bundle.json"
        if not p.exists():
            self.skipTest("dist bundle absent (clean checkout)")
        with p.open(encoding="utf-8") as fh:
            bundle = json.load(fh)
        self.assertEqual(bundle["engine_version"], ds.ENGINE_VERSION)
        self.assertEqual(bundle["patch"], sync._PATCH)
        self.assertTrue(bundle["sources"], "bundle sources empty")

    def test_build_bundle_script_pins_live_engine(self):
        """build_bundle.py's own ENGINE_VERSION literal == live engine."""
        text = (sync._INGEST / "build_bundle.py").read_text(encoding="utf-8")
        self.assertIn(f'ENGINE_VERSION = "{ds.ENGINE_VERSION}"', text)


class IngestRuleShapeTests(unittest.TestCase):
    def test_engine_rule_does_not_match_patch_token(self):
        rule = next(r for r in sync._ingest_anchor_rules()
                    if r[0] == "ingest engine version")
        self.assertEqual([m.group(0) for m in rule[1].finditer("16.11.1")], [])
        self.assertEqual(
            [m.group(0) for m in rule[1].finditer("engine 1.108.0 ok")],
            ["1.108.0"],
        )

    def test_patch_rule_does_not_match_engine_token(self):
        rule = next(r for r in sync._ingest_anchor_rules()
                    if r[0] == "ingest data patch")
        self.assertEqual([m.group(0) for m in rule[1].finditer("1.108.0")], [])
        self.assertEqual(
            [m.group(0) for m in rule[1].finditer("patch 16.11.1 ok")],
            ["16.11.1"],
        )


class RewriteAndCheckMechanismTests(unittest.TestCase):
    """Planted-drift round-trip on a temp Share tree (anchors + bundle)."""

    def _plant(self, tmp: Path, engine: str, patch: str) -> None:
        ing = tmp / "lolmath_ingest"
        (ing / "dist").mkdir(parents=True, exist_ok=True)
        (ing / "README.md").write_text(
            f"Engine `{engine}` - patch `{patch}`.\n", encoding="utf-8")
        (ing / "INGEST_SPEC.md").write_text(
            f'const EXPECT_ENGINE = "{engine}";\n'
            f'const EXPECT_PATCH = "{patch}";\n', encoding="utf-8")
        (ing / "daemon_slayer_bundle.d.ts").write_text(
            f"/* Engine {engine} - patch {patch}. */\n", encoding="utf-8")
        (ing / "build_bundle.py").write_text(
            f'ENGINE_VERSION = "{engine}"\n', encoding="utf-8")
        # Minimal Share/src snapshot for the bundle rebuild.
        snap = tmp / "src" / "data" / "daemon_slayer" / sync._PATCH
        snap.mkdir(parents=True, exist_ok=True)
        (snap / "champions.json").write_text(
            '{"data": {"Ahri": {}}}', encoding="utf-8")
        (ing / "dist" / "daemon_slayer_bundle.json").write_text(
            json.dumps({"engine_version": engine, "patch": patch,
                        "generated_note": "static one-shot export",
                        "sources": {}}), encoding="utf-8")

    def test_check_detects_planted_drift_and_rewrite_repairs(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._plant(tmp, "0.0.0", "0.0.0")
            orig_share, orig_src = sync._SHARE, sync._SRC
            orig_ingest = sync._INGEST
            try:
                sync._SHARE = tmp
                sync._SRC = tmp / "src"
                sync._INGEST = tmp / "lolmath_ingest"
                self.assertGreater(sync._check_ingest_anchors(), 0)
                self.assertGreater(sync._check_ingest_bundle(), 0)
                changed = sync._rewrite_ingest_anchors()
                self.assertTrue(changed)
                sync._rebuild_ingest_bundle()
                self.assertEqual(sync._check_ingest_anchors(), 0)
                self.assertEqual(sync._check_ingest_bundle(), 0)
                live = sync._engine_version()
                text = (tmp / "lolmath_ingest" / "build_bundle.py").read_text(
                    encoding="utf-8")
                self.assertIn(f'ENGINE_VERSION = "{live}"', text)
                bundle = json.loads(
                    (tmp / "lolmath_ingest" / "dist" /
                     "daemon_slayer_bundle.json").read_text(encoding="utf-8"))
                self.assertEqual(bundle["engine_version"], live)
                self.assertEqual(bundle["patch"], sync._PATCH)
                self.assertIn("champions", bundle["sources"])
            finally:
                sync._SHARE, sync._SRC = orig_share, orig_src
                sync._INGEST = orig_ingest

    def test_missing_bundle_is_skipped_not_drift(self):
        """The bundle is gitignored - a clean checkout (CI --check) has no
        file; that must NOT count as drift."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._plant(tmp, "0.0.0", "0.0.0")
            (tmp / "lolmath_ingest" / "dist" /
             "daemon_slayer_bundle.json").unlink()
            orig_share, orig_src = sync._SHARE, sync._SRC
            orig_ingest = sync._INGEST
            try:
                sync._SHARE = tmp
                sync._SRC = tmp / "src"
                sync._INGEST = tmp / "lolmath_ingest"
                self.assertEqual(sync._check_ingest_bundle(), 0)
            finally:
                sync._SHARE, sync._SRC = orig_share, orig_src
                sync._INGEST = orig_ingest


class AsciiHygieneTests(unittest.TestCase):
    def test_test_file_is_ascii(self):
        raw = Path(__file__).read_bytes()
        self.assertTrue(all(b < 128 for b in raw))


if __name__ == "__main__":
    unittest.main()
