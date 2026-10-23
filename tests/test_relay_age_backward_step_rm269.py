"""RM-269: a BACKWARD wall-clock step made a stale relay snapshot read as
perfectly fresh at three sites, because each aged a STORED wall-clock `ts`
against its own `time.time()` and a negative age trips no threshold.

Decision (recorded once, applied at all three sites): `ts` crosses a process
boundary, so a monotonic companion cannot be compared by the consumer. The
shared helper `core.relay_age.is_stale` treats an age more negative than a
small tolerance as STALE. All three sites route through it.
"""
from __future__ import annotations

import io
import json
import time

import pytest

from core import relay_age
from tests._module_view import bind_urlopen


class TestHelper:
    def test_fresh(self):
        assert relay_age.is_stale(100.0, 12.0, now=105.0) is False

    def test_old(self):
        assert relay_age.is_stale(100.0, 12.0, now=200.0) is True

    def test_future_ts_after_backward_step_is_stale(self):
        assert relay_age.is_stale(100.0 + 3600.0, 12.0, now=100.0) is True

    def test_tiny_negative_jitter_is_tolerated(self):
        assert relay_age.is_stale(100.5, 12.0, now=100.0) is False

    @pytest.mark.parametrize("ts", [None, "x", float("nan"), float("inf")])
    def test_garbage_ts_is_stale(self, ts):
        assert relay_age.is_stale(ts, 12.0, now=100.0) is True


def _urlopen_returning(payload, calls=None):
    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=None):
        if calls is not None:
            calls.append(req)
        return _Resp(json.dumps(payload).encode())

    return fake


class TestPollerSites:
    def _mixin(self):
        from game_reader.poller import _PollerMixin
        return _PollerMixin.__new__(_PollerMixin)

    @staticmethod
    def _serve(monkeypatch, payload):
        """game_reader.poller's OWN urllib.request.urlopen (_try_relay and
        _try_lcu_game_id call it through the module-global `urllib`) serves
        PAYLOAD, never the shared module a foreign thread of the xdist worker
        also sees (RM-801, tests/_module_view.py). Returns the call record,
        so a rejecting test proves the fake - not the live relay - answered."""
        import game_reader.poller as poller
        calls = []
        bind_urlopen(monkeypatch, poller, _urlopen_returning(payload, calls))
        return calls

    def test_try_relay_rejects_future_ts(self, monkeypatch):
        future = time.time() + 3600.0
        calls = self._serve(monkeypatch, {"ts": future, "data": {"x": 1}})
        assert self._mixin()._try_relay() is None
        assert calls, "the scoped urlopen fake was never reached"

    def test_try_relay_accepts_fresh_ts(self, monkeypatch):
        # Positive control: the same fake with a fresh ts is served.
        self._serve(monkeypatch, {"ts": time.time(), "data": {"x": 1}})
        assert self._mixin()._try_relay() == {"x": 1}

    def test_lcu_game_id_rejects_future_ts(self, monkeypatch):
        future = time.time() + 3600.0
        calls = self._serve(monkeypatch, {"ts": future, "data": {"game_id": 9}})
        assert self._mixin()._try_lcu_game_id() == ""
        assert calls, "the scoped urlopen fake was never reached"

    def test_lcu_game_id_accepts_fresh_ts(self, monkeypatch):
        self._serve(monkeypatch, {"ts": time.time(), "data": {"game_id": 9}})
        assert self._mixin()._try_lcu_game_id() == "9"


class TestRelaySelfHealSite:
    def test_future_ts_triggers_self_read(self, monkeypatch):
        from vision_server import _relay
        calls = []

        def spy():
            calls.append(1)
            return {"data": {"fresh": True}, "ts": time.time()}

        monkeypatch.setattr(_relay, "GAME_HOST", "127.0.0.1")
        monkeypatch.setattr(_relay, "_maybe_self_read", spy)
        with _relay._liveclient_lock:
            saved = dict(_relay._liveclient)
            _relay._liveclient.update({"data": {"old": 1}, "ts": time.time() + 3600.0})
        try:
            snap = _relay.get_latest_liveclient()
        finally:
            with _relay._liveclient_lock:
                _relay._liveclient.clear()
                _relay._liveclient.update(saved)
        assert calls == [1]
        assert snap["data"] == {"fresh": True}
