# arch: in-process idempotency (replay) table for operator intents | section=dashboard | frozen=no
"""One operator INTENT equals one idempotency key.

The dashboard control plane fires real side effects (halt the loop, claim a
lane). Those requests cross a phone, Tailscale and a browser that may already
be wedged, so the SAME intent can arrive more than once without the operator
ever meaning it twice. Disabling a button does not cover that: the click has
already become an in-flight request, and a frozen UI retries it. The durable fix
is server side - the client mints a UUID per intent, and a repeat of that key
returns the ORIGINAL stored result and performs NO second side effect.

Deliberately in-process and non-durable. The thing being de-duplicated is a
single operator's click, on a single-operator local surface, over seconds to
minutes - not a distributed exactly-once problem. A dashboard restart clearing
the table is correct: nothing is in flight across it.

Bounded on purpose. The table is keyed by client-supplied strings, so an
unbounded dict is a memory-growth vector. MAX_ENTRIES caps it and eviction is
FIFO by insertion (a read never refreshes an entry's position, so a caller
cannot pin one alive). Keys are validated for shape - hex and dashes, at most
64 chars - so nothing path-like or shell-like ever reaches a caller that might
echo it into a filename or a log line.

Atomic by CLAIM, not by check-then-act. `seen` and `remember` are each locked
individually, but the sequence "seen -> perform the side effect -> remember" is
not, and the dashboard is a ThreadingHTTPServer (dashboard/server.py `_DualStackHTTPServer`). Two
requests carrying the same key therefore ran on two threads, both saw an empty
table, and both acted. That is precisely the shape this module exists to stop:
a wedged client's retry storm is CONCURRENT, not sequential, so the defended
case was the one that never happens and the undefended one was the real thing.
`claim` closes it - it decides "replay / act / wait" under a single lock and
hands the winner an exclusive reservation to settle or abandon. `seen` and
`remember` are kept for read-only callers and legacy use; a gate that must not
double-fire uses claim/settle/abandon.

API:
    is_valid_key(key)                -> bool
    seen(key, ttl_s=900)             -> dict | None   prior result, None if new
    remember(key, result, ttl_s=900) -> None
    claim(key, ttl_s=900)            -> (state, value) hit / claimed / inflight
    settle(key, result, ttl_s=900)   -> None          remember + release waiters
    abandon(key)                     -> None          release WITHOUT remembering
    purge(now=None)                  -> int           expired entries dropped
    size()                           -> int
    clear()                          -> None
"""
from __future__ import annotations

import copy
import math
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

# ~15 minutes: long enough to cover a retry storm from a wedged client, short
# enough that a genuinely new intent an operator re-issues later is not eaten.
DEFAULT_TTL_S = 900.0

# Cap so a hostile / buggy client cannot grow the table without limit.
#
# The cap is also the one remaining hole in the claim protocol, stated rather
# than papered over: if MAX_ENTRIES distinct keys are remembered between an
# owner settling and a waiter waking, the settled answer is evicted and the
# waiter - unable to tell an evicted key from an abandoned one, since both must
# mean "act" - runs the side effect a second time. Reaching it needs 512
# distinct intents inside one wake-up on a single-operator local surface, and
# the pre-claim code had the identical hole through seen(), so this is a bound
# to know about, not a regression. Distinguishing the two would mean carrying
# an outcome flag on the Event; that machinery is not worth an unreachable case.
MAX_ENTRIES = 512

# Client-minted UUIDs (hex + dashes). Nothing path-like, quoted or shell-ish
# can pass, so the key is safe to embed in a JSON control file verbatim.
_KEY_RE = re.compile(r"\A[0-9a-fA-F-]{1,64}\Z")

_LOCK = threading.RLock()
# key -> (stored_at, ttl_s, result). OrderedDict preserves insertion order so
# eviction is oldest-first.
_TABLE: "OrderedDict[str, tuple[float, float, dict]]" = OrderedDict()

# key -> Event, for keys whose side effect is RUNNING RIGHT NOW. A key lives
# here between claim() and settle()/abandon(), so the registry is bounded by
# the number of CONCURRENT in-flight requests rather than by client input, and
# needs no MAX_ENTRIES of its own. The Event is set exactly once, by whoever
# releases the claim, which is what wakes the waiters.
#
# Read that bound precisely: it holds only while every claimer releases. This
# registry has NO TTL and purge() does not touch it, so a caller that takes a
# claim and neither settles nor abandons leaks that key until the process
# restarts, and size() - which reports len(_TABLE) - will not show it. The one
# consumer releases in a `finally`; a future one must too. That is a contract,
# not an invariant this module can enforce on its own.
_INFLIGHT: "dict[str, threading.Event]" = {}


