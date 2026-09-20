# arch: server-side arm-then-confirm gate for irreversible loop-control acts | section=dashboard | frozen=no
"""One irreversible act equals one ARM plus one CONFIRM.

WHY THIS IS SERVER SIDE. The original arm-then-confirm lived in
`web/mc/arm_confirm.js:45`, a browser module wired at `web/mc/mc.js:133`. That
made the guard a property of ONE CLIENT: curl, a script, a second tab or a
wedged phone reached `interrupt` - a taskkill over a named victim set - in a
single HTTP call, because a browser module cannot defend a route it does not
sit in front of. Retiring the Mission Control web UI would have deleted the
guard silently while every control endpoint stayed live. Deleting a client
cannot make a server safer, so the state machine moved here.

WHAT IS GATED, AND WHY ONLY THREE ACTIONS. The gated set is exactly the set the
UI armed, derived from the client rather than invented here:
`web/mc/mc.js:285` armed a lane (fire_lane), `:483` armed a shortcut
(queue_intent), `:338` armed the interrupt. `stop`, `resume`, `set_directive`
and `clear_directive` were one-click in the UI (`web/mc/mc.js:665,668,800,802`)
because each is reversible by its own opposite. `steer` is one-click by an
explicit in-tree finding - "GUIDANCE, NOT A COMMAND ... nothing here executes
anything and nothing is signalled or killed"
(`dashboard/routes_loop_control.py:353-357`). `interrupt_preview` kills nothing
and writes nothing (`dashboard/routes_loop_control.py:415`), and gating it
would make the fingerprint unobtainable without an arm, which would break the
very confirm this module protects.

WHAT CHANGED FROM THE JS, STATED RATHER THAN GLOSSED. The browser controller
held a SINGLE armed slot, so arming a second button disarmed the first
(`web/mc/arm_confirm.js:89-100`). That was a rendering affordance: two lit
buttons on one screen are an operator trap. It is NOT the safety property, and
reproducing it here would be actively wrong, because the server is a
ThreadingHTTPServer and two concurrent requests are not two confused clicks.
This module keeps a BOUNDED TABLE of tokens instead, and recovers the safety
half a different way: a token is BOUND to one action and one target, so a token
armed for lane `ds` cannot fire lane `repo` and a token armed for `fire_lane`
cannot fire `interrupt`. That binding is strictly stronger than the single slot
it replaces.

THE WINDOW IS LONGER THAN THE UI'S 3 SECONDS, ON PURPOSE. `ARM_WINDOW_MS` was
3000 in the browser because the second step was a second CLICK. Here the second
step is a second REQUEST an operator has to compose, so a 3 s window would make
the gate unusable and unusable guards get bypassed. The window's job is to
bound how long an unattended arm sits live, not to race a human's reflexes.
Override with `RC_MC_ARM_WINDOW_S` for a tighter or looser perimeter.

THE SEAM WITH IDEMPOTENCY (`dashboard/routes_loop_control.py:482-565`). These
two gates answer DIFFERENT questions and must not be collapsed:

  * the arm gate asks "did a human mean this ONCE?" - it refuses an unmeant act;
  * the idempotency table asks "is this the SAME meant act arriving twice?" -
    it replays the first answer rather than acting again.

So a token is CONSUMED on the confirm but RETAINED, with the key it ran under,
for `CONSUMED_RETAIN_S`. A transport-level re-send of the same confirm then
still resolves - to the SAME key - and the idempotency table replays the stored
answer. A re-send carrying a DIFFERENT key is a second intent wearing a spent
arm, and is refused. Without the retain window a benign TCP retry would read as
`bad_token`, which is a confusing refusal in the exact situation both gates
exist to make boring.

Deliberately in-process and non-durable, for the same reason
`dashboard/_idempotency.py:12-15` gives: an arm is a single operator's intent
over seconds, on a single-operator local surface. A restart clearing the table
is CORRECT - it fails CLOSED, since a lost arm refuses rather than fires.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, NamedTuple, Optional

from dashboard._idempotency import is_valid_key

# The three irreversible actions. See the module docstring for the derivation
# and for why the other five loop-control actions are not here.
GATED_ACTIONS = ("fire_lane", "queue_intent", "interrupt")

# Route-layer actions this module owns. They never reach
# routes_loop_control.apply_action, which is the side-effect layer.
ROUTE_ACTIONS = ("arm", "disarm")


def _window_from_env() -> float:
    raw = os.environ.get("RC_MC_ARM_WINDOW_S", "").strip()
    if not raw:
        return 60.0
    try:
        val = float(raw)
    except ValueError:
        return 60.0
    # A non-positive window would arm and expire in the same instant, which is
    # a gate that refuses everything - fail to the documented default instead
    # of to a surface that looks armed and never fires.
    return val if val > 0 else 60.0


ARM_WINDOW_S = _window_from_env()

# How long a CONSUMED token still resolves, so a transport retry replays rather
# than reading as a forged token. Matched to _idempotency.DEFAULT_TTL_S: past
# that point the replay table has forgotten the answer anyway, so resolving the
# token would buy nothing and would re-run the side effect.
CONSUMED_RETAIN_S = 900.0

# Both tables are keyed by values this module mints, not by client input, so
# they cannot be grown by a hostile body. The caps bound an ARM STORM instead -
# a client that arms in a loop and never confirms - and eviction is FIFO by
# insertion, oldest first, exactly like _idempotency.MAX_ENTRIES.
MAX_ARMED = 64
MAX_CONSUMED = 64

_LOCK = threading.RLock()
# token -> {action, target, key, expires_at}
_ARMED: "OrderedDict[str, dict]" = OrderedDict()
# token -> {action, target, key, consumed_at}
_CONSUMED: "OrderedDict[str, dict]" = OrderedDict()


class Verdict(NamedTuple):
    """The gate's answer. `key` is the idempotency key the confirm runs under."""

    ok: bool
    reason: Optional[str]
    key: Optional[str]


