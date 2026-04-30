"""
gamepc_screen_agent.py — Captures Game-PC screen and pushes to Legion's vision server.

Run on Game-PC (192.168.8.237). Legion (192.168.8.230:8889) caches the latest
frame; coaches read it via /latest-frame and pass to /vision, /ocr, /coach.

Deploy on Game-PC (one time):
    1. Copy this file to C:\\RC-Agent\\gamepc_screen_agent.py
    2. Install Pillow:  py -m pip install Pillow
    3. Run:             py C:\\RC-Agent\\gamepc_screen_agent.py --monitor 0

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
    py gamepc_screen_agent.py --monitor 0 --channel game-pc-league

    # UI debug (secondary): monitor 1, NOT primary, addressable by channel
    py gamepc_screen_agent.py --monitor 1 --channel game-pc-ui --no-primary

Scheduled tasks (run as user, ONLOGON):
    schtasks /Create /TN "RC-ScreenAgent-League" /SC ONLOGON /RL HIGHEST /F ^
        /TR "py C:\\RC-Agent\\gamepc_screen_agent.py --monitor 0 --channel game-pc-league"
    schtasks /Create /TN "RC-ScreenAgent-UI" /SC ONLOGON /RL HIGHEST /F ^
        /TR "py C:\\RC-Agent\\gamepc_screen_agent.py --monitor 1 --channel game-pc-ui --no-primary"
"""
import argparse
import base64
import ctypes
import io
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from ctypes import wintypes

LEGION_URL = "http://192.168.8.230:8889/upload-frame"

# AUDIT (2026-04-22): self-contained token resolver — env var →
# local config file → hardcoded fallback. The Game-PC has no access to
# core.vision_token, so we re-implement the same order in 6 lines.
import os as _os_tok
from pathlib import Path as _Path_tok
def _resolve_auth_token() -> str:
    env = _os_tok.environ.get("RC_VISION_TOKEN")
    if env:
        return env.strip()
    cfg = _Path_tok(__file__).resolve().parent / "vision_token.txt"
    try:
        if cfg.exists():
            line = cfg.read_text(encoding="utf-8").splitlines()[0].strip()
            if line:
                return line
    except OSError:
        pass
    return "8e8f131e212b329438218eca27372dde"

AUTH_TOKEN = _resolve_auth_token()

# Capture cadence + format
INTERVAL_S     = 2.0          # base interval between captures
USE_JPEG       = True         # JPEG = 5-10x smaller than PNG; PNG = lossless
JPEG_QUALITY   = 85           # 80-90 is the sweet spot for vision
MAX_WIDTH      = None         # set e.g. 1280 to downscale; None = native
# AUDIT 2026-04-29 (gap D): default to monitor 0 instead of virtual
# desktop. The full 3840×1280 stitched capture is ~14.7 MB raw and
# Win32 BitBlt on it stalls every ~2 min under fullscreen-game
# compositor pressure (audit observed 4-5 s spikes). Monitor 0 is
# 1920×1080 = 4× smaller, no stalls. Use `--monitor` flag explicitly
# to override (or `-1` / pass --all-monitors via env to opt back into
# the old virtual-desktop behaviour).
MONITOR_INDEX  = 0            # was None; primary monitor only by default
CHANNEL        = "game-pc"    # upload `source` field; distinguishes concurrent streams
PRIMARY        = True         # False = don't update the global /latest-frame slot

# Stall-warn threshold (seconds). A single cycle slower than this gets
# a WARNING with the capture/upload breakdown so the operator can see
# whether it was the OS capture call or the network upload that stalled.
STALL_WARN_S   = 2.5

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("screen_agent")


def _enum_monitor_rects() -> list[tuple[int, int, int, int]]:
    """Return monitor rects as (left, top, right, bottom) in the order
    Windows' EnumDisplayMonitors reports them. Index 0 is conventionally
    the primary on a single-adapter system, but the OS is free to reorder
    if displays are added/removed — always check the startup enum log.
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


def capture(monitor_index: int | None = MONITOR_INDEX,
            crop: tuple[int, int, int, int] | None = None) -> tuple[str, str, int, int]:
    """Return (b64, format, width, height) for the chosen monitor.

    monitor_index:
        None → whole virtual desktop spanning all monitors
        0    → the first monitor EnumDisplayMonitors returns (usually primary)
        1..N → subsequent monitors; N must be < number of enumerated displays

    crop: optional (left, top, right, bottom) bbox in monitor-local coords
    applied AFTER the monitor grab. Used by the fast minimap stream so
    Game-PC sends a ~30KB region instead of a 200KB full frame at 5-10Hz.
    """
    from PIL import ImageGrab
    if monitor_index is None:
        img = ImageGrab.grab(all_screens=True)
    else:
        rects = _enum_monitor_rects()
        if not rects:
            log.warning("EnumDisplayMonitors returned 0 rects; falling back to primary")
            img = ImageGrab.grab()
        elif monitor_index < 0 or monitor_index >= len(rects):
            log.warning("monitor %d not present (found %d); falling back to monitor 0",
                        monitor_index, len(rects))
            img = ImageGrab.grab(bbox=rects[0], all_screens=True)
        else:
            # Grab the virtual desktop + crop to the target monitor. `all_screens`
            # is required — without it ImageGrab clips to the primary monitor's
            # rect and a negative-x / off-primary monitor returns black pixels.
            img = ImageGrab.grab(bbox=rects[monitor_index], all_screens=True)
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
        except Exception as e:
            consecutive_fail += 1
            log.warning("capture/upload failed (%dx): %s", consecutive_fail, e)
        # Backoff if Legion is unreachable; recover quickly when it returns.
        # 2026-04-27 audit: cap consecutive_fail so the exponential doesn't
        # silently park at 30s forever. After ~5 failures, log loudly so
        # the operator notices a sustained outage instead of stale frames
        # being served from the server's cache.
        if consecutive_fail == 6:
            log.critical("vision stream down for 6 consecutive uploads — Legion unreachable?")
        if consecutive_fail > 8:
            consecutive_fail = 8  # cap exponent so backoff stays at 30s ceiling
        sleep_for = interval if consecutive_fail < 3 else min(30.0, interval * (2 ** (consecutive_fail - 2)))
        elapsed = time.time() - t0
        time.sleep(max(0.0, sleep_for - elapsed))


if __name__ == "__main__":
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
