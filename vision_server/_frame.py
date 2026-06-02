# arch: latest-frame cache + upload handler | section=vision | frozen=no
"""Frame upload + cache.

Split out of moon_vision_server.py during Phase 2.4. Owns:
- ``_latest_frame`` - single-slot mirror of the most recent upload.
- ``_frames_by_source`` - per-source slots so secondary captures (e.g. dashboard
  UI debug) don't clobber the primary League frame the coaches read.
- ``handle_upload_frame(body)`` - POST /upload-frame with magic-byte validation
  and ~7 MB b64 payload cap.
- ``get_latest_frame(source)`` - GET /latest-frame[?source=...].

1-PC self-heal (post-2026-05 Legion consolidation, ADR-011): mirrors the
liveclient relay self-heal (vision_server/_relay.py, item 267). After the
Game-PC -> Legion consolidation the continuous DXGI screen-agent that pushed
frames here is DISABLED (it is the permanent BSOD trigger - ADR-011,
feedback_gamepc_screen_capture_bsod), so nothing feeds the global
``/latest-frame`` slot. When League runs on this host
(``core.game_host.GAME_HOST`` local) and the cached frame is stale/missing,
``get_latest_frame`` grabs ONE frame in-process (a single on-demand GDI BitBlt
via PIL.ImageGrab - NOT a loop, NOT the continuous DXGI surface) so the relay
agent becomes an optimization rather than a hard dependency. A remote
``RC_GAME_HOST`` (legacy 2-PC) disables the self-grab (the agent stays primary;
a remote box's screen is not capturable here). Self-grabs are throttled so a
no-game steady state never hammers GDI, and are fail-soft (return the existing
cache, never raise). This ONLY activates as a fallback when the relay frame is
already dead.
"""
from __future__ import annotations

import base64 as _b64
import io
import json
import threading
import time

from core.game_host import GAME_HOST

from ._config import log
from ._stats import _record, _stats, _stats_lock

_frame_lock = threading.Lock()
_latest_frame: dict = {"b64": None, "ts": 0.0, "size": 0, "source": None,
                       "width": None, "height": None, "format": None,
                       "event_meta": None}
_frames_by_source: dict = {}

# ── 1-PC self-heal config (ADR-011) ─────────────────────────────────────────
# Mirrors vision_server/_relay.py. A single one-shot GDI BitBlt grab is the
# fallback; it is NOT the continuous DXGI/bettercam loop that crashed Game-PC
# (feedback_gamepc_screen_capture_bsod) - that loop stays permanently retired.
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_SELF_GRAB_STALE_S = 2.0          # serve the cache as-is when fresher than this
_SELF_GRAB_MIN_INTERVAL_S = 1.5   # min gap between in-process grab attempts
_SELF_GRAB_MAX_WIDTH = 1280       # downscale to the documented coaching width
_SELF_GRAB_JPEG_QUALITY = 85      # matches the legacy screen-agent sweet spot
_self_grab_lock = threading.Lock()
_last_self_grab_attempt = 0.0


def _fetch_frame_direct():
    """One in-process screen grab. Returns the cache-shaped frame dict (with a
    base64 JPEG ``b64``) or None on any failure (PIL absent, headless session,
    grab error). A single GDI BitBlt via PIL.ImageGrab - NOT the continuous
    DXGI/bettercam surface that is the BSOD trigger. Patchable seam for tests."""
    try:
        from PIL import ImageGrab
    except Exception:
        return None
    try:
        img = ImageGrab.grab()  # primary virtual screen, single GDI BitBlt
        if img is None:
            return None
        if img.width > _SELF_GRAB_MAX_WIDTH:
            ratio = _SELF_GRAB_MAX_WIDTH / img.width
            img = img.resize((_SELF_GRAB_MAX_WIDTH, int(img.height * ratio)))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG",
                                quality=_SELF_GRAB_JPEG_QUALITY, optimize=True)
        b64 = _b64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        log.debug("frame self-grab failed: %s", exc)
        return None
    return {
        "b64":    b64,
        "size":   len(b64),
        "width":  img.width,
        "height": img.height,
        "format": "jpeg",
        "source": "self_grab",
    }


def _reset_self_read_state() -> None:
    """Test helper: clear the self-grab throttle + the cached frame slots."""
    global _last_self_grab_attempt
    with _self_grab_lock:
        _last_self_grab_attempt = 0.0
    with _frame_lock:
        _latest_frame.update({"b64": None, "ts": 0.0, "size": 0,
                              "source": None, "width": None, "height": None,
                              "format": None, "event_meta": None})
        _frames_by_source.clear()


def _maybe_self_grab() -> dict | None:
    """If League is local and the cache is stale, grab one frame in-process
    (throttled). Returns the freshly populated frame dict or None to fall
    through to the existing cache."""
    global _last_self_grab_attempt
    now = time.time()
    with _self_grab_lock:
        if now - _last_self_grab_attempt < _SELF_GRAB_MIN_INTERVAL_S:
            return None
        _last_self_grab_attempt = now
    grabbed = _fetch_frame_direct()
    if not isinstance(grabbed, dict) or not grabbed.get("b64"):
        return None
    frame = {
        "b64":    grabbed["b64"],
        "ts":     now,
        "size":   grabbed.get("size", len(grabbed["b64"])),
        "source": "self_grab",
        "width":  grabbed.get("width"),
        "height": grabbed.get("height"),
        "format": grabbed.get("format", "jpeg"),
        "primary": True,
        "event_meta": None,
    }
    with _frame_lock:
        _latest_frame.update(frame)
        _frames_by_source["self_grab"] = dict(frame)
        return dict(_latest_frame)


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

    1-PC self-heal: a source-less (global) request, when League is on this host
    and the cached frame is stale/missing, triggers ONE throttled in-process
    grab so coaches keep getting frames after the continuous screen-agent is
    retired. A ``?source=`` request is the secondary UI-debug channel and is
    NEVER self-grabbed (it must reflect exactly what that channel pushed).
    """
    with _frame_lock:
        if source is not None:
            return dict(_frames_by_source.get(source, {"b64": None, "ts": 0.0}))
        snap = dict(_latest_frame)
    if GAME_HOST in _LOCAL_HOSTS:
        age = time.time() - float(snap.get("ts") or 0.0)
        if age > _SELF_GRAB_STALE_S:
            fresh = _maybe_self_grab()
            if fresh is not None:
                return fresh
    return snap
