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

Y-03 (external reference K) - the self-grab FAILS CLOSED with one named
reason (vocabulary: vision_server._stats.CAPTURE_SKIP_REASONS), counted in
``get_stats()["capture_skip"]``:
- ``locked``: the input desktop cannot be opened (locked / secure desktop);
  checked in ``_maybe_self_grab`` before ANY source is tried.
- ``not_foreground``: League of Legends.exe has not held the foreground window
  within ``_FOREGROUND_GRACE_S``; GDI path only (the OBS lane captures a scene,
  not the desktop, so an alt-tab cannot leak into it).
- ``blank``: a near-uniform frame (core.screen_grab.frame_is_blank), dropped
  from both lanes before it can reach OCR, Sonnet or a calibration still.
The probes read only the foreground window's image name and whether the input
desktop opens; nothing is injected (Vanguard).

S156 S7 - WINDOWED clients: the GDI grab is cut to the game window's client
area (``vision_server._game_window``; read-only Win32) when the League / TFT
client runs windowed, so the frame is the game surface every OCR region is
authored against and scaled to; a fullscreen client or no game window keeps
the full primary-screen grab exactly as before (``last_capture_window()``).
The foreground gate above is unchanged: a windowed client must still hold
(or have just held) the foreground.

s144 true-audit (RM-1046): in-process intervals (the self-grab throttle,
the foreground grace window, upload latency) run on the MONOTONIC clock, so a
backward wall-clock step can neither freeze the self-grab nor hold the grace
window open; the frame ``ts`` stays wall-clock (it crosses the process
boundary) and is aged through core.relay_age.is_stale (RM-269). An upload's
``image_b64`` must be an ASCII string, ``source`` a short non-empty string
and ``primary`` a bool; the cached width / height / format are read from the
payload header, not taken from the uploader's claim; distinct source slots are
capped.
"""
from __future__ import annotations

import base64 as _b64
import io
import json
import threading
import time

from core.game_host import GAME_HOST
from core.relay_age import is_stale
from core.screen_grab import frame_is_blank, input_desktop_locked

from ._config import log
from ._stats import (
    OBS_LANE_FAILURES,
    _capture_skips,
    _record,
    _record_capture_skip,
    _record_gdi_lane_failure,
    _record_obs_lane_failure,
    _stats,
    _stats_lock,
)

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
# Monotonic stamp of the last attempt; None = none yet (the monotonic origin
# is unspecified, so 0.0 is not a safe "long ago").
_last_self_grab_attempt: "float | None" = None
# Y-03 grace window: a GDI grab is still allowed this long after League was
# last SEEN in the foreground. Derived, not lifted: it spans one screen-agent
# cycle (2.0s) plus margin over the self-grab stale/throttle cadence
# (1.0s / 0.5s), so one alt-tab flick or a focus hand-off at a loading screen
# does not drop a cycle, while a sustained alt-out stops shipping desktop
# frames within ~3s. tools/screen_agent.py mirrors this value (test-pinned).
_FOREGROUND_GRACE_S = 3.0
# Monotonic stamp of the last League foreground sighting; None = never seen.
_league_fg_last_seen: "float | None" = None


def _input_desktop_locked() -> bool:
    """Seam: True on a locked / secure input desktop (core.screen_grab)."""
    return input_desktop_locked()


# Foreground images whose frame is GAME CONTENT. The RC overlay (rc-shell,
# focusable while ACTIVE - rc-shell/src/main.js overlay BrowserWindow) can
# hold foreground ~20s mid-game, and its transparent frame over League is
# still the game, so it must not darken the gate. "amberstone shell.exe" is
# the packaged name (electron-builder productName "Amberstone Shell");
# "electron.exe" is included because the live overlay is launched from
# node_modules electron.exe (Desktop shortcut + rc-shell/launch_overlay.bat),
# and a stray dev Electron app is a far smaller risk than a dark vision feed.
# S134 P0 (measured live 2026-10-25): TFT now runs on its own Unreal client;
# the window that holds the game (class UnrealWindow, title "TFT", borderless
# fullscreen, display affinity 0 so a GDI BitBlt reads real pixels) belongs to
# "tftclient-win64-shipping.exe". Without it every TFT frame was refused as
# not_foreground and :8889/latest-frame served 404 for the whole match.
# tools/screen_agent.py mirrors this set (test-pinned).
_GAME_CONTENT_IMAGES = frozenset({
    "league of legends.exe", "tftclient-win64-shipping.exe",
    "amberstone shell.exe", "electron.exe"})


def _foreground_image() -> str:
    """Seam: lower-cased image name owning the foreground window, "" on error.
    Reuses the read-only probe in core.vision_profiles (image name only)."""
    try:
        from core.vision_profiles import _foreground_image_name
        return _foreground_image_name() or ""
    except Exception:  # noqa: BLE001
        return ""


def _league_foreground() -> bool:
    """Seam: True iff League OR the RC overlay owns the foreground window."""
    return _foreground_image() in _GAME_CONTENT_IMAGES


def _gdi_gate() -> "str | None":
    """Foreground gate for the GDI desktop grab. Returns ``not_foreground``
    to refuse, else None. A foreground sighting refreshes the grace window."""
    global _league_fg_last_seen
    now = time.monotonic()
    if _league_foreground():
        _league_fg_last_seen = now
        return None
    seen = _league_fg_last_seen
    if seen is not None and now - seen <= _FOREGROUND_GRACE_S:
        return None
    return "not_foreground"


def _frame_blank(img) -> bool:
    """Seam: near-uniform frame check; an error never drops a frame."""
    try:
        return frame_is_blank(img)
    except Exception:  # noqa: BLE001
        return False


def _note_capture_skip(reason: str) -> None:
    _record_capture_skip(reason)
    log.debug("frame capture skipped: %s", reason)


def last_capture_skip() -> dict:
    """The most recent Y-03 refusal: {"reason": str|None, "ts": float}."""
    with _stats_lock:
        return {"reason": _capture_skips["last_reason"],
                "ts": _capture_skips["last_ts"]}


def _maybe_obs_frame():
    """OBS occlusion-proof frame provider (ZOI plan spec O, 2026-07-05).

    Config-gated on ``obs.frame_source`` (DEFAULT OFF). When enabled, an OBS
    GetSourceScreenshot frame REPLACES the GDI self-grab: OBS Game Capture
    reads the game surface directly, so the RC overlay sitting on top never
    contaminates the frame. ANY failure (flag off, OBS down, decode error)
    returns None and the caller falls through to the untouched GDI path -
    flag off is byte-identical to prior behavior.

    Mirrors the GDI path's contract: downscales to ``_SELF_GRAB_MAX_WIDTH``
    (the documented coaching width) and returns the cache-shaped dict.

    s144 true-audit (RM-1108): only a payload PIL fully decodes is served
    (an undecodable, truncated or non-bytes one returns None, so GDI runs and
    no frame is cached from it; PIL absent counts as undecodable, and the GDI path
    needs PIL too), every decoded frame goes through the Y-03 blank check, and the
    ``"jpeg"`` label always matches the bytes - a decoded JPEG at or under the
    coaching width passes through byte-identical, anything else is re-encoded
    as JPEG.

    RM-1054: a payload Pillow cannot decode counts as ``undecodable`` and
    any other failure in the lane (the re-encode included) as ``error``, in
    ``get_stats()["obs_lane"]``; the flag off and a served frame count
    nothing, so a gated drain can tell "OBS yielded nothing" from "the OBS
    bytes were bad" (an empty OBS reply counted nothing here until
    RM-1215, below, gave it a reason).

    RM-1214: the fetch's own failures (websocket error, failed identify,
    overrun worker, unexpected exception) arrive through ``get_obs_frame``'s
    ``on_failure`` callback and are counted in the same block. RM-1215: an
    OBS reply with no frame names its reason there too (``no_reply``,
    ``source_missing``, ``request_failed``, ``bad_payload``)."""
    try:
        from core.obs_frame_source import get_obs_frame, obs_frame_source_enabled
        if not obs_frame_source_enabled():
            return None
        raw = get_obs_frame(on_failure=_note_obs_fetch_failure)
        if not raw:
            return None
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(raw))
            img.load()
        except Exception as exc:  # noqa: BLE001 - PIL absent/undecodable: fall to GDI
            _record_obs_lane_failure("undecodable")
            log.debug("obs frame undecodable, falling back to GDI: %s", exc)
            return None
        if _frame_blank(img):  # Y-03: drop a flat scene, fall to GDI
            _note_capture_skip("blank")
            return None
        if img.width > _SELF_GRAB_MAX_WIDTH or img.format != "JPEG":
            img = _downscaled(img)
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG",
                                    quality=_SELF_GRAB_JPEG_QUALITY,
                                    optimize=True)
            raw = buf.getvalue()
        b64 = _b64.b64encode(raw).decode("ascii")
        return {
            "b64":    b64,
            "size":   len(b64),
            "width":  img.width,
            "height": img.height,
            "format": "jpeg",
            "source": "obs",
        }
    except Exception as exc:  # noqa: BLE001 - never let the OBS lane break the grab
        _record_obs_lane_failure("error")
        log.debug("obs frame lane failed, falling back to GDI: %s", exc)
        return None


def _note_obs_fetch_failure(reason) -> None:
    """``get_obs_frame`` on_failure hook (RM-1214): count the fetch reason in
    ``obs_lane``; a reason outside the vocabulary counts as ``error``."""
    _record_obs_lane_failure(reason if reason in OBS_LANE_FAILURES else "error")


def _downscaled(img):
    """``img`` resized to ``_SELF_GRAB_MAX_WIDTH`` wide, keeping its aspect,
    or ``img`` itself when it is already that narrow. The height is clamped
    to at least 1: a super-wide frame (20000x1) would otherwise compute a
    zero height and make PIL raise (s144 true-audit, RM-1108)."""
    if img.width <= _SELF_GRAB_MAX_WIDTH:
        return img
    ratio = _SELF_GRAB_MAX_WIDTH / img.width
    return img.resize((_SELF_GRAB_MAX_WIDTH, max(1, int(img.height * ratio))))


# S156 S7: the capture mode of the last GDI grab - "fullscreen", "windowed"
# (cropped to the game's client area) or "screen" (no game window found: the
# whole primary screen, as before) - with the client rect when windowed.
_last_capture_window: dict = {"mode": None, "client": None, "visible": None,
                              "ts": 0.0}


def _game_window():
    """Seam: the game window (vision_server._game_window.find_game_window),
    or None. Read-only Win32; fail-soft."""
    try:
        from ._game_window import find_game_window
        return find_game_window()
    except Exception:  # noqa: BLE001
        return None


def _crop_to_game_window(img):
    """``img`` (a grab of the primary screen) cut to the game's client area
    when the game runs WINDOWED, else ``img`` unchanged.

    S156 S7: every OCR region is authored against a frame that IS the game
    surface and scaled to the frame's size (tft/cv profile, core
    vision_tesseract), so a windowed client grabbed with the whole desktop
    read nothing. The cut is the client area at the window's own size; a
    part past the screen edge is padded black so the geometry holds. A
    fullscreen client, no game window, or a grab whose size is not the
    screen the window was measured on (a DPI-virtualised grab, a stub)
    keeps the full frame. Never raises."""
    mode, client, visible = "screen", None, None
    try:
        win = _game_window()
        if isinstance(win, dict):
            from ._game_window import crop_to_plan, plan_crop
            screen = win.get("screen")
            plan = plan_crop(win.get("client"), screen)
            if plan is not None and plan["mode"] == "fullscreen":
                mode = "fullscreen"
            elif (plan is not None and screen
                    and tuple(img.size) == (screen[2] - screen[0], screen[3] - screen[1])):
                img = crop_to_plan(img, plan)
                mode, client, visible = "windowed", tuple(win["client"]), plan["visible"]
    except Exception as exc:  # noqa: BLE001 - a crop failure keeps the full frame
        log.debug("game window crop skipped: %s", exc)
    prev = _last_capture_window.get("mode")
    _last_capture_window.update({"mode": mode, "client": client,
                                 "visible": visible, "ts": time.time()})
    if mode != prev:
        log.info("frame capture mode: %s%s", mode,
                 f" client={client} visible={visible}" if client else "")
    return img


def last_capture_window() -> dict:
    """The last GDI grab's capture mode (see ``_crop_to_game_window``)."""
    return dict(_last_capture_window)


