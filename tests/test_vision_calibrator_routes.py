"""Vision-region calibrator backend: load / validate / atomic-save regions
+ the :8889 frame proxy.

Feature (2026-07-05): an adjustable companion tool to debug + recalibrate the
OCR regions in data/vision_regions.json (a dict of field -> [x1,y1,x2,y2] pixel
boxes on the :8889 frame). The static tools/calibrate_vision.py only draws the
current boxes onto a JPG; this adds a draggable web surface backed by these
routes so a region can be dragged/resized over the live frame and saved back.

Contract:
  - validate_regions accepts a dict of name -> [x1,y1,x2,y2] (4 ints, x1<x2,
    y1<y2, non-negative, sanely bounded) and rejects every malformed shape.
  - save_regions atomic-writes only VALID payloads; an invalid payload never
    touches the file on disk.
  - load_regions round-trips what save_regions wrote; a missing file -> {}.
  - fetch_frame returns {"ok": True, ...} on a good relay read and a friendly
    {"ok": False, ...} when the relay is down (never raises, never leaks the
    raw error string - CLAUDE.md error rule).
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from dashboard import routes_vision_calibrator as vc


class ValidateRegionsTests(unittest.TestCase):
    def test_valid_payload_passes(self):
        ok, err, clean = vc.validate_regions(
            {"hp": [865, 1044, 965, 1059], "timer": [1857, 4, 1903, 26]}
        )
        self.assertTrue(ok, err)
        self.assertIsNone(err)
        self.assertEqual(clean["hp"], [865, 1044, 965, 1059])

    def test_rejects_non_dict(self):
        ok, err, _ = vc.validate_regions([1, 2, 3, 4])
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_rejects_wrong_arity(self):
        ok, err, _ = vc.validate_regions({"hp": [1, 2, 3]})
        self.assertFalse(ok)

    def test_rejects_non_int(self):
        ok, err, _ = vc.validate_regions({"hp": [1, 2, 3, "x"]})
        self.assertFalse(ok)

    def test_rejects_inverted_box(self):
        # x2 <= x1 (or y2 <= y1) is a zero/negative-area crop - reject.
        ok, err, _ = vc.validate_regions({"hp": [900, 10, 800, 40]})
        self.assertFalse(ok)

    def test_rejects_negative(self):
        ok, err, _ = vc.validate_regions({"hp": [-5, 10, 40, 40]})
        self.assertFalse(ok)

    def test_rejects_empty(self):
        ok, err, _ = vc.validate_regions({})
        self.assertFalse(ok)


class SaveLoadRegionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()) / "vision_regions.json"

    def test_save_then_load_roundtrips(self):
        payload = {"hp": [865, 1044, 965, 1059], "cs": [1, 2, 3, 4]}
        ok, err, count = vc.save_regions(payload, path=self.tmp)
        self.assertTrue(ok, err)
        self.assertEqual(count, 2)
        self.assertEqual(vc.load_regions(path=self.tmp), payload)

    def test_invalid_payload_never_writes(self):
        good = {"hp": [1, 2, 3, 4]}
        vc.save_regions(good, path=self.tmp)
        before = self.tmp.read_text(encoding="utf-8")
        ok, err, _ = vc.save_regions({"hp": [9, 9, 1, 1]}, path=self.tmp)  # inverted
        self.assertFalse(ok)
        self.assertEqual(self.tmp.read_text(encoding="utf-8"), before)  # untouched

    def test_load_missing_file_returns_empty(self):
        missing = pathlib.Path(tempfile.mkdtemp()) / "nope.json"
        self.assertEqual(vc.load_regions(path=missing), {})


class FetchFrameTests(unittest.TestCase):
    def test_good_relay_read(self):
        body = json.dumps(
            {"b64": "AAAA", "width": 1920, "height": 1080, "ts": 1.0}
        ).encode()
        out = vc.fetch_frame(_fetch=lambda: body, _now=lambda: 4.0)
        self.assertTrue(out["ok"])
        self.assertEqual(out["width"], 1920)
        self.assertEqual(out["b64"], "AAAA")
        self.assertAlmostEqual(out["age_s"], 3.0, places=3)

    def test_relay_down_is_friendly(self):
        def boom():
            raise OSError("connection refused 10061")

        out = vc.fetch_frame(_fetch=boom)
        self.assertFalse(out["ok"])
        self.assertNotIn("10061", json.dumps(out))  # raw error never surfaced


class NoBannedCodepointsTests(unittest.TestCase):
    def test_no_banned_codepoints(self):
        text = pathlib.Path(vc.__file__).read_text(encoding="utf-8")
        banned = {
            0x2014: "em-dash", 0x2013: "en-dash",
            0x2018: "lsquo", 0x2019: "rsquo",
            0x201C: "ldquo", 0x201D: "rdquo",
        }
        hits = [name for cp, name in banned.items() if chr(cp) in text]
        self.assertFalse(hits, f"routes_vision_calibrator.py banned codepoints: {hits}")


if __name__ == "__main__":
    unittest.main()
