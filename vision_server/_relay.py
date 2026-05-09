# arch: LCU + Live Client relays | section=vision | frozen=no
"""LCU session + Live Client API relays from Game-PC.

Split out of moon_vision_server.py during Phase 2.4. Owns two independent
relay surfaces that share the same shape (Game-PC pushes JSON, Legion pulls
the latest snapshot):

- LCU relay: session state + a command queue for actions like
  ``start_matchmaking`` that only the LCU agent on Game-PC can execute.
- Live Client API relay: ``/liveclientdata/allgamedata`` snapshots from the
  in-game :2999 endpoint that Riot exposes per-game.
"""
from __future__ import annotations

import json
import threading
import time

from ._stats import _record, _stats, _stats_lock

# ── LCU relay ──────────────────────────────────────────────────────────────
_lcu_lock = threading.Lock()
_lcu_state: dict = {"data": None, "ts": 0.0}
_lcu_cmd_lock = threading.Lock()
_lcu_cmd_queue: list = []           # [{id, cmd, ts}]
_lcu_cmd_results: dict = {}         # id -> {result, ts}
_lcu_cmd_seq = 0


def handle_upload_lcu(body: bytes) -> dict:
    if not body:
        return {"error": "empty"}
    try:
        parsed = json.loads(body)
    except Exception as e:
        return {"error": f"bad_json: {e}"}
    with _lcu_lock:
        _lcu_state.update({"data": parsed, "ts": time.time(),
                           "size": len(body)})
    _record("lcu_upload", 0, ok=True)
    return {"ok": True}


def get_latest_lcu() -> dict:
    with _lcu_lock:
        return dict(_lcu_state)


def lcu_queue_command(cmd: dict) -> int:
    """Dashboard adds a command; agent drains via /lcu-cmd-pending."""
    global _lcu_cmd_seq
    with _lcu_cmd_lock:
        _lcu_cmd_seq += 1
        cid = _lcu_cmd_seq
        _lcu_cmd_queue.append({"id": cid, "cmd": cmd, "ts": time.time()})
    return cid


def lcu_drain_pending() -> list:
    """Agent calls this; returns and clears the pending queue."""
    with _lcu_cmd_lock:
        items = list(_lcu_cmd_queue)
        _lcu_cmd_queue.clear()
    return items


def lcu_record_result(cmd_id: int, result: dict) -> None:
    with _lcu_cmd_lock:
        _lcu_cmd_results[cmd_id] = {"result": result, "ts": time.time()}
        if len(_lcu_cmd_results) > 100:
            oldest = sorted(_lcu_cmd_results.items(),
                            key=lambda x: x[1]["ts"])[:50]
            for k, _ in oldest:
                _lcu_cmd_results.pop(k, None)


def lcu_get_result(cmd_id: int) -> dict | None:
    """Dashboard polls this after queueing a command so it can surface LCU
    errors (e.g. non-leader tried to start_matchmaking)."""
    with _lcu_cmd_lock:
        return _lcu_cmd_results.get(cmd_id)


# ── Live Client API relay ──────────────────────────────────────────────────
_liveclient_lock = threading.Lock()
_liveclient: dict = {"data": None, "ts": 0.0, "size": 0}


def handle_upload_liveclient(body: bytes) -> dict:
    """Game-PC liveclient relay POSTs /liveclientdata/allgamedata JSON.
    Body is the raw JSON from Riot's :2999 endpoint."""
    t0 = time.time()
    if not body:
        _record("liveclient_upload", 0, ok=False)
        return {"error": "empty body"}
    try:
        parsed = json.loads(body)
    except Exception as e:
        _record("liveclient_upload", int((time.time() - t0) * 1000), ok=False)
        return {"error": f"bad_json: {e}"}
    with _liveclient_lock:
        _liveclient.update({
            "data": parsed,
            "ts":   time.time(),
            "size": len(body),
        })
    ms = int((time.time() - t0) * 1000)
    with _stats_lock:
        _stats["liveclient_upload"]["bytes"] = (
            _stats["liveclient_upload"].get("bytes", 0) + len(body)
        )
    _record("liveclient_upload", ms, ok=True)
    return {"ok": True, "size": len(body), "ts": _liveclient["ts"]}


def get_latest_liveclient() -> dict:
    with _liveclient_lock:
        return dict(_liveclient)
