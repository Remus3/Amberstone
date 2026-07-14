"""
tests/snapshot_panels/test_item_value_diff.py

Contract tests for the R117 F1 team item-value differential
(web/js/lib/item_value.js + the repurposed gold-diff bar in
web/js/panels/map_state.js).

The economy lens: enemy GOLD is activePlayer-only over the Live Client API,
but allPlayers[].items is public for all 10, so summing each player's on-board
item gold-worth (ITEM_COSTS) and diffing ally-vs-enemy is the one economy
signal computable client-side. The pure arithmetic is exercised by the node
suite (web/js/lib/item_value.test.mjs, run with `node --test`); these pytest
contract tests pin the wiring that CI enforces:

  - the helper module exists + exports its public surface + is ASCII-only,
  - map_state.js imports it, feeds ITEM_COSTS, and calls renderItemValueDiff,
  - the dormant p.team_gold_diff read is gone (the bar is no longer wired to a
    field nothing produces live),
  - the index.html bar is relabeled honestly ("item value", not "gold").

Run:
    pytest tests/snapshot_panels/test_item_value_diff.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
LIB_JS = ROOT / "web" / "js" / "lib" / "item_value.js"
LIB_TEST = ROOT / "web" / "js" / "lib" / "item_value.test.mjs"
MAP_STATE_JS = ROOT / "web" / "js" / "panels" / "map_state.js"
INDEX_HTML = ROOT / "web" / "index.html"


@pytest.fixture(scope="module")
def lib_js() -> str:
    return LIB_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def map_state_js() -> str:
    return MAP_STATE_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index_html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_helper_module_exists():
    assert LIB_JS.is_file(), "web/js/lib/item_value.js missing"
    assert LIB_TEST.is_file(), "web/js/lib/item_value.test.mjs missing"


def test_helper_exports_public_surface(lib_js: str):
    for sym in ("teamItemValueDiff", "_resolveMyTeam", "_playerItemValue"):
        assert f"export function {sym}" in lib_js, f"item_value.js must export {sym}"


def test_helper_is_failsoft(lib_js: str):
    # null-on-missing keeps the bar hidden exactly like the pre-R117 dormant
    # behavior; unknown-cost ids must not fabricate value.
    assert "return null" in lib_js
    assert "itemCosts.ready" in lib_js, "must gate on ITEM_COSTS.ready (no premature 0-diff)"
    assert "itemID || it.itemId" in lib_js, "must honor the itemID/itemId alias"


@pytest.mark.parametrize("path", [LIB_JS, LIB_TEST])
def test_new_files_are_ascii(path: Path):
    raw = path.read_bytes()
    non_ascii = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
    assert not non_ascii, f"{path.name} has non-ASCII bytes: {non_ascii[:5]}"


def test_map_state_imports_and_calls_helper(map_state_js: str):
    assert "from '../lib/item_value.js'" in map_state_js
    assert "teamItemValueDiff" in map_state_js
    assert "ITEM_COSTS" in map_state_js, "must feed ITEM_COSTS to the diff"
    assert "renderItemValueDiff" in map_state_js
    assert "renderItemValueDiff(p)" in map_state_js, "render loop must call the item-value bar"


def test_dormant_gold_diff_field_read_is_gone(map_state_js: str):
    # The bar was wired to p.team_gold_diff, a field with no live producer.
    # After R117 the bar sources item value, so that dead read must be gone.
    assert "p.team_gold_diff" not in map_state_js
    assert "function renderGoldDiff" not in map_state_js


def test_index_html_label_is_honest(index_html: str):
    # Item value is an economy proxy, not literal gold-in-hand - label it truthfully.
    assert "</span> item value</div>" in index_html
    assert "</span> gold</div>" not in index_html
    assert 'id="gold-diff-val"' in index_html