# Refusal reasons, kept as constants so the route and the tests cannot drift
# from each other on a string literal.
ARM_REQUIRED = "arm_required"
BAD_TOKEN = "bad_token"
OTHER_ARMED = "other_armed"
EXPIRED = "expired"
CONSUMED = "consumed"

_REASON_DETAIL = {
    ARM_REQUIRED: ("this action is irreversible and needs a two-step: POST "
                   "{\"action\": \"arm\", \"target_action\": ...} first, then "
                   "re-send this body with the arm_token it returns"),
    BAD_TOKEN: "no such arm - it was never issued, was disarmed, or has aged out",
    OTHER_ARMED: "that arm_token was issued for a different action or target",
    EXPIRED: "the arm window closed - arm again",
    CONSUMED: ("that arm was already spent by a different request - one arm is "
               "one intent, so arm again"),
}


def _now() -> float:
    """Wall clock, isolated so tests can drive expiry without sleeping."""
    return time.time()


def _mint() -> str:
    return str(uuid.uuid4())


def target_of(action: str, body: dict) -> str:
    """The sub-identity an arm is bound to, mirroring the UI's armed id.

    `web/mc/mc.js` armed a lane by its lane name (`:255`), a shortcut by its
    intent id (`:467`) and the interrupt by the constant `_MC_IRQ_ID` (`:304`).
    A missing field returns "" rather than raising: the action-level 400 in
    routes_loop_control is what reports a malformed body, and an arm that
    refused first would mask it.
    """
    if not isinstance(body, dict):
        return ""
    if action == "fire_lane":
        return str(body.get("lane") or "").strip()
    if action == "queue_intent":
        return str(body.get("intent") or "").strip()
    if action == "interrupt":
        # The victim set is pinned by the fingerprint, which the module
        # re-probes and compares (ops/loop/interrupt.py execute), so the arm
        # binds the ACTION and lets the fingerprint bind the targets.
        return "interrupt"
    return ""


def _sweep_locked(now: float) -> None:
    for token, rec in list(_ARMED.items()):
        if now >= rec["expires_at"]:
            del _ARMED[token]
    for token, rec in list(_CONSUMED.items()):
        if (now - rec["consumed_at"]) > CONSUMED_RETAIN_S:
            del _CONSUMED[token]


