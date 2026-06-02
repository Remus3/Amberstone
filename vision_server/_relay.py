# arch: LCU + Live Client relays | section=vision | frozen=no
"""LCU session + Live Client API relays.

Split out of moon_vision_server.py during Phase 2.4. Owns two independent
relay surfaces that share the same shape (an agent pushes JSON, consumers pull
the latest snapshot):

- LCU relay: session state + a command queue for actions like
  ``start_matchmaking`` that only the LCU agent can execute.
- Live Client API relay: ``/liveclientdata/allgamedata`` snapshots from the
  in-game :2999 endpoint that Riot exposes per-game.

1-PC self-heal (post-2026-05 Legion consolidation, ADR-011): when League runs
on this host (``core.game_host.GAME_HOST`` local) and the relayed liveclient
snapshot is stale/missing, ``get_latest_liveclient`` reads :2999 in-process so
the RC-LiveClientRelay agent is an optimization (it pre-warms the cache), NOT a
hard dependency. If the agent dies, the self-read keeps coaching alive. In the
legacy 2-PC topology (RC_GAME_HOST set to a remote box) the self-read is
disabled - Riot's :2999 binds localhost-only on the remote host - and the
agent push stays the only feed.
"""
from __future__ import annotations

import json
import ssl
import threading
import time
import urllib.request

from core.game_host import GAME_HOST

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

# 1-PC self-heal config (ADR-011). League's :2999 is HTTPS with a self-signed
# Riot cert; verify=off like every other RC reader (poller, lcu_client).
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_LIVE_API_URL = f"https://{GAME_HOST}:2999/liveclientdata/allgamedata"
_SELF_READ_STALE_S = 2.0          # serve the cache as-is when fresher than this
_SELF_READ_MIN_INTERVAL_S = 1.5   # min gap between :2999 self-read attempts
_SELF_READ_TIMEOUT_S = 1.0
_self_read_ssl = ssl._create_unverified_context()
_self_read_lock = threading.Lock()
_last_self_read_attempt = 0.0


def _fetch_liveclient_direct():
    """One in-process read of Riot's :2999 /allgamedata. Returns the parsed
    dict or None on any failure (no game -> instant localhost connection
    refusal; not a timeout). Patchable seam for tests."""
    try:
        req = urllib.request.Request(_LIVE_API_URL)
        with urllib.request.urlopen(
            req, context=_self_read_ssl, timeout=_SELF_READ_TIMEOUT_S
        ) as r:
            parsed = json.loads(r.read())
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _reset_self_read_state() -> None:
    """Test helper: clear the self-read throttle + the cached snapshot."""
    global _last_self_read_attempt
    with _self_read_lock:
        _last_self_read_attempt = 0.0
    with _liveclient_lock:
        _liveclient.update({"data": None, "ts": 0.0, "size": 0})
        _liveclient.pop("source", None)


def _maybe_self_read():
    """If League is local and the cache is stale, self-read :2999 (throttled).
    Returns the freshly populated snapshot dict or None to fall through to the
    existing cache."""
    global _last_self_read_attempt
    now = time.time()
    with _self_read_lock:
        if now - _last_self_read_attempt < _SELF_READ_MIN_INTERVAL_S:
            return None
        _last_self_read_attempt = now
    parsed = _fetch_liveclient_direct()
    if not isinstance(parsed, dict):
        return None
    with _liveclient_lock:
        _liveclient.update(
            {"data": parsed, "ts": now, "size": 0, "source": "self_read"}
        )
        return dict(_liveclient)


def handle_upload_liveclient(body: bytes) -> dict:
    """The RC-LiveClientRelay agent POSTs /liveclientdata/allgamedata JSON.
    Body is the raw JSON from Riot's :2999 endpoint. On 1-PC this pre-warms
    the cache; get_latest_liveclient self-reads :2999 if it goes stale."""
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
            "source": "agent_push",
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
        snap = dict(_liveclient)
    # 1-PC self-heal: when the relayed snapshot is stale/missing and League is
    # on this host, read :2999 in-process so the relay agent is non-integral.
    if GAME_HOST in _LOCAL_HOSTS:
        age = time.time() - float(snap.get("ts") or 0.0)
        if age > _SELF_READ_STALE_S:
            fresh = _maybe_self_read()
            if fresh is not None:
                return fresh
    return snap
