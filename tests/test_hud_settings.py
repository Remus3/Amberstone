"""Parse League game.cfg for HUD/resolution settings (region hardening).

The OCR regions must be keyed by the settings that actually move the HUD -
resolution + GlobalScale + flip flags - so a config change re-selects the right
boxes instead of silently misreading. See reference_vision_ocr_capture_pipeline.
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from core import hud_settings

_SAMPLE = """\
[General]
Height=1440
Width=2560
WindowMode=1

[HUD]
GlobalScale=0.0000
FlipMiniMap=0
MinimapScale=1.2000
ShopScale=1.0000
"""


class ReadHudSettingsTests(unittest.TestCase):
    def _write(self, text):
        p = pathlib.Path(tempfile.mkdtemp()) / "game.cfg"
        p.write_text(text, encoding="utf-8")
        return p

    def test_parses_resolution_and_scale(self):
        s = hud_settings.read_hud_settings(path=self._write(_SAMPLE))
        self.assertTrue(s["ok"])
        self.assertEqual((s["width"], s["height"]), (2560, 1440))
        self.assertEqual(s["global_scale"], 0.0)
        self.assertEqual(s["flip_minimap"], 0)

    def test_config_key_is_stable_signature(self):
        s = hud_settings.read_hud_settings(path=self._write(_SAMPLE))
        self.assertEqual(s["config_key"], "2560x1440@scale0.0@flip0")
        self.assertIn("MinimapScale", s["hud"])

    def test_missing_file_is_friendly(self):
        s = hud_settings.read_hud_settings(path=pathlib.Path(tempfile.mkdtemp()) / "nope.cfg")
        self.assertFalse(s["ok"])
        self.assertEqual(s["config_key"], "unknown")

    def test_garbage_values_do_not_raise(self):
        s = hud_settings.read_hud_settings(path=self._write("[General]\nWidth=abc\nHeight=\n"))
        self.assertFalse(s["ok"])   # width unparseable -> not ok, but no crash

    def test_no_banned_codepoints(self):
        text = pathlib.Path(hud_settings.__file__).read_text(encoding="utf-8")
        banned = {0x2014: "em", 0x2013: "en", 0x2018: "lsq", 0x2019: "rsq", 0x201C: "ldq", 0x201D: "rdq"}
        hits = [n for cp, n in banned.items() if chr(cp) in text]
        self.assertFalse(hits, f"hud_settings.py banned codepoints: {hits}")


if __name__ == "__main__":
    unittest.main()
