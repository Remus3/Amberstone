"""RM-1352: core/precomputed_replay_narrative.py cites its neighbours by symbol.

The module prose carried nine `file.py:<line>` anchors into replay_coach.py,
post_game_rubric.py and obj_participation.py. A line number is a measurement
at one commit and they had drifted (`compute_role_grade` is not at
`post_game_rubric.py:378`, `_load_match` is not at `replay_coach.py:55`). The
prose now names the symbol; these guards keep it that way and pin that each
cited symbol still exists where the prose says it does.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "core" / "precomputed_replay_narrative.py"

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
        "(replay_coach.py:55-74)",
        "(post_game_rubric.py:378) for",
        "column model (obj_participation.py:63-83) for the",
        "(obj_participation.py:157), which",
        "(post_game_rubric.py:422-436). We do NOT",
    ):
        assert _LINE_CITE.search(old), old


@pytest.mark.parametrize(
    "rel, needle",
    [
        ("coaches/replay_coach.py", "def _load_match("),
        ("core/post_game_rubric.py", "def compute_role_grade("),
        ("core/post_game_rubric.py", '"components": components'),
        ("core/obj_participation.py", "_OBJ_COLUMNS = ("),
        ("core/obj_participation.py", "_ROW_SUM_SQL = "),
        ("core/obj_participation.py", "def compute_obj_participation("),
    ],
)
def test_every_symbol_the_module_cites_still_exists(rel, needle):
    assert needle in (ROOT / rel).read_text(encoding="utf-8"), f"{rel} lost {needle}"


@pytest.mark.parametrize(
    "name",
    [
        "coaches/replay_coach._load_match",
        "compute_role_grade",
        "_OBJ_COLUMNS",
        "_ROW_SUM_SQL",
    ],
)
def test_prose_still_names_the_symbol(name):
    assert name in MODULE.read_text(encoding="utf-8")
