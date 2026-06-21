"""
tests/snapshot_panels/test_cd_ledger.py

Contract tests for the right-rail CD Ledger panel (web/js/panels/cd_ledger.js).

The panel is a pure render module over /api/state.summoner_cooldowns - the
deterministic behavior is the structural contract (DOM shape, sig dedup,
spell-icon map coverage). A live Playwright snapshot would require a
fixture with the new top-level `summoner_cooldowns` array, which adds
coupling for a panel whose logic is already covered by:

  1. Backend tests: tests/test_summoner_cooldowns.py + test_state_cooldowns.py
     cover compute_cooldowns + the Live Client adapter end-to-end.
  2. These contract tests: verify the JS exports the public surface,
     the spell-icon map covers every spell id the backend can emit,
     the CSS/HTML wire is intact, and the active_match dispatcher calls
     the panel.

Run:
    pytest tests/snapshot_panels/test_cd_ledger.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
JS_PATH = ROOT / "web" / "js" / "panels" / "cd_ledger.js"
CSS_PATH = ROOT / "web" / "css" / "panels" / "cd_ledger.css"
DASHBOARD_CSS = ROOT / "web" / "css" / "dashboard.css"
INDEX_HTML = ROOT / "web" / "index.html"
ACTIVE_MATCH_JS = ROOT / "web" / "js" / "panels" / "active_match.js"
MAIN_JS = ROOT / "web" / "js" / "main.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_cd_ledger_js_exists():
    assert JS_PATH.exists(), f"cd_ledger.js missing at {JS_PATH}"
    assert JS_PATH.stat().st_size > 0


def test_cd_ledger_css_exists():
    assert CSS_PATH.exists(), f"cd_ledger.css missing at {CSS_PATH}"
    assert CSS_PATH.stat().st_size > 0


def test_cd_ledger_exports_public_api():
    """The two public exports the active_match dispatcher imports."""
    src = _read(JS_PATH)
    assert "export function renderCooldownLedger" in src
    assert "export function attachCooldownLedgerHandlers" in src
    # The __test export bundle for unit poking.
    assert "export const __test" in src


def test_spell_icon_map_covers_every_backend_spell_id():
    """The _SPELL_IMG map in JS must include every spell id the backend
    can emit in summs.d_id / summs.f_id, otherwise the chip falls back
    to the initial-letter sigil and the operator loses visual scan."""
    from core.summoner_cooldowns import SUMMONER_SPELL_BASE_CD

    src = _read(JS_PATH)
    # Extract the _SPELL_IMG literal block.
    m = re.search(r"const\s+_SPELL_IMG\s*=\s*\{(.*?)\};", src, re.DOTALL)
    assert m, "_SPELL_IMG declaration not found"
    block = m.group(1)
    found_ids: set[int] = set()
    for line in block.splitlines():
        mid = re.match(r"\s*(\d+)\s*:", line)
        if mid:
            found_ids.add(int(mid.group(1)))
    backend_ids = set(SUMMONER_SPELL_BASE_CD.keys())
    missing = backend_ids - found_ids
    assert not missing, (
        f"_SPELL_IMG missing spell ids the backend can emit: {sorted(missing)}. "
        f"Add them so chips show the spell icon instead of the letter sigil."
    )


def test_ledger_emits_expected_dom_classes():
    """The render path attaches CSS classes the stylesheet styles. If a
    class name drifts here vs the CSS, the chip pill / blue+red side
    tint / READY-pill background silently disappear."""
    src = _read(JS_PATH)
    css = _read(CSS_PATH)
    # Class names the JS emits via _renderRow + _chip.
    js_classes = [
        "cd-ledger",
        "cd-row",
        "cd-row-blue",
        "cd-row-red",
        "cd-row-portrait",
        "cd-row-portrait-img",
        "cd-row-initial",
        "cd-row-name",
        "cd-row-chips",
        "cd-chip",
        "cd-chip-icon",
        "cd-chip-sigil",
        "cd-chip-text",
        "cd-chip-ready",
        "cd-empty",
    ]
    for cls in js_classes:
        # JS must reference it (sanity - guards rename drift).
        assert cls in src, f"cd_ledger.js does not emit {cls!r}"
        # CSS must style it.
        assert ("." + cls) in css, f"cd_ledger.css missing rule for .{cls}"


def test_ledger_handles_null_or_empty_cooldowns():
    """Render path must render an empty placeholder (not crash, not blank)
    when cooldowns is null or [] - this is the lobby/idle state."""
    src = _read(JS_PATH)
    # The empty-placeholder branch must exist and emit cd-empty.
    assert "cd-empty" in src
    # The Array.isArray check is the gate; absence means a null payload
    # would either crash or fall through to the for-loop with a non-array.
    assert "Array.isArray(cooldowns)" in src


def test_ledger_uses_idempotent_render_dedup():
    """Sig-based dedup keeps the DOM stable across 1 Hz state ticks when
    cooldowns haven't changed - mirrors the pattern in other panels."""
    src = _read(JS_PATH)
    assert "idempotentRender" in src
    assert "from '../lib/idempotent_render.js'" in src


