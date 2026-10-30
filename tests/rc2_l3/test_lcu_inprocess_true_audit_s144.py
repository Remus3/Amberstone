"""s144 true-audit cycle 70 - dashboard/_lcu_inprocess.py hardening.

Four findings, each pinned red-then-green against the module:

  F1  ``lcu_port`` and the shaped body came off a SHARED, MUTABLE client
      with no consistency check. ``client._port`` was read once for the gate
      and again for the stamp, and the shape ran after both, so a League
      close or a lockfile rotation inside the read (another caller's
      ``_get_client`` refresh, or ``LcuClient._request``'s own retry refresh)
      produced either ``lcu_port == "None"`` - a truthy port string for a
      closed client, where the "client closed" signal is lcu_port ABSENCE
      (``tools/lcu_agent.capture_state``) - or a snapshot stamped with the
      OLD port over a body read from nothing or from a different client.
      Now the port is captured once and a read that straddles a port change
      is discarded (None -> relay fallback), silently, because a League
      close is an expected event.

  F2  No time budget. Every ``LcuClient._request`` may take its 3 s timeout
      plus one idempotent retry, ``shape_snapshot`` makes several calls, and
      ``tools/lcu_agent.capture_state`` itself records that in-game captures
      run 8-11 s under League CPU pressure. In-process, that time is spent
      inside ``build_state`` under ``routes_state._STATE_BUILD_LOCK``, so
      flipping ``RC_LCU_INPROCESS`` would stall every /api/state build and
      every SSE tick for the length of the read. Now one read has a budget
      (``_SNAPSHOT_BUDGET_S``): the adapter refuses to START an LCU call once
      it is spent, the partial read is discarded, and a cooldown
      (``_BUDGET_COOLDOWN_S``) sends the following builds straight to the
      relay so a slow LCU costs one budget per cooldown, not one per build.

  F3  ``_agent_config`` could commit an OLDER relay read over a newer one.
      Three callers reach it concurrently (routes_state's builder, the OBS
      publisher's own build_state, routes_lobby_aux), so two TTL refreshes
      can overlap; whichever lands last won and re-stamped the TTL, so an
      operator's auto-accept click could read back as the pre-click value
      for up to ``_CONFIG_TTL_S``. Now each refresh takes a ticket and only
      a newer ticket may commit.

  F4  ``_get_client`` ran ``connect()`` outside the lock on the shared
      client, so two concurrent cold callers both connected (duplicate
      "LCU connected" lines, interleaved port / auth assignment). Now the
      connect-or-refresh step runs under ``_client_lock``.

Spies are RECORDING, never raising, except where a raise IS the stimulus:
an ``AssertionError`` is an ``Exception`` and would be swallowed by the
fail-soft ``except`` under test.

All authored content here is 7-bit ASCII.
"""
from __future__ import annotations

import logging
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import dashboard._lcu_inprocess as inp  # noqa: E402

_LOGGER = "rc.web_dashboard"


def _budget() -> float:
    # getattr so the pre-fix module goes red on BEHAVIOUR, not on a missing name
    return getattr(inp, "_SNAPSHOT_BUDGET_S", 1.0)


def _cooldown() -> float:
    return getattr(inp, "_BUDGET_COOLDOWN_S", 30.0)


class _FakeClock:
    """Monotonic stand-in the tests advance by hand."""

    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class _Client:
    """Stand-in LcuClient: records calls, optionally mutates on request."""

    def __init__(self, port=5000, on_request=None):
        self._port = port
        self.calls: list[str] = []
        self._on_request = on_request

    def connect(self):
        return bool(self._port)

    def _refresh_conn_if_changed(self):
        return False

    def _request(self, method, endpoint, data=None, _retry=True):
        self.calls.append(endpoint)
        if self._on_request is not None:
            self._on_request(self, endpoint)
        return {"ok": True}


def _shape_n_calls(n):
    """A shape_snapshot stand-in that makes n LCU calls, then returns."""
    def _shape(request, config):
        for i in range(n):
            request("GET", f"/p{i}")
        return {"phase": "Lobby"}
    return _shape


