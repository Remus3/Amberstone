"""Native full-resolution screen grab for the OCR + calibration paths.

grab_native must NOT downscale (unlike the vision self-grab, which halves to
1280 wide), must return a valid JPEG, and must degrade to a friendly no-op
without raising when PIL is absent or the grab fails (headless / locked session).
See memory reference_vision_ocr_capture_pipeline.
"""
from __future__ import annotations

import base64
import pathlib
import unittest

from core import screen_grab


def _fake_grab(w=2560, h=1440):
    from PIL import Image
    return lambda: Image.new("RGB", (w, h), (30, 40, 50))


class GrabNativeTests(unittest.TestCase):
    def test_returns_native_resolution_no_downscale(self):
        out = screen_grab.grab_native(_grabber=_fake_grab(2560, 1440))
        self.assertTrue(out["ok"])
        self.assertEqual(out["width"], 2560)   # NOT downscaled to 1280
        self.assertEqual(out["height"], 1440)
        self.assertEqual(out["format"], "jpeg")

    def test_b64_is_a_valid_jpeg(self):
        out = screen_grab.grab_native(_grabber=_fake_grab(320, 200))
        raw = base64.b64decode(out["b64"], validate=True)
        self.assertEqual(raw[:3], b"\xff\xd8\xff")  # JPEG magic bytes

    def test_grab_failure_is_friendly(self):
        def boom():
            raise OSError("headless session 0x5")
        out = screen_grab.grab_native(_grabber=boom)
        self.assertFalse(out["ok"])
        self.assertNotIn("0x5", str(out))  # raw error never surfaced

    def test_none_image_is_friendly(self):
        out = screen_grab.grab_native(_grabber=lambda: None)
        self.assertFalse(out["ok"])

    def test_no_banned_codepoints(self):
        text = pathlib.Path(screen_grab.__file__).read_text(encoding="utf-8")
        banned = {
            0x2014: "em-dash", 0x2013: "en-dash",
            0x2018: "lsquo", 0x2019: "rsquo",
            0x201C: "ldquo", 0x201D: "rdquo",
        }
        hits = [name for cp, name in banned.items() if chr(cp) in text]
        self.assertFalse(hits, f"screen_grab.py has banned codepoints: {hits}")


if __name__ == "__main__":
    unittest.main()
