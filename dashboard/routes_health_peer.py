# arch: GET /api/health/peer + /api/health/all | section=dashboard | frozen=no
"""POST /api/health/peer/<node> — peer publishes their bridge_watcher_health.json.

Closes ROADMAP §3 polish item: peers' watcher heartbeats live on their own
disks; this endpoint receives them so Legion's /api/health/all rolls up
fleet-wide. Each peer runs `tools/bridge_watcher_health_publisher.py`
which polls local heartbeat every 60s and POSTs here.

Auth: same Bearer secret as /api/bridge/inbox (shared cross-Claude token).
Storage: ops/runtime/peer_health/<node>.json — atomic-write, retained
indefinitely (small file, ~600 bytes per peer).
Staleness: consumers read updated_at; consider a peer stale if its
bridge_watcher heartbeat hasn't refreshed in 5+ minutes.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from core import bridge as _bridge
from dashboard._dispatch import equals, prefix

log = logging.getLogger("rc.routes_health_peer")

_APP_DIR = Path(__file__).parent.parent
_PEER_DIR = _APP_DIR / "ops" / "runtime" / "peer_health"
_VALID_NODES = {"gamepc", "peer"}


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    last_exc: Exception | None = None
    for delay in (0, 0.025, 0.050, 0.200):
        if delay:
            time.sleep(delay)
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            last_exc = exc
            continue
    if last_exc:
        raise last_exc


def _node_from_path(path: str) -> str | None:
    base = "/api/health/peer/"
    if not path.startswith(base):
        return None
    rest = path[len(base):]
    if "?" in rest:
        rest = rest.split("?", 1)[0]
    rest = rest.strip("/")
    return rest if rest in _VALID_NODES else None


def _serve_post_peer(h, body) -> None:
    if not _bridge.is_configured():
        h._send(503, b'{"error":"bridge_not_configured"}', "application/json")
        return

    auth = (h.headers.get("Authorization") or "").strip()
    expected = "Bearer " + _bridge.shared_secret()
    if auth != expected:
        log.warning("health peer auth reject from %s", h.client_address[0])
        h._send(401, b'{"error":"unauthorized"}', "application/json")
        return

    node = _node_from_path(h.path)
    if not node:
        h._send(400,
                json.dumps({"error": "expected /api/health/peer/<node>",
                            "valid_nodes": sorted(_VALID_NODES)}).encode(),
                "application/json")
        return

    if not isinstance(body, dict):
        h._send(400, b'{"error":"body must be a JSON object"}',
                "application/json")
        return

    record = {
        "node":         node,
        "received_at":  time.time(),
        "from_addr":    h.client_address[0],
        "heartbeat":    body,
    }
    try:
        _atomic_write(_PEER_DIR / f"{node}.json", record)
    except OSError as exc:
        h._send(500, json.dumps({"error": str(exc)[:200]}).encode(),
                "application/json")
        return

    h._send(200, json.dumps({"ok": True, "node": node,
                             "received_at": record["received_at"]}).encode(),
            "application/json")


def _read_peer(node: str) -> dict | None:
    path = _PEER_DIR / f"{node}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _serve_get_peer_index(h) -> None:
    out = {}
    for node in sorted(_VALID_NODES):
        rec = _read_peer(node)
        if rec is None:
            out[node] = {"status": "no_data"}
            continue
        recv = rec.get("received_at") or 0
        age_s = max(0, time.time() - recv)
        out[node] = {
            "received_at": recv,
            "age_s":       round(age_s, 1),
            "stale":       age_s > 300,
            "heartbeat":   rec.get("heartbeat"),
        }
    h._send(200, json.dumps(out).encode(), "application/json")


def _serve_get_peer_one(h) -> None:
    node = _node_from_path(h.path)
    if not node:
        h._send(400,
                json.dumps({"error": "expected /api/health/peer/<node>",
                            "valid_nodes": sorted(_VALID_NODES)}).encode(),
                "application/json")
        return
    rec = _read_peer(node)
    if rec is None:
        h._send(404, json.dumps({"error": "no_data", "node": node}).encode(),
                "application/json")
        return
    recv = rec.get("received_at") or 0
    age_s = max(0, time.time() - recv)
    rec["age_s"] = round(age_s, 1)
    rec["stale"] = age_s > 300
    h._send(200, json.dumps(rec).encode(), "application/json")


GET_ROUTES = [
    (equals("/api/health/peer"),    _serve_get_peer_index),
    (prefix("/api/health/peer/"),   _serve_get_peer_one),
]

POST_ROUTES = [
    (prefix("/api/health/peer/"),   _serve_post_peer),
]
