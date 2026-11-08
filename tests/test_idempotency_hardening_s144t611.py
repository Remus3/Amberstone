"""S144-T-611 (true-audit lane, cycle 218): dashboard/_idempotency.py hardening.

The replay table exists so ONE operator intent cannot fire a side effect twice.
Four ways it still could, each pinned here:

1. TTL ran on the WALL clock (time.time). A clock step forward past the TTL
   between a settle and a retry expires the settled answer, and the retry
   performs the side effect again. A step backward makes `now - stored_at`
   negative. The TTL now runs on time.monotonic, which no clock step moves.
2. remember() popped the old entry BEFORE validating ttl_s / deep-copying the
   result, so a bad ttl or an uncopyable result destroyed a settled answer and
   then raised before releasing the in-flight claim - every waiter parked on
   that key slept until its own timeout, and the key stayed reserved forever
   for any caller that did not unwind with abandon().
3. A non-finite ttl_s (NaN) made an entry immortal: every `>` against NaN is
   False, so it never expired. A negative ttl_s stored an already-dead answer.
   Both are now refused with ValueError, before any mutation.
4. A non-dict result was stored as-is, so a later claim() returned
   ("hit", None) and the one consumer's dict(value) raised. Refused with
   TypeError, before any mutation.
Plus abandon() with an unhashable key raised TypeError whenever any claim
was in flight; it is now the same permissive no-op every other entry point
has for an invalid key.
"""
from __future__ import annotations

import math
import threading
import time

import pytest

from dashboard import _idempotency as idem

KEY = "5a5a5a5a-0000-4000-8000-000000000611"


# ------------------------------------------------------------------ clock
def test_now_is_the_monotonic_clock(monkeypatch):
    """A wall-clock jump must not move the TTL clock."""
    monkeypatch.setattr(time, "time", lambda: 1e12)
    a = idem._now()
    assert a < 1e11, "TTL clock followed a wall-clock step"
    assert abs(a - time.monotonic()) < 5.0


def test_wall_clock_step_forward_does_not_expire_a_settled_answer(monkeypatch):
    real_time = time.time
    idem.settle(KEY, {"ok": True, "detail": "fired"})
    # Wall clock jumps forward a full day (NTP correction, manual set).
    monkeypatch.setattr(time, "time", lambda: real_time() + 86400.0)
    state, value = idem.claim(KEY)
    assert state == "hit", "a wall-clock step re-armed a settled intent"
    assert value == {"ok": True, "detail": "fired"}


# ------------------------------------------------------- ttl validation
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, -1.0])
def test_remember_refuses_a_bad_ttl(bad):
    with pytest.raises(ValueError):
        idem.remember(KEY, {"ok": True}, ttl_s=bad)
    assert idem.size() == 0


@pytest.mark.parametrize("bad", ["abc", None, [1]])
def test_remember_refuses_a_non_numeric_ttl(bad):
    with pytest.raises((TypeError, ValueError)):
        idem.remember(KEY, {"ok": True}, ttl_s=bad)
    assert idem.size() == 0


def test_bool_ttl_is_refused():
    with pytest.raises(TypeError):
        idem.remember(KEY, {"ok": True}, ttl_s=True)


def test_zero_ttl_is_allowed():
    idem.remember(KEY, {"ok": True}, ttl_s=0)
    assert idem.size() == 1


def test_nan_ttl_never_makes_an_entry_immortal(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(idem, "_now", lambda: clock[0])
    with pytest.raises(ValueError):
        idem.remember(KEY, {"ok": True}, ttl_s=math.nan)
    clock[0] = 1e9
    assert idem.seen(KEY) is None


# ---------------------------------------------------- result validation
@pytest.mark.parametrize("bad", [None, [1, 2], "ok", 3])
def test_remember_refuses_a_non_dict_result(bad):
    with pytest.raises(TypeError):
        idem.remember(KEY, bad)
    assert idem.size() == 0


# ------------------------------------- a failed remember keeps old state
def test_bad_ttl_does_not_destroy_an_existing_settled_answer():
    idem.remember(KEY, {"ok": True, "n": 1})
    with pytest.raises(ValueError):
        idem.remember(KEY, {"ok": True, "n": 2}, ttl_s=math.nan)
    assert idem.seen(KEY) == {"ok": True, "n": 1}


class _Uncopyable:
    def __deepcopy__(self, memo):
        raise RuntimeError("cannot copy")


def test_uncopyable_result_does_not_destroy_an_existing_settled_answer():
    idem.remember(KEY, {"ok": True, "n": 1})
    with pytest.raises(RuntimeError):
        idem.remember(KEY, {"ok": True, "bad": _Uncopyable()})
    assert idem.seen(KEY) == {"ok": True, "n": 1}


# ------------------------------- a failed settle never strands a waiter
def test_failed_settle_releases_the_claim_and_wakes_waiters():
    state, _ = idem.claim(KEY)
    assert state == "claimed"
    state2, event = idem.claim(KEY)
    assert state2 == "inflight"
    with pytest.raises(RuntimeError):
        idem.settle(KEY, {"ok": True, "bad": _Uncopyable()})
    assert event.is_set(), "a raising settle left its waiters parked"
    # The key is free again: the next caller acts (abandon semantics).
    state3, _ = idem.claim(KEY)
    assert state3 == "claimed"
    idem.abandon(KEY)


def test_failed_settle_wakes_a_real_waiting_thread():
    assert idem.claim(KEY)[0] == "claimed"
    _, event = idem.claim(KEY)
    woke = []
    t = threading.Thread(target=lambda: woke.append(event.wait(5.0)),
                         name="idem-waiter-s144t611", daemon=True)
    t.start()
    with pytest.raises(ValueError):
        idem.settle(KEY, {"ok": True}, ttl_s=-5.0)
    t.join(5.0)
    assert woke == [True]


# ------------------------------------------------------------ abandon
@pytest.mark.parametrize("bad", [["not", "hashable"], {"k": 1}, None, 7])
def test_abandon_with_an_invalid_key_is_a_no_op(bad):
    # A claim must be in flight: CPython's dict.pop on an EMPTY dict never
    # hashes the key, so the unhashable-key TypeError only fired while some
    # other request held a claim - i.e. exactly under contention.
    assert idem.claim(KEY)[0] == "claimed"
    idem.abandon(bad)
    idem.abandon(KEY)


def test_abandon_with_an_invalid_key_leaves_real_claims_alone():
    assert idem.claim(KEY)[0] == "claimed"
    idem.abandon(["x"])
    assert idem.claim(KEY)[0] == "inflight"
    idem.abandon(KEY)


# ------------------------------------------- read-time ttl narrowing
@pytest.mark.parametrize("bad", [math.nan, -1.0, "abc", True])
def test_claim_and_seen_refuse_a_bad_ttl_without_touching_state(bad):
    idem.remember(KEY, {"ok": True})
    with pytest.raises((TypeError, ValueError)):
        idem.claim(KEY, ttl_s=bad)
    with pytest.raises((TypeError, ValueError)):
        idem.seen(KEY, ttl_s=bad)
    # A negative narrowing used to expire (and delete) a live answer, so the
    # caller acted again. The answer must still be there.
    assert idem.claim(KEY) == ("hit", {"ok": True})
