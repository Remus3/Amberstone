# arch: POST /api/loop-control route table - S10 Task 9 de-registered it from the :8888 dispatch table; only mc/routes.py imports it now (:8895) | section=dashboard | frozen=no
"""POST /api/loop-control - write the headless-loop control files from the dashboard.

The CONTROL complement to the read-only GET /api/loop-status (item 346). Lets the
operator halt a running headless loop, clear the halt flag, or queue a one-shot
directive override for the next cycle - all from the phone over Tailscale
(https://legion-rc:8888 -> Settings) without shelling into Legion.

Trust model (re-measured lane 8 cycle 21 - the previous wording described the
:8888 surface this route no longer sits on). mc/routes.py:16 is the ONLY
production importer, so the perimeter is Mission Control's, not the dashboard's:
mc/server.py:39 binds 127.0.0.1 + the Tailscale address ONLY (never a wildcard,
never the LAN address), mc/server.py:62-66 refuses to start without TLS, and
mc/handler.py:105-108 gates every POST on a bearer token that fails CLOSED
(mc/auth.py:48-61 - 503 when unconfigured, 401 on absent/mismatched). That is a
STRONGER perimeter than the old paragraph claimed, not a weaker one; do not
relax this route on the belief that it is only as guarded as /api/command.

This route only WRITES files under ops/loop/control/ (all gitignored runtime
state); it never executes anything itself, except `interrupt` (see S9 below).
ops/loop/loop_controller.py polls those files:
  STOP                  present => the controller halts at its next poll (external STOP).
  directive_override.md one-shot; consume_directive_override() reads + unlinks it
                        as the NEXT cycle's directive, ahead of the director.

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

S9 adds the two INTERRUPT actions - the only ones here that touch a process:

  interrupt_preview  no body, no key. NAMES every process an interrupt would
                     kill (lane lock holder, controller lock holder, and their
                     descendants) plus a `fingerprint` pinning that exact set.
                     Read-only, so it is deliberately NOT idempotency-keyed:
                     remembering a preview would freeze one stale victim list
                     into every subsequent arm.
  interrupt          {fingerprint, idempotency_key}. Kills the previewed
                     victims and only those. The fingerprint is re-probed, not
                     trusted, so a set that changed between the preview and the
                     confirm is a 200 refusal (`victims_changed`) carrying the
                     FRESH list - never a kill of processes the operator did
                     not see. A missing fingerprint is a 400: no preview means
                     nothing was ever named.

The guidance action (`steer`) still rejects tier "interrupt" with a 400. That
is not an oversight - the plan requires the act never be downgraded to a note,
and there is deliberately no path through this route that does so.

Everything except `interrupt` writes files and takes file locks; `interrupt`
is the single exception and carries the arm-then-confirm plus fingerprint
machinery because of it.
"""
from __future__ import annotations

import importlib
import json
import logging
import sys
import time
from pathlib import Path

from core.polled_json import atomic_write_bytes
from dashboard import _idempotency as idem
from dashboard._errors import send_error
from dashboard._matchers import equals

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

# S5 owns the launcher. Same late-bind, same reason: a missing launcher must not
# take the other five actions down with it.
_LAUNCHER_MODULE = "ops.loop.lane_launcher"

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
NEXT_SESSION_PATH = "RC-NEXT-SESSION.txt"

_INTENT_FILES = {
    "halt_save": "INTENT_HALT_SAVE.json",
    "done_continue": "INTENT_DONE_CONTINUE.json",
}

_VALID_ACTIONS = ("stop", "resume", "set_directive", "clear_directive",
                  "fire_lane", "queue_intent", "steer",
                  "interrupt_preview", "interrupt")

# S7 owns the steer channel. Late-bound for the same reason as the other two.
_STEER_MODULE = "ops.loop.steer"

# S9 owns the INTERRUPT tier - the only action here that kills a process.
_INTERRUPT_MODULE = "ops.loop.interrupt"

