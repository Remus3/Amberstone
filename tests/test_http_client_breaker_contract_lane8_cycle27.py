# arch: lane 8 cycle 27 - lib/http/client.py circuit-breaker contract | section=tests | frozen=no
"""Lane 8 Headless-True-Audit cycle 27 - `lib/http/client.py` circuit breaker.

The module docstring made a CLAIM, and this file exists to decide by test how
much of it the code keeps. Pre-fix wording, quoted from `git show
HEAD:lib/http/client.py` lines 7-8:

    "Circuit breaker per hostname: opens after 5 consecutive failures,
     half-open after 60s; one probe call closes it on success."

MEASURED VERDICT ON THAT CLAIM (against the pre-fix source, before a line of
production code moved this cycle):

  - "opens after 5 consecutive failures"  - TRUE.
  - "half-open after 60s"                 - HALF true. The cooldown gate
    worked, but there was no half-OPEN state at all: pre-fix `_check_breaker`
    fell off the end once the cooldown had elapsed, so EVERY caller was
    admitted, not one. `_HostState` carried no probe-in-flight marker to hold
    the second caller back.
  - "one probe call closes it on success" - the CLOSE half was true. The "one
    probe" half was not implemented, and the unstated other half - what a
    FAILED probe does - was worse: pre-fix `_on_failure` only stamped
    `opened_at` when it was `None`, which an open breaker never is, so a probe
    that failed left the ORIGINAL open timestamp in place and the cooldown
    never restarted. Against a host that stayed down the breaker opened once
    and then, 60s later, became a permanent no-op admitting every call.

TIMELINE - READ THIS BEFORE READING THE GREEN/RED LABELS. These tests were
authored against the pre-fix file (277 lines). The production fix landed in
`lib/http/client.py` from the merger WHILE they were being written, and the
file is now 547 lines with a real half-open implementation. So the D1/D2/D3
regression tests below were RED when written and are GREEN against the landed
fix - they now serve as the guard that holds it in place.

The pre-fix red split was MEASURED, not asserted from memory: the HEAD copy of
the module was injected into `sys.modules` in a throwaway process and this same
file was run against it. 6 failed, exactly the D1 and D2 regressions
(`..._reads_breaker_state_under_the_lock`, `..._cleared_between_its_two_reads`,
`..._only_one_caller_is_admitted...`, `..._concurrent_callers...`,
`..._failed_probe_re_opens...`, `..._failed_probe_then_admits_one_new_probe...`).
9 errored on seams the pre-fix file did not have at all (`_opener`,
`st.rate_lock`), so for those the pre-fix redness was established the other way,
by mutation: three mutants of the FIXED file, each killed by exactly the one
test that owns it and by no other -
  `_rate_gate` re-sharing `st.lock`  -> kills both RateGateLockTests (D3)
  `finally:` clause emptied          -> kills the unexpected-exception latch test
  Blocked branch dropping the clear  -> kills the blocked-redirect slot test
That is the evidence these are load-bearing rather than vacuously green.

The three defect families, each labelled in the individual test docstrings:

  D1 - UNSYNCHRONIZED READ. Pre-fix `_check_breaker` read `st.opened_at` TWICE
       with `st.lock` held for neither read, while `_on_success`/`_on_failure`
       mutated that same field under the lock. The two reads were not one
       another's snapshot, so a concurrent `_on_success` landing between them
       turned `now - st.opened_at` into `now - None` - a `TypeError` escaping a
       method whose declared failure mode is `CircuitOpen`. Fixed: client.py
       :391-410 now does all of it under `st.lock`.
       NOTE against the brief that commissioned this file: pre-fix
       `_check_breaker` did NOT read `st.failures` - only `opened_at`. That
       half of the D1 description is refuted; the lock-audit test records the
       field names so the record stays honest.

  D2 - NO ONE-PROBE CONTRACT. Pinned four ways: sequentially, concurrently (8
       threads off a barrier), through the failed-probe path, and through a
       second cooldown cycle. Fixed: `probe_in_flight` on `_HostState` (:182,
       :190) plus the `elif was_probe` branch in `_on_failure` (:430-434).

  D3 - LOCK HELD ACROSS A SLEEP. Pre-fix `_rate_gate` held `st.lock` while it
       slept up to `MIN_INTERVAL_SEC`, and that was the SAME lock the breaker
       bookkeeping needs, so a thread waiting out the rate limit stalled
       another thread's `_on_failure` on that host for up to a second. Fixed:
       a separate `st.rate_lock` (:182, :186, :445).

THE PROBE SLOT IS A RESOURCE, and the fix created a way to leak it that did
not exist before. Worth stating plainly because it is the one hazard the fix
ADDED rather than removed: the slot is released on every path `request()`
names - `Blocked` from the redirect handler (client.py:500-504), 4xx/5xx
(:506-517), URLError/TimeoutError/OSError (:518-521), success (:523-525) - and
an exception it does NOT name would escape with `probe_in_flight` still True
while `opened_at` is still set. From that moment every caller for that host
gets "probe already in flight" FOREVER: the cooldown cannot rescue it, because
the flag is what refuses them, and only a success or failure clears the flag.
That is strictly worse than the D2 defect it replaces - D2 let too much traffic
through, this stops all of it permanently. It is reachable: `resp.read()` runs
inside the try block and raises `http.client.IncompleteRead` on a truncated
response, which is an `HTTPException` and therefore neither `OSError` nor
`URLError`. The merger closed it with the `finally: if not settled` at
client.py:526-528; the two `ProbeSlotLifetimeTests` hold it closed, and each
was confirmed to kill its own mutant.

CLOCK AND SLEEP DISCIPLINE (asked for explicitly - the choice and the reason).
No fake clock is installed and `BREAKER_COOLDOWN_SEC` is never monkeypatched.
Neither is needed, because the cooldown boundary is ALREADY injectable:
`_check_breaker(host, now)` takes `now` as a parameter. So the tests stay on the
real `time.monotonic` timeline and move the OTHER end of the comparison -
`_open_breaker_seconds_ago()` back-dates `st.opened_at`. That beats a patched
clock here: patching `time.monotonic` would be process-wide (the module does a
plain `import time`, so `client.time` IS the global module) and every other
thread in the pytest worker would read the fake value. Nothing sleeps for the
60s cooldown, and nothing sleeps for the 1s rate-limit interval either -
`_defuse_rate_gate()` back-dates `last_call` so `request()` never reaches its
`time.sleep`.

The only real waits are two event timeouts in the D3 blocking test, which has
to prove a thread is BLOCKED and so must give it a bounded chance not to be.
That costs ~0.75s while the defect is present and ~0 once it is fixed.

WHAT THE LOCK-DISCIPLINE TESTS DO AND DO NOT PROVE. D1a, D3a and their green
`_on_failure`/`_on_success` counterpart are STRUCTURAL, not races. They replace
the per-host state object with an instrumented stand-in whose fields record
whether `lock` was held at the instant of each read and write, then assert the
recording. That proves the discipline directly and deterministically for the
path exercised. It does NOT prove any particular interleaving occurs in
production, and a pass is NOT evidence that a race is impossible - it is
evidence that the access is inside the critical section. D1b shows the
consequence: it scripts the mutation a concurrent `_on_success` would make, but
only at moments when the lock is genuinely free, which is the only time a real
`_on_success` could get in. That keeps it a faithful model rather than an
impossible one - under the fix the mutation simply cannot land.

Everything is offline. The four tests that go through `request()` patch
`client._opener.open`, which is the seam the fixed code actually calls; the
rest drive the internal methods directly. No test resolves a hostname. Any
blocklist is written into a `tempfile` directory - the repo's real
`lib/http/blocklist.json` is never written, only read by the sibling slices.
"""
from __future__ import annotations

