"""Contract tests for the Draft Elo chip panel (UX wave 2)."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
JS_PATH = ROOT / "web" / "js" / "panels" / "draft_elo.js"
CSS_PATH = ROOT / "web" / "css" / "panels" / "draft_elo.css"
DASHBOARD_CSS = ROOT / "web" / "css" / "dashboard.css"
INDEX_HTML = ROOT / "web" / "index.html"
ACTIVE_MATCH_JS = ROOT / "web" / "js" / "panels" / "active_match.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_files_exist():
    assert JS_PATH.exists()
    assert CSS_PATH.exists()
    assert JS_PATH.stat().st_size > 0
    assert CSS_PATH.stat().st_size > 0


def test_draft_elo_exports_public_api():
    src = _read(JS_PATH)
    assert "export function renderDraftElo" in src
    assert "export function fetchDraftElo" in src
    assert "export function getCachedDraftElo" in src
    assert "export function _resetDraftElo" in src
    assert "export const __test" in src


def test_dashboard_css_imports_draft_elo():
    css = _read(DASHBOARD_CSS)
    assert "@import './panels/draft_elo.css';" in css


def test_index_html_has_mount_point():
    html = _read(INDEX_HTML)
    assert 'id="am-draft-elo"' in html
    # Inside the BUILD pane. B-OVL-4 (2026-09-01) re-parented the chip out of
    # .am-pane-head (hidden in the overlay, so the chip painted 0x0 in-game)
    # into the .am-pane-chips row - still under .am-pane-build, which is what
    # this assertion has always actually pinned.
    pane_start = html.find('class="am-pane am-pane-build"')
    assert pane_start >= 0
    mount_pos = html.find('id="am-draft-elo"', pane_start)
    assert mount_pos > 0


def test_active_match_js_imports_draft_elo():
    src = _read(ACTIVE_MATCH_JS)
    assert "from './draft_elo.js'" in src
    assert "renderDraftElo" in src
    assert "fetchDraftElo" in src
    assert "getCachedDraftElo" in src
    assert "_renderDraftEloFromCtx" in src


def test_emits_expected_dom_classes():
    src = _read(JS_PATH)
    css = _read(CSS_PATH)
    for cls in ["de-label", "de-wr", "de-score", "de-sample", "de-empty"]:
        assert cls in src, f"draft_elo.js does not emit {cls!r}"
    for cls in [".draft-elo-chip", ".de-label", ".de-wr", ".de-score",
                ".de-sample-low", ".de-sample-mid", ".de-sample-high"]:
        assert cls in css, f"draft_elo.css does not style {cls!r}"


def test_wr_bands_match_personal_vs_convention():
    """Red <0.42, amber 0.42..0.58, green >0.58."""
    src = _read(JS_PATH)
    # The threshold numbers should appear explicitly.
    assert "0.42" in src
    assert "0.58" in src


def test_sig_dedup_present():
    src = _read(JS_PATH)
    assert "_signature" in src
    assert "_DE_SIG" in src
    assert re.search(r"_DE_SIG\[\w+\]\s*===\s*sig", src) is not None


def test_cache_ttl_matches_backend():
    """Cache TTL is 5 minutes in ms (matches backend cache)."""
    src = _read(JS_PATH)
    # The literal expression in the JS is "5 * 60 * 1000".
    assert re.search(r"_DE_TTL_MS\s*=\s*5\s*\*\s*60\s*\*\s*1000", src) is not None


def test_no_em_dashes_or_smart_quotes():
    for p in (JS_PATH, CSS_PATH):
        text = _read(p)
        for ch in (chr(0x2013), chr(0x2014), chr(0x2018), chr(0x2019), chr(0x201C), chr(0x201D)):
            assert ch not in text, f"non-ASCII char {ch!r} in {p}"
