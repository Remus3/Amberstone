"""s144 true-audit (RM-1108): the OBS lane of vision_server/_frame.py.

``_maybe_obs_frame`` turns OBS GetSourceScreenshot bytes into the
cache-shaped frame the coaches read. Before this slice:

  F1  an undecodable payload (PIL could not open it) was served RAW,
      labelled "jpeg", with no magic check and no Y-03 blank check;
  F2  a decodable frame at or under 1280 wide was served raw and labelled
      "jpeg" whatever its real format (a PNG went out as "jpeg");
  F3  a super-wide frame computed a resize height of 0, the resize raised,
      and the raw un-downscaled bytes were served instead (no width/height);
  F4  (characterization, already CLEAN) a non-bytes payload returns None:
      PIL refuses it at decode, which now falls through like any
      undecodable payload;
  F5  the GDI sibling in ``_fetch_frame_direct`` had the same zero-height
      resize, so a super-wide desktop grab was dropped instead of served.

Acceptance: an undecodable OBS payload returns None (the caller falls
through to GDI) and records nothing; the "jpeg" label always matches the
served bytes; a zero resize height is clamped to 1. Every case runs against
a ``get_obs_frame`` stub - no live OBS, no real desktop grab.

All authored content is 7-bit ASCII.
"""
from __future__ import annotations

import base64
import io

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from vision_server import _frame  # noqa: E402
from vision_server import _stats as stats_mod  # noqa: E402

_JPEG_MAGIC = b"\xff\xd8\xff"


def _textured(w, h):
    """A non-uniform frame: horizontal grey ramp (not Y-03 blank)."""
    img = Image.new("L", (w, h))
    img.putdata([int(255 * (x / max(1, w - 1))) for _y in range(h) for x in range(w)])
    return img.convert("RGB")


def _encode(img, fmt):
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    _frame._reset_self_read_state()
    stats_mod._reset_capture_skips()
    from core import vision_profiles
    monkeypatch.setattr(vision_profiles, "save_reference_image",
                        lambda *a, **k: False)
    yield
    _frame._reset_self_read_state()
    stats_mod._reset_capture_skips()


def _obs(monkeypatch, payload):
    from core import obs_frame_source as ofs
    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: True)
    monkeypatch.setattr(ofs, "get_obs_frame", lambda *a, **k: payload)


def _gdi(monkeypatch, img, fg):
    grabs = []
    from PIL import ImageGrab

    def _grab(*a, **k):
        grabs.append(1)
        return img
    monkeypatch.setattr(ImageGrab, "grab", _grab)
    monkeypatch.setattr(_frame, "_input_desktop_locked", lambda: False)
    monkeypatch.setattr(_frame, "_league_foreground", lambda: fg)
    return grabs


def _served(frame):
    return base64.b64decode(frame["b64"])


# -- F1: an undecodable payload falls through, never served raw -------------

@pytest.mark.parametrize("payload", [
    b"\xff\xd8\xff-not-a-real-jpeg",  # JPEG magic, garbage body
    b"GIF89a-not-an-image",           # wrong family, garbage
    b"\x00" * 64,                     # no magic at all
], ids=["jpeg-magic-garbage", "gif-garbage", "zeros"])
def test_undecodable_obs_payload_returns_none(monkeypatch, payload):
    _obs(monkeypatch, payload)
    assert _frame._maybe_obs_frame() is None


