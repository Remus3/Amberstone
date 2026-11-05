"""Lane 8 true-audit (s144 cycle 104) of core/champ_select_shadow.py.

The shadow writer records, beside the live Haiku pick advice, what the
deterministic advisor would have said, so the precompute path can be graded
offline. Every finding below made that corpus wrong or lossy:

F1  the gate was truthiness, not coach_pick's name rule, so a body coach_pick
    refuses ("(no champion locked yet)") still wrote a row (RM-1337 half).
F2  a string list field was split into characters, a dict read by key.
F3  non-string list entries and padded names were written raw.
F4  list fields were unbounded (one POST of 1 MiB = one 1 MiB row).
F5  is_aram was bool(value): the string "false" recorded an ARAM game, and an
    ARAM queue with no flag (which coach_pick treats as ARAM) recorded Rift.
F6  queue_id was written raw: NaN wrote a non-JSON token, strings and bools
    went through as-is.
F7  non-string advice values were written raw.
F8  a degraded native reply consumed the dedup slot of the real reply for the
    same pick state.
F9  the dedup check and the append were not serialised, so concurrent handler
    threads (ThreadingHTTPServer) wrote duplicate rows.
F10 a torn last line (crash mid-append) glued the next record onto it, and the
    text-mode append wrote CRLF on Windows.
F11 every failure was logged at DEBUG only, so a data dir that cannot be
    written was invisible at the default level.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import pytest

import coaches.champ_select_coach as csc
from core import champ_select_shadow as css
from core.champ_select_shadow import log_champ_select_advice
from core.queue_modes import QUEUE_ID_TO_MODE_KEY

_STATE = {
    "is_aram": True, "queue_id": 450, "my_champion": "Ahri",
    "my_team": ["Ahri", "Zed", "Lux"], "their_team": ["Caitlyn", "Leona"],
    "bench": ["Ashe"],
}
_REAL = {"ok": True, "advice": "Stay Ahri", "swap": "", "summoners": "Flash + Heal",
         "watchout": "Caitlyn"}
_PAUSED = {"ok": False, "advice": "(coaching paused - retrying)", "swap": "",
           "summoners": "", "watchout": ""}
_DET = {"advice": "Stay Ahri - solid.", "swap": "", "summoners": "Flash + Barrier",
        "watchout": "Watch Caitlyn."}


@pytest.fixture(autouse=True)
def _fresh_dedup_state(monkeypatch):
    # pytest reuses a deleted tmp dir NAME for a later test (retention
    # "failed"), and the dedup key is the path string, so module state from
    # one test would dedup the next test's first row.
    monkeypatch.setattr(css, "_LAST_SIG", {})
    monkeypatch.setattr(css, "_WARNED", set())


def _rows(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _state(**over):
    s = dict(_STATE)
    s.update(over)
    return s


# ---------------------------------------------------------------- F1


_REFUSED_CHAMPIONS = [
    "   ",
    "x" * 65,
    "***",
    {"name": "Ahri"},
    ["Ahri"],
    7,
    True,
]


@pytest.mark.parametrize("champ", _REFUSED_CHAMPIONS, ids=repr)
def test_f1_body_coach_pick_refuses_writes_no_row(tmp_path, champ, monkeypatch):
    # Parity first: coach_pick itself refuses this champion before any spend.
    monkeypatch.setattr("core.cost_tracker.get_tracker",
                        lambda: (_ for _ in ()).throw(RuntimeError("no tracker")))
    refused = csc.coach_pick(_state(my_champion=champ), None)
    assert refused["advice"] == "(no champion locked yet)"
    p = tmp_path / "cs.jsonl"
    assert log_champ_select_advice(_state(my_champion=champ), refused, _DET, path=p) is None
    assert not p.exists()


def test_f1_padded_champion_recorded_as_coach_pick_sends_it(tmp_path):
    p = tmp_path / "cs.jsonl"
    rec = log_champ_select_advice(_state(my_champion="  Ahri  "), _REAL, _DET, path=p)
    assert rec is not None
    assert rec["my_champion"] == "Ahri" == csc._name("  Ahri  ")


# ---------------------------------------------------------------- F2 / F3 / F4


def test_f2_string_list_field_is_not_split_into_characters(tmp_path):
    rec = log_champ_select_advice(_state(my_team="Ahri"), _REAL, _DET,
                                  path=tmp_path / "cs.jsonl")
    assert rec is not None
    assert rec["my_team"] == []


def test_f2_dict_list_field_is_not_read_by_key(tmp_path):
    rec = log_champ_select_advice(_state(their_team={"Zed": 1, "Lux": 2}), _REAL, _DET,
                                  path=tmp_path / "cs.jsonl")
    assert rec is not None
    assert rec["their_team"] == []


def test_f3_non_string_and_blank_entries_are_dropped_and_names_stripped(tmp_path):
    rec = log_champ_select_advice(
        _state(my_team=["Zed", 5, None, {"a": 1}, "   ", " Lux ", "y" * 65]),
        _REAL, _DET, path=tmp_path / "cs.jsonl")
    assert rec is not None
    assert rec["my_team"] == ["Zed", "Lux"]


def test_f4_list_fields_are_capped_at_coach_pick_cap(tmp_path):
    p = tmp_path / "cs.jsonl"
    many = [f"Champ{i}" for i in range(5000)]
    rec = log_champ_select_advice(_state(their_team=many, bench=many), _REAL, _DET, path=p)
    assert rec is not None
    assert rec["their_team"] == many[: csc._MAX_NAMES]
    assert rec["bench"] == many[: csc._MAX_NAMES]
    assert p.stat().st_size < 4096


# ---------------------------------------------------------------- F5 / F6


def test_f5_string_false_is_not_aram(tmp_path):
    rec = log_champ_select_advice(_state(is_aram="false", queue_id=420), _REAL, _DET,
                                  path=tmp_path / "cs.jsonl")
    assert rec is not None
    assert rec["is_aram"] is False


def test_f5_aram_queue_without_flag_is_aram_like_coach_pick(tmp_path):
    assert QUEUE_ID_TO_MODE_KEY.get(450) == "aram"
    st = _state(queue_id=450)
    del st["is_aram"]
    rec = log_champ_select_advice(st, _REAL, _DET, path=tmp_path / "cs.jsonl")
    assert rec is not None
    assert rec["is_aram"] is True


@pytest.mark.parametrize("qid", ["450", 450.0, float("nan"), float("inf"), True, -1, 2 ** 40],
                         ids=repr)
def test_f6_bad_queue_id_recorded_as_null(tmp_path, qid):
    p = tmp_path / "cs.jsonl"
    rec = log_champ_select_advice(_state(queue_id=qid, is_aram=False), _REAL, _DET, path=p)
    assert rec is not None
    assert rec["queue_id"] is None

    def _no_constants(name):
        raise AssertionError(f"non-JSON token {name} in the shadow row")

    line = p.read_text(encoding="utf-8").splitlines()[0]
    assert json.loads(line, parse_constant=_no_constants)["queue_id"] is None


def test_f6_custom_queue_zero_is_kept(tmp_path):
    rec = log_champ_select_advice(_state(queue_id=0, is_aram=False), _REAL, _DET,
                                  path=tmp_path / "cs.jsonl")
    assert rec is not None
    assert rec["queue_id"] == 0


# ---------------------------------------------------------------- F7


def test_f7_non_string_advice_values_become_empty(tmp_path):
    native = {"ok": True, "advice": None, "swap": {"x": 1}, "summoners": 5,
              "watchout": "Watch Zed"}
    rec = log_champ_select_advice(_STATE, native, ["not", "a", "dict"],
                                  path=tmp_path / "cs.jsonl")
    assert rec is not None
    assert rec["native"] == {"advice": "", "swap": "", "summoners": "",
                             "watchout": "Watch Zed"}
    assert rec["deterministic"] == {"advice": "", "swap": "", "summoners": "",
                                    "watchout": ""}


# ---------------------------------------------------------------- F8


def test_f8_degraded_reply_does_not_consume_the_real_replys_dedup_slot(tmp_path):
    p = tmp_path / "cs.jsonl"
    assert log_champ_select_advice(_STATE, _PAUSED, _DET, path=p) is not None
    assert log_champ_select_advice(_STATE, _REAL, _DET, path=p) is not None
    assert log_champ_select_advice(_STATE, _REAL, _DET, path=p) is None
    advice = [r["native"]["advice"] for r in _rows(p)]
    assert advice == ["(coaching paused - retrying)", "Stay Ahri"]


def test_f8_repeated_degraded_reply_is_still_deduped(tmp_path):
    p = tmp_path / "cs.jsonl"
    assert log_champ_select_advice(_STATE, _PAUSED, _DET, path=p) is not None
    assert log_champ_select_advice(_STATE, _PAUSED, _DET, path=p) is None
    assert len(_rows(p)) == 1


def test_dedup_is_consecutive_only(tmp_path):
    # Characterisation of the documented contract: the dedup compares with the
    # LAST written pick state per target, so A, B, A writes three rows.
    p = tmp_path / "cs.jsonl"
    b = _state(my_champion="Lux")
    for st in (_STATE, b, _STATE):
        assert log_champ_select_advice(st, _REAL, _DET, path=p) is not None
    assert len(_rows(p)) == 3


# ---------------------------------------------------------------- F9


class _SlowJson:
    """json stand-in whose dumps sleeps, to hold the check-then-write window
    open long enough for every thread to enter it."""

    def __init__(self, ev: threading.Event):
        self._ev = ev

    def dumps(self, *a, **k):
        self._ev.wait(0.05)
        return json.dumps(*a, **k)

    def __getattr__(self, name):
        return getattr(json, name)


def test_f9_concurrent_identical_posts_write_one_row(tmp_path, monkeypatch):
    p = tmp_path / "cs.jsonl"
    monkeypatch.setattr(css, "json", _SlowJson(threading.Event()))
    n = 8
    barrier = threading.Barrier(n)
    results = []

    def _post():
        barrier.wait()
        results.append(log_champ_select_advice(_STATE, _REAL, _DET, path=p))

    threads = [threading.Thread(target=_post, name=f"cs-shadow-{i}") for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert len(results) == n
    assert sum(r is not None for r in results) == 1
    assert len(_rows(p)) == 1


# ---------------------------------------------------------------- F10


def test_f10_torn_last_line_does_not_swallow_the_next_record(tmp_path):
    p = tmp_path / "cs.jsonl"
    p.write_bytes(b'{"ts": "torn", "my_champ')
    rec = log_champ_select_advice(_STATE, _REAL, _DET, path=p)
    assert rec is not None
    lines = p.read_bytes().split(b"\n")
    assert lines[0] == b'{"ts": "torn", "my_champ'
    assert json.loads(lines[1])["native"]["advice"] == "Stay Ahri"


def test_f10_rows_are_lf_terminated_bytes(tmp_path):
    p = tmp_path / "cs.jsonl"
    log_champ_select_advice(_STATE, _REAL, _DET, path=p)
    log_champ_select_advice(_state(my_champion="Lux"), _REAL, _DET, path=p)
    data = p.read_bytes()
    assert b"\r" not in data
    assert data.endswith(b"\n")
    assert data.count(b"\n") == 2


# ---------------------------------------------------------------- F11


def test_f11_write_failure_warns_once_and_never_raises(tmp_path, caplog):
    target = tmp_path / "is_a_dir.jsonl"
    target.mkdir()
    caplog.set_level(logging.WARNING, logger="rc.champ_select_shadow")
    assert log_champ_select_advice(_STATE, _REAL, _DET, path=target) is None
    assert log_champ_select_advice(_state(my_champion="Lux"), _REAL, _DET,
                                   path=target) is None
    warns = [r for r in caplog.records
             if r.name == "rc.champ_select_shadow" and r.levelno == logging.WARNING]
    assert len(warns) == 1


def test_f11_warning_rearms_after_a_successful_write(tmp_path, caplog, monkeypatch):
    p = tmp_path / "cs.jsonl"
    caplog.set_level(logging.WARNING, logger="rc.champ_select_shadow")
    real_open = Path.open

    def _boom(self, *a, **k):
        if self == p:
            raise PermissionError("locked")
        return real_open(self, *a, **k)

    monkeypatch.setattr(Path, "open", _boom)
    assert log_champ_select_advice(_STATE, _REAL, _DET, path=p) is None
    monkeypatch.setattr(Path, "open", real_open)
    assert log_champ_select_advice(_STATE, _REAL, _DET, path=p) is not None
    monkeypatch.setattr(Path, "open", _boom)
    assert log_champ_select_advice(_state(my_champion="Lux"), _REAL, _DET, path=p) is None
    warns = [r for r in caplog.records
             if r.name == "rc.champ_select_shadow" and r.levelno == logging.WARNING]
    assert len(warns) == 2
