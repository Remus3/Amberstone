"""hotkey_listener.py - Legion-local global hotkeys for coach decisions.

Background process that registers Ctrl+Shift+1 / Ctrl+Shift+2 / Ctrl+Shift+A as
Win32 global hotkeys (NOT a keyboard hook - uses RegisterHotKey, which is the
quiet, registered-accelerator API that doesn't trip anti-cheat watch patterns
the way `pynput`/`keyboard` low-level hooks tend to).

When a hotkey fires:
  1. The most recently created pending decision is fetched from the
     local cache (refreshed every 2 s in a worker thread).
  2. Ctrl+Shift+1 -> POST the FIRST option in `options`.
     Ctrl+Shift+2 -> POST the SECOND option.
  3. Ctrl+Shift+A -> stamp the overlay ACTIVE-toggle signal file so rc-shell
     flips the overlay interactive. This combo is owned HERE, not by the
     Electron overlay: Electron's globalShortcut does NOT deliver while League
     holds foreground focus, but this Win32 RegisterHotKey does (proven
     2026-06-27 - Ctrl+Shift+1 receipts logged in-game).
  4. If no pending decision (slots 1/2): silent no-op (no crash, no toast).

This lets the player answer a coach decision OR move the overlay without
alt-tabbing out of League. The Edge dashboard updates from its own poll loop
within a second of the POST landing, so the banner clears whether the player
glances over or not.

Deploy:
  curl.exe -sk -o C:\\RC-Agent\\hotkey_listener.py \\
      https://192.168.8.230:8888/agent/hotkey_listener.py
  Start-Process -WindowStyle Hidden py -ArgumentList "C:\\RC-Agent\\hotkey_listener.py"

Or - preferred - let the logon boot script start it at logon (it's now
in the canonical agent list).

Stops on Ctrl+C (when run interactively) or when the process is killed
via taskkill /F. No state to flush - pending decisions live on Legion.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from ctypes import wintypes

# -- Config --------------------------------------------------------------------
LEGION_BASE   = "https://192.168.8.230:8888"
DECISIONS_URL = f"{LEGION_BASE}/api/decisions"
POLL_S        = 2.0
HTTP_TIMEOUT  = 3.0

# Overlay ACTIVE-toggle signal file. Ctrl+Shift+A (id 3) stamps this with the
# current epoch time on each press; rc-shell's main process polls it and flips
# the overlay ACTIVE (rc-shell/src/main.js startActiveToggleWatch). Hardcoded
# Legion-absolute, matching the LEGION_BASE convention above + the path
# rc-shell resolves (C:\Riot Commander\ops\runtime\).
TOGGLE_SIGNAL_FILE = r"C:\Riot Commander\ops\runtime\overlay_active_toggle.txt"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("rc.hotkey")

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


# -- Decision cache ------------------------------------------------------------
class DecisionCache:
    """Thread-safe latest-pending cache. Worker refreshes; hotkey reads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: list[dict] = []
        self._last_fetch_ok = 0.0

    def topmost(self) -> dict | None:
        """Return the most recently CREATED pending decision (or None).
        Most recent = max created_at_unix; ties broken by id string."""
        with self._lock:
            if not self._pending:
                return None
            return max(self._pending, key=lambda d: (
                d.get("created_at_unix", 0), d.get("id", "")
            ))

    def refresh(self) -> None:
        try:
            req = urllib.request.Request(DECISIONS_URL)
            with urllib.request.urlopen(
                req, timeout=HTTP_TIMEOUT, context=_SSL_CTX
            ) as r:
                payload = json.loads(r.read())
        except (urllib.error.URLError, ValueError) as exc:
            log.debug("refresh: %s", exc)
            return
        items = payload.get("pending") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return
        with self._lock:
            self._pending = items
            self._last_fetch_ok = time.time()


def _refresh_loop(cache: DecisionCache, stop: threading.Event) -> None:
    while not stop.is_set():
        cache.refresh()
        stop.wait(POLL_S)


# -- POST a choice -------------------------------------------------------------
def post_choice(decision_id: str, choice: str) -> bool:
    url = f"{LEGION_BASE}/api/decisions/{decision_id}"
    body = json.dumps({"choice": choice, "note": "via hotkey"}).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(
            req, timeout=HTTP_TIMEOUT, context=_SSL_CTX
        ) as r:
            ok = (200 <= r.status < 300)
            log.info("POST %s choice=%s -> %d", decision_id, choice, r.status)
            return ok
    except urllib.error.HTTPError as exc:
        log.warning("POST %s choice=%s -> HTTP %s", decision_id, choice, exc.code)
        return False
    except Exception as exc:  # noqa: BLE001
        log.warning("POST %s choice=%s -> %s", decision_id, choice, exc)
        return False


