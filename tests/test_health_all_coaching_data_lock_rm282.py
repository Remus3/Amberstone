"""RM-282: the coaching-data lock counters must reach a POLLED channel.

`coaching_data_lock_stats()` had zero production callers, so between
rate-floored WARNINGs the lock's health lived only in a counter no code read.
Acceptance: a field on `/api/health/all` that moves when
`file_lock_failures` moves.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest import mock

import pytest

from core import coaching_data_lock as cdl


@pytest.fixture(autouse=True)
def _clean():
    cdl._reset_state_for_tests()
    yield
    cdl._reset_state_for_tests()


class _H:
    def _send(self, code, body, ctype):
        self.code, self.body = code, body


def _rollup():
    from dashboard import routes_state
    real = routes_state.read_json
    now = datetime.now(timezone.utc).isoformat()

    def _rj(name):
        if name == "ops/runtime/health.json":
            return {"alive": True, "updated_at": now, "pid": 1}
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

    h = _H()
    with mock.patch.object(routes_state, "read_json", side_effect=_rj), \
            mock.patch.object(routes_state.urllib.request, "urlopen",
                              side_effect=lambda url, timeout=None: _Resp(url)):
        routes_state._serve_health_all(h)
    assert h.code == 200
    return json.loads(h.body)


def test_field_present_and_zero_when_healthy():
    r = _rollup()
    assert r["coaching_data_lock"]["file_lock_failures"] == 0
    assert set(r["coaching_data_lock"]) == set(cdl.coaching_data_lock_stats())


def test_field_moves_when_file_lock_failures_moves():
    before = _rollup()["coaching_data_lock"]["file_lock_failures"]
    for _ in range(3):
        cdl._note_file_lock_failure("acquire", OSError("simulated"))
    after = _rollup()["coaching_data_lock"]
    assert after["file_lock_failures"] == before + 3
    assert after["degradation_episodes"] >= 1


def test_counters_do_not_move_the_status_dot():
    cdl._note_file_lock_failure("acquire", OSError("simulated"))
    r = _rollup()
    assert r["status"] == _status_with_clean_lock()


def _status_with_clean_lock():
    cdl._reset_state_for_tests()
    return _rollup()["status"]


def test_schema_declares_the_field():
    from dashboard.api_schema import HealthAllResponse
    assert "coaching_data_lock" in HealthAllResponse.model_fields
