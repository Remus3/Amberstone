"""Round 27 - dashboard KDA streaks strip."""
from __future__ import annotations

from pathlib import Path


def test_html_contains_streaks_scaffold() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="adapt-streaks"' in html
    assert 'id="streaks-hot"' in html
    assert 'id="streaks-cold"' in html
    assert "KDA streaks" in html


def test_js_binds_streak_elements() -> None:
    js = Path("web/js/dashboard.js").read_text(encoding="utf-8")
    assert 'streaksHot: el("streaks-hot")' in js
    assert 'streaksCold: el("streaks-cold")' in js


def test_js_hits_trending_endpoint() -> None:
    js = Path("web/js/dashboard.js").read_text(encoding="utf-8")
    assert "/api/trending" in js
    assert "fetchTrending" in js
    # Streaks fetch must fire from the adaptation flow.
    assert "fetchTrending(modeTag)" in js


def test_js_dedupes_trending_fetch() -> None:
    """Must not hammer /api/trending on every state tick; dedupe by mode
    and a short staleness window."""
    js = Path("web/js/dashboard.js").read_text(encoding="utf-8")
    assert "TRENDS.lastMode" in js
    assert "30000" in js  # 30s freshness window


def test_css_streak_rules_present() -> None:
    css = Path("web/css/dashboard.css").read_text(encoding="utf-8")
    assert "#adapt-streaks" in css
    assert ".streak-row.hot" in css
    assert ".streak-row.cold" in css
