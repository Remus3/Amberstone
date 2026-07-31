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

API:
    is_valid_key(key)                -> bool
    seen(key, ttl_s=900)             -> dict | None   prior result, None if new
    remember(key, result, ttl_s=900) -> None
    purge(now=None)                  -> int           expired entries dropped
    size()                           -> int
    clear()                          -> None
"""
from __future__ import annotations

import copy
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

# ~15 minutes: long enough to cover a retry storm from a wedged client, short
# enough that a genuinely new intent an operator re-issues later is not eaten.
DEFAULT_TTL_S = 900.0

# Cap so a hostile / buggy client cannot grow the table without limit.
MAX_ENTRIES = 512

# Client-minted UUIDs (hex + dashes). Nothing path-like, quoted or shell-ish
# can pass, so the key is safe to embed in a JSON control file verbatim.
_KEY_RE = re.compile(r"\A[0-9a-fA-F-]{1,64}\Z")

_LOCK = threading.RLock()
# key -> (stored_at, ttl_s, result). OrderedDict preserves insertion order so
# eviction is oldest-first.
_TABLE: "OrderedDict[str, tuple[float, float, dict]]" = OrderedDict()


def _now() -> float:
    """Wall clock, isolated so tests can drive expiry deterministically."""
    return time.time()


def is_valid_key(key: Any) -> bool:
    """True when `key` is a well-shaped idempotency key (hex/dash, <= 64)."""
    return isinstance(key, str) and bool(_KEY_RE.match(key))


def _expired(stored_at: float, ttl_s: float, now: float) -> bool:
    return (now - stored_at) > ttl_s


def seen(key: str, ttl_s: float = DEFAULT_TTL_S) -> Optional[dict]:
    """Return the result stored for `key`, or None if new / expired.

    `ttl_s` narrows the freshness window at read time; the effective TTL is the
    smaller of it and the TTL recorded when the entry was remembered.
    """
    if not is_valid_key(key):
        return None
    now = _now()
    with _LOCK:
        entry = _TABLE.get(key)
        if entry is None:
            return None
        stored_at, entry_ttl, result = entry
        if _expired(stored_at, min(entry_ttl, float(ttl_s)), now):
            del _TABLE[key]
            return None
        # Deep copy so a caller decorating the payload (e.g. adding
        # "replayed": true) can never corrupt the stored original.
        return copy.deepcopy(result)


def remember(key: str, result: dict, ttl_s: float = DEFAULT_TTL_S) -> None:
    """Store `result` as the settled answer for `key`. No-op on a bad key."""
    if not is_valid_key(key):
        return
    with _LOCK:
        _TABLE.pop(key, None)
        _TABLE[key] = (_now(), float(ttl_s), copy.deepcopy(result))
        while len(_TABLE) > MAX_ENTRIES:
            _TABLE.popitem(last=False)


def purge(now: Optional[float] = None) -> int:
    """Drop every expired entry. Returns how many were dropped."""
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
    """Drop everything. Test isolation + a hard reset on demand."""
    with _LOCK:
        _TABLE.clear()
