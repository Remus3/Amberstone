"""RM-1097: the two GT_SOURCE_ORDER copies stay one order.

The most-trusted-first ground-truth source order is defined twice:
tft/rounds/ground_truth.py (read by final_boards, lobby_rows and
tft/rounds/accuracy.py) and tft/engine/milestones.py (read by
_local_gt_board and by dashboard/routes_tft.py). The engine keeps its own
copy on purpose: importing tft.rounds.schema would run tft/rounds/__init__.py,
which loads the store and its writer, and the engine reads the store only
through the getter it is handed. So the copies stay, and this guard pins
them: a reorder in one copy would make the dashboard board, the engine record
and lobby_rows / accuracy pick different sources for the same player.

Pins:
1. the two tuples are equal (same members, same order);
2. their members are exactly schema.GT_SOURCES, each once;
3. GT_SOURCE_BY_RM616 maps only into schema.GT_SOURCES;
4. no third module-level GT_SOURCE_ORDER exists under tft/ (a new copy must
   join this guard), anchored on the two known definitions so an empty walk
   cannot pass.

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import ast
from pathlib import Path

from tft.engine import milestones
from tft.rounds import ground_truth, schema

REPO_ROOT = Path(__file__).resolve().parent.parent
TFT_DIR = REPO_ROOT / "tft"
KNOWN_DEFINERS = {"tft/engine/milestones.py", "tft/rounds/ground_truth.py"}


def test_the_two_copies_are_one_order():
    assert milestones.GT_SOURCE_ORDER == ground_truth.GT_SOURCE_ORDER


def test_the_order_ranks_every_schema_source_once():
    for order in (milestones.GT_SOURCE_ORDER, ground_truth.GT_SOURCE_ORDER):
        assert isinstance(order, tuple)
        assert len(order) == len(set(order))
        assert set(order) == set(schema.GT_SOURCES)


def test_rm616_routes_map_into_schema_sources():
    assert ground_truth.GT_SOURCE_BY_RM616
    assert set(ground_truth.GT_SOURCE_BY_RM616.values()) <= set(schema.GT_SOURCES)


def _module_level_definers(name: str) -> set:
    found = set()
    for path in sorted(TFT_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                found.add(path.relative_to(REPO_ROOT).as_posix())
    return found


def test_no_third_copy_of_the_order_under_tft():
    assert _module_level_definers("GT_SOURCE_ORDER") == KNOWN_DEFINERS
