"""Unit tests for tools/rc_facts.py anomaly gating.

main() does live HTTP/subprocess probes, so the unit surface here is the pure
anomaly-decision helper _bridge_peer_anomalies. Post-1PC (ADR-011) the Game-PC
peer + its MCP :8892 were severed; Peer is the sole remaining bridge peer, and a
dead watcher, a stale publisher, or a real queue backlog on Peer must still flag.
"""
from __future__ import annotations

from tools import rc_facts


# ---------------------------------------------------------------------------
# Bridge-peer gating (Peer is the sole remaining peer post-1PC)

def test_bridge_atx_watcher_dead_flags():
    assert rc_facts._bridge_peer_anomalies(
        "peer", watcher_alive=False, stale=False, age_str="?",
        queue=0) == ["Bridge: peer watcher dead"]


def test_bridge_atx_stale_flags():
    assert rc_facts._bridge_peer_anomalies(
        "peer", watcher_alive=True, stale=True, age_str="600s",
        queue=0) == ["Bridge: peer health publisher stale (600s)"]


def test_bridge_atx_fresh_no_anomaly():
    assert rc_facts._bridge_peer_anomalies(
        "peer", watcher_alive=True, stale=False, age_str="5s",
        queue=0) == []


def test_bridge_atx_queue_backlog_flags():
    assert rc_facts._bridge_peer_anomalies(
        "peer", watcher_alive=True, stale=False, age_str="5s",
        queue=42) == ["Bridge: peer task queue backed up (42 tasks)"]


def test_bridge_atx_dead_watcher_takes_precedence_over_queue():
    # A dead watcher AND a backlog: both surface (watcher line first).
    assert rc_facts._bridge_peer_anomalies(
        "peer", watcher_alive=False, stale=True, age_str="600s",
        queue=42) == ["Bridge: peer watcher dead",
                      "Bridge: peer task queue backed up (42 tasks)"]
