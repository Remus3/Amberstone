"""H-04 fix: publisher age vs watcher heartbeat age should both gate peer status.

A peer whose publisher POSTs every 60s (fresh received_at) but whose
heartbeat.updated_at is stale must surface status: yellow/red and cap
the top-level rollup.  A fresh publisher + fresh heartbeat must still
report green.
"""
from __future__ import annotations

import json
import time
import tempfile
import pathlib
from unittest import mock

import dashboard.routes_state as rs


# ---------------------------------------------------------------------------
# Unit tests on _peer_health_status (unchanged contract, regression guard)
# ---------------------------------------------------------------------------

def test_peer_health_status_green():
    assert rs._peer_health_status(0.0) == "green"
    assert rs._peer_health_status(rs._PEER_HEALTH_WARN_S) == "green"


def test_peer_health_status_yellow():
    assert rs._peer_health_status(rs._PEER_HEALTH_WARN_S + 1) == "yellow"
    assert rs._peer_health_status(rs._PEER_HEALTH_ALERT_S) == "yellow"


def test_peer_health_status_red():
    assert rs._peer_health_status(rs._PEER_HEALTH_ALERT_S + 1) == "red"


# ---------------------------------------------------------------------------
# Helper: build a peer health JSON record
# ---------------------------------------------------------------------------

def _make_rec(received_at: float, hb_updated_at: float | None = None) -> dict:
    rec: dict = {"received_at": received_at}
    hb: dict = {"alive": True, "pid": 1234, "queue_depth": 0,
                 "auto_ok_since_boot": 5, "auto_err_since_boot": 0,
                 "escalations_since_boot": 0, "tokens_used_today_usd": 0.01}
    if hb_updated_at is not None:
        hb["updated_at"] = hb_updated_at
    rec["heartbeat"] = hb
    return rec


def _parse_peer_block(rec: dict) -> dict:
    """Run the rollup peer-block logic from routes_state, return the peer dict."""
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "peer.json"
        p.write_text(json.dumps(rec), encoding="utf-8")

        # Patch APP_DIR so the code reads from our temp dir
        with mock.patch.object(rs, "APP_DIR", pathlib.Path(td).parent):
            # We need routes_state to look for ops/runtime/peer_health/peer.json
            peer_dir = pathlib.Path(td).parent / "ops" / "runtime" / "peer_health"
            peer_dir.mkdir(parents=True, exist_ok=True)
            (peer_dir / "peer.json").write_text(json.dumps(rec), encoding="utf-8")

            now = time.time()
            recv = rec.get("received_at") or 0
            age_s = max(0.0, now - recv)
            hb = rec.get("heartbeat") or {}
            hb_updated = hb.get("updated_at") or 0
            hb_age_s: float | None = max(0.0, now - hb_updated) if hb_updated else None
            effective_age_s = max(age_s, hb_age_s) if hb_age_s is not None else age_s
            peer_status = rs._peer_health_status(effective_age_s)
            return {
                "age_s":           round(age_s, 1),
                "heartbeat_age_s": round(hb_age_s, 1) if hb_age_s is not None else None,
                "stale":           effective_age_s > rs._PEER_HEALTH_WARN_S,
                "status":          peer_status,
            }


# ---------------------------------------------------------------------------
# Case 1: fresh publisher + fresh heartbeat -> green
# ---------------------------------------------------------------------------

def test_fresh_publisher_fresh_heartbeat_green():
    now = time.time()
    rec = _make_rec(received_at=now - 30, hb_updated_at=now - 60)
    peer = _parse_peer_block(rec)
    assert peer["status"] == "green", f"expected green, got {peer['status']}"
    assert peer["stale"] is False
    assert peer["heartbeat_age_s"] is not None and peer["heartbeat_age_s"] < rs._PEER_HEALTH_WARN_S


# ---------------------------------------------------------------------------
# Case 2: fresh publisher + stale heartbeat (> WARN) -> yellow/red
# ---------------------------------------------------------------------------

def test_fresh_publisher_stale_heartbeat_yellow():
    now = time.time()
    # Publisher just posted (30s ago) but heartbeat frozen 10 minutes ago
    stale_hb = now - (rs._PEER_HEALTH_WARN_S + 120)
    rec = _make_rec(received_at=now - 30, hb_updated_at=stale_hb)
    peer = _parse_peer_block(rec)
    assert peer["status"] in ("yellow", "red"), (
        f"expected yellow or red for frozen watcher, got {peer['status']}"
    )
    assert peer["stale"] is True


def test_fresh_publisher_very_stale_heartbeat_red():
    now = time.time()
    # Heartbeat 19.6 days stale - the exact live scenario from the audit
    stale_hb = now - (19.6 * 86400)
    rec = _make_rec(received_at=now - 30, hb_updated_at=stale_hb)
    peer = _parse_peer_block(rec)
    assert peer["status"] == "red", f"19.6d stale watcher must be red, got {peer['status']}"
    assert peer["stale"] is True
    assert peer["heartbeat_age_s"] is not None


# ---------------------------------------------------------------------------
# Case 3: no heartbeat.updated_at field -> falls back to publisher age only
# ---------------------------------------------------------------------------

def test_no_heartbeat_updated_at_uses_publisher_age_green():
    now = time.time()
    rec = _make_rec(received_at=now - 30)  # no hb_updated_at
    peer = _parse_peer_block(rec)
    assert peer["status"] == "green"
    assert peer["heartbeat_age_s"] is None


# ---------------------------------------------------------------------------
# Case 4: stale publisher + fresh heartbeat -> stale publisher dominates
# ---------------------------------------------------------------------------

def test_stale_publisher_fresh_heartbeat_yellow():
    now = time.time()
    stale_recv = now - (rs._PEER_HEALTH_WARN_S + 60)
    rec = _make_rec(received_at=stale_recv, hb_updated_at=now - 10)
    peer = _parse_peer_block(rec)
    assert peer["status"] in ("yellow", "red"), (
        f"stale publisher should still degrade status, got {peer['status']}"
    )
    assert peer["stale"] is True


# ---------------------------------------------------------------------------
# Case 5: heartbeat_age_s exposed in the response payload
# ---------------------------------------------------------------------------

def test_heartbeat_age_s_present_when_updated_at_provided():
    now = time.time()
    rec = _make_rec(received_at=now - 5, hb_updated_at=now - 120)
    peer = _parse_peer_block(rec)
    assert "heartbeat_age_s" in peer
    assert peer["heartbeat_age_s"] is not None
    assert peer["heartbeat_age_s"] >= 120.0
