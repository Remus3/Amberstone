"""Parse League game.cfg + PersistedSettings for OCR region + color hardening.

Regions must key off the settings that move the HUD (resolution + scale + layout
toggles like ShowTeamFramesOnLeft) AND OCR must know the color/gamma settings so
it can inverse-correct + adapt bar-color matching. See
reference_vision_ocr_capture_pipeline.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from core import hud_settings

_GAME_CFG = """\
[FloatingText]
Gold_Enabled=1

[General]
Height=1440
Width=2560
RelativeTeamColors=1

[HUD]
GlobalScale=0.0000
ShowTeamFramesOnLeft=0
MirroredScoreboard=0
FlipMiniMap=0
MinimapScale=1.6200
DrawHealthBars=1
NumericCooldownFormat=1

[Performance]
EffectsQuality=1
"""


def _persisted(gamma="0.5000", palette=0):
    return json.dumps({
        "description": "x",
        "files": [{"name": "Game.cfg", "sections": [{"name": "General", "settings": [
            {"name": "ColorBrightness", "value": "0.5000"},
            {"name": "ColorContrast", "value": "0.5000"},
            {"name": "ColorGamma", "value": gamma},
            {"name": "ColorLevel", "value": "0.5000"},
            {"name": "ColorPalette", "value": palette},
        ]}]}],
    })


class ReadHudSettingsTests(unittest.TestCase):
    def _files(self, cfg=_GAME_CFG, gamma="0.5000", palette=0):
        d = pathlib.Path(tempfile.mkdtemp())
        g = d / "game.cfg"; g.write_text(cfg, encoding="utf-8")
        p = d / "PersistedSettings.json"; p.write_text(_persisted(gamma, palette), encoding="utf-8")
        return g, p

    def test_config_key_includes_layout_toggles(self):
        g, p = self._files()
        s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
        self.assertTrue(s["ok"])
        self.assertIn("2560x1440", s["config_key"])
        self.assertIn("ShowTeamFramesOnLeft=0", s["config_key"])  # portrait side is in the key
        self.assertIn("MinimapScale=1.6200", s["config_key"])

    def test_layout_and_full_cfg_captured(self):
        g, p = self._files()
        s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
        self.assertEqual(s["layout"]["ShowTeamFramesOnLeft"], "0")
        self.assertEqual(s["layout"]["RelativeTeamColors"], "1")
        self.assertIn("Performance", s["cfg"])          # full cfg, every section
        self.assertIn("FloatingText", s["cfg"])

    def test_neutral_color_needs_no_correction(self):
        g, p = self._files(gamma="0.5000", palette=0)
        s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
        self.assertFalse(s["color_correction_needed"])
        self.assertFalse(s["colorblind"])
        self.assertEqual(s["color"]["ColorGamma"], "0.5000")

    def test_nondefault_gamma_flags_correction(self):
        g, p = self._files(gamma="0.7500")
        s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
        self.assertTrue(s["color_correction_needed"])

    def test_colorblind_palette_flags_correction(self):
        g, p = self._files(palette=1)
        s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
        self.assertTrue(s["colorblind"])
        self.assertTrue(s["color_correction_needed"])

    def test_missing_game_cfg_is_friendly(self):
        s = hud_settings.read_hud_settings(game_cfg=pathlib.Path(tempfile.mkdtemp()) / "nope.cfg")
        self.assertFalse(s["ok"])
        self.assertEqual(s["config_key"], "unknown")
        self.assertEqual(s["cfg"], {})

    def test_no_banned_codepoints(self):
        text = pathlib.Path(hud_settings.__file__).read_text(encoding="utf-8")
        banned = {0x2014: "em", 0x2013: "en", 0x2018: "lsq", 0x2019: "rsq", 0x201C: "ldq", 0x201D: "rdq"}
        hits = [n for cp, n in banned.items() if chr(cp) in text]
        self.assertFalse(hits, f"hud_settings.py banned codepoints: {hits}")


if __name__ == "__main__":
    unittest.main()
