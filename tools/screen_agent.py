"""
screen_agent.py - Legion-local screen agent (self-grab source, relocated
2026-05-29). Captures the Legion screen and pushes to the vision server.

Post 1-PC consolidation (ADR-011) League runs on Legion; the in-process
vision server (127.0.0.1:8889) caches the latest frame and coaches read it
via /latest-frame, passing to /vision, /ocr, /coach.

Run (one time):
    1. Install deps:    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe -m pip install Pillow bettercam numpy comtypes
    2. Run:             $env:LOCALAPPDATA/Programs/Python/Python314/python.exe C:\\RC-Agent\\screen_agent.py --monitor 0

Capture backend: DXGI Desktop Duplication via `bettercam`, bound to the
single real GPU adapter. The legacy PIL ImageGrab(all_screens=True)
backend was retired 2026-05-16 - it BitBlt'd the whole virtual desktop
(spanning virtual display adapters) and proved unreliable across the
match-end display-mode switch. See the AUDIT note on `capture()`.

Bandwidth: ~100-300KB per frame (PNG, optimized) at 0.5 Hz default = ~150KB/s.

Tunables: INTERVAL_S, JPEG_QUALITY, USE_JPEG, MAX_WIDTH, MONITOR_INDEX.

Monitor selection (2026-04-24): `--monitor N` picks a single monitor by
0-based index (0 = primary, 1 = secondary, ...). Omit the flag to capture
the whole virtual desktop spanning all displays. The agent logs every
monitor it sees at startup so indexing is self-verifying in the deploy log.

Dual-stream (2026-04-24): the vision server accepts an optional `primary`
flag on each upload. When False, the upload lands in the per-source cache
only and does NOT update the global `/latest-frame` slot that League
vision coaches read. This lets a second agent instance stream a separate
monitor (e.g. the RC dashboard on monitor 1) without clobbering the game
frame. Fetch the secondary stream via `/latest-frame?source=<channel>`.

    # League (primary): monitor 0, primary slot (coaches read this)
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe screen_agent.py --monitor 0 --channel legion-league

    # UI debug (secondary): monitor 1, NOT primary, addressable by channel
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe screen_agent.py --monitor 1 --channel legion-ui --no-primary

Scheduled tasks (run as user, ONLOGON):
    schtasks /Create /TN "RC-ScreenAgent-League" /SC ONLOGON /RL HIGHEST /F ^
        /TR "$env:LOCALAPPDATA/Programs/Python/Python314/python.exe C:\\RC-Agent\\screen_agent.py --monitor 0 --channel legion-league"
    schtasks /Create /TN "RC-ScreenAgent-UI" /SC ONLOGON /RL HIGHEST /F ^
        /TR "$env:LOCALAPPDATA/Programs/Python/Python314/python.exe C:\\RC-Agent\\screen_agent.py --monitor 1 --channel legion-ui --no-primary"
"""
import argparse
import base64
import ctypes
import io
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from ctypes import wintypes

# Frame upload target. LOOPBACK by default (RM-150). This was a hardcoded
# 192.168.8.230, which still resolves on this box but is wrong on both counts
# post-ADR-011: both ends are the same machine, so the X-RC-Token crossed the
# LAN interface in cleartext for nothing, and a DHCP change would have killed
# the agent silently (it runs under pythonw - see the logging note in
# tools/liveclient_relay.py, whose _upload_url is the precedent this copies).
# Overridable for the same reason core/game_host.py is: host is config, not
# code.
LEGION_URL = os.environ.get(
    "RC_VISION_UPLOAD_URL", "http://127.0.0.1:8889/upload-frame")

