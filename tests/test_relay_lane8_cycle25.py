# arch: lane 8 cycle 25 regression suite | section=vision | frozen=no
"""Lane 8 Headless-True-Audit cycle 25 - vision_server/_relay.py.

The relay is the seam between two processes RC does not fully control (the
RC-LiveClientRelay agent and the RC-LCUAgent) and the coaching pipeline that
consumes their pushes. Every test here pins a weakness found by direct read
and reproduced RED before the fix landed.

Trust boundary, stated explicitly because it bounds the severity of all of
this: ``do_POST`` auth-gates every one of these handlers
(``vision_server/_http.py:195``) and the server binds ``127.0.0.1`` by default
(``vision_server/__init__.py:68``). The realistic attacker is therefore NOT an
anonymous remote caller - it is a sibling agent on its own release cadence
sending a shape the relay never expected, which is precisely the wording
``core/liveclient_cache.py:212-214`` already uses for the same seam.
"""
from __future__ import annotations

import unittest

from vision_server import _relay
from vision_server import _stats as stats_mod


class _RelayTestBase(unittest.TestCase):
    """Resets every module global these tests touch.

    The relay keeps process-wide state, so a leaked mutation would surface as
    an unrelated failure in a sibling test file sharing the worker.
    """

    def setUp(self):
        self._orig_fetch = _relay._fetch_liveclient_direct
        self._orig_host = _relay.GAME_HOST
        self._orig_liveclient = _relay._liveclient
        _relay._reset_self_read_state()
        with _relay._lcu_lock:
            _relay._lcu_state.update({"data": None, "ts": 0.0})
            _relay._lcu_state.pop("size", None)
        with _relay._lcu_cmd_lock:
            _relay._lcu_cmd_queue.clear()
            _relay._lcu_cmd_results.clear()
        with stats_mod._stats_lock:
            for kind in ("lcu_upload", "liveclient_upload"):
                stats_mod._stats[kind].update(
                    {"calls": 0, "errors": 0, "total_ms": 0})

    def tearDown(self):
        _relay._fetch_liveclient_direct = self._orig_fetch
        _relay.GAME_HOST = self._orig_host
        _relay._liveclient = self._orig_liveclient
        _relay._reset_self_read_state()
        with _relay._lcu_cmd_lock:
            _relay._lcu_cmd_queue.clear()
            _relay._lcu_cmd_results.clear()

    def _stub_fetch(self, ret, calls=None):
        def _f():
            if calls is not None:
                calls.append(1)
            return ret
        _relay._fetch_liveclient_direct = _f


# -- W1 (RM-253): the raw-exception echo cycle 20 fixed one line above -------
class RawDecodeErrorIsNotEchoed(_RelayTestBase):
    """RM-253. ``handle_upload_lcu`` was corrected on 2026-08-30 with a block
    comment naming the defect; ``handle_upload_liveclient`` kept
    ``return {"error": f"bad_json: {e}"}`` 130 lines below, in the same file
    and the same commit. ``JSONDecodeError.__str__`` carries the offending
    byte offset and the surrounding document slice, and because this RETURNS
    rather than raises it bypasses the redaction ``_err500`` applies to every
    raised error.
    """

    BAD = b'{"gameData": {"gameTime": '

    def test_liveclient_bad_json_returns_the_fixed_token(self):
        # Positive pin, not just "no digits": a collapsed or empty message
        # would satisfy a purely negative assertion.
        self.assertEqual(_relay.handle_upload_liveclient(self.BAD),
                         {"error": "bad_json"})

    def test_liveclient_bad_json_leaks_no_parse_position(self):
        out = _relay.handle_upload_liveclient(self.BAD)
        blob = repr(out)
        self.assertFalse(any(c.isdigit() for c in blob),
                         f"decoder position leaked to the caller: {blob}")

    def test_liveclient_bad_json_logs_the_cause(self):
        with self.assertLogs(_relay.log, level="WARNING") as cm:
            _relay.handle_upload_liveclient(self.BAD)
        self.assertTrue(any("bad json" in m.lower() for m in cm.output),
                        f"cause was swallowed entirely: {cm.output}")


