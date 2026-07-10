# arch: native-2560-profile vs 1280-halved-frame crop-mapping regression guard | section=vision-tests | frozen=no
"""R98 regression guard: a native 2560x1440 profile crops correctly onto the
1280-halved OCR frame that vision_server actually serves.

Context (verify-before-declare, R98). The R98 directive re-issued the R94-refuted
premise "recalibrate the 23 boxes at 2560x1440 + wire native OCR crops": both are
already shipped -

  * SLICE 1 - data/vision_profiles/2560x1440_*.json is a real native custom-HUD
    calibration (ally panels on the RIGHT, ShowTeamFramesOnLeft=0), scalar OCR
    boxes backfilled (test_vision_profile_2560_ocr_boxes.py).
  * SLICE 2 - core.vision_tesseract._regions() prefers the active profile + its
    native base (test_vision_tesseract_profile_wiring.py), and _color_correct /
    _preprocess / _apply_color_correction (R95) are wired
    (test_vision_tesseract_native_crop_r94.py, _hud_color_r95.py).

The ONE uncovered production seam: the live OCR read path (core.vision_routing ->
read_fast_fields) consumes /latest-frame, which vision_server/_frame.py downscales
to _SELF_GRAB_MAX_WIDTH = 1280. So with a native 2560 profile active, _scale_bbox
maps native boxes DOWN 0.5x onto a 1280x720 frame at crop time. The existing
wiring tests only cover 2560-base-vs-2560-frame (a no-op scale) or the 1920
fallback - NOTHING drives the real production condition (native 2560 base, 1280
halved frame). This locks that mapping so a profile-base regression (silently
reverting to the 1920 base) or a downscale-width drift is caught.

CI-safe: PIL only, no Tesseract (region-resolution + crop geometry seams only).
"""
from __future__ import annotations

import pytest

from core import vision_tesseract as vt

# A representative slice of the real shipped native profile (native base 2560x1440,
# custom HUD - ally panels on the RIGHT). Values copied from
# data/vision_profiles/2560x1440_...MinimapScale_1.6200.json.
_NATIVE_PROFILE = {
    "config_key": "2560x1440|ShowTeamFramesOnLeft=0",
    "base": [2560, 1440],
    "regions": {
        "gold": [1463, 1407, 1549, 1433],
        "level": [977, 1404, 999, 1424],
        "hp": [1153, 1392, 1287, 1412],
        "mana": [1147, 1409, 1280, 1429],
        "timer": [2476, 5, 2537, 35],
        "ally_1_hp": [2173, 972, 2248, 987],   # RIGHT side (custom HUD)
        "ally_4_mana": [2473, 987, 2546, 998],  # far-RIGHT edge
    },
    "source": "profile",
}

# The frame vision_server/_frame.py actually serves to OCR (2560 grab halved).
_HALVED_W, _HALVED_H = 1280, 720


@pytest.fixture(autouse=True)
def _reset_region_cache():
    """Clear the region cache after each test so this module never leaks its
    fake native profile into sibling vision tests (the live Legion machine has a
    real 2560 profile on disk, so we cannot assert a fixed post-teardown base -
    just guarantee a fresh re-resolve)."""
    yield
    vt.reload_regions()


def _load_native(monkeypatch):
    import core.vision_profiles as vp
    monkeypatch.setattr(vp, "load_profile", lambda config_key=None: _NATIVE_PROFILE)
    vt.reload_regions()


def test_active_native_profile_installs_native_base(monkeypatch):
    _load_native(monkeypatch)
    vt._regions()
    # the native profile base MUST drive _scale_bbox; a regression to the 1920
    # legacy base would silently mis-scale every crop on the halved frame.
    assert vt._BASE_CACHE == (2560, 1440)


def test_native_box_maps_to_halved_frame_at_half_scale(monkeypatch):
    _load_native(monkeypatch)
    vt._regions()
    # 1280/2560 == 720/1440 == 0.5, with _scale_bbox's int() truncation.
    assert vt._scale_bbox([1463, 1407, 1549, 1433], _HALVED_W, _HALVED_H) == (731, 703, 774, 716)


def test_halved_frame_mapping_is_not_the_1920_drift(monkeypatch):
    """Anti-drift sentinel (mirrors the R94 legacy-downscale assertion): the
    correct native-base 0.5x maps gold's left edge to 731; a stale 1920 base
    would scale by 1280/1920 == 0.667 and land it at ~975. Guard the gap."""
    _load_native(monkeypatch)
    vt._regions()
    left = vt._scale_bbox([1463, 1407, 1549, 1433], _HALVED_W, _HALVED_H)[0]
    assert left == 731
    assert left < 900  # a 1920-base drift would put it at ~975


def test_every_native_box_stays_inside_halved_frame(monkeypatch):
    _load_native(monkeypatch)
    regions = vt._regions()
    for name, box in regions.items():
        l, t, r, b = vt._scale_bbox(box, _HALVED_W, _HALVED_H)
        assert 0 <= l < r <= _HALVED_W, f"{name} x out of halved frame: {(l, t, r, b)}"
        assert 0 <= t < b <= _HALVED_H, f"{name} y out of halved frame: {(l, t, r, b)}"


def test_crop_from_halved_frame_is_nonempty(monkeypatch):
    """The whole crop path on a real 1280x720 frame yields a non-degenerate crop
    for every native box (no empty/zero-area crop that would starve OCR)."""
    from PIL import Image

    _load_native(monkeypatch)
    regions = vt._regions()
    frame = Image.new("RGB", (_HALVED_W, _HALVED_H), (0, 0, 0))
    for name, box in regions.items():
        crop = vt._crop(frame, vt._scale_bbox(box, _HALVED_W, _HALVED_H))
        assert crop.width > 0 and crop.height > 0, f"{name} degenerate crop"
