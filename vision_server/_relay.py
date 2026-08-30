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
legacy remote-host config (RC_GAME_HOST set to a remote box) the self-read is
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

from ._config import log
from ._stats import _record, _stats, _stats_lock

# -- LCU relay --------------------------------------------------------------
_lcu_lock = threading.Lock()
_lcu_state: dict = {"data": None, "ts": 0.0}
_lcu_cmd_lock = threading.Lock()
_lcu_cmd_queue: list = []           # [{id, cmd, ts}]
_lcu_cmd_results: dict = {}         # id -> {result, ts}
_lcu_cmd_seq = 0

# AUDIT 2026-08-30 (lane 8 cycle 25): _lcu_cmd_results below evicts down to 50
# once it passes 100, but the queue beside it had NO bound at all. The drain is
# the RC-LCUAgent, and an agent that is down is the exact failure mode this
# module's docstring says it exists to survive - so the unbounded side is the
# one that grows precisely when the thing it depends on fails. Oldest-first
# eviction is deliberate: a start_matchmaking queued twenty minutes ago must
# not be what fires when the agent reconnects.
_MAX_PENDING_CMDS = 200


def handle_upload_lcu(body: bytes) -> dict:
    t0 = time.time()
    if not body:
        # AUDIT 2026-08-30 (lane 8 cycle 25): this returned before any _record,
        # bad json recorded nothing, and the success path passed a hardcoded 0
        # ms - so /stats reported lcu_upload as flawless no matter what came
        # in. Same class as the cycle-20 _inference.py defect: an observability
        # surface structurally incapable of expressing the failure it exists to
        # report. Every exit now records, with a measured duration.
        #
        # The DURATION half of that claim went unguarded in the first draft of
        # this fix and the verifier caught it: replacing any measured
        # expression below with a literal 0 left the whole suite green, which
        # is the same vacuous-guard shape the tests here exist to prevent.
        # UploadLatencyIsMeasuredNotHardcoded now pins every one of these eight
        # _record sites with a deterministic stub clock. Do not reintroduce a
        # literal duration on ANY exit, including the empty-body ones - that
        # was the last hardcoded 0 in the module.
        _record("lcu_upload", int((time.time() - t0) * 1000), ok=False)
        return {"error": "empty"}
    try:
        parsed = json.loads(body)
    except Exception as e:  # noqa: BLE001
        # AUDIT 2026-08-30 (lane 8 cycle 20): this echoed the raw exception
        # text - offending byte offset and surrounding document context - back
        # to the caller, bypassing the redaction that _err500 applies to every
        # RAISED error. Same class cycles 18/19 closed in routes_diag and
        # routes_state. Log the cause, return a fixed token.
        log.warning("upload-lcu bad json: %s", e)
        _record("lcu_upload", int((time.time() - t0) * 1000), ok=False)
        return {"error": "bad_json"}
    # AUDIT 2026-08-30 (lane 8 cycle 25): the guard above covers only the
    # DECODE. `[1,2]`, `"x"`, `5` and `null` all decode fine and were cached as
    # a valid LCU session, reaching consumers that call .get on them. The
    # sibling module already carries this guard (_frame.py:231, cycle 20) and
    # so does the self-read path below (:132, :156) - the asymmetry inside one
    # package is what shows this was an omission rather than a choice.
    if not isinstance(parsed, dict):
        _record("lcu_upload", int((time.time() - t0) * 1000), ok=False)
        return {"error": "bad_body"}
    with _lcu_lock:
        _lcu_state.update({"data": parsed, "ts": time.time(),
                           "size": len(body)})
    _record("lcu_upload", int((time.time() - t0) * 1000), ok=True)
    return {"ok": True}


def get_latest_lcu() -> dict:
    with _lcu_lock:
        return dict(_lcu_state)


def lcu_queue_command(cmd: dict) -> int:
    """Dashboard adds a command; agent drains via /lcu-cmd-pending."""
    global _lcu_cmd_seq
    dropped = 0
    with _lcu_cmd_lock:
        _lcu_cmd_seq += 1
        cid = _lcu_cmd_seq
        _lcu_cmd_queue.append({"id": cid, "cmd": cmd, "ts": time.time()})
        if len(_lcu_cmd_queue) > _MAX_PENDING_CMDS:
            dropped = len(_lcu_cmd_queue) - _MAX_PENDING_CMDS
            del _lcu_cmd_queue[:dropped]
    if dropped:
        # Outside the lock: logging can block on a file handler, and this lock
        # is on the dashboard's request path.
        log.warning(
            "lcu command queue full at %d - dropped %d oldest command(s); "
            "is the RC-LCUAgent draining /lcu-cmd-pending?",
            _MAX_PENDING_CMDS, dropped)
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
        row = _lcu_cmd_results.get(cmd_id)
        # AUDIT 2026-08-30 (lane 8 cycle 25): this handed out the STORED dict,
        # so a caller mutating the result corrupted the store for every later
        # reader. get_latest_lcu beside it already copies.
        return dict(row) if row is not None else None