import http.client
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib import error as urllib_error

from lib.http.client import (
    BREAKER_COOLDOWN_SEC,
    BREAKER_THRESHOLD,
    MIN_INTERVAL_SEC,
    Blocked,
    CircuitOpen,
    HttpClient,
    HttpError,
)

# Hosts used below. None of them ends in a suffix from the real blocklist
# (.ru/.cn/.tk/.top/.xyz), and every client here is built against a tempfile
# blocklist anyway, so the real file never decides anything in this file.
HOST = "alpha.test"
OTHER_HOST = "beta.test"
URL = "https://alpha.test/probe"


def _write_blocklist(directory, name="blocklist.json", hostnames=(), suffixes=()):
    """Write an isolated blocklist into a tempfile dir and return its Path."""
    path = Path(directory) / name
    path.write_text(
        json.dumps({"hostnames": list(hostnames), "suffixes": list(suffixes)}),
        encoding="utf-8",
    )
    return path


def _http_error(code, url=URL, body=b"body"):
    """Build a real urllib HTTPError - the object urlopen raises on 4xx/5xx.

    `fp` is a live BytesIO because `request()` calls `e.read()`; a fresh one is
    minted per call since that read consumes it.
    """
    return urllib_error.HTTPError(url, code, f"status {code}",
                                  {"Content-Type": "text/plain"}, io.BytesIO(body))


def _raiser(factory):
    """Opener side_effect that raises a FRESH exception on every call."""

    def _fn(*_args, **_kwargs):
        raise factory()

    return _fn


class _FakeHttpResponse:
    """Minimal stand-in for the opener's context manager (status/read/getheaders/url)."""

    def __init__(self, status=200, body=b"{}", headers=None, url=URL, read_raises=None):
        self.status = status
        self.url = url
        self._body = body
        self._headers = dict(headers or {})
        self._read_raises = read_raises

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, amt=None):
        # `amt` accepted because the real http.client.HTTPResponse.read takes
        # it and the client passes it once RM-351's byte cap is in force.
        # Widened 2026-09-06; the raise-and-return behaviour is unchanged.
        if self._read_raises is not None:
            raise self._read_raises
        if amt is None:
            return self._body
        head, self._body = self._body[:amt], self._body[amt:]
        return head

    def getheaders(self):
        return list(self._headers.items())


