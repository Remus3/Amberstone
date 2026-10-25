# arch: RM-836 - a lane-lock write fault is not a lane holder | section=tests | frozen=no
"""RM-836: a lane-lock write failure is reported as what it is, and logged.

Measured at origin/main ce24e6d62, before the fix:

- ``ops/loop/lanes.py`` ``try_acquire_lane`` catches the OSError of the lock
  rewrite, releases the claim and returns ``{"refused":
  "lane_lock_unwritable", "holder": None, "pid": None, "detail":
  str(exc)[:200]}``. The module has no logger, so the cause is recorded
  nowhere, and the raw exception text rides in the result.
- ``dashboard/routes_loop_control.py`` (Mission Control :8895) overwrites
  ``detail`` with ``f"lane held by {holder} (pid {pid})"`` for EVERY refusal,
  so the operator reads "lane held by None (pid None)" for a disk or
  permission fault (and "lane held by ds, repo, uiux (pid None)" when every
  lane slot is full).
- Same root, swept: ``ops/loop/queue_loop.py`` ``run_cycle`` records the same
  "lane held by None (pid None)" detail for any refusal.

The lanes cases drive the real ``try_acquire_lane`` against a tmp lane root
with the lock rewrite made to raise an OSError whose text carries a marker, a
path and control characters. The route and queue_loop cases feed each
consumer the refusal shapes ``try_acquire_lane`` returns. Nothing touches the
live control dir and nothing launches a process.
"""
from __future__ import annotations

import importlib
import json
import logging

import pytest

from dashboard import _arm_confirm as armgate
from dashboard import _idempotency as idem
from dashboard import routes_loop_control as route

lanes = importlib.import_module("ops.loop.lanes")
qloop = importlib.import_module("ops.loop.queue_loop")

SECRET_PATH = r"C:\Example Repo\ops\loop\control\lanes\0.lock"
_CONTROL_CHARS = ("\x1b", "\r", "\n", "\x85", "\x7f")
KEY = "8c1f2e3d-4b5a-4c6d-9e7f-0a1b2c3d4e5f"


def _evil(marker: str) -> str:
    return f"{marker} at {SECRET_PATH} \x1b[31m\r\nFAKE-LINE\x85\x7f"


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from _strings(v)


def _assert_clean(doc, marker: str) -> None:
    for s in _strings(doc):
        assert marker not in s, (marker, s)
        assert "Example Repo" not in s, s
        assert "FAKE-LINE" not in s, s
        for ch in _CONTROL_CHARS:
            assert ch not in s, (repr(ch), s)