# AUDIT (2026-04-22): self-contained token resolver - env var ->
# local config file -> hardcoded fallback. This standalone agent does not
# import core.vision_token, so we re-implement the same order in 6 lines.
import os as _os_tok
from pathlib import Path as _Path_tok
def _resolve_auth_token() -> str:
    env = _os_tok.environ.get("RC_VISION_TOKEN")
    if env:
        return env.strip()
    # RM-154: the canonical token is config/vision_token.txt (the same file
    # core.vision_token and the dashboard read). Only the tools-sibling copy
    # used to be searched, so an in-repo run resolved "" even with a valid
    # token on disk - which the new tokenless guard below would then read as
    # a genuine misconfiguration. The sibling stays first-class because the
    # deployed copy at C:\RC-Agent\ has no repo above it.
    _here = _Path_tok(__file__).resolve().parent
    for cfg in (_here.parent / "config" / "vision_token.txt",
                _here / "vision_token.txt"):
        try:
            if cfg.exists():
                line = cfg.read_text(encoding="utf-8").splitlines()[0].strip()
                if line:
                    return line
        except OSError:
            pass
    # Lane 8 audit 2026-08-03: a hardcoded 32-hex token used to be
    # returned here. It was DEAD (it did not match the live token) but
    # dashboard/routes_static.py serves this file's SOURCE at
    # /agent/screen_agent.py with no auth on a "::" bind, so the literal was
    # published to the LAN and tailnet - and a missing config silently
    # produced a WRONG token, 401ing every request with no report.
    # Return "" so the caller can fail loudly. Never reintroduce it.
    return ""

AUTH_TOKEN = _resolve_auth_token()

# Capture cadence + format
INTERVAL_S     = 2.0          # base interval between captures
USE_JPEG       = True         # JPEG = 5-10x smaller than PNG; PNG = lossless
JPEG_QUALITY   = 85           # 80-90 is the sweet spot for vision
MAX_WIDTH      = None         # set e.g. 1280 to downscale; None = native
# AUDIT 2026-04-29 (gap D): default to monitor 0 instead of virtual
# desktop. The full 3840x1280 stitched capture is ~14.7 MB raw and
# Win32 BitBlt on it stalls every ~2 min under fullscreen-game
# compositor pressure (audit observed 4-5 s spikes). Monitor 0 is
# 1920x1080 = 4x smaller, no stalls. Use `--monitor` flag explicitly
# to override (or `-1` / pass --all-monitors via env to opt back into
# the old virtual-desktop behaviour).
MONITOR_INDEX  = 0            # was None; primary monitor only by default
CHANNEL        = "legion"     # upload `source` field; distinguishes concurrent streams
PRIMARY        = True         # False = don't update the global /latest-frame slot

# Stall-warn threshold (seconds). A single cycle slower than this gets
# a WARNING with the capture/upload breakdown so the operator can see
# whether it was the OS capture call or the network upload that stalled.
STALL_WARN_S   = 2.5

# RM-154. basicConfig without handlers= installs a StreamHandler on stderr,
# and the RC-ScreenAgent-* tasks run this under pythonw.exe where stderr is
# None - so every record this module emitted, including the upload errors,
# went nowhere. Pass explicit handlers so there is a channel that survives.
# Precedent: tools/liveclient_relay.py:41-51.
_LOG_FILE = _Path_tok(__file__).resolve().parent.parent / "logs" / "screen_agent.log"
_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(_LOG_FILE), encoding="utf-8"),
    ],
)
log = logging.getLogger("screen_agent")


def _enum_monitor_rects() -> list[tuple[int, int, int, int]]:
    """Return monitor rects as (left, top, right, bottom) in the order
    Windows' EnumDisplayMonitors reports them. Index 0 is conventionally
    the primary on a single-adapter system, but the OS is free to reorder
    if displays are added/removed - always check the startup enum log.
    """
    rects: list[tuple[int, int, int, int]] = []
    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
    )

    def _cb(_hmon, _hdc, lprect, _lparam):
        r = lprect.contents
        rects.append((r.left, r.top, r.right, r.bottom))
        return 1

    ctypes.windll.user32.EnumDisplayMonitors(0, 0, MonitorEnumProc(_cb), 0)
    return rects


