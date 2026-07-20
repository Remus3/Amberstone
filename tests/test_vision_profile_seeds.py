# arch: tests for ultrawide / 1440p OCR-region seed generation | section=vision-tests | frozen=no
"""Tests for the RM-26 seed generator in core.vision_profiles.

A SEED is an untuned, proportionally-scaled profile derived from the operator's
hand-calibrated 1920x1080 baseline (data/vision_regions.json) and persisted at a
non-1080p base so a first run on a 1440p / ultrawide display has plausible boxes
instead of unscaled 1080p ones. Seeds are a STARTING POINT, not a calibration:
League's HUD does not stretch uniformly on ultrawide, so the boxes still need a
live tuning pass (out of scope here, live-gated).

These lock the two properties that make a seed safe to ship:
  * ADDITIVE - it never overwrites an existing profile and never touches the
    tracked 1920x1080 baseline file.
  * IN-BOUNDS - every derived box stays inside the destination base and keeps
    the baseline's proportional placement.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from core import vision_profiles as vp

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BASELINE_FILE = os.path.join(_ROOT, "data", "vision_regions.json")


def _baseline() -> dict:
    with open(_BASELINE_FILE, encoding="utf-8") as fh:
        return json.load(fh)


class SeedBasesTests(unittest.TestCase):
    def test_seed_bases_cover_1440p_and_ultrawide(self):
        bases = [list(b) for b in vp.SEED_BASES]
        self.assertIn([2560, 1440], bases, "16:9 1440p seed missing")
        self.assertIn([3440, 1440], bases, "21:9 ultrawide 1440p seed missing")
        self.assertIn([2560, 1080], bases, "21:9 ultrawide 1080p seed missing")

    def test_authoring_base_is_not_a_seed(self):
        # The hand-calibrated 1920x1080 baseline is the SOURCE, never a seed
        # target - seeding it would be a no-op that risks clobbering it.
        self.assertNotIn([1920, 1080], [list(b) for b in vp.SEED_BASES])

    def test_every_seed_base_validates(self):
        for base in vp.SEED_BASES:
            ok, err, _clean = vp.validate_base(list(base))
            self.assertTrue(ok, f"{base} rejected by validate_base: {err}")


class SeedProfilesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="rc_seed_")
        self._orig_dir = vp.PROFILES_DIR
        vp.PROFILES_DIR = Path(self._tmp)

    def tearDown(self):
        vp.PROFILES_DIR = self._orig_dir
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_seeds_are_written_for_every_base(self):
        res = vp.seed_profiles()
        self.assertTrue(res["ok"])
        self.assertEqual(res["written"], len(vp.SEED_BASES))
        self.assertEqual(res["skipped"], 0)
        for base in vp.SEED_BASES:
            ck = f"{base[0]}x{base[1]}"
            self.assertTrue(vp.profile_path(ck).exists(), f"no seed file for {ck}")

    def test_ultrawide_seed_is_scaled_and_in_bounds(self):
        vp.seed_profiles(bases=[[3440, 1440]])
        d = json.loads(vp.profile_path("3440x1440").read_text(encoding="utf-8"))
        self.assertEqual(d["base"], [3440, 1440])
        baseline = _baseline()
        self.assertEqual(sorted(d["regions"]), sorted(baseline))
        sx, sy = 3440 / 1920, 1440 / 1080
        for name, box in d["regions"].items():
            l, t, r, b = box
            self.assertTrue(0 <= l < r <= 3440, f"{name} x out of bounds: {box}")
            self.assertTrue(0 <= t < b <= 1440, f"{name} y out of bounds: {box}")
            src = baseline[name]
            self.assertEqual(box, [int(src[0] * sx), int(src[1] * sy),
                                   int(src[2] * sx), int(src[3] * sy)])

    def test_seeding_is_additive_and_never_overwrites(self):
        ck = "2560x1440"
        vp.save_profile(ck, {"timer": [1, 2, 3, 4]}, [2560, 1440])
        before = vp.profile_path(ck).read_text(encoding="utf-8")
        res = vp.seed_profiles()
        self.assertEqual(vp.profile_path(ck).read_text(encoding="utf-8"), before)
        self.assertIn(ck, res["skipped_keys"])
        self.assertEqual(res["skipped"], 1)

    def test_force_rewrites_an_existing_seed(self):
        ck = "2560x1440"
        vp.save_profile(ck, {"timer": [1, 2, 3, 4]}, [2560, 1440])
        vp.seed_profiles(bases=[[2560, 1440]], force=True)
        d = json.loads(vp.profile_path(ck).read_text(encoding="utf-8"))
        self.assertGreater(len(d["regions"]), 1)

    def test_legacy_1080p_baseline_is_untouched(self):
        before = Path(_BASELINE_FILE).read_bytes()
        vp.seed_profiles()
        self.assertEqual(Path(_BASELINE_FILE).read_bytes(), before)
        self.assertFalse((Path(self._tmp) / "1920x1080.json").exists())


if __name__ == "__main__":
    unittest.main()