# -- W2: the shape guard the sibling module already has ---------------------
class NonObjectBodyIsRejected(_RelayTestBase):
    """``vision_server/_frame.py:231`` carries this exact guard with an AUDIT
    comment from cycle 20 ("a body that is valid JSON but not an object -
    [1,2], "x", 5 - decoded fine and then died on .get below"). Both relay
    upload paths were left without it, even though the self-read path at
    ``_relay.py:132`` and ``:156`` validates the very same shape - an
    asymmetry inside one module that shows this is an omission, not a choice.
    """

    NON_OBJECTS = (b'[1, 2]', b'"a string"', b'5', b'null', b'true')

    def test_liveclient_rejects_every_non_object(self):
        for body in self.NON_OBJECTS:
            with self.subTest(body=body):
                self.assertEqual(_relay.handle_upload_liveclient(body),
                                 {"error": "bad_body"})

    def test_liveclient_non_object_never_reaches_the_cache(self):
        for body in self.NON_OBJECTS:
            with self.subTest(body=body):
                _relay.handle_upload_liveclient(body)
                self.assertIsNone(_relay._liveclient.get("data"))
                self.assertEqual(_relay._liveclient.get("ts"), 0.0)

    def test_lcu_rejects_every_non_object(self):
        for body in self.NON_OBJECTS:
            with self.subTest(body=body):
                self.assertEqual(_relay.handle_upload_lcu(body),
                                 {"error": "bad_body"})
                self.assertIsNone(_relay.get_latest_lcu().get("data"))

    def test_valid_object_still_accepted(self):
        # The guard must not become a tautology that rejects everything.
        out = _relay.handle_upload_liveclient(b'{"gameData": {"gameTime": 7}}')
        self.assertTrue(out.get("ok"))
        self.assertEqual(_relay.get_latest_liveclient().get("data"),
                         {"gameData": {"gameTime": 7}})


class GarbagePushDoesNotSuppressTheSelfHeal(_RelayTestBase):
    """The consequence that makes W2 more than a tidiness fix.

    A truthy non-object was cached WITH A FRESH ``ts``. ``get_latest_liveclient``
    gates the 1-PC self-heal on ``age > _SELF_READ_STALE_S``, so that fresh ts
    suppressed the :2999 self-read for a full 2 s per garbage push - the exact
    mechanism the module docstring says keeps coaching alive when the agent
    dies. A malfunctioning agent could therefore hold the self-heal off
    indefinitely by pushing junk faster than the stale window.
    """

    def test_self_heal_still_fires_after_a_garbage_push(self):
        calls = []
        self._stub_fetch({"gameData": {"gameTime": 42}}, calls)
        _relay.GAME_HOST = "127.0.0.1"
        _relay.handle_upload_liveclient(b'"garbage"')
        out = _relay.get_latest_liveclient()
        self.assertEqual(len(calls), 1,
                         "garbage push suppressed the 1-PC self-heal")
        self.assertEqual(out.get("data"), {"gameData": {"gameTime": 42}})
        self.assertEqual(out.get("source"), "self_read")


# -- W3: the ack re-read shared state after releasing the lock --------------
class _RacingDict(dict):
    """Simulates a concurrent writer that overwrites ``ts`` the instant the
    upload releases ``_liveclient_lock``. Any read of the shared dict AFTER
    the write therefore observes the other writer's timestamp.
    """

    OTHER_WRITER_TS = 999999.0

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.reads_after_write = 0
        self._written = False

    def update(self, *a, **kw):
        super().update(*a, **kw)
        self._written = True

    def __getitem__(self, key):
        if key == "ts" and self._written:
            self.reads_after_write += 1
            return self.OTHER_WRITER_TS
        return super().__getitem__(key)