def test_truncated_obs_jpeg_returns_none(monkeypatch):
    whole = _encode(_textured(640, 360), "JPEG")
    _obs(monkeypatch, whole[: len(whole) // 2])
    assert _frame._maybe_obs_frame() is None


def test_undecodable_obs_falls_through_to_gdi(monkeypatch):
    _obs(monkeypatch, b"\xff\xd8\xff-not-a-real-jpeg")
    grabs = _gdi(monkeypatch, _textured(640, 360), fg=True)
    out = _frame._maybe_self_grab()
    assert out is not None and out["source"] == "self_grab"
    assert grabs == [1]
    assert "obs" not in _frame._frames_by_source


def test_undecodable_obs_records_nothing_when_gdi_refuses(monkeypatch):
    _obs(monkeypatch, b"\xff\xd8\xff-not-a-real-jpeg")
    grabs = _gdi(monkeypatch, _textured(640, 360), fg=False)
    assert _frame._maybe_self_grab() is None
    assert grabs == []
    assert _frame.get_latest_frame().get("b64") is None
    assert "obs" not in _frame._frames_by_source


# -- F2: the "jpeg" label matches the served bytes --------------------------

def test_small_png_obs_frame_is_reencoded_as_jpeg(monkeypatch):
    _obs(monkeypatch, _encode(_textured(640, 360), "PNG"))
    frame = _frame._maybe_obs_frame()
    assert frame is not None
    assert frame["format"] == "jpeg"
    data = _served(frame)
    assert data[:3] == _JPEG_MAGIC
    assert (frame["width"], frame["height"]) == (640, 360)
    assert Image.open(io.BytesIO(data)).size == (640, 360)


def test_small_jpeg_obs_frame_passes_through_byte_identical(monkeypatch):
    raw = _encode(_textured(640, 360), "JPEG")
    _obs(monkeypatch, raw)
    frame = _frame._maybe_obs_frame()
    assert frame is not None
    assert _served(frame) == raw
    assert frame["format"] == "jpeg"
    assert (frame["width"], frame["height"]) == (640, 360)
    assert frame["size"] == len(frame["b64"])


def test_wide_jpeg_obs_frame_is_downscaled(monkeypatch):
    _obs(monkeypatch, _encode(_textured(2560, 1440), "JPEG"))
    frame = _frame._maybe_obs_frame()
    assert frame is not None
    assert (frame["width"], frame["height"]) == (1280, 720)
    data = _served(frame)
    assert data[:3] == _JPEG_MAGIC
    assert Image.open(io.BytesIO(data)).size == (1280, 720)


# -- F3: a super-wide OBS frame clamps the resize height to 1 ---------------

def test_super_wide_obs_frame_clamps_height(monkeypatch):
    raw = _encode(_textured(20000, 1), "PNG")
    _obs(monkeypatch, raw)
    frame = _frame._maybe_obs_frame()
    assert frame is not None
    assert (frame["width"], frame["height"]) == (1280, 1)
    data = _served(frame)
    assert data != raw
    assert data[:3] == _JPEG_MAGIC
    assert Image.open(io.BytesIO(data)).size == (1280, 1)


# -- F4: a non-bytes payload is refused (characterization) ------------------

@pytest.mark.parametrize("payload", ["\xff\xd8\xff-text", 12345, ["x"]])
def test_non_bytes_obs_payload_returns_none(monkeypatch, payload):
    _obs(monkeypatch, payload)
    assert _frame._maybe_obs_frame() is None


def test_bytearray_obs_payload_is_accepted(monkeypatch):
    raw = _encode(_textured(320, 180), "JPEG")
    _obs(monkeypatch, bytearray(raw))
    frame = _frame._maybe_obs_frame()
    assert frame is not None
    assert _served(frame) == raw


# -- F5: the GDI sibling clamps the same way --------------------------------

def test_super_wide_gdi_grab_clamps_height(monkeypatch):
    from core import obs_frame_source as ofs
    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: False)
    _gdi(monkeypatch, _textured(20000, 1), fg=True)
    frame = _frame._fetch_frame_direct()
    assert frame is not None
    assert frame["source"] == "self_grab"
    assert (frame["width"], frame["height"]) == (1280, 1)
    assert _served(frame)[:3] == _JPEG_MAGIC


def test_wide_gdi_grab_keeps_aspect(monkeypatch):
    """Characterization: the normal GDI downscale is unchanged."""
    from core import obs_frame_source as ofs
    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: False)
    _gdi(monkeypatch, _textured(2560, 1440), fg=True)
    frame = _frame._fetch_frame_direct()
    assert frame is not None
    assert (frame["width"], frame["height"]) == (1280, 720)
