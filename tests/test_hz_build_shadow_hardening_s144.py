"""s144 true-audit cycle 124 - core.hz_build_shadow hardening (RM-1589..RM-1596).

Every test writes to a tmp path (the module's test seam), never the live
data/hz_build_shadow.jsonl. Each test names the finding it pins.
"""
from __future__ import annotations

import json
import logging
import threading
import time

import pytest

from core import hz_build_shadow as hbs


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    # Dedup / freshness / warn state is per target, but a test that reuses a
    # tmp path name across parametrized cases must not inherit it.
    monkeypatch.setattr(hbs, "_LAST_SIG", {})
    monkeypatch.setattr(hbs, "_LAST_GT", {})
    if hasattr(hbs, "_WARN_AT"):
        monkeypatch.setattr(hbs, "_WARN_AT", {})


def _rows(path):
    return [json.loads(ln) for ln in path.read_bytes().decode("utf-8").split("\n") if ln.strip()]


def _log(path, **kw):
    args = dict(lean="anti_tank", choices=[{"key": "A", "label": "Build anti-tank"}],
                covered=True, item_count=1, game_time_s=600.0, path=path)
    args.update(kw)
    mode = args.pop("mode", "sr")
    champ = args.pop("my_champion", "Ahri")
    enemies = args.pop("enemy_comp", ["Malphite", "Ornn"])
    return hbs.log_precomputed_build(mode, champ, enemies, **args)


# RM-1589: a NaN / Infinity / bool / string / overflowing clock is not a tick.
@pytest.mark.parametrize("clock", [float("nan"), float("inf"), float("-inf"),
                                   True, False, "600", b"600", [600],
                                   pytest.param(10 ** 400, id="huge-int")])
def test_junk_clock_is_a_quiet_refusal(tmp_path, clock, caplog):
    p = tmp_path / "b.jsonl"
    with caplog.at_level(logging.DEBUG, logger="rc.hz_build_shadow"):
        assert _log(p, game_time_s=clock) is None
    assert not p.exists()
    # Quiet: refused at the gate, not by a later encode / arithmetic failure.
    assert [r for r in caplog.records if r.name == "rc.hz_build_shadow"] == []


def test_junk_clock_records_no_dedup_state(tmp_path):
    p = tmp_path / "b.jsonl"
    assert _log(p, game_time_s=float("nan")) is None
    assert _log(p, game_time_s=600.0) is not None
    assert len(_rows(p)) == 1


def test_none_clock_still_records_and_int_clock_kept(tmp_path):
    p = tmp_path / "b.jsonl"
    assert _log(p, game_time_s=None) is not None
    assert _log(p, game_time_s=900, item_count=3) is not None
    rows = _rows(p)
    assert rows[0]["game_time_s"] is None
    assert rows[1]["game_time_s"] == 900


# RM-1590: the enemy comp is a list of champion-name strings only.
def test_string_enemy_comp_is_not_split_into_characters(tmp_path):
    p = tmp_path / "b.jsonl"
    rec = _log(p, enemy_comp="Malphite")
    assert rec is not None
    assert _rows(p)[0]["enemy_comp"] == []


def test_dict_and_scalar_enemy_comp_record_an_empty_comp(tmp_path):
    p = tmp_path / "b.jsonl"
    assert _log(p, enemy_comp={"Malphite": 1}) is not None
    assert _log(p, enemy_comp=5, game_time_s=700.0) is not None
    assert [r["enemy_comp"] for r in _rows(p)] == [[], []]


def test_non_string_enemy_entries_are_dropped_and_capped(tmp_path):
    p = tmp_path / "b.jsonl"
    comp = ["Malphite", {"x": 1}, 7, None, "", "   ", "Ornn"] + ["Sion"] * 40
    assert _log(p, enemy_comp=comp) is not None
    got = _rows(p)[0]["enemy_comp"]
    assert got[:2] == ["Malphite", "Ornn"]
    assert all(isinstance(e, str) and e.strip() for e in got)
    assert len(got) == hbs._MAX_ENEMIES


# RM-1591: choices / native_choices are lists of dicts; the row is strict JSON.
@pytest.mark.parametrize("bad", ["AB", {"key": "A"}, 3, (x for x in [{"key": "A"}])])
def test_non_list_choices_record_empty(tmp_path, bad):
    p = tmp_path / "b.jsonl"
    assert _log(p, choices=bad, native_choices=bad) is not None
    r = _rows(p)[0]
    assert r["choices"] == [] and r["native_choices"] == []


def test_non_dict_choice_entries_dropped(tmp_path):
    p = tmp_path / "b.jsonl"
    assert _log(p, choices=[{"key": "A"}, "B", 3, None]) is not None
    assert _rows(p)[0]["choices"] == [{"key": "A"}]


def test_nan_inside_a_choice_is_refused_not_written(tmp_path):
    p = tmp_path / "b.jsonl"
    assert _log(p, choices=[{"key": "A", "score": float("nan")}]) is None
    assert not p.exists() or b"NaN" not in p.read_bytes()


def test_refused_row_does_not_advance_dedup(tmp_path):
    p = tmp_path / "b.jsonl"
    assert _log(p, choices=[{"key": "A", "score": float("inf")}]) is None
    assert _log(p, choices=[{"key": "A", "score": 1.0}]) is not None


