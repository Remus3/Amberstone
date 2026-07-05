"""Tests for the SHADOW-ONLY ARAM coach wiring in dashboard._deterministic_coaching.

The HARD SAFETY PROPERTY: the shadow path is purely additive + fail-soft and
must NEVER mutate any field on the served coach / det dict. These tests assert:
  1. shadow_log_aram_coach writes a record for a real ARAM in-game tick, AND
  2. the served coach dict is byte-identical (deep-equal) before and after the
     shadow path runs (the safety property), AND
  3. it is fail-soft (no raise) and correctly gated (no log for non-aram modes
     or a no-champion liveclient).

No DS-engine network call happens: shadow_log_aram_coach assembles the block
from the dashboard state + passed-in build/hint primitives; the build-table /
hint reads are fail-soft and degrade to empty when the engine data is absent in
the test environment.
"""

from __future__ import annotations

import copy
import json

from dashboard._deterministic_coaching import shadow_log_aram_coach


def _read_lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_writes_record_for_real_aram_tick(tmp_path):
    target = tmp_path / "aram_coach_shadow.jsonl"
    coach = {"champion": "Kalista", "hp_pct": 85, "action": "POKE"}
    lc = {
        "champion": "Kalista",
        "enemy_team": ["Ashe", "Annie", "Leona", "Malphite", "Sett"],
        "hp": 850,
        "hp_max": 1000,
        "owned_items": ["Berserker's Greaves"],
    }

    shadow_log_aram_coach(coach, lc, "aram", path=target)

    lines = _read_lines(target)
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["champ"] == "Kalista"
    assert "Ashe" in row["enemy_comp"]
    # both sides present with the shadow block keys (the original fields plus
    # choices, the A/B array, plus the R78 item_extra + objective tail - all
    # captured for shadow comparison).
    assert set(row["deterministic"].keys()) == {
        "action", "fight_rule", "risk", "reset_item",
        "item_build", "item_build_reasons", "choices",
        "item_extra", "objective",
    }
    assert set(row["live_haiku"].keys()) == set(row["deterministic"].keys())


def test_served_coach_dict_unchanged_safety_property(tmp_path):
    target = tmp_path / "aram_coach_shadow.jsonl"
    coach = {
        "champion": "Kalista",
        "hp_pct": 85,
        "action": "POKE PHASE",
        "fight_rule": "live haiku fight rule",
        "risk": "live haiku risk",
        "reset_item": "live haiku reset",
        "item_build": "live haiku build",
        "item_build_reasons": {"BorK": "live reason"},
        "choices": [{"label": "A"}],
    }
    lc = {
        "champion": "Kalista",
        "enemy_team": ["Ashe", "Annie"],
        "hp": 850,
        "hp_max": 1000,
    }
    coach_before = copy.deepcopy(coach)
    lc_before = copy.deepcopy(lc)

    shadow_log_aram_coach(coach, lc, "aram", path=target)

    # THE SAFETY PROPERTY: the served dicts are byte-identical after the
    # shadow path. Nothing the shadow logger does may touch served output.
    assert coach == coach_before
    assert lc == lc_before


def test_non_aram_mode_does_not_log(tmp_path):
    target = tmp_path / "aram_coach_shadow.jsonl"
    coach = {"champion": "Ahri"}
    lc = {"champion": "Ahri", "enemy_team": ["Zed"]}

    shadow_log_aram_coach(coach, lc, "sr", path=target)
    shadow_log_aram_coach(coach, lc, "arena", path=target)
    shadow_log_aram_coach(coach, lc, "tft", path=target)

    assert not target.exists()


def test_no_champion_liveclient_does_not_log(tmp_path):
    target = tmp_path / "aram_coach_shadow.jsonl"
    # Stale coach keeps champion after a game ends; lc has no champion -> gated.
    coach = {"champion": "Kalista", "hp_pct": 90}

    shadow_log_aram_coach(coach, None, "aram", path=target)
    shadow_log_aram_coach(coach, {}, "aram", path=target)
    shadow_log_aram_coach(coach, {"enemy_team": ["Ashe"]}, "aram", path=target)

    assert not target.exists()