def _now() -> float:
    """MONOTONIC clock, isolated so tests can drive expiry deterministically.

    Never the wall clock (S144-T-611). A TTL measured on time.time() moves when
    the clock is stepped (NTP correction, a manual set, a resume from sleep):
    a forward step past the TTL between a settle and a retry expired the
    settled answer, and the retry performed the side effect a second time -
    the exact double fire this module exists to stop. Nothing outside this
    process ever reads a stored timestamp, so a process-local clock is enough.
    """
    return time.monotonic()


def is_valid_key(key: Any) -> bool:
    """True when `key` is a well-shaped idempotency key (hex/dash, <= 64)."""
    return isinstance(key, str) and bool(_KEY_RE.match(key))


def _checked_ttl(ttl_s: Any) -> float:
    """Return `ttl_s` as a finite, non-negative float, or raise.

    A NaN TTL made an entry immortal (every comparison against NaN is False,
    so it never expired); a negative one stored an answer that was already
    dead, or - as a read-time narrowing - expired every live answer so the
    caller acted again. Both are programming errors, refused loudly. A bool
    is refused too: True is an int, and a TTL of one second is never what a
    caller passing a flag meant.
    """
    if isinstance(ttl_s, bool) or not isinstance(ttl_s, (int, float)):
        raise TypeError("idempotency ttl_s must be a real number of seconds")
    ttl = float(ttl_s)
    if not math.isfinite(ttl) or ttl < 0.0:
        raise ValueError("idempotency ttl_s must be finite and >= 0")
    return ttl


def _expired(stored_at: float, ttl_s: float, now: float) -> bool:
    return (now - stored_at) > ttl_s


def seen(key: str, ttl_s: float = DEFAULT_TTL_S) -> Optional[dict]:
    """Return the result stored for `key`, or None if new / expired.

    `ttl_s` narrows the freshness window at read time; the effective TTL is the
    smaller of it and the TTL recorded when the entry was remembered.
    """
    if not is_valid_key(key):
        return None
    ttl = _checked_ttl(ttl_s)
    now = _now()
    with _LOCK:
        entry = _TABLE.get(key)
        if entry is None:
            return None
        stored_at, entry_ttl, result = entry
        if _expired(stored_at, min(entry_ttl, ttl), now):
            del _TABLE[key]
            return None
        # Deep copy so a caller decorating the payload (e.g. adding
        # "replayed": true) can never corrupt the stored original.
        return copy.deepcopy(result)


def _store_locked(key: str, stored: dict, ttl: float) -> None:
    """Insert an already-validated, already-copied answer under _LOCK.

    Nothing here can raise on caller input: the TTL was checked and the
    result deep-copied BEFORE the lock was taken, so the old entry is only
    ever replaced by a good one. The previous shape popped the old entry
    first and then raised on a bad TTL or an uncopyable payload, destroying a
    settled answer it never replaced.
    """
    _TABLE.pop(key, None)
    _TABLE[key] = (_now(), ttl, stored)
    while len(_TABLE) > MAX_ENTRIES:
        _TABLE.popitem(last=False)


def _release_locked(key: str) -> Optional[threading.Event]:
    """Detach the in-flight Event under an already-held _LOCK.

    Returned rather than set here so the caller can .set() OUTSIDE the lock:
    waking a waiter that immediately re-enters claim() while we still hold the
    lock would just bounce it off the mutex.
    """
    return _INFLIGHT.pop(key, None)