def arm(action: str, target: str, key: Optional[str] = None,
        window_s: Optional[float] = None) -> dict:
    """Issue an arm token for one (action, target) intent.

    Mints the idempotency key HERE, not at confirm time, for the reason
    `web/mc/arm_confirm.js:7-13` measured the hard way: a key that outlives one
    intent replays that intent's first answer forever, so the surface looks
    alive and is permanently inert. One arm, one key, discarded together.
    """
    now = _now()
    token = _mint()
    rec = {
        "action": action,
        "target": str(target or ""),
        "key": key if is_valid_key(key) else _mint(),
        "expires_at": now + float(window_s if window_s is not None else ARM_WINDOW_S),
    }
    with _LOCK:
        _sweep_locked(now)
        _ARMED[token] = rec
        while len(_ARMED) > MAX_ARMED:
            _ARMED.popitem(last=False)
    out = dict(rec)
    out["arm_token"] = token
    out["idempotency_key"] = out.pop("key")
    return out


def disarm(token: Any) -> bool:
    """Drop an armed token and its key. True when something was armed."""
    if not isinstance(token, str):
        return False
    with _LOCK:
        return _ARMED.pop(token, None) is not None


def resolve(action: str, target: str, token: Any,
            supplied_key: Any = None) -> Verdict:
    """Decide whether this confirm may proceed, and under which key.

    The token is CONSUMED on success: a second INTENT needs a second arm. A
    transport re-send of the SAME intent still resolves, because the consumed
    record is retained - see the module docstring on the idempotency seam.
    """
    if not isinstance(token, str) or not token.strip():
        return Verdict(False, ARM_REQUIRED, None)
    token = token.strip()
    now = _now()
    want_target = str(target or "")

    with _LOCK:
        # NO sweep here, deliberately. Sweeping first deletes an expired arm
        # before it is looked up, so a genuinely-expired token reports
        # `bad_token` - "you invented that" - instead of `expired` - "you were
        # too slow". Both refuse, so the safety property is identical, but only
        # one of them tells the operator what to do next. Growth is bounded at
        # arm() time, which is where growth actually happens.
        spent = _CONSUMED.get(token)
        if spent is not None and (now - spent["consumed_at"]) > CONSUMED_RETAIN_S:
            # Past the retain window the replay table has forgotten the answer
            # anyway, so resolving this token would re-run the side effect.
            del _CONSUMED[token]
            spent = None
        if spent is not None:
            if spent["action"] != action or spent["target"] != want_target:
                return Verdict(False, OTHER_ARMED, None)
            if supplied_key is not None and supplied_key != spent["key"]:
                # A different key on a spent arm is a SECOND intent, not a
                # re-send of the first one.
                return Verdict(False, CONSUMED, None)
            # Same bytes arriving twice. Hand back the ORIGINAL key so the
            # idempotency table answers with the stored result.
            return Verdict(True, "replay", spent["key"])

        rec = _ARMED.get(token)
        if rec is None:
            return Verdict(False, BAD_TOKEN, None)
        if rec["action"] != action or rec["target"] != want_target:
            # Checked BEFORE expiry so a mis-aimed token reports why it is
            # wrong rather than blaming the clock.
            return Verdict(False, OTHER_ARMED, None)
        if now >= rec["expires_at"]:
            del _ARMED[token]
            return Verdict(False, EXPIRED, None)

        key = rec["key"]
        if supplied_key is not None and is_valid_key(supplied_key):
            # An explicit key wins: that is how a client that mints one key per
            # SEND (the shape web/mc/mc.js:717 used) keeps its own contract.
            key = supplied_key
        del _ARMED[token]
        _CONSUMED[token] = {"action": action, "target": want_target,
                            "key": key, "consumed_at": now}
        while len(_CONSUMED) > MAX_CONSUMED:
            _CONSUMED.popitem(last=False)
        return Verdict(True, None, key)


def detail_for(reason: str) -> str:
    """Operator-facing explanation for a refusal reason."""
    return _REASON_DETAIL.get(reason, "arm-then-confirm refused")


def armed_count() -> int:
    with _LOCK:
        return len(_ARMED)


def consumed_count() -> int:
    with _LOCK:
        return len(_CONSUMED)


def clear() -> None:
    """Drop everything. Test isolation and a hard reset.

    Safe in a way `_idempotency.clear()` is not: this table fails CLOSED, so a
    cleared arm refuses the next confirm rather than letting one through.
    """
    with _LOCK:
        _ARMED.clear()
        _CONSUMED.clear()
