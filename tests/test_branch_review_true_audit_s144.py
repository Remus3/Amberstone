"""s144 true-audit cycle 121: core/branch_review.py hardening.

The reader serves /api/branch-review and /api/branch-review/runs, whose
handler sends STRICT JSON (allow_nan=False) and turns any raise into a generic
error envelope. So one junk row in the 68 MB shadow corpus used to take down
the whole post-game review: an unhashable game_run_id raised in the picker, a
NaN / Infinity / 1e400 token made the strict send fail, and a non-iterable
``choices`` raised in the builder. Each finding below carries its provisional
S144-T id.
"""
from __future__ import annotations

import json
import logging

import pytest

from core import branch_review

RUN_A = "local-aram-2026-08-12T20:00:00+00:00"
RUN_B = "7000000001"


def _row(**kw):
    base = {
        "mode": "aram", "my_champion": "Annie", "enemy": "Caitlyn",
        "band": "L6", "covered": True, "game_time_s": 300.0, "level": 6,
        "item_count": 2,
        "choices": [{"key": "A", "label": "Force a short trade",
                     "confidence": "high"}],
        "native_action": "POKE PHASE", "cv_override": None,
        "game_id": None, "game_run_id": RUN_A,
    }
    base.update(kw)
    return base


def _write_lines(path, lines):
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))


def _write(path, rows):
    _write_lines(path, [json.dumps(r) for r in rows])


def _strict(obj):
    # The route's own encoder contract (dashboard/routes_coach.py _send_json).
    return json.dumps(obj, allow_nan=False)


# RM-1573 ----------------------------------------------------------------

def test_unhashable_run_id_does_not_break_the_picker(tmp_path):
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(game_run_id=["x"]), _row(game_run_id={"a": 1}),
               _row(game_run_id=RUN_B)])
    runs = branch_review.list_recent_runs(path=p)
    assert [r["game_run_id"] for r in runs] == [RUN_B]


def test_non_string_run_ids_are_not_grouped(tmp_path):
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(game_run_id=12345), _row(game_run_id=True),
               _row(game_run_id=["x"]), _row(game_run_id="   ")])
    out = branch_review.load_branch_series(path=p)
    assert out["branches"] == []
    assert out["legacy_rows_skipped"] == 4
    assert branch_review.list_recent_runs(path=p) == []


# RM-1574 ----------------------------------------------------------------

def test_non_finite_tokens_never_reach_the_strict_payload(tmp_path):
    p = tmp_path / "hz.jsonl"
    good = json.dumps(_row(game_time_s=100.0))
    nan_row = (json.dumps(_row(game_time_s=200.0))
               .replace('"game_time_s": 200.0', '"game_time_s": NaN')
               .replace('"level": 6', '"level": Infinity')
               .replace('"item_count": 2', '"item_count": 1e400')
               .replace('"confidence": "high"', '"confidence": -Infinity'))
    assert "NaN" in nan_row and "1e400" in nan_row
    _write_lines(p, [good, nan_row])
    out = branch_review.load_branch_series(RUN_A, path=p)
    _strict(out)  # raises ValueError on any surviving non-finite float
    assert out["branch_count"] == 2, "a bad number must not drop the row"
    bad = [b for b in out["branches"] if b["level"] is None]
    assert len(bad) == 1
    assert bad[0]["game_time_s"] is None
    assert bad[0]["item_count"] is None
    _strict(branch_review.list_recent_runs(path=p))


def test_an_overflowing_int_clock_is_unknown_not_fatal(tmp_path):
    # An int token parses to a Python int (parse_float never sees it), and
    # float() on a 401-digit int raises OverflowError.
    p = tmp_path / "hz.jsonl"
    huge = "1" + "0" * 400
    line = (json.dumps(_row(game_time_s=200.0))
            .replace('"game_time_s": 200.0', '"game_time_s": ' + huge))
    _write_lines(p, [line, json.dumps(_row(game_time_s=50.0))])
    out = branch_review.load_branch_series(RUN_A, path=p)
    _strict(out)
    assert [b["game_time_s"] for b in out["branches"]] == [None, 50.0]


