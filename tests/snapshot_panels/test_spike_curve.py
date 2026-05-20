"""
tests/snapshot_panels/test_spike_curve.py

Contract tests for the Spike Curve Sparkline panel
(web/js/panels/spike_curve.js).

The panel is a pure SVG-render module over the /api/spike-curve backend
(dashboard/routes_spike_curve.py - already covered by
tests/test_routes_spike_curve.py). The frontend's deterministic
behavior is the structural contract: DOM shape, palette, sig dedup,
mount point, fail-soft on null curve. A live Playwright snapshot would
require a fixture with the new mount node + the CHAMPS.byId index
populated; that adds coupling for a panel whose logic is covered by:

  1. Backend tests: tests/test_routes_spike_curve.py - validates the
     /api/spike-curve route end-to-end (request shape, response shape,
     caching, error paths).
  2. These contract tests: the JS exports the public surface, the CSS
     covers the container classes the JS emits, the active_match
     dispatcher imports + invokes the panel, the SVG palette + scale
     primitives are sound, and the fail-soft empty path renders a
     visible placeholder.

Run:
    pytest tests/snapshot_panels/test_spike_curve.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
JS_PATH = ROOT / "web" / "js" / "panels" / "spike_curve.js"
CSS_PATH = ROOT / "web" / "css" / "panels" / "spike_curve.css"
DASHBOARD_CSS = ROOT / "web" / "css" / "dashboard.css"
INDEX_HTML = ROOT / "web" / "index.html"
ACTIVE_MATCH_JS = ROOT / "web" / "js" / "panels" / "active_match.js"
BACKEND_ROUTE = ROOT / "dashboard" / "routes_spike_curve.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_spike_curve_js_exists():
    assert JS_PATH.exists(), f"spike_curve.js missing at {JS_PATH}"
    assert JS_PATH.stat().st_size > 0


def test_spike_curve_css_exists():
    assert CSS_PATH.exists(), f"spike_curve.css missing at {CSS_PATH}"
    assert CSS_PATH.stat().st_size > 0


def test_spike_curve_exports_public_api():
    """The three public exports active_match.js imports."""
    src = _read(JS_PATH)
    assert "export function renderSpikeCurve" in src
    assert "export function fetchSpikeCurve" in src
    assert "export function getCachedSpikeCurve" in src
    assert "export function _resetSpikeCurve" in src
    # Internals exposed for unit poking.
    assert "export const __test" in src


def test_dashboard_css_imports_spike_curve():
    """The new stylesheet must be wired into the dashboard.css import
    chain or the panel renders unstyled."""
    css = _read(DASHBOARD_CSS)
    assert "@import './panels/spike_curve.css';" in css


def test_index_html_has_mount_point():
    """The mount point (#am-spike-curve) must exist in the static
    markup above #am-build-body inside .am-pane-build."""
    html = _read(INDEX_HTML)
    assert 'id="am-spike-curve"' in html
    # The mount sits inside the BUILD pane between the head and the body.
    # Verify ordering: head, then mount, then body within am-pane-build.
    pane_start = html.find('class="am-pane am-pane-build"')
    assert pane_start >= 0, "am-pane-build not found in markup"
    pane_end = html.find("</div>", pane_start)
    # Walk forward past nested closes - just confirm both ids appear
    # after the pane start in the right order.
    spike_pos = html.find('id="am-spike-curve"', pane_start)
    build_body_pos = html.find('id="am-build-body"', pane_start)
    assert spike_pos > 0
    assert build_body_pos > spike_pos, (
        "am-spike-curve must appear BEFORE am-build-body inside am-pane-build"
    )


def test_active_match_js_imports_spike_curve():
    """The active_match dispatcher must import the panel's exports +
    invoke renderSpikeCurveFromCtx on every render so the panel picks
    up state ticks."""
    src = _read(ACTIVE_MATCH_JS)
    assert "from './spike_curve.js'" in src
    assert "renderSpikeCurve" in src
    assert "fetchSpikeCurve" in src
    assert "getCachedSpikeCurve" in src
    assert "_renderSpikeCurveFromCtx" in src


def test_emits_expected_dom_classes():
    """JS-emitted class names must match CSS rules in spike_curve.css.
    Drift here breaks the rendered styling silently."""
    src = _read(JS_PATH)
    css = _read(CSS_PATH)
    # Container class is emitted by index.html, but the JS must emit
    # at least these for the SVG + the empty placeholder.
    js_classes = ["spk-svg", "spk-empty", "spk-ally", "spk-enemy"]
    for cls in js_classes:
        assert cls in src, f"spike_curve.js does not emit {cls!r}"
    # CSS must style the container + the empty / ready states.
    assert ".spike-curve-container" in css
    assert ".spk-svg" in css
    assert ".spk-empty" in css


def test_palette_matches_brief():
    """Brief specifies #5096ff (ally blue), #ff5050 (enemy red), and a
    gray dashed 'now' marker. Drift breaks the team color semantic."""
    src = _read(JS_PATH)
    assert "#5096ff" in src, "ally color #5096ff missing"
    assert "#ff5050" in src, "enemy color #ff5050 missing"
    # Now marker should be dashed gray of some kind.
    assert "stroke-dasharray" in src
    assert "rgba(180, 180, 180" in src or "_NOW_COLOR" in src


def test_svg_dimensions_match_brief():
    """40px-tall SVG, full-width, viewBox set so it scales clean."""
    src = _read(JS_PATH)
    css = _read(CSS_PATH)
    # JS-side constant for height.
    assert "_SVG_HEIGHT" in src
    m = re.search(r"_SVG_HEIGHT\s*=\s*(\d+)", src)
    assert m, "_SVG_HEIGHT constant not found"
    assert int(m.group(1)) == 40, "SVG height must be 40px per brief"
    # CSS height matches.
    assert "height: 40px" in css


def test_signature_dedup_present():
    """The render path must dedupe by signature so 1Hz state ticks don't
    rebuild the SVG every time - matches the cd_ledger.js pattern."""
    src = _read(JS_PATH)
    # Signature function exists.
    assert "_signature" in src
    # The sig-dedup short-circuit guard.
    assert "_CURVE_SIG" in src
    # Comparing the new sig vs the last-rendered sig and bailing.
    assert re.search(r"_CURVE_SIG\[\w+\]\s*===\s*sig", src) is not None


def test_cache_key_order_insensitive():
    """The fetch cache key must sort the team ids so 1,2,3,4,5 and
    5,4,3,2,1 hit the same key (mirrors the backend's
    _response_cache_key, which dedupes order-insensitively)."""
    src = _read(JS_PATH)
    m = re.search(r"function\s+_cacheKey\([^)]*\)\s*\{(.*?)\n\}", src, re.DOTALL)
    assert m, "_cacheKey helper not found"
    body = m.group(1)
    # Must sort both team id arrays.
    assert ".sort()" in body
    # Both ally + enemy must be sorted (two .sort() calls is the
    # standard pattern; a single .sort would only cover one side).
    assert body.count(".sort()") >= 2


def test_failsoft_on_null_curve():
    """Null / empty curves must render an empty placeholder, not crash
    and not collapse the 40px reserved height (which would jitter the
    BUILD pane layout)."""
    src = _read(JS_PATH)
    # The fail-soft branch checks Array.isArray on both curves + the
    # length-zero case.
    assert "Array.isArray(ally_curve)" in src
    assert "Array.isArray(enemy_curve)" in src
    # Placeholder state attribute distinguishes empty vs ready render.
    assert 'dataset.spkState' in src
    assert '"empty"' in src
    assert 'spk-empty' in src


def test_render_signature_function_pure():
    """The signature function must be deterministic over the same inputs.
    The implementation should round powers to avoid float-noise sig
    changes on identical curves."""
    src = _read(JS_PATH)
    m = re.search(r"function\s+_signature\([^)]*\)\s*\{(.*?)\n\}", src, re.DOTALL)
    assert m, "_signature helper not found"
    body = m.group(1)
    # Powers are rounded so float jitter doesn't trip the dedup guard.
    assert "Math.round" in body
    # Both teams' curves contribute to the sig.
    assert "ally" in body
    assert "enemy" in body
    # Peaks + now_minute + item_minutes also contribute.
    assert "peaks" in body
    assert "nowMinute" in body or "now_minute" in body
    assert "itemMinutes" in body or "item_minutes" in body


def test_peak_triangle_renders_polygon():
    """Peak indicators must use SVG <polygon> with three points so the
    triangle has a consistent shape regardless of viewport."""
    src = _read(JS_PATH)
    m = re.search(r"function\s+_peakTriangle\([^)]*\)\s*\{(.*?)\n\}", src, re.DOTALL)
    assert m, "_peakTriangle helper not found"
    body = m.group(1)
    assert "<polygon" in body
    # Three points + fail-soft on missing peak.
    assert "peakMinute == null" in body or "peakMinute === null" in body
    assert "return \"\"" in body or "return ''" in body


def test_item_minutes_threaded_through_ctx():
    """The optional item-completion ticks must be read from ctx.item_minutes
    so the active_match wire-up can pass the canonical 6-slot schedule
    without modifying the panel's public surface."""
    src = _read(JS_PATH)
    assert "item_minutes" in src


def test_mode_map_covers_supported_modes():
    """The mode mapping in active_match.js must cover the same set the
    backend supports: SR, ARAM, ARENA, BRAWL. TFT / KIWI variants
    should be silently skipped (the backend returns 400 for them)."""
    src = _read(ACTIVE_MATCH_JS)
    m = re.search(r"_SPK_MODE_MAP\s*=\s*\{(.*?)\};", src, re.DOTALL)
    assert m, "_SPK_MODE_MAP not found in active_match.js"
    block = m.group(1)
    for backend_mode in ("SR", "ARAM", "ARENA", "BRAWL"):
        assert backend_mode in block, (
            f"_SPK_MODE_MAP missing backend mode {backend_mode!r}"
        )


def test_no_em_or_en_dashes_in_new_files():
    """Hard rule: 7-bit ASCII authored content across the fleet.
    Smart quotes / em / en dashes break PS 5.1 parsers + operator style."""
    bad = ["—", "–", "“", "”", "‘", "’"]
    for fp in (JS_PATH, CSS_PATH):
        src = _read(fp)
        for ch in bad:
            assert ch not in src, (
                f"{fp.name} contains forbidden non-ASCII char U+{ord(ch):04X}"
            )


def test_no_inline_label_overflow():
    """40px is too short for inline labels per brief - confirm the JS
    renders only an aria-label / <title> for accessibility, not visible
    text. (Operator decision: tooltip on hover only.)"""
    src = _read(JS_PATH)
    # <text> is only allowed if commented out or absent; the SVG should
    # rely on <title> + aria-label for labelling.
    # We accept the presence of <title> + aria-label and the absence of
    # an SVG <text> element with real label content.
    assert "<title>" in src
    assert "aria-label" in src
    # Sanity: no SVG <text> tag in the rendered svg template.
    # Pull the svg block and check.
    m = re.search(r"const\s+svg\s*=\s*`(.*?)`;", src, re.DOTALL)
    assert m, "svg template literal not found"
    svg_block = m.group(1)
    assert "<text" not in svg_block, (
        "Inline <text> labels would overflow 40px - keep labels in <title>/aria"
    )


def test_backend_route_present():
    """Sanity tie-back: the /api/spike-curve route the frontend fetches
    must exist - dashboard/routes_spike_curve.py is the producer."""
    assert BACKEND_ROUTE.exists(), (
        "dashboard/routes_spike_curve.py missing - frontend has nothing to fetch"
    )
    src = _read(BACKEND_ROUTE)
    assert '"/api/spike-curve"' in src


def test_scale_function_handles_zero_extent():
    """The internal _scale builder must collapse to a sensible midpoint
    when the domain extent is zero (degenerate flat curve) instead of
    dividing by zero and emitting NaN coordinates that break SVG render."""
    src = _read(JS_PATH)
    m = re.search(r"function\s+_scale\([^)]*\)\s*\{(.*?)\n\}", src, re.DOTALL)
    assert m, "_scale helper not found"
    body = m.group(1)
    # Zero-extent guard must be present.
    assert "dExt <= 0" in body or "dExt === 0" in body
    # Returns a callable that emits a midpoint (or any safe constant).
    assert "return" in body


def test_active_match_uses_champs_for_id_lookup():
    """The mode wire-up must use CHAMPS.byId from items_index.js (not a
    fictional window.CHAMP_INDEX) so the panel resolves champion ids
    consistently with the rest of the dashboard."""
    src = _read(ACTIVE_MATCH_JS)
    assert "import { ITEMS, CHAMPS }" in src or "import { CHAMPS" in src
    # The reverse-lookup memo must read from CHAMPS.byId.
    assert "CHAMPS.byId" in src


@pytest.mark.parametrize(
    "field,expected",
    [
        ("_SVG_HEIGHT", 40),
        ("_PAD_TOP", 3),
        ("_PAD_BOTTOM", 4),
    ],
)
def test_layout_constants(field, expected):
    """The SVG inner-padding constants must stay aligned with the 40px
    brief; values are referenced via __test for unit tests downstream."""
    src = _read(JS_PATH)
    m = re.search(rf"const\s+{re.escape(field)}\s*=\s*(\d+)", src)
    assert m, f"layout constant {field} not found"
    assert int(m.group(1)) == expected, (
        f"{field} drifted from expected {expected}"
    )