# Actions that carry a non-repeatable operator intent and therefore require an
# idempotency_key. The four legacy actions are naturally idempotent (writing the
# same STOP twice is the same world) and keep their key-free contract.
#
# `interrupt_preview` is deliberately NOT here. It is a read: it takes no lock,
# writes nothing and kills nothing, so there is nothing to replay - and
# remembering it would be actively harmful, freezing one stale victim list into
# every subsequent arm. `interrupt` itself is the most important entry in the
# list, because a phone retrying over Tailscale must not kill twice.
_IDEMPOTENT_ACTIONS = ("fire_lane", "queue_intent", "steer", "interrupt")

# How long a duplicate request waits for the in-flight original to settle.
#
# SHORT ON PURPOSE, and the first version of this comment had the reasoning
# backwards. It claimed the guarded side effects were "a lane launch and a
# taskkill - none of them slow" and set a 10 s ceiling meant to outlast them.
# Both halves were wrong. ops/loop/interrupt.py:297-298 kills victims SERIALLY
# and :235-236 gives each taskkill `timeout=20`, so an interrupt over N victims
# runs to 20N seconds; _fire_lane -> launch_lane -> ensure_worktree
# (ops/loop/lane_launcher.py:185-191) shells out to `git worktree add` on a
# lane's first fire. No wait this route can afford outlasts either, so a
# ceiling sized to try is a ceiling that expires DURING normal operation and
# then reports a false failure.
#
# The wait therefore does the only job it can do honestly: absorb a transport
# level re-send of the SAME request, which arrives in milliseconds. Anything
# longer is answered as an explicit refusal instead. That also keeps the pin on
# a ThreadingHTTPServer worker brief - and the pin is real, because mc/handler.py
# (the only production importer of this route, see the arch line above) sets no
# Handler.timeout at all.
INFLIGHT_WAIT_S = 2.0


def _awrite(path: Path, text: str) -> None:
    """Atomic write - and the contention here is ROUTINE, not theoretical.

    STOP is read from three separate poll loops: loop_controller.py:772/786
    every 5 s (ops/loop/config.json poll_sec), claude_gui_bridge.ahk:299 every
    1 s, and routes_loop_status.py:450 read_text() on every browser poll of
    GET /api/loop-status. On Windows a reader holding the destination open
    share-locks it, so a bare os.replace raises PermissionError (WinError 5) -
    measured, and already recorded in-tree at dashboard/_writers.py:29-36.

    This used to hand-roll `tmp.write_text` + a bare `os.replace`, which meant
    the operator's emergency `stop` lost a coin-flip against the poller: the
    PermissionError escaped apply_action, hit the catch-all in
    _serve_loop_control, and returned HTTP 500 "internal error - see logs"
    while the loop kept running. It also stranded STOP.tmp.

    Bytes, not text: Path.write_text rewrites LF as CRLF on Windows, so the
    `N chars queued` detail disagreed with the file and MAX_DIRECTIVE was not
    a byte cap (reference_windows_write_text_crlf_byte_count).
    """
    try:
        atomic_write_bytes(path, text.encode("utf-8"))
    except PermissionError:
        # The bounded backoff (~275 ms) is sized for the routine case, a reader
        # that holds the file for a few ms. If it still loses, the caller
        # renders an actionable 503 - "internal error - see logs" tells the
        # operator nothing about a halt that did not land.
        #
        # LANE 8 CYCLE 24: the scratch file is no longer cleaned up here.
        # atomic_write_bytes now removes its own scratch file on every failure
        # path (core/polled_json._write_then_replace), and the name it uses is
        # per-writer, so this mirror of the old shared "<dest>.tmp" name would
        # be a silent no-op rather than the cleanup it looks like.
        raise


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