def test_bool_game_time_is_not_a_clock(tmp_path):
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(game_time_s=True), _row(game_time_s=50.0)])
    out = branch_review.load_branch_series(RUN_A, path=p)
    assert [b["game_time_s"] for b in out["branches"]] == [None, 50.0]


# RM-1575 ----------------------------------------------------------------

@pytest.mark.parametrize("junk", [5, 2.5, True, "AB", {"key": "A"}])
def test_junk_choices_never_raise_or_explode(tmp_path, junk):
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(choices=junk), _row(game_time_s=400.0)])
    out = branch_review.load_branch_series(RUN_A, path=p)
    assert out["ticks_total"] == 2
    assert out["branch_count"] == 1
    assert out["branches"][0]["game_time_s"] == 400.0


def test_non_dict_choice_elements_are_dropped(tmp_path):
    # The panel's _choiceHtml reads c.key: a null element throws in the browser.
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(choices=[None, "x", 3, {"key": "B", "label": "Back off"}])])
    out = branch_review.load_branch_series(RUN_A, path=p)
    assert out["branches"][0]["choices"] == [{"key": "B", "label": "Back off"}]


# RM-1576 ----------------------------------------------------------------

def test_tail_landing_on_a_line_start_keeps_that_record(tmp_path):
    p = tmp_path / "hz.jsonl"
    first = json.dumps(_row(game_time_s=1.0))
    second = json.dumps(_row(game_time_s=2.0))
    third = json.dumps(_row(game_time_s=3.0))
    _write_lines(p, [first, second, third])
    tail = len(second) + 1 + len(third) + 1  # exactly the last two records
    out = branch_review.load_branch_series(RUN_A, path=p, tail_bytes=tail)
    assert out["truncated"] is True
    assert [b["game_time_s"] for b in out["branches"]] == [2.0, 3.0]


def test_tail_landing_mid_record_still_drops_the_fragment(tmp_path):
    p = tmp_path / "hz.jsonl"
    first = json.dumps(_row(game_time_s=1.0))
    second = json.dumps(_row(game_time_s=2.0))
    _write_lines(p, [first, second])
    tail = len(second) + 1 + 5  # five bytes into the end of the first record
    out = branch_review.load_branch_series(RUN_A, path=p, tail_bytes=tail)
    assert [b["game_time_s"] for b in out["branches"]] == [2.0]


# RM-1577 ----------------------------------------------------------------

def test_runs_are_ordered_by_last_appearance(tmp_path):
    # A restart can interleave: A starts, B runs, A resumes. A is newest.
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(game_run_id=RUN_A), _row(game_run_id=RUN_B),
               _row(game_run_id=RUN_A)])
    runs = branch_review.list_recent_runs(path=p)
    assert [r["game_run_id"] for r in runs] == [RUN_A, RUN_B]
    assert [r["ticks"] for r in runs] == [2, 1]
    # The default selection agrees with the picker's first entry.
    assert branch_review.load_branch_series(path=p)["game_run_id"] == RUN_A


@pytest.mark.parametrize("junk", [None, "3", 2.5, True, 0, -4])
def test_junk_limit_never_raises(tmp_path, junk):
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(game_run_id=RUN_A), _row(game_run_id=RUN_B)])
    runs = branch_review.list_recent_runs(path=p, limit=junk)
    assert 1 <= len(runs) <= 2


# RM-1578 ----------------------------------------------------------------

