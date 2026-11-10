"""
tests/test_decisions_route_liveness_gate.py.

S144-U-270 (s144 uiux): GET /api/decisions serves a pending coach decision
only while the DecisionLoop that owns it is alive.

WHY. The coach decisions banner (#coach-decisions, web/js/panels/
coach_decisions.js) and the hotkey listener (tools/hotkey_listener.py)
both render or answer whatever /api/decisions returns. The route read
data/decisions_pending.json straight through DecisionStore.list_pending(),
whatever state the loop was in. The ONLY thing that empties that file out
of game is the loop itself (core/decision_detector.DecisionLoop._loop: no
fresh snapshot -> reconcile([])). So when the Phase 3 supervisor process
that owns the loop is down (crashed, or not started yet at boot) and the
file still holds a call, the banner kept painting "Dragon in 45s - 3
enemies missing" in home, lobby, champ select and every other view, with
live CONTEST / GIVE buttons and a live hotkey answer that log a choice on
a call nobody is tracking. Measured headless in S144-U-269: the banner
renders in all 11 views, 81 px tall, and pushes four out-of-game views
past their box (FUTURE (f) of the UI/UX QA ledger).

THE CONTRACT. The route consults core.decision_detector.read_heartbeat()
(the file-backed liveness read the loop writes after every in-game eval,
alive inside 5 s) and answers {"pending": []} unless `alive is True`. The
loop writes the heartbeat only while it is evaluating a live game, so the
banner is in-game-only by contract, which closes FUTURE (f) as "push"
(Active Match absorbs the banner, 740 of 742 px).

The integration cases run the REAL read_heartbeat and the REAL
DecisionStore against tmp files, so they exercise the real liveness
window, not a mocked flag.
"""
from __future__ import annotations

import json
import time
from unittest import mock

import pytest

import core.decision_detector as dd
from dashboard import routes_diag

_DECISION = {
    "id": "objective_contest:Dragon:300",
    "type": "objective_contest",
    "title": "Dragon in 45s - 3 enemies missing",
    "subtitle": "Missing: Vi (river), Ahri (mid), Jinx (bot)",
    "options": ["contest", "give"],
    "created_at_unix": 1.0,
    "created_at_game_time": 255.0,
    "expires_at_game_time": 390.0,
    "context": {},
}


class _FakeHandler:
    def __init__(self) -> None:
        self.sent = None
        self.path = "/api/decisions"

    def _send(self, status, payload, ctype):
        self.sent = (status, payload, ctype)

    @property
    def status(self) -> int:
        assert self.sent is not None, "_send was never called"
        return self.sent[0]

    @property
    def body(self) -> dict:
        assert self.sent is not None, "_send was never called"
        return json.loads(self.sent[1].decode("utf-8"))


@pytest.fixture
def files(tmp_path, monkeypatch):
    """Point the store and the heartbeat at tmp files; one pending call."""
    pending = tmp_path / "decisions_pending.json"
    log_path = tmp_path / "decisions_log.jsonl"
    heartbeat = tmp_path / "decisions_heartbeat.json"
    pending.write_text(json.dumps([_DECISION]), encoding="utf-8")
    monkeypatch.setattr(dd, "_HEARTBEAT_PATH", heartbeat)
    real_store = dd.DecisionStore

    def _store(*_a, **_k):
        return real_store(pending_path=pending, log_path=log_path)

    monkeypatch.setattr(dd, "DecisionStore", _store)
    return heartbeat


def _beat(path, last_eval_unix) -> None:
    path.write_text(json.dumps({
        "counter": 7,
        "last_eval_unix": last_eval_unix,
        "age_s": 0.0,
        "alive": True,           # stale on purpose: liveness is recomputed
        "game_time": 255.0,
        "detectors": 5,
        "detector_errors": 0,
        "last_detector_error": None,
    }), encoding="utf-8")


def _serve() -> _FakeHandler:
    h = _FakeHandler()
    routes_diag._serve_decisions(h)
    return h


def test_live_loop_serves_the_pending_call(files):
    _beat(files, time.time())
    h = _serve()
    assert h.status == 200
    assert [d["id"] for d in h.body["pending"]] == [_DECISION["id"]]
    assert h.body["pending"][0]["title"] == _DECISION["title"]


def test_dead_loop_hides_the_stale_call(files):
    # 60 s old: well past the 5 s alive window. The file still says
    # alive=True; the read recomputes it, so the stored flag cannot leak.
    _beat(files, time.time() - 60.0)
    h = _serve()
    assert h.status == 200
    assert h.body == {"pending": []}


def test_never_ran_loop_hides_the_stale_call(files):
    # No heartbeat file at all: Phase 3 not started yet at boot, while a
    # previous session left a call behind.
    assert not files.exists()
    h = _serve()
    assert h.status == 200
    assert h.body == {"pending": []}


def test_future_stamp_beyond_jitter_hides_the_call(files):
    # read_heartbeat routes the stamp through core.relay_age.is_stale: a
    # stamp from the future (backward clock step) is not alive.
    _beat(files, time.time() + 3600.0)
    h = _serve()
    assert h.body == {"pending": []}


@pytest.mark.parametrize("alive", [False, None, "true", 1])
def test_only_a_real_true_alive_opens_the_gate(alive):
    store = mock.Mock()
    store.list_pending.return_value = [_DECISION]
    with mock.patch("core.decision_detector.DecisionStore",
                    return_value=store), \
         mock.patch("core.decision_detector.read_heartbeat",
                    return_value={"alive": alive}):
        h = _serve()
    assert h.status == 200
    assert h.body == {"pending": []}


def test_a_real_true_alive_opens_the_gate():
    # Positive control for the parametrized case above, same mocks.
    store = mock.Mock()
    store.list_pending.return_value = [_DECISION]
    with mock.patch("core.decision_detector.DecisionStore",
                    return_value=store), \
         mock.patch("core.decision_detector.read_heartbeat",
                    return_value={"alive": True}):
        h = _serve()
    assert h.body == {"pending": [_DECISION]}


def test_empty_store_with_live_loop_stays_empty(files):
    files.parent.joinpath("decisions_pending.json").write_text(
        "[]", encoding="utf-8")
    _beat(files, time.time())
    h = _serve()
    assert h.body == {"pending": []}