class AckReportsThisCallsTimestamp(_RelayTestBase):
    """``handle_upload_liveclient`` built its response from
    ``_liveclient["ts"]`` at :191, outside the ``with _liveclient_lock`` block
    that wrote it at :178-184. Between release and read, a second upload could
    land, so the agent's ack carried a timestamp its own push never wrote.
    """

    def test_ack_ts_is_the_value_this_call_stored(self):
        racing = _RacingDict({"data": None, "ts": 0.0, "size": 0})
        _relay._liveclient = racing
        out = _relay.handle_upload_liveclient(b'{"gameData": {}}')
        stored = dict.__getitem__(racing, "ts")
        self.assertEqual(out["ts"], stored)
        self.assertNotEqual(out["ts"], _RacingDict.OTHER_WRITER_TS)

    def test_ack_does_not_re_read_shared_state(self):
        racing = _RacingDict({"data": None, "ts": 0.0, "size": 0})
        _relay._liveclient = racing
        _relay.handle_upload_liveclient(b'{"gameData": {}}')
        self.assertEqual(racing.reads_after_write, 0)


# -- W4: the LCU relay could not record a failure ---------------------------
class LcuUploadFailuresAreCounted(_RelayTestBase):
    """``/stats`` reported ``lcu_upload`` as flawless no matter what.

    The empty-body path returned before any ``_record`` call, the bad-JSON
    path recorded nothing, and the success path passed a hardcoded ``0`` ms.
    Same class as the cycle-20 ``_inference.py`` defect ("counted a failed
    vision read as a success") - an observability surface that cannot express
    the failure it exists to report.
    """

    def _lcu(self):
        with stats_mod._stats_lock:
            return dict(stats_mod._stats["lcu_upload"])

    def test_empty_body_is_recorded_as_an_error(self):
        _relay.handle_upload_lcu(b"")
        s = self._lcu()
        self.assertEqual(s["calls"], 1)
        self.assertEqual(s["errors"], 1)

    def test_bad_json_is_recorded_as_an_error(self):
        _relay.handle_upload_lcu(b"{definitely not json")
        s = self._lcu()
        self.assertEqual(s["calls"], 1)
        self.assertEqual(s["errors"], 1)

    def test_non_object_is_recorded_as_an_error(self):
        _relay.handle_upload_lcu(b'[1,2]')
        s = self._lcu()
        self.assertEqual(s["calls"], 1)
        self.assertEqual(s["errors"], 1)

    def test_success_is_recorded_without_an_error(self):
        _relay.handle_upload_lcu(b'{"gameflow": "Lobby"}')
        s = self._lcu()
        self.assertEqual(s["calls"], 1)
        self.assertEqual(s["errors"], 0)


