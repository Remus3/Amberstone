# arch: latest-frame cache + upload handler | section=vision | frozen=no
"""Frame upload + cache.

Split out of moon_vision_server.py during Phase 2.4. Owns:
- ``_latest_frame`` - single-slot mirror of the most recent upload.
- ``_frames_by_source`` - per-source slots so secondary captures (e.g. dashboard
  UI debug) don't clobber the primary League frame the coaches read.
- ``handle_upload_frame(body)`` - POST /upload-frame with magic-byte validation
  and ~7 MB b64 payload cap.
- ``get_latest_frame(source)`` - GET /latest-frame[?source=...].
"""
from __future__ import annotations

import base64 as _b64
import json
import threading
import time

from ._config import log
from ._stats import _record, _stats, _stats_lock

_frame_lock = threading.Lock()
_latest_frame: dict = {"b64": None, "ts": 0.0, "size": 0, "source": None,
                       "width": None, "height": None, "format": None,
                       "event_meta": None}
_frames_by_source: dict = {}


# 2026-04-27 audit: cap b64 payload at ~7 MB (≈5 MB decoded). Typical frames
# are ~150 KB; anything 50× that is either a 4K screenshot we don't want to
# cache or a misbehaving uploader. Without this, a stray 100 MB upload would
# OOM the server before magic-byte validation runs.
_MAX_FRAME_B64 = 7_000_000


def handle_upload_frame(body: bytes) -> dict:
    """Game-PC agent POSTs the latest screenshot here.

    Body: {image_b64, source?, width?, height?, format?, primary?}

    ``primary`` (default True, for back-compat with the single-stream
    deployment) controls whether this upload also updates the global
    ``_latest_frame`` slot that coaches read via ``/latest-frame`` with no
    source filter. A secondary stream (e.g. UI-debug capture of the RC
    dashboard on monitor 1) should pass ``primary=False`` so it lands in
    ``_frames_by_source[src]`` only and doesn't clobber the League game
    frame the vision coaches are consuming. Legion-side readers that want
    that secondary stream query ``/latest-frame?source=<channel>``.
    """
    t0 = time.time()
    try:
        d = json.loads(body)
    except Exception:
        _record("frame_upload", int((time.time() - t0) * 1000), ok=False)
        return {"error": "bad_json"}
    img = d.get("image_b64", "")
    if not img:
        _record("frame_upload", int((time.time() - t0) * 1000), ok=False)
        return {"error": "no image_b64"}
    if len(img) > _MAX_FRAME_B64:
        _record("frame_upload", int((time.time() - t0) * 1000), ok=False)
        return {"error": "frame_too_large", "size": len(img),
                "limit": _MAX_FRAME_B64}
    # 2026-04-25: Magic-byte validation. Catches a corrupt / truncated /
    # non-image payload at upload time so coaches don't get garbage at the
    # /latest-frame fetch and waste a Sonnet call analyzing it. Cost is one
    # base64 decode of the leading 16 bytes - negligible vs the ~150 KB
    # frame we're about to cache.
    try:
        head = _b64.b64decode(img[:64], validate=False)[:8]
        is_jpeg = head[:3] == b"\xff\xd8\xff"
        is_png = head[:8] == b"\x89PNG\r\n\x1a\n"
        if not (is_jpeg or is_png):
            _record("frame_upload", int((time.time() - t0) * 1000), ok=False)
            return {"error": "not_an_image",
                    "head_hex": head.hex(),
                    "size": len(img)}
    except Exception as _exc:
        log.debug("frame magic check failed: %s", _exc)
        # Don't fail-closed on validation glitches - let the frame through so
        # a corner-case base64 layout doesn't blackhole real captures.
    src = d.get("source", "unknown")
    primary = bool(d.get("primary", True))
    # Item 207: optional event_meta field tags the frame as event-
    # driven (LCU phase-watcher capture). Backward-compatible: polling
    # uploads omit the field and get a None entry. UI-audit-ritual
    # subagent can subscribe to event-tagged frames specifically.
    event_meta = d.get("event_meta")
    if event_meta is not None and not isinstance(event_meta, dict):
        event_meta = None
    frame = {
        "b64":    img,
        "ts":     time.time(),
        "size":   len(img),
        "source": src,
        "width":  d.get("width"),
        "height": d.get("height"),
        "format": d.get("format", "png"),
        "primary": primary,
        "event_meta": event_meta,
    }
    with _frame_lock:
        _frames_by_source[src] = dict(frame)
        if primary:
            _latest_frame.update(frame)
    ms = int((time.time() - t0) * 1000)
    with _stats_lock:
        _stats["frame_upload"]["bytes"] = (
            _stats["frame_upload"].get("bytes", 0) + len(img)
        )
    _record("frame_upload", ms, ok=True)
    return {"ok": True, "size": len(img), "ts": frame["ts"],
            "source": src, "primary": primary,
            "event_tagged": event_meta is not None}


def get_latest_frame(source: str | None = None) -> dict:
    """Return a copy of the latest cached frame metadata + b64.

    If ``source`` is given, returns the most recent upload from that source
    only (or an empty dict if none seen). Otherwise returns the overall
    latest upload regardless of source.
    """
    with _frame_lock:
        if source is not None:
            return dict(_frames_by_source.get(source, {"b64": None, "ts": 0.0}))
        return dict(_latest_frame)
