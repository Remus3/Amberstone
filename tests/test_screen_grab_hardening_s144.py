"""S144-T-728: core/screen_grab.py true-audit hardening.

Pins four findings of the lane-8 audit:

- F1 grab_native, the native twin of the vision self-grab, served a blank
  (near-uniform) frame as ``ok: True``. The self-grab drops such a frame with
  the Y-03 reason ``blank``; a lock that lands between the probe and the grab,
  or an exclusive-fullscreen surface GDI cannot read, hands OCR a black frame.
  It now refuses with ``reason: "blank"``.
- F2 the input-desktop probe ignored a failed CloseDesktop (the Win32 BOOL
  was never read, and a raising close was swallowed by a bare ``pass``), so a
  leaked desktop handle per frame was invisible. The verdict stays "unlocked"
  (the open succeeded) but the failure is logged.
- F3 every probe built a fresh ``WinDLL("user32")`` and re-declared its
  argtypes, twice per frame on the self-grab path. The configured handle is
  now built once.
- F4 ``luma_range`` took any ``width``: 0 or a negative one failed deep inside
  PIL with an opaque message and ``True`` silently meant width 1. It now
  refuses a non-int, bool or non-positive width with ValueError.
"""
from __future__ import annotations

import base64
import io
import logging
import sys

import pytest
from PIL import Image

from core import screen_grab


def _textured(w=320, h=200):
    # Coarse blocks, not fine stripes: the blank detector averages over a
    # 64-wide thumbnail, so a 4-px stripe at 2560 wide reads flat by design.
    img = Image.new("RGB", (w, h), (0, 0, 0))
    img.paste((200, 180, 160), (0, 0, w // 2, h // 2))
    img.paste((90, 120, 60), (w // 2, h // 2, w, h))
    return img


# -- F1: grab_native refuses a blank frame ------------------------------------

@pytest.mark.parametrize("val", [0, 16, 128, 255])
def test_grab_native_refuses_uniform_frame_as_blank(val):
    out = screen_grab.grab_native(
        _grabber=lambda: Image.new("RGB", (2560, 1440), (val, val, val)))
    assert out["ok"] is False
    assert out["reason"] == "blank"
    assert "b64" not in out


def test_grab_native_refuses_zero_area_frame_as_blank():
    out = screen_grab.grab_native(_grabber=lambda: Image.new("RGB", (0, 0)))
    assert out["ok"] is False
    assert out["reason"] == "blank"


def test_grab_native_serves_textured_frame_at_native_size():
    out = screen_grab.grab_native(_grabber=lambda: _textured(2560, 1440))
    assert out["ok"] is True
    assert (out["width"], out["height"]) == (2560, 1440)
    raw = base64.b64decode(out["b64"], validate=True)
    assert raw[:3] == b"\xff\xd8\xff"
    assert "reason" not in out


def test_grab_native_blank_check_error_degrades_friendly():
    class _Weird:
        width = 10
        height = 10

        def convert(self, mode):
            raise ValueError("secret-ish internal 0xDEAD")

    out = screen_grab.grab_native(_grabber=_Weird)
    assert out["ok"] is False
    assert "0xDEAD" not in str(out)


# -- F2: a failed CloseDesktop is logged, verdict stays unlocked --------------

def test_close_returning_false_is_logged_not_silent(caplog):
    caplog.set_level(logging.DEBUG, logger="rc.vision")
    locked = screen_grab.input_desktop_locked(
        _open_input_desktop=lambda: 77, _close_desktop=lambda h: False)
    assert locked is False
    assert any("CloseDesktop" in r.getMessage() for r in caplog.records)


def test_close_raising_is_logged_not_silent(caplog):
    caplog.set_level(logging.DEBUG, logger="rc.vision")

    def boom(h):
        raise OSError("close failed")

    locked = screen_grab.input_desktop_locked(
        _open_input_desktop=lambda: 77, _close_desktop=boom)
    assert locked is False
    assert any("CloseDesktop" in r.getMessage() for r in caplog.records)


def test_close_succeeding_logs_nothing(caplog):
    caplog.set_level(logging.DEBUG, logger="rc.vision")
    closed = []
    locked = screen_grab.input_desktop_locked(
        _open_input_desktop=lambda: 77,
        _close_desktop=lambda h: closed.append(h) or True)
    assert locked is False
    assert closed == [77]
    assert not [r for r in caplog.records if "CloseDesktop" in r.getMessage()]


def test_close_returning_none_is_not_a_failure(caplog):
    # A seam (or a ctypes restype-less call) returning None is not evidence
    # of failure; only an explicit False / 0 is.
    caplog.set_level(logging.DEBUG, logger="rc.vision")
    assert screen_grab.input_desktop_locked(
        _open_input_desktop=lambda: 77, _close_desktop=lambda h: None) is False
    assert not [r for r in caplog.records if "CloseDesktop" in r.getMessage()]


# -- F3: the configured user32 handle is built once ---------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Win32 user32 only")
def test_user32_handle_is_built_once():
    a = screen_grab._user32()
    b = screen_grab._user32()
    assert a is b
    assert a.OpenInputDesktop.argtypes is not None
    assert a.CloseDesktop.argtypes is not None


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 user32 only")
def test_user32_handle_is_private_not_shared_windll():
    import ctypes
    assert screen_grab._user32() is not ctypes.windll.user32


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 user32 only")
def test_close_desktop_win_returns_bool_for_null_handle():
    # CloseDesktop(NULL) fails; the wrapper must report that as False, never
    # raise and never return the raw int.
    assert screen_grab._close_desktop_win(0) is False


# -- F4: luma_range validates width -------------------------------------------

@pytest.mark.parametrize("bad", [0, -1, True, False, 2.5, "64", None])
def test_luma_range_refuses_bad_width(bad):
    with pytest.raises(ValueError, match="width"):
        screen_grab.luma_range(Image.new("RGB", (64, 64)), width=bad)


def test_luma_range_accepts_width_one():
    img = Image.new("RGB", (64, 64), (0, 0, 0))
    assert screen_grab.luma_range(img, width=1) == 0


def test_luma_range_default_matches_constant():
    img = _textured()
    assert screen_grab.luma_range(img) == screen_grab.luma_range(
        img, width=screen_grab.BLANK_THUMB_WIDTH)


def test_jpeg_roundtrip_of_textured_frame_is_not_blank():
    buf = io.BytesIO()
    _textured().save(buf, format="JPEG", quality=85)
    assert not screen_grab.frame_is_blank(Image.open(io.BytesIO(buf.getvalue())))
