"""HZ-C1 - dashboard._deterministic_coaching.shadow_log_precomputed_choices
wiring tests. Pins that the state-builder shadow hook reads the coach + lc
dicts, resolves the lane opponent from the precomputed table, and records a
covered hit / a coverage miss / nothing on a lobby tick. Monkeypatches the
table loader so it is data-independent; writes to a tmp path.
"""
from __future__ import annotations

import json

from dashboard import _deterministic_coaching as dc


def _cell():
    return {
        "verdict": "all_in", "net_swing": 0.25,
        "pct_my_removed": 0.3, "pct_enemy_removed": 0.6,
        "economy": {"recall": "recall_now", "next_spike": "first_item",
                    "gold_at_band": 1300.0},
    }


def _payload():
    return {
        "schema": "laning_scenarios/v3",
        "scenarios": {"Annie": {"Caitlyn": {"L6": {"full": {"all_up": _cell()}}}}},
    }


def _patch_loader(monkeypatch):
    import core.laning_scenario_precompute as lsp
    monkeypatch.setattr(lsp, "load_laning_scenarios", lambda mode="sr", patch=None: _payload())


def _read(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_wiring_covered_hit(tmp_path, monkeypatch):
    _patch_loader(monkeypatch)
    p = tmp_path / "hz.jsonl"
    coach = {"champion": "Annie", "level": 6, "game_time_s": 300.0,
             "action": "Trade with Q", "choices": [{"key": "A", "label": "Trade"}]}
    # lc carries champion: the HZ-D4 gate requires a LIVE liveclient tick.
    lc = {"champion": "Annie", "enemy_team": ["Zed", "Caitlyn"]}
    dc.shadow_log_precomputed_choices(coach, lc, "sr", path=p)
    rows = _read(p)
    assert len(rows) == 1
    r = rows[0]
    assert r["my_champion"] == "Annie"
    assert r["enemy"] == "Caitlyn"
    assert r["covered"] is True
    # native coach signal captured for the precompute-vs-Haiku comparison
    assert r["native_action"] == "Trade with Q"
    assert r["native_choices"] == [{"key": "A", "label": "Trade", "expected_outcome": "",
                                    "confidence": "mid", "source_tag": ""}]
    assert r["band"] == "L6"
    assert r["mana_state"] == "full"
    assert r["cd_state"] == "all_up"
    assert len(r["choices"]) == 2
    assert r["choices"][0]["source_tag"] == "ds-precompute"


def test_wiring_coverage_miss_recorded(tmp_path, monkeypatch):
    _patch_loader(monkeypatch)
    p = tmp_path / "hz.jsonl"
    coach = {"champion": "Yasuo", "level": 6}
    lc = {"champion": "Yasuo", "enemy_team": ["Zed", "Caitlyn"]}
    dc.shadow_log_precomputed_choices(coach, lc, "sr", path=p)
    rows = _read(p)
    assert len(rows) == 1
    assert rows[0]["covered"] is False
    assert rows[0]["enemy"] is None
    assert rows[0]["choices"] == []


def test_wiring_no_champion_no_record(tmp_path, monkeypatch):
    _patch_loader(monkeypatch)
    p = tmp_path / "hz.jsonl"
    dc.shadow_log_precomputed_choices({}, {"enemy_team": ["Caitlyn"]}, "sr", path=p)
    assert not p.exists()


def test_wiring_never_raises(tmp_path, monkeypatch):
    # Loader raising must not escape the fail-soft wrapper.
    import core.laning_scenario_precompute as lsp

    def _boom(mode="sr", patch=None):
        raise RuntimeError("table read blew up")

    monkeypatch.setattr(lsp, "load_laning_scenarios", _boom)
    p = tmp_path / "hz.jsonl"
    # Should swallow and write nothing (champ present but loader dies).
    dc.shadow_log_precomputed_choices(
        {"champion": "Annie"},
        {"champion": "Annie", "enemy_team": ["Caitlyn"]}, "sr", path=p)
    assert not p.exists()
