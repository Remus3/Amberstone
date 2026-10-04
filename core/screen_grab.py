# arch: full-resolution screen grab for OCR + calibration (no downscale) | section=vision | frozen=no
"""Native (un-downscaled) primary-screen grab for the OCR + calibration paths.

The vision self-grab (vision_server/_frame.py) downscales every frame to
_SELF_GRAB_MAX_WIDTH (1280) for the /latest-frame relay - fine for Sonnet scene
vision + companion bandwidth, but it halves HUD-text detail, which is exactly
what deterministic OCR needs most (memory reference_vision_ocr_capture_pipeline,
2026-07-05: operator plays 2560x1440, so the grab is halved to 1280x720 before
OCR crops from it). This helper grabs the primary screen at FULL resolution so
OCR crops + the region calibrator work on native pixels; per-snippet enhancement
(core/vision_tesseract._preprocess: 4x upscale + binarize) then sharpens glyphs.

A single GDI BitBlt via PIL.ImageGrab; safe no-op ({"ok": False}) when PIL is
absent or the grab fails (headless / locked session). JPEG quality is higher than
the downscaled path (detail matters more than bytes for a localhost 1-PC crop).

Y-03 (external reference K) fail-closed helpers, shared by the vision
self-grab: ``input_desktop_locked`` (the input desktop cannot be opened - a
locked workstation or a secure desktop such as UAC) and ``frame_is_blank`` (a
near-uniform frame by luminance range on a downscaled grey copy). Neither
injects anything; the locked probe only opens and closes a desktop handle.
"""
from __future__ import annotations

import base64
import io
import logging
import sys

log = logging.getLogger("rc.vision")

_NATIVE_JPEG_QUALITY = 92

# -- Y-03 blank-frame detector ----------------------------------------------
# A frame is "blank" when max - min luminance of a BLANK_THUMB_WIDTH-wide grey
# thumbnail is <= BLANK_LUMA_RANGE_MAX. Downscaling first averages away codec
# noise and costs a few ms. MEASURED 2026-10-04 (Y-03 slice): the twelve real
# 2560x1440 League stills in data/vision_calib_reference (incl. the grey
# self_dead death screen) score 107..166; uniform 0/16/128/255 frames JPEG'd
# at q85 (the self-grab encoding) at 1280x720 and 2560x1440 score 0. 16 (about
# 6% of the 0-255 scale) sits far above codec noise and far below the lowest
# real frame; re-measure if a legitimately flat in-game screen ever drops.
BLANK_THUMB_WIDTH = 64
BLANK_LUMA_RANGE_MAX = 16


def luma_range(img, width: int = BLANK_THUMB_WIDTH) -> int:
    """max - min luminance (0..255) of a ``width``-wide grey thumbnail."""
    grey = img.convert("L")
    h = max(1, round(grey.height * width / max(1, grey.width)))
    lo, hi = grey.resize((width, h)).getextrema()
    return int(hi) - int(lo)


def frame_is_blank(img) -> bool:
    """True for a near-uniform (all black / all white / flat) frame."""
    return luma_range(img) <= BLANK_LUMA_RANGE_MAX


# -- Y-03 locked / secure desktop probe --------------------------------------
_DESKTOP_SWITCHDESKTOP = 0x0100


def _open_input_desktop_win() -> int:
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)  # private fn objects
    user32.OpenInputDesktop.restype = ctypes.c_void_p
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                        wintypes.DWORD]
    return user32.OpenInputDesktop(0, False, _DESKTOP_SWITCHDESKTOP) or 0


def _close_desktop_win(handle: int) -> None:
    import ctypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.CloseDesktop.argtypes = [ctypes.c_void_p]
    user32.CloseDesktop(handle)


def input_desktop_locked(_open_input_desktop=None, _close_desktop=None) -> bool:
    """True when the input desktop cannot be opened for switching: the
    workstation is locked or a secure desktop (UAC, Ctrl+Alt+Del) holds input.
    A GDI grab there returns black or fails, so callers refuse the capture
    with reason ``locked``. A probe ERROR also reads locked (fail closed).
    Non-Windows hosts have no input desktop and report False. The two
    callables are injectable seams for tests."""
    if _open_input_desktop is None:
        if sys.platform != "win32":
            return False
        _open_input_desktop = _open_input_desktop_win
        _close_desktop = _close_desktop_win
    try:
        handle = _open_input_desktop()
    except Exception as exc:  # noqa: BLE001
        log.debug("input desktop probe failed: %s", exc)
        return True
    if not handle:
        return True
    try:
        _close_desktop(handle)
    except Exception:  # noqa: BLE001
        pass
    return False


def grab_native(_grabber=None) -> dict:
    """Full-resolution primary-screen grab (no downscale). Returns
    ``{"ok": True, "b64", "width", "height", "format"}`` or
    ``{"ok": False, "error"}``. ``_grabber`` is an injectable seam for tests
    (a callable returning a PIL Image). Y-03: a real grab (no ``_grabber``)
    on a locked / secure input desktop returns ``reason: "locked"``."""
    if _grabber is None and input_desktop_locked():
        return {"ok": False, "error": "input desktop locked",
                "reason": "locked"}
    try:
        if _grabber is None:
            from PIL import ImageGrab
            _grabber = ImageGrab.grab
        img = _grabber()
        if img is None:
            return {"ok": False, "error": "grab returned no image"}
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG",
                                quality=_NATIVE_JPEG_QUALITY, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return {"ok": True, "b64": b64, "width": img.width,
                "height": img.height, "format": "jpeg"}
    except Exception as exc:  # noqa: BLE001
        log.debug("native grab failed: %s", exc)
        return {"ok": False, "error": "native grab unavailable"}
