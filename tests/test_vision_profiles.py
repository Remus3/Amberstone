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
        vp._last_ref_save = 0.0

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

    def test_reference_save_is_throttled(self):
        ck = "throttle_test"
        self.assertTrue(vp.save_reference_image(_img(), config_key=ck, force=True))
        # a second non-forced save within the interval is skipped
        self.assertFalse(vp.save_reference_image(_img(), config_key=ck, force=False))

    def test_non_forced_save_requires_active_game(self):
        vp._last_ref_save = 0.0
        orig = vp._game_active
        try:
            vp._game_active = lambda: False    # lobby / desktop
            self.assertFalse(vp.save_reference_image(_img(), config_key="g", force=False))
            vp._game_active = lambda: True      # game live
            self.assertTrue(vp.save_reference_image(_img(), config_key="g", force=False))
        finally:
            vp._game_active = orig

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
