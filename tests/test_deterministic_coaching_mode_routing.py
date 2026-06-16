"""Mode-routing guard for dashboard._deterministic_coaching (item-439 class).

mode_key "tft" / "brawl" have NO laning / build / SR-objective precompute
model, but the mode maps (_MODE_KEY_TO_UPPER / _MODE_KEY_TO_LOWER) omitted them
so a bare ``.get(mk, "sr"/"SR")`` silently routed those live ticks against the
SR tables - firing a needless DS matchup call + serving SR objective callouts
in modes that have none, and (worse) writing SR-scored rows into the HZ shadow
dataset under a "tft"/"brawl" mode label, biasing the flip-gating agreement
metric exactly the way item 439 did.

The supported precompute modes are exactly the keys of the mode maps
(sr/client/game/aram/arena); every other mode must serve the empty result and
log no shadow row.
"""
from __future__ import annotations

import json

from dashboard import _deterministic_coaching as dc


def _spy_laning(monkeypatch):
    """Replace the networked laning_choices with a call-recording stub."""
    calls = []

    def _spy(gs, mode="SR"):
        calls.append(mode)
        return []

    monkeypatch.setattr(dc, "laning_choices", _spy)
    return calls


def test_tft_compute_returns_empty_without_sr_call(monkeypatch):
    calls = _spy_laning(monkeypatch)
    out = dc._compute_uncached({"my_champion": "Annie"}, "tft")
    assert out == {"choices": [], "callouts": [], "lead_projection": {}}
    assert calls == []  # no SR matchup network call for a table-less mode


def test_brawl_compute_returns_empty_without_sr_call(monkeypatch):
    calls = _spy_laning(monkeypatch)
    out = dc._compute_uncached({"my_champion": "Garen"}, "brawl")
    assert out == {"choices": [], "callouts": [], "lead_projection": {}}
    assert calls == []


def test_unknown_mode_returns_empty(monkeypatch):
    calls = _spy_laning(monkeypatch)
    out = dc._compute_uncached({"my_champion": "Annie"}, "totally-unknown")
    assert out == {"choices": [], "callouts": [], "lead_projection": {}}
    assert calls == []


def test_supported_mode_still_routes(monkeypatch):
    # Regression guard: the supported precompute modes are unaffected - SR still
    # drives the matchup call and returns the 3-key shape.
    calls = _spy_laning(monkeypatch)
    gs = {"my_champion": "Annie", "game_time_s": 300.0, "level": 6,
          "items": [], "gold": 1000, "enemy_comp": [],
          "enemy_item_ids": [], "ally_item_ids": []}
    out = dc._compute_uncached(gs, "sr")
    assert set(out) == {"choices", "callouts", "lead_projection"}
    assert calls == ["SR"]


def _patch_laning_loader(monkeypatch, payload):
    import core.laning_scenario_precompute as lsp
    monkeypatch.setattr(
        lsp, "load_laning_scenarios", lambda mode="sr", patch=None: payload)


def test_tft_choices_shadow_writes_no_row(tmp_path, monkeypatch):
    # Even with a live champion tick + a covered payload, a tft tick must NOT
    # log against the SR laning table; the same inputs under "sr" DO log (proves
    # the guard is mode-scoped, not a coverage miss).
    _patch_laning_loader(monkeypatch, {"schema": "laning_scenarios/v3",
                                       "scenarios": {}})
    p = tmp_path / "hz.jsonl"
    coach = {"champion": "Annie", "level": 6}
    lc = {"champion": "Annie", "enemy_team": ["Caitlyn"]}
    dc.shadow_log_precomputed_choices(coach, lc, "tft", path=p)
    assert not p.exists()
    dc.shadow_log_precomputed_choices(coach, lc, "sr", path=p)
    assert p.exists()


def test_brawl_build_shadow_writes_no_row(tmp_path, monkeypatch):
    import core.build_order_variants as bov
    monkeypatch.setattr(
        bov, "load_build_order_variants", lambda mode="sr", patch=None: {})
    p = tmp_path / "hzb.jsonl"
    coach = {"champion": "Annie", "action": "poke"}
    lc = {"champion": "Annie", "enemy_team": ["Caitlyn", "Malphite"]}
    dc.shadow_log_precomputed_build(coach, lc, "brawl", path=p)
    assert not p.exists()
    dc.shadow_log_precomputed_build(coach, lc, "sr", path=p)
    assert p.exists()