class _LockAuditHostState:
    """Instrumented drop-in for `_HostState`.

    `HttpClient._host_state` is a plain dict lookup, so seeding
    `client._hosts[host]` with this object routes every breaker read and write
    through the properties below. Each records whether `lock` was held at that
    instant. `lock.locked()` is true when ANY thread holds it, which is exactly
    the right signal in the single-threaded structural tests that use this.

    `rate_lock` is present and deliberately NOT audited - it guards the rate
    limiter, not the breaker, and holding it across a sleep is the whole point
    of the D3 fix.
    """

    _AUDITED = ("failures", "opened_at", "probe_in_flight")

    def __init__(self, failures=0, opened_at=None, probe_in_flight=False, last_call=0.0):
        self.lock = threading.Lock()
        self.rate_lock = threading.Lock()
        self.last_call = last_call
        self.events = []  # (op, field, lock_held_at_that_instant)
        self._failures = failures
        self._opened_at = opened_at
        self._probe_in_flight = probe_in_flight

    def _record(self, op, field):
        self.events.append((op, field, self.lock.locked()))

    @property
    def failures(self):
        self._record("read", "failures")
        return self._failures

    @failures.setter
    def failures(self, value):
        self._record("write", "failures")
        self._failures = value

    @property
    def opened_at(self):
        self._record("read", "opened_at")
        return self._opened_at

    @opened_at.setter
    def opened_at(self, value):
        self._record("write", "opened_at")
        self._opened_at = value

    @property
    def probe_in_flight(self):
        self._record("read", "probe_in_flight")
        return self._probe_in_flight

    @probe_in_flight.setter
    def probe_in_flight(self, value):
        self._record("write", "probe_in_flight")
        self._probe_in_flight = value

    def unsynchronized(self):
        return [(op, field) for op, field, held in self.events if not held]

    def fields_touched(self):
        return sorted({field for _, field, _ in self.events})


class _ClearedMidCheckHostState:
    """Simulates a concurrent `_on_success` clearing `opened_at` mid-check.

    The clear lands only at moments when `lock` is NOT held, because that is
    the only time a real `_on_success` could take the lock and get in. So this
    models the interleaving faithfully instead of forcing an impossible one:
    against the pre-fix reader (no lock) the second read returns None and
    `now - None` raises TypeError; against a reader that holds the lock across
    both reads the mutation cannot land at all and the value is stable.
    """

    def __init__(self, opened_at):
        self.lock = threading.Lock()
        self.rate_lock = threading.Lock()
        self.last_call = 0.0
        self.failures = BREAKER_THRESHOLD
        self.probe_in_flight = False
        self.reads = 0
        self.unguarded_reads = 0
        self._value = opened_at

    @property
    def opened_at(self):
        self.reads += 1
        value = self._value
        if not self.lock.locked():
            # A concurrent _on_success could take the free lock right here,
            # immediately after this read handed its value back.
            self.unguarded_reads += 1
            self._value = None
        return value

    @opened_at.setter
    def opened_at(self, value):
        self._value = value


class _BreakerTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="lane8c27_")
        self.addCleanup(self._tmp.cleanup)
        self.blocklist = _write_blocklist(self._tmp.name)
        self.client = HttpClient(blocklist_path=self.blocklist)

    # ----- helpers ----------------------------------------------------
    def _state(self, host=HOST):
        return self.client._host_state(host)

    def _open_breaker_seconds_ago(self, seconds_ago, host=HOST):
        """Put the breaker in the state it would hold `seconds_ago` after opening.

        Back-dating `opened_at` on the REAL monotonic timeline is what lets this
        whole file run with no fake clock and no sleeping - module docstring.
        """
        st = self._state(host)
        with st.lock:
            st.failures = BREAKER_THRESHOLD
            st.opened_at = time.monotonic() - seconds_ago
        return st

    def _defuse_rate_gate(self, host=HOST):
        """Back-date `last_call` so the next `_rate_gate` finds no debt to pay.

        Without this a second `request()` to the same host sleeps a real
        second. `_rate_gate` re-stamps `last_call`, so call this before EVERY
        request in a loop.
        """
        st = self._state(host)
        with st.rate_lock:
            st.last_call = time.monotonic() - 3600.0

    def _patch_opener(self, **kwargs):
        """Patch the seam `request()` actually calls (client.py:496).

        Guarantees offline: nothing below ever resolves a hostname.
        """
        return mock.patch.object(self.client._opener, "open", **kwargs)