def signal_overlay_active_toggle() -> None:
    """Stamp the toggle-signal file (atomic tmp+replace) so rc-shell flips the
    overlay ACTIVE. Fire-and-forget: a write failure must never crash the loop."""
    try:
        tmp = TOGGLE_SIGNAL_FILE + ".tmp"
        with open(tmp, "w", encoding="ascii") as f:
            f.write(f"{time.time():.3f}")
        os.replace(tmp, TOGGLE_SIGNAL_FILE)
        log.info("overlay ACTIVE toggle signaled")
    except Exception as exc:  # noqa: BLE001
        log.warning("overlay toggle signal failed: %s", exc)


def handle_hotkey(cache: DecisionCache, slot: int) -> None:
    """slot=1 -> first option; slot=2 -> second option."""
    d = cache.topmost()
    if d is None:
        log.info("hotkey slot=%d but no pending decision", slot)
        return
    options = d.get("options") or []
    if not isinstance(options, list) or len(options) < slot:
        log.info("hotkey slot=%d but decision %s has %d options",
                 slot, d.get("id"), len(options))
        return
    choice = options[slot - 1]
    post_choice(d["id"], str(choice))


# -- Win32 RegisterHotKey loop -------------------------------------------------
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_MOD_CONTROL  = 0x0002
_MOD_SHIFT    = 0x0004
_MOD_NOREPEAT = 0x4000
_VK_1         = 0x31
_VK_2         = 0x32
_VK_A         = 0x41
_WM_HOTKEY    = 0x0312
_HOTKEY_FLAGS = _MOD_CONTROL | _MOD_SHIFT | _MOD_NOREPEAT
_SLOT_OVERLAY_TOGGLE = 3


def _register(hotkey_id: int, vk: int) -> None:
    if not _user32.RegisterHotKey(None, hotkey_id, _HOTKEY_FLAGS, vk):
        raise OSError(
            f"RegisterHotKey id={hotkey_id} vk=0x{vk:02x} failed "
            f"(GetLastError={ctypes.get_last_error()}) - another process "
            f"already owns this combo?"
        )


def _unregister(hotkey_id: int) -> None:
    _user32.UnregisterHotKey(None, hotkey_id)


def message_loop(cache: DecisionCache) -> None:
    msg = wintypes.MSG()
    while True:
        rc = _user32.GetMessageA(ctypes.byref(msg), None, 0, 0)
        if rc == 0:
            break               # WM_QUIT
        if rc == -1:
            log.error("GetMessageA failed (%d)", ctypes.get_last_error())
            break
        if msg.message == _WM_HOTKEY:
            slot = int(msg.wParam)   # 1/2 = coach choice; 3 = overlay toggle
            try:
                if slot == _SLOT_OVERLAY_TOGGLE:
                    signal_overlay_active_toggle()
                else:
                    handle_hotkey(cache, slot)
            except Exception as exc:
                log.exception("hotkey handler crashed: %s", exc)
        _user32.TranslateMessage(ctypes.byref(msg))
        _user32.DispatchMessageA(ctypes.byref(msg))


def main() -> int:
    log.info("hotkey_listener starting "
             "(Ctrl+Shift+1 / Ctrl+Shift+2 / Ctrl+Shift+A)")
    cache = DecisionCache()
    stop = threading.Event()
    worker = threading.Thread(
        target=_refresh_loop, args=(cache, stop),
        daemon=True, name="hotkey-refresh",
    )
    worker.start()

    try:
        _register(1, _VK_1)
        _register(2, _VK_2)
        _register(_SLOT_OVERLAY_TOGGLE, _VK_A)  # Ctrl+Shift+A -> overlay toggle
    except OSError as exc:
        log.error("%s", exc)
        return 2

    log.info("hotkeys registered; entering message loop")
    try:
        message_loop(cache)
    except KeyboardInterrupt:
        pass
    finally:
        _unregister(1)
        _unregister(2)
        _unregister(_SLOT_OVERLAY_TOGGLE)
        stop.set()
        log.info("hotkey_listener shutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
