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

S2 adds two IDEMPOTENT actions. They differ from the four above in that they
carry a real, non-repeatable operator intent, so each one requires a
client-minted `idempotency_key`:

  fire_lane     {lane, run_id, worktree, idempotency_key} - claim one of the six
                mutually exclusive headless lanes via ops/loop/lanes.py (S1).
                A lane already held by a LIVE pid is a REFUSAL, which is a
                normal answer, not an error: HTTP 200 with
                {"ok": false, "refused": "lane_held", "holder":..., "pid":...}.
                Refusing with 4xx/5xx would push the dashboard into an error
                path for what is simply "someone else is running".
  queue_intent  {intent, idempotency_key}, intent in halt_save|done_continue -
                write control/INTENT_HALT_SAVE.json or INTENT_DONE_CONTINUE.json
                atomically. halt_save ALSO raises the existing STOP flag.
                A queued intent NEVER kills anything; the running session
                notices the file and winds itself down.

Idempotency is the layer that survives a frozen UI: a disabled button does not
stop a request already in flight, nor a phone retrying over Tailscale. A repeat
key returns the ORIGINAL stored result with `"replayed": true` and performs no
second side effect. See dashboard/_idempotency.py.

This module still executes nothing - it writes files and takes a file lock.
"""
from __future__ import annotations

import importlib
import json
from dashboard._errors import send_error
import logging
import os
import sys
import time
from pathlib import Path

from dashboard import _idempotency as idem
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

ROOT = Path(__file__).resolve().parent.parent
CONTROL_DIR = ROOT / "ops" / "loop" / "control"

# Caps so a stray POST cannot write an unbounded control file.
MAX_REASON = 200
MAX_DIRECTIVE = 8000

# S1 owns this module. Imported lazily (see _lanes) so this route module stays
# importable when lanes.py is absent - the other five actions must not go down
# with it.
_LANES_MODULE = "ops.loop.lanes"

# OVERWRITE-on-write, single well-known path, no timestamp suffix (operator
# decision 2026-07-30). S2 only RECORDS it in the queued intent; S3
# (ops/loop/intents.py) is what writes the file when a session consumes.
#
# RC- prefixed because the Desktop is SHARED with the sibling repos (operator
# 2026-07-30): Sibling-A and RM run this same design and must never
# overwrite each other's hand-off when they run concurrently. The consumer
# ENFORCES the prefix rather than trusting this string - see
# ops.loop.intents.resolve_next_session_path. Pinned equal by
# tests/test_session_intents.py::test_default_next_session_path_matches_the_route.
NEXT_SESSION_PATH = "Desktop/RC-NEXT-SESSION.txt"

_INTENT_FILES = {
    "halt_save": "INTENT_HALT_SAVE.json",
    "done_continue": "INTENT_DONE_CONTINUE.json",
}

_VALID_ACTIONS = ("stop", "resume", "set_directive", "clear_directive",
                  "fire_lane", "queue_intent")

# Actions that carry a non-repeatable operator intent and therefore require an
# idempotency_key. The four legacy actions are naturally idempotent (writing the
# same STOP twice is the same world) and keep their key-free contract.
_IDEMPOTENT_ACTIONS = ("fire_lane", "queue_intent")


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


def _lanes():
    """Import ops/loop/lanes.py (S1) at CALL time, never at module import.

    Two reasons it is late-bound: this route module must stay importable if
    lanes.py is absent (the other five actions are unrelated to it), and tests
    replace this seam wholesale rather than reaching into the real lock dir.
    sys.modules is consulted first so an injected stub wins without touching the
    import machinery.
    """
    cached = sys.modules.get(_LANES_MODULE)
    if cached is not None:
        return cached
    return importlib.import_module(_LANES_MODULE)


def _fire_lane(body: dict) -> tuple[int, dict]:
    """Claim one of the six mutually exclusive headless lanes.

    Never spawns anything - it takes a lock and reports the outcome. Actually
    launching the lane arrives in a later stage.
    """
    try:
        lanes = _lanes()
    except ModuleNotFoundError as exc:
        log.warning("api/loop-control fire_lane: %s", exc)
        return 503, {"ok": False, "action": "fire_lane",
                     "error": "lane control unavailable: ops/loop/lanes.py is not installed"}

    lane = str(body.get("lane") or "").strip()
    known = tuple(getattr(lanes, "LANES", ()))
    if lane not in known:
        return 400, {"ok": False, "action": "fire_lane",
                     "error": f"unknown lane: {lane!r}", "valid": list(known)}
    for field in ("run_id", "worktree"):
        if not str(body.get(field) or "").strip():
            return 400, {"ok": False, "action": "fire_lane",
                         "error": f"fire_lane requires non-empty {field!r}"}
    run_id = str(body["run_id"]).strip()
    worktree = str(body["worktree"]).strip()

    try:
        # No `root` override: the contract's default IS ops/loop/control/lanes.
        result = lanes.try_acquire_lane(lane, run_id=run_id, worktree=worktree)
    except ValueError as exc:
        # A rejected worktree (empty, or the main tree) - operator error, 400.
        return 400, {"ok": False, "action": "fire_lane", "error": str(exc)}

    payload = {"ok": bool(result.get("ok")), "action": "fire_lane",
               "state": _state()}
    payload.update(result)
    payload["detail"] = (f"lane {lane} acquired" if payload["ok"]
                         else f"lane held by {result.get('holder')} (pid {result.get('pid')})")
    # A refusal is a normal answer - 200 with ok=false, never 4xx/5xx.
    return 200, payload


def _queue_intent(body: dict, key: str) -> tuple[int, dict]:
    """Record a halt_save / done_continue intent for the running session.

    Writes a marker file only. Queued intents NEVER kill anything - the session
    polls, finishes what it is doing, and winds itself down.
    """
    intent = str(body.get("intent") or "").strip()
    if intent not in _INTENT_FILES:
        return 400, {"ok": False, "action": "queue_intent",
                     "error": f"unknown intent: {intent!r}",
                     "valid": list(_INTENT_FILES)}
    name = _INTENT_FILES[intent]
    doc = {"intent": intent, "key": key, "ts": time.time(), "consumed": False,
           "next_session_path": NEXT_SESSION_PATH}
    _awrite(CONTROL_DIR / name, json.dumps(doc, indent=2) + "\n")
    detail = f"{intent} queued"
    if intent == "halt_save":
        # Reuse the existing halt path so a controller that only knows about
        # STOP still stands down.
        _awrite(CONTROL_DIR / "STOP", "halt_save queued from dashboard")
        detail = "halt_save queued; STOP raised"
    return 200, {"ok": True, "action": "queue_intent", "state": _state(),
                 "detail": detail, "intent": intent, "file": name, "key": key}


def _apply_idempotent(action: str, body: dict) -> tuple[int, dict]:
    """Gate an intent-carrying action on its idempotency key.

    A replay short-circuits BEFORE the side effect and returns the original
    stored payload. Only settled answers (HTTP 200 - including a lane refusal)
    are remembered; a 400/503 is not an answer to replay, it is a request that
    never happened.
    """
    key = body.get("idempotency_key")
    if not idem.is_valid_key(key):
        return 400, {"ok": False, "action": action,
                     "error": f"{action} requires 'idempotency_key' "
                              "(hex/dash, 1-64 chars)"}
    prior = idem.seen(key)
    if prior is not None:
        payload = dict(prior)
        payload["replayed"] = True
        return 200, payload

    if action == "fire_lane":
        status, payload = _fire_lane(body)
    else:
        status, payload = _queue_intent(body, key)
    if status == 200:
        idem.remember(key, payload)
    return status, payload


def apply_action(action: str, body: dict) -> tuple[int, dict]:
    """Perform the file side-effect; return (http_status, payload).

    Split from the handler so tests drive it directly against a tmp CONTROL_DIR.
    """
    if action not in _VALID_ACTIONS:
        return 400, {"ok": False, "error": f"unknown action: {action!r}",
                     "valid": list(_VALID_ACTIONS)}
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    if action in _IDEMPOTENT_ACTIONS:
        return _apply_idempotent(action, body)
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
