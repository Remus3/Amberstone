"""
keybind_listener.py - Left Alt + 1/2/3 keybinds for decision_detector.

Runs Legion-local (1-PC, ADR-011). Hooks global keypresses (left alt+1 /
left alt+2 / left alt+3) and POSTs to Legion's /api/decisions/respond_active
so the operator can answer mid-game without alt-tabbing to the dashboard.

Left Alt + number row was chosen for tenkeyless keyboards (no numpad)
and because Alt+1..6 are NOT bound in League's default keymap - unlike
Ctrl+1..6 which would item-cast slots 1/2/3 alongside the listener fire.

ADR-007 (s169) - phase-1 ship. Optional install; the dashboard banner
buttons keep working without this. The point of the keybinds is to
preserve game focus.

Default keymap:
    Left Alt + 1   -> choice_index = 0  (decision.options[0])
    Left Alt + 2   -> choice_index = 1  (decision.options[1])
    Left Alt + 3   -> dismiss           ("skip")

Override via env vars RC_KEY_A / RC_KEY_B / RC_KEY_DISMISS (use `keyboard`
names - see https://github.com/boppreh/keyboard).

Deploy (one time):
    1. Install dependency:  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe -m pip install keyboard
    2. Copy this file to:   C:\\RC-Agent\\keybind_listener.py
    3. Run:                 $env:LOCALAPPDATA/Programs/Python/Python314/python.exe C:\\RC-Agent\\keybind_listener.py

Scheduled task (PowerShell; runs as the current user, ONLOGON - same
elevation tier as other RC-* Legion agents). RM-404: this was a caret-
continued `schtasks /Create`, and a caret does NOT continue a line in
PowerShell - it parsed as two commands with zero errors and dropped the
/TR payload. Register-ScheduledTask takes the executable and its
arguments separately. Pinned by
tests/test_scheduled_task_docstring_commands.py.

    Register-ScheduledTask -TaskName "RC-KeybindListener" -Force -RunLevel Highest `
        -Trigger (New-ScheduledTaskTrigger -AtLogOn) `
        -Action (New-ScheduledTaskAction -Execute "$env:LOCALAPPDATA/Programs/Python/Python314/python.exe" -Argument 'C:\\RC-Agent\\keybind_listener.py')

Note on permissions: the `keyboard` library hooks the Win32 low-level
keyboard event API. On Windows it works without admin for most users;
some League fullscreen modes block global hooks - start the listener
BEFORE launching League to be safe.

Rate-limit: a single 250ms debounce per key. Holding numpad1 fires
exactly one POST.

Failure mode: if Legion is unreachable, the script logs and keeps
running - no game disruption. The dashboard banner still records
choices on its own.
"""
from __future__ import annotations

import json
import logging
import os
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request

LEGION_HOST = os.environ.get("RC_LEGION_HOST", "192.168.8.230")
LEGION_PORT = int(os.environ.get("RC_LEGION_PORT", "8888"))
RESPOND_URL = f"https://{LEGION_HOST}:{LEGION_PORT}/api/decisions/respond_active"

# Default keybinds - use `keyboard` library names. Left Alt + number row
# above QWERTY (tenkeyless-friendly; collision-free with League which
# only binds Ctrl+1..6 to items, not Alt+1..6).
KEY_A = os.environ.get("RC_KEY_A", "left alt+1")
KEY_B = os.environ.get("RC_KEY_B", "left alt+2")
KEY_DISMISS = os.environ.get("RC_KEY_DISMISS", "left alt+3")

# Per-key debounce so a long press doesn't double-fire.
_DEBOUNCE_S = 0.25

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
_log = logging.getLogger("rc.keybind")

# Trust the RC dashboard's mkcert cert without per-cert verification - the
# operator's machine doesn't have legion's CA installed and the bridge is
# already mTLS-equivalent via tailnet. Mirrors the pattern in
# tools/lcu_agent.py.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_last_fire_at: dict[str, float] = {}
_fire_lock = threading.Lock()


def _post_respond(*, choice_index: int | None = None,
                  dismiss: bool = False) -> None:
    body = {"dismiss": dismiss}
    if not dismiss and choice_index is not None:
        body["choice_index"] = choice_index
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        RESPOND_URL,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=3) as r:
            payload = r.read()
        _log.info("posted choice (idx=%s dismiss=%s) -> %s",
                  choice_index, dismiss, payload.decode("utf-8")[:120])
    except urllib.error.HTTPError as exc:
        # 404 is the common case: no decision is pending. Treat as info,
        # not error - operator may have pressed early or after the
        # decision auto-expired.
        if exc.code == 404:
            _log.info("no pending decision (idx=%s dismiss=%s)",
                      choice_index, dismiss)
        else:
            _log.warning("HTTPError %s: %s", exc.code, exc.reason)
    except urllib.error.URLError as exc:
        _log.warning("URLError: %s", exc.reason)
    except Exception as exc:  # noqa: BLE001
        _log.warning("post failed: %s", exc)


def _fire(label: str, *, choice_index: int | None = None,
          dismiss: bool = False) -> None:
    now = time.monotonic()
    with _fire_lock:
        prev = _last_fire_at.get(label, 0.0)
        if now - prev < _DEBOUNCE_S:
            return
        _last_fire_at[label] = now
    # Dispatch on a background thread so the keyboard hook returns fast.
    threading.Thread(
        target=_post_respond,
        kwargs={"choice_index": choice_index, "dismiss": dismiss},
        daemon=True,
    ).start()


def main() -> int:
    try:
        import keyboard
    except ImportError:
        sys.stderr.write(
            "ERROR: `keyboard` package not installed.\n"
            "Install with:  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe -m pip install keyboard\n"
        )
        return 2

    _log.info("RC keybind listener starting")
    _log.info("  endpoint: %s", RESPOND_URL)
    _log.info("  A      = %s", KEY_A)
    _log.info("  B      = %s", KEY_B)
    _log.info("  dismiss= %s", KEY_DISMISS)
    _log.info("press Ctrl+C to exit")

    keyboard.add_hotkey(KEY_A, lambda: _fire("A", choice_index=0))
    keyboard.add_hotkey(KEY_B, lambda: _fire("B", choice_index=1))
    keyboard.add_hotkey(KEY_DISMISS, lambda: _fire("dismiss", dismiss=True))
    try:
        keyboard.wait()   # blocks forever
    except KeyboardInterrupt:
        _log.info("interrupted, exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
