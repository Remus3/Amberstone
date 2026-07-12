"""Unit tests for the rank-tier benchmark grid (overlay item 8, Phase 1).

core.rank_tier_bench serves a selected rank-tier's mode-specific average
metrics (cs / kda / kp) for the in-game stats panel. This phase runs on the
committed estimate seed (data/rank_tiers/rank_tier_averages.seed.json). Tests
pin: exact seed values (data-fidelity guards against silent drift), the
early/mid bracket duplication, arena/unknown -> "no benchmark" ({}), and the
live-first / static-fallback source() reporting under the RC_RANK_TIER_LIVE
kill switch (live source monkey-patched offline).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from core import rank_tier_bench as RTB  # noqa: E402
from core import rank_tier_source as RTS  # noqa: E402


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    # Default the kill switch OFF (deleted -> module default "0") + clear cache
    # so each test starts from the static seed unless it opts into live.
    monkeypatch.delenv("RC_RANK_TIER_LIVE", raising=False)
    RTB._reset_cache()
    yield
    RTB._reset_cache()


# --- data-fidelity guards (exact seed values) ----------------------------

def test_iron_sr_exact_seed_values():
    grid = RTB.rank_tier_grid("iron", "SR")
    assert grid  # non-empty
    early = grid["all"]["early"]
    assert early["cs"]["avg"] == 140
    assert early["kda"]["avg"] == 1.7
    assert early["kp"]["avg"] == 50


def test_challenger_sr_kda_exact_seed_value():
    grid = RTB.rank_tier_grid("challenger", "SR")
    assert grid["all"]["early"]["kda"]["avg"] == 4.3


def test_iron_aram_cs_exact_seed_value():
    grid = RTB.rank_tier_grid("iron", "ARAM")
    assert grid["all"]["early"]["cs"]["avg"] == 35


def test_metrics_are_cs_kda_kp_only():
    grid = RTB.rank_tier_grid("gold", "SR")
    assert set(grid["all"]["early"].keys()) == {"cs", "kda", "kp"}


# --- structure -----------------------------------------------------------

def test_both_brackets_present_and_equal():
    grid = RTB.rank_tier_grid("gold", "SR")
    all_role = grid["all"]
    assert set(all_role.keys()) == {"early", "mid"}
    assert all_role["early"] == all_role["mid"]


def test_all_ten_tiers_resolve_for_both_modes():
    tiers = ("iron", "bronze", "silver", "gold", "platinum",
             "emerald", "diamond", "master", "grandmaster", "challenger")
    assert len(tiers) == 10
    for tier in tiers:
        for mode in ("SR", "ARAM"):
            assert RTB.rank_tier_grid(tier, mode)["all"]["early"]["cs"]["avg"] > 0


def test_case_insensitive_tier_and_mode():
    assert RTB.rank_tier_grid("IRON", "sr")["all"]["early"]["cs"]["avg"] == 140
    assert RTB.rank_tier_grid("  Gold  ", "Aram")["all"]["early"]["cs"]["avg"] == 55


def test_returned_grid_is_a_copy():
    g1 = RTB.rank_tier_grid("iron", "SR")
    g1["all"]["early"]["cs"]["avg"] = 99999
    g2 = RTB.rank_tier_grid("iron", "SR")
    assert g2["all"]["early"]["cs"]["avg"] == 140


# --- "no benchmark" cases ------------------------------------------------

def test_arena_mode_has_no_benchmark():
    assert RTB.rank_tier_grid("iron", "ARENA") == {}
    assert RTB.rank_tier_grid("iron", "arena") == {}


def test_unknown_tier_has_no_benchmark():
    assert RTB.rank_tier_grid("wood", "SR") == {}
    assert RTB.rank_tier_grid("", "SR") == {}
    assert RTB.rank_tier_grid("iron", "") == {}


# --- source() + kill switch ---------------------------------------------

def test_source_is_static_with_kill_switch_off():
    assert RTB.source() == "static"


def test_kill_switch_toggles_source_live_vs_static(monkeypatch):
    live_rows = [
        {"role": "all", "bracket": "early", "metric": "cs", "avg": 999.0},
        {"role": "all", "bracket": "mid", "metric": "cs", "avg": 999.0},
    ]
    monkeypatch.setattr(RTS, "fetch_rows", lambda tier, mode, **k: live_rows)

    # Live ON: source() flips to "live" and the live value overlays the seed...
    monkeypatch.setenv("RC_RANK_TIER_LIVE", "1")
    RTB._reset_cache()
    assert RTB.source() == "live"
    assert RTB.rank_tier_grid("iron", "SR")["all"]["early"]["cs"]["avg"] == 999.0
    # ...while non-overridden metrics keep their static seed values.
    assert RTB.rank_tier_grid("iron", "SR")["all"]["early"]["kda"]["avg"] == 1.7

    # Live OFF: back to the static seed.
    monkeypatch.setenv("RC_RANK_TIER_LIVE", "0")
    RTB._reset_cache()
    assert RTB.source() == "static"
    assert RTB.rank_tier_grid("iron", "SR")["all"]["early"]["cs"]["avg"] == 140


def test_live_fetch_failure_falls_back_to_static(monkeypatch):
    def _boom(tier, mode, **k):
        raise RuntimeError("live source down")

    monkeypatch.setattr(RTS, "fetch_rows", _boom)
    monkeypatch.setenv("RC_RANK_TIER_LIVE", "1")
    RTB._reset_cache()
    # Fail-soft: a raising live source must not crash the loader; seed serves.
    assert RTB.source() == "static"
    assert RTB.rank_tier_grid("iron", "SR")["all"]["early"]["cs"]["avg"] == 140


def test_live_empty_falls_back_to_static(monkeypatch):
    monkeypatch.setattr(RTS, "fetch_rows", lambda tier, mode, **k: None)
    monkeypatch.setenv("RC_RANK_TIER_LIVE", "1")
    RTB._reset_cache()
    assert RTB.source() == "static"


# --- ascii hygiene -------------------------------------------------------

def test_module_is_ascii():
    b = (_ROOT / "core" / "rank_tier_bench.py").read_bytes()
    assert [(i, x) for i, x in enumerate(b) if x > 0x7F] == []


def test_this_file_is_ascii():
    b = Path(__file__).read_bytes()
    assert [(i, x) for i, x in enumerate(b) if x > 0x7F] == []