def _launcher():
    """Import ops/loop/lane_launcher.py (S5) at CALL time. See _lanes."""
    cached = sys.modules.get(_LAUNCHER_MODULE)
    if cached is not None:
        return cached
    return importlib.import_module(_LAUNCHER_MODULE)


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
    if not str(body.get("run_id") or "").strip():
        return 400, {"ok": False, "action": "fire_lane",
                     "error": "fire_lane requires non-empty 'run_id'"}
    run_id = str(body["run_id"]).strip()

    # `worktree` stays MANDATORY at the lock (a lane may never run against the
    # main tree), but the dashboard must not have to know filesystem layout, so
    # an omitted worktree is filled from the launcher's own answer rather than
    # rejected. An explicitly-supplied one still wins - that is the path a
    # script or a test uses.
    worktree = str(body.get("worktree") or "").strip()
    if not worktree:
        try:
            worktree = str(_launcher().worktree_path(lane))
        except Exception as exc:  # noqa: BLE001 - fall through to the 400 below
            log.warning("api/loop-control fire_lane: no default worktree: %s", exc)
    if not worktree:
        return 400, {"ok": False, "action": "fire_lane",
                     "error": "fire_lane requires non-empty 'worktree'"}

    try:
        # No `root` override: the contract's default IS ops/loop/control/lanes.
        result = lanes.try_acquire_lane(lane, run_id=run_id, worktree=worktree)
    except ValueError as exc:
        # A rejected worktree (empty, or the main tree) - operator error, 400.
        return 400, {"ok": False, "action": "fire_lane", "error": str(exc)}

    payload = {"ok": bool(result.get("ok")), "action": "fire_lane",
               "state": _state()}
    payload.update(result)
    if not payload["ok"]:
        payload["detail"] = (
            f"lane held by {result.get('holder')} (pid {result.get('pid')})")
        # A refusal is a normal answer - 200 with ok=false, never 4xx/5xx.
        return 200, payload

    # S5: the claim is only half the act. Launch the worker, and hand the lane
    # back if anything in the spawn path fails - a lock with no process behind
    # it wedges the lane until someone reclaims it by hand.
    try:
        launcher = _launcher()
    except ModuleNotFoundError as exc:
        lanes.release_lane(result.get("token"))
        log.warning("api/loop-control fire_lane: launcher missing: %s", exc)
        return 503, {"ok": False, "action": "fire_lane",
                     "error": "lane launcher unavailable: "
                              "ops/loop/lane_launcher.py is not installed"}
    try:
        run = launcher.launch_lane(lane, run_id=run_id,
                                   token=result.get("token"))
    except Exception as exc:  # noqa: BLE001 - launch_lane already released the lane
        log.warning("api/loop-control fire_lane: launch failed: %s", exc)
        # 503, NOT 200: only settled answers are remembered by the idempotency
        # table, and remembering a launch fault would replay it forever.
        return 503, {"ok": False, "action": "fire_lane",
                     "error": f"launch failed: {exc}", "released": True}

    payload.update(run)
    payload["detail"] = f"lane {lane} running (pid {run['pid']})"
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


def _steer(body: dict, key: str) -> tuple[int, dict]:
    """Append one free-text steer for the running session to pick up.

    GUIDANCE, NOT A COMMAND. Nothing here executes anything and nothing is
    signalled or killed - the consumer reads the text at its own boundary and
    decides. That is what makes NOTE and STEER safe to fire on a single click;
    the arm-then-confirm window exists for acts that cannot be taken back, and
    INTERRUPT (stage S9) is the one that will need it.

    Idempotency-keyed like the other intent-carrying actions: a phone retrying
    over Tailscale must not append the same steer twice.
    """
    try:
        steer = sys.modules.get(_STEER_MODULE) or \
            importlib.import_module(_STEER_MODULE)
    except ModuleNotFoundError as exc:
        log.warning("api/loop-control steer: %s", exc)
        return 503, {"ok": False, "action": "steer",
                     "error": "steer channel unavailable: "
                              "ops/loop/steer.py is not installed"}
    tier = str(body.get("tier") or "note").strip().lower()
    if tier not in getattr(steer, "TIERS", ("note", "steer")):
        return 400, {"ok": False, "action": "steer",
                     "error": f"unknown tier: {tier!r}",
                     "valid": list(getattr(steer, "TIERS", ()))}
    try:
        rec = steer.append(body.get("text"), tier=tier, key=key)
    except ValueError as exc:
        return 400, {"ok": False, "action": "steer", "error": str(exc)}
    except OSError as exc:
        log.warning("api/loop-control steer: %s", exc)
        return 503, {"ok": False, "action": "steer", "error": str(exc)}
    except RuntimeError as exc:
        # ops/loop/steer.py:146 serializes the append on a Win32 named mutex and
        # raises winmutex.MutexTimeout (a RuntimeError, NOT an OSError) after
        # 5 s. Only ValueError/OSError were caught, so losing the lock race
        # returned a 500 "internal error" for what is simply "busy, retry".
        #
        # Narrowed to that ONE class on purpose: catching RuntimeError whole
        # would report a genuine bug inside steer.append to the operator as
        # "busy - retry", which is the worst of both worlds - the fault is
        # hidden AND the suggested remedy does not work. Matched by NAME rather
        # than imported, because ops.loop.winmutex is late-bound like every
        # other ops.loop dependency here (and is byte-identical-by-contract
        # with the sibling repo, so this module must not take a hard import on
        # it). Anything else re-raises to the generic guard.
        if type(exc).__name__ != "MutexTimeout":
            raise
        log.warning("api/loop-control steer: lock contention: %s", exc)
        return 503, {"ok": False, "action": "steer",
                     "error": "steer channel busy - retry"}
    return 200, {"ok": True, "action": "steer", "state": _state(),
                 "detail": f"{tier} queued (#{rec['id']})",
                 "tier": tier, "id": rec["id"], "key": key}


