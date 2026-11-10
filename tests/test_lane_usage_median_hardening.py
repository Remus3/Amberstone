"""S144-T-735: tools/lane_usage_median.py hardening (lane 8 true-audit).

The FLEET-3b acceptance reader. Each test pins one audited weakness:
  F1 the default --usage path was this checkout's, but the kit writes
     headless_usage.jsonl in the MAIN checkout, so from a linked worktree the
     reader crashed with a FileNotFoundError traceback;
  F2 a missing / unreadable usage file was a raw traceback, not exit 2;
  F3 --since / --until were never parsed, so a typo ("2026-1-05", "11/01")
     silently compared as a string and moved the window;
  F4 a row whose ts is not an ISO date ("garbage", an epoch) was compared as a
     string, and "garbage" > "2026-..." put it INSIDE an open-ended window;
  F5 a bool, NaN, inf or negative cache_creation was counted, and NaN / inf
     made the printed report non-JSON;
  F6 a missing num_turns was counted as 0 turns (dragging the median down) and
     a non-numeric one raised TypeError out of statistics.median;
  F7 one deeply nested JSONL line raised RecursionError out of json.loads;
  F8 a leading UTF-8 BOM made the first row non-JSON and silently dropped it.
Verifier round 1 added the MAX_FIGURE ceiling (a finite 1.7e308 pair summed
to inf and broke the strict-JSON print).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lane_usage_median as lum  # noqa: E402

DAY = "2026-11-01"


def _write(path: Path, rows: list) -> Path:
    lines = [r if isinstance(r, str) else json.dumps(r) for r in rows]
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return path


def _row(cc, turns=1, ts=DAY + "T01:00:00-06:00", note="lane-s144-ds"):
    return {"ts": ts, "note": note, "cache_creation": cc, "num_turns": turns}


def _strict_json(text: str):
    def _refuse(token):
        raise ValueError("non-JSON constant " + token)
    return json.loads(text, parse_constant=_refuse)


# F1 ------------------------------------------------------------------------

def test_default_usage_path_is_the_main_checkouts(tmp_path):
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "lane").mkdir(parents=True)
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: " + str(main / ".git" / "worktrees" / "lane") + "\n",
                             encoding="utf-8")
    assert lum.usage_path(wt) == main / lum.USAGE_REL
    assert lum.usage_path(main) == main / lum.USAGE_REL


def test_module_default_is_resolved_through_main_checkout():
    from core.claude_project import main_checkout
    assert lum.USAGE == main_checkout(ROOT) / lum.USAGE_REL


# F2 ------------------------------------------------------------------------

def test_missing_usage_file_exits_2_with_one_line(tmp_path, capsys):
    rc = lum.main(["--since", DAY, "--usage", str(tmp_path / "absent.jsonl")])
    err = capsys.readouterr().err
    assert rc == 2
    assert err.count("\n") == 1 and "Traceback" not in err
    assert "absent.jsonl" in err


def test_usage_path_that_is_a_directory_exits_2(tmp_path, capsys):
    rc = lum.main(["--since", DAY, "--usage", str(tmp_path)])
    assert rc == 2
    assert "Traceback" not in capsys.readouterr().err


# F3 ------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["2026-1-05", "11/01/2026", "garbage", "", "2026-02-30",
                                 "2026-11-01T00:00",
                                 # date.fromisoformat accepts these two (3.11+);
                                 # only the strict YYYY-MM-DD shape refuses them.
                                 "20261101", "2026-W44-7"])
def test_since_must_be_an_iso_day(bad, capsys):
    with pytest.raises(SystemExit) as exc:
        lum.main(["--since", bad])
    assert exc.value.code == 2


def test_until_must_be_an_iso_day():
    with pytest.raises(SystemExit) as exc:
        lum.main(["--since", DAY, "--until", "11-02"])
    assert exc.value.code == 2


def test_until_before_since_is_refused(tmp_path, capsys):
    usage = _write(tmp_path / "u.jsonl", [_row(10)])
    rc = lum.main(["--since", "2026-11-02", "--until", DAY, "--usage", str(usage)])
    assert rc == 2
    assert "until" in capsys.readouterr().err


def test_load_rows_refuses_a_non_iso_bound(tmp_path):
    usage = _write(tmp_path / "u.jsonl", [_row(10)])
    with pytest.raises(ValueError):
        lum.load_rows(usage, "2026-1-05", None)


# F4 ------------------------------------------------------------------------

@pytest.mark.parametrize("ts", ["garbage", "9999-99-99T00:00:00", 1730000000, None, "",
                                "Z026-11-01T00:00:00", "2026-13-45T00:00:00"])
def test_row_without_an_iso_day_is_skipped_in_an_open_window(tmp_path, ts):
    usage = _write(tmp_path / "u.jsonl", [_row(10), _row(777, ts=ts)])
    rows = lum.load_rows(usage, DAY, None)
    assert [r["cache_creation"] for r in rows] == [10]


def test_window_bounds_are_inclusive_days(tmp_path):
    usage = _write(tmp_path / "u.jsonl", [
        _row(1, ts="2026-10-31T23:59:59-06:00"),
        _row(2, ts="2026-11-01T00:00:00-06:00"),
        _row(3, ts="2026-11-02T23:59:59-06:00"),
        _row(4, ts="2026-11-03T00:00:00-06:00"),
    ])
    rows = lum.load_rows(usage, DAY, "2026-11-02")
    assert [r["cache_creation"] for r in rows] == [2, 3]


# F5 ------------------------------------------------------------------------

@pytest.mark.parametrize("cc", [True, False, float("nan"), float("inf"), -5, "100", None])
def test_junk_cache_creation_is_not_counted(tmp_path, cc):
    usage = tmp_path / "u.jsonl"
    # json.dumps writes NaN / Infinity literals, which json.loads accepts.
    _write(usage, [_row(10), _row(30), _row(cc)])
    rows = lum.load_rows(usage, DAY, None)
    assert [r["cache_creation"] for r in rows] == [10, 30]


def test_printed_report_is_strict_json(tmp_path, capsys):
    usage = _write(tmp_path / "u.jsonl", [_row(10), _row(float("nan")), _row(float("inf"))])
    assert lum.main(["--since", DAY, "--usage", str(usage)]) == 0
    out = _strict_json(capsys.readouterr().out)
    assert out["all_runs"]["n"] == 1
    assert out["all_runs"]["total_cache_creation"] == 10


@pytest.mark.parametrize("huge", [1.7e308, 10 ** 400, lum.MAX_FIGURE + 1])
def test_finite_but_huge_figures_do_not_end_in_a_traceback(tmp_path, capsys, huge):
    # Two finite 1.7e308 rows sum to inf; a 10**400 int overflows the median.
    usage = _write(tmp_path / "u.jsonl", [_row(10, turns=huge), _row(huge, turns=huge),
                                          _row(huge), _row(30, turns=huge)])
    assert lum.main(["--since", DAY, "--usage", str(usage)]) == 0
    out = _strict_json(capsys.readouterr().out)
    assert out["all_runs"]["n"] == 2
    assert out["all_runs"]["total_cache_creation"] == 40
    assert out["all_runs"]["median_turns"] is None


def test_max_figure_itself_is_counted(tmp_path):
    usage = _write(tmp_path / "u.jsonl", [_row(lum.MAX_FIGURE)])
    assert lum.summarize(lum.load_rows(usage, DAY, None))["n"] == 1


# F6 ------------------------------------------------------------------------

def test_missing_num_turns_is_not_a_zero_turn_run(tmp_path):
    usage = _write(tmp_path / "u.jsonl", [_row(10, turns=9), _row(20, turns=None),
                                          _row(30, turns=7)])
    s = lum.summarize(lum.load_rows(usage, DAY, None))
    assert s["n"] == 3
    assert s["median_turns"] == 8


@pytest.mark.parametrize("junk", ["7", True, float("nan"), -1, [3]])
def test_junk_num_turns_neither_raises_nor_counts(tmp_path, junk):
    usage = _write(tmp_path / "u.jsonl", [_row(10, turns=4), _row(20, turns=junk),
                                          _row(30, turns=6)])
    s = lum.summarize(lum.load_rows(usage, DAY, None))
    assert s["median_turns"] == 5
    assert not (isinstance(s["median_turns"], float) and math.isnan(s["median_turns"]))


def test_no_valid_turns_gives_none(tmp_path):
    usage = _write(tmp_path / "u.jsonl", [_row(10, turns=None)])
    s = lum.summarize(lum.load_rows(usage, DAY, None))
    assert s["n"] == 1 and s["median_turns"] is None


# F7 / F8 (verifier round 2) ------------------------------------------------

@pytest.mark.parametrize("deep", ["[" * 200000 + "]" * 200000, '{"a":' * 100000])
def test_deeply_nested_line_is_skipped_not_a_traceback(tmp_path, capsys, deep):
    usage = _write(tmp_path / "u.jsonl", [_row(10), deep, _row(30)])
    assert lum.main(["--since", DAY, "--usage", str(usage)]) == 0
    out = _strict_json(capsys.readouterr().out)
    assert out["all_runs"]["n"] == 2


def test_leading_bom_does_not_drop_the_first_row(tmp_path):
    usage = tmp_path / "u.jsonl"
    body = (json.dumps(_row(10)) + "\n" + json.dumps(_row(30)) + "\n").encode("utf-8")
    usage.write_bytes(b"\xef\xbb\xbf" + body)
    rows = lum.load_rows(usage, DAY, None)
    assert [r["cache_creation"] for r in rows] == [10, 30]


# characterization: the existing split survives -----------------------------

def test_lane_split_and_empty_window(tmp_path):
    usage = _write(tmp_path / "u.jsonl", [
        _row(100, note="lane-s144-ds"), _row(300, note="lane-s144-repo"),
        _row(500, note="other"), "not json", "[1, 2]",
    ])
    out = lum.report(lum.load_rows(usage, DAY, DAY))
    assert out["all_runs"]["n"] == 3
    assert out["lane_runs"]["total_cache_creation"] == 400
    assert sorted(out["per_lane"]) == ["lane-s144-ds", "lane-s144-repo"]
    empty = lum.report(lum.load_rows(usage, "2027-01-01", None))
    assert empty["all_runs"] == {"n": 0, "median_cache_creation": None,
                                 "total_cache_creation": 0, "median_turns": None}
