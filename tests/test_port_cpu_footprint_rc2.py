# arch: consolidated port/CPU footprint regression guard (RC2 P6.6) | section=test | frozen=no
"""RC2 6.6 - verify no port/CPU footprint regression across Phase 6.

Phase 6 tightened poll/render cadences (6.2 RuneWriter 2.0s->1.0s,
6.3 state cadence 1.0s->0.5s) and added latency overlap (6.5 relay pool).
Each tightening could multiply loopback sockets or CPU if its safeguard
drifts. The per-stage tests lock each lever in isolation; THIS file is the
single consolidated guard that re-asserts every footprint invariant
together so a future edit to any one lever cannot silently regress the
aggregate footprint. Deliverable companion:
docs/research/RC2_PORT_CPU_FOOTPRINT_VERIFICATION.md.

Pure introspection - no sockets, no sleeps, no game required.
"""
from __future__ import annotations

import concurrent.futures
import importlib
import unittest


class LcuPoolDefaultOnTests(unittest.TestCase):
    """6.4 L6 - connection pooling is DEFAULT-ON since E7 (2026-06-30,
    validated live). The footprint stays BOUNDED: default-on means exactly
    ONE long-lived socket per LCU port (reuse), NOT the per-call TCP+TLS
    handshake churn it replaced. Explicit RC_LCU_POOL=0 restores the legacy
    per-call path."""

    def test_pool_enabled_by_default(self):
        from core import lcu_pool
        import os
        os.environ.pop("RC_LCU_POOL", None)
        self.assertTrue(lcu_pool.pool_enabled())

    def test_shared_pool_is_lazy(self):
        # The singleton must not be eagerly built (no socket reserved) just
        # by importing the module - only get_shared_pool() may construct it.
        from core import lcu_pool
        importlib.reload(lcu_pool)
        self.assertIsNone(lcu_pool._shared_pool)

    def test_min_interval_guard_enforces_floor(self):
        # L7: one shared guard caps the effective read rate - ready() is
        # True at most once per interval, so stacked callers cannot push
        # past the floor (no consolidated-reader storm).
        from core import lcu_pool
        clock = {"t": 100.0}
        g = lcu_pool.MinIntervalGuard(1.5, clock=lambda: clock["t"])
        self.assertTrue(g.ready("k"))
        clock["t"] += 1.0          # under floor
        self.assertFalse(g.ready("k"))
        clock["t"] += 0.6          # now past 1.5s total
        self.assertTrue(g.ready("k"))


class RelaySelfReadFloorTests(unittest.TestCase):
    """6.4 L8 - the only DIRECT Riot :2999 reader keeps its >=1.5s hard
    floor. Re-asserted here (also locked in test_lcu_pool.py) so the
    consolidated footprint guard fails loud if the floor ever drops."""

    def test_self_read_floor_at_least_1_5s(self):
        from vision_server import _relay
        self.assertGreaterEqual(_relay._SELF_READ_MIN_INTERVAL_S, 1.5)

    def test_self_read_timeout_bounded(self):
        # A hung :2999 read cannot pin a thread indefinitely.
        from vision_server import _relay
        self.assertLessEqual(_relay._SELF_READ_TIMEOUT_S, 1.5)


class RelayPoolBoundedTests(unittest.TestCase):
    """6.5 - the state-pipeline overlap uses a SMALL bounded thread pool.
    A bounded worker count is what keeps the latency overlap from becoming
    a fan-out (the build is TTL-gated to ~2/s; the relay opens the SAME two
    connections, briefly overlapped, never multiplied)."""

    def test_relay_pool_is_threadpool(self):
        from dashboard import _state_builder
        self.assertIsInstance(
            _state_builder._RELAY_POOL,
            concurrent.futures.ThreadPoolExecutor,
        )

    def test_relay_pool_worker_count_bounded(self):
        from dashboard import _state_builder
        # Small fixed cap - a handful of overlapped round-trips, never a
        # per-request thread fan-out.
        self.assertLessEqual(_state_builder._RELAY_POOL._max_workers, 4)

    def test_relay_pool_named_for_audit(self):
        from dashboard import _state_builder
        # Named so a thread dump can attribute these workers (not a runaway).
        self.assertEqual(
            _state_builder._RELAY_POOL._thread_name_prefix, "rc-state-relay")


class StateCadenceFootprintTests(unittest.TestCase):
    """6.3 - the faster render cadence adds NO sockets (SSE is push over one
    long-lived stream) and the TTL+tick share ONE constant so they cannot
    drift into double the build rate. A floor clamp bounds CPU."""

    def test_sse_tick_equals_ttl(self):
        from dashboard import routes_state
        self.assertEqual(routes_state._SSE_TICK_S, routes_state._STATE_CADENCE_S)

    def test_cadence_floor_clamped(self):
        # Even a garbage / zero override cannot drive an unbounded build loop.
        from dashboard import routes_state
        self.assertGreaterEqual(routes_state._STATE_CADENCE_S, 0.1)

    def test_cadence_default_half_second(self):
        import os
        os.environ.pop("RC_STATE_CADENCE_SEC", None)
        from dashboard import routes_state
        self.assertEqual(routes_state._state_cadence_s(), 0.5)

    def test_sse_connection_lifetime_bounded(self):
        # Long-lived SSE streams are capped so dispatcher threads cannot
        # accumulate across a long session (CPU/thread footprint bound).
        from dashboard import routes_state
        self.assertLessEqual(routes_state._SSE_MAX_DURATION_S, 600.0)


class RuneWriterCadenceFootprintTests(unittest.TestCase):
    """6.2 - the champ-select auto-apply cadence stays a single loop on the
    lockfile port with a positive floor (no zero-sleep busy spin)."""

    def test_poll_interval_positive_and_capped(self):
        import lcu.lcu_rune_writer as rw
        self.assertGreater(rw.RuneWriter.POLL_INTERVAL, 0.0)
        self.assertLessEqual(rw.RuneWriter.POLL_INTERVAL, 1.0)


if __name__ == "__main__":
    unittest.main()