# --- Capture backend: DXGI Desktop Duplication via bettercam ----------------
# AUDIT 2026-05-16 (capture-stability fix). The previous backend was
# PIL ImageGrab.grab(all_screens=True): a GDI BitBlt across the entire
# VIRTUAL DESKTOP, which in the retired 2-PC topology spanned the real
# Intel Xe GPU PLUS the Parsec + secondary VIRTUAL display adapters. A
# BitBlt landing during the
# fullscreen-game -> desktop mode switch at match-end was unreliable
# against those virtual adapters. bettercam uses DXGI Desktop Duplication
# bound to the single real adapter (device 0): it never touches the
# virtual adapters, and on a display-mode change the duplication loses
# access GRACEFULLY (grab() returns None / raises a recoverable error) -
# we release and rebuild the camera next cycle instead.
_BETTERCAM: dict = {}          # output_idx -> bettercam camera (created once, reused)
_BETTERCAM_LASTIMG: dict = {}  # output_idx -> last good PIL image (static-screen fill)
_BETTERCAM_DISABLED = False    # True only if bettercam import hard-fails


def _resolve_output_idx(monitor_index: int | None) -> int:
    """Map the agent's monitor index to a DXGI output index on device 0.
    None (legacy 'virtual desktop' / all_screens) is retired - it was the
    unreliable virtual-adapter path - and maps to the primary output with
    a warning."""
    if monitor_index is None:
        log.warning("virtual-desktop capture (all_screens) retired - it was the "
                    "unreliable virtual-adapter path; using primary output 0 instead")
        return 0
    return max(0, monitor_index)


def _release_camera(output_idx: int) -> None:
    cam = _BETTERCAM.pop(output_idx, None)
    if cam is not None:
        try:
            cam.release()
        except Exception:  # noqa: BLE001
            pass


def _bettercam_image(output_idx: int):
    """Return a PIL RGB image for the DXGI output, or None on a transient
    miss. A grab failure (mode-change access-loss) releases the camera so
    the next cycle rebuilds it - this graceful loss is what replaces the
    unreliable virtual-desktop BitBlt."""
    import bettercam
    import numpy as np
    from PIL import Image
    try:
        cam = _BETTERCAM.get(output_idx)
        if cam is None:
            # device_idx=0 is the only DXGI adapter (Intel Xe); the
            # secondary virtual display adapters are intentionally unreachable.
            # output_color="BGRA" returns the raw native array - bettercam
            # skips its cv2-based colour conversion (no OpenCV dep), we
            # reorder BGRA->RGB below in numpy.
            cam = bettercam.create(device_idx=0, output_idx=output_idx,
                                   output_color="BGRA")
            _BETTERCAM[output_idx] = cam
            log.info("bettercam camera created: device=0 output=%d", output_idx)
        frame = cam.grab()  # numpy HxWx4 BGRA, or None if no new frame
        if frame is None and output_idx not in _BETTERCAM_LASTIMG:
            # Cold start on a static screen: one short retry before giving up.
            time.sleep(0.05)
            frame = cam.grab()
    except Exception as e:  # noqa: BLE001
        log.warning("bettercam grab error on output %d (%s); recreating camera",
                    output_idx, e)
        _release_camera(output_idx)
        return _BETTERCAM_LASTIMG.get(output_idx)
    if frame is None:
        # No new frame since last grab (static screen) - reuse last good so
        # the stream doesn't gap on idle. None only on a true cold miss.
        return _BETTERCAM_LASTIMG.get(output_idx)
    rgb = np.ascontiguousarray(frame[:, :, [2, 1, 0]])  # BGRA -> RGB
    img = Image.fromarray(rgb, "RGB")
    _BETTERCAM_LASTIMG[output_idx] = img
    return img


