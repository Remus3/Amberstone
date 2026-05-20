"""Contract tests for the Ward Coverage Heat Strip panel.

Mirrors the spike-curve / cd-ledger contract pattern - JS exports, CSS
import wired, mount point in index.html, active_match dispatcher import,
DOM class consistency, fail-soft, sig dedup.

Backend route is covered by tests/test_routes_ward_heat.py + the
producer wire by tests/test_ward_producer.py +
tests/test_liveclient_cache_listeners.py.
"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
JS_PATH = ROOT / "web" / "js" / "panels" / "ward_heat.js"
CSS_PATH = ROOT / "web" / "css" / "panels" / "ward_heat.css"
DASHBOARD_CSS = ROOT / "web" / "css" / "dashboard.css"
INDEX_HTML = ROOT / "web" / "index.html"
ACTIVE_MATCH_JS = ROOT / "web" / "js" / "panels" / "active_match.js"
BACKEND_ROUTE = ROOT / "dashboard" / "routes_ward_heat.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_ward_heat_js_exists():
    assert JS_PATH.exists(), f"ward_heat.js missing at {JS_PATH}"
    assert JS_PATH.stat().st_size > 0


def test_ward_heat_css_exists():
    assert CSS_PATH.exists(), f"ward_heat.css missing at {CSS_PATH}"
    assert CSS_PATH.stat().st_size > 0


def test_ward_heat_exports_public_api():
    src = _read(JS_PATH)
    assert "export function renderWardHeat" in src
    assert "export function fetchWardHeat" in src
    assert "export function getCachedWardHeat" in src
    assert "export function _resetWardHeat" in src
    assert "export const __test" in src


def test_dashboard_css_imports_ward_heat():
    css = _read(DASHBOARD_CSS)
    assert "@import './panels/ward_heat.css';" in css


def test_index_html_has_mount_point():
    """Mount point #am-ward-heat must sit inside the MAP pane, between
    the head and the body."""
    html = _read(INDEX_HTML)
    assert 'id="am-ward-heat"' in html
    pane_start = html.find('class="am-pane am-pane-map"')
    assert pane_start >= 0, "am-pane-map not found"
    ward_pos = html.find('id="am-ward-heat"', pane_start)
    map_body_pos = html.find('id="am-map-body"', pane_start)
    assert ward_pos > 0
    assert map_body_pos > ward_pos, (
        "am-ward-heat must appear BEFORE am-map-body inside am-pane-map"
    )


def test_active_match_js_imports_ward_heat():
    src = _read(ACTIVE_MATCH_JS)
    assert "from './ward_heat.js'" in src
    assert "renderWardHeat" in src
    assert "fetchWardHeat" in src
    assert "getCachedWardHeat" in src
    assert "_renderWardHeatTick" in src


def test_emits_expected_dom_classes():
    src = _read(JS_PATH)
    css = _read(CSS_PATH)
    # Cells + rows + side labels rendered by the JS (the per-side
    # variant classes are templated as wh-${sideKey} so we test the
    # base prefix here).
    for cls in ["wh-row", "wh-side", "wh-cell", "wh-lane", "wh-count",
                "wh-empty"]:
        assert cls in src, f"ward_heat.js does not emit {cls!r}"
    assert "wh-${sideKey}" in src, "per-side variant template missing"
    # CSS styles the container + per-side + states.
    assert ".ward-heat-container" in css
    assert ".wh-cell" in css
    assert ".wh-row" in css
    assert ".wh-empty" in css
    assert ".wh-ally" in css
    assert ".wh-enemy" in css


def test_palette_matches_brief():
    """Ally blue base + enemy red base + uncovered red outline."""
    src = _read(JS_PATH)
    assert "_ALLY_BASE" in src
    assert "_ENEMY_BASE" in src
    assert "_UNCOVERED" in src
    # Red outline on uncovered cells.
    assert "#ff3030" in src or "_UNCOVERED" in src


def test_signature_dedup_present():
    src = _read(JS_PATH)
    assert "_signature" in src
    assert "_WH_SIG" in src
    # Sig short-circuit guard.
    assert re.search(r"_WH_SIG\[\w+\]\s*===\s*sig", src) is not None


def test_failsoft_on_null_payload():
    """Null / not-ok payload must render an empty placeholder."""
    src = _read(JS_PATH)
    assert "wh-empty" in src
    assert "no wards yet" in src


def test_lanes_constant_matches_backend():
    """The four-lane sequence rendered by the JS must match the
    canonical backend lane set top/jg/mid/bot (the order is the
    L-to-R visual order)."""
    src = _read(JS_PATH)
    m = re.search(r"_LANES\s*=\s*\[([^\]]+)\]", src)
    assert m, "_LANES constant not found"
    lanes = [tok.strip().strip('"\'') for tok in m.group(1).split(",") if tok.strip()]
    assert lanes == ["top", "jg", "mid", "bot"], (
        f"ward_heat _LANES must be [top,jg,mid,bot]; got {lanes}"
    )


def test_window_s_matches_brief():
    src = _read(JS_PATH)
    m = re.search(r"_WINDOW_S\s*=\s*(\d+)", src)
    assert m
    assert int(m.group(1)) == 90, "Rolling window must default to 90s per backend"


def test_polling_interval_is_polite():
    """Backend caches 2s; client polls 4s to keep load light."""
    src = _read(JS_PATH)
    m = re.search(r"_FETCH_INTERVAL_MS\s*=\s*(\d+)", src)
    assert m
    interval = int(m.group(1))
    assert 2000 <= interval <= 10000, (
        f"fetch interval should be 2-10s; got {interval}ms"
    )


def test_backend_route_exists():
    assert BACKEND_ROUTE.exists()


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text."""
    for p in (JS_PATH, CSS_PATH):
        text = _read(p)
        for ch in ("–", "—", "‘", "’", "“", "”"):
            assert ch not in text, f"non-ASCII char {ch!r} in {p}"
