"""
tests/phase2_smoke/test_disabled_placeholders.py
Smoke tests for disabled-policy placeholder/output semantics.

All placeholder writes go into a temp directory via the artifact_root seam.
The live project artifact paths (coaching_data.json, data/*) are never touched.
No live API, no Tk required.
"""
import json
import sys
import unittest
import tempfile
from pathlib import Path

# Project root resolved relative to this file — no hardcoded absolute paths.
_PROJECT_ROOT = Path(__file__).parent.parent.parent

sys.path.insert(0, str(_PROJECT_ROOT))
import core.feature_policy as fp
from core.feature_policy import (
    write_disabled_placeholder,
    _PROJECT_DIR, _SR_ARTIFACT, _DATA_DIR,
)


class TestDisabledPlaceholders(unittest.TestCase):

    def setUp(self):
        self._td_obj = tempfile.TemporaryDirectory()
        self._td = Path(self._td_obj.name)
        fp._reload()

    def tearDown(self):
        fp._reload()
        self._td_obj.cleanup()

    def _read(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    # ── SR ─────────────────────────────────────────────────────────────────

    def test_sr_placeholder_production_path_contract(self):
        """SR production artifact path must equal project_root/coaching_data.json."""
        # This is an import/path contract check only — no file is written.
        expected = _PROJECT_DIR / "coaching_data.json"
        self.assertEqual(_SR_ARTIFACT, expected)

    def test_sr_placeholder_action_field(self):
        """SR placeholder writes action=COACHING DISABLED to temp root."""
        write_disabled_placeholder("sr", artifact_root=self._td)
        content = self._read(self._td / "coaching_data.json")
        self.assertEqual(content.get("action"), "COACHING DISABLED")

    # ── ARAM ───────────────────────────────────────────────────────────────

    def test_aram_placeholder_action_field(self):
        write_disabled_placeholder("aram", artifact_root=self._td)
        p = self._td / "data" / "aram_coaching_data.json"
        self.assertTrue(p.exists())
        self.assertEqual(self._read(p).get("action"), "COACHING DISABLED")

    # ── Arena / Brawl ──────────────────────────────────────────────────────

    def test_arena_placeholder_without_client(self):
        """Placeholder written into temp root regardless of _client state."""
        write_disabled_placeholder("arena", artifact_root=self._td)
        p = self._td / "data" / "arena_coaching_data.json"
        self.assertTrue(p.exists())
        self.assertEqual(self._read(p).get("action"), "COACHING DISABLED")

    def test_brawl_placeholder_without_client(self):
        write_disabled_placeholder("brawl", artifact_root=self._td)
        p = self._td / "data" / "brawl_coaching_data.json"
        self.assertTrue(p.exists())
        self.assertEqual(self._read(p).get("action"), "COACHING DISABLED")

    # ── TFT independence ───────────────────────────────────────────────────

    def test_tft_live_coaching_writes_only_coaching_artifact(self):
        write_disabled_placeholder("tft", "live_coaching",
                                   artifact_root=self._td)
        coaching_path = self._td / "data" / "tft_coaching_data.json"
        live_path     = self._td / "data" / "tft_live_data.json"
        self.assertTrue(coaching_path.exists())
        self.assertFalse(live_path.exists())

    def test_tft_vision_writes_only_live_artifact(self):
        write_disabled_placeholder("tft", "tft_vision_analysis",
                                   artifact_root=self._td)
        coaching_path = self._td / "data" / "tft_coaching_data.json"
        live_path     = self._td / "data" / "tft_live_data.json"
        self.assertFalse(coaching_path.exists())
        self.assertTrue(live_path.exists())

    def test_tft_both_disabled_writes_both(self):
        write_disabled_placeholder("tft", None, artifact_root=self._td)
        coaching_path = self._td / "data" / "tft_coaching_data.json"
        live_path     = self._td / "data" / "tft_live_data.json"
        self.assertTrue(coaching_path.exists())
        self.assertTrue(live_path.exists())

    def test_tft_coaching_disabled_does_not_suppress_live(self):
        """Disabling live_coaching must not write tft_live_data.json."""
        write_disabled_placeholder("tft", "live_coaching",
                                   artifact_root=self._td)
        live_path = self._td / "data" / "tft_live_data.json"
        self.assertFalse(live_path.exists())

    def test_tft_vision_disabled_does_not_suppress_coaching(self):
        """Disabling tft_vision_analysis must not write tft_coaching_data.json."""
        write_disabled_placeholder("tft", "tft_vision_analysis",
                                   artifact_root=self._td)
        coaching_path = self._td / "data" / "tft_coaching_data.json"
        self.assertFalse(coaching_path.exists())

    # ── Live artifacts NOT mutated ─────────────────────────────────────────

    def test_live_sr_artifact_not_mutated(self):
        """write_disabled_placeholder with artifact_root must not touch live paths."""
        live_sr = _PROJECT_ROOT / "coaching_data.json"
        # Record pre-test mtime if file exists; it must not change.
        pre_mtime = live_sr.stat().st_mtime if live_sr.exists() else None
        write_disabled_placeholder("sr", artifact_root=self._td)
        post_mtime = live_sr.stat().st_mtime if live_sr.exists() else None
        self.assertEqual(pre_mtime, post_mtime,
                         "Live coaching_data.json must not be modified by test")

    def test_live_data_dir_not_mutated(self):
        """data/ artifacts must not be touched when artifact_root is used."""
        live_arena = _PROJECT_ROOT / "data" / "arena_coaching_data.json"
        pre_mtime = live_arena.stat().st_mtime if live_arena.exists() else None
        write_disabled_placeholder("arena", artifact_root=self._td)
        post_mtime = live_arena.stat().st_mtime if live_arena.exists() else None
        self.assertEqual(pre_mtime, post_mtime,
                         "Live arena_coaching_data.json must not be modified by test")

    # ── Arena/Brawl coach gate ordering (structural) ────────────────────────

    def test_arena_gate_before_client_check(self):
        """Policy gate in arena_coach._run_coach() precedes _client check."""
        arena_path = _PROJECT_ROOT / "coaches" / "arena_coach.py"
        src = arena_path.read_text(encoding="utf-8")
        run_body  = src.split("def _run_coach")[1]
        gate_pos  = run_body.find("Phase 2 Step 1 / 1.1")
        client_pos = run_body.find("if not self._client:")
        self.assertGreater(client_pos, gate_pos,
                           "Policy gate must appear before _client check")

    def test_brawl_gate_before_client_check(self):
        brawl_path = _PROJECT_ROOT / "coaches" / "brawl_coach.py"
        src = brawl_path.read_text(encoding="utf-8")
        run_body   = src.split("def _run_coach")[1]
        gate_pos   = run_body.find("Phase 2 Step 1 / 1.1")
        client_pos = run_body.find("if not self._client:")
        self.assertGreater(client_pos, gate_pos,
                           "Policy gate must appear before _client check")


if __name__ == "__main__":
    unittest.main()
