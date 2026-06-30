"""RC2 E7a - ARAM bench-swap queue-drain latency tightening.

The Legion command-queue drain loop (`_cmd_poll_loop`) used to sleep the
full CMD_INTERVAL (0.5s) after EVERY drain, so a freshly-clicked ARAM
bench swap could sit a full 0.5s behind the queue before its POST fired.
E7a refactors the drain body into a testable `drain_once` helper and
re-polls FAST (BENCH_CMD_FAST_INTERVAL) when the drained batch held a
latency-sensitive command (bench_swap / reroll / accept_ready), while
keeping the full idle sleep when nothing was processed (no busy-spin).

These tests inject fakes for get / post / exec - no network, no real
sleep. The agent is stdlib-only and lives under tools/ (no __init__.py),
so it is imported via an explicit sys.path insert like the sibling
phase-B test module.
"""
from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "tools"))

import lcu_agent as agent  # noqa: E402


def _fake_get_returning(commands):
    """A get_fn that returns one /lcu-cmd-pending batch then empties."""
    state = {"served": False}

    def _get(path):
        assert path == "/lcu-cmd-pending", path
        if state["served"]:
            return {"commands": []}
        state["served"] = True
        return {"commands": commands}

    return _get


class TestModuleConstants(unittest.TestCase):
    def test_fast_interval_present_and_shorter_than_cmd_interval(self):
        self.assertTrue(hasattr(agent, "BENCH_CMD_FAST_INTERVAL"))
        self.assertLess(agent.BENCH_CMD_FAST_INTERVAL, agent.CMD_INTERVAL)
        # Spec value.
        self.assertEqual(agent.BENCH_CMD_FAST_INTERVAL, 0.1)
        self.assertEqual(agent.CMD_INTERVAL, 0.5)

    def test_latency_sensitive_cmd_set(self):
        self.assertEqual(
            set(agent.LATENCY_SENSITIVE_CMDS),
            {"bench_swap", "reroll", "accept_ready"})


class TestDrainOnce(unittest.TestCase):
    def test_bench_swap_batch_marks_fast(self):
        get_fn = _fake_get_returning(
            [{"id": "c1", "cmd": {"cmd": "bench_swap", "championId": 105}}])
        posted = []
        execed = []

        def _post(path, body):
            posted.append((path, body))

        def _exec(cmd):
            execed.append(cmd)
            return {"ok": True}

        processed, fast = agent.drain_once(get_fn, _post, _exec)
        self.assertEqual(processed, 1)
        self.assertTrue(fast)
        # Result was posted back for the command id.
        self.assertEqual(posted[0][0], "/lcu-cmd-done")
        self.assertEqual(posted[0][1]["id"], "c1")
        self.assertTrue(posted[0][1]["result"]["ok"])
        self.assertEqual(execed[0]["cmd"], "bench_swap")

    def test_reroll_and_accept_ready_also_fast(self):
        for name in ("reroll", "accept_ready"):
            get_fn = _fake_get_returning(
                [{"id": "x", "cmd": {"cmd": name}}])
            _processed, fast = agent.drain_once(
                get_fn, lambda *_: None, lambda _c: {"ok": True})
            self.assertTrue(fast, f"{name} should be latency-sensitive")

    def test_idle_empty_batch_not_fast(self):
        def _get(_path):
            return {"commands": []}

        posted = []
        processed, fast = agent.drain_once(
            _get, lambda p, b: posted.append((p, b)),
            lambda _c: {"ok": True})
        self.assertEqual(processed, 0)
        self.assertFalse(fast)
        self.assertEqual(posted, [])

    def test_non_latency_batch_processed_but_not_fast(self):
        get_fn = _fake_get_returning(
            [{"id": "c2", "cmd": {"cmd": "set_summoners", "d": 4, "f": 7}}])
        processed, fast = agent.drain_once(
            get_fn, lambda *_: None, lambda _c: {"ok": True})
        self.assertEqual(processed, 1)
        self.assertFalse(fast)

    def test_exec_exception_still_posts_done_contract_preserved(self):
        """A bench_swap whose execute_command RAISES must still POST the
        /lcu-cmd-done result so /api/lcu-cmd-result flows never hang."""
        get_fn = _fake_get_returning(
            [{"id": "c3", "cmd": {"cmd": "bench_swap", "championId": 1}}])
        posted = []

        def _post(path, body):
            posted.append((path, body))

        def _boom(_cmd):
            raise RuntimeError("LCU down")

        processed, fast = agent.drain_once(get_fn, _post, _boom)
        self.assertEqual(processed, 1)
        # Latency-sensitive cmd type drives fast re-poll even on failure.
        self.assertTrue(fast)
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted[0][0], "/lcu-cmd-done")
        self.assertEqual(posted[0][1]["id"], "c3")
        self.assertFalse(posted[0][1]["result"]["ok"])
        self.assertIn("RuntimeError", posted[0][1]["result"]["err"])

    def test_post_failure_swallowed(self):
        """If the result POST itself raises, drain_once must not propagate
        (the loop keeps draining)."""
        get_fn = _fake_get_returning(
            [{"id": "c4", "cmd": {"cmd": "bench_swap", "championId": 1}}])

        def _post(_path, _body):
            raise RuntimeError("post failed")

        processed, fast = agent.drain_once(
            get_fn, _post, lambda _c: {"ok": True})
        self.assertEqual(processed, 1)
        self.assertTrue(fast)


class TestBenchSwapDispatch(unittest.TestCase):
    def test_bench_swap_posts_canonical_path(self):
        """(d) bench_swap dispatches exactly POST
        /lol-champ-select/v1/session/bench/swap/{cid}."""
        from unittest import mock
        with mock.patch.object(agent, "lcu_request") as mreq:
            mreq.return_value = ({}, None)
            out = agent.execute_command(
                {"cmd": "bench_swap", "championId": 105})
        self.assertTrue(out["ok"])
        method, path = mreq.call_args[0][0], mreq.call_args[0][1]
        self.assertEqual(method, "POST")
        self.assertEqual(
            path, "/lol-champ-select/v1/session/bench/swap/105")


class TestSwapWakeSignal(unittest.TestCase):
    """RC2 E7 TODO-1 - after a latency-sensitive drain the cmd loop wakes
    the state-push loop immediately via a threading.Event, so a freshly
    swapped champ reflects in /api/state in ~BENCH_CMD_FAST_INTERVAL rather
    than waiting the full state-push INTERVAL. Only ONE thread
    (_state_push_loop) ever calls capture_state(), so no new races: the
    cmd loop just SETS the event."""

    def setUp(self):
        agent._swap_wake.clear()

    def tearDown(self):
        agent._swap_wake.clear()

    def test_swap_wake_is_threading_event(self):
        self.assertIsInstance(agent._swap_wake, threading.Event)

    def test_fast_drain_signals_wake(self):
        woke = agent._signal_state_refresh(fast=True, processed=1)
        self.assertTrue(woke)
        self.assertTrue(agent._swap_wake.is_set())

    def test_slow_drain_does_not_wake(self):
        woke = agent._signal_state_refresh(fast=False, processed=3)
        self.assertFalse(woke)
        self.assertFalse(agent._swap_wake.is_set())

    def test_empty_fast_flag_does_not_wake(self):
        # Defensive: a fast flag with nothing processed must not wake
        # (drain_once only sets fast when an item was iterated, but the
        # guard keeps the contract explicit).
        woke = agent._signal_state_refresh(fast=True, processed=0)
        self.assertFalse(woke)
        self.assertFalse(agent._swap_wake.is_set())


if __name__ == "__main__":
    unittest.main()