# -- Live Client API relay --------------------------------------------------
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
    except Exception:  # noqa: BLE001
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
    # AUDIT 2026-08-30 (lane 8 cycle 25): the throttle measured a pure INTERVAL
    # with the WALL clock. A backward NTP correction makes the difference
    # negative, which is always < _SELF_READ_MIN_INTERVAL_S, so the :2999
    # self-read stayed disabled until wall time caught back up - an hour of no
    # self-heal after an hour-long step, and the self-heal is what keeps
    # coaching alive when the relay agent is down. An interval belongs on
    # monotonic; `now` stays wall-clock because it is STORED as `ts` and every
    # consumer compares it against their own time.time().
    mono = time.monotonic()
    with _self_read_lock:
        if mono - _last_self_read_attempt < _SELF_READ_MIN_INTERVAL_S:
            return None
        _last_self_read_attempt = mono
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
    On 1-PC this pre-warms the cache; get_latest_liveclient self-reads :2999
    if it goes stale.

    The body is EXPECTED to be the raw JSON object from Riot's :2999 endpoint,
    but it is not trusted to be: the sender is a separate process on its own
    release cadence, so a renamed field or a retyped body is a contract change
    rather than an impossibility (the same reasoning
    core/liveclient_cache.py:212-214 applies to this envelope from the other
    side). Callers get a fixed error token; the cause goes to logs/.
    """
    t0 = time.time()
    if not body:
        _record("liveclient_upload", int((time.time() - t0) * 1000), ok=False)
        return {"error": "empty body"}
    try:
        parsed = json.loads(body)
    except Exception as e:  # noqa: BLE001
        # AUDIT 2026-08-30 (lane 8 cycle 25, closing RM-253): this returned
        # f"bad_json: {e}", echoing the decoder's byte offset and the
        # surrounding document slice to the caller. Because it RETURNS rather
        # than raises it bypassed the redaction _err500 applies to raised
        # errors. handle_upload_lcu was corrected for exactly this on
        # 2026-08-30 (cycle 20) and this identical sibling, 130 lines below in
        # the same file and the same commit, was left behind - the
        # resolver-fix-is-not-a-consumer-fix shape at its smallest.
        log.warning("upload-liveclient bad json: %s", e)
        _record("liveclient_upload", int((time.time() - t0) * 1000), ok=False)
        return {"error": "bad_json"}
    # AUDIT 2026-08-30 (lane 8 cycle 25): shape guard, missing here for the
    # same reason it was missing above. This one bites hardest: a TRUTHY
    # non-object was cached with a FRESH ts, and get_latest_liveclient gates
    # the 1-PC self-heal on age > _SELF_READ_STALE_S - so junk from a
    # malfunctioning agent did not merely pass through, it actively SUPPRESSED
    # the :2999 self-read that exists to keep coaching alive when that agent
    # fails, for 2 s per push.
    if not isinstance(parsed, dict):
        _record("liveclient_upload", int((time.time() - t0) * 1000), ok=False)
        return {"error": "bad_body"}
    with _liveclient_lock:
        # AUDIT 2026-08-30 (lane 8 cycle 25): the ack used to be built from
        # _liveclient["ts"] AFTER this block released the lock, so a second
        # upload landing in between made the agent's ack report a timestamp
        # its own push never wrote. Capture it here instead.
        ts = time.time()
        _liveclient.update({
            "data": parsed,
            "ts":   ts,
            "size": len(body),
            "source": "agent_push",
        })
    ms = int((time.time() - t0) * 1000)
    with _stats_lock:
        _stats["liveclient_upload"]["bytes"] = (
            _stats["liveclient_upload"].get("bytes", 0) + len(body)
        )
    _record("liveclient_upload", ms, ok=True)
    return {"ok": True, "size": len(body), "ts": ts}


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