class BreakerCharacterizationTests(_BreakerTestBase):
    """(a) CHARACTERIZATION - green before AND after the fix; must not regress."""

    def test_breaker_opens_at_exactly_the_threshold_and_not_before(self):
        """CHARACTERIZATION (green pre-fix and post-fix). Pins the first half of
        the module-docstring claim - "opens after 5 consecutive failures".
        Guards `st.failures >= BREAKER_THRESHOLD` (client.py:427) against an
        off-by-one in either direction."""
        st = self._state()
        for i in range(BREAKER_THRESHOLD - 1):
            self.client._on_failure(HOST, RuntimeError(f"failure {i}"))
            self.assertIsNone(
                st.opened_at,
                f"breaker opened early, after {i + 1} of {BREAKER_THRESHOLD} failures",
            )
        self.assertEqual(st.failures, BREAKER_THRESHOLD - 1)

        self.client._on_failure(HOST, RuntimeError("failure at threshold"))
        self.assertIsNotNone(st.opened_at, "breaker did not open at the threshold")
        self.assertEqual(st.failures, BREAKER_THRESHOLD)

    def test_check_breaker_raises_circuit_open_inside_the_cooldown(self):
        """CHARACTERIZATION (green pre-fix and post-fix). Pins the cooldown gate:
        while open and inside `BREAKER_COOLDOWN_SEC`, `_check_breaker` refuses
        the call with `CircuitOpen`, names the host, and stays a subclass of
        `HttpError` so existing `except HttpError` callers keep catching it."""
        self._open_breaker_seconds_ago(1.0)
        with self.assertRaises(CircuitOpen) as ctx:
            self.client._check_breaker(HOST, time.monotonic())
        self.assertIn(HOST, str(ctx.exception))
        self.assertIsInstance(ctx.exception, HttpError)

    def test_a_success_before_the_threshold_clears_the_failure_run(self):
        """CHARACTERIZATION (green pre-fix and post-fix). The counter is
        CONSECUTIVE failures, not lifetime failures - four failures, a success,
        then four more must not open the breaker."""
        st = self._state()
        for _ in range(BREAKER_THRESHOLD - 1):
            self.client._on_failure(HOST, RuntimeError("boom"))
        self.client._on_success(HOST)
        self.assertEqual(st.failures, 0)
        self.assertIsNone(st.opened_at)

        for _ in range(BREAKER_THRESHOLD - 1):
            self.client._on_failure(HOST, RuntimeError("boom"))
        self.assertIsNone(st.opened_at, "the failure run was not reset by the success")

    def test_the_first_caller_is_admitted_at_exactly_the_cooldown_boundary(self):
        """CHARACTERIZATION (green pre-fix and post-fix). At exactly
        `opened_at + BREAKER_COOLDOWN_SEC` the comparison is `< COOLDOWN` and
        therefore false, so the boundary admits rather than rejects.
        Deliberately calls ONCE: under the one-probe contract this caller IS
        the probe, which is why it survives the fix unchanged."""
        st = self._open_breaker_seconds_ago(0.0)
        boundary = st.opened_at + BREAKER_COOLDOWN_SEC
        self.assertIsNone(self.client._check_breaker(HOST, boundary))

    def test_breaker_state_is_per_hostname(self):
        """CHARACTERIZATION (green pre-fix and post-fix). Pins "per hostname" -
        opening the breaker for one host must not gate a different host."""
        for _ in range(BREAKER_THRESHOLD):
            self.client._on_failure(HOST, RuntimeError("boom"))
        self.assertIsNotNone(self._state(HOST).opened_at)
        self.assertIsNone(self._state(OTHER_HOST).opened_at)
        self.assertIsNone(self.client._check_breaker(OTHER_HOST, time.monotonic()))

    def test_a_successful_probe_fully_closes_the_breaker(self):
        """CHARACTERIZATION (green pre-fix and post-fix). The close half of the
        claim - after the cooldown, an admitted probe that succeeds resets the
        breaker and normal traffic resumes. It also pins the fix: the
        `probe_in_flight` marker MUST be cleared by `_on_success`
        (client.py:419), or the final `_check_breaker` here starts failing with
        "probe already in flight"."""
        st = self._open_breaker_seconds_ago(BREAKER_COOLDOWN_SEC + 1.0)
        self.client._check_breaker(HOST, time.monotonic())  # probe admitted
        self.client._on_success(HOST)
        self.assertEqual(st.failures, 0)
        self.assertIsNone(st.opened_at)
        self.assertIsNone(
            self.client._check_breaker(HOST, time.monotonic()),
            "normal traffic did not resume after a successful probe",
        )


