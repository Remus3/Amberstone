"""Tests for the SHADOW-ONLY Arena coach wiring in dashboard._deterministic_coaching.

The HARD SAFETY PROPERTY: the shadow path is purely additive + fail-soft and
must NEVER mutate any field on the served coach / det dict. These tests assert:
  1. shadow_log_arena_coach writes a record for a real Arena in-game tick, AND
  2. the served coach dict is byte-identical (deep-equal) before and after the
     shadow path runs (the safety property), AND
  3. it is fail-soft (no raise) and correctly gated (no log for non-arena
     modes or a no-champion liveclient), AND
  4. the wire-level round-aware dedup holds (idle re-ticks dedup; a new round
     re-logs).

No DS-engine network call happens: shadow_log_arena_coach assembles the block
from the dashboard state + passed-in build/threat primitives; the build-DB /
frontline / CC reads are fail-soft and degrade to empty when the engine data
is absent in the test environment.
"""

from __future__ import annotations

import copy
import json

from dashboard._deterministic_coaching import shadow_log_arena_coach

BLOCK_KEYS = {
    "action", "round_strategy", "fight_rule", "augment_advice",
    "anvil_advice", "target_priority", "risk",
}


def _read_lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def _seed_live(tmp_path):
    live = tmp_path / "arena_coaching_data.json"
    live.write_text(json.dumps({
        "action": "LIVE HAIKU ACTION",
        "round_strategy": "live strategy",
        "fight_rule": "live fight rule",
        "augment_advice": "live augment",
        "anvil_advice": "live anvil",
        "target_priority": "live target",
        "risk": "live risk",
    }), encoding="utf-8")
    return live


def _coach():
    return {
        "champion": "Jinx",
        "hp_pct": 80,
        "camp_phase": False,
        "round": 3,
        "alive_teams": 5,
        "teams": [
            {"name": "Jinx", "is_you": True},
            {"name": "Sett", "is_partner": True},
            {"name": "Malphite", "is_dead": False},
            {"name": "Lux", "is_dead": False},
            {"name": "Zed", "is_dead": True},
        ],
        "items": [],
    }


def _lc():
    return {"champion": "Jinx", "enemy_team": ["Malphite", "Lux", "Zed"]}


def test_writes_record_for_real_arena_tick(tmp_path):
    target = tmp_path / "arena_coach_shadow.jsonl"
    live = _seed_live(tmp_path)

    shadow_log_arena_coach(_coach(), _lc(), "arena", path=target, live_path=live)

    lines = _read_lines(target)
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["champ"] == "Jinx"
    assert row["round"] == 3
    assert row["enemy_comp"]  # non-empty from lc enemy_team
    # hp 80 > 70, no camp phase, no low-opp source -> the aggro band.
    assert row["deterministic"]["action"] == "PLAY AGGRO"
    assert row["live_haiku"]["action"] == "LIVE HAIKU ACTION"
    # both sides present with the seven keys
    assert set(row["deterministic"].keys()) == BLOCK_KEYS
    assert set(row["live_haiku"].keys()) == BLOCK_KEYS


def test_served_coach_dict_unchanged_safety_property(tmp_path):
    target = tmp_path / "arena_coach_shadow.jsonl"
    live = _seed_live(tmp_path)
    coach = _coach()
    lc = _lc()
    coach_before = copy.deepcopy(coach)
    lc_before = copy.deepcopy(lc)

    shadow_log_arena_coach(coach, lc, "arena", path=target, live_path=live)

    # THE SAFETY PROPERTY: the served dicts are byte-identical after the
    # shadow path. Nothing the shadow logger does may touch served output.
    assert coach == coach_before
    assert lc == lc_before


def test_non_arena_mode_does_not_log(tmp_path):
    target = tmp_path / "arena_coach_shadow.jsonl"

    for mode in ("aram", "sr", "tft", "brawl", "cherry", "", None):
        shadow_log_arena_coach(_coach(), _lc(), mode, path=target)

    assert not target.exists()


def test_no_champion_liveclient_does_not_log(tmp_path):
    target = tmp_path / "arena_coach_shadow.jsonl"
    # Stale coach keeps champion after a game ends; lc has no champion -> gated.
    coach = _coach()

    shadow_log_arena_coach(coach, None, "arena", path=target)
    shadow_log_arena_coach(coach, {}, "arena", path=target)
    shadow_log_arena_coach(coach, {"enemy_team": ["X"]}, "arena", path=target)

    assert not target.exists()


def test_failsoft_garbage_inputs_no_raise(tmp_path):
    target = tmp_path / "arena_coach_shadow.jsonl"
    # Must not raise on any garbage; just returns having logged or not.
    shadow_log_arena_coach("garbage", 12345, "arena", path=target)
    shadow_log_arena_coach(None, None, None, path=target)
    shadow_log_arena_coach({}, {}, "arena", path=target)

    assert not target.exists()


def test_frontline_path_target_priority_failsoft(tmp_path):
    # Alive opponents include a known tank (Malphite). The kill-order line must
    # FAIL-SOFT-tolerate a missing champions catalog in the test env: always a
    # str; a non-empty line always names a target; when the catalog resolves
    # Malphite as frontline the squishy (Lux) is named first.
    target = tmp_path / "arena_coach_shadow.jsonl"
    live = _seed_live(tmp_path)

    shadow_log_arena_coach(_coach(), _lc(), "arena", path=target, live_path=live)

    row = json.loads(_read_lines(target)[0])
    tp = row["deterministic"]["target_priority"]
    assert isinstance(tp, str)
    if tp:
        assert tp.startswith("Kill ")
    try:
        from core.aram_comp_verdict import compute_factors
        catalog_resolves = bool(compute_factors(["Malphite"]).get("frontline_count"))
    except Exception:  # noqa: BLE001
        catalog_resolves = False
    if catalog_resolves:
        assert "Lux" in tp


def test_dedup_same_state_once_new_round_relogs(tmp_path):
    target = tmp_path / "arena_coach_shadow.jsonl"
    live = _seed_live(tmp_path)

    # Same coarse state twice -> the round-aware sig dedups to ONE line.
    shadow_log_arena_coach(_coach(), _lc(), "arena", path=target, live_path=live)
    shadow_log_arena_coach(_coach(), _lc(), "arena", path=target, live_path=live)
    assert len(_read_lines(target)) == 1

    # A new round is a distinct validation sample -> re-logs.
    bumped = _coach()
    bumped["round"] = 4
    shadow_log_arena_coach(bumped, _lc(), "arena", path=target, live_path=live)
    lines = _read_lines(target)
    assert len(lines) == 2
    assert json.loads(lines[1])["round"] == 4