def _fetch_frame_direct():
    """One in-process screen grab. Returns the cache-shaped frame dict (with a
    base64 JPEG ``b64``) or None on any failure (PIL absent, headless session,
    grab error). A single GDI BitBlt via PIL.ImageGrab. Patchable seam for
    tests.

    Spec O (2026-07-05): when config ``obs.frame_source`` is on, the OBS
    occlusion-proof frame is tried FIRST; ANY OBS failure falls back to the
    GDI BitBlt below. Flag off (the default) short-circuits to None inside
    ``_maybe_obs_frame`` and this function behaves exactly as before.

    RM-1214: a GDI grab that was due and not refused but failed is counted
    in ``get_stats()["gdi_lane"]`` - ``unavailable`` when PIL.ImageGrab will
    not import, ``error`` when the grab, downscale or encode raised (or, since
    RM-1215, when ``ImageGrab.grab()`` returned no image). A refusal
    (``not_foreground``, ``blank``) stays a capture_skip and counts nothing
    there."""
    obs_frame = _maybe_obs_frame()
    if obs_frame is not None:
        return obs_frame
    # Y-03: the GDI grab reads the DESKTOP, so refuse it unless League holds
    # (or very recently held) the foreground - an alt-tab must not ship a
    # desktop frame to OCR / Sonnet.
    gate = _gdi_gate()
    if gate is not None:
        _note_capture_skip(gate)
        return None
    try:
        from PIL import ImageGrab
    except Exception as exc:  # noqa: BLE001
        _record_gdi_lane_failure("unavailable")
        log.debug("frame self-grab unavailable (PIL.ImageGrab): %s", exc)
        return None
    try:
        img = ImageGrab.grab()  # primary virtual screen, single GDI BitBlt
        if img is None:
            # RM-1215: Pillow documents no None return; a due, unrefused
            # grab that yields no image is a failure, not "no frame".
            _record_gdi_lane_failure("error")
            log.debug("frame self-grab returned no image")
            return None
        # S156 S7: a WINDOWED game client is cut out of the desktop so the
        # frame is the game surface the OCR regions are authored against.
        img = _crop_to_game_window(img)
        # Y-03: a near-uniform frame (black / white / flat) carries no game
        # state; drop it BEFORE it can become a calibration still.
        if _frame_blank(img):
            _note_capture_skip("blank")
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
        img = _downscaled(img)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG",
                                quality=_SELF_GRAB_JPEG_QUALITY, optimize=True)
        b64 = _b64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:  # noqa: BLE001
        _record_gdi_lane_failure("error")
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
    global _last_self_grab_attempt, _league_fg_last_seen
    with _self_grab_lock:
        _last_self_grab_attempt = None
        _league_fg_last_seen = None
    _last_capture_window.update({"mode": None, "client": None,
                                 "visible": None, "ts": 0.0})
    with _frame_lock:
        _latest_frame.update({"b64": None, "ts": 0.0, "size": 0,
                              "source": None, "width": None, "height": None,
                              "format": None, "event_meta": None})
        _frames_by_source.clear()