def capture(monitor_index: int | None = MONITOR_INDEX,
            crop: tuple[int, int, int, int] | None = None) -> tuple[str, str, int, int]:
    """Return (b64, format, width, height) for the chosen monitor via DXGI
    Desktop Duplication (bettercam) on the single real adapter - legacy
    virtual-desktop / virtual-adapter capture is retired (see the capture-
    stability AUDIT note above).

    monitor_index -> DXGI output index on device 0 (0 = primary game
    monitor, 1 = secondary). None maps to the primary output.

    crop: optional (left, top, right, bottom) bbox in output-local coords
    applied AFTER the grab. Used by the fast minimap stream so the agent
    sends a ~30KB region instead of a full frame.
    """
    global _BETTERCAM_DISABLED
    output_idx = _resolve_output_idx(monitor_index)
    img = None
    if not _BETTERCAM_DISABLED:
        try:
            img = _bettercam_image(output_idx)
        except ImportError as e:
            _BETTERCAM_DISABLED = True
            log.critical("bettercam unavailable (%s) - DEGRADED to primary-only "
                         "ImageGrab (NO all_screens). Reinstall bettercam to "
                         "restore the safe DXGI backend.", e)
    if img is None and _BETTERCAM_DISABLED:
        # Last-resort degraded path: primary monitor ONLY, no all_screens
        # (does not traverse the secondary virtual display adapters). Less
        # safe than DXGI but far safer than the retired virtual-desktop BitBlt.
        from PIL import ImageGrab
        img = ImageGrab.grab()
    if img is None:
        # Transient miss (cold start / mid-mode-change). Signal loop() to
        # skip this cycle; the vision server keeps serving its cached frame.
        raise RuntimeError("no frame this cycle (transient - camera rebuilding)")
    if crop is not None:
        l, t, r, b = crop
        l = max(0, min(l, img.width))
        t = max(0, min(t, img.height))
        r = max(l + 1, min(r, img.width))
        b = max(t + 1, min(b, img.height))
        img = img.crop((l, t, r, b))
    if MAX_WIDTH and img.width > MAX_WIDTH:
        ratio = MAX_WIDTH / img.width
        img = img.resize((MAX_WIDTH, int(img.height * ratio)))
    buf = io.BytesIO()
    if USE_JPEG:
        img.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY,
                                optimize=True)
        fmt = "jpeg"
    else:
        img.save(buf, format="PNG", optimize=True)
        fmt = "png"
    return (base64.b64encode(buf.getvalue()).decode("ascii"),
            fmt, img.width, img.height)


def upload(b64: str, fmt: str, w: int, h: int,
           channel: str = CHANNEL, primary: bool = PRIMARY) -> dict:
    body = json.dumps({
        "image_b64": b64, "source": channel,
        "width": w, "height": h, "format": fmt,
        "primary": primary,
    }).encode()
    req = urllib.request.Request(
        LEGION_URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "X-RC-Token": AUTH_TOKEN},
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())