class _Cap(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def cap():
    lg = logging.getLogger("rc.loop.lanes")
    handler, prior = _Cap(), lg.level
    lg.addHandler(handler)
    lg.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        lg.removeHandler(handler)
        lg.setLevel(prior)


@pytest.fixture
def root(tmp_path):
    return tmp_path / "repo" / "ops" / "loop" / "control" / "lanes"


def _unwritable(monkeypatch, root, tmp_path, marker: str) -> dict:
    def _boom(_path, _data):
        raise OSError(13, _evil(marker), SECRET_PATH)

    monkeypatch.setattr(lanes, "_atomic_write_bytes", _boom)
    wt = tmp_path / "wt-repo"
    wt.mkdir(exist_ok=True)
    return lanes.try_acquire_lane("repo", run_id="r836", worktree=str(wt),
                                  root=root)


# --------------------------------------------------------------- ops/loop/lanes.py
def test_an_unwritable_lock_is_refused_as_such_and_left_released(
        monkeypatch, root, tmp_path, cap):
    res = _unwritable(monkeypatch, root, tmp_path, "MARK-A")
    assert res["ok"] is False
    assert res["refused"] == "lane_lock_unwritable"
    assert res["holder"] is None and res["pid"] is None
    assert not list(root.glob("*.lock")), "the claim must be released"


def test_the_result_carries_no_exception_text(monkeypatch, root, tmp_path, cap):
    res = _unwritable(monkeypatch, root, tmp_path, "MARK-B")
    _assert_clean(res, "MARK-B")


def test_the_result_is_fixed_across_exception_texts(monkeypatch, root,
                                                    tmp_path, cap):
    first = _unwritable(monkeypatch, root, tmp_path, "MARK-C1")
    second = _unwritable(monkeypatch, root, tmp_path, "MARK-C2")
    assert first == second


def test_the_cause_is_logged_once_scrubbed_with_its_type(monkeypatch, root,
                                                         tmp_path, cap):
    _unwritable(monkeypatch, root, tmp_path, "MARK-D")
    hits = [r for r in cap.records if "MARK-D" in r.getMessage()]
    assert len(hits) == 1, [r.getMessage() for r in cap.records]
    rec = hits[0]
    assert rec.levelno == logging.WARNING
    msg = rec.getMessage()
    assert "PermissionError" in msg, msg
    assert msg.startswith("lane repo: "), "the lane named"
    for ch in _CONTROL_CHARS:
        assert ch not in msg, (repr(ch), msg)


# --------------------------------------------------------------- the :8895 route
class _Lanes:
    LANES = ("upgrade", "repo", "ds", "uiux")

    def __init__(self, result: dict) -> None:
        self.result = result

    def try_acquire_lane(self, lane, *, run_id, worktree, root=None):
        return dict(self.result)

    def release_lane(self, token, root=None):
        return True


@pytest.fixture
def ctldir(tmp_path, monkeypatch):
    idem.clear()
    armgate.clear()
    ctl = tmp_path / "control"
    ctl.mkdir()
    monkeypatch.setattr(route, "CONTROL_DIR", ctl)
    yield ctl
    idem.clear()
    armgate.clear()


class _FakeH:
    def __init__(self) -> None:
        self.path = "/api/loop-control"
        self.sent = None

    def _send(self, status, body, ctype):
        self.sent = (status, body, ctype)


def _raw_post(body: dict):
    h = _FakeH()
    route._serve_loop_control(h, body)
    status, raw, _ctype = h.sent
    return status, json.loads(raw.decode("utf-8"))


def _fire(monkeypatch, result: dict):
    monkeypatch.setattr(route, "_lanes", lambda: _Lanes(result))
    body = {"action": "fire_lane", "lane": "repo", "run_id": "cafe0836",
            "worktree": "C:/wt/repo", "idempotency_key": KEY}
    if "fire_lane" in armgate.GATED_ACTIONS:
        st, armed = _raw_post({"action": "arm", "target_action": "fire_lane",
                               "target": armgate.target_of("fire_lane", body)})
        assert st == 200, armed
        body["arm_token"] = armed["arm_token"]
    return _raw_post(body)


def _old_unwritable(marker: str) -> dict:
    """The pre-fix lanes.py shape, raw text included - the route must not
    forward it even from an older lanes module."""
    return {"ok": False, "refused": "lane_lock_unwritable", "holder": None,
            "pid": None, "holders": [], "detail": _evil(marker)[:200]}


def test_the_route_does_not_read_a_write_fault_as_a_holder(ctldir, monkeypatch):
    status, payload = _fire(monkeypatch, _old_unwritable("MARK-E"))
    assert status == 200 and payload["ok"] is False
    assert payload["refused"] == "lane_lock_unwritable"
    assert "held by" not in payload["detail"], payload["detail"]
    assert "None" not in payload["detail"], payload["detail"]
    assert "lock" in payload["detail"] and "written" in payload["detail"]
    _assert_clean(payload, "MARK-E")


def test_the_route_keeps_a_real_holder_refusal(ctldir, monkeypatch):
    _status, payload = _fire(monkeypatch, {"ok": False, "refused": "lane_held",
                                           "holder": "repo", "pid": 9380,
                                           "holders": ["repo"]})
    assert payload["detail"] == "lane held by repo (pid 9380)"


def test_the_route_names_a_full_cap_without_a_none_pid(ctldir, monkeypatch):
    _status, payload = _fire(monkeypatch, {"ok": False, "refused": "lanes_full",
                                           "holder": "ds, uiux, upgrade",
                                           "pid": None,
                                           "holders": ["ds", "uiux", "upgrade"]})
    assert "None" not in payload["detail"], payload["detail"]
    assert "ds, uiux, upgrade" in payload["detail"]
    assert "lane held by" not in payload["detail"]


def test_the_route_answers_an_unknown_refusal_with_a_fixed_line(ctldir,
                                                               monkeypatch):
    _status, payload = _fire(monkeypatch, {"ok": False, "refused": "novel",
                                           "holder": None, "pid": None})
    assert "None" not in payload["detail"], payload["detail"]
    assert "held by" not in payload["detail"]


# --------------------------------------------------------------- queue_loop sibling
def _cycle(result: dict) -> dict:
    def acquire(lane, *, run_id, worktree, **_kw):
        return dict(result)

    def _never(*_a, **_k):
        raise AssertionError("a refused acquire must not reach this seam")

    state = {"t": 1000.0}

    def clock():
        state["t"] += 1.0
        return state["t"]

    return qloop.run_cycle(1, worktree="wt", acquire_retries=2,
                           acquire_wait_s=0, acquire=acquire, release=_never,
                           launch=_never, alive=_never, kill=_never,
                           sleep=lambda _s: None, clock=clock,
                           monotonic=clock)


def test_queue_loop_does_not_record_a_write_fault_as_a_holder():
    rec = _cycle(_old_unwritable("MARK-F"))
    assert rec["ok"] is False and rec["pid"] is None
    assert "held by" not in rec["detail"], rec["detail"]
    assert "None" not in rec["detail"], rec["detail"]
    assert "lock" in rec["detail"] and "written" in rec["detail"]
    _assert_clean(rec, "MARK-F")


def test_queue_loop_keeps_a_real_holder_detail():
    rec = _cycle({"ok": False, "refused": "lane_held", "holder": "ds",
                  "pid": 999})
    assert rec["outcome"] == "lane_held"
    assert "lane held by 'ds' (pid 999)" in rec["detail"], rec["detail"]
