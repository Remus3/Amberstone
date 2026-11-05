"""Tests for tools/gated_g312_aram_debounce_lag.py (G3-12 ARAM state-debounce lag read-back).

Every log line, sample and trace row here is hand-written and synthetic (RM-906):
no real Riot id, game id or match key.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from tools import gated_g312_aram_debounce_lag as g

DAY = date(2026, 11, 4)
SINCE, UNTIL = datetime(2026, 11, 4, 20, 0), datetime(2026, 11, 4, 20, 10)
PROOF = ("20:01:05.120 DEBUG    rc.aram              [aram_coach.py:1219] ARAM state-debounce: "
         "signature unchanged (age 6.0s < 45s ceiling) - reusing cached coaching")
ROOT = Path(__file__).resolve().parent.parent


def sample(wall, lc_gt, co_gt, hp=900, mode="aram", hp_max=1000):
    if isinstance(wall, str):
        wall = datetime.fromisoformat(wall)
    return g.make_sample({"mode_key": mode, "liveclient": {"game_time_s": lc_gt, "hp": hp, "hp_max": hp_max}},
                         {"game_time_s": co_gt}, wall)


def ended(wall):
    return g.make_sample({"mode_key": "client", "liveclient": {}}, {"game_time_s": 600}, wall)


def run(lag=40, spikes=None, dead=(), failed=(), n=25, step=25, end=True, mode="aram"):
    """n polls every `step` s from SINCE (25 x 25 s tiles 20:00:00 .. 20:10:00), game clock 30 s at
    the first, then one game-over poll 20 s after the last when `end`."""
    rows = []
    for i in range(n):
        wall, gt = SINCE + timedelta(seconds=i * step), 30 + i * step
        if i in failed:
            rows.append(g.make_sample({"error": "URLError"}, None, wall))
        else:
            rows.append(sample(wall, gt, gt - (spikes or {}).get(i, lag),
                               hp=0 if i in dead else 900, mode=mode))
    if end:
        rows.append(ended(SINCE + timedelta(seconds=(n - 1) * step + 20)))
    return rows


def log(*lines):
    return g.parse_log(lines, DAY)


def grade(rows, lines=(PROOF,), slow=(), budget_ok=False, trace_ok=True):
    return g.grade(rows, log(*lines), list(slow), SINCE, UNTIL, budget_ok, trace_ok)


def test_pass_needs_proof_full_coverage_and_every_lag_within_90s():
    rep = grade(run(lag=85))
    assert rep["verdict"] == "PASS" and rep["usable"] == 25 and rep["max_lag_s"] == 85.0
    assert not rep["coverage"]["holes"] and rep["coverage"]["end_seen"]


def test_bound_is_90_not_the_arena_150():
    assert g.LAG_BOUND_S == 90.0
    rep = grade(run(spikes={10: 95}), budget_ok=True)
    assert rep["verdict"] == "FAIL" and rep["over_bound"][0]["lag_s"] == 95.0
    assert grade(run(spikes={10: 90})).get("verdict") == "PASS"  # the bound itself is inside


def test_unexcused_lag_is_fail_only_with_budget_assertion_and_a_trace():
    rows = run(spikes={10: 120})
    assert grade(rows)["verdict"] == "INCONCLUSIVE"
    assert grade(rows, budget_ok=True, trace_ok=False)["verdict"] == "INCONCLUSIVE"
    assert grade(rows, budget_ok=True)["verdict"] == "FAIL"


def test_zero_proof_lines_and_arena_proof_lines_are_never_a_pass():
    assert grade(run(), lines=())["verdict"] == "INCONCLUSIVE"
    arena = PROOF.replace("ARAM state-debounce", "Arena state-debounce")
    assert grade(run(), lines=(arena,))["verdict"] == "INCONCLUSIVE"
    late = "20:11:00.000" + PROOF[12:]  # outside the window
    assert grade(run(), lines=(late,))["proof_lines"] == 0


def test_arena_samples_are_not_usable():
    assert grade(run(mode="arena"))["verdict"] == "NO_RESULT"
    assert not g.usable(sample("2026-11-04T20:02:00", 300, 260, mode="arena"))
    assert g.usable(sample("2026-11-04T20:02:00", 300, 260))


def test_coverage_holes_dead_runs_and_missing_game_over_are_not_a_pass():
    assert grade(run(failed=(5,)))["verdict"] == "INCONCLUSIVE"  # a failed poll is a hole
    assert grade(run(dead=(5,)))["verdict"] == "PASS"  # one dead poll is known, not a hole
    assert grade(run(dead=tuple(range(5, 11))))["verdict"] == "INCONCLUSIVE"  # 125 s dead run
    assert grade(run(end=False))["verdict"] == "INCONCLUSIVE"
    assert grade(run(n=20))["verdict"] == "INCONCLUSIVE"  # stopped early: tail hole


def test_coach_file_ahead_of_the_live_clock_is_not_a_pass():
    rep = grade(run(spikes={3: -40}))
    assert rep["verdict"] == "INCONCLUSIVE" and rep["coverage"]["ahead"]


def test_excuses_inside_the_lag_window_only():
    rows = run(spikes={10: 120})  # sample at 20:04:10, window 20:02:10 .. 20:04:10
    err = "20:03:00.000 ERROR    coach                ARAM coach error: timeout"
    assert grade(rows, lines=(PROOF, err), budget_ok=True)["verdict"] == "INCONCLUSIVE"
    nf = "20:03:00.000 WARNING  rc.aram              ARAM: no fields parsed (raw len=0)"
    assert grade(rows, lines=(PROOF, nf), budget_ok=True)["verdict"] == "INCONCLUSIVE"
    old = "20:01:00.000 ERROR    coach                ARAM coach error: timeout"
    assert grade(rows, lines=(PROOF, old), budget_ok=True)["verdict"] == "FAIL"
    arena_err = "20:03:00.000 ERROR    coach                Arena coach error: timeout"
    assert grade(rows, lines=(PROOF, arena_err), budget_ok=True)["verdict"] == "FAIL"
    call = (datetime(2026, 11, 4, 20, 3, 50), datetime(2026, 11, 4, 20, 4, 30))  # still running
    assert grade(rows, slow=[call], budget_ok=True)["verdict"] == "INCONCLUSIVE"


def test_slow_calls_filters_mode_phase_and_duration():
    t = datetime(2026, 11, 4, 20, 0).timestamp()
    end = datetime.fromtimestamp(t)
    rows = [{"ts": t, "mode": "aram", "phase": "coach", "dur_ms": 25000},
            {"ts": t, "mode": "aram", "phase": "coach", "dur_ms": 19000},
            {"ts": t, "mode": "aram", "phase": "coach", "dur_ms": 2500},
            {"ts": t + 60, "mode": "arena", "phase": "coach", "dur_ms": 31000},
            {"ts": t + 90, "mode": "arena", "phase": "tick", "dur_ms": 9000},
            {"ts": "x", "mode": "aram", "phase": "coach", "dur_ms": 25000}]
    assert g.slow_calls(rows) == [(end - timedelta(seconds=25), end)]


def test_slow_non_coach_phases_count_over_2s():
    t = datetime(2026, 11, 4, 20, 0).timestamp()
    end = datetime.fromtimestamp(t)
    rows = [{"ts": t, "mode": "aram", "phase": "shadow", "dur_ms": 2500},
            {"ts": t, "mode": "aram", "phase": "tick", "dur_ms": 1900},
            {"ts": t, "mode": "aram", "phase": None, "dur_ms": 9000}]
    assert g.slow_calls(rows) == [(end - timedelta(milliseconds=2500), end)]


def test_failed_coach_file_write_excuses_a_lag():
    rows = run(spikes={10: 120})
    sw = "20:03:00.000 ERROR    rc.coaches._base     safe_write aram_coaching_data.json: [Errno 13] denied"
    assert grade(rows, lines=(PROOF, sw), budget_ok=True)["verdict"] == "INCONCLUSIVE"
    other = sw.replace("aram_coaching_data", "arena_coaching_data")
    assert grade(rows, lines=(PROOF, other), budget_ok=True)["verdict"] == "FAIL"


def test_a_poll_still_in_the_aram_game_is_not_the_game_over():
    rows = run(end=False)
    rows.append(sample(SINCE + timedelta(seconds=24 * 25 + 20), 650, 640))  # aram, still timed
    rows[-1]["hp"] = None  # neither usable nor dead: not known, yet not an end
    assert grade(rows)["coverage"]["end_seen"] is False
    rows.append(sample(SINCE + timedelta(seconds=24 * 25 + 25), 655, 640, mode="arena"))
    assert grade(rows)["coverage"]["end_seen"] is False  # first poll after the last known is not an end


def test_hp_zero_without_hp_max_is_unknown_not_dead():
    rows = run()
    rows[5] = sample(rows[5]["wall"], rows[5]["lc_game_time_s"], 0, hp=0, hp_max=0)
    rep = grade(rows)
    assert rep["coverage"]["known"] == 24 and rep["verdict"] == "INCONCLUSIVE"  # a 50 s hole


def test_main_grade_exit_codes_and_required_window(tmp_path, capsys):
    lp = tmp_path / "2026-11-04.log"
    lp.write_text(PROOF + "\n", encoding="utf-8")
    sp = tmp_path / "s.jsonl"
    tp = tmp_path / "trace.jsonl"
    tp.write_text("", encoding="utf-8")
    args = ["grade", "--samples", str(sp), "--log", str(lp), "--trace", str(tp),
            "--since", "20:00:00", "--until", "20:10:00"]
    sp.write_text("".join(json.dumps(s) + "\n" for s in run()), encoding="utf-8")
    assert g.main(args) == 0 and "G3-12 verdict: PASS" in capsys.readouterr().out
    sp.write_text("".join(json.dumps(s) + "\n" for s in run(spikes={20: 100})), encoding="utf-8")
    assert g.main(args + ["--budget-ok"]) == 2
    assert g.main(args) == 1
    tp.unlink()
    assert g.main(args + ["--budget-ok"]) == 1
    try:
        g.main(args[:-4])
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("grade ran without a window")


def test_powershell_utf16_redirect_is_read(tmp_path):
    lp = tmp_path / "2026-11-04.log"
    lp.write_text(PROOF + "\n", encoding="utf-8")
    sp = tmp_path / "s.jsonl"
    sp.write_bytes("".join(json.dumps(s) + "\r\n" for s in run()).encode("utf-16"))
    assert g.main(["grade", "--samples", str(sp), "--log", str(lp), "--trace", str(tmp_path / "x"),
                   "--since", "20:00:00", "--until", "20:10:00"]) == 0


def test_sampler_reads_the_aram_coach_file_before_the_state(monkeypatch, capsys):
    order, paths = [], []
    monkeypatch.setattr(g, "_read_json", lambda p: paths.append(p) or order.append("coach")
                        or {"game_time_s": 100})
    monkeypatch.setattr(g, "_get_state", lambda base: order.append("state") or
                        {"mode_key": "aram", "liveclient": {"game_time_s": 130, "hp": 1, "hp_max": 2}})
    assert g.main(["sample", "--count", "1"]) == 0
    assert order == ["coach", "state"] and json.loads(capsys.readouterr().out)["lag_s"] == 30.0
    assert paths[0].name == "aram_coaching_data.json"


def test_marks_and_bound_premises_match_the_coach_source():
    # The grader is useless if the log strings drift, and the 90 s bound rests on
    # the 30 s game-time band, the 25 s stable cadence and the 20 s Haiku timeout.
    aram = (ROOT / "coaches" / "aram_coach.py").read_text(encoding="utf-8")
    assert '"ARAM state-debounce: signature unchanged "' in aram
    assert '"ARAM: no fields parsed (raw len=%d)"' in aram
    assert '@safe_coach_output("ARAM")\n    def _run_coach' in aram
    assert '_MODE_NAME     = "aram"' in aram
    assert '_DATA_FILENAME = "aram_coaching_data.json"' in aram
    assert 'time_band = _bucket(state.get("game_seconds", 0), 30)' in aram
    assert "_STABLE_DEBOUNCE_S  = 25.0" in aram
    assert "_STATE_DEBOUNCE_MAX_STALE_S = 45.0" in aram
    assert re.search(r'"game_time_s":\s+state\.get\("game_seconds",\s+0\)', aram)
    assert re.search(r"timeout\s+=\s+20,", aram)
    assert re.search(r'"%s coach error: %s"', (ROOT / "core" / "safe_coach_output.py").read_text(encoding="utf-8"))
    base = (ROOT / "coaches" / "_base_coach.py").read_text(encoding="utf-8")
    assert '"mode":      self._MODE_NAME' in base and 'self._trace_coach_tick("coach", dt' in base