def test_deterministic_item_build_filled_from_table(tmp_path):
    # The deterministic block's item_build is now filled from the curated ARAM
    # build-order table (previously always ""). For a champ with a real table
    # entry it is a comma-separated list of completed items (<=6). SHADOW-ONLY:
    # this changes only the logged deterministic block, never served output.
    target = tmp_path / "aram_coach_shadow.jsonl"
    coach = {"champion": "Kalista", "hp_pct": 85}
    lc = {
        "champion": "Kalista",
        "enemy_team": ["Ashe", "Annie", "Leona", "Malphite", "Sett"],
        "hp": 850,
        "hp_max": 1000,
        "owned_items": ["Berserker's Greaves"],
    }

    shadow_log_aram_coach(coach, lc, "aram", path=target)

    row = json.loads(_read_lines(target)[0])
    item_build = row["deterministic"]["item_build"]
    # Kalista has a curated ARAM order; item_build is now a non-empty join.
    assert item_build != ""
    parts = [p.strip() for p in item_build.split(",")]
    assert 1 <= len(parts) <= 6
    assert "Infinity Edge" in parts


def test_deterministic_item_build_empty_for_unknown_champ(tmp_path):
    # A champion with NO build-order table entry keeps item_build "" (fail-soft,
    # unchanged behavior) while the record is still written.
    target = tmp_path / "aram_coach_shadow.jsonl"
    coach = {"champion": "ZzNotARealChampZz", "hp_pct": 85}
    lc = {
        "champion": "ZzNotARealChampZz",
        "enemy_team": ["Ashe", "Annie"],
        "hp": 850,
        "hp_max": 1000,
    }

    shadow_log_aram_coach(coach, lc, "aram", path=target)

    row = json.loads(_read_lines(target)[0])
    assert row["deterministic"]["item_build"] == ""


def test_failsoft_garbage_inputs_no_raise(tmp_path):
    target = tmp_path / "aram_coach_shadow.jsonl"
    # Must not raise on any garbage; just returns having logged or not.
    shadow_log_aram_coach("garbage", 12345, "aram", path=target)
    shadow_log_aram_coach(None, None, None, path=target)
    shadow_log_aram_coach({}, {}, "aram", path=target)
    # No assertion beyond "did not raise".


def test_deterministic_objective_from_coach_tower_hp(tmp_path):
    # The deterministic objective (R78) is filled from the vision tower-HP
    # echoed on the coach dict (my_tower_hp / enemy_tower_hp - INPUT state, not
    # a Haiku output, so non-circular). enemy T1 at 0 -> "push to their base".
    # SHADOW-ONLY: changes only the logged deterministic block.
    target = tmp_path / "aram_coach_shadow.jsonl"
    coach = {
        "champion": "Kalista", "hp_pct": 85,
        "my_tower_hp": 90, "enemy_tower_hp": 0,
    }
    lc = {
        "champion": "Kalista", "enemy_team": ["Ashe", "Annie"],
        "hp": 850, "hp_max": 1000,
    }

    shadow_log_aram_coach(coach, lc, "aram", path=target)

    row = json.loads(_read_lines(target)[0])
    assert "their base" in row["deterministic"]["objective"].lower()


def test_deterministic_objective_empty_without_tower_hp(tmp_path):
    # No tower HP on the coach dict -> objective degrades to "" (fail-soft, like
    # wave_pct absent server-side), while the record is still written.
    target = tmp_path / "aram_coach_shadow.jsonl"
    coach = {"champion": "Kalista", "hp_pct": 85}
    lc = {
        "champion": "Kalista", "enemy_team": ["Ashe"],
        "hp": 850, "hp_max": 1000,
    }

    shadow_log_aram_coach(coach, lc, "aram", path=target)

    row = json.loads(_read_lines(target)[0])
    assert row["deterministic"]["objective"] == ""


def test_deterministic_item_extra_is_omit(tmp_path):
    # owned_item_count is always a known non-negative int in the wired path, so
    # item_extra (R78) resolves to the safe "omit" - never a fabricated
    # Pot/Shard consumable (do-not-flip-blind).
    target = tmp_path / "aram_coach_shadow.jsonl"
    coach = {"champion": "Kalista", "hp_pct": 85}
    lc = {
        "champion": "Kalista", "enemy_team": ["Ashe"],
        "hp": 850, "hp_max": 1000, "owned_items": ["Berserker's Greaves"],
    }

    shadow_log_aram_coach(coach, lc, "aram", path=target)

    row = json.loads(_read_lines(target)[0])
    assert row["deterministic"]["item_extra"] == "omit"
