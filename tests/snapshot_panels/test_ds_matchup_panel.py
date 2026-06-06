"""Contract tests for the DS-Matchup champ-select card panel.

Mirrors the ward-heat / ds-profile contract pattern - JS exports, CSS
import wired, mount point in index.html, champ-select dispatcher import +
call, fixture validity, ASCII hygiene.

The backend route (GET /api/ds-matchup) is built + covered by a sibling
slice; this panel is purely additive frontend over that contract.
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
JS_PATH = ROOT / "web" / "js" / "panels" / "ds_matchup.js"
CSS_PATH = ROOT / "web" / "css" / "panels" / "ds_matchup.css"
DASHBOARD_CSS = ROOT / "web" / "css" / "dashboard.css"
INDEX_HTML = ROOT / "web" / "index.html"
CHAMP_SELECT_JS = ROOT / "web" / "js" / "panels" / "champ_select.js"
FIXTURE_PATH = ROOT / "web" / "data" / "ui_mock" / "ds_matchup.json"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_ds_matchup_js_exists():
    assert JS_PATH.exists(), f"ds_matchup.js missing at {JS_PATH}"
    assert JS_PATH.stat().st_size > 0


def test_ds_matchup_css_exists():
    assert CSS_PATH.exists(), f"ds_matchup.css missing at {CSS_PATH}"
    assert CSS_PATH.stat().st_size > 0


def test_ds_matchup_exports_public_api():
    src = _read(JS_PATH)
    assert "export function renderDsMatchup" in src
    assert "export function renderDsMatchupForChampSelect" in src


def test_dashboard_css_imports_ds_matchup():
    css = _read(DASHBOARD_CSS)
    assert "@import './panels/ds_matchup.css';" in css


def test_index_html_has_mount_point():
    html = _read(INDEX_HTML)
    assert 'id="csv-sugg-ds-matchup"' in html


def test_champ_select_imports_and_calls_ds_matchup():
    src = _read(CHAMP_SELECT_JS)
    assert "from './ds_matchup.js'" in src
    assert "renderDsMatchupForChampSelect" in src


def test_champ_select_wires_ds_matchup_scheduler():
    # The on-land re-render only fires if the scheduler is wired, exactly like
    # the ds_sweep / ds_profile siblings. Without this call the card renders one
    # tick late on a cold cache. Regression-guard the wiring.
    src = _read(CHAMP_SELECT_JS)
    assert "setDsMatchupScheduler" in src


def test_fixture_is_valid_json_with_expected_keys():
    assert FIXTURE_PATH.exists(), f"fixture missing at {FIXTURE_PATH}"
    data = json.loads(_read(FIXTURE_PATH))
    assert isinstance(data, dict)
    for key in ("ok", "verdict", "swing_pct"):
        assert key in data, f"fixture missing {key!r}"
    assert data["ok"] is True


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    for p in (JS_PATH, CSS_PATH, FIXTURE_PATH, Path(__file__)):
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
