"""Post Game Review quick review speaks the current item system (RM-978).

The "Gold deficit" row's tooltip (dashboard/builders_last_match.py
_compute_wrong_team_from_enriched) read "That's roughly an extra completed
mythic + finisher across the team". Mythic items left League in the 2024
pre-season item rework, so the line named an item class that no longer
exists. The row fires at a gap of 8000g or more and never for Arena (the
builder returns before it), and the dearest standard legendary on maps 11
and 12 costs 3500g (data/daemon_slayer/16.21.1/items.json, Rabadon's
Deathcap and Infinity Edge; map 12 also lists three 6000g 22xxxx-id mode
specials), so "more than two completed legendary items" holds at the
threshold and above.

Pinned here:
- the gold-deficit why names legendary items and never "mythic";
- no string constant the builder module can emit says "mythic" (comments
  and docstrings are not rendered and are not read);
- no ui_mock fixture carries "mythic" text;
- the Brawl ui_mock fixture's quick_review.wrong_team is exactly what the
  builder computes from that fixture's own enriched block, so the fixture
  cannot keep a stale copy of builder text.

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

from dashboard.builders_last_match import _compute_wrong_team_from_enriched

ROOT = Path(__file__).resolve().parent.parent
BUILDER = ROOT / "dashboard" / "builders_last_match.py"
UI_MOCK = ROOT / "web" / "data" / "ui_mock"
BRAWL = UI_MOCK / "last_match_brawl.json"


def _enriched(my_gold: int, opp_gold: int, *, queue_id: int = 420,
              game_mode: str = "CLASSIC") -> dict:
    # Synthetic two-team payload; five players a side share the team gold.
    def side(tid: int, gold: int) -> list[dict]:
        return [{"team_id": tid, "kills": 5, "deaths": 5, "gold": gold // 5}
                for _ in range(5)]
    return {
        "team_id": 100,
        "queue_id": queue_id,
        "game_mode": game_mode,
        "teams": [{"team_id": 100}, {"team_id": 200}],
        "roster": side(100, my_gold) + side(200, opp_gold),
    }


def _gold_row(out: list[dict]) -> dict:
    rows = [r for r in out if r["text"].startswith("Gold deficit")]
    assert len(rows) == 1, out
    return rows[0]


def test_gold_deficit_why_names_legendary_items_not_mythic():
    row = _gold_row(_compute_wrong_team_from_enriched(
        _enriched(50000, 58000), 2, 3, 4))
    assert row["text"] == "Gold deficit -8k"
    assert "mythic" not in row["why"].lower(), row["why"]
    assert "more than two completed legendary items" in row["why"], row["why"]
    assert row["why"].startswith("Enemy ended 8000g ahead (58.0k vs 50.0k)."), row["why"]


def test_gold_deficit_row_fires_from_the_8000g_threshold_only():
    below = _compute_wrong_team_from_enriched(_enriched(50000, 57995), 2, 3, 4)
    assert not [r for r in below if r["text"].startswith("Gold deficit")], below


def test_gold_deficit_wording_is_mode_independent():
    for queue_id, mode in ((450, "ARAM"), (900, "URF"), (2400, "KIWI")):
        row = _gold_row(_compute_wrong_team_from_enriched(
            _enriched(40000, 60000, queue_id=queue_id, game_mode=mode), 2, 3, 4))
        assert "mythic" not in row["why"].lower(), (mode, row["why"])


def test_builder_module_emits_no_mythic_string():
    tree = ast.parse(BUILDER.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(
                    getattr(body[0], "value", None), ast.Constant):
                docstrings.add(id(body[0].value))
    hits = [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in docstrings and "mythic" in node.value.lower()
    ]
    # Positive control: the walk does see the builder's rendered strings.
    seen = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and "across the team" in node.value
    ]
    assert seen, "string-constant walk found no gold-deficit text"
    assert not hits, hits


def test_no_ui_mock_fixture_carries_mythic_text():
    fixtures = sorted(UI_MOCK.glob("*.json"))
    assert len(fixtures) >= 10, fixtures
    hits = [p.name for p in fixtures
            if "mythic" in p.read_text(encoding="utf-8").lower()]
    assert not hits, hits


def test_brawl_fixture_wrong_team_is_the_builder_output():
    data = json.loads(BRAWL.read_text(encoding="utf-8"))
    m = data["match"]
    recomputed = _compute_wrong_team_from_enriched(
        m["enriched"], m["kills"], m["deaths"], m["assists"])
    assert data["quick_review"]["wrong_team"] == recomputed
    # The fixture exercises the row this file pins.
    assert any(r["text"].startswith("Gold deficit") for r in recomputed)
