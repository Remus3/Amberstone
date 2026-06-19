# arch: POST /api/loop-control (headless-loop remote control) | section=dashboard | frozen=no
"""POST /api/loop-control - write the headless-loop control files from the dashboard.

The CONTROL complement to the read-only GET /api/loop-status (item 346). Lets the
operator halt a Gemini-directed loop, clear the halt flag, or queue a one-shot
directive override for the next cycle - all from the phone over Tailscale
(https://legion-rc:8888 -> Settings) without shelling into Legion.

Trust model: same as every other dashboard POST (/api/command, /api/input) - the
:8888 surface is local / Tailscale-tailnet only, single-operator. This route only
WRITES files under ops/loop/control/ (all gitignored runtime state); it never
executes anything itself. ops/loop/loop_controller.py polls those files:
  STOP                  present => the controller halts at its next poll (external STOP).
  directive_override.md one-shot; consume_directive_override() reads + unlinks it
                        as the NEXT cycle's directive, ahead of the gemini director.

Actions (POST JSON {"action": ...}):
  stop            write control/STOP with {reason} (default "stopped from dashboard").
  resume          unlink control/STOP (clears the halt flag; does NOT relaunch the
                  controller process - a stopped controller has already exited, so
                  this readies a fresh launch + unblocks the status view).
  set_directive   write control/directive_override.md with {text} (one-shot; the
                  controller applies it next cycle, then unlinks it).
  clear_directive unlink control/directive_override.md.

Response (HTTP 200 on a handled action; 400 on a bad / missing / empty action;
500 only on an unexpected top-level error):
  {"ok": true, "action": <str>, "state": "stopped|running|idle", "detail": <str>}
"""
from __future__ import annotations

import json
from dashboard._errors import send_error
import logging
import os
from pathlib import Path

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

ROOT = Path(__file__).resolve().parent.parent
CONTROL_DIR = ROOT / "ops" / "loop" / "control"

# Caps so a stray POST cannot write an unbounded control file.
MAX_REASON = 200
MAX_DIRECTIVE = 8000

_VALID_ACTIONS = ("stop", "resume", "set_directive", "clear_directive")


def _awrite(path: Path, text: str) -> None:
    """Atomic write (tmp + os.replace) - loop_controller polls mid-write."""
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _state() -> str:
    """Mirror routes_loop_status: stopped > running (cycle.txt present) > idle."""
    if (CONTROL_DIR / "STOP").exists():
        return "stopped"
    if (CONTROL_DIR / "cycle.txt").exists():
        return "running"
    return "idle"


def apply_action(action: str, body: dict) -> tuple[int, dict]:
    """Perform the file side-effect; return (http_status, payload).

    Split from the handler so tests drive it directly against a tmp CONTROL_DIR.
    """
    if action not in _VALID_ACTIONS:
        return 400, {"ok": False, "error": f"unknown action: {action!r}",
                     "valid": list(_VALID_ACTIONS)}
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    detail = ""
    if action == "stop":
        reason = (str(body.get("reason") or "stopped from dashboard").strip()
                  or "stopped from dashboard")[:MAX_REASON]
        _awrite(CONTROL_DIR / "STOP", reason)
        detail = reason
    elif action == "resume":
        (CONTROL_DIR / "STOP").unlink(missing_ok=True)
        detail = "STOP cleared"
    elif action == "set_directive":
        text = str(body.get("text") or "").strip()
        if not text:
            return 400, {"ok": False, "error": "set_directive requires non-empty 'text'"}
        text = text[:MAX_DIRECTIVE]
        _awrite(CONTROL_DIR / "directive_override.md", text)
        detail = f"{len(text)} chars queued"
    elif action == "clear_directive":
        (CONTROL_DIR / "directive_override.md").unlink(missing_ok=True)
        detail = "override cleared"
    return 200, {"ok": True, "action": action, "state": _state(), "detail": detail}


def _serve_loop_control(h, body) -> None:
    """POST /api/loop-control handler."""
    try:
        if not isinstance(body, dict):
            status, payload = 400, {"ok": False, "error": "expected a JSON object body"}
        else:
            action = str(body.get("action") or "").strip()
            status, payload = apply_action(action, body)
        h._send(status, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001 - last-resort guard, never 500 the server
        log.warning("api/loop-control: %s", exc)
        try:
            send_error(h, exc)
        except Exception:  # noqa: BLE001
            pass


GET_ROUTES: list = []
POST_ROUTES = [
    (equals("/api/loop-control"), _serve_loop_control),
]
