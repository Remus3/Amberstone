"""HZ-D4 - live-liveclient gate for the HZ-C1/C2 shadow loggers.

Root cause pinned here: the stale coach payload (data/*_coaching_data.json)
keeps ``champion`` forever after a game ends, while the liveclient dict is
only non-empty during a real game. Gating the shadow writers on the COACH
champion therefore logged a junk row (enemy=null, covered=false) on every
idle /api/state tick. The gate is now "liveclient champion present (a real
in-game tick)". These tests pin:

  1. idle tick (stale coach champ, lc=None) -> nothing written,
  2. client-mode tick (lc={}) -> nothing written,
  3. live tick -> a record IS written; a coverage MISS during a real game is
     still signal (covered field present, enemy may be None),
  4. suite hermeticity - a default-path call lands at the conftest-redirected
     SHADOW_PATH, never in the repo's real data/*.jsonl shadow logs.

Table loaders are monkeypatched (same pattern as test_hz_c1_wiring /
test_hz_c2_wiring) so the tests are data-independent.
"""
from __future__ import annotations

import json
from pathlib import Path

from dashboard import _deterministic_coaching as dc


def _patch_loaders(monkeypatch):
    """Data-independent stand-ins for both precompute table loaders."""
    import core.build_order_variants as bov
    import core.laning_scenario_precompute as lsp
    import core.precomputed_build_coach as pbc
    monkeypatch.setattr(
        lsp, "load_laning_scenarios",
        lambda mode="sr", patch=None: {
            "schema": "laning_scenarios/v3", "scenarios": {},
        },
    )
    monkeypatch.setattr(
        bov, "load_build_order_variants",
        lambda mode="sr", patch=None: {
            "schema": "build_order_variants/v1", "build_orders": {},
        },
    )
    monkeypatch.setattr(
        pbc, "compute_factors",
        lambda comp: {"n": len(comp or []), "frontline_count": 1},
    )


