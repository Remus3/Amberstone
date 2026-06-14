"""Audit7 H-01 - bridge health-publisher staleness alarm.

A peer's bridge health publisher POSTs its watcher heartbeat ~every 60s
to /api/health/peer/<node> (persisted at ops/runtime/peer_health/<node>
.json). When that file goes silent the bridge *task loop* may still be
alive - only the publisher sub-process died (2026-05-18 incident: gamepc
silent ~2.7h while peer was fresh at 25s). The rc_facts probe rendered
the staleness but nothing on the dashboard flipped and nothing escalated
- the exact false-confidence shape the auditor charter warns about.

Two pure decision seams encode the fix; both are unit-tested here. The
rollup "dot flips yellow" integration is live-verified against the
still-stale publisher (proposal acceptance #4), not mocked - a heavily
stubbed _serve_health_all test would be weaker evidence than the real
endpoint.

  Part A - dashboard/routes_state._peer_health_status: the graded
           green/yellow/red ladder that feeds peers.<node>.status and
           (via peer_degraded) the top-right rollup dot.
  Part B - agents.supervisor._bridge_pub_should_file: the dedup / re-arm
           decision the watchdog loop uses to file at most one Agent-1
           task per node per outage.
"""
from __future__ import annotations

import inspect
import unittest

from dashboard.routes_state import (
    _PEER_HEALTH_ALERT_S,
    _PEER_HEALTH_WARN_S,
    _peer_health_status,
)
from agents.supervisor import (
    _BRIDGE_PUB_ALERT_S,
    _BRIDGE_PUB_REFILE_COOLDOWN_S,
    _DETERMINISTIC_RECORDKEEPING_OPS,
    Supervisor,
    _bridge_pub_should_file,
)


class PeerHealthStatusLadderTests(unittest.TestCase):
    """Part A - graded status. <=WARN green, <=ALERT yellow, >ALERT red."""

    def test_fresh_is_green(self):
        self.assertEqual(_peer_health_status(0), "green")
        self.assertEqual(_peer_health_status(60), "green")

    def test_warn_boundary_inclusive_green(self):
        # 299/300 green (<= WARN), 301 yellow - preserves the prior
        # hardcoded `stale = age_s > 300` boundary exactly.
        self.assertEqual(_peer_health_status(_PEER_HEALTH_WARN_S - 1), "green")
        self.assertEqual(_peer_health_status(_PEER_HEALTH_WARN_S), "green")
        self.assertEqual(_peer_health_status(_PEER_HEALTH_WARN_S + 1), "yellow")

    def test_alert_boundary_inclusive_yellow(self):
        self.assertEqual(_peer_health_status(_PEER_HEALTH_ALERT_S - 1), "yellow")
        self.assertEqual(_peer_health_status(_PEER_HEALTH_ALERT_S), "yellow")
        self.assertEqual(_peer_health_status(_PEER_HEALTH_ALERT_S + 1), "red")

    def test_live_anomaly_value_is_red(self):
        # The session-start anomaly fired at ~9792s.
        self.assertEqual(_peer_health_status(9792), "red")

    def test_thresholds_are_ordered(self):
        self.assertLess(_PEER_HEALTH_WARN_S, _PEER_HEALTH_ALERT_S)


class BridgePubShouldFileTests(unittest.TestCase):
    """Part B - the proposal's three test-plan cases + re-arm."""

    def test_below_alarm_threshold_does_not_file_and_rearms(self):
        # Proposal "mtime 700s ago": the dashboard goes yellow via Part A,
        # but the *alarm* threshold is 1800 - no Agent-1 task, and the
        # node is (re-)armed so a later real outage still fires.
        should_file, rearm = _bridge_pub_should_file(700.0, None, 10_000.0)
        self.assertFalse(should_file)
        self.assertTrue(rearm)

    def test_stale_never_filed_files_exactly_once(self):
        # Proposal "mtime 2000s ago" -> queue exactly one task.
        should_file, rearm = _bridge_pub_should_file(2000.0, None, 10_000.0)
        self.assertTrue(should_file)
        self.assertFalse(rearm)

    def test_second_call_within_cooldown_is_suppressed(self):
        # Proposal "second consecutive call still 2000s+ ago" -> dedup
        # suppresses the second filing.
        prev = 10_000.0
        now = prev + 60.0  # 60s later, well inside the 6h cooldown
        should_file, rearm = _bridge_pub_should_file(2000.0, prev, now)
        self.assertFalse(should_file)
        self.assertFalse(rearm)

    def test_refiles_after_cooldown_elapsed(self):
        prev = 10_000.0
        now = prev + _BRIDGE_PUB_REFILE_COOLDOWN_S + 1.0
        should_file, rearm = _bridge_pub_should_file(5000.0, prev, now)
        self.assertTrue(should_file)
        self.assertFalse(rearm)

    def test_recovery_rearms_so_a_fresh_outage_alarms_again(self):
        # Node had fired; publisher recovered (age back under alert).
        # rearm=True -> loop clears fired_at -> next outage files anew.
        should_file, rearm = _bridge_pub_should_file(120.0, 10_000.0, 11_000.0)
        self.assertFalse(should_file)
        self.assertTrue(rearm)

    def test_alert_boundary_inclusive_healthy(self):
        # age == alert exactly -> healthy side (<=), so re-arm not file.
        sf, ra = _bridge_pub_should_file(_BRIDGE_PUB_ALERT_S, None, 1.0)
        self.assertFalse(sf)
        self.assertTrue(ra)
        sf, ra = _bridge_pub_should_file(_BRIDGE_PUB_ALERT_S + 1, None, 1.0)
        self.assertTrue(sf)
        self.assertFalse(ra)


class WatchdogWiringTests(unittest.TestCase):
    """The filed task must complete cleanly (record-keeping op), and the
    watchdog must actually be an async loop the supervisor can launch."""

    def test_op_is_registered_recordkeeping(self):
        # Without this the Round-43 strict allowlist in _run_deterministic
        # raises "no deterministic handler for op=..." and the alarm task
        # fails loudly instead of completing as an audit-trail breadcrumb.
        self.assertIn("bridge-publisher-stale", _DETERMINISTIC_RECORDKEEPING_OPS)

    def test_watchdog_is_a_coroutine_method(self):
        self.assertTrue(
            inspect.iscoroutinefunction(Supervisor._bridge_publisher_watchdog)
        )


if __name__ == "__main__":
    unittest.main()
