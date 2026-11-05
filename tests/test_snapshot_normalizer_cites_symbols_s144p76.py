"""RM-1349: game_reader/snapshot_normalizer.py cites its neighbours by symbol.

The module prose carried `file.py:<line>` / `:<line>` anchors into poller.py,
coaches/aram_coach.py, core/district_fusion.py and dashboard/_liveclient.py.
A line number is a measurement at one commit and these had drifted (the
`_liveclient.py` anchor no longer parsed turret names at all). The prose now
names the symbol; these guards keep it that way and pin that each cited symbol
still exists where the prose says it does.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "game_reader" / "snapshot_normalizer.py"

# `name.py:123`, `name.py:12-34`, `poller.py:233-234`, a bare `, :457)` anchor,
# `:277-280` ranges, `lines 12`.
_LINE_CITE = re.compile(
    r"[A-Za-z_/.]+\.(?:py|js):\d+"
    r"|\(:\d+|\+ :\d+|\bat :\d+|, :\d+\)|\bto :\d+"
    r"|\(:\d+-\d+\)|\blines? \d{2,}"
)


def test_module_cites_no_file_line_numbers():
    text = MODULE.read_text(encoding="utf-8")
    assert _LINE_CITE.findall(text) == [], "cite a symbol, not a line number"


def test_line_cite_pattern_catches_the_old_forms():
    for old in (
        "game_reader/poller.py:277-280",
        "poller.py:233-234",
        "core/district_fusion.py:85",
        "dashboard/_liveclient.py:348-350",
        "(`cs_per_min`, :457)",
        "`_get` moved to :277-280",
    ):
        assert _LINE_CITE.search(old), old


@pytest.mark.parametrize(
    "rel, needle",
    [
        ("game_reader/poller.py", "def _get(self, url):"),
        ("game_reader/poller.py", "def _read_game_fallback(self):"),
        ("game_reader/poller.py", "def _normalise_events("),
        ("core/district_fusion.py", "_SIDE_BY_TOKEN = {"),
        ("core/district_fusion.py", "def _structure_killer_team("),
        ("coaches/aram_coach.py", "My runes: {my_runes}"),
    ],
)
def test_every_symbol_the_module_cites_still_exists(rel, needle):
    assert needle in (ROOT / rel).read_text(encoding="utf-8"), f"{rel} lost {needle}"


@pytest.mark.parametrize(
    "name",
    [
        "_PollerMixin._get", "_read_game_fallback", "_normalise_events",
        "_SIDE_BY_TOKEN", "_structure_killer_team", "My runes:",
    ],
)
def test_prose_still_names_the_symbol(name):
    assert name in MODULE.read_text(encoding="utf-8")
