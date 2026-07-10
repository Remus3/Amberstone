# arch: characterization tests for OCR-region resolution-scaling primitive | section=vision-tests | frozen=no
"""Characterization tests for the pure resolution-scaling primitive in
core.vision_profiles (derive_scaled_regions / derive_profile).

These lock the derived boxes byte-for-byte to the LIVE crop-time scaler
core.vision_tesseract._scale_bbox, so a native-base profile derived offline
crops the identical rectangle the runtime scaler produces for a native frame -
no downscale drift. CI-runnable: the 1920x1080 baseline is read from the tracked
data/vision_regions.json (there is no gitignored per-machine profile dependency).
"""
from __future__ import annotations

import json
import os
import unittest

from core import vision_profiles as vp
from core import vision_tesseract

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BASELINE_FILE = os.path.join(_ROOT, "data", "vision_regions.json")


def _baseline() -> dict:
    with open(_BASELINE_FILE, encoding="utf-8") as fh:
        return json.load(fh)


class DeriveScaledRegionsTests(unittest.TestCase):
    def test_byte_exact_vs_live_scaler(self):
        # Every field must equal core.vision_tesseract._scale_bbox to the byte,
        # with _BASE_CACHE pinned to the 1920x1080 authoring base.
        baseline = _baseline()
        orig = vision_tesseract._BASE_CACHE
        vision_tesseract._BASE_CACHE = (1920, 1080)
        try:
            derived = vp.derive_scaled_regions(baseline, [1920, 1080], [2560, 1440])
            for field, box in baseline.items():
                expected = list(vision_tesseract._scale_bbox(box, 2560, 1440))
                self.assertEqual(derived[field], expected,
                                 f"{field} diverged from live _scale_bbox")
        finally:
            vision_tesseract._BASE_CACHE = orig

    def test_idempotent_at_same_base(self):
        # Scaling to the source base is a no-op (int(v * 1.0) == v for int v).
        baseline = _baseline()
        derived = vp.derive_scaled_regions(baseline, [1920, 1080], [1920, 1080])
        for field, box in baseline.items():
            self.assertEqual(derived[field], list(box))

    def test_derived_boxes_inside_2560x1440_frame(self):
        # Well-formed: every derived box sits inside the frame, left<right, top<bottom.
        baseline = _baseline()
        derived = vp.derive_scaled_regions(baseline, [1920, 1080], [2560, 1440])
        self.assertTrue(derived)
        for name, box in derived.items():
            l, t, r, b = box
            self.assertTrue(0 <= l < r <= 2560, f"{name} x out of frame: {box}")
            self.assertTrue(0 <= t < b <= 1440, f"{name} y out of frame: {box}")

    def test_per_axis_independence_non_16_9(self):
        # 3440x1440 (21:9): sx != sy. timer = [1857, 4, 1903, 26].
        baseline = _baseline()
        derived = vp.derive_scaled_regions(baseline, [1920, 1080], [3440, 1440])
        sx = 3440 / 1920
        sy = 1440 / 1080
        timer = baseline["timer"]
        self.assertEqual(
            derived["timer"],
            [int(timer[0] * sx), int(timer[1] * sy),
             int(timer[2] * sx), int(timer[3] * sy)])
        # Concretely prove x used the x-scale, not the y-scale (per-axis math).
        self.assertEqual(derived["timer"][0], int(1857 * (3440 / 1920)))
        self.assertNotEqual(derived["timer"][0], int(1857 * (1440 / 1080)))

    def test_malformed_entries_skipped(self):
        out = vp.derive_scaled_regions(
            {"good": [1, 2, 3, 4], "bad3": [1, 2, 3], "bad_str": "x"},
            [1920, 1080], [2560, 1440])
        self.assertEqual(set(out), {"good"})

    def test_input_regions_not_mutated(self):
        # derive_scaled_regions returns a NEW dict and never mutates the input.
        src = {"timer": [1, 2, 3, 4]}
        vp.derive_scaled_regions(src, [1920, 1080], [2560, 1440])
        self.assertEqual(src, {"timer": [1, 2, 3, 4]})


class DeriveProfileTests(unittest.TestCase):
    def test_derive_profile_shape(self):
        prof = vp.derive_profile([2560, 1440])
        self.assertEqual(prof["source"], "derived")
        self.assertEqual(prof["base"], [2560, 1440])
        self.assertEqual(prof["config_key"], "2560x1440")
        self.assertTrue(prof["regions"])
        self.assertIn("timer", prof["regions"])
        self.assertIn("ally_levels", prof["regions"])

    def test_derive_profile_invalid_base_raises(self):
        with self.assertRaises(ValueError):
            vp.derive_profile([0, 0])
        with self.assertRaises(ValueError):
            vp.derive_profile([1920])


if __name__ == "__main__":
    unittest.main()
