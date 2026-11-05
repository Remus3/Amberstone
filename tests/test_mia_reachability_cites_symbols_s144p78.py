"""RM-1351: core/mia_reachability.py cites its neighbours by symbol.

The module prose carried ten `file.py:<line>` anchors into vision_tracker.py,
minimap_districts.py, league_settings.py, _state_builder.py, game_snapshot.py
and laning_cv_overrides.py (plus `sr.json:4`). A line number is a measurement
at one commit and several had drifted (`_state_builder.py:119` no longer holds
the mode-key mapping; `league_settings.py:142` is mid-dataclass). The prose now
names the symbol; these guards keep it that way and pin that each cited symbol
still exists where the prose says it does.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "core" / "mia_reachability.py"

# `name.py:123`, `name.py:12-34`, `sr.json:4`, `lines 12`.
_LINE_CITE = re.compile(
    r"[A-Za-z_/.]+\.(?:py|js|json):\d+"
    r"|\(:\d+|\bat :\d+|, :\d+\)|\bto :\d+"
    r"|\blines? \d{2,}"
)


def test_module_cites_no_file_line_numbers():
    text = MODULE.read_text(encoding="utf-8")
    assert _LINE_CITE.findall(text) == [], "cite a symbol, not a line number"


def test_line_cite_pattern_catches_the_old_forms():
    for old in (
        "vision_tracker.py:376-388",
        "core/vision_tracker.py:55-61",
        "(dashboard/_state_builder.py:119)",
        "config/minimap_grids/sr.json:4",
        "core/laning_cv_overrides.py:50 - shorter",
    ):
        assert _LINE_CITE.search(old), old


@pytest.mark.parametrize(
    "rel, needle",
    [
        ("core/vision_tracker.py", "def _sr_zone("),
        ("core/vision_tracker.py", "def state(self)"),
        ("core/vision_tracker.py", '"last_seen_pos":'),
        ("core/vision_tracker.py", "missing_for_s = max(0.0, game_time"),
        ("core/minimap_districts.py", "def district_of("),
        ("core/league_settings.py", "def minimap_rect_payload("),
        ("core/league_settings.py", '"flip": rect.flip'),
        ("dashboard/_state_builder.py", "def resolve_mode_key("),
        ("core/game_snapshot.py", 'MODE_SR     = "SR"'),
        ("core/laning_cv_overrides.py", "MISS_THRESHOLD_S"),
        ("config/minimap_grids/sr.json", '"id": "blue_base"'),
    ],
)
def test_every_symbol_the_module_cites_still_exists(rel, needle):
    assert needle in (ROOT / rel).read_text(encoding="utf-8"), f"{rel} lost {needle}"


@pytest.mark.parametrize(
    "name",
    [
        "VisionTracker.state", "_sr_zone", "district_of",
        "minimap_rect_payload", "resolve_mode_key", "MODE_SR",
        "MISS_THRESHOLD_S", "minimap_grids/sr.json",
    ],
)
def test_prose_still_names_the_symbol(name):
    assert name in MODULE.read_text(encoding="utf-8")
