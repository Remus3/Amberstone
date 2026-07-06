# arch: profile-aware OCR region loading + native-res color-correction wiring | section=vision-tests | frozen=no
"""RED-first guard for wiring core.vision_profiles into the OCR hot path.

Before this change core/vision_tesseract._regions() read ONLY the legacy
data/vision_regions.json (base 1920x1080) and never consulted the per-HUD
profile store (core/vision_profiles), so a native 2560x1440 calibration profile
was ignored and every crop was scaled from 1920 boxes (drift + the halved-frame
tiny-text problem, memory reference_vision_ocr_capture_pipeline). These tests
assert:
  1. _regions() prefers the active profile's regions + base when one exists.
  2. It falls back to the legacy 1920 base when no profile / an empty profile.
  3. A native-res color-correction step (_color_correct via autocontrast) exists
     and lifts a dim glyph above the binarize threshold without inverting it.

pytesseract is NOT installed in CI, but none of these tests invoke Tesseract -
they exercise the region-resolution + preprocessing seams only. PIL is available
in the RC test env (the sibling test_vision_profiles uses it).
"""
from __future__ import annotations

import importlib

import pytest

from core import vision_tesseract as vt


def _reset(monkeypatch, prof):
    """Point vision_tesseract's profile lookup at a fake load_profile and clear
    the region cache so the next _regions() call re-resolves."""
    import core.vision_profiles as vp
    monkeypatch.setattr(vp, "load_profile", lambda config_key=None: prof)
    vt.reload_regions()


def test_regions_prefers_active_profile(monkeypatch):
    prof = {
        "config_key": "2560x1440|X",
        "base": [2560, 1440],
        "regions": {"gold": [1463, 1407, 1549, 1433], "level": [977, 1404, 999, 1424]},
        "source": "profile",
    }
    _reset(monkeypatch, prof)
    regions = vt._regions()
    assert regions.get("gold") == [1463, 1407, 1549, 1433]
    assert regions.get("level") == [977, 1404, 999, 1424]
    # the native profile base must drive _scale_bbox (no 1920 scaling drift)
    assert vt._BASE_CACHE == (2560, 1440)


def test_native_profile_base_makes_scale_a_noop(monkeypatch):
    prof = {
        "config_key": "2560x1440|X",
        "base": [2560, 1440],
        "regions": {"gold": [1463, 1407, 1549, 1433]},
        "source": "profile",
    }
    _reset(monkeypatch, prof)
    vt._regions()
    # a 2560x1440 frame against a 2560x1440-base profile: bbox unchanged
    assert vt._scale_bbox([1463, 1407, 1549, 1433], 2560, 1440) == (1463, 1407, 1549, 1433)


def test_regions_falls_back_to_legacy_on_empty_profile(monkeypatch):
    prof = {"config_key": "unknown", "base": [1920, 1080], "regions": {}, "source": "legacy_seed"}
    _reset(monkeypatch, prof)
    regions = vt._regions()
    # legacy path: base stays 1920x1080 and the default/legacy fields are present
    assert vt._BASE_CACHE == (1920, 1080)
    assert "timer" in regions


def test_regions_fail_soft_when_profile_import_raises(monkeypatch):
    import core.vision_profiles as vp

    def _boom(config_key=None):
        raise RuntimeError("profile store unavailable")

    monkeypatch.setattr(vp, "load_profile", _boom)
    vt.reload_regions()
    # must not raise; degrades to legacy regions
    regions = vt._regions()
    assert isinstance(regions, dict) and "timer" in regions
    assert vt._BASE_CACHE == (1920, 1080)


def test_color_correct_lifts_dim_glyph_above_threshold():
    from PIL import Image

    # a dim white-on-dark digit patch: foreground ~150 grey (below the 180
    # binarize threshold), background ~20. autocontrast must stretch the
    # foreground toward 255 so preprocessing can separate it.
    img = Image.new("L", (8, 8), 20)
    for y in range(2, 6):
        for x in range(2, 6):
            img.putpixel((x, y), 150)
    corrected = vt._color_correct(img)
    fg = corrected.getpixel((3, 3))
    bg = corrected.getpixel((0, 0))
    assert fg > 150            # stretched brighter, not dimmed
    assert fg > bg             # polarity preserved (not inverted)


def test_preprocess_applies_color_correction():
    from PIL import Image

    # a dim-foreground patch that a fixed 180 threshold would drop entirely;
    # with autocontrast folded into _preprocess the glyph survives binarize.
    img = Image.new("L", (6, 6), 15)
    for y in range(2, 4):
        for x in range(2, 4):
            img.putpixel((x, y), 140)
    out = vt._preprocess(img, scale=1, threshold=180)
    hist = out.convert("L").histogram()
    assert hist[255] > 0       # at least one lit pixel survived binarize
