"""Profile-based, hot-reloadable OCR region + native-reference store.

Regions are keyed by the live HUD config_key (profile), the active profile is
resolved live (on-the-fly config switching), a save just rewrites the file, and
a native reference frame is captured per profile during a game so a single-screen
operator can recalibrate against it later. See reference_vision_ocr_capture_pipeline.
"""
from __future__ import annotations

import base64
import pathlib
import tempfile
import unittest

from core import vision_profiles as vp


def _img(w=2560, h=1440):
    from PIL import Image
    return Image.new("RGB", (w, h), (20, 30, 40))


class VisionProfilesTests(unittest.TestCase):
    def setUp(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self._pd, self._rd = vp.PROFILES_DIR, vp.REFERENCE_DIR
        vp.PROFILES_DIR = d / "profiles"
        vp.REFERENCE_DIR = d / "reference"

    def tearDown(self):
        vp.PROFILES_DIR, vp.REFERENCE_DIR = self._pd, self._rd

    def test_config_key_is_filesystem_safe(self):
        # config_key has | @ = which cannot be a filename
        p = vp.profile_path("2560x1440|GlobalScale=0.0000|ShowTeamFramesOnLeft=0")
        self.assertNotIn("|", p.name)
        self.assertTrue(p.name.endswith(".json"))

    def test_save_then_load_profile_roundtrips(self):
        ck = "2560x1440|ShowTeamFramesOnLeft=0"
        out = vp.save_profile(ck, {"hp": [1, 2, 3, 4]}, [2560, 1440])
        self.assertTrue(out["ok"])
        self.assertEqual(out["count"], 1)
        prof = vp.load_profile(ck)
        self.assertEqual(prof["source"], "profile")
        self.assertEqual(prof["base"], [2560, 1440])
        self.assertEqual(prof["regions"]["hp"], [1, 2, 3, 4])

    def test_missing_profile_seeds_from_legacy(self):
        prof = vp.load_profile("never_calibrated_config")
        self.assertEqual(prof["source"], "legacy_seed")
        self.assertEqual(prof["base"], [1920, 1080])   # legacy base

    def test_reference_capture_and_load_roundtrip(self):
        ck = "2560x1440@test"
        out = vp.capture_reference(config_key=ck, _grabber=_img)
        self.assertTrue(out["ok"])
        self.assertEqual(out["width"], 2560)
        ref = vp.load_reference(config_key=ck)
        self.assertTrue(ref["ok"])
        self.assertEqual(ref["width"], 2560)
        raw = base64.b64decode(ref["b64"], validate=True)
        self.assertEqual(raw[:3], b"\xff\xd8\xff")   # JPEG magic

    def test_forced_save_overwrites_existing_ref(self):
        # force=True is the manual-refresh path: it saves regardless of
        # foreground / an already-present reference (item: base-grab clobber fix).
        ck = "force_overwrite"
        self.assertTrue(vp.save_reference_image(_img(), config_key=ck, force=True))
        # a second FORCED save still overwrites (no once-per-config gate on force)
        self.assertTrue(vp.save_reference_image(_img(), config_key=ck, force=True))

    def test_auto_save_when_game_and_league_foreground_and_no_ref(self):
        # AUTO (force=False) base grab: has_game + League foreground + no ref -> SAVES.
        orig_ga, orig_fg = vp._game_active, vp._league_is_foreground
        try:
            vp._game_active = lambda: True
            vp._league_is_foreground = lambda: True
            self.assertTrue(
                vp.save_reference_image(_img(), config_key="auto_ok", force=False))
        finally:
            vp._game_active, vp._league_is_foreground = orig_ga, orig_fg

    def test_auto_save_skipped_when_league_not_foreground(self):
        # The clobber regression: game running (has_game) but the operator
        # alt-tabbed out (desktop is foreground). Must NOT save (would overwrite
        # the calibrated base with a desktop frame).
        orig_ga, orig_fg = vp._game_active, vp._league_is_foreground
        try:
            vp._game_active = lambda: True
            vp._league_is_foreground = lambda: False   # alt-tabbed / desktop
            self.assertFalse(
                vp.save_reference_image(_img(), config_key="alt_tab", force=False))
        finally:
            vp._game_active, vp._league_is_foreground = orig_ga, orig_fg

    def test_auto_save_skipped_when_ref_already_exists(self):
        # Once-per-config: a reference already exists for this config -> no re-grab
        # (retires the 60s cadence; a settings change makes a NEW config_key).
        ck = "already_has_ref"
        orig_ga, orig_fg = vp._game_active, vp._league_is_foreground
        try:
            vp._game_active = lambda: True
            vp._league_is_foreground = lambda: True
            # seed the reference via the manual (force) path
            self.assertTrue(vp.save_reference_image(_img(), config_key=ck, force=True))
            self.assertTrue(vp.reference_path(ck).exists())
            # now the AUTO path must be a no-op (ref exists)
            self.assertFalse(
                vp.save_reference_image(_img(), config_key=ck, force=False))
        finally:
            vp._game_active, vp._league_is_foreground = orig_ga, orig_fg

    def test_auto_save_skipped_when_no_game(self):
        # has_game False (lobby / desktop) -> never save, even if League foreground.
        orig_ga, orig_fg = vp._game_active, vp._league_is_foreground
        try:
            vp._game_active = lambda: False
            vp._league_is_foreground = lambda: True
            self.assertFalse(
                vp.save_reference_image(_img(), config_key="no_game", force=False))
        finally:
            vp._game_active, vp._league_is_foreground = orig_ga, orig_fg

    def test_load_reference_missing_is_friendly(self):
        ref = vp.load_reference(config_key="nothing_here")
        self.assertFalse(ref["ok"])

    def test_no_banned_codepoints(self):
        text = pathlib.Path(vp.__file__).read_text(encoding="utf-8")
        banned = {0x2014: "em", 0x2013: "en", 0x2018: "lsq", 0x2019: "rsq", 0x201C: "ldq", 0x201D: "rdq"}
        hits = [n for cp, n in banned.items() if chr(cp) in text]
        self.assertFalse(hits, f"vision_profiles.py banned codepoints: {hits}")


if __name__ == "__main__":
    unittest.main()
