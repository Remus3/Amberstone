# arch: public-API native-crop regression guard (R94) | section=vision-tests | frozen=no
"""R94 regression guard: the PUBLIC crop entrypoints honor a native-res profile.

Context (verify-before-declare): the R94 directive asked to "wire native OCR
crops + color-correction into core/vision_tesseract", but that wiring ALREADY
shipped - _color_correct/_preprocess (LEDGER 793) + the vision_profiles hot-path
in _regions() + _scale_bbox, and the R91 derive_scaled_regions primitive
(LEDGER 832). test_vision_tesseract_profile_wiring.py already guards those seams
in isolation (_regions / _scale_bbox / _color_correct / _preprocess).

The one uncovered seam was the PUBLIC crop path: nothing drove crop_png_b64 or
the read_fast_fields work-list with a native 2560x1440 profile to prove a native
frame is cropped at native coordinates with NO 1920->native downscale drift (the
halved-frame tiny-text failure mode, memory reference_vision_ocr_capture_pipeline).
These tests close that gap end-to-end.

CI-safe: crop_png_b64 needs only PIL; the read_fast_fields path monkeypatches the
tesseract seams (_ensure_tesseract + _parse_field) so no tesseract.exe is invoked.
"""
from __future__ import annotations

import base64
import io

import pytest

from core import vision_tesseract as vt

# A native 2560x1440 profile with a known gold box. Width 86, height 26 - the
# exact rectangle a native frame must yield when the profile base matches the
# frame (scale is a no-op). If the crop path fell back to the legacy 1920 base
# it would scale this box by 2560/1920 and the crop dimensions would differ.
_NATIVE_BASE = [2560, 1440]
_GOLD_BOX = [1463, 1407, 1549, 1433]
_GOLD_W = _GOLD_BOX[2] - _GOLD_BOX[0]   # 86
_GOLD_H = _GOLD_BOX[3] - _GOLD_BOX[1]   # 26


def _native_profile():
    return {
        "config_key": "2560x1440|GlobalScale=1",
        "base": list(_NATIVE_BASE),
        "regions": {"gold": list(_GOLD_BOX)},
        "source": "profile",
    }


def _use_native_profile(monkeypatch):
    import core.vision_profiles as vp
    monkeypatch.setattr(vp, "load_profile", lambda config_key=None: _native_profile())
    vt.reload_regions()


def _native_frame_b64():
    from PIL import Image
    img = Image.new("RGB", (_NATIVE_BASE[0], _NATIVE_BASE[1]), (10, 10, 10))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_crop_png_b64_uses_native_box_no_drift(monkeypatch):
    """crop_png_b64 (public) crops a native frame at native coords: the decoded
    PNG is exactly the profile box, not a 1920-scaled rectangle."""
    _use_native_profile(monkeypatch)
    from PIL import Image

    out_b64 = vt.crop_png_b64(_native_frame_b64(), "gold")
    assert out_b64, "expected a PNG crop, got None"
    crop = Image.open(io.BytesIO(base64.b64decode(out_b64)))
    assert crop.size == (_GOLD_W, _GOLD_H)
    # native base drove the scaler (a no-op), so the box is byte-identical
    assert vt._BASE_CACHE == (2560, 1440)
    assert vt._scale_bbox(_GOLD_BOX, 2560, 1440) == tuple(_GOLD_BOX)


def test_read_fast_fields_worklist_crops_native(monkeypatch):
    """The read_fast_fields work-list selects a native-coordinate crop for a
    native frame. tesseract is stubbed - we only assert the crop geometry the
    parser receives, which is what "native OCR crops" means at the hot path."""
    _use_native_profile(monkeypatch)
    monkeypatch.setattr(vt, "_ensure_tesseract", lambda: None)

    seen = {}

    def _capture(name, crop):
        seen[name] = crop.size
        return None   # skip the real parser -> no tesseract needed

    monkeypatch.setattr(vt, "_parse_field", _capture)
    vt.read_fast_fields(_native_frame_b64(), fields=["gold"], parallel=False)
    assert seen.get("gold") == (_GOLD_W, _GOLD_H)


def test_crop_png_b64_unknown_field_is_none(monkeypatch):
    """Public guard: an unmapped field yields None, never an exception."""
    _use_native_profile(monkeypatch)
    assert vt.crop_png_b64(_native_frame_b64(), "not_a_real_field") is None


def test_native_profile_defeats_legacy_downscale(monkeypatch):
    """Explicit anti-drift assertion: at the native base the crop keeps full
    native size, strictly larger than the legacy 1920-base scaling of the same
    box would leave it (2560/1920 = 1.3333x). Documents the failure the wiring
    prevents without re-testing the scaler in isolation."""
    _use_native_profile(monkeypatch)
    from PIL import Image

    crop = Image.open(io.BytesIO(base64.b64decode(vt.crop_png_b64(_native_frame_b64(), "gold"))))
    legacy_w = int(_GOLD_BOX[2] * 1920 / 2560) - int(_GOLD_BOX[0] * 1920 / 2560)
    assert crop.size[0] > legacy_w   # native path did NOT shrink toward 1920


@pytest.fixture(autouse=True)
def _restore_regions():
    """Every test leaves the module region cache clean for the next importer."""
    yield
    vt.reload_regions()