def _maybe_self_grab() -> dict | None:
    """If League is local and the cache is stale, grab one frame in-process
    (throttled). Returns the freshly populated frame dict or None to fall
    through to the existing cache.

    Y-03: fails closed - a locked / secure input desktop returns None with
    reason ``locked`` before any source is tried; ``not_foreground`` (GDI
    only) and ``blank`` are refused inside ``_fetch_frame_direct``."""
    global _last_self_grab_attempt
    mono = time.monotonic()
    with _self_grab_lock:
        last = _last_self_grab_attempt
        if last is not None and mono - last < _SELF_GRAB_MIN_INTERVAL_S:
            return None
        _last_self_grab_attempt = mono
    if _input_desktop_locked():
        _note_capture_skip("locked")
        return None
    grabbed = _fetch_frame_direct()
    if not isinstance(grabbed, dict) or not grabbed.get("b64"):
        return None
    now = time.time()  # the published ts is wall-clock (read cross-process)
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
        _store_source_slot(src, frame)
        return dict(_latest_frame)


# 2026-04-27 audit: cap b64 payload at ~7 MB (~5 MB decoded). Typical frames
# are ~150 KB; anything 50x that is either a 4K screenshot we don't want to
# cache or a misbehaving uploader. Without this, a stray 100 MB upload would
# OOM the server before magic-byte validation runs.
_MAX_FRAME_B64 = 7_000_000
# RM-247: same ceiling as vision_server._inference._VISION_MAX_W/_H - real
# frames are 1920x1080 or stitched 3840x1080/1280; 8K is the hard ceiling.
_MAX_FRAME_W = 7680
_MAX_FRAME_H = 4320
# s144 true-audit: every distinct ``source`` holds a full frame (up to the
# b64 cap) for the process lifetime, so the slot count is bounded; the real
# channels are a handful (league, legion-ui, phase-watcher, self_grab, obs).
_MAX_SOURCE_LEN = 128
_MAX_SOURCE_SLOTS = 32
_FRAME_FORMATS = ("jpeg", "png")


