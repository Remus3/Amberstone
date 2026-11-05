"""RM-1355: the minimap / ZOI modules cite their neighbours by symbol.

core/minimap_blob_detect.py, minimap_districts.py, minimap_identity.py,
minimap_presence.py, zoi_capability.py, zoi_field.py, zoi_influence.py and
district_fusion.py carried `<file>.py:<line>` anchors into vision_tracker,
minimap_geometry, zoi_influence, champion_movespeed, event_callouts,
_liveclient and _state_builder. Several had already drifted (for example
`zoi_influence.py:263` no longer pointed at a team-colour convention). The
prose now names the symbol; these guards keep it that way and pin that every
cited symbol still exists.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "core/minimap_blob_detect.py",
    "core/minimap_districts.py",
    "core/minimap_identity.py",
    "core/minimap_presence.py",
    "core/zoi_capability.py",
    "core/zoi_field.py",
    "core/zoi_influence.py",
    "core/district_fusion.py",
)

# `vision_tracker.py:307`, `event_callouts.py:603-617`, `file.py:105,603-617`,
# a bare `at :943`, `lines 12`.
_LINE_CITE = re.compile(
    r"[A-Za-z_/.]+\.(?:py|js|json):\d+"
    r"|\bat ``?:\d+|\bat :\d+|\bto :\d+"
    r"|\blines? \d{2,}"
)


@pytest.mark.parametrize("rel", MODULES)
def test_module_cites_no_file_line_numbers(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert _LINE_CITE.findall(text) == [], "cite a symbol, not a line number"


def test_line_cite_pattern_catches_the_old_forms():
    for old in (
        "(core/vision_tracker.py:307 naming), via the shared",
        "the minimap left (core/minimap_geometry.py:152-155); ``district_of``",
        "as in core/event_callouts.py:105,603-617) or to the one",
        "(mirrors core/event_callouts.py:603-617).",
        "dashboard/_liveclient.py:265-301.",
    ):
        assert _LINE_CITE.search(old), old


@pytest.mark.parametrize(
    "rel, needle",
    [
        ("core/vision_tracker.py", "def _compute_enemies"),
        ("core/vision_tracker.py", 'p.get("championName")'),
        ("core/minimap_geometry.py", "def compute_minimap_rect"),
        ("core/minimap_geometry.py", "want_flip"),
        ("core/zoi_influence.py", "def _action_quadrant"),
        ("core/zoi_influence.py", "def compute_zoi"),
        ("core/zoi_influence.py", '"r_frac"'),
        ("core/champion_movespeed.py", "def _name_keys"),
        ("core/champion_movespeed.py", "def _reset_caches"),
        ("core/event_callouts.py", "_INHIB_LANE_BY_TOKEN"),
        ("core/event_callouts.py", "def _inhib_lane"),
        ("core/minimap_blob_detect.py", "def detect_team_dots"),
        ("dashboard/_liveclient.py", "def liveclient_summary"),
        ("dashboard/_liveclient.py", 'out["players"]'),
        ("dashboard/_liveclient.py", 'out["inhib_events"]'),
        ("dashboard/_liveclient.py", 'out["turret_events"]'),
        ("dashboard/_state_builder.py", 'mode_key in ("sr", "aram")'),
    ],
)
def test_every_symbol_the_modules_cite_still_exists(rel, needle):
    assert needle in (ROOT / rel).read_text(encoding="utf-8"), f"{rel} lost {needle}"


@pytest.mark.parametrize(
    "rel, name",
    [
        ("core/minimap_districts.py", "compute_minimap_rect"),
        ("core/minimap_identity.py", "_name_keys"),
        ("core/minimap_presence.py", "detect_team_dots"),
        ("core/zoi_field.py", "compute_zoi"),
        ("core/district_fusion.py", "_inhib_lane"),
        ("core/district_fusion.py", "liveclient_summary"),
    ],
)
def test_prose_still_names_the_symbol(rel, name):
    assert name in (ROOT / rel).read_text(encoding="utf-8")
