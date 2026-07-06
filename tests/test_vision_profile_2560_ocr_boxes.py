# arch: 2560x1440 profile numeric-OCR-box completeness guard | section=vision-tests | frozen=no
"""Guard that the shipped 2560x1440 HUD profiles carry every numeric OCR field
core.vision_tesseract._parse_field can read.

The auto/calibrator-built 2560 profiles held 25 scene-panel regions but were
MISSING the core scalar OCR boxes (timer/level/hp/mana/gold/ping/fps/ally_levels),
so once vision_tesseract prefers the active profile those fields would silently
drop. This backfills + locks them at native base [2560, 1440], scaled 1.3333x
(= 2560/1920, identical vertical since both are 16:9) from the operator's real
1920x1080 calibration in data/vision_regions.json - byte-for-byte what
_scale_bbox already produced for a native frame, now persisted so no downscale
drift. Every box must sit inside the 2560x1440 frame with left<right, top<bottom.
"""
from __future__ import annotations

import glob
import json
import os

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROFILES = os.path.join(_ROOT, "data", "vision_profiles")

# scalar OCR fields that were previously absent from the 2560 profiles
_REQUIRED_OCR = {
    "timer", "level", "hp", "mana", "gold", "ping", "fps",
    "cs", "kda", "score_blue", "score_red", "ally_levels",
}


def _profiles_2560():
    return sorted(glob.glob(os.path.join(_PROFILES, "2560x1440_*.json")))


def _require_local_profiles():
    """data/vision_profiles/ is gitignored per-machine calibration state (like
    vision_calib_reference/), so a fresh CI checkout has none. This guard makes
    the backfill-completeness checks a LOCAL (Legion) guard that skips cleanly on
    CI instead of failing on an inherently absent artifact."""
    profs = _profiles_2560()
    if not profs:
        pytest.skip("no local 2560x1440 HUD profiles (gitignored machine state)")
    return profs


def test_2560_profiles_carry_all_numeric_ocr_boxes():
    for path in _require_local_profiles():
        d = json.loads(open(path, encoding="utf-8").read())
        assert d.get("base") == [2560, 1440], f"{os.path.basename(path)} wrong base"
        regions = d.get("regions", {})
        missing = sorted(_REQUIRED_OCR - set(regions))
        assert not missing, f"{os.path.basename(path)} missing OCR boxes: {missing}"


def test_2560_ocr_boxes_are_inside_frame_and_well_formed():
    for path in _require_local_profiles():
        d = json.loads(open(path, encoding="utf-8").read())
        for name, box in d.get("regions", {}).items():
            assert isinstance(box, list) and len(box) == 4, f"{name} not a 4-tuple"
            l, t, r, b = box
            assert 0 <= l < r <= 2560, f"{path}:{name} x out of frame: {box}"
            assert 0 <= t < b <= 1440, f"{path}:{name} y out of frame: {box}"