def _interrupt():
    """Import ops/loop/interrupt.py (S9) at CALL time. See _lanes."""
    cached = sys.modules.get(_INTERRUPT_MODULE)
    if cached is not None:
        return cached
    return importlib.import_module(_INTERRUPT_MODULE)


def _interrupt_preview() -> tuple[int, dict]:
    """Name the processes an interrupt would kill. Kills nothing, writes nothing.

    This is the half that makes the tier honest: the plan requires the button
    to NAME the agents before the confirm, and this is where the names come
    from. It also hands back the fingerprint that pins this exact answer, which
    the confirm must carry so a set that moved in between is refused rather
    than killed blind.
    """
    try:
        mod_i = _interrupt()
    except ModuleNotFoundError as exc:
        log.warning("api/loop-control interrupt_preview: %s", exc)
        return 503, {"ok": False, "action": "interrupt_preview",
                     "error": "interrupt unavailable: "
                              "ops/loop/interrupt.py is not installed"}
    try:
        out = dict(mod_i.preview())
    except Exception as exc:  # noqa: BLE001 - a probe fault must not 500
        log.warning("api/loop-control interrupt_preview: %s", exc)
        return 503, {"ok": False, "action": "interrupt_preview",
                     "error": f"preview failed: {exc}"}
    out["action"] = "interrupt_preview"
    out["state"] = _state()
    return 200, out


