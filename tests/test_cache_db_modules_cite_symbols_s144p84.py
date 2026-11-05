"""RM-1357: the cache / DB reader modules cite their neighbours by symbol.

core/liveclient_cache.py, riot_api_cache.py, metrics_cache.py, match_db.py,
session_hygiene.py and self_cast_log.py carried `<file>.py:<line>` anchors
into decision_detector, vision_tracker, _base_coach, rofl_archive, _loop,
performance_tracker, ds_matchdb_mcp_server, duration_winrate and
rewind_scraper. Several had drifted (`rofl_archive.py:611` is no longer
`extract_stats`, which now sits far below it), and the match_db.save_match
docstring still said no caller reads the returned bool although RM-904 made
performance_tracker read it. The prose now names the symbol; these guards keep
it that way and pin that every cited symbol still exists.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "core/liveclient_cache.py",
    "core/riot_api_cache.py",
    "core/metrics_cache.py",
    "core/match_db.py",
    "core/session_hygiene.py",
    "core/self_cast_log.py",
)

# `vision_tracker.py:279`, `file.py:105,603-617`, a bare `at :943`,
# `lines 12`.
_LINE_CITE = re.compile(
    r"[A-Za-z_/.]+\.(?:py|js|json):\d+"
    r"|\bat ``?:\d+|\bat :\d+|\bto :\d+"
    r"|\band :\d+"
    r"|\blines? \d{2,}"
)


@pytest.mark.parametrize("rel", MODULES)
def test_module_cites_no_file_line_numbers(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert _LINE_CITE.findall(text) == [], "cite a symbol, not a line number"


def test_line_cite_pattern_catches_the_old_forms():
    for old in (
        "because core/decision_detector.py:830 and",
        "core/vision_tracker.py:279 hand age_s back",
        "(the loosest is 12.0s at coaches/_base_coach.py:689).",
        "`core/rofl_archive.py:611 extract_stats`",
        "(app/_loop.py:75-79), so _task",
        "(performance_tracker.py:415 and :477 discard it).",
        "`tools/ds_matchdb_mcp_server.py:342` does clamp",
        "(core/duration_winrate.py:57-64) so tests",
        "scripts/rewind_scraper.py:452 stores them in",
    ):
        assert _LINE_CITE.search(old), old


@pytest.mark.parametrize(
    "rel, needle",
    [
        ("core/decision_detector.py", "def _fetch_snapshot"),
        ("core/vision_tracker.py", "def _fetch_snapshot"),
        ("game_reader/poller.py", "RELAY_MAX_AGE_S = 12.0"),
        ("coaches/_base_coach.py", "def _fetch_game_data"),
        ("core/rofl_archive.py", "def extract_stats"),
        ("app/_loop.py", "def spawn_task"),
        ("performance_tracker.py", "def save_rating"),
        ("performance_tracker.py", "def _tft_db_write"),
        ("tools/ds_matchdb_mcp_server.py", "def tool_match_recent"),
        ("core/duration_winrate.py", "def _open_ro"),
        ("scripts/rewind_scraper.py", "def parse_participant"),
    ],
)
def test_every_symbol_the_modules_cite_still_exists(rel, needle):
    assert needle in (ROOT / rel).read_text(encoding="utf-8"), f"{rel} lost {needle}"


@pytest.mark.parametrize(
    "rel, name",
    [
        ("core/liveclient_cache.py", "_fetch_snapshot"),
        ("core/liveclient_cache.py", "RELAY_MAX_AGE_S"),
        ("core/liveclient_cache.py", "_fetch_game_data"),
        ("core/riot_api_cache.py", "extract_stats"),
        ("core/metrics_cache.py", "AppLoop.spawn_task"),
        ("core/match_db.py", "save_rating"),
        ("core/match_db.py", "_tft_db_write"),
        ("core/match_db.py", "tool_match_recent"),
        ("core/session_hygiene.py", "_open_ro"),
        ("core/self_cast_log.py", "parse_participant"),
    ],
)
def test_prose_still_names_the_symbol(rel, name):
    assert name in (ROOT / rel).read_text(encoding="utf-8")


def test_save_match_docstring_no_longer_claims_no_caller_reads_the_bool():
    text = (ROOT / "core/match_db.py").read_text(encoding="utf-8")
    assert "no caller in the tree" not in text
    perf = (ROOT / "performance_tracker.py").read_text(encoding="utf-8")
    assert "is not False" in perf, "the RM-904 reader the docstring names is gone"
