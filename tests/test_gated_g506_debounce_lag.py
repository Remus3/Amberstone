"""Tests for tools/gated_g506_debounce_lag.py (G5-06 Arena state-debounce lag read-back).

Every log line, sample and trace row here is hand-written and synthetic (RM-906):
no real Riot id, game id or match key.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from tools import gated_g506_debounce_lag as g

DAY = date(2026, 10, 27)
SINCE, UNTIL = datetime(2026, 10, 27, 20, 0), datetime(2026, 10, 27, 20, 10)
PROOF = ("20:01:05.120 DEBUG    rc.arena             [arena_coach.py:816] Arena state-debounce: "
         "signature unchanged (age 22.0s < 45s ceiling) - reusing cached coaching")
ROOT = Path(__file__).resolve().parent.parent


def sample(wall, lc_gt, co_gt, hp=900, mode="arena", hp_max=1000, get_s=0.2):
    if isinstance(wall, str):
        wall = datetime.fromisoformat(wall)
    return g.make_sample({"mode_key": mode, "liveclient": {"game_time_s": lc_gt, "hp": hp, "hp_max": hp_max}},
                         {"game_time_s": co_gt}, wall, get_s)


def ended(wall):
    return g.make_sample({"mode_key": "client", "liveclient": {}}, {"game_time_s": 600}, wall)


def run(lag=40, spikes=None, dead=(), failed=(), n=25, step=25, end=True):
    """n polls every `step` s from SINCE (25 x 25 s tiles 20:00:00 .. 20:10:00), game clock 30 s at
    the first, then one game-over poll 20 s after the last when `end`.

    spikes: {index: lag} overrides; dead / failed: indexes polled while dead / with a failed GET.
    """
    rows = []
    for i in range(n):
        wall, gt = SINCE + timedelta(seconds=i * step), 30 + i * step
        if i in failed:
            rows.append(g.make_sample({"error": "URLError"}, None, wall))
        else:
            rows.append(sample(wall, gt, gt - (spikes or {}).get(i, lag), hp=0 if i in dead else 900))
    if end:
        rows.append(ended(SINCE + timedelta(seconds=(n - 1) * step + 20)))
    return rows


def log(*lines):
    return g.parse_log(lines, DAY)


def grade(rows, lines=(PROOF,), slow=(), budget_ok=False, since=SINCE, until=UNTIL):
    return g.grade(rows, log(*lines), list(slow), since, until, budget_ok)


def test_make_sample_computes_lag_and_tolerates_missing_docs():
    s = sample("2026-10-27T20:02:00", 300, 260)
    assert s["lag_s"] == 40.0 and s["mode_key"] == "arena" and g.usable(s)
    empty = g.make_sample(None, None, datetime(2026, 10, 27, 20, 0, 0))
    assert empty["lag_s"] is None and not g.usable(empty)


def test_pass_needs_proof_full_coverage_and_every_lag_within_bound():
    rep = grade(run(lag=149))
    assert rep["verdict"] == "PASS" and rep["max_lag_s"] == 149.0 and rep["proof_lines"] == 1
    cov = rep["coverage"]
    assert cov["known"] == 25 and cov["start_ok"] and cov["end_seen"]
    assert cov["holes"] == cov["dead_runs"] == cov["ahead"] == []


def test_zero_proof_lines_is_never_a_pass():
    assert grade(run(), lines=("20:01:00.000 INFO x y",))["verdict"] == "INCONCLUSIVE"


def test_proof_line_outside_the_window_does_not_count():
    early = "19:30:00.000 DEBUG    rc.arena [arena_coach.py:816] " + g.PROOF_MARK + " (age 1s)"
    rep = grade(run(), lines=(early,))
    assert rep["proof_lines"] == 0 and rep["verdict"] == "INCONCLUSIVE"


def test_dead_or_non_arena_samples_are_not_usable():
    rows = [sample("2026-10-27T20:02:00", 600, 100, hp=0),
            sample("2026-10-27T20:02:30", 600, 100, mode="aram")]
    assert grade(rows, budget_ok=True)["verdict"] == "NO_RESULT"


def test_sampling_that_stops_early_is_not_a_pass():
    rep = grade(run(n=14))  # stops at 20:05:25 of a game that ends 20:10:00
    assert rep["verdict"] == "INCONCLUSIVE" and rep["coverage"]["holes"][-1].endswith("20:10:00")


def test_window_cut_short_at_either_end_is_not_a_pass():
    # an over-bound lag at 20:01:40 sits outside a window that starts late ...
    rows = run(spikes={4: 200})
    assert grade(rows, budget_ok=True)["verdict"] == "FAIL"
    late = grade(rows, budget_ok=True, since=datetime(2026, 10, 27, 20, 2))
    assert late["verdict"] == "INCONCLUSIVE" and not late["coverage"]["start_ok"]
    # ... or before a window that ends early: the next poll is still in game
    early = grade(run(spikes={22: 200}), budget_ok=True, until=datetime(2026, 10, 27, 20, 9))
    assert early["verdict"] == "INCONCLUSIVE" and not early["coverage"]["end_seen"]
    point = datetime(2026, 10, 27, 20, 5)
    assert grade(run(), since=point, until=point)["verdict"] == "INCONCLUSIVE"


def test_no_game_over_poll_is_not_a_pass():
    assert grade(run(end=False))["verdict"] == "INCONCLUSIVE"
    rows = run(end=False) + [g.make_sample({"error": "URLError"}, None, UNTIL + timedelta(seconds=20))]
    assert grade(rows)["verdict"] == "INCONCLUSIVE"  # a failed poll is not a game over


def test_coach_file_ahead_of_live_clock_is_not_a_pass():
    # A file left over from an earlier, longer game reads as a NEGATIVE lag.
    rep = grade(run(lag=-1000), budget_ok=True)
    assert rep["verdict"] == "INCONCLUSIVE" and len(rep["coverage"]["ahead"]) == 25
    assert grade(run(lag=-10))["verdict"] == "PASS"  # read skew within tolerance


def test_failed_polls_are_holes_and_dead_polls_are_not():
    assert grade(run(failed={8, 9, 10}))["verdict"] == "INCONCLUSIVE"
    assert grade(run(dead={8, 9, 10}))["verdict"] == "PASS"
    # one dead poll inside a run of failed polls must not excuse the whole gap
    rep = grade(run(failed={6, 7, 8, 10, 11, 12}, dead={9}))
    assert rep["verdict"] == "INCONCLUSIVE" and len(rep["coverage"]["holes"]) == 2


def test_long_dead_run_is_not_a_pass():
    # hp reads 0 when currentHealth is missing, so a long "dead" stretch cannot hide a stale coach
    rep = grade(run(dead=set(range(1, 25)), spikes={i: 30 + i * 25 for i in range(1, 25)}))
    assert rep["verdict"] == "INCONCLUSIVE" and rep["coverage"]["dead_runs"]


def test_hp_zero_without_hp_max_or_game_time_is_unknown():
    rows = run()
    for i in (8, 9, 10):
        rows[i] = sample(SINCE + timedelta(seconds=i * 25), 30 + i * 25, None, hp=0, hp_max=0)
    assert grade(rows)["verdict"] == "INCONCLUSIVE"
    for i in (8, 9, 10):
        rows[i] = g.make_sample({"mode_key": "arena", "liveclient": {"hp": 0, "hp_max": 1000}}, None,
                                SINCE + timedelta(seconds=i * 25))
    assert grade(rows)["verdict"] == "INCONCLUSIVE"


def test_unexcused_lag_is_fail_only_with_budget_assertion():
    rows = run(spikes={20: 200})  # 20:08:20
    assert grade(rows)["verdict"] == "INCONCLUSIVE"
    rep = grade(rows, budget_ok=True)
    assert rep["verdict"] == "FAIL" and rep["over_bound"][0]["lag_s"] == 200.0


def test_missing_trace_file_keeps_an_unexcused_lag_inconclusive():
    rows = run(spikes={20: 200})
    rep = g.grade(rows, log(PROOF), [], SINCE, UNTIL, budget_ok=True, trace_ok=False)
    assert rep["verdict"] == "INCONCLUSIVE" and "--trace" in rep["over_bound"][0]["note"]


def test_excuse_inside_lag_window_makes_it_inconclusive():
    rows = run(spikes={20: 200})  # excuse window 20:05:00 .. 20:08:20
    err = "20:07:00.000 ERROR    rc.arena             [safe_coach_output.py:35] Arena coach error: boom"
    rep = grade(rows, lines=(PROOF, err), budget_ok=True)
    assert rep["verdict"] == "INCONCLUSIVE" and rep["over_bound"][0]["excuses"]
    slow = [(datetime(2026, 10, 27, 20, 5, 30), datetime(2026, 10, 27, 20, 6, 0))]
    assert grade(rows, slow=slow, budget_ok=True)["verdict"] == "INCONCLUSIVE"


def test_slow_call_still_running_at_the_sample_excuses_it():
    rows = run(spikes={20: 200})
    t_end = datetime(2026, 10, 27, 20, 8, 30)  # ends 10 s AFTER the 20:08:20 sample, ran 65 s
    trace = [{"ts": t_end.timestamp(), "mode": "arena", "phase": "coach", "dur_ms": 65000}]
    assert grade(rows, slow=g.slow_calls(trace), budget_ok=True)["verdict"] == "INCONCLUSIVE"


def test_excuse_outside_lag_window_excuses_nothing():
    rows = run(spikes={20: 200})
    err = "20:04:00.000 WARNING  rc.arena             [arena_coach.py:842] Arena: no fields parsed"
    slow = [(datetime(2026, 10, 27, 20, 3, 0), datetime(2026, 10, 27, 20, 4, 0))]
    assert grade(rows, lines=(PROOF, err), slow=slow, budget_ok=True)["verdict"] == "FAIL"


def test_samples_outside_the_window_are_dropped():
    rep = grade([sample("2026-10-27T21:00:00", 900, 100)], budget_ok=True)
    assert rep["verdict"] == "NO_RESULT" and rep["usable"] == 0


def test_non_finite_values_are_not_usable_and_do_not_crash():
    rows = run()
    rows[5] = dict(rows[5], lag_s=float("nan"))
    rows[6] = dict(rows[6], lag_s=float("inf"))
    rep = grade(rows)
    assert rep["usable"] == 23 and rep["verdict"] == "INCONCLUSIVE"


def test_slow_calls_filters_mode_phase_and_duration():
    t = datetime(2026, 10, 27, 20, 0).timestamp()
    rows = [{"ts": t, "mode": "arena", "phase": "coach", "dur_ms": 25000},
            {"ts": t, "mode": "arena", "phase": "coach", "dur_ms": 19000},
            {"ts": t, "mode": "aram", "phase": "coach", "dur_ms": 25000},
            {"ts": t, "mode": "arena", "phase": "vision", "dur_ms": 25000}]
    end = datetime.fromtimestamp(t)
    assert g.slow_calls(rows) == [(end - timedelta(seconds=25), end)]


def test_parse_log_drops_continuation_lines_and_reads_date():
    parsed = g.parse_log([PROOF, "Traceback (most recent call last):"], DAY)
    assert len(parsed) == 1 and parsed[0][0] == datetime(2026, 10, 27, 20, 1, 5, 120000)
    assert g.log_date(Path("logs/2026-10-27.log")) == DAY


def test_main_grade_exit_codes_and_required_window(tmp_path, capsys):
    lp = tmp_path / "2026-10-27.log"
    lp.write_text(PROOF + "\n", encoding="utf-8")
    sp = tmp_path / "s.jsonl"
    tp = tmp_path / "trace.jsonl"
    tp.write_text("", encoding="utf-8")  # present but empty: no slow call recorded
    args = ["grade", "--samples", str(sp), "--log", str(lp), "--trace", str(tp),
            "--since", "20:00:00", "--until", "20:10:00"]
    sp.write_text("".join(json.dumps(s) + "\n" for s in run()), encoding="utf-8")
    assert g.main(args) == 0 and "PASS" in capsys.readouterr().out
    sp.write_text("".join(json.dumps(s) + "\n" for s in run(spikes={20: 200})), encoding="utf-8")
    assert g.main(args + ["--budget-ok"]) == 2
    assert g.main(args) == 1
    tp.unlink()
    assert g.main(args + ["--budget-ok"]) == 1  # missing trace: slow call not ruled out
    with pytest.raises(SystemExit) as excinfo:
        g.main(args[:-4])
    assert excinfo.value.code == 2  # argparse: --since / --until are required


def test_powershell_utf16_redirect_is_read(tmp_path):
    lp = tmp_path / "2026-10-27.log"
    lp.write_text(PROOF + "\n", encoding="utf-8")
    sp = tmp_path / "s.jsonl"
    sp.write_bytes("".join(json.dumps(s) + "\r\n" for s in run()).encode("utf-16"))  # BOM + CRLF
    assert g.main(["grade", "--samples", str(sp), "--log", str(lp), "--trace", str(tmp_path / "x"),
                   "--since", "20:00:00", "--until", "20:10:00"]) == 0


def test_sampler_reads_the_coach_file_before_the_state(monkeypatch, capsys):
    order = []
    monkeypatch.setattr(g, "_read_json", lambda p: order.append("coach") or {"game_time_s": 100})
    monkeypatch.setattr(g, "_get_state", lambda base: order.append("state") or
                        {"mode_key": "arena", "liveclient": {"game_time_s": 130, "hp": 1, "hp_max": 2}})
    assert g.main(["sample", "--count", "1"]) == 0
    assert order == ["coach", "state"] and json.loads(capsys.readouterr().out)["lag_s"] == 30.0


def test_make_sample_records_the_read_to_get_span():
    wall = datetime(2026, 10, 27, 20, 0)
    assert sample(wall, 300, 260, get_s=1.23456)["get_s"] == 1.235
    for bad in (None, -0.5, float("nan"), float("inf"), True, "2"):
        assert sample(wall, 300, 260, get_s=bad)["get_s"] is None
    assert g.make_sample(None, None, wall)["get_s"] is None  # the old three-argument call


def test_get_span_turns_a_near_bound_fail_inconclusive():
    """RM-1345: the live clock is read at the END of the GET, the coach file before it."""
    rows = run(spikes={20: 152})
    rows[20]["get_s"] = 3.0  # 152 - 3 = 149: within the 150 s bound once the GET is discounted
    rep = grade(rows, budget_ok=True)
    assert rep["verdict"] == "INCONCLUSIVE" and "read-to-GET span" in rep["over_bound"][0]["note"]
    rows[20]["get_s"] = 1.5  # 152 - 1.5 = 150.5: still over, so still a FAIL
    assert grade(rows, budget_ok=True)["verdict"] == "FAIL"
    rows[20]["get_s"] = 2.0  # exactly the bound is inside, as for lag_s itself
    assert grade(rows, budget_ok=True)["verdict"] == "INCONCLUSIVE"


def test_sample_without_a_get_span_is_never_a_fail():
    rows = run(spikes={20: 200})
    rows[20]["get_s"] = None  # a sample from a sampler that did not record the span
    rep = grade(rows, budget_ok=True)
    assert rep["verdict"] == "INCONCLUSIVE" and "get_s" in rep["over_bound"][0]["note"]
    del rows[20]["get_s"]
    assert grade(rows, budget_ok=True)["verdict"] == "INCONCLUSIVE"
    assert grade(run(), budget_ok=True)["verdict"] == "PASS"  # no over-bound sample: span unused


def test_sampler_records_the_span_from_coach_read_to_get_end(monkeypatch, capsys):
    clock = [10.0]  # the read takes 1.0 s and the GET 2.25 s: the span must hold BOTH

    def read(p):
        clock[0] += 1.0
        return {"game_time_s": 100}

    def get(base):
        clock[0] += 2.25
        return {"mode_key": "arena", "liveclient": {"game_time_s": 130}}

    monkeypatch.setattr(g.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(g, "_read_json", read)
    monkeypatch.setattr(g, "_get_state", get)
    assert g.main(["sample", "--count", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["get_s"] == 3.25


def test_marks_match_the_coach_source_strings():
    # The grader is useless if the log strings drift from the code that emits them.
    arena = (ROOT / "coaches" / "arena_coach.py").read_text(encoding="utf-8")
    assert "Arena state-debounce: signature unchanged " in arena
    assert '"Arena: no fields parsed"' in arena
    assert '@safe_coach_output("Arena")' in arena
    assert '"%s coach error: %s"' in (ROOT / "core" / "safe_coach_output.py").read_text(encoding="utf-8")
    assert '_MODE_NAME     = "arena"' in arena