def _do_interrupt(body: dict, key: str) -> tuple[int, dict]:
    """Kill the previewed victims - and ONLY those.

    `fingerprint` is mandatory and unforgeable in the sense that matters: the
    module re-probes and compares rather than trusting it, so a client that
    invents one gets a `victims_changed` refusal instead of a kill. Its absence
    means no preview was ever shown, which means nothing was ever named - a 400
    rather than a kill of whatever happens to be running.
    """
    fp = str(body.get("fingerprint") or "").strip()
    if not fp:
        return 400, {"ok": False, "action": "interrupt",
                     "error": "interrupt requires 'fingerprint' from "
                              "interrupt_preview - a confirm may only kill "
                              "what a preview named"}
    try:
        mod_i = _interrupt()
    except ModuleNotFoundError as exc:
        log.warning("api/loop-control interrupt: %s", exc)
        return 503, {"ok": False, "action": "interrupt",
                     "error": "interrupt unavailable: "
                              "ops/loop/interrupt.py is not installed"}
    try:
        out = dict(mod_i.execute(fp, key=key))
    except Exception as exc:  # noqa: BLE001 - never 500 the server on a kill path
        log.warning("api/loop-control interrupt: %s", exc)
        # 503, not 200: only settled answers are remembered, and remembering a
        # fault would replay it forever against a machine that has moved on.
        return 503, {"ok": False, "action": "interrupt",
                     "error": f"interrupt failed: {exc}"}
    out["action"] = "interrupt"
    out["state"] = _state()
    out["key"] = key
    if out.get("refused"):
        out["detail"] = f"refused: {out['refused']}"
    else:
        out["detail"] = f"killed {len(out.get('killed') or [])} process(es)"
    # A refusal is a normal answer - 200 with ok=false, same as a held lane.
    return 200, out


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

    deadline = time.monotonic() + INFLIGHT_WAIT_S
    while True:
        state, value = idem.claim(key)
        if state == "hit":
            payload = dict(value)
            payload["replayed"] = True
            return 200, payload
        if state == "claimed":
            break
        # Another thread owns this key and is mid-side-effect. Wait for its
        # answer rather than acting: seen() alone let both threads through,
        # which is how a retrying phone got two kills out of one intent.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            # 200 + ok=false, NOT 503: web/mc/mc.js:51-53 maps EVERY 503 to
            # "auth not configured on the server" and returns before r.json(),
            # so a 503 would report a false cause and discard this payload
            # (filed as RM-283).
            #
            # `refused` is REQUIRED, not decoration. Each panel has its own
            # renderer and only _mcFire (mc.js:161, queue_intent) treats a bare
            # ok=false as a refusal; _mcFireLane (mc.js:221) and _mcIrqFire
            # (mc.js:363) branch on `refused` and otherwise fall through to
            # "<label> failed:", which would report a still-running interrupt
            # as a FAILED one.
            #
            # The text must not invite an immediate retry either. Every client
            # mints a fresh key per send (mc.js:717 "one key per SEND"), so a
            # re-send is a NEW key that this gate cannot dedupe - it would run
            # the side effect a second time alongside the first. Telling the
            # operator to wait is the only advice that does not manufacture the
            # double-fire this whole protocol exists to prevent.
            return 200, {"ok": False, "action": action, "in_flight": True,
                         "refused": "in_flight",
                         "detail": "the original request is still running - "
                                   "wait for it to finish, do not re-send",
                         "error": "an identical request is still running"}
        value.wait(remaining)

    # The claim is released on EVERY path, including one where settle() itself
    # raises. Covering only the side effect leaves a real hole: settle ->
    # remember -> _remember_locked deep-copies the payload BEFORE releasing, so
    # a payload that cannot be copied dies with the key still reserved and
    # nothing to wake its waiters - permanently, since _INFLIGHT has no TTL and
    # purge() does not touch it. Every later request on that key would then
    # block and be refused until the process restarts, which is a worse outage
    # than the double-fire this protocol removes.
    settled = False
    try:
        if action == "fire_lane":
            status, payload = _fire_lane(body)
        elif action == "steer":
            status, payload = _steer(body, key)
        elif action == "interrupt":
            status, payload = _do_interrupt(body, key)
        else:
            status, payload = _queue_intent(body, key)
        if status == 200:
            idem.settle(key, payload)
        else:
            # A 400/503 is not an answer to replay - it is a request that never
            # happened - so the key is released WITHOUT being remembered and the
            # next caller is free to act.
            idem.abandon(key)
        settled = True
    finally:
        if not settled:
            idem.abandon(key)
    return status, payload


def apply_action(action: str, body: dict) -> tuple[int, dict]:
    """Perform the file side-effect; return (http_status, payload).

    Split from the handler so tests drive it directly against a tmp CONTROL_DIR.
    """
    if action not in _VALID_ACTIONS:
        return 400, {"ok": False, "error": f"unknown action: {action!r}",
                     "valid": list(_VALID_ACTIONS)}
    if action == "interrupt_preview":
        # BEFORE the mkdir: this action is documented read-only ("Kills
        # nothing, writes nothing") and must not create control/ as a side
        # effect. _state() only calls .exists(), which is safe on a missing dir.
        return _interrupt_preview()
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
    except PermissionError as exc:
        # A control file stayed share-locked past the retry window. This is a
        # known, transient, RETRYABLE condition, so it gets its own actionable
        # answer rather than the generic 500 - the operator has to be able to
        # tell "your halt did not land, press it again" from "the server is
        # broken". CLAUDE.md Error Handling: friendly message out, raw cause
        # to logs.
        log.warning("api/loop-control: control file busy: %s", exc)
        try:
            send_error(h, exc, status=503,
                       public_msg="control file busy - the loop is mid-poll, retry")
        except Exception:  # noqa: BLE001
            pass
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