def test_collapse_state_persisted_in_localstorage():
    """The pitch's 'collapsible' contract: collapse state survives reload."""
    src = _read(JS_PATH)
    assert 'localStorage' in src
    assert 'cdLedgerCollapsed' in src
    # Both read + write paths.
    assert 'getItem' in src
    assert 'setItem' in src


def test_dashboard_css_imports_cd_ledger():
    """The new stylesheet must be wired into the dashboard.css import
    chain or the rail renders unstyled."""
    css = _read(DASHBOARD_CSS)
    assert "@import './panels/cd_ledger.css';" in css


def test_index_html_has_mount_point():
    """The mount point (#cd-ledger-body) + collapse head (#cd-ledger-head)
    must exist in the static markup."""
    html = _read(INDEX_HTML)
    assert 'id="cd-ledger-body"' in html
    assert 'id="cd-ledger-head"' in html
    # And the pane wrapper inside view-active-match.
    assert "am-pane-cd" in html


def test_active_match_grid_hides_cd_rail_visual_only():
    """Operator 2026-06-10: the CDS rail is visually retired from the
    dashboard grid (display:none, no cd column/area) but the pane + its
    wiring stay - the overlay threat panelset re-shows it. This replaces
    the old 280px-rail allocation contract."""
    css = _read(ROOT / "web" / "css" / "panels" / "active_match.css")
    # Rail column gone; two-column template remains.
    assert "280px" not in css
    assert '"call  map"' in css
    assert '"build map"' in css
    # The pane is hidden, not deleted.
    assert "am-pane-cd" in css
    import re
    # .am-grid hop outranks cd_ledger.css's same-selector display:flex
    # (later import order would otherwise win).
    assert re.search(
        r"#view-active-match \.am-grid \.am-pane-cd\s*\{[^}]*display:\s*none",
        css)
    # Overlay threat panelset keeps its CDS surface. The widget-field doctrine
    # (2026-06-21) made the cd pane a w-threat .ovx-widget, so the selector
    # carries a `.ovx-widget:not(.ovx-hidden)` suffix before the brace - allow
    # any selector continuation between .am-pane-cd and the rule body.
    overlay = _read(ROOT / "web" / "css" / "overlay.css")
    assert re.search(
        r'\[data-panelset="threat"\] #view-active-match \.am-pane-cd'
        r"[^{]*\{[^}]*display:\s*block\s*!important", overlay)


def test_active_match_js_dispatches_to_cd_ledger():
    """The active_match dispatcher must import + invoke both public
    functions on every render so the rail picks up state ticks."""
    src = _read(ACTIVE_MATCH_JS)
    assert "from './cd_ledger.js'" in src
    assert "renderCooldownLedger(" in src
    assert "attachCooldownLedgerHandlers(" in src


def test_main_js_threads_cooldowns_through_ctx():
    """main.js must thread state.latest.summoner_cooldowns into the
    active_match ctx so the panel gets the wire."""
    src = _read(MAIN_JS)
    assert "summoner_cooldowns" in src
    assert "cooldowns:" in src


def test_no_em_or_en_dashes_in_new_files():
    """Hard rule: 7-bit ASCII authored content across the fleet.
    Smart quotes / em / en dashes break PS 5.1 parsers + operator style."""
    bad = [chr(0x2014), chr(0x2013), chr(0x201C), chr(0x201D), chr(0x2018), chr(0x2019)]
    for fp in (JS_PATH, CSS_PATH):
        src = _read(fp)
        for ch in bad:
            assert ch not in src, (
                f"{fp.name} contains forbidden non-ASCII char U+{ord(ch):04X}"
            )


def test_short_name_helper_truncates_long_names():
    """_shortName must not return more than 14 chars (12 + 3 for '...' minus 1)
    so the narrow rail's name column doesn't overflow."""
    src = _read(JS_PATH)
    m = re.search(r"function\s+_shortName\(s\)\s*\{(.*?)\n\}", src, re.DOTALL)
    assert m, "_shortName helper not found"
    body = m.group(1)
    # The truncation branch uses 12-char threshold + slice(0, 11) + '...'.
    assert "<= 12" in body or "<=12" in body
    assert "slice(0, 11)" in body or "slice(0,11)" in body


@pytest.mark.parametrize(
    "side_field,expected_class",
    [
        ("blue", "cd-row-blue"),
        ("red",  "cd-row-red"),
    ],
)
def test_side_tint_emitted_per_team(side_field, expected_class):
    """The render path must emit a side-specific class so the CSS can
    color the left border blue/red."""
    src = _read(JS_PATH)
    # Both branches must be present in _renderRow.
    assert f'"{side_field}"' in src
    assert expected_class in src
