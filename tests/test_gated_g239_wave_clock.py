"""Tests for tools/gated_g239_wave_clock.py (G2-39 PREP, s144 lane gated c40).

Every input is hand-built (RM-906: no real game, match or player id). The tool
is a read-only grader; these tests pin its verdicts, that its schedule is the
production wave_callout walked forward, that its bracket bounds restate the
production constants, and that the B4 suppression it cites still exists.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import event_callouts
from tools import gated_g239_wave_clock as g239

ROOT = Path(__file__).resolve().parent.parent


def test_bracket_bounds_restate_production_constants():
    assert g239.BRACKET_EVERY2_S == event_callouts._CANNON_BRK_EVERY2_S
    assert g239.BRACKET_EVERY1_S == event_callouts._CANNON_BRK_EVERY1_S


def test_sr_mode_keys_restate_production_map():
    from dashboard import _deterministic_coaching as dc
    assert g239.SR_MODE_KEYS == {k for k, v in dc._MODE_KEY_TO_LOWER.items() if v == "sr"}


def test_schedule_is_production_wave_callout_walked_forward():
    cannons = g239.predicted_cannons(65.0, until_s=1600.0)
    assert cannons[:3] == [125.0, 215.0, 305.0]
    # Every predicted spawn is exactly what wave_callout reports just before it.
    for spawn in cannons:
        c = event_callouts.wave_callout(spawn - 1.0, [{"at_s": 65.0}])
        assert c is not None and round(spawn - 1.0 + c["eta_s"], 3) == spawn
    assert {g239.bracket(s) for s in cannons} == {"every3", "every2", "every1"}


def test_parse_clock_and_clock_round_trip():
    assert g239.parse_clock("2:05") == 125.0
    assert g239.parse_clock("125") == 125.0
    assert g239.clock(125.0) == "2:05"
    for bad in ("2:5", "2:60", "x:00", "-3", "nan"):
        with pytest.raises(ValueError):
            g239.parse_clock(bad)


def _state(lc: dict, callouts: list | None = None) -> dict:
    return {"mode_key": "sr", "liveclient": lc, "callouts": callouts or []}


@pytest.mark.parametrize("lc,verdict", [
    ({}, "NOT_IN_GAME"),
    ({"game_time_s": 40, "minion_events": []}, "PRE_SPAWN"),
    ({"game_time_s": 120, "minion_events": []}, "ANCHOR_MISSING"),
    ({"game_time_s": 120, "minion_events": [{"at_s": 65.0}]}, "ANCHOR_OK"),
    ({"game_time_s": 120, "minion_events": [{"at_s": 65.0}, {"at_s": 95.0}]},
     "ANCHOR_MULTI"),
    ({"game_time_s": 400, "minion_events": [{"at_s": 300.0}]}, "ANCHOR_BAD"),
    ({"game_time_s": 120, "minion_events": [{"at_s": True}]}, "ANCHOR_BAD"),
])
def test_grade_state_verdicts(lc, verdict):
    assert g239.grade_state(_state(lc))["verdict"] == verdict


def test_grade_state_counts_served_wave_rows():
    res = g239.grade_state(_state({"game_time_s": 120, "minion_events": [{"at_s": 65.0}]},
                                  [{"kind": "wave", "eta_s": 5.0}, {"kind": "siege"}]))
    assert res["served_wave_rows"] == 1 and res["anchor_s"] == 65.0


def _rec(ts: str, gt: float, eta: float | None, mode: str = "sr") -> dict:
    callouts = [{"kind": "siege", "eta_s": 0.0}]
    if eta is not None:
        callouts.append({"kind": "wave", "eta_s": eta, "tag": "wave"})
    return {"ts": ts, "mode": mode, "game_time_s": gt, "callouts": callouts}


RECORDS = [
    _rec("2026-01-01T00:00:00+00:00", 100.0, 25.0),   # before --since: ignored
    _rec("2026-01-02T00:00:10+00:00", 100.0, 25.0),   # -> 125
    _rec("2026-01-02T00:00:15+00:00", 110.0, 15.0),   # -> 125 (same spawn)
    _rec("2026-01-02T00:00:40+00:00", 130.0, 85.0),   # -> 215
    _rec("2026-01-02T00:00:41+00:00", 130.0, 1.0, mode="aram"),
    _rec("2026-01-02T00:00:42+00:00", 140.0, None),   # wave row cut by the cap
    _rec("2026-01-02T00:00:50+00:00", 300.0, 5.0, mode="client"),  # SR alias -> 305
    {"ts": "2026-01-02T00:00:51+00:00", "mode": "sr", "game_time_s": 1.0,
     "callouts": 7},                                   # malformed: skipped
    _rec("not a time", 100.0, 1.0),                    # unparsable ts: skipped
]
SINCE = "2026-01-02T00:00:00+00:00"


def test_implied_spawns_filters_and_dedups():
    assert g239.implied_spawns(RECORDS, g239.parse_since(SINCE)) == [125.0, 215.0, 305.0]


def test_since_is_a_time_not_text():
    # 2026-01-01T19:00:00-05:00 is 2026-01-02T00:00:00 UTC: the same cut as SINCE.
    local = g239.parse_since("2026-01-01T19:00:00-05:00")
    assert g239.implied_spawns(RECORDS, local) == [125.0, 215.0, 305.0]
    # A Z suffix at the first kept record's own second still keeps it.
    z = g239.parse_since("2026-01-02T00:00:10Z")
    assert g239.implied_spawns(RECORDS, z) == [125.0, 215.0, 305.0]
    for bad in ("2026-01-02", "2026-01-02T00:00:00", "yesterday"):
        with pytest.raises(ValueError):
            g239.parse_since(bad)


def test_grade_shadow_verdicts():
    implied = g239.implied_spawns(RECORDS, g239.parse_since(SINCE))
    assert g239.grade_shadow([], [125.0])["verdict"] == "NO_RESULT"
    assert g239.grade_shadow(implied, [])["verdict"] == "SCHEDULE"
    hit = g239.grade_shadow(implied, [126.0, 213.0])
    assert hit["verdict"] == "MATCH" and hit["brackets_observed"] == ["every3"]
    miss = g239.grade_shadow(implied, [155.0])
    assert miss["verdict"] == "MISS" and miss["pairs"][0]["delta_s"] == 30.0


def test_cli_shadow_and_exit_codes(tmp_path, capsys):
    log = tmp_path / "det_coach_shadow.jsonl"
    log.write_text("".join(json.dumps(r) + "\n" for r in RECORDS) + "not json\n",
                   encoding="utf-8")
    before = sorted(p.name for p in tmp_path.iterdir())
    assert g239.main(["shadow", str(log), "--since", SINCE,
                      "--observed", "2:05,3:35", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "MATCH"
    assert g239.main(["shadow", str(log), "--since", SINCE, "--observed", "2:35"]) == 3
    assert g239.main(["shadow", str(tmp_path / "missing.jsonl"), "--since", SINCE]) == 2
    assert g239.main(["shadow", str(log), "--since", "2026-01-02"]) == 2  # naive
    for tol in ("inf", "nan", "0", "-1"):
        assert g239.main(["shadow", str(log), "--since", SINCE, "--observed", "2:05",
                          "--tolerance-s", tol]) == 2
    assert g239.implied_spawns([_rec(SINCE, 1e308, 1e308)], g239.parse_since(SINCE)) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == before  # read-only


def test_cli_state_and_schedule(tmp_path, capsys):
    st = tmp_path / "state.json"
    st.write_text(json.dumps(_state({"game_time_s": 120,
                                     "minion_events": [{"at_s": 65.0}]})),
                  encoding="utf-8")
    assert g239.main(["state", str(st)]) == 0
    st.write_text(json.dumps(_state({})), encoding="utf-8")
    assert g239.main(["state", str(st)]) == 3
    capsys.readouterr()
    assert g239.main(["schedule", "--anchor", "65", "--until", "300", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [c["spawn"] for c in out["cannons"]] == ["2:05", "3:35"]
    assert g239.main(["schedule", "--anchor", "nan"]) == 2


def test_cited_b4_suppression_and_shadow_field_still_exist():
    sb = (ROOT / "dashboard" / "_state_builder.py").read_text(encoding="utf-8")
    assert 'LIVE_SUPPRESSED_ENVELOPE_FIELDS = ("callouts", "lead_projection")' in sb
    assert "det = suppress_live_envelope(det" in sb
    shadow = (ROOT / "core" / "det_coach_shadow.py").read_text(encoding="utf-8")
    assert '"callouts": det.get("callouts") or []' in shadow
    dc = (ROOT / "dashboard" / "_deterministic_coaching.py").read_text(encoding="utf-8")
    assert 'os.environ.get("RC_WAVE_CALLOUT", "0") == "1"' in dc


def test_tool_source_is_ascii():
    src = (ROOT / "tools" / "gated_g239_wave_clock.py").read_bytes()
    assert src.isascii() and b"\r\n" not in src
