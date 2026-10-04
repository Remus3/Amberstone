"""RM-235: the Live Client subresource failure counters were process-global
with no production reset and no production reader.

(1) The per-game reset the SrAramWorker poll thread applies (requested by the
    frozen app/_game_lifecycle.py at game start and game end) now also
    clears the counters and the 60s warn throttle, so "so far" means this
    game and a pre-game warn no longer silences the new game.
(2) /api/health/all carries them as `liveclient_subresource_failures`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

import pytest

from game_reader import snapshot_normalizer as sn


@pytest.fixture(autouse=True)
def _clean():
    sn.reset_liveclient_subresource_failures()
    yield
    sn.reset_liveclient_subresource_failures()


def _worker():
    from core.sr_aram_worker import SrAramWorker
    w = SrAramWorker.__new__(SrAramWorker)
    w._reset_pending = False
    w._reset_reason = ""
    return w


def _reader():
    return SimpleNamespace(_enemy_last_seen={"a": 1}, _enemy_death_time={"a": 2})


def test_game_reset_clears_counters_and_throttle():
    sn._note_subresource_failure("runes", OSError("x"))
    assert sn.get_liveclient_subresource_failures() == {"runes": 1}
    assert sn._subresource_last_warn
    w = _worker()
    w.reset_reader_state(reason="game_start")
    w._apply_pending_reset(_reader())
    assert sn.get_liveclient_subresource_failures() == {}
    assert sn._subresource_last_warn == {}


def test_no_pending_reset_keeps_counters():
    # Positive control: an ordinary tick does not wipe the counters.
    sn._note_subresource_failure("runes", OSError("x"))
    _worker()._apply_pending_reset(_reader())
    assert sn.get_liveclient_subresource_failures() == {"runes": 1}


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


def test_health_all_exposes_counters_and_they_move():
    assert _rollup()["liveclient_subresource_failures"] == {}
    sn._note_subresource_failure("runes", OSError("x"))
    sn._note_subresource_failure("runes", OSError("x"))
    assert _rollup()["liveclient_subresource_failures"] == {"runes": 2}
