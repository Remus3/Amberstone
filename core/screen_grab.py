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
"""
from __future__ import annotations

import base64
import io
import logging

log = logging.getLogger("rc.vision")

_NATIVE_JPEG_QUALITY = 92


def grab_native(_grabber=None) -> dict:
    """Full-resolution primary-screen grab (no downscale). Returns
    ``{"ok": True, "b64", "width", "height", "format"}`` or
    ``{"ok": False, "error"}``. ``_grabber`` is an injectable seam for tests
    (a callable returning a PIL Image)."""
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