class _Base(unittest.TestCase):
    def setUp(self):
        inp._reset_client_for_tests()
        self.addCleanup(inp._reset_client_for_tests)
        self.clock = _FakeClock()
        p = mock.patch.object(inp, "_clock", self.clock, create=True)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(inp, "_agent_config",
                              return_value={"auto_accept": False})
        self.agent_config = p.start()
        self.addCleanup(p.stop)

    def _run(self, client, shape):
        with mock.patch.object(inp, "_get_client", return_value=client), \
                mock.patch.object(inp, "shape_snapshot", shape):
            return inp.lcu_summary_inprocess()


class TestF1PortConsistency(_Base):
    def test_stable_port_keeps_contract_and_key_order(self):
        client = _Client(port=5000)
        snap = self._run(client, _shape_n_calls(2))
        self.assertIsNotNone(snap)
        self.assertEqual(list(snap)[:3], ["config", "lcu_port", "phase"])
        self.assertEqual(snap["lcu_port"], "5000")
        self.assertEqual(snap["config"], {"auto_accept": False})

    def test_port_cleared_between_gate_and_stamp_is_never_stamped_none(self):
        client = _Client(port=5000)

        def _config_and_close():
            client._port = None   # League closed while config was read
            return {"auto_accept": False}

        self.agent_config.side_effect = _config_and_close
        snap = self._run(client, _shape_n_calls(1))
        self.assertIsNone(snap, "a read that straddles a close must fall back")

    def test_league_close_mid_shape_discards_the_read(self):
        def _close(c, endpoint):
            c._port = None
        client = _Client(port=5000, on_request=_close)
        snap = self._run(client, _shape_n_calls(2))
        self.assertIsNone(snap)

    def test_port_rotation_mid_shape_discards_the_read(self):
        def _rotate(c, endpoint):
            c._port = 6000
        client = _Client(port=5000, on_request=_rotate)
        snap = self._run(client, _shape_n_calls(2))
        self.assertIsNone(snap)

    def test_straddle_is_silent(self):
        def _close(c, endpoint):
            c._port = None
        client = _Client(port=5000, on_request=_close)
        with self.assertNoLogs(_LOGGER, level="WARNING"):
            self.assertIsNone(self._run(client, _shape_n_calls(1)))


class TestF2Budget(_Base):
    def _slow_client(self, step):
        def _advance(c, endpoint):
            self.clock.t += step
        return _Client(port=5000, on_request=_advance)

    def test_fast_read_within_budget_returns_snapshot(self):
        client = _Client(port=5000)
        snap = self._run(client, _shape_n_calls(5))
        self.assertIsNotNone(snap)
        self.assertEqual(len(client.calls), 5)

    def test_slow_lcu_stops_starting_calls_once_budget_is_spent(self):
        client = self._slow_client(_budget() + 1.0)
        snap = self._run(client, _shape_n_calls(10))
        self.assertIsNone(snap, "an over-budget partial read must be dropped")
        self.assertEqual(len(client.calls), 1,
                         "no LCU call may START after the budget is spent")

    def test_budget_trip_warns_once_without_payload(self):
        client = self._slow_client(_budget() + 1.0)
        with self.assertLogs(_LOGGER, level="WARNING") as cm:
            self._run(client, _shape_n_calls(10))
        self.assertEqual(len(cm.records), 1)
        msg = cm.records[0].getMessage()
        self.assertIn("_SnapshotBudgetExceeded", msg)
        self.assertNotIn("/p1", msg)

    def test_cooldown_sends_next_builds_straight_to_relay(self):
        slow = self._slow_client(_budget() + 1.0)
        self.assertIsNone(self._run(slow, _shape_n_calls(10)))
        fresh = _Client(port=5000)
        get_client = mock.Mock(return_value=fresh)
        with mock.patch.object(inp, "_get_client", get_client), \
                mock.patch.object(inp, "shape_snapshot", _shape_n_calls(3)):
            self.clock.t += 1.0
            self.assertIsNone(inp.lcu_summary_inprocess())
            self.assertEqual(fresh.calls, [])
            get_client.assert_not_called()
            self.clock.t += _cooldown()
            snap = inp.lcu_summary_inprocess()
        self.assertIsNotNone(snap, "the in-process path resumes after cooldown")
        self.assertEqual(len(fresh.calls), 3)

    def test_slow_but_complete_read_is_kept_and_arms_cooldown(self):
        client = self._slow_client(_budget() + 1.0)
        snap = self._run(client, _shape_n_calls(1))
        self.assertIsNotNone(snap, "a complete read is valid data")
        again = _Client(port=5000)
        self.clock.t += 1.0
        self.assertIsNone(self._run(again, _shape_n_calls(1)))
        self.assertEqual(again.calls, [])

    def test_slow_relay_config_read_is_not_charged_to_the_lcu_budget(self):
        def _slow_config():
            self.clock.t += _budget() + 1.0   # a wedged relay, fast LCU
            return {"auto_accept": False}

        self.agent_config.side_effect = _slow_config
        client = _Client(port=5000)
        snap = self._run(client, _shape_n_calls(3))
        self.assertIsNotNone(snap, "a slow relay is not a slow LCU")
        self.assertEqual(len(client.calls), 3)
        again = _Client(port=5000)
        self.agent_config.side_effect = None
        self.assertIsNotNone(self._run(again, _shape_n_calls(1)),
                             "a slow relay read must not arm the cooldown")

    def test_budget_constants_are_sane(self):
        self.assertGreater(inp._SNAPSHOT_BUDGET_S, 0.0)
        self.assertLess(inp._SNAPSHOT_BUDGET_S, 3.0)
        self.assertGreater(inp._BUDGET_COOLDOWN_S, inp._SNAPSHOT_BUDGET_S)


