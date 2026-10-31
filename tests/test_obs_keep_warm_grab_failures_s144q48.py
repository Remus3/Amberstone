"""RM-1216 - the OBS publisher keep-warm grab no longer fails silently.

`OBSPublisher._async_loop` calls `grab_source_screenshot` once per tick when
`obs.frame_source` is on, and before this fix it discarded the None: a wrong
`frame_source_name` (OBS-WS v5 status 600) left the keep-warm slot cold
forever with nothing on the RC side saying why. The loop now passes the
RM-1215 `on_failure` hook, which:

- counts every failure per reason on the publisher
  (`OBSPublisher.grab_failure_counts()`, every `GRAB_FAILURES` key present);
- logs the FIRST occurrence of each reason once per connection, so a
  steady-state misconfiguration costs one log line per connection, not one
  per tick, and a reconnect logs it again.

These tests drive the real `_async_loop` against a stubbed
`websockets.connect` (no OBS, no network). Every synthetic value here is
hand-written.
"""
from __future__ import annotations

import asyncio
import json
import logging

import pytest

from core import obs_publisher
from core.obs_publisher import GRAB_FAILURES, OBSPublisher
from tests._asyncio_isolation import run_coro


class _FakeWS:
    """An identified OBS-WS connection whose GetSourceScreenshot replies come
    from `replies` (one per request, the last one repeats)."""

    def __init__(self, replies):
        self._replies = list(replies)
        self._queue: list = []

    async def send(self, raw):
        msg = json.loads(raw)
        d = msg.get("d") or {}
        if d.get("requestType") != "GetSourceScreenshot":
            return
        reply = self._replies.pop(0) if len(self._replies) > 1 \
            else self._replies[0]
        if reply is None:
            return  # no op:7 at all -> request_response times out
        body = dict(reply)
        body["requestId"] = d.get("requestId")
        body["requestType"] = "GetSourceScreenshot"
        self._queue.append(json.dumps({"op": 7, "d": body}))

    async def recv(self):
        if self._queue:
            return self._queue.pop(0)
        await asyncio.sleep(3600)


class _Conn:
    def __init__(self, ws):
        self._ws = ws

    async def __aenter__(self):
        return self._ws

    async def __aexit__(self, *exc):
        return False


_MISSING = {"requestStatus": {"result": False, "code": 600}}
_INACTIVE = {"requestStatus": {"result": False, "code": 604}}
_EMPTY = {"requestStatus": {"result": True, "code": 100},
          "responseData": {"imageData": ""}}
_GOOD = {"requestStatus": {"result": True, "code": 100},
         "responseData": {"imageData": "data:image/jpg;base64,QUJD"}}


def _run_loop(monkeypatch, connections, ticks_per_conn, cfg_extra=None):
    """Run `_async_loop` over `connections` (a list of _FakeWS), ending each
    connection after exactly `ticks_per_conn` grabs with an OSError (a drop)
    raised from the drain of the next tick, and stopping the publisher at
    the last one's drop. Returns the publisher."""
    pub = OBSPublisher()
    conns = list(connections)
    state = {"tick": 0, "conn": 0}

    def _connect(url, open_timeout=None):
        ws = conns[state["conn"]]
        state["conn"] += 1
        state["tick"] = 0
        return _Conn(ws)

    async def _identify(ws, password, event_subscriptions=0):
        return True

    async def _drain(ws):
        state["tick"] += 1
        if state["tick"] > ticks_per_conn:
            if state["conn"] >= len(conns):
                pub._stop.set()  # last connection: drop, then stop
            raise OSError("synthetic drop")

    monkeypatch.setattr(obs_publisher.websockets, "connect", _connect)
    monkeypatch.setattr(obs_publisher, "_render_state", lambda: "")
    monkeypatch.setattr(obs_publisher, "_BACKOFF_AFTER_DROP_S", 0)
    monkeypatch.setattr(pub, "_identify", _identify)
    monkeypatch.setattr(pub, "_drain_pending", _drain)
    obs_publisher._reset_frame_slot()
    cfg = {"frame_source": True, "frame_source_name": "Synthetic Capture",
           "interval_s": 0, "frame_timeout_s": 0.05}
    cfg.update(cfg_extra or {})
    # Off the main thread (tests/_asyncio_isolation): a bare asyncio.run()
    # raises "cannot be called from a running event loop" once a
    # snapshot_panels Playwright session has run on the same worker.
    run_coro(asyncio.wait_for(pub._async_loop(cfg), timeout=20), timeout=30)
    return pub


