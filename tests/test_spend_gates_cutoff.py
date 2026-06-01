"""Regression tests for the API spend-gate cutoff + per-match cost panel.

Covers the gate registry, purpose->gate attribution, the live disabled-set
gate, and the per-match cost segment recording (note_match_boundary +
recent_match_avg) with pruning to the last N full matches.
"""
import json

import pytest

from core.cost_tracker import (
    GATES,
    GATE_META,
    CostTracker,
    _purpose_to_gate,
    _RECENT_MATCHES_KEEP,
)


def _tracker(tmp_path, disabled=None):
    disabled = list(disabled or [])
    return CostTracker(
        config_provider=lambda: {"disabled_coaches": disabled},
        spend_dir=tmp_path,
    )


def test_gate_registry_is_the_seven_known_gates():
    assert GATES == ["sr", "aram", "arena", "brawl",
                     "vision", "champ_select", "tft"]
    for g in GATES:
        assert GATE_META[g]["label"]
        assert GATE_META[g]["explain"]


@pytest.mark.parametrize("purpose,gate", [
    ("sr_coach", "sr"),
    ("aram_coach", "aram"),
    ("aram_aug_select", "aram"),
    ("arena_coach", "arena"),
    ("brawl_coach", "brawl"),
    ("vision_relay", "vision"),
    ("vision_direct", "vision"),
    ("tft_vision", "tft"),       # tft prefix wins over the vision substring
    ("tft_pbe", "tft"),
    ("champ_select_brief", "champ_select"),
    ("aram_team_analyzer", "champ_select"),
    ("experimental_builder", "champ_select"),
    ("coach_relay", None),       # relayed text - not a gated purpose
    ("agent7_warm", None),
    ("", None),
])
def test_purpose_to_gate_mapping(purpose, gate):
    assert _purpose_to_gate(purpose) == gate


def test_gate_disabled_reads_config_live(tmp_path):
    t = _tracker(tmp_path, disabled=["vision", "tft"])
    assert t.gate_disabled("vision") is True
    assert t.gate_disabled("tft") is True
    assert t.gate_disabled("sr") is False
    # gates_state reflects the same disabled set
    st = t.gates_state()
    assert st["vision"]["disabled"] is True
    assert st["sr"]["disabled"] is False


def test_set_coach_disabled_persists_for_any_gate(tmp_path, monkeypatch):
    cfg = tmp_path / "coach_settings.json"
    cfg.write_text(json.dumps({"disabled_coaches": []}), encoding="utf-8")
    monkeypatch.setattr("core.cost_tracker._COACH_CFG", cfg)
    t = _tracker(tmp_path)
    t.set_coach_disabled("vision", True)
    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert "vision" in saved["disabled_coaches"]


def test_recent_match_avg_empty_when_no_matches(tmp_path):
    t = _tracker(tmp_path)
    avg = t.recent_match_avg()
    assert set(avg) == set(GATES)
    assert avg["sr"] == {"usd": 0.0, "tokens": 0, "n": 0}


def test_per_match_segment_records_and_averages(tmp_path):
    t = _tracker(tmp_path)
    # Match 1: one SR call + one vision call.
    t.record_call(model="m", input_tokens=100, output_tokens=50,
                  cache_read=0, cache_write=0, purpose="sr_coach")
    t.record_call(model="m", input_tokens=200, output_tokens=0,
                  cache_read=0, cache_write=0, purpose="vision_relay")
    t.note_match_boundary()
    avg1 = t.recent_match_avg()
    assert avg1["sr"]["n"] == 1
    assert avg1["sr"]["tokens"] == 150            # 100 + 50
    assert avg1["vision"]["tokens"] == 200
    assert avg1["sr"]["usd"] > 0

    # Match 2: only an SR call. Average over the two matches.
    t.record_call(model="m", input_tokens=50, output_tokens=0,
                  cache_read=0, cache_write=0, purpose="sr_coach")
    t.note_match_boundary()
    avg2 = t.recent_match_avg()
    assert avg2["sr"]["n"] == 2
    # match1 sr tokens 150, match2 sr tokens 50 -> avg 100
    assert avg2["sr"]["tokens"] == 100
    # vision only fired in match1 (200) -> avg over 2 = 100
    assert avg2["vision"]["tokens"] == 100


def test_recent_matches_pruned_to_keep(tmp_path):
    t = _tracker(tmp_path)
    for _ in range(_RECENT_MATCHES_KEEP + 3):
        t.record_call(model="m", input_tokens=10, output_tokens=0,
                      cache_read=0, cache_write=0, purpose="sr_coach")
        t.note_match_boundary()
    rec = json.loads((tmp_path / "recent_matches.json").read_text(encoding="utf-8"))
    assert len(rec["matches"]) == _RECENT_MATCHES_KEEP


def test_ungated_purpose_excluded_from_per_match(tmp_path):
    t = _tracker(tmp_path)
    t.record_call(model="m", input_tokens=99, output_tokens=0,
                  cache_read=0, cache_write=0, purpose="coach_relay")
    t.note_match_boundary()
    avg = t.recent_match_avg()
    # coach_relay maps to no gate -> nothing attributed
    assert all(avg[g]["tokens"] == 0 for g in GATES)
