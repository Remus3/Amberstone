"""Tests for core.aram_coach_shadow - the Stage 2 ARAM shadow writer.

log_aram_coach appends ONE record per distinct coarse game state to
data/aram_coach_shadow.jsonl, capturing the deterministic ARAM block beside
the live Haiku block, so the operator can eyeball them. Mirrors
core.det_coach_shadow: same fail-soft contract (never raises), same per-path
coarse-state dedup, and the item-386 live-game gate (lc["champion"] present).

Each test uses its own tmp_path so the module-level per-path dedup cache is
isolated between cases.
"""

from __future__ import annotations

import json

from core.aram_coach_shadow import log_aram_coach

_NOW = "2026-06-27T00:00:00+00:00"

_DET = {
    "action": "ALL-IN",
    "fight_rule": "Respect Ashe R (stun) before you commit",
    "risk": "Ashe R stun - top CC threat",
    "reset_item": "No fountain trips; save toward Infinity Edge (1400g remaining).",
    "item_build": "Kraken Slayer -> Infinity Edge",
    "item_build_reasons": {"Kraken": "spear proc"},
}

_LIVE = {
    "action": "POKE PHASE",
    "fight_rule": "E ready + 4 spears stacked; respect Viego W root.",
    "risk": "Viego W root locks you down.",
    "reset_item": "No fountain; next BorK (1400g remaining).",
    "item_build": "Blade of The Ruined King -> Kraken Slayer",
    "item_build_reasons": {"BorK": "on-hit DPS"},
}


def _read_lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_writes_one_record_both_sides(tmp_path):
    target = tmp_path / "aram_coach_shadow.jsonl"
    lc = {"champion": "Kalista", "enemy_team": ["Ashe", "Annie"]}

    rec = log_aram_coach(_DET, _LIVE, lc, "aram", path=target, now_iso=_NOW)

    assert rec is not None
    lines = _read_lines(target)
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["ts"] == _NOW
    assert row["champ"] == "Kalista"
    assert row["enemy_comp"] == ["Ashe", "Annie"]
    assert row["deterministic"] == _DET
    assert row["live_haiku"] == _LIVE


def test_no_champion_gate_skips(tmp_path):
    # Item-386 lesson: never log a lobby/idle/Champ0 row. The live-game gate is
    # lc["champion"] present.
    target = tmp_path / "aram_coach_shadow.jsonl"

    rec_no_lc = log_aram_coach(_DET, _LIVE, None, "aram", path=target, now_iso=_NOW)
    assert rec_no_lc is None
    assert not target.exists()

    rec_empty = log_aram_coach(_DET, _LIVE, {}, "aram", path=target, now_iso=_NOW)
    assert rec_empty is None
    assert not target.exists()

    rec_blank = log_aram_coach(
        _DET, _LIVE, {"champion": ""}, "aram", path=target, now_iso=_NOW
    )
    assert rec_blank is None
    assert not target.exists()


def test_dedup_identical_coarse_state_writes_once(tmp_path):
    target = tmp_path / "aram_coach_shadow.jsonl"
    lc = {"champion": "Kalista", "enemy_team": ["Ashe"]}

    first = log_aram_coach(_DET, _LIVE, lc, "aram", path=target, now_iso=_NOW)
    second = log_aram_coach(_DET, _LIVE, lc, "aram", path=target, now_iso=_NOW)

    assert first is not None
    assert second is None
    assert len(_read_lines(target)) == 1


def test_distinct_action_re_logs(tmp_path):
    # A changed deterministic action is a meaningful state shift -> re-log so
    # idle ticks dedup but real coaching transitions are captured.
    target = tmp_path / "aram_coach_shadow.jsonl"
    lc = {"champion": "Kalista", "enemy_team": ["Ashe"]}

    log_aram_coach(_DET, _LIVE, lc, "aram", path=target, now_iso=_NOW)
    det2 = dict(_DET, action="FALL BACK")
    log_aram_coach(det2, _LIVE, lc, "aram", path=target, now_iso=_NOW)

    assert len(_read_lines(target)) == 2


def test_distinct_enemy_comp_re_logs(tmp_path):
    target = tmp_path / "aram_coach_shadow.jsonl"
    lc1 = {"champion": "Kalista", "enemy_team": ["Ashe"]}
    lc2 = {"champion": "Kalista", "enemy_team": ["Ashe", "Zed"]}

    log_aram_coach(_DET, _LIVE, lc1, "aram", path=target, now_iso=_NOW)
    log_aram_coach(_DET, _LIVE, lc2, "aram", path=target, now_iso=_NOW)

    assert len(_read_lines(target)) == 2


def test_malformed_inputs_no_raise(tmp_path):
    target = tmp_path / "aram_coach_shadow.jsonl"

    # Non-dict det / live still log (coerced) as long as the gate passes.
    rec = log_aram_coach(
        "garbage", None, {"champion": "Lux", "enemy_team": ["Brand"]},
        "aram", path=target, now_iso=_NOW,
    )
    assert rec is not None
    row = json.loads(_read_lines(target)[-1])
    # Non-dict sides coerce to the all-empty six-field block (every column
    # present, never raises) - NOT a bare {} - so the shadow row is uniform.
    _empty = {
        "action": "",
        "fight_rule": "",
        "risk": "",
        "reset_item": "",
        "item_build": "",
        "item_build_reasons": {},
    }
    assert row["deterministic"] == _empty
    assert row["live_haiku"] == _empty

    # A wholly broken lc (not a dict) is gated out (no champion) -> None.
    rec_bad_lc = log_aram_coach(_DET, _LIVE, 12345, "aram", path=target, now_iso=_NOW)
    assert rec_bad_lc is None


def test_enemy_comp_missing_logs_empty_list(tmp_path):
    # The gate is on champion, NOT enemy_comp (an ARAM tick before the
    # scoreboard fully populates still has a champion). enemy_comp degrades to
    # [] rather than blocking the row.
    target = tmp_path / "aram_coach_shadow.jsonl"
    lc = {"champion": "Kalista"}

    rec = log_aram_coach(_DET, _LIVE, lc, "aram", path=target, now_iso=_NOW)
    assert rec is not None
    row = json.loads(_read_lines(target)[-1])
    assert row["champ"] == "Kalista"
    assert row["enemy_comp"] == []
