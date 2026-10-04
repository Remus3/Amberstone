"""RM-277 - app/__init__.py _write_data() / _init_data_file() must hold the
shared coaching_data_lock around a real read-modify-write of root
coaching_data.json, so neither an app write nor a coach write is lost.

FAILURE SCENARIO (the row's): the SR coach enters _write_fields, reads the
file; the lifecycle thread runs app._write_data() on game end, blanking
action / immediate / ...; the coach then replaces the file with what it read
plus its fields, resurrecting the cleared text. And because _write_data
wrote the WHOLE stale self.data, it also erased any coach key written since
the last 500 ms poll.

The interleave is forced deterministically: the coach's json.loads is
paused right after its read (inside its critical section) while the app
write is started on another thread.
"""
from __future__ import annotations

import json
import threading

import pytest

import app as app_mod
from coach_integration import _coach as coach_mod


class _PausingJson:
    """Stand-in for the coach module's ``json``: loads() signals then waits."""

    def __init__(self, read_done: threading.Event, go: threading.Event):
        self.read_done, self.go = read_done, go

    def loads(self, s, *a, **k):
        out = json.loads(s, *a, **k)
        self.read_done.set()
        assert self.go.wait(10.0), "harness: go never set"
        return out

    def dumps(self, *a, **k):
        return json.dumps(*a, **k)


def _coach(data_file):
    c = object.__new__(coach_mod.CoachIntegration)
    c.data_file = data_file
    c._parse_response = lambda raw: {"action": "push mid", "immediate": "go",
                                     "wave": "slow push"}
    c._last_state = {}
    c._last_gs = {"kda": "3/1/4"}
    c._last_ds_rows = None
    return c


def _app(data):
    a = object.__new__(app_mod.OverlayApp)
    a.data = dict(data)
    a._last_mtime = 0
    return a


@pytest.fixture
def data_file(tmp_path, monkeypatch):
    f = tmp_path / "coaching_data.json"
    f.write_text(json.dumps({"mode": "game", "action": "OLD", "immediate": "old",
                             "pregame": "draft notes"}), encoding="utf-8")
    monkeypatch.setattr(app_mod, "DATA_FILE", f)
    return f


def test_app_blank_is_not_lost_to_a_straddling_coach_write(data_file, monkeypatch):
    read_done, go = threading.Event(), threading.Event()
    monkeypatch.setattr(coach_mod, "json", _PausingJson(read_done, go))
    coach = _coach(data_file)
    a = _app(json.loads(data_file.read_text(encoding="utf-8")))

    t_coach = threading.Thread(
        target=lambda: coach._write_fields("raw", update_ts=False), daemon=True)
    t_coach.start()
    assert read_done.wait(10.0), "coach never read the file"

    blank = {"action": "", "immediate": "", "log": []}
    t_app = threading.Thread(target=lambda: a._write_data(blank), daemon=True)
    t_app.start()
    t_app.join(0.5)          # with the lock it must still be waiting here
    go.set()
    t_coach.join(10.0)
    t_app.join(10.0)
    assert not t_coach.is_alive() and not t_app.is_alive()

    final = json.loads(data_file.read_text(encoding="utf-8"))
    # The app's update (issued after the coach's) is not lost ...
    assert final["action"] == "" and final["immediate"] == "", final
    # ... and neither is the coach's non-overlapping update.
    assert final["wave"] == "slow push", final
    assert final["kda"] == "3/1/4", final
    assert final["pregame"] == "draft notes", final


def test_app_field_write_preserves_keys_written_since_last_poll(data_file):
    a = _app({"mode": "game", "action": "OLD"})      # stale poll copy
    # A coach write lands after the app's last poll:
    cur = json.loads(data_file.read_text(encoding="utf-8"))
    cur["daemon_slayer_picks"] = [{"id": 1}]
    data_file.write_text(json.dumps(cur), encoding="utf-8")
    a._write_data({"mode": "client"})
    final = json.loads(data_file.read_text(encoding="utf-8"))
    assert final["mode"] == "client"
    assert final["daemon_slayer_picks"] == [{"id": 1}], final
    assert a.data == final, "app adopts the merged file as its copy"


def test_write_data_holds_the_shared_lock(data_file, monkeypatch):
    seen = []
    import core.coaching_data_lock as lk
    real = lk.coaching_data_lock

    def _spy():
        seen.append(1)
        return real()

    monkeypatch.setattr(lk, "coaching_data_lock", _spy)
    _app({})._write_data({"mode": "client"})
    _app({})._init_data_file()
    assert len(seen) == 2


def test_init_data_file_keeps_pregame(data_file):
    _app({})._init_data_file()
    final = json.loads(data_file.read_text(encoding="utf-8"))
    assert final["pregame"] == "draft notes"
    assert final["mode"] == "client" and final["action"] == ""


def test_legacy_no_fields_call_still_replaces_whole_dict(data_file):
    a = _app({"mode": "client", "action": "x"})
    a._write_data()
    final = json.loads(data_file.read_text(encoding="utf-8"))
    assert final == {"mode": "client", "action": "x"}