def test_header_and_branch_fields_are_scalars(tmp_path):
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(my_champion={"n": "Annie"}, enemy=["Caitlyn"],
                    mode=7, band=[1], level={"x": 1}, item_count="2",
                    native_action={"a": 1}, cv_override=["junk"],
                    covered="false", game_id=["g"])])
    out = branch_review.load_branch_series(RUN_A, path=p)
    assert out["my_champion"] is None
    assert out["enemy"] is None
    assert out["game_id"] is None
    assert out["mode"] == 7
    b = out["branches"][0]
    assert b["band"] is None
    assert b["level"] is None
    assert b["item_count"] == "2"
    assert b["native_action"] is None
    assert b["cv_override"] is None
    assert b["covered"] is False
    run = branch_review.list_recent_runs(path=p)[0]
    assert run["my_champion"] is None and run["enemy"] is None


def test_cv_override_dict_is_kept(tmp_path):
    p = tmp_path / "hz.jsonl"
    cv = {"verdict": "hold", "confidence": "mid"}
    _write(p, [_row(cv_override=cv)])
    out = branch_review.load_branch_series(RUN_A, path=p)
    assert out["branches"][0]["cv_override"] == cv
    assert out["branches"][0]["covered"] is True


# RM-1579 ----------------------------------------------------------------

def test_unreadable_corpus_says_read_failed_and_warns(tmp_path, monkeypatch,
                                                      caplog):
    p = tmp_path / "hz.jsonl"
    _write(p, [_row()])

    def _boom(*_a, **_k):
        raise PermissionError("locked")

    monkeypatch.setattr(branch_review, "_tail_lines", _boom)
    with caplog.at_level(logging.WARNING, logger="rc.branch_review"):
        out = branch_review.load_branch_series(path=p)
    assert out["reason"] == "read-failed"
    assert out["branches"] == []
    assert any("tail read failed" in r.getMessage() for r in caplog.records)
    assert branch_review.list_recent_runs(path=p) == []


def test_an_unexpected_error_is_not_swallowed(tmp_path, monkeypatch):
    p = tmp_path / "hz.jsonl"
    _write(p, [_row()])

    def _boom(*_a, **_k):
        raise RuntimeError("bug")

    monkeypatch.setattr(branch_review, "_tail_lines", _boom)
    with pytest.raises(RuntimeError):
        branch_review.load_branch_series(path=p)
    with pytest.raises(RuntimeError):
        branch_review.list_recent_runs(path=p)


# RM-1580 ----------------------------------------------------------------

@pytest.mark.parametrize("junk", [0, -5, True, "4000", 2.5, None])
def test_junk_tail_bytes_falls_back_to_the_default(tmp_path, junk):
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(game_time_s=1.0), _row(game_time_s=2.0)])
    out = branch_review.load_branch_series(RUN_A, path=p, tail_bytes=junk)
    assert out["truncated"] is False
    assert out["branch_count"] == 2
    runs = branch_review.list_recent_runs(path=p, tail_bytes=junk)
    assert runs[0]["ticks"] == 2


def test_run_id_argument_is_normalised(tmp_path):
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(game_run_id=RUN_B), _row(game_run_id=RUN_A)])
    # An int game id selects the run the writer stamped as str(game_id).
    assert (branch_review.load_branch_series(int(RUN_B), path=p)
            ["game_run_id"] == RUN_B)
    # Junk or blank falls back to the most recent run.
    for junk in (["x"], {"a": 1}, True, "   ", ""):
        out = branch_review.load_branch_series(junk, path=p)
        assert out["game_run_id"] == RUN_A, junk
    assert (branch_review.load_branch_series(f"  {RUN_B} ", path=p)
            ["game_run_id"] == RUN_B)


# RM-1581 ----------------------------------------------------------------

def test_a_pathologically_nested_line_is_skipped(tmp_path):
    p = tmp_path / "hz.jsonl"
    deep = "[" * 200000 + "]" * 200000
    _write_lines(p, [json.dumps(_row(game_time_s=1.0)), deep,
                     json.dumps(_row(game_time_s=2.0))])
    out = branch_review.load_branch_series(RUN_A, path=p)
    assert out["branch_count"] == 2
    assert len(branch_review.list_recent_runs(path=p)) == 1
