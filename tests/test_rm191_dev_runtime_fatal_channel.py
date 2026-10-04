"""RM-191 - DevRuntime.write_fatal must not be a write-only channel.

It used to overwrite a single-slot ops/runtime/last_fatal.txt that nothing
read, never reached logs/, and swallowed its own failure - so the
2026-08-09 health.json rename fault sat unseen for three days while the
process stayed alive and health.json still read alive=true. Acceptance is
NOT "add a log line": a counter plus last-N ring reaching BOTH logs/ and the
health payload, and /api/health/all must see a stale heartbeat.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from ops import rc_dev_runtime as rdr


@pytest.fixture(autouse=True)
def _clean_stats():
    rdr._reset_fatal_stats_for_tests()
    yield
    rdr._reset_fatal_stats_for_tests()


def _rt(tmp_path):
    return rdr.DevRuntime(project_root=tmp_path)


def test_every_fatal_is_counted_not_overwritten(tmp_path):
    rt = _rt(tmp_path)
    for i in range(3):
        rt.write_fatal(f"heartbeat_error: PermissionError: [WinError 5] #{i}\ntb")
    st = rdr.fatal_stats()
    assert st["count"] == 3
    assert [e["summary"][-2:] for e in st["recent"]] == ["#0", "#1", "#2"]
    assert st["recent"][0]["kind"] == "heartbeat_error"
    assert st["last_at"]


def test_ring_is_bounded(tmp_path):
    rt = _rt(tmp_path)
    for i in range(rdr._FATAL_RING_MAX + 5):
        rt.write_fatal(f"command_loop_error: X: {i}")
    st = rdr.fatal_stats()
    assert st["count"] == rdr._FATAL_RING_MAX + 5
    assert len(st["recent"]) == rdr._FATAL_RING_MAX


def test_fatal_reaches_the_log(tmp_path, caplog):
    caplog.set_level(logging.ERROR, logger="rc.dev_runtime")
    _rt(tmp_path).write_fatal("heartbeat_error: OSError: boom\ntraceback...")
    assert any(r.levelno >= logging.ERROR and "heartbeat_error" in r.getMessage()
               for r in caplog.records)


def test_fatal_reaches_the_health_payload(tmp_path):
    rt = _rt(tmp_path)
    rt.write_fatal("heartbeat_error: OSError: boom")
    p = rt._build_health_payload()
    assert p["fatal_count"] == 1
    assert p["last_fatal_at"]
    assert p["recent_fatals"][0]["kind"] == "heartbeat_error"


def test_failure_to_record_is_logged_not_swallowed(tmp_path, caplog):
    rt = _rt(tmp_path)
    rt.last_fatal_file = tmp_path / "ops" / "runtime"  # a directory: write fails
    caplog.set_level(logging.WARNING, logger="rc.dev_runtime")
    rt.write_fatal("heartbeat_error: X: y")
    assert rdr.fatal_stats()["count"] == 1, "the in-process record still counts it"
    assert any("could not write" in r.getMessage() for r in caplog.records)


def test_heartbeat_loop_fault_is_counted(tmp_path):
    rt = _rt(tmp_path)
    calls = {"n": 0}

    def _boom(*a, **k):
        calls["n"] += 1
        rt._stop_event.set()
        raise PermissionError(5, "Access is denied")

    with mock.patch.object(rdr, "_atomic_write_json", side_effect=_boom):
        rt._heartbeat_loop()
    assert calls["n"] == 1
    assert rdr.fatal_stats()["count"] == 1


# --------------------------------------------------------- /api/health/all

class _H:
    def __init__(self):
        self.body = None

    def _send(self, code, body, ctype):
        self.code, self.body = code, body


def _rollup(health):
    from dashboard import routes_state
    real = routes_state.read_json

    def _rj(name):
        if name == "ops/runtime/health.json":
            return dict(health)
        return real(name)

    class _Resp:
        def __init__(self, url):
            self._b = (b'{"status": "ok"}' if ":8860" in url
                       else b'{"alive": true}')

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self._b

    # Vision + DS probes answer healthy, so the rollup status is decided by
    # the RC half alone (otherwise "red" would be vacuous - an offline
    # vision probe forces red by itself).
    h = _H()
    with mock.patch.object(routes_state, "read_json", side_effect=_rj), \
            mock.patch.object(routes_state.urllib.request, "urlopen",
                              side_effect=lambda url, timeout=None: _Resp(url)):
        routes_state._serve_health_all(h)
    return json.loads(h.body)


def test_health_all_flags_a_frozen_heartbeat_red():
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    r = _rollup({"alive": True, "updated_at": old, "pid": 1})
    assert r["rc_stale"] is True
    assert r["rc_heartbeat_age_s"] > 500
    assert r["status"] == "red"


def test_health_all_carries_in_process_fatal_record(tmp_path):
    _rt(tmp_path).write_fatal("heartbeat_error: OSError: boom")
    now = datetime.now(timezone.utc).isoformat()
    r = _rollup({"alive": True, "updated_at": now, "pid": 1})
    assert r["rc_stale"] is False
    assert r["rc_fatal"]["count"] == 1
    assert r["rc_fatal"]["recent"][0]["kind"] == "heartbeat_error"
    assert r["status"] != "green", "a fatal in the last 5 min is not green"


def test_health_all_fresh_and_clean_is_not_red():
    now = datetime.now(timezone.utc).isoformat()
    r = _rollup({"alive": True, "updated_at": now, "pid": 1})
    assert r["rc_stale"] is False
    assert r["status"] != "red", r
