"""RM-1361: ten more modules cite their neighbours by symbol.

tft_roll_odds, tft_live_analysis, lcu_pregame, lcu_postgame_collector,
draft_log, mode_capabilities, replay_history, build_planner situational and
replan, tft_coach and enemy_stats carried `<file>.py:<line>` anchors that had
drifted: `coaches/tft_pbe_coach.py:149-151` pointed at a file RM-292 (b)
deleted, `lcu_rune_writer.py:879` at code that no longer reads the spell wire
fields inline, `tft_coach_engine.py:442-452` at a Duo lobby block instead of
the roll-odds lines. The prose now names the symbol; this guard keeps it that
way and pins that every cited symbol still exists. Port numbers such as
`:8888` are not line cites and are left alone.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "tft/tft_roll_odds.py",
    "tft/tft_live_analysis.py",
    "lcu/lcu_pregame.py",
    "lcu/lcu_postgame_collector.py",
    "lcu/draft_log.py",
    "core/mode_capabilities.py",
    "core/replay_history.py",
    "core/build_planner/situational.py",
    "core/build_planner/replan.py",
    "coaches/tft_coach.py",
    "coach_integration/enemy_stats.py",
)

_LINE_CITE = re.compile(r"[A-Za-z0-9_/.]+\.(?:py|js|css|json):\d+")


@pytest.mark.parametrize("rel", MODULES)
def test_module_cites_no_file_line_numbers(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert _LINE_CITE.findall(text) == [], "cite a symbol, not a line number"


def test_line_cite_pattern_catches_the_old_forms():
    for old in (
        "prompt TEXT (tft/tft_coach_engine.py:442-452) and letting",
        "# core/tft_worker.py:310-312 and coaches/tft_pbe_coach.py:149-151 call",
        "`lcu/lcu_rune_writer.py:879` with its own `or 0` guard",
        "path at app/_game_lifecycle.py:146 only calls",
        "(lib/rewind_live_writer.py:85 DB_PATH",
        "MODE_SR (core/game_snapshot.py:80), which would",
        "`scripts/rewind_scraper.py:567` maps only `itemId`.",
        "stub at core/build_planner/scoring.py:321. Given",
        "(scoring.py:324\n forces",
        "symbol entirely: app/_game_lifecycle.py:315 `_try_read_api_key`",
        "preset table at coaches/sr_draft_profile.py:71).",
    ):
        assert _LINE_CITE.search(old), old
    assert _LINE_CITE.search("served on :8888 by dashboard/_dispatch.py") is None


@pytest.mark.parametrize(
    "rel, needle",
    [
        ("tft/tft_coach_engine.py", "Roll odds at Lv"),
        ("tft/tft_coach_engine.py", "def _build_prompt"),
        ("core/tft_worker.py", "live.notify_round(state)"),
        ("lcu/lcu_rune_writer.py", "def _sync_spells"),
        ("lcu/lcu_rune_writer.py", "def _spell_id"),
        ("lcu/lcu_postgame_collector.py", "def trigger"),
        ("app/_game_lifecycle.py", "_pgc.trigger("),
        ("app/_game_lifecycle.py", "def _try_read_api_key"),
        ("lib/rewind_live_writer.py", "DB_PATH ="),
        ("scripts/rewind_catchup.py", "record_hydrated"),
        ("core/game_snapshot.py", "def mode_from_game_mode_string"),
        ("scripts/rewind_scraper.py", "def parse_event"),
        ("scripts/rewind_scraper.py", '"item_id":        ev.get("itemId")'),
        ("core/build_planner/scoring.py", "def score_build"),
        ("core/build_planner/scoring.py",
         "from core.build_planner.situational import situational_fit"),
        ("coaches/sr_draft_profile.py", "_FALLBACK_PRESETS"),
    ],
)
def test_every_symbol_the_modules_cite_still_exists(rel, needle):
    assert needle in (ROOT / rel).read_text(encoding="utf-8"), f"{rel} lost {needle}"


@pytest.mark.parametrize(
    "rel, name",
    [
        ("tft/tft_roll_odds.py", "tft_coach_engine._build_prompt"),
        ("tft/tft_live_analysis.py", "TftWorker poll loop"),
        ("lcu/lcu_pregame.py", "RuneWriter._sync_spells"),
        ("lcu/lcu_pregame.py", "_spell_id"),
        ("lcu/lcu_postgame_collector.py", "_pgc.trigger"),
        ("lcu/draft_log.py", "DB_PATH"),
        ("core/mode_capabilities.py", "mode_from_game_mode_string in core/game_snapshot.py"),
        ("core/replay_history.py", "`parse_event` in scripts/rewind_scraper.py"),
        ("core/build_planner/situational.py", "`score_build`"),
        ("core/build_planner/replan.py", "scoring.score_build"),
        ("coaches/tft_coach.py", "`_try_read_api_key` in app/_game_lifecycle.py"),
        ("coach_integration/enemy_stats.py", "_FALLBACK_PRESETS"),
    ],
)
def test_prose_still_names_the_symbol(rel, name):
    assert name in (ROOT / rel).read_text(encoding="utf-8")


def test_the_deleted_pbe_coach_stays_deleted_and_uncited():
    """tft_live_analysis once pointed at coaches/tft_pbe_coach.py, which
    RM-292 (b) retired; no live module may cite it as a caller again."""
    assert not (ROOT / "coaches" / "tft_pbe_coach.py").exists()
    text = (ROOT / "tft" / "tft_live_analysis.py").read_text(encoding="utf-8")
    assert "tft_pbe_coach" not in text
