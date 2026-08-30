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
liveclient relay self-heal (vision_server/_relay.py, item 267). On 1-PC the
continuous screen-agent loop is retired in favor of the in-process self-grab
relay, so the global ``/latest-frame`` slot is fed on demand. When League runs
on this host (``core.game_host.GAME_HOST`` local) and the cached frame is
stale/missing, ``get_latest_frame`` grabs ONE frame in-process (a single
on-demand GDI BitBlt via PIL.ImageGrab) so the relay agent is an optimization
rather than a hard dependency. A remote ``RC_GAME_HOST`` (legacy remote-host
config) disables the self-grab (the agent stays primary; a remote box's screen
is not capturable here). Self-grabs are lightly throttled to avoid redundant
back-to-back grabs
and are fail-soft (return the existing cache, never raise).
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

# -- 1-PC self-heal config (ADR-011) -----------------------------------------
# Mirrors vision_server/_relay.py. A single one-shot GDI BitBlt grab is the
# fallback for the retired continuous screen-agent loop (1-PC, ADR-011). The
# intervals are tight so vision recording stays fresh during live gameplay.
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_SELF_GRAB_STALE_S = 1.0          # serve the cache as-is when fresher than this
_SELF_GRAB_MIN_INTERVAL_S = 0.5   # min gap between in-process grab attempts
_SELF_GRAB_MAX_WIDTH = 1280       # downscale to the documented coaching width
_SELF_GRAB_JPEG_QUALITY = 85      # matches the legacy screen-agent sweet spot
_self_grab_lock = threading.Lock()
_last_self_grab_attempt = 0.0


def _maybe_obs_frame():
    """OBS occlusion-proof frame provider (ZOI plan spec O, 2026-07-05).

    Config-gated on ``obs.frame_source`` (DEFAULT OFF). When enabled, an OBS
    GetSourceScreenshot frame REPLACES the GDI self-grab: OBS Game Capture
    reads the game surface directly, so the RC overlay sitting on top never
    contaminates the frame. ANY failure (flag off, OBS down, decode error)
    returns None and the caller falls through to the untouched GDI path -
    flag off is byte-identical to prior behavior.

    Mirrors the GDI path's contract: downscales to ``_SELF_GRAB_MAX_WIDTH``
    (the documented coaching width) and returns the cache-shaped dict."""
    try:
        from core.obs_frame_source import get_obs_frame, obs_frame_source_enabled
        if not obs_frame_source_enabled():
            return None
        raw = get_obs_frame()
        if not raw:
            return None
        width = height = None
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(raw))
            img.load()
            if img.width > _SELF_GRAB_MAX_WIDTH:
                ratio = _SELF_GRAB_MAX_WIDTH / img.width
                img = img.resize((_SELF_GRAB_MAX_WIDTH,
                                  int(img.height * ratio)))
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG",
                                        quality=_SELF_GRAB_JPEG_QUALITY,
                                        optimize=True)
                raw = buf.getvalue()
            width, height = img.width, img.height
        except Exception:  # noqa: BLE001 - PIL absent/undecodable: serve raw as-is
            pass
        b64 = _b64.b64encode(raw).decode("ascii")
        return {
            "b64":    b64,
            "size":   len(b64),
            "width":  width,
            "height": height,
            "format": "jpeg",
            "source": "obs",
        }
    except Exception:  # noqa: BLE001 - never let the OBS lane break the grab
        return None


def _fetch_frame_direct():
    """One in-process screen grab. Returns the cache-shaped frame dict (with a
    base64 JPEG ``b64``) or None on any failure (PIL absent, headless session,
    grab error). A single GDI BitBlt via PIL.ImageGrab. Patchable seam for
    tests.

    Spec O (2026-07-05): when config ``obs.frame_source`` is on, the OBS
    occlusion-proof frame is tried FIRST; ANY OBS failure falls back to the
    GDI BitBlt below. Flag off (the default) short-circuits to None inside
    ``_maybe_obs_frame`` and this function behaves exactly as before."""
    obs_frame = _maybe_obs_frame()
    if obs_frame is not None:
        return obs_frame
    try:
        from PIL import ImageGrab
    except Exception:  # noqa: BLE001
        return None
    try:
        img = ImageGrab.grab()  # primary virtual screen, single GDI BitBlt
        if img is None:
            return None
        # Arm single-screen calibration: persist a NATIVE (pre-downscale) reference
        # frame per HUD profile ONCE, only while a game is live AND League holds the
        # foreground window (all gating is inside save_reference_image: has_game +
        # foreground + no-ref-yet). The foreground gate stops an alt-tab from
        # clobbering the calibrated base with a desktop frame; the once-per-config
        # gate retires the old 60s re-grab cadence. Fail-soft - never breaks the grab.
        try:
            from core.vision_profiles import save_reference_image
            save_reference_image(img)
        except Exception:  # noqa: BLE001
            pass
        if img.width > _SELF_GRAB_MAX_WIDTH:
            ratio = _SELF_GRAB_MAX_WIDTH / img.width
            img = img.resize((_SELF_GRAB_MAX_WIDTH, int(img.height * ratio)))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG",
                                quality=_SELF_GRAB_JPEG_QUALITY, optimize=True)
        b64 = _b64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:  # noqa: BLE001
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
    # Spec O: the direct grab may come from OBS ("obs") instead of the GDI
    # BitBlt ("self_grab"); propagate its label. GDI grabs always stamp
    # "self_grab" so the flag-off path is byte-identical to before.
    src = grabbed.get("source") or "self_grab"
    frame = {
        "b64":    grabbed["b64"],
        "ts":     now,
        "size":   grabbed.get("size", len(grabbed["b64"])),
        "source": src,
        "width":  grabbed.get("width"),
        "height": grabbed.get("height"),
        "format": grabbed.get("format", "jpeg"),
        "primary": True,
        "event_meta": None,
    }
    with _frame_lock:
        _latest_frame.update(frame)
        _frames_by_source[src] = dict(frame)
        return dict(_latest_frame)


# 2026-04-27 audit: cap b64 payload at ~7 MB (~5 MB decoded). Typical frames
# are ~150 KB; anything 50x that is either a 4K screenshot we don't want to
# cache or a misbehaving uploader. Without this, a stray 100 MB upload would
# OOM the server before magic-byte validation runs.
_MAX_FRAME_B64 = 7_000_000


def handle_upload_frame(body: bytes) -> dict:
    """Legion-local screen agent POSTs the latest screenshot here.

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
    except Exception:  # noqa: BLE001
        _record("frame_upload", int((time.time() - t0) * 1000), ok=False)
        return {"error": "bad_json"}
    # AUDIT 2026-08-30 (lane 8 cycle 20, sibling of the _inference fix): the
    # guard above covers only the DECODE. A body that is valid JSON but not an
    # object - `[1,2]`, `"x"`, `5` - decoded fine and then died on `.get`
    # below with AttributeError, which do_POST turned into an HTTP 500.
    if not isinstance(d, dict):
        _record("frame_upload", int((time.time() - t0) * 1000), ok=False)
        return {"error": "bad_body"}
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
    except Exception as _exc:  # noqa: BLE001
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
