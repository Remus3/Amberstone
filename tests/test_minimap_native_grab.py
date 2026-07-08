"""Tests for the NATIVE-resolution minimap grab (2026-07-01).

The vision self-grab downscales the whole screen to 1280px + JPEG
(vision_server/_frame.py), so the minimap crop is only ~208px and champion
icons are 5-25px, color-corrupted. `current_minimap_dots` now prefers a NATIVE
full-res grab (~416px, 4x the pixels, no JPEG) and falls back to the coaching
frame. Detection stays resolution-invariant via scaled size bounds. All
CI-safe: the grabs are monkeypatched, never touching a real screen / vision
server.
"""
import pytest

np = pytest.importorskip("numpy")

import core.minimap_blob_detect as mbd

RED = (200, 40, 40)


def _crop_with_red(w=208):
    """A square crop with one champion-sized red blob (scaled to the crop)."""
    a = np.zeros((w, w, 3), dtype=np.uint8)
    s = max(3, w // 40)
    c = w // 2
    a[c:c + s, c:c + s] = RED
    return a


def _boom(_rect):
    raise AssertionError("fallback frame path used when native succeeded")


def test_native_grab_enabled_default_on(monkeypatch):
    monkeypatch.delenv("RC_ZOI_NATIVE_GRAB", raising=False)
    assert mbd._native_grab_enabled() is True


def test_native_grab_disabled_by_env(monkeypatch):
    for v in ("0", "false", "off", "no"):
        monkeypatch.setenv("RC_ZOI_NATIVE_GRAB", v)
        assert mbd._native_grab_enabled() is False, v


def test_scaled_bounds_baseline_208_unchanged():
    minpx, maxpx = mbd._scaled_size_bounds(208)
    assert minpx == mbd._MIN_PX
    assert maxpx == mbd._MAX_PX


def test_scaled_bounds_native_416_is_2x():
    # 416px = 2x linear; champion minimap icons are FIXED pixel size (not
    # proportional to crop width), so scaling is LINEAR (2026-07-08: was area).
    minpx, maxpx = mbd._scaled_size_bounds(416)
    assert minpx == mbd._MIN_PX * 2
    assert maxpx == mbd._MAX_PX * 2


def test_current_uses_native_when_available(monkeypatch):
    mbd._dots_cache.update(wall=0.0, rect=None, dots=[])
    crop = _crop_with_red(416)
    monkeypatch.setattr(mbd, "_native_grab_enabled", lambda: True)
    monkeypatch.setattr(mbd, "_grab_native_minimap", lambda r: crop)
    monkeypatch.setattr(mbd, "_grab_frame_minimap", _boom)  # must NOT be called
    dots = mbd.current_minimap_dots({"x": 1600, "y": 761, "w": 312, "h": 312}, ttl_s=0.0)
    assert len(dots) == 1 and dots[0]["team"] == "red"


def test_current_falls_back_to_frame_when_native_none(monkeypatch):
    mbd._dots_cache.update(wall=0.0, rect=None, dots=[])
    crop = _crop_with_red(208)
    monkeypatch.setattr(mbd, "_native_grab_enabled", lambda: True)
    monkeypatch.setattr(mbd, "_grab_native_minimap", lambda r: None)
    monkeypatch.setattr(mbd, "_grab_frame_minimap", lambda r: crop)
    dots = mbd.current_minimap_dots({"x": 1600, "y": 761, "w": 312, "h": 312}, ttl_s=0.0)
    assert len(dots) == 1 and dots[0]["team"] == "red"


def test_current_skips_native_when_disabled(monkeypatch):
    mbd._dots_cache.update(wall=0.0, rect=None, dots=[])
    crop = _crop_with_red(208)
    monkeypatch.setattr(mbd, "_native_grab_enabled", lambda: False)
    monkeypatch.setattr(mbd, "_grab_native_minimap", _boom)  # must NOT be called
    monkeypatch.setattr(mbd, "_grab_frame_minimap", lambda r: crop)
    dots = mbd.current_minimap_dots({"x": 1600, "y": 761, "w": 312, "h": 312}, ttl_s=0.0)
    assert len(dots) == 1 and dots[0]["team"] == "red"


def test_current_empty_when_both_grabs_none(monkeypatch):
    mbd._dots_cache.update(wall=0.0, rect=None, dots=[])
    monkeypatch.setattr(mbd, "_grab_native_minimap", lambda r: None)
    monkeypatch.setattr(mbd, "_grab_frame_minimap", lambda r: None)
    dots = mbd.current_minimap_dots({"x": 1, "y": 1, "w": 1, "h": 1}, ttl_s=0.0)
    assert dots == []


def test_grab_native_fail_soft_on_grab_error(monkeypatch):
    ImageGrab = pytest.importorskip("PIL.ImageGrab")
    monkeypatch.setattr(ImageGrab, "grab",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no display")))
    out = mbd._grab_native_minimap({"x": 1600, "y": 761, "w": 312, "h": 312})
    assert out is None


def test_grab_native_bad_rect_none():
    assert mbd._grab_native_minimap(None) is None
    assert mbd._grab_native_minimap("nope") is None
