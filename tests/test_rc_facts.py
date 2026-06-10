"""Unit tests for tools/rc_facts.py anomaly gating.

main() does live HTTP/subprocess probes, so the unit surface here is the pure
anomaly-decision helpers. Post-1PC (ADR-011) Game-PC's MCP :8892 and bridge
publisher are EXPECTED absent/stale and must not flag as anomalies unless
RC_GAMEPC_RETIRED is explicitly disabled (gamepc returned to service).
"""
from __future__ import annotations

from tools import rc_facts


# ---------------------------------------------------------------------------
# RC_GAMEPC_RETIRED env parsing

def test_parse_retired_default_and_overrides():
    assert rc_facts._parse_retired(None) is True   # unset -> retired (quiet)
    assert rc_facts._parse_retired("") is True
    assert rc_facts._parse_retired("1") is True
    assert rc_facts._parse_retired("0") is False
    assert rc_facts._parse_retired("false") is False
    assert rc_facts._parse_retired("No") is False


# ---------------------------------------------------------------------------
# Game-PC MCP probe gating

def test_gamepc_mcp_ok_never_anomalous():
    assert rc_facts._gamepc_mcp_anomaly(200, retired=True) is None
    assert rc_facts._gamepc_mcp_anomaly(200, retired=False) is None


def test_gamepc_mcp_down_suppressed_when_retired():
    assert rc_facts._gamepc_mcp_anomaly(None, retired=True) is None
    assert rc_facts._gamepc_mcp_anomaly(500, retired=True) is None


def test_gamepc_mcp_down_flags_when_armed():
    assert rc_facts._gamepc_mcp_anomaly(None, retired=False) == \
        "Game-PC: MCP /health returned None"
    assert rc_facts._gamepc_mcp_anomaly(503, retired=False) == \
        "Game-PC: MCP /health returned 503"


# ---------------------------------------------------------------------------
# Bridge-peer gating

def test_bridge_gamepc_stale_suppressed_when_retired():
    assert rc_facts._bridge_peer_anomalies(
        "gamepc", watcher_alive=True, stale=True, age_str="784380s",
        queue=0, retired=True) == []


def test_bridge_gamepc_dead_suppressed_when_retired():
    assert rc_facts._bridge_peer_anomalies(
        "gamepc", watcher_alive=False, stale=False, age_str="?",
        queue=0, retired=True) == []


def test_bridge_gamepc_stale_flags_when_armed():
    assert rc_facts._bridge_peer_anomalies(
        "gamepc", watcher_alive=True, stale=True, age_str="784380s",
        queue=0, retired=False) == ["Bridge: gamepc health publisher stale (784380s)"]


def test_bridge_atx_stale_always_flags_regardless_of_retired():
    # The retired flag is gamepc-specific; Peer is live and must still flag.
    assert rc_facts._bridge_peer_anomalies(
        "peer", watcher_alive=True, stale=True, age_str="600s",
        queue=0, retired=True) == ["Bridge: peer health publisher stale (600s)"]


def test_bridge_queue_backlog_flags_even_for_retired_gamepc():
    # A backed-up queue on a "retired" peer is genuinely odd - keep surfacing it.
    assert rc_facts._bridge_peer_anomalies(
        "gamepc", watcher_alive=True, stale=False, age_str="5s",
        queue=42, retired=True) == ["Bridge: gamepc task queue backed up (42 tasks)"]
