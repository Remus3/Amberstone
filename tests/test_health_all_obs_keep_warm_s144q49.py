"""RM-1217: the OBS keep-warm grab failure counters reach a POLLED channel.

RM-1216 gave `OBSPublisher` a per-reason counter of keep-warm grab
failures (`grab_failure_counts()`), but no code read it: between the
once-per-connection WARNING lines a cold keep-warm slot (a wrong
`frame_source_name`) was visible only in an in-process dict.
Acceptance: `/api/health/all` carries the counts under the stable key
`obs_keep_warm_grab_failures`, one key per `GRAB_FAILURES` reason, that
moves when the publisher's counter moves; the block is informational and
never moves the status dot; a raising probe is a GENERIC_ERROR block and
the rollup still serves 200.

The publisher runs in the RC process (dashboard/server.py starts it), the
same process that serves `/api/health/all`, so the read is in-process.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

from core import obs_publisher
from tests._module_view import bind_urlopen

ROOT = Path(__file__).resolve().parent.parent
KEY = "obs_keep_warm_grab_failures"


@pytest.fixture(autouse=True)
def _fresh_publisher():
    """Each test gets its own publisher singleton; the real one is restored."""
    saved = obs_publisher._publisher
    obs_publisher._publisher = obs_publisher.OBSPublisher()
    yield obs_publisher._publisher
    obs_publisher._publisher = saved


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
    # routes_state's own urllib only, never the shared module (RM-801).
    with mock.patch.object(routes_state, "read_json", side_effect=_rj), \
            pytest.MonkeyPatch.context() as mp:
        bind_urlopen(mp, routes_state, lambda url, timeout=None: _Resp(url))
        routes_state._serve_health_all(h)
    assert h.code == 200
    return json.loads(h.body)


def test_field_present_with_every_reason_at_zero():
    block = _rollup()[KEY]
    assert set(block) == set(obs_publisher.GRAB_FAILURES)
    assert all(v == 0 for v in block.values()), block


def test_field_moves_when_the_publisher_counter_moves(_fresh_publisher):
    pub = _fresh_publisher
    logged: set = set()
    for _ in range(3):
        pub._record_grab_failure("source_missing", logged, "RC-Frame")
    pub._record_grab_failure("no_reply", logged, "RC-Frame")
    block = _rollup()[KEY]
    assert block["source_missing"] == 3
    assert block["no_reply"] == 1
    assert block == pub.grab_failure_counts()


def test_reads_the_process_singleton_not_a_fresh_publisher(_fresh_publisher):
    # A route that built its own OBSPublisher() would always read zeros.
    _fresh_publisher._record_grab_failure("request_failed", set(), "src")
    assert _rollup()[KEY]["request_failed"] == 1


def test_counters_do_not_move_the_status_dot(_fresh_publisher):
    clean = _rollup()["status"]
    for r in obs_publisher.GRAB_FAILURES:
        _fresh_publisher._record_grab_failure(r, set(), "src")
    r = _rollup()
    assert r["status"] == clean
    assert KEY not in r["why"]


def test_raising_probe_is_a_generic_error_block(_fresh_publisher):
    from dashboard.routes_state import GENERIC_ERROR
    with mock.patch.object(_fresh_publisher, "grab_failure_counts",
                           side_effect=RuntimeError("secret detail")):
        r = _rollup()
    assert r[KEY] == {"error": GENERIC_ERROR}
    assert "secret detail" not in json.dumps(r)
    # informational: even an errored probe is not a status sub-probe
    assert KEY not in r["why"]


def test_schema_and_generated_js_declare_the_field():
    from dashboard.api_schema import HealthAllResponse
    assert KEY in HealthAllResponse.model_fields
    js = (ROOT / "web" / "js" / "lib" / "state_schema.js").read_text(
        encoding="utf-8")
    block = js[js.index("@typedef {Object} HealthAllResponse"):]
    block = block[:block.index("*/")]
    assert f"@property {{Object}} {KEY}" in block