def _read(path: Path) -> list[dict]:
    return [json.loads(ln)
            for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def test_idle_tick_writes_nothing(tmp_path, monkeypatch):
    """Stale coach champion + lc=None (post-game idle tick) -> NO record."""
    _patch_loaders(monkeypatch)
    cp = tmp_path / "choice.jsonl"
    bp = tmp_path / "build.jsonl"
    coach = {"champion": "StaleChamp", "level": 18}
    dc.shadow_log_precomputed_choices(coach, None, "aram", path=cp)
    dc.shadow_log_precomputed_build(coach, None, "aram", path=bp)
    assert not cp.exists()
    assert not bp.exists()


def test_client_mode_tick_writes_nothing(tmp_path, monkeypatch):
    """Coach champion + empty lc dict (lobby/client tick) -> NO record."""
    _patch_loaders(monkeypatch)
    cp = tmp_path / "choice.jsonl"
    bp = tmp_path / "build.jsonl"
    coach = {"champion": "StaleChamp", "level": 18}
    dc.shadow_log_precomputed_choices(coach, {}, "client", path=cp)
    dc.shadow_log_precomputed_build(coach, {}, "client", path=bp)
    assert not cp.exists()
    assert not bp.exists()


def test_empty_string_champion_writes_nothing(tmp_path, monkeypatch):
    """lc carries champion="" (loading screen edge) -> falsy gate, NO record."""
    _patch_loaders(monkeypatch)
    cp = tmp_path / "choice.jsonl"
    bp = tmp_path / "build.jsonl"
    coach = {"champion": "StaleChamp", "level": 18}
    lc = {"champion": ""}
    dc.shadow_log_precomputed_choices(coach, lc, "sr", path=cp)
    dc.shadow_log_precomputed_build(coach, lc, "sr", path=bp)
    assert not cp.exists()
    assert not bp.exists()


def test_non_dict_lc_writes_nothing(tmp_path, monkeypatch):
    """Malformed lc (list / str instead of dict) -> isinstance guard, NO record."""
    _patch_loaders(monkeypatch)
    cp = tmp_path / "choice.jsonl"
    bp = tmp_path / "build.jsonl"
    coach = {"champion": "StaleChamp", "level": 18}
    for bad_lc in (["champion"], "champion", 7):
        dc.shadow_log_precomputed_choices(coach, bad_lc, "sr", path=cp)
        dc.shadow_log_precomputed_build(coach, bad_lc, "sr", path=bp)
    assert not cp.exists()
    assert not bp.exists()


def test_live_tick_coverage_miss_still_recorded(tmp_path, monkeypatch):
    """Live lc (champion present) -> a record IS written even on a coverage
    miss; the real-game coverage rate is itself the validation signal."""
    _patch_loaders(monkeypatch)
    cp = tmp_path / "choice.jsonl"
    bp = tmp_path / "build.jsonl"
    coach = {"champion": "Ahri", "level": 6, "game_time_s": 300.0}
    lc = {"champion": "Ahri", "enemy_team": ["Darius"]}
    dc.shadow_log_precomputed_choices(coach, lc, "sr", path=cp)
    dc.shadow_log_precomputed_build(coach, lc, "sr", path=bp)
    rows_c = _read(cp)
    rows_b = _read(bp)
    assert len(rows_c) == 1
    assert len(rows_b) == 1
    assert rows_c[0]["my_champion"] == "Ahri"
    assert "covered" in rows_c[0]
    assert rows_c[0]["enemy"] is None or isinstance(rows_c[0]["enemy"], str)
    assert rows_b[0]["my_champion"] == "Ahri"
    assert "covered" in rows_b[0]


def test_native_laning_action_prefers_action():
    assert dc._native_laning_action({"action": "TRADE", "immediate": "x"}) == "TRADE"


def test_native_laning_action_falls_back_to_immediate_when_blank():
    # cycle-53: alive ticks with an empty top-line action must still capture the
    # laning intent from the immediate prose, not log a blank native signal.
    assert dc._native_laning_action(
        {"action": "", "immediate": "Trade now then back"}) == "Trade now then back"
    assert dc._native_laning_action(
        {"action": "   ", "immediate": "Back off"}) == "Back off"


def test_native_laning_action_preserves_overlay_state():
    # a non-blank overlay action is kept verbatim (the report's non-laning-state
    # guard excludes it); it is never overridden by immediate.
    assert dc._native_laning_action(
        {"action": "WAIT RESPAWN", "immediate": "Trade now"}) == "WAIT RESPAWN"


def test_native_laning_action_none_when_no_signal():
    assert dc._native_laning_action({"action": "", "immediate": ""}) is None
    assert dc._native_laning_action({}) is None
    assert dc._native_laning_action(None) is None


def test_live_tick_captures_immediate_when_action_blank(tmp_path, monkeypatch):
    """Alive tick, blank top-line action, laning intent in immediate -> the
    shadow row's native_action carries the immediate prose (the cycle-53
    capture-starvation fix)."""
    _patch_loaders(monkeypatch)
    cp = tmp_path / "choice.jsonl"
    coach = {"champion": "Ahri", "level": 6, "game_time_s": 300.0,
             "action": "", "immediate": "Trade now then disengage"}
    lc = {"champion": "Ahri", "enemy_team": ["Darius"]}
    dc.shadow_log_precomputed_choices(coach, lc, "sr", path=cp)
    rows = _read(cp)
    assert len(rows) == 1
    assert rows[0]["native_action"] == "Trade now then disengage"


def test_hermeticity_default_path_redirected(tmp_path, monkeypatch):
    """A NO-path call inside a test must never touch the repo's real shadow
    log - the conftest autouse fixture redirects the module SHADOW_PATH."""
    _patch_loaders(monkeypatch)
    import core.hz_choice_shadow as hzs
    repo_root = Path(dc.__file__).resolve().parent.parent
    repo_log = repo_root / "data" / "hz_choice_shadow.jsonl"
    before = (len(repo_log.read_text(encoding="utf-8").splitlines())
              if repo_log.exists() else 0)
    # Sanity: the autouse fixture already pointed SHADOW_PATH off the repo.
    assert Path(hzs.SHADOW_PATH).resolve() != repo_log.resolve()
    coach = {"champion": "Ahri", "level": 6}
    lc = {"champion": "Ahri", "enemy_team": ["Darius"]}
    dc.shadow_log_precomputed_choices(coach, lc, "sr")  # NO path argument
    after = (len(repo_log.read_text(encoding="utf-8").splitlines())
             if repo_log.exists() else 0)
    assert after == before
    # The record landed at the redirected location instead.
    assert Path(hzs.SHADOW_PATH).exists()
    assert len(_read(Path(hzs.SHADOW_PATH))) == 1
