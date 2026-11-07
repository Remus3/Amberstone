"""s144 true-audit cycle 184 - core/macro_response_shadow.py hardening.

The WS4 macro shadow is the sibling of core/objective_playbook_shadow.py, which
cycle 123 hardened (tests/test_objective_playbook_shadow_hardening_s144.py).
S144-T-225 filed the same writer shape here. Each test is named for the
weakness it pins:

- 558: a non-finite, non-numeric or bool game clock was written verbatim (a
  NaN clock made the row non-strict JSON, an infinite one fell to the silent
  outer except, a string clock collapsed into bucket 0 and was written);
- 559: non-string text fields (mode, macro tag / line, lead_state, phase) were
  written verbatim, unbounded prose was written whole, and one unserialisable
  macro field (a set) dropped the whole row;
- 560: a blank / whitespace-only champion produced a row;
- 561: the dedup check-then-write was unlocked, so two concurrent /api/state
  builders both wrote the same tick;
- 562: a torn tail (a crash mid-append left no trailing newline) glued the
  next record onto it, losing both rows;
- 563: a persistent write failure was logged at DEBUG only, so the
  do-not-flip-blind gate could starve with no visible signal.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from pathlib import Path

import pytest

import core.macro_response_shadow as mrs
from tests._timing_budget import fleet_test_guard

_MACRO = {"tag": "macro_lost_objective", "line": "Baron lost - defend",
          "kind": "macro_response"}
_LOGGER = "rc.macro_response_shadow"


@pytest.fixture(autouse=True)
def _fresh_state():
    mrs._LAST_SIG.clear()
    mrs._LAST_GT.clear()
    getattr(mrs, "_WARN_AT", {}).clear()
    yield
    mrs._LAST_SIG.clear()
    mrs._LAST_GT.clear()
    getattr(mrs, "_WARN_AT", {}).clear()


def _strict_rows(path: Path) -> list[dict]:
    def _refuse(tok):
        raise ValueError("non-strict JSON constant " + tok)

    raw = path.read_bytes()
    assert b"\r" not in raw, "rows must be LF-only bytes"
    return [json.loads(ln, parse_constant=_refuse)
            for ln in raw.decode("utf-8").split("\n") if ln.strip()]


def _log(path, **kw):
    args = {"macro": _MACRO, "native_objective": "defend base",
            "lead_state": "behind", "phase": "late", "game_time_s": 1310.0}
    args.update(kw)
    champ = args.pop("champ", "Aatrox")
    mode = args.pop("mode", "sr")
    return mrs.log_macro_response(mode, champ, path=path, **args)


# --- S144-T-558: the game clock -----------------------------------------

@pytest.mark.parametrize("clock", [
    math.nan, math.inf, -math.inf, "1310", True, False, b"1310", [1310],
    {"t": 1}, 10 ** 400,
])
def test_s144_t558_junk_game_clock_is_refused(tmp_path, clock, caplog):
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    p = tmp_path / "m.jsonl"
    assert _log(p, game_time_s=clock) is None
    assert not p.exists()
    # A junk clock is a quiet gate miss, not an error path.
    assert [r for r in caplog.records if r.name == _LOGGER] == []


@pytest.mark.parametrize("clock", [0, 0.0, 1310, 1310.5, 3599])
def test_s144_t558_real_game_clock_is_written_as_strict_json(tmp_path, clock):
    p = tmp_path / "m.jsonl"
    rec = _log(p, game_time_s=clock)
    assert rec is not None
    rows = _strict_rows(p)
    assert len(rows) == 1
    assert rows[0]["game_time_s"] == clock


def test_s144_t558_nan_clock_does_not_poison_the_next_real_tick(tmp_path):
    p = tmp_path / "m.jsonl"
    assert _log(p, game_time_s=math.nan) is None
    assert _log(p, game_time_s=1310.0) is not None
    assert len(_strict_rows(p)) == 1


def test_s144_t558_string_clock_does_not_suppress_bucket_zero(tmp_path):
    # Before: "1310" fell into bucket 0 and was written, so a real load-screen
    # tick (clock 0) with the same fields was deduped away.
    p = tmp_path / "m.jsonl"
    assert _log(p, game_time_s="1310") is None
    assert _log(p, game_time_s=0) is not None
    assert [r["game_time_s"] for r in _strict_rows(p)] == [0]


# --- S144-T-559: typed, bounded text fields -----------------------------

def test_s144_t559_non_string_text_fields_are_recorded_as_null(tmp_path):
    p = tmp_path / "m.jsonl"
    rec = _log(p, mode=5, macro={"tag": ["x"], "line": {"a": 1}},
               lead_state=3, phase=7)
    assert rec is not None
    row = _strict_rows(p)[0]
    for key in ("mode", "macro_tag", "macro_line", "lead_state", "phase"):
        assert row[key] is None, key
    assert row["native_objective"] == "defend base"


def test_s144_t559_unserialisable_macro_field_still_writes_the_row(tmp_path):
    p = tmp_path / "m.jsonl"
    rec = _log(p, macro={"tag": {1, 2}, "line": "Baron lost - defend"},
               phase=object())
    assert rec is not None
    row = _strict_rows(p)[0]
    assert row["macro_tag"] is None
    assert row["phase"] is None
    assert row["macro_line"] == "Baron lost - defend"


def test_s144_t559_overlong_prose_is_capped(tmp_path):
    p = tmp_path / "m.jsonl"
    rec = _log(p, native_objective="x" * 50000,
               macro={"tag": "t", "line": "y" * 50000})
    assert rec is not None
    row = _strict_rows(p)[0]
    assert len(row["native_objective"]) == mrs._MAX_TEXT
    assert len(row["macro_line"]) == mrs._MAX_TEXT
    assert mrs._MAX_TEXT >= 500


def test_s144_t559_well_typed_record_is_unchanged(tmp_path):
    p = tmp_path / "m.jsonl"
    rec = _log(p)
    row = _strict_rows(p)[0]
    assert row == rec
    assert (row["mode"], row["my_champion"], row["macro_tag"],
            row["macro_line"], row["lead_state"], row["phase"],
            row["native_objective"], row["game_time_s"]) == (
        "sr", "Aatrox", "macro_lost_objective", "Baron lost - defend",
        "behind", "late", "defend base", 1310.0)
    assert isinstance(row["engine_version"], str) and row["engine_version"]


def test_s144_t559_none_macro_still_records_a_silent_tick(tmp_path):
    p = tmp_path / "m.jsonl"
    rec = _log(p, macro=None)
    assert rec is not None
    row = _strict_rows(p)[0]
    assert row["macro_tag"] is None and row["macro_line"] is None
    assert row["native_objective"] == "defend base"


# --- S144-T-560: blank champion -----------------------------------------

@pytest.mark.parametrize("champ", ["", " ", "\t\n", "   "])
def test_s144_t560_blank_champion_is_refused(tmp_path, champ):
    p = tmp_path / "m.jsonl"
    assert _log(p, champ=champ) is None
    assert not p.exists()


# --- S144-T-561: concurrent writers -------------------------------------

def test_s144_t561_concurrent_same_tick_writes_one_row(tmp_path):
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

    p = GatedPath(tmp_path / "m.jsonl")
    errors = []

    def _call():
        try:
            _log(p)
        except Exception as exc:  # noqa: BLE001 - surfaced by the assert below
            errors.append(exc)

    t1 = threading.Thread(target=_call, name="s144-t561-a")
    t1.start()
    assert entered.wait(fleet_test_guard.budget(5))
    t2 = threading.Thread(target=_call, name="s144-t561-b")
    t2.start()
    t2.join(0.5)
    release.set()
    t1.join(fleet_test_guard.budget(5))
    t2.join(fleet_test_guard.budget(5))
    assert not t1.is_alive() and not t2.is_alive()
    assert errors == []
    assert len(_strict_rows(Path(p))) == 1


# --- S144-T-562: torn tail and line endings -----------------------------

def test_s144_t562_torn_tail_is_terminated_before_the_next_row(tmp_path):
    p = tmp_path / "m.jsonl"
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


def test_s144_t562_append_is_lf_only_and_preserves_existing_rows(tmp_path):
    p = tmp_path / "m.jsonl"
    p.write_bytes(b'{"ts": "old", "game_time_s": 5}\r\n')
    _log(p, game_time_s=1310.0)
    _log(p, game_time_s=1320.0)
    raw = p.read_bytes()
    # The pre-existing CRLF row is kept byte for byte; new rows are LF-only.
    assert raw.startswith(b'{"ts": "old", "game_time_s": 5}\r\n')
    tail = raw[len(b'{"ts": "old", "game_time_s": 5}\r\n'):]
    assert b"\r" not in tail
    assert raw.endswith(b"\n")
    assert [json.loads(ln)["game_time_s"]
            for ln in tail.decode("utf-8").split("\n") if ln] == [1310.0, 1320.0]


def test_s144_t562_empty_existing_file_gets_no_leading_blank_line(tmp_path):
    p = tmp_path / "m.jsonl"
    p.write_bytes(b"")
    _log(p)
    assert not p.read_bytes().startswith(b"\n")


# --- S144-T-563: a persistent write failure is visible ------------------

def test_s144_t563_write_failure_warns_once_per_minute_and_never_raises(
        tmp_path, monkeypatch, caplog):
    blocker = tmp_path / "m.jsonl"
    blocker.mkdir()  # opening a directory for append fails with an OSError
    now = [1000.0]
    monkeypatch.setattr(mrs, "_now", lambda: now[0], raising=False)
    caplog.set_level(logging.DEBUG, logger=_LOGGER)

    def _warnings():
        return [r for r in caplog.records
                if r.name == _LOGGER and r.levelno == logging.WARNING]

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


def test_s144_t563_warning_carries_no_row_content(tmp_path, monkeypatch,
                                                   caplog):
    blocker = tmp_path / "m.jsonl"
    blocker.mkdir()
    monkeypatch.setattr(mrs, "_now", lambda: 1000.0, raising=False)
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    assert _log(blocker, native_objective="SECRET-PROSE-XYZ") is None
    text = "\n".join(r.getMessage() for r in caplog.records
                     if r.name == _LOGGER)
    assert text
    assert "SECRET-PROSE-XYZ" not in text


# --- sibling parity: one contract for the WS3 and WS4 shadows -----------

def test_s144_t558_helpers_match_the_ws3_sibling():
    import core.objective_playbook_shadow as ops

    assert mrs._MAX_TEXT == ops._MAX_TEXT
    assert mrs._WARN_INTERVAL_S == ops._WARN_INTERVAL_S
    for v in (0, 1.5, True, "3", math.nan, math.inf, None, 10 ** 400, [1]):
        assert mrs._clock(v) == ops._clock(v), v
    for v in ("x", "y" * 5000, 5, None, b"x"):
        assert mrs._text(v) == ops._text(v), v
    # Distinct locks: the two writers append to different files.
    assert mrs._LOCK is not ops._LOCK
