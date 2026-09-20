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

THE SEAM WITH IDEMPOTENCY (`dashboard/routes_loop_control.py` `_apply_idempotent`).
These two gates answer DIFFERENT questions and must not be collapsed:

  * the arm gate asks "did a human mean this ONCE?" - it refuses an unmeant act;
  * the idempotency table asks "is this the SAME meant act arriving twice?" -
    it replays the first answer rather than acting again.

So a token is CONSUMED on the confirm but RETAINED, with the key it ran under,
a PIN of the body it ran for, and - once the confirm settles - THE ANSWER
ITSELF. A transport-level re-send then resolves to that stored answer without
dispatching anything. Without the retain window a benign TCP retry would read
as `bad_token`, which is a confusing refusal in the exact situation both gates
exist to make boring.

THE ANSWER IS STORED HERE, NOT LOOKED UP THERE, AND THAT IS A FIX, NOT A
DUPLICATE. An adversarial pass on 2026-09-20 got TWO real kills out of ONE arm
three different ways, all from the same root cause: this module used to hand a
repeat confirm back to `_apply_idempotent` and TRUST it to replay.

  1. The two tables evict on DIFFERENT AXES. The original reasoning here was
     "past the retain window the replay table has forgotten the answer anyway",
     which is true of TIME and false of CAPACITY: `_CONSUMED` caps at 64 while
     `_idempotency.MAX_ENTRIES` is 512 and is fed by UNGATED actions such as
     `steer`. 517 unrelated steers evicted the remembered answer, and the
     identical re-send on the spent token then killed a second time.
  2. A confirm that did NOT settle (a 503 from a partial kill, a 400 from a
     malformed key) left the spent token resolvable, so the retry acted even
     though the first request had been declared never to have happened.
  3. Nothing pinned the BODY across the two sends, so a re-send could carry a
     different `fingerprint` and kill a victim set no preview had named.

The fix is one rule applied three times: A CONSUMED ARM IS AUTHORITATIVE ABOUT
ITS OWN OUTCOME. It stores the answer (so no other table's capacity can
resurrect the intent), it is RELEASED outright when the confirm does not settle
(so a failed confirm costs an arm and forces a fresh preview), and it pins the
body (so a retry must be the same request). `settle()` is how the route reports
the outcome and MUST be called on every path.