def _grab_warnings(caplog):
    return [r for r in caplog.records
            if r.name == "rc.obs_publisher"
            and r.levelno >= logging.WARNING
            and "keep-warm" in r.getMessage()]


def test_fresh_publisher_counts_every_reason_at_zero():
    pub = OBSPublisher()
    counts = pub.grab_failure_counts()
    assert set(counts) == set(GRAB_FAILURES)
    assert all(v == 0 for v in counts.values())


def test_grab_failure_counts_returns_a_copy():
    pub = OBSPublisher()
    counts = pub.grab_failure_counts()
    counts["source_missing"] = 99
    assert pub.grab_failure_counts()["source_missing"] == 0


def test_wrong_source_name_is_counted_every_tick(monkeypatch):
    pub = _run_loop(monkeypatch, [_FakeWS([_MISSING])], ticks_per_conn=5)
    counts = pub.grab_failure_counts()
    assert counts["source_missing"] == 5
    assert counts["request_failed"] == 0
    assert counts["bad_payload"] == 0
    assert counts["no_reply"] == 0


def test_wrong_source_name_logs_once_per_connection(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="rc.obs_publisher")
    _run_loop(monkeypatch, [_FakeWS([_MISSING])], ticks_per_conn=6)
    warns = _grab_warnings(caplog)
    assert len(warns) == 1, [w.getMessage() for w in warns]
    msg = warns[0].getMessage()
    assert "source_missing" in msg
    assert "Synthetic Capture" in msg


def test_reconnect_logs_the_reason_again(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="rc.obs_publisher")
    pub = _run_loop(monkeypatch,
                    [_FakeWS([_MISSING]), _FakeWS([_MISSING])],
                    ticks_per_conn=3)
    warns = _grab_warnings(caplog)
    assert len(warns) == 2, [w.getMessage() for w in warns]
    assert pub.grab_failure_counts()["source_missing"] == 6


def test_each_distinct_reason_logs_once(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="rc.obs_publisher")
    replies = [_MISSING, _INACTIVE, _EMPTY, _MISSING, _INACTIVE, _EMPTY]
    pub = _run_loop(monkeypatch, [_FakeWS(replies)], ticks_per_conn=6)
    counts = pub.grab_failure_counts()
    assert counts["source_missing"] == 2
    assert counts["request_failed"] == 2
    assert counts["bad_payload"] == 2
    warns = _grab_warnings(caplog)
    reasons = sorted(r for w in warns for r in GRAB_FAILURES
                     if f"({r})" in w.getMessage())
    assert reasons == ["bad_payload", "request_failed", "source_missing"]


def test_no_reply_is_counted(monkeypatch):
    pub = _run_loop(monkeypatch, [_FakeWS([None])], ticks_per_conn=2)
    assert pub.grab_failure_counts()["no_reply"] == 2


def test_good_frames_count_nothing_and_log_nothing(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="rc.obs_publisher")
    pub = _run_loop(monkeypatch, [_FakeWS([_GOOD])], ticks_per_conn=4)
    assert all(v == 0 for v in pub.grab_failure_counts().values())
    assert _grab_warnings(caplog) == []
    assert obs_publisher.peek_frame(max_age_s=60.0) == b"ABC"


def test_frame_source_off_never_grabs(monkeypatch):
    sent: list = []

    class _Spy(_FakeWS):
        async def send(self, raw):
            sent.append(json.loads(raw))
            await super().send(raw)

    pub = _run_loop(monkeypatch, [_Spy([_MISSING])], ticks_per_conn=3,
                    cfg_extra={"frame_source": False})
    assert all(v == 0 for v in pub.grab_failure_counts().values())
    assert not any((m.get("d") or {}).get("requestType")
                   == "GetSourceScreenshot" for m in sent)


def test_unknown_reason_from_hook_is_counted_not_dropped():
    """The recorder accepts a reason outside GRAB_FAILURES (a future grab
    reason) rather than raising or discarding it."""
    pub = OBSPublisher()
    logged: set = set()
    pub._record_grab_failure("future_reason", logged, "Synthetic Capture")
    assert pub.grab_failure_counts()["future_reason"] == 1


@pytest.mark.parametrize("reason", GRAB_FAILURES)
def test_recorder_logs_first_then_counts(reason, caplog):
    caplog.set_level(logging.DEBUG, logger="rc.obs_publisher")
    pub = OBSPublisher()
    logged: set = set()
    for _ in range(4):
        pub._record_grab_failure(reason, logged, "Synthetic Capture")
    assert pub.grab_failure_counts()[reason] == 4
    assert len(_grab_warnings(caplog)) == 1