class RequestPathCharacterizationTests(_BreakerTestBase):
    """(a) CHARACTERIZATION of how `request()` scores outcomes - green throughout."""

    def test_five_5xx_responses_open_the_breaker(self):
        """CHARACTERIZATION (green pre-fix and post-fix). A 5xx is a failure for
        breaker purposes (client.py:511-512) and five of them open it. Runs the
        real `request()` with the opener patched to raise HTTPError; the rate
        gate is defused before each call so no real second is slept."""
        st = self._state()
        with self._patch_opener(side_effect=_raiser(lambda: _http_error(503))):
            for _ in range(BREAKER_THRESHOLD):
                self._defuse_rate_gate()
                resp = self.client.request("GET", URL)
                self.assertEqual(resp.status, 503)
                self.assertEqual(resp.body, b"body")
        self.assertEqual(st.failures, BREAKER_THRESHOLD)
        self.assertIsNotNone(st.opened_at, "five 5xx responses did not open the breaker")

    def test_a_4xx_response_resets_the_failure_count_by_design(self):
        """CHARACTERIZATION (green pre-fix and post-fix) of DELIBERATE
        behaviour, recorded so a later reader does not "fix" it: client.py
        :513-515 treats a 4xx as proof the remote is WORKING and calls
        `_on_success`, which wipes an in-progress failure run. Intended - a 404
        means the server answered."""
        st = self._state()
        for _ in range(BREAKER_THRESHOLD - 1):
            self.client._on_failure(HOST, RuntimeError("boom"))
        self.assertEqual(st.failures, BREAKER_THRESHOLD - 1)

        self._defuse_rate_gate()
        with self._patch_opener(side_effect=_raiser(lambda: _http_error(404))):
            resp = self.client.request("GET", URL)
        self.assertEqual(resp.status, 404)
        self.assertEqual(st.failures, 0, "a 4xx did not reset the failure count")
        self.assertIsNone(st.opened_at)

    def test_a_transport_error_is_wrapped_and_counted_as_a_failure(self):
        """CHARACTERIZATION (green pre-fix and post-fix). A URLError becomes
        `HttpError` - no raw urllib type leaks to callers - and increments the
        failure count (client.py:518-521)."""
        st = self._state()
        with self._patch_opener(
            side_effect=_raiser(lambda: urllib_error.URLError("no route to host"))
        ):
            with self.assertRaises(HttpError) as ctx:
                self.client.request("GET", URL)
        self.assertIs(type(ctx.exception), HttpError)
        self.assertIn("network error", str(ctx.exception))
        self.assertEqual(st.failures, 1)

    def test_a_2xx_response_clears_the_breaker_state(self):
        """CHARACTERIZATION (green pre-fix and post-fix). The happy path calls
        `_on_success` (client.py:523), so a recovered host is un-gated at once."""
        st = self._state()
        for _ in range(BREAKER_THRESHOLD - 1):
            self.client._on_failure(HOST, RuntimeError("boom"))
        self._defuse_rate_gate()
        with self._patch_opener(return_value=_FakeHttpResponse(200, b'{"ok": true}')):
            resp = self.client.request("GET", URL)
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.json(), {"ok": True})
        self.assertEqual(st.failures, 0)

    def test_a_blocked_host_is_rejected_before_the_breaker_or_the_network(self):
        """CHARACTERIZATION (green pre-fix and post-fix). Ordering inside
        `request()`: the scheme check and `is_blocked` run FIRST, so a
        blocklisted host never mints per-host breaker state and never reaches
        the opener. Uses its own tempfile blocklist - the repo's real one is
        untouched."""
        blocked_path = _write_blocklist(self._tmp.name, name="blocked.json",
                                        hostnames=["blocked.test"])
        client = HttpClient(blocklist_path=blocked_path)
        with mock.patch.object(client._opener, "open") as fake_open:
            with self.assertRaises(Blocked):
                client.request("GET", "https://blocked.test/x")
        self.assertEqual(fake_open.call_count, 0, "a blocked host still reached the network")
        self.assertEqual(client._hosts, {}, "a blocked host still minted breaker state")