def loop(interval: float, monitor_index: int | None,
         channel: str, primary: bool,
         crop: tuple[int, int, int, int] | None = None) -> None:
    rects = _enum_monitor_rects()
    label = (f"virtual-desktop ({len(rects)} monitors)" if monitor_index is None
             else f"monitor {monitor_index}/{len(rects) or '?'}")
    crop_label = f" crop={crop}" if crop else ""
    log.info("Screen agent -> %s every %.1fs (jpeg=%s q=%d) "
             "capturing %s%s channel=%s primary=%s",
             LEGION_URL, interval, USE_JPEG, JPEG_QUALITY,
             label, crop_label, channel, primary)
    if rects:
        for i, r in enumerate(rects):
            log.info("  monitor %d: %dx%d at (%d,%d)",
                     i, r[2] - r[0], r[3] - r[1], r[0], r[1])
    consecutive_fail = 0
    while True:
        t0 = time.time()
        try:
            t_capture_start = time.time()
            b64, fmt, w, h = capture(monitor_index, crop=crop)
            t_capture_done = time.time()
            r = upload(b64, fmt, w, h, channel=channel, primary=primary)
            t_done = time.time()
            cap_ms = int((t_capture_done - t_capture_start) * 1000)
            up_ms  = int((t_done - t_capture_done) * 1000)
            total_ms = cap_ms + up_ms
            # AUDIT 2026-04-29 (gap D): split capture vs upload time so
            # a stall is attributable. >2.5s in either is unusual and
            # gets logged at WARNING.
            if total_ms > STALL_WARN_S * 1000:
                log.warning("STALL %s %dx%d %dKB total=%dms (capture=%dms upload=%dms)",
                            fmt, w, h, len(b64) // 1024, total_ms, cap_ms, up_ms)
            else:
                log.info("uploaded %s %dx%d %dKB in %dms (cap %dms / up %dms) ok=%s",
                         fmt, w, h, len(b64) // 1024, total_ms, cap_ms, up_ms,
                         r.get("ok"))
            consecutive_fail = 0
        except urllib.error.URLError as e:
            consecutive_fail += 1
            log.warning("upload failed (%dx): %s", consecutive_fail, e)
        except Exception as e:  # noqa: BLE001
            consecutive_fail += 1
            log.warning("capture/upload failed (%dx): %s", consecutive_fail, e)
        # Backoff if Legion is unreachable; recover quickly when it returns.
        # 2026-04-27 audit: cap consecutive_fail so the exponential doesn't
        # silently park at 30s forever. After ~5 failures, log loudly so
        # the operator notices a sustained outage instead of stale frames
        # being served from the server's cache.
        if consecutive_fail == 6:
            log.critical("vision stream down for 6 consecutive uploads - Legion unreachable?")
        if consecutive_fail > 8:
            consecutive_fail = 8  # cap exponent so backoff stays at 30s ceiling
        sleep_for = interval if consecutive_fail < 3 else min(30.0, interval * (2 ** (consecutive_fail - 2)))
        elapsed = time.time() - t0
        time.sleep(max(0.0, sleep_for - elapsed))


if __name__ == "__main__":
    if not AUTH_TOKEN:
        # Exit non-zero so the scheduled task's Last Result is not a
        # reassuring 0 while every frame upload 401s.
        log.error("no vision token: set RC_VISION_TOKEN or create %s",
                  _Path_tok(__file__).resolve().parent.parent / "config" / "vision_token.txt")
        sys.exit(2)
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=float, default=INTERVAL_S,
                   help="seconds between captures (default %(default).1f)")
    p.add_argument("--once", action="store_true", help="single capture and exit")
    p.add_argument("--monitor", type=int, default=MONITOR_INDEX,
                   help="0-based monitor index (0=primary, 1=secondary, ...); "
                        "omit to capture the whole virtual desktop")
    p.add_argument("--channel", type=str, default=CHANNEL,
                   help="upload source field; distinguishes concurrent streams "
                        "(default %(default)s). Query via /latest-frame?source=<channel>")
    primary_grp = p.add_mutually_exclusive_group()
    primary_grp.add_argument("--primary", dest="primary", action="store_true",
                             default=PRIMARY,
                             help="update the global /latest-frame slot (default)")
    primary_grp.add_argument("--no-primary", dest="primary", action="store_false",
                             help="per-source cache only; don't touch /latest-frame")
    p.add_argument("--crop", type=str, default="",
                   help="monitor-local bbox L,T,R,B to crop after capture; "
                        "use for the fast minimap stream (e.g. 1500,750,1920,1080)")
    args = p.parse_args()
    crop_tuple = None
    if args.crop:
        try:
            parts = [int(x) for x in args.crop.split(",")]
            if len(parts) != 4:
                raise ValueError("need 4 integers")
            crop_tuple = (parts[0], parts[1], parts[2], parts[3])
        except ValueError as e:
            log.error("--crop must be L,T,R,B integers: %s", e)
            sys.exit(2)
    if args.once:
        b64, fmt, w, h = capture(args.monitor, crop=crop_tuple)
        mon_label = "all" if args.monitor is None else str(args.monitor)
        log.info("ONE-SHOT monitor=%s channel=%s primary=%s crop=%s %s %dx%d %dKB",
                 mon_label, args.channel, args.primary, crop_tuple,
                 fmt, w, h, len(b64) // 1024)
        log.info("upload result: %s",
                 upload(b64, fmt, w, h, channel=args.channel, primary=args.primary))
        sys.exit(0)
    try:
        loop(args.interval, args.monitor, args.channel, args.primary, crop=crop_tuple)
    except KeyboardInterrupt:
        log.info("Screen agent stopped.")