Deliberately in-process and non-durable, for the same reason
`dashboard/_idempotency.py:12-15` gives: an arm is a single operator's intent
over seconds, on a single-operator local surface. A restart clearing the table
is CORRECT - it fails CLOSED, since a lost arm refuses rather than fires.
"""
from __future__ import annotations

import copy
import hashlib
import json
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


DEFAULT_WINDOW_S = 60.0


def window_s() -> float:
    """The live arm window, READ AT CALL TIME.

    Read at IMPORT time originally, which made `RC_MC_ARM_WINDOW_S` inert for
    anyone tightening the perimeter after the process had started - and worse,
    left the arm response advertising a window it was no longer using. A
    security knob that silently does nothing is worse than no knob.
    """
    raw = os.environ.get("RC_MC_ARM_WINDOW_S", "").strip()
    if not raw:
        return DEFAULT_WINDOW_S
    try:
        val = float(raw)
    except ValueError:
        return DEFAULT_WINDOW_S
    # A non-positive window would arm and expire in the same instant, which is
    # a gate that refuses everything - fail to the documented default instead
    # of to a surface that looks armed and never fires.
    return val if val > 0 else DEFAULT_WINDOW_S


# Kept as a module attribute for readers that want the default at a glance.
# Nothing in this module uses it; window_s() is the authority.
ARM_WINDOW_S = DEFAULT_WINDOW_S

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
    """The gate's answer.

    `key`    the idempotency key the confirm runs under.
    `answer` a SETTLED answer for this exact request, stored by a previous
             confirm on the same token. When it is not None the caller MUST
             return it and MUST NOT dispatch - that is what makes a repeat
             confirm incapable of a second side effect regardless of what the
             idempotency table has evicted.
    """

    ok: bool
    reason: Optional[str]
    key: Optional[str]
    answer: Optional[dict] = None


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


def body_pin(action: str, body: Any) -> str:
    """A stable digest of the MATERIAL request, so a retry must be the same one.

    `arm_token` is excluded because it is the thing being checked, and
    `idempotency_key` because a caller may legitimately omit it on one send and
    let the arm supply it on the next - the key is compared separately and by
    value. Everything else is in: for `interrupt` that means `fingerprint`,
    which is the field that names the victims. Without this pin a re-send could
    wear a spent arm and aim it somewhere no preview ever looked.
    """
    if not isinstance(body, dict):
        material: Any = body
    else:
        material = {k: v for k, v in body.items()
                    if k not in ("arm_token", "idempotency_key")}
    try:
        blob = json.dumps(material, sort_keys=True, default=str)
    except (TypeError, ValueError):
        blob = repr(material)
    return hashlib.sha256(f"{action}\n{blob}".encode()).hexdigest()


def arm(action: str, target: str, window: Optional[float] = None) -> dict:
    """Issue an arm token for one (action, target) intent.

    Mints the idempotency key HERE, not at confirm time, for the reason the
    retired browser controller measured the hard way: a key that outlives one
    intent replays that intent's first answer forever, so the surface looks
    alive and is permanently inert. One arm, one key, discarded together.

    THE KEY IS ALWAYS SERVER-MINTED. A client-supplied one was accepted here
    originally, which was not a bypass - the token stays uuid4 - but it left
    the key half of the pair fully guessable, and a guessable key lets an
    attacker AIM a replay-table eviction rather than wait for one. A caller
    that wants to choose its own key can still do so on the CONFIRM, which is
    the only place it ever mattered.
    """
    now = _now()
    token = _mint()
    rec = {
        "action": action,
        "target": str(target or ""),
        "key": _mint(),
        "expires_at": now + float(window if window is not None else window_s()),
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


def resolve(action: str, target: str, token: Any, supplied_key: Any = None,
            pin: Optional[str] = None) -> Verdict:
    """Decide whether this confirm may proceed, and under which key.

    The token is CONSUMED on success: a second INTENT needs a second arm. A
    transport re-send of the SAME intent still resolves, because the consumed
    record is retained - see the module docstring on the idempotency seam.

    THE CALLER MUST CALL settle() for every Verdict with ok=True and answer
    None. Not calling it leaves the arm pending, which refuses every later
    confirm on that token - fail-closed, but it strands the operator.
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
            del _CONSUMED[token]
            spent = None
        if spent is not None:
            if spent["action"] != action or spent["target"] != want_target:
                return Verdict(False, OTHER_ARMED, None)
            if pin is not None and spent["pin"] != pin:
                # A DIFFERENT request wearing a spent arm. For `interrupt` this
                # is the one that matters: the arm binds only the action, so
                # without this the re-send could carry another fingerprint and
                # kill a set no preview named.
                return Verdict(False, CONSUMED, None)
            if supplied_key is not None and supplied_key != spent["key"]:
                # A different key on a spent arm is a SECOND intent, not a
                # re-send of the first one.
                return Verdict(False, CONSUMED, None)
            if spent["settled"]:
                # Authoritative: answer from OUR record. Never dispatch, and
                # never depend on the idempotency table still holding it.
                return Verdict(True, "replay", spent["key"],
                               copy.deepcopy(spent["answer"]))
            # Still in flight on another thread. Hand back the key and let
            # _apply_idempotent's claim protocol do the waiting - it owns
            # concurrency, this module owns intent.
            return Verdict(True, "in_flight", spent["key"])

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
            # SEND keeps its own contract.
            key = supplied_key
        del _ARMED[token]
        _CONSUMED[token] = {"action": action, "target": want_target,
                            "key": key, "pin": pin, "consumed_at": now,
                            "settled": False, "answer": None}
        while len(_CONSUMED) > MAX_CONSUMED:
            _CONSUMED.popitem(last=False)
        return Verdict(True, None, key)


def settle(token: Any, status: int, payload: Optional[dict]) -> None:
    """Report a confirm's outcome. MUST be called for every acting Verdict.

    A 200 STORES the answer on the consumed record, which is what lets a later
    re-send be answered without dispatching. Anything else RELEASES the arm
    outright.

    Releasing on a non-200 is the deliberate half. A 400 or a 503 means the
    request never happened, and `_apply_idempotent` abandons its key for
    exactly that reason - but "it never happened" must not also mean "your arm
    is still good", because the two cases where it fails are the two where the
    world has already moved: a 503 from `ops/loop/interrupt.py` arrives AFTER
    some victims are dead (it kills serially), and a 400 arrives after the
    operator got the body wrong. Both need a fresh preview and a fresh arm.
    Costing an arm is the cheap half of that trade.
    """
    if not isinstance(token, str) or not token.strip():
        return
    token = token.strip()
    with _LOCK:
        rec = _CONSUMED.get(token)
        if rec is None:
            return
        if status == 200 and isinstance(payload, dict):
            rec["settled"] = True
            rec["answer"] = copy.deepcopy(payload)
        else:
            del _CONSUMED[token]


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