def remember(key: str, result: dict, ttl_s: float = DEFAULT_TTL_S) -> None:
    """Store `result` as the settled answer for `key`. No-op on a bad key.

    Also releases any in-flight claim on the key, so a caller that took a claim
    and then used the legacy API to record its answer cannot strand a waiter.

    Raises TypeError for a non-dict `result` (a stored None replayed as
    ("hit", None) and broke the consumer's dict(value)) and TypeError /
    ValueError for a bad `ttl_s`; an uncopyable payload raises whatever
    deepcopy raises. Every one of those raises BEFORE the table is touched, so
    an existing settled answer survives, AND after releasing any in-flight
    claim on the key, so a failed settle behaves as abandon(): its waiters
    wake, re-claim and act, instead of sleeping until their own timeout with
    the key reserved until the process restarts (S144-T-611).
    """
    if not is_valid_key(key):
        return
    try:
        ttl = _checked_ttl(ttl_s)
        if not isinstance(result, dict):
            raise TypeError("idempotency result must be a dict")
        stored = copy.deepcopy(result)
    except BaseException:
        abandon(key)
        raise
    with _LOCK:
        _store_locked(key, stored, ttl)
        ev = _release_locked(key)
    if ev is not None:
        ev.set()


def claim(key: str, ttl_s: float = DEFAULT_TTL_S):
    """Decide replay / act / wait for `key` ATOMICALLY. Returns (state, value):

      ("hit", result)      a settled answer exists - replay it, do NOT act.
      ("claimed", None)    this caller now OWNS the key and MUST finish with
                           settle() (a settled answer) or abandon() (it never
                           happened). Not finishing strands every waiter until
                           the process restarts, so own it in a try/finally.
      ("inflight", event)  another caller owns it. Wait on `event`, then call
                           claim() again - the owner may settle (you get a hit)
                           or abandon (you get the claim and act yourself).

    An invalid key is unguardable, so it returns ("claimed", None) with no
    reservation taken - the same permissive no-op contract remember() has. The
    route validates keys and answers 400 before ever reaching here.
    """
    if not is_valid_key(key):
        return ("claimed", None)
    ttl = _checked_ttl(ttl_s)
    now = _now()
    with _LOCK:
        entry = _TABLE.get(key)
        if entry is not None:
            stored_at, entry_ttl, result = entry
            if not _expired(stored_at, min(entry_ttl, ttl), now):
                return ("hit", copy.deepcopy(result))
            del _TABLE[key]
        event = _INFLIGHT.get(key)
        if event is not None:
            return ("inflight", event)
        _INFLIGHT[key] = threading.Event()
        return ("claimed", None)


def settle(key: str, result: dict, ttl_s: float = DEFAULT_TTL_S) -> None:
    """Record the settled answer for a claimed key and wake its waiters."""
    remember(key, result, ttl_s)


def abandon(key: str) -> None:
    """Release a claim WITHOUT remembering - the request never happened.

    A 400 or a 503 is not an answer to replay, so the next caller of that key
    must be free to act rather than inherit a failure. Also the unwind path
    when the side effect raises.

    An invalid key is a no-op, like every other entry point: claim() never
    reserves one, so there is nothing to release, and an unhashable key used
    to raise TypeError out of the dict lookup whenever any claim was in
    flight - inside an unwind path.
    """
    if not is_valid_key(key):
        return
    with _LOCK:
        ev = _release_locked(key)
    if ev is not None:
        ev.set()


def purge(now: Optional[float] = None) -> int:
    """Drop every expired entry. Returns how many were dropped.

    An explicit `now` is on the _now() clock (monotonic), never a wall-clock
    stamp: a time.time() value is decades past any monotonic reading and
    would expire everything.
    """
    stamp = _now() if now is None else float(now)
    with _LOCK:
        dead = [k for k, (at, ttl, _r) in _TABLE.items() if _expired(at, ttl, stamp)]
        for k in dead:
            del _TABLE[k]
        return len(dead)


def size() -> int:
    """Current entry count (expired-but-unpurged rows included)."""
    with _LOCK:
        return len(_TABLE)


def clear() -> None:
    """Drop everything. Test isolation + a hard reset on demand.

    Waiters are WOKEN, not orphaned: a cleared in-flight registry that left its
    Events unset would hang every thread parked on one until its own timeout,
    which in a test run reads as a mysterious stall rather than a failure.

    That choice has a knowable edge, stated rather than hidden. Clearing while a
    side effect is still running wakes its waiter WITHOUT the owner having
    settled, so the waiter re-claims and acts - a double fire. It is the right
    trade anyway: this is a hard reset with no production caller (its callers
    are test fixtures), and a hung suite is a worse failure than a duplicated
    call in a test that was already tearing the table down mid-flight. Do NOT
    call clear() from request-handling code.
    """
    with _LOCK:
        _TABLE.clear()
        events = list(_INFLIGHT.values())
        _INFLIGHT.clear()
    for ev in events:
        ev.set()