class UploadLatencyIsMeasuredNotHardcoded(_RelayTestBase):
    """The DURATION half of W4, added after the verifier refuted the first draft.

    The original tests asserted `calls` and `errors` but never `total_ms`, so
    replacing any measured `int((time.time() - t0) * 1000)` with a literal `0`
    left the whole suite GREEN - including the success path whose hardcoded 0
    was the defect W4 names, and which the live `/stats` evidence
    (68275 calls, total_ms 0) rests on entirely. A guard nobody exercises is
    the standing failure class here, and this one was mine.

    Asserting `total_ms > 0` would not work and would be flaky: these handlers
    complete in well under a millisecond, so the honest measurement really is
    0. The property under test is that the duration is MEASURED rather than
    fixed, so the clock is stubbed to advance a known amount and the recorded
    value is pinned exactly.
    """

    STEP = 0.25          # every time.time() call advances the clock this much
    ORIGIN = 1_000_000.0

    def _stub_clock(self):
        """`_relay.time` -> a clock whose every read advances by STEP.

        `t0` is the first read inside the handler and the duration is computed
        from a later read, so any real subtraction yields a multiple of STEP.
        A hardcoded literal yields 0 and fails.
        """
        state = {"n": 0}
        real = _relay.time

        class _Clock:
            @staticmethod
            def time():
                state["n"] += 1
                return UploadLatencyIsMeasuredNotHardcoded.ORIGIN + \
                    state["n"] * UploadLatencyIsMeasuredNotHardcoded.STEP

            monotonic = staticmethod(real.monotonic)
            strftime = staticmethod(real.strftime)

        _relay.time = _Clock
        self.addCleanup(lambda: setattr(_relay, "time", real))
        return state

    def _total_ms(self, kind):
        with stats_mod._stats_lock:
            return stats_mod._stats[kind]["total_ms"]

    def _assert_measured(self, kind, call):
        self._stub_clock()
        call()
        ms = self._total_ms(kind)
        self.assertGreater(
            ms, 0,
            f"{kind} recorded a hardcoded duration ({ms} ms) instead of a "
            "measured one")
        self.assertEqual(
            ms % int(self.STEP * 1000), 0,
            f"{kind} recorded {ms} ms, not a multiple of the stubbed step")

    # -- LCU relay: all four exits -----------------------------------------
    def test_lcu_empty_body_duration_is_measured(self):
        self._assert_measured("lcu_upload",
                              lambda: _relay.handle_upload_lcu(b""))

    def test_lcu_bad_json_duration_is_measured(self):
        self._assert_measured("lcu_upload",
                              lambda: _relay.handle_upload_lcu(b"{nope"))

    def test_lcu_bad_body_duration_is_measured(self):
        self._assert_measured("lcu_upload",
                              lambda: _relay.handle_upload_lcu(b"[1,2]"))

    def test_lcu_success_duration_is_measured(self):
        # The one the verifier caught: this exit is what /stats aggregates.
        self._assert_measured(
            "lcu_upload", lambda: _relay.handle_upload_lcu(b'{"a": 1}'))

    # -- Live Client relay: all four exits ---------------------------------
    def test_liveclient_empty_body_duration_is_measured(self):
        self._assert_measured("liveclient_upload",
                              lambda: _relay.handle_upload_liveclient(b""))

    def test_liveclient_bad_json_duration_is_measured(self):
        self._assert_measured("liveclient_upload",
                              lambda: _relay.handle_upload_liveclient(b"{nope"))

    def test_liveclient_bad_body_duration_is_measured(self):
        self._assert_measured("liveclient_upload",
                              lambda: _relay.handle_upload_liveclient(b"[1,2]"))

    def test_liveclient_success_duration_is_measured(self):
        self._assert_measured(
            "liveclient_upload",
            lambda: _relay.handle_upload_liveclient(b'{"gameData": {}}'))


# -- W5: the command queue grew without bound -------------------------------
class CommandQueueIsBounded(_RelayTestBase):
    """``_lcu_cmd_results`` right beside it evicts down to 50 once it passes
    100; ``_lcu_cmd_queue`` had no bound at all. The drain is the LCU agent,
    and an agent that is down is the documented failure mode this module
    exists to survive - so the unbounded side is the one that grows when the
    thing it depends on fails.
    """

    def test_queue_stops_growing_at_the_cap(self):
        for i in range(_relay._MAX_PENDING_CMDS + 120):
            _relay.lcu_queue_command({"cmd": "noop", "n": i})
        with _relay._lcu_cmd_lock:
            self.assertLessEqual(len(_relay._lcu_cmd_queue),
                                 _relay._MAX_PENDING_CMDS)

    def test_the_newest_commands_are_the_ones_kept(self):
        # A stale start_matchmaking from twenty minutes ago must not be what
        # survives when the agent reconnects.
        total = _relay._MAX_PENDING_CMDS + 10
        for i in range(total):
            _relay.lcu_queue_command({"cmd": "noop", "n": i})
        kept = [item["cmd"]["n"] for item in _relay.lcu_drain_pending()]
        self.assertEqual(kept[-1], total - 1)
        self.assertNotIn(0, kept)

    def test_dropping_is_logged(self):
        for i in range(_relay._MAX_PENDING_CMDS):
            _relay.lcu_queue_command({"cmd": "noop", "n": i})
        with self.assertLogs(_relay.log, level="WARNING") as cm:
            _relay.lcu_queue_command({"cmd": "noop", "n": -1})
        self.assertTrue(any("queue" in m.lower() for m in cm.output))

    def test_ids_stay_unique_and_monotonic_across_a_drop(self):
        ids = [_relay.lcu_queue_command({"cmd": "noop"})
               for _ in range(_relay._MAX_PENDING_CMDS + 5)]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual(ids, sorted(ids))