# RM-1592: text fields are capped strings or null; blank champion refused;
# covered is a real bool; item_count is a non-negative int or null.
@pytest.mark.parametrize("champ", ["", "   ", "\t\n", None, 5, ["Ahri"]])
def test_blank_or_non_string_champion_refused(tmp_path, champ):
    p = tmp_path / "b.jsonl"
    assert _log(p, my_champion=champ) is None
    assert not p.exists()


def test_non_string_text_fields_are_null_and_prose_capped(tmp_path):
    p = tmp_path / "b.jsonl"
    rec = _log(p, mode=["sr"], lean={"x": 1}, native_action="x" * 50000, now_iso=12)
    assert rec is not None
    r = _rows(p)[0]
    assert r["mode"] is None and r["lean"] is None and r["ts"] is None
    assert len(r["native_action"]) == hbs._MAX_TEXT
    p2 = tmp_path / "c.jsonl"
    assert _log(p2, native_action=7) is not None
    assert _rows(p2)[0]["native_action"] is None


@pytest.mark.parametrize("cov,want", [("False", False), (1, False), ([1], False),
                                      (True, True), (False, False)])
def test_covered_is_only_true_for_true(tmp_path, cov, want):
    p = tmp_path / "b.jsonl"
    assert _log(p, covered=cov) is not None
    assert _rows(p)[0]["covered"] is want


@pytest.mark.parametrize("ic,want", [(3, 3), (0, 0), (-1, None), (True, None),
                                     ("3", None), (2.5, None), (float("nan"), None)])
def test_item_count_is_a_non_negative_int_or_null(tmp_path, ic, want):
    p = tmp_path / "b.jsonl"
    assert _log(p, item_count=ic) is not None
    assert _rows(p)[0]["item_count"] == want


# RM-1593: concurrent state builders cannot both write one tick.
def test_concurrent_writers_write_one_row_per_tick(tmp_path, monkeypatch):
    p = tmp_path / "b.jsonl"
    real = json.dumps

    class _SlowJson:
        loads = staticmethod(json.loads)

        @staticmethod
        def dumps(*a, **k):
            time.sleep(0.05)
            return real(*a, **k)

    monkeypatch.setattr(hbs, "json", _SlowJson)
    gate = threading.Barrier(8)
    out = []

    def run():
        gate.wait()
        out.append(_log(p))

    threads = [threading.Thread(target=run) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sum(1 for r in out if r is not None) == 1
    assert len(_rows(p)) == 1


# RM-1594: one LF-terminated strict-JSON row; a torn tail is terminated.
def test_rows_are_lf_only(tmp_path):
    p = tmp_path / "b.jsonl"
    _log(p)
    _log(p, game_time_s=700.0)
    raw = p.read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") == 2 and raw.endswith(b"\n")


def test_torn_tail_is_terminated_before_the_next_row(tmp_path):
    p = tmp_path / "b.jsonl"
    p.write_bytes(b'{"ts": "x", "my_champ')
    assert _log(p) is not None
    lines = p.read_bytes().split(b"\n")
    assert lines[0] == b'{"ts": "x", "my_champ'
    assert json.loads(lines[1])["my_champion"] == "Ahri"


def test_nul_filled_tail_is_terminated(tmp_path):
    p = tmp_path / "b.jsonl"
    p.write_bytes(b'{"a": 1}\n' + b"\x00" * 64)
    assert _log(p) is not None
    assert json.loads(p.read_bytes().split(b"\n")[-2])["my_champion"] == "Ahri"


# RM-1595: a persistent write failure WARNs once a minute, never silently.
def test_write_failure_warns_once_and_does_not_advance_dedup(tmp_path, caplog):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    bad = tmp_path / "f.txt" / "b.jsonl"
    with caplog.at_level(logging.DEBUG, logger="rc.hz_build_shadow"):
        assert _log(bad) is None
        assert _log(bad) is None
    warns = [r for r in caplog.records
             if r.name == "rc.hz_build_shadow" and r.levelno == logging.WARNING]
    assert len(warns) == 1
    assert hbs._LAST_SIG.get(str(bad)) is None


def test_warn_repeats_after_the_interval(tmp_path, caplog, monkeypatch):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    bad = tmp_path / "f.txt" / "b.jsonl"
    clock = [1000.0]
    monkeypatch.setattr(hbs, "_now", lambda: clock[0])
    with caplog.at_level(logging.WARNING, logger="rc.hz_build_shadow"):
        _log(bad)
        clock[0] += hbs._WARN_INTERVAL_S + 1
        _log(bad)
    assert len([r for r in caplog.records if r.name == "rc.hz_build_shadow"]) == 2


# RM-1596: a str path is a path, not a silent AttributeError.
def test_str_path_is_accepted(tmp_path):
    p = tmp_path / "b.jsonl"
    assert _log(str(p)) is not None
    assert len(_rows(p)) == 1


def test_returned_record_matches_written_row(tmp_path):
    p = tmp_path / "b.jsonl"
    rec = _log(p, native_choices=[{"key": "A", "label": "Void Staff"}])
    assert rec == _rows(p)[0]