class HalfOpenProbeContractTests(_BreakerTestBase):
    """(b) REGRESSION for D2 - the one-probe half-open contract."""

    def test_only_one_caller_is_admitted_once_the_cooldown_elapses(self):
        """REGRESSION D2 (red pre-fix, green post-fix). The module docstring
        promises "one probe call". Pre-fix there was no probe: once the cooldown
        had elapsed `_check_breaker` fell off the end for EVERY caller.
        Deterministic and single-threaded on purpose - the second call must be
        refused while the first probe is unresolved. Pre-fix this failed on the
        assertRaises, because the second call returned None."""
        self._open_breaker_seconds_ago(BREAKER_COOLDOWN_SEC + 1.0)
        now = time.monotonic()
        self.assertIsNone(
            self.client._check_breaker(HOST, now),
            "the first caller after the cooldown should be admitted as the probe",
        )
        with self.assertRaises(CircuitOpen):
            self.client._check_breaker(HOST, now)

    def test_concurrent_callers_after_the_cooldown_admit_exactly_one_probe(self):
        """REGRESSION D2 (red pre-fix, green post-fix). The same defect under
        load: N threads arriving after the cooldown all stampede the host the
        breaker exists to protect. Deterministic in BOTH directions - pre-fix
        all 8 were admitted (no interleaving admits fewer), and under the
        one-probe contract exactly 1 is admitted whatever the interleaving. A
        barrier releases the threads together; no bare sleep orders anything."""
        self._open_breaker_seconds_ago(BREAKER_COOLDOWN_SEC + 1.0)
        now = time.monotonic()
        n = 8
        barrier = threading.Barrier(n, timeout=10.0)
        tally_lock = threading.Lock()
        admitted = []
        rejected = []

        def caller(index):
            barrier.wait()
            try:
                self.client._check_breaker(HOST, now)
            except CircuitOpen:
                with tally_lock:
                    rejected.append(index)
            else:
                with tally_lock:
                    admitted.append(index)

        threads = [threading.Thread(target=caller, args=(i,), name=f"lane8c27-probe-{i}")
                   for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
        for t in threads:
            self.assertFalse(t.is_alive(), "a probe thread did not finish")

        self.assertEqual(
            len(admitted), 1,
            f"{len(admitted)} of {n} concurrent callers were admitted past an open "
            f"breaker; the half-open state must admit exactly one probe",
        )
        self.assertEqual(len(rejected), n - 1)

    def test_a_failed_probe_re_opens_the_breaker_for_a_fresh_cooldown(self):
        """REGRESSION D2 (red pre-fix, green post-fix) - the sharpest form.
        Pre-fix `_on_failure` only stamped `opened_at` when it was `None`, which
        an open breaker never is, so a probe failing after the cooldown left the
        ORIGINAL timestamp in place and the cooldown never restarted. From that
        moment the breaker admitted every call forever against a host still
        down - it degraded to a no-op instead of re-opening. Pre-fix this failed
        on the assertRaises: the follow-up call returned None because
        `now - opened_at` was still 61s. Post-fix, client.py:430-434."""
        self._open_breaker_seconds_ago(BREAKER_COOLDOWN_SEC + 1.0)
        self.client._check_breaker(HOST, time.monotonic())  # probe admitted
        self.client._on_failure(HOST, RuntimeError("the probe failed too"))
        with self.assertRaises(CircuitOpen):
            self.client._check_breaker(HOST, time.monotonic())

    def test_a_failed_probe_then_admits_one_new_probe_after_the_new_cooldown(self):
        """REGRESSION D2 (red pre-fix, green post-fix). The cycle must be
        repeatable, not one-shot: after a failed probe re-opens the breaker, the
        NEXT cooldown expiry admits exactly one caller and refuses the second.
        Pre-fix this failed at the first assertRaises for the reason above."""
        self._open_breaker_seconds_ago(BREAKER_COOLDOWN_SEC + 1.0)
        self.client._check_breaker(HOST, time.monotonic())
        self.client._on_failure(HOST, RuntimeError("the probe failed too"))
        with self.assertRaises(CircuitOpen):
            self.client._check_breaker(HOST, time.monotonic())

        st = self._state()
        second_cycle = st.opened_at + BREAKER_COOLDOWN_SEC + 1.0
        self.assertIsNone(self.client._check_breaker(HOST, second_cycle),
                          "the second cooldown never admitted a fresh probe")
        with self.assertRaises(CircuitOpen):
            self.client._check_breaker(HOST, second_cycle)


class ProbeSlotLifetimeTests(_BreakerTestBase):
    """The probe slot is a RESOURCE. Whoever takes it must give it back."""

    def test_a_blocked_redirect_during_a_probe_releases_the_probe_slot(self):
        """REGRESSION (green post-fix; the code path did not exist pre-fix).
        `request()` admits the probe, then the redirect handler can raise
        `Blocked` for a redirect target. That is not a network failure, so it
        scores neither success nor failure - which means nothing would release
        the probe slot without the explicit `_clear_probe` at client.py:500-504.
        Without it the host is refused forever with "probe already in flight"."""
        self._open_breaker_seconds_ago(BREAKER_COOLDOWN_SEC + 1.0)
        self._defuse_rate_gate()
        with self._patch_opener(
            side_effect=_raiser(lambda: Blocked("redirect target blocked: https://evil.test/"))
        ):
            with self.assertRaises(Blocked):
                self.client.request("GET", URL)

        st = self._state()
        self.assertFalse(st.probe_in_flight, "the blocked redirect leaked the probe slot")
        self.assertIsNone(
            self.client._check_breaker(HOST, time.monotonic()),
            "the breaker latched after a blocked redirect - no caller can ever probe again",
        )

    def test_an_unexpected_exception_during_a_probe_does_not_latch_the_breaker(self):
        """REGRESSION (green post-fix) on the hazard the FIX ITSELF introduced.

        `request()` releases the probe slot on every exit it NAMES: `Blocked`
        (client.py:500), 4xx/5xx (:506), URLError/TimeoutError/OSError (:518),
        success (:523). It names nothing else. `resp.read()` runs INSIDE that
        try block and raises `http.client.IncompleteRead` on a truncated
        response - an `HTTPException`, which is NOT an `OSError` and NOT a
        `URLError`, so without a catch-all it escapes with `probe_in_flight`
        still True while `opened_at` is still set. Every later caller for that
        host then gets "probe already in flight" FOREVER: the cooldown cannot
        rescue it, because the flag is what refuses them, and only a success or
        a failure clears the flag.

        Pre-fix there was no flag and therefore no latch, so this failure mode
        is NEW, and it is strictly worse than the D2 defect it replaces - D2 let
        too much traffic through, this stops all of it permanently. The merger
        closed it with `finally: if not settled: self._clear_probe(host)`
        (:526-528). Confirmed load-bearing by mutation: emptying that `finally`
        fails this test and only this test, on `self.fail` in the except."""
        self._open_breaker_seconds_ago(BREAKER_COOLDOWN_SEC + 1.0)
        self._defuse_rate_gate()
        truncated = _FakeHttpResponse(200, read_raises=http.client.IncompleteRead(b"partial"))
        with self._patch_opener(return_value=truncated):
            with self.assertRaises(http.client.IncompleteRead):
                self.client.request("GET", URL)

        st = self._state()
        # Give the breaker every chance: ask again a full cooldown after the
        # newest possible open timestamp. Only a latched probe slot can refuse.
        much_later = time.monotonic() + BREAKER_COOLDOWN_SEC + 1.0
        try:
            self.client._check_breaker(HOST, much_later)
        except CircuitOpen as exc:
            self.fail(
                "the breaker latched permanently after a probe raised an exception "
                f"request() does not name (probe_in_flight={st.probe_in_flight!r}, "
                f"opened_at set={st.opened_at is not None!r}): {exc}"
            )


class BreakerLockDisciplineTests(_BreakerTestBase):
    """D1 - who touches breaker state, and under which lock."""

    def test_on_failure_and_on_success_touch_breaker_state_only_under_the_lock(self):
        """CHARACTERIZATION (green pre-fix and post-fix). The writer half of the
        class always had correct discipline: every read and write of
        `failures`/`opened_at`/`probe_in_flight` inside `_on_failure`
        (client.py:421-434) and `_on_success` (:412-419) happens with `st.lock`
        held, including the read-modify-write `st.failures += 1` and the log
        line's reads. Pinned so no future edit loosens it."""
        audited = _LockAuditHostState()
        self.client._hosts[HOST] = audited
        for _ in range(BREAKER_THRESHOLD):
            self.client._on_failure(HOST, RuntimeError("boom"))
        self.client._on_success(HOST)

        self.assertTrue(audited.events, "the instrumented state recorded no field access at all")
        self.assertEqual(
            audited.unsynchronized(), [],
            f"breaker fields were touched without st.lock held: {audited.unsynchronized()!r}",
        )

    def test_check_breaker_reads_breaker_state_under_the_lock(self):
        """REGRESSION D1 (red pre-fix, green post-fix). Pre-fix
        `_check_breaker` read `st.opened_at` twice with `st.lock` held for
        neither, while the two writers above held it for every touch.
        Structural proof: the instrumented state records lock-held at the
        instant of each access. Pre-fix this failed with two unsynchronized
        ('read', 'opened_at') events; post-fix client.py:400 wraps the lot.

        This proves the access sits inside the critical section. It does NOT
        prove a race occurs in production, and passing is NOT evidence that one
        cannot - the next test shows the consequence. The recorded field list
        also documents the REFUTED half of the brief: `_check_breaker` never
        reads `failures`."""
        audited = _LockAuditHostState(failures=BREAKER_THRESHOLD,
                                      opened_at=time.monotonic() - 1.0)
        self.client._hosts[HOST] = audited
        try:
            self.client._check_breaker(HOST, time.monotonic())
        except CircuitOpen:
            pass

        self.assertTrue(audited.events, "the instrumented state recorded no field access at all")
        self.assertEqual(
            audited.unsynchronized(), [],
            f"_check_breaker touched breaker state without st.lock held: "
            f"{audited.unsynchronized()!r} (all accesses: {audited.events!r})",
        )
        self.assertNotIn(
            "failures", audited.fields_touched(),
            "_check_breaker now reads failures - the docstring note in this file "
            "that it does not is stale and must be corrected",
        )

    def test_check_breaker_survives_opened_at_being_cleared_between_its_two_reads(self):
        """REGRESSION D1 (red pre-fix, green post-fix) - the consequence.
        `_check_breaker` reads `st.opened_at` twice (the `is None` guard, then
        the subtraction). Pre-fix those two reads were not one another's
        snapshot: a concurrent `_on_success` setting the field to None under a
        lock the reader did not take made the subtraction evaluate `now - None`.

        The state object scripts exactly that, and ONLY at instants when the
        lock is free - which is the only time a real `_on_success` could get in.
        So the pre-fix failure was deterministic rather than a race to win, and
        post-fix the mutation cannot land at all because the lock is held across
        both reads. Contract: `_check_breaker` raises `CircuitOpen` or returns -
        never a TypeError out of a method whose callers catch `HttpError`."""
        racing = _ClearedMidCheckHostState(time.monotonic() - 1.0)
        self.client._hosts[HOST] = racing
        try:
            self.client._check_breaker(HOST, time.monotonic())
        except CircuitOpen:
            pass
        except TypeError as exc:
            self.fail(
                "_check_breaker re-read st.opened_at outside st.lock and raised "
                f"TypeError when a concurrent _on_success cleared it: {exc!r}"
            )
        self.assertGreaterEqual(racing.reads, 1, "opened_at was never read")
        self.assertEqual(
            racing.unguarded_reads, 0,
            f"{racing.unguarded_reads} read(s) of opened_at happened with st.lock free",
        )


class RateGateLockTests(_BreakerTestBase):
    """D3 - the rate gate must not hold the BREAKER lock across its sleep."""

    def test_rate_gate_does_not_hold_the_breaker_lock_across_its_sleep(self):
        """REGRESSION D3 (red pre-fix, green post-fix). Pre-fix `_rate_gate`
        slept up to `MIN_INTERVAL_SEC` inside `with st.lock:` - the same lock
        the breaker bookkeeping needs. Structural proof: `time.sleep` is
        replaced (thread-scoped to this test's own thread, so no other thread in
        the pytest worker is affected or busy-spun) with a probe that records
        `st.lock.locked()` at the moment of the sleep and returns immediately -
        no real second is slept.

        Pre-fix this failed on the final assertFalse. Post-fix the rate limiter
        has its own `st.rate_lock` (client.py:445), which it is free to hold
        across the sleep - that is asserted too, so a future edit cannot make
        this pass by deleting the rate limiter's mutual exclusion outright.
        What this proves is the structure of the critical section, not that a
        contending thread was actually delayed - the next test measures that."""
        st = self._state()
        with st.rate_lock:
            st.last_call = time.monotonic()  # full interval still owed

        observed = []
        owner = threading.get_ident()
        real_sleep = time.sleep

        def probe(seconds=0.0):
            if threading.get_ident() == owner:
                rate_lock = getattr(st, "rate_lock", None)
                observed.append((seconds, st.lock.locked(),
                                 rate_lock is not None and rate_lock.locked()))
                return
            real_sleep(seconds)

        time.sleep = probe
        try:
            self.client._rate_gate(HOST)
        finally:
            time.sleep = real_sleep

        self.assertEqual(len(observed), 1, "the rate gate did not sleep at all")
        seconds, breaker_lock_held, rate_lock_held = observed[0]
        self.assertGreater(seconds, 0.0)
        self.assertLessEqual(seconds, MIN_INTERVAL_SEC)
        self.assertFalse(
            breaker_lock_held,
            f"st.lock was held across the rate-gate sleep of {seconds:.3f}s; that lock "
            f"also guards the circuit-breaker bookkeeping",
        )
        self.assertTrue(
            rate_lock_held,
            "the rate gate slept holding NO rate lock - two callers can now "
            "issue simultaneously and the 1 req/sec limit is not enforced",
        )

    def test_breaker_bookkeeping_is_not_blocked_by_a_rate_gate_sleeper(self):
        """REGRESSION D3 (red pre-fix, green post-fix) - the consequence,
        measured rather than argued. One thread parks inside the rate gate's
        sleep while holding its lock; a second thread then records a failure for
        the same host. Ordering is by events, never by bare sleeps: the
        bookkeeper is not started until the sleeper has provably entered the
        sleep.

        Proving a thread is BLOCKED requires giving it a bounded chance not to
        be, so this is the one test here with a real wait - 0.75s while the
        defect stands, ~0 once the sleep is off the breaker lock. Pre-fix it
        failed on the final assertFalse."""
        st = self._state()
        with st.rate_lock:
            st.last_call = time.monotonic()  # full interval still owed

        sleeper_ident = {"value": None}
        in_sleep = threading.Event()
        release = threading.Event()
        bookkeeping_done = threading.Event()
        real_sleep = time.sleep

        def probe(seconds=0.0):
            if threading.get_ident() == sleeper_ident["value"]:
                in_sleep.set()
                release.wait(10.0)
                return
            real_sleep(seconds)

        def sleeper():
            sleeper_ident["value"] = threading.get_ident()
            self.client._rate_gate(HOST)

        def bookkeeper():
            self.client._on_failure(HOST, RuntimeError("failure during the rate wait"))
            bookkeeping_done.set()

        time.sleep = probe
        t_sleep = threading.Thread(target=sleeper, name="lane8c27-rategate")
        t_book = threading.Thread(target=bookkeeper, name="lane8c27-bookkeeper")
        try:
            t_sleep.start()
            self.assertTrue(in_sleep.wait(10.0), "the rate gate never entered its sleep")
            t_book.start()
            blocked = not bookkeeping_done.wait(0.75)
        finally:
            release.set()
            time.sleep = real_sleep
            t_sleep.join(10.0)
            if t_book.ident is not None:
                t_book.join(10.0)

        self.assertFalse(t_sleep.is_alive())
        self.assertFalse(t_book.is_alive())
        self.assertFalse(
            blocked,
            "_on_failure could not record a failure while another thread waited out "
            "the rate limit - the rate gate holds the breaker lock across its sleep, "
            f"so bookkeeping is stalled for up to MIN_INTERVAL_SEC ({MIN_INTERVAL_SEC:.1f}s)",
        )


if __name__ == "__main__":
    unittest.main()