# -- W6: a wall-clock step could disable the self-heal ----------------------
class SelfReadThrottleSurvivesAClockStep(_RelayTestBase):
    """The throttle measured a pure INTERVAL with ``time.time()``.

    A backward NTP correction makes ``now - _last_self_read_attempt``
    negative, which is always ``< _SELF_READ_MIN_INTERVAL_S``, so the :2999
    self-read stays disabled until the wall clock catches back up. On a
    one-hour step that is an hour with no self-heal - and the self-heal is
    what keeps coaching alive when the relay agent is down. An interval
    belongs on ``time.monotonic``.
    """

    def test_backward_clock_step_does_not_disable_the_self_read(self):
        calls = []
        self._stub_fetch({"gameData": {"gameTime": 1}}, calls)
        _relay.GAME_HOST = "127.0.0.1"

        real_monotonic = _relay.time.monotonic
        base_wall = _relay.time.time()
        state = {"wall": base_wall, "mono": real_monotonic()}

        class _Clock:
            @staticmethod
            def time():
                return state["wall"]

            @staticmethod
            def monotonic():
                return state["mono"]

        orig_time = _relay.time
        _relay.time = _Clock
        try:
            _relay._maybe_self_read()
            self.assertEqual(len(calls), 1)
            # NTP steps the wall clock an hour backward; monotonic advances
            # past the throttle window as it always does.
            state["wall"] = base_wall - 3600.0
            state["mono"] += _relay._SELF_READ_MIN_INTERVAL_S + 0.5
            _relay._maybe_self_read()
        finally:
            _relay.time = orig_time

        self.assertEqual(len(calls), 2,
                         "a backward wall-clock step disabled the self-heal")

    def test_throttle_still_blocks_inside_the_window(self):
        # The fix must not turn the throttle off; L8 of the port-safety audit
        # pins this floor as the only direct-Riot read limiter.
        calls = []
        self._stub_fetch(None, calls)
        _relay.GAME_HOST = "127.0.0.1"
        _relay._maybe_self_read()
        _relay._maybe_self_read()
        self.assertEqual(len(calls), 1)


# -- W7: the result store handed out its own mutable rows -------------------
class ResultLookupDoesNotHandOutSharedState(_RelayTestBase):
    """``lcu_get_result`` returned the stored dict itself, so a caller that
    mutated the result corrupted the store for every later reader.
    ``get_latest_lcu`` beside it already copies.

    SCOPE, stated so a later reader does not over-trust this: the function has
    ZERO production callers today and is not re-exported by
    ``vision_server/__init__.py`` - ``_http.py:143`` hand-rolls the same
    lookup inline. This fix closes a latent API hazard; it changes no live
    behaviour until something calls it. The duplication itself is filed as
    RM-266.
    """

    def test_mutating_the_returned_result_does_not_corrupt_the_store(self):
        _relay.lcu_record_result(1, {"ok": True})
        got = _relay.lcu_get_result(1)
        got["result"] = {"ok": False, "injected": True}
        again = _relay.lcu_get_result(1)
        self.assertEqual(again["result"], {"ok": True})

    def test_missing_id_still_returns_none(self):
        self.assertIsNone(_relay.lcu_get_result(4242))


if __name__ == "__main__":
    unittest.main()