def _store_source_slot(src: str, frame: dict) -> None:
    """Write one per-source slot, evicting the least recently WRITTEN other
    slot when a new source would exceed ``_MAX_SOURCE_SLOTS``. Write order is
    the dict's insertion order (a rewrite moves the key to the end), so no
    clock is involved. Caller holds ``_frame_lock``."""
    _frames_by_source.pop(src, None)
    while len(_frames_by_source) >= _MAX_SOURCE_SLOTS:
        del _frames_by_source[next(iter(_frames_by_source))]
    _frames_by_source[src] = dict(frame)


def _claimed_dim(value) -> "int | None":
    """An uploader-claimed dimension, kept only when it is a sane int."""
    if (isinstance(value, int) and not isinstance(value, bool)
            and 0 < value <= max(_MAX_FRAME_W, _MAX_FRAME_H)):
        return value
    return None


def _frame_dims(img_b64) -> "tuple[int, int] | None":
    """(width, height) from the image HEADER, or None if unreadable.

    A decompression-bomb-class header (PIL raises DecompressionBombError at
    open for > 2x its pixel limit) is reported as an out-of-range size so it
    is refused rather than treated as unreadable.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        raw = _b64.b64decode(img_b64, validate=False)
        with Image.open(io.BytesIO(raw)) as im:
            return im.size
    except Exception as exc:  # noqa: BLE001 - unreadable header: fail open
        bomb = getattr(Image, "DecompressionBombError", None)
        if bomb is not None and isinstance(exc, bomb):
            return (_MAX_FRAME_W + 1, _MAX_FRAME_H + 1)
        return None


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
    t0 = time.monotonic()

    def _refuse(reply: dict) -> dict:
        _record("frame_upload", int((time.monotonic() - t0) * 1000), ok=False)
        return reply

    try:
        d = json.loads(body)
    except Exception as e:  # noqa: BLE001
        # RM-771 sibling: this refusal logged nothing; _relay's two upload
        # refusals already log the parser's detail. Never echoed to the client.
        log.warning("upload-frame: bad JSON body: %s: %s", type(e).__name__, e)
        return _refuse({"error": "bad_json"})
    # AUDIT 2026-08-30 (lane 8 cycle 20, sibling of the _inference fix): the
    # guard above covers only the DECODE. A body that is valid JSON but not an
    # object - `[1,2]`, `"x"`, `5` - decoded fine and then died on `.get`
    # below with AttributeError, which do_POST turned into an HTTP 500.
    if not isinstance(d, dict):
        return _refuse({"error": "bad_body"})
    img = d.get("image_b64", "")
    if not img:
        return _refuse({"error": "no image_b64"})
    # s144 true-audit: an int raised TypeError at len() (an HTTP 500); a list
    # or a non-ASCII string raised inside the fail-open magic check below and
    # was then CACHED as the frame every coach base64-decodes.
    if not isinstance(img, str) or not img.isascii():
        return _refuse({"error": "bad_image_b64"})
    if len(img) > _MAX_FRAME_B64:
        return _refuse({"error": "frame_too_large", "size": len(img),
                        "limit": _MAX_FRAME_B64})
    # 2026-04-25: Magic-byte validation. Catches a corrupt / truncated /
    # non-image payload at upload time so coaches don't get garbage at the
    # /latest-frame fetch and waste a Sonnet call analyzing it. Cost is one
    # base64 decode of the leading 16 bytes - negligible vs the ~150 KB
    # frame we're about to cache.
    magic_format = None
    try:
        head = _b64.b64decode(img[:64], validate=False)[:8]
        is_jpeg = head[:3] == b"\xff\xd8\xff"
        is_png = head[:8] == b"\x89PNG\r\n\x1a\n"
        if not (is_jpeg or is_png):
            return _refuse({"error": "not_an_image",
                            "head_hex": head.hex(),
                            "size": len(img)})
        magic_format = "jpeg" if is_jpeg else "png"
    except Exception as _exc:  # noqa: BLE001
        log.debug("frame magic check failed: %s", _exc)
        # Don't fail-closed on validation glitches - let the frame through so
        # a corner-case base64 layout doesn't blackhole real captures.
    # RM-247: dimension cap. The byte cap above bounds the WIRE, not the
    # decode - a tiny PNG can declare a huge canvas, and every coach that
    # reads /latest-frame decodes it. Header-only read (Image.open does not
    # decode pixels); an unreadable header keeps the fail-open policy above.
    dims = _frame_dims(img)
    if dims is not None:
        fw, fh = dims
        if not (0 < fw <= _MAX_FRAME_W and 0 < fh <= _MAX_FRAME_H):
            return _refuse({"error": "frame_dimensions_out_of_range",
                            "width": fw, "height": fh,
                            "limit": [_MAX_FRAME_W, _MAX_FRAME_H]})
    # s144 true-audit: a list / dict source raised TypeError on the slot dict
    # (unhashable, an HTTP 500); an int was cached under a key no ?source=
    # query (always a string) can name.
    src = d.get("source", "unknown")
    if not isinstance(src, str) or not 0 < len(src) <= _MAX_SOURCE_LEN:
        return _refuse({"error": "bad_source"})
    # bool() read the string "false" as True, so a secondary stream clobbered
    # the League frame the coaches read. Every producer sends a JSON bool.
    primary = d.get("primary", True)
    if not isinstance(primary, bool):
        return _refuse({"error": "bad_primary"})
    # Item 207: optional event_meta field tags the frame as event-
    # driven (LCU phase-watcher capture). Backward-compatible: polling
    # uploads omit the field and get a None entry. UI-audit-ritual
    # subagent can subscribe to event-tagged frames specifically.
    event_meta = d.get("event_meta")
    if event_meta is not None and not isinstance(event_meta, dict):
        event_meta = None
    # The cached metadata describes the PAYLOAD: header dims and magic-byte
    # format win over the uploader's claim; a claim is kept only when the
    # header could not be read, and only when it is sane.
    if dims is not None:
        width, height = dims
    else:
        width = _claimed_dim(d.get("width"))
        height = _claimed_dim(d.get("height"))
    fmt = magic_format
    if fmt is None:
        claimed = d.get("format", "png")
        fmt = claimed if claimed in _FRAME_FORMATS else "png"
    frame = {
        "b64":    img,
        "ts":     time.time(),
        "size":   len(img),
        "source": src,
        "width":  width,
        "height": height,
        "format": fmt,
        "primary": primary,
        "event_meta": event_meta,
    }
    with _frame_lock:
        _store_source_slot(src, frame)
        if primary:
            _latest_frame.update(frame)
    ms = int((time.monotonic() - t0) * 1000)
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
    # RM-269 / RM-1045: a future ts (backward wall-clock step) or a
    # junk one is STALE; a bare now - ts went negative and served an
    # arbitrarily old frame as current.
    if GAME_HOST in _LOCAL_HOSTS and is_stale(snap.get("ts"), _SELF_GRAB_STALE_S, now=time.time()):
        fresh = _maybe_self_grab()
        if fresh is not None:
            return fresh
    return snap
