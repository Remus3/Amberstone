"""s144 true-audit cycle 123 - core/objective_playbook_shadow.py hardening.

Each test is named for the weakness it pins (RM-1583..224):

- 219: a non-finite, non-numeric or bool game clock was written verbatim (a NaN
  clock made the row non-strict JSON, an infinite one fell to an uncaught
  OverflowError path, a string clock collapsed into bucket 0);
- 220: non-string text fields (mode, playbook tag / line, lead_state, phase,
  native objective) were written verbatim, so a dict playbook_line counted as
  "present" in the report, and unbounded prose was written whole;
- 221: a blank / whitespace-only champion produced a row;
- 222: the dedup check-then-write was unlocked, so two concurrent /api/state
  builders both wrote the same tick;
- 223: a torn tail (a crash mid-append left no trailing newline) glued the
  next record onto it, losing both rows; text-mode append wrote CRLF;
- 224: a persistent write failure was logged at DEBUG only.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from pathlib import Path

import pytest

import core.objective_playbook_shadow as ops
from tests._timing_budget import fleet_test_guard

_PLAY ={"tag": "playbook_dragon", "line": "Drake in 20s: group bot", "kind": "playbook"}


@pytest.fixture(autouse=True)
def _fresh_state():
    ops._LAST_SIG.clear()
    ops._LAST_GT.clear()
    getattr(ops, "_WARN_AT", {}).clear()
    yield
    ops._LAST_SIG.clear()
    ops._LAST_GT.clear()
    getattr(ops, "_WARN_AT", {}).clear()


def _strict_rows(path: Path) -> list[dict]:
    def _refuse(tok):
        raise ValueError("non-strict JSON constant " + tok)

    raw = path.read_bytes()
    assert b"\r" not in raw, "rows must be LF-only bytes"
    return [json.loads(ln, parse_constant=_refuse)
            for ln in raw.decode("utf-8").split("\n") if ln.strip()]


def _log(path, **kw):
    args = {"playbook": _PLAY, "native_objective": "take drake",
            "lead_state": "ahead", "phase": "mid", "game_time_s": 300.0}
    args.update(kw)
    champ = args.pop("champ", "Aatrox")
    mode = args.pop("mode", "sr")
    return ops.log_objective_playbook(mode, champ, path=path, **args)


# --- RM-1583: the game clock -------------------------------------------

@pytest.mark.parametrize("clock", [
    math.nan, math.inf, -math.inf, "300", True, False, b"300", [300], {"t": 1},
])
def test_s144_t219_junk_game_clock_is_refused(tmp_path, clock, caplog):
    caplog.set_level(logging.DEBUG, logger="rc.objective_playbook_shadow")
    p = tmp_path / "ob.jsonl"
    assert _log(p, game_time_s=clock) is None
    assert not p.exists()
    # A junk clock is a quiet gate miss, not an error path.
    assert [r for r in caplog.records
            if r.name == "rc.objective_playbook_shadow"] == []


@pytest.mark.parametrize("clock", [0, 0.0, 300, 300.5, 3599])
def test_s144_t219_real_game_clock_is_written_as_strict_json(tmp_path, clock):
    p = tmp_path / "ob.jsonl"
    rec = _log(p, game_time_s=clock)
    assert rec is not None
    rows = _strict_rows(p)
    assert len(rows) == 1
    assert rows[0]["game_time_s"] == clock


def test_s144_t219_nan_clock_does_not_poison_the_next_real_tick(tmp_path):
    p = tmp_path / "ob.jsonl"
    assert _log(p, game_time_s=math.nan) is None
    assert _log(p, game_time_s=300.0) is not None
    assert len(_strict_rows(p)) == 1


# --- RM-1584: typed, bounded text fields --------------------------------

def test_s144_t220_non_string_text_fields_are_recorded_as_null(tmp_path):
    p = tmp_path / "ob.jsonl"
    rec = _log(p, mode=5, playbook={"tag": ["x"], "line": {"a": 1}},
               lead_state=3, phase=object())
    assert rec is not None
    row = _strict_rows(p)[0]
    for key in ("mode", "playbook_tag", "playbook_line", "lead_state", "phase"):
        assert row[key] is None, key
    assert row["native_objective"] == "take drake"


def test_s144_t220_unserialisable_playbook_field_still_writes_the_row(tmp_path):
    p = tmp_path / "ob.jsonl"
    rec = _log(p, playbook={"tag": {1, 2}, "line": "Drake in 20s"})
    assert rec is not None
    row = _strict_rows(p)[0]
    assert row["playbook_tag"] is None
    assert row["playbook_line"] == "Drake in 20s"


def test_s144_t220_overlong_prose_is_capped(tmp_path):
    p = tmp_path / "ob.jsonl"
    rec = _log(p, native_objective="x" * 50000,
               playbook={"tag": "t", "line": "y" * 50000})
    assert rec is not None
    row = _strict_rows(p)[0]
    assert len(row["native_objective"]) == ops._MAX_TEXT
    assert len(row["playbook_line"]) == ops._MAX_TEXT
    assert ops._MAX_TEXT >= 500


def test_s144_t220_well_typed_record_is_unchanged(tmp_path):
    p = tmp_path / "ob.jsonl"
    rec = _log(p)
    row = _strict_rows(p)[0]
    assert row == rec
    assert (row["mode"], row["playbook_tag"], row["playbook_line"],
            row["lead_state"], row["phase"], row["native_objective"]) == (
        "sr", "playbook_dragon", "Drake in 20s: group bot", "ahead", "mid",
        "take drake")


# --- RM-1585: blank champion --------------------------------------------

@pytest.mark.parametrize("champ", ["", " ", "\t\n", "   "])
def test_s144_t221_blank_champion_is_refused(tmp_path, champ):
    p = tmp_path / "ob.jsonl"
    assert _log(p, champ=champ) is None
    assert not p.exists()


# --- RM-1586: concurrent writers ----------------------------------------

def test_s144_t222_concurrent_same_tick_writes_one_row(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    class GatedPath(type(tmp_path)):
        def open(self, *a, **k):  # noqa: A003 - Path API
            calls.append(1)
            if len(calls) == 1:
                entered.set()
                release.wait(5)
            return super().open(*a, **k)

    p = GatedPath(tmp_path / "ob.jsonl")
    errors = []

    def _call():
        try:
            _log(p)
        except Exception as exc:  # noqa: BLE001 - surfaced by the assert below
            errors.append(exc)

    t1 = threading.Thread(target=_call, name="s144-t222-a")
    t1.start()
    assert entered.wait(fleet_test_guard.budget(5))
    t2 = threading.Thread(target=_call, name="s144-t222-b")
    t2.start()
    t2.join(0.5)
    release.set()
    t1.join(fleet_test_guard.budget(5))
    t2.join(fleet_test_guard.budget(5))
    assert not t1.is_alive() and not t2.is_alive()
    assert errors == []
    assert len(_strict_rows(Path(p))) == 1


# --- RM-1587: torn tail and line endings --------------------------------

def test_s144_t223_torn_tail_is_terminated_before_the_next_row(tmp_path):
    p = tmp_path / "ob.jsonl"
    good = json.dumps({"ts": "a", "mode": "sr", "my_champion": "Ahri",
                       "game_time_s": 10})
    p.write_bytes((good + "\n" + '{"ts": "b", "mode": "s').encode("utf-8"))
    rec = _log(p)
    assert rec is not None
    lines = p.read_bytes().decode("utf-8").split("\n")
    assert lines[0] == good
    assert lines[1] == '{"ts": "b", "mode": "s'
    assert json.loads(lines[2]) == rec
    assert lines[3] == ""


def test_s144_t223_append_is_lf_only_and_preserves_existing_rows(tmp_path):
    p = tmp_path / "ob.jsonl"
    _log(p, game_time_s=300.0)
    _log(p, game_time_s=310.0)
    raw = p.read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"\n")
    assert [r["game_time_s"] for r in _strict_rows(p)] == [300.0, 310.0]


def test_s144_t223_empty_existing_file_gets_no_leading_blank_line(tmp_path):
    p = tmp_path / "ob.jsonl"
    p.write_bytes(b"")
    _log(p)
    assert not p.read_bytes().startswith(b"\n")


# --- RM-1588: a persistent write failure is visible ---------------------

def test_s144_t224_write_failure_warns_once_per_minute_and_never_raises(
        tmp_path, monkeypatch, caplog):
    blocker = tmp_path / "ob.jsonl"
    blocker.mkdir()  # opening a directory for append fails with an OSError
    now = [1000.0]
    monkeypatch.setattr(ops, "_now", lambda: now[0], raising=False)
    caplog.set_level(logging.DEBUG, logger="rc.objective_playbook_shadow")

    def _warnings():
        return [r for r in caplog.records
                if r.name == "rc.objective_playbook_shadow"
                and r.levelno == logging.WARNING]

    assert _log(blocker) is None
    assert len(_warnings()) == 1
    now[0] += 30.0
    assert _log(blocker) is None
    assert len(_warnings()) == 1
    now[0] += 31.0
    assert _log(blocker) is None
    assert len(_warnings()) == 2
    # The dedup state was not advanced by a failed write: a later good write of
    # the same tick still lands.
    blocker.rmdir()
    assert _log(blocker) is not None
    assert len(_strict_rows(blocker)) == 1
