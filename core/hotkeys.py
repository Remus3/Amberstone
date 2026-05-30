"""
core/hotkeys.py  - Global hotkey listener for Riot Commander
Ctrl+Tab → triggers forced vision scan in all active non-TFT coaches.
Runs as a daemon thread; safe to import from any module.
"""
import logging
import threading
import time
from pathlib import Path

_log = logging.getLogger("rc.hotkeys")
_APP_DIR = Path(__file__).parent.parent

# ── State ────────────────────────────────────────────────────────────────────
_coaches: list = []       # registered coach objects (have set_force_scan / set_scanning)
_running = False
_thread: threading.Thread | None = None

CTRL_TAB_COOLDOWN = 3.0   # seconds between consecutive force scans


def register_coach(coach: object) -> None:
    """Register a coach for forced-scan triggering. Call from app.py when coach starts."""
    global _coaches
    if coach not in _coaches:
        _coaches.append(coach)


def unregister_coach(coach: object) -> None:
    global _coaches
    _coaches = [c for c in _coaches if c is not coach]


def start() -> None:
    """Start the hotkey listener thread."""
    global _running, _thread
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_listen_loop, daemon=True, name="HotkeyListener")
    _thread.start()
    _log.info("Hotkey listener started  [Ctrl+Tab = Force Scan]")


def stop() -> None:
    global _running
    _running = False


# ── Listener ─────────────────────────────────────────────────────────────────
def _listen_loop() -> None:
    """
    Uses Win32 GetAsyncKeyState to detect Ctrl+Tab without requiring
    keyboard/pynput installs and without blocking the target application.

    Inner try/except with auto-restart: a single GetAsyncKeyState glitch
    (driver hiccup, low-memory blip) used to silently kill the listener
    forever - Ctrl+Tab would stop working with no signal. Now we log,
    sleep briefly, and resume the loop instead of exiting.
    """
    import ctypes
    VK_CONTROL = 0x11
    VK_TAB     = 0x09
    last_fire  = 0.0
    was_down   = False
    crash_count = 0

    while _running:
        try:
            _gaks = ctypes.windll.user32.GetAsyncKeyState
            ctrl_down = bool(_gaks(VK_CONTROL) & 0x8000)
            tab_down  = bool(_gaks(VK_TAB)     & 0x8000)
            combo     = ctrl_down and tab_down

            if combo and not was_down:
                now = time.monotonic()
                if now - last_fire > CTRL_TAB_COOLDOWN:
                    last_fire = now
                    _trigger_force_scan()

            was_down = combo
            time.sleep(0.05)   # 50ms poll - low CPU, responsive enough
        except Exception as e:
            crash_count += 1
            # Exponential backoff (cap at 5s) so a permanent fault doesn't
            # spin a tight error loop, but a transient blip recovers fast.
            sleep_for = min(5.0, 0.1 * (2 ** min(crash_count, 6)))
            _log.warning("Hotkey listener glitch %dx: %s - resuming in %.1fs",
                         crash_count, e, sleep_for)
            time.sleep(sleep_for)


def _trigger_force_scan() -> None:
    """Signal all registered coaches to run an immediate forced vision scan."""
    _log.info("Ctrl+Tab: forced scan triggered")

    # Write force-scan marker file (coaches poll this)
    try:
        ts_file = _APP_DIR / "data" / "force_scan.json"
        import json
        import time as _t
        ts_file.write_text(json.dumps({"force": _t.time()}), encoding="utf-8")
    except Exception:
        pass

    # Direct signal to each registered coach's AI status bar
    for coach in list(_coaches):
        try:
            # Signal the AI status bar if it exists
            ai_bar = getattr(coach, "_overlay", {}).get("ai_bar")
            if ai_bar and hasattr(ai_bar, "set_force_scan"):
                ai_bar.set_force_scan()
            # Reset vision timer to force immediate scan on next loop iteration
            if hasattr(coach, "_last_vision"):
                coach._last_vision = 0.0
        except Exception as e:
            _log.debug("Force scan signal to coach: %s", e)