class TestF3ConfigOrdering(unittest.TestCase):
    def setUp(self):
        inp._reset_client_for_tests()
        self.addCleanup(inp._reset_client_for_tests)

    def test_older_overlapping_read_never_overwrites_newer(self):
        a_in = threading.Event()
        release_a = threading.Event()
        calls = {"n": 0}
        lock = threading.Lock()

        def _relay():
            with lock:
                calls["n"] += 1
                n = calls["n"]
            if n == 1:
                a_in.set()
                release_a.wait(5)
                return {"config": {"auto_accept": False}}   # older read
            return {"config": {"auto_accept": True}}        # newer read

        out = {}
        with mock.patch.object(inp, "_read_relay_snapshot", _relay):
            t = threading.Thread(
                target=lambda: out.setdefault("a", inp._agent_config()),
                name="s144-cfg-a", daemon=True)
            t.start()
            self.assertTrue(a_in.wait(5))
            b = inp._agent_config()
            release_a.set()
            t.join(5)
            self.assertFalse(t.is_alive())
            after = inp._agent_config()      # inside TTL: served from cache
        self.assertEqual(b, {"auto_accept": True})
        self.assertEqual(after, {"auto_accept": True},
                         "the older read landed last and overwrote the newer")
        self.assertEqual(calls["n"], 2)

    def test_sequential_refresh_still_commits(self):
        seq = iter([{"config": {"auto_accept": False}},
                    {"config": {"auto_accept": True}}])
        with mock.patch.object(inp, "_read_relay_snapshot",
                               lambda: next(seq)):
            self.assertEqual(inp._agent_config(), {"auto_accept": False})
            inp._expire_config_cache_for_tests()
            self.assertEqual(inp._agent_config(), {"auto_accept": True})


class TestF4ConnectSerialized(unittest.TestCase):
    def setUp(self):
        inp._reset_client_for_tests()
        self.addCleanup(inp._reset_client_for_tests)

    def test_concurrent_cold_callers_connect_once(self):
        first_in = threading.Event()
        second_in = threading.Event()
        counts = {"connect": 0, "refresh": 0}
        lock = threading.Lock()

        class _Slow:
            _port = None

            def connect(self):
                with lock:
                    counts["connect"] += 1
                    n = counts["connect"]
                if n == 1:
                    first_in.set()
                    second_in.wait(0.5)    # overlap window
                else:
                    second_in.set()
                self._port = 5000
                return True

            def _refresh_conn_if_changed(self):
                with lock:
                    counts["refresh"] += 1
                return False

        stub = _Slow()
        with mock.patch.object(inp, "_client", stub):
            t1 = threading.Thread(target=inp._get_client,
                                  name="s144-conn-1", daemon=True)
            t1.start()
            self.assertTrue(first_in.wait(5))
            t2 = threading.Thread(target=inp._get_client,
                                  name="s144-conn-2", daemon=True)
            t2.start()
            t1.join(5)
            t2.join(5)
        self.assertEqual(counts["connect"], 1,
                         "two cold callers connected the shared client twice")
        self.assertEqual(counts["refresh"], 1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
