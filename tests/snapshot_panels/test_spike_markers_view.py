"""
tests/snapshot_panels/test_spike_markers_view.py
Power-spike markers strip VISUAL snapshot + grid-compliance coverage (R28,
2026-06-23).

The spike-markers strip (competitor lift #4, docs/COMPETITOR_LIFT_2026-05-30.md)
shipped as web/js/panels/spike_markers.js (#am-spike-markers, in the Active
Match BUILD pane) with backend (dashboard/routes_spike_markers.py) +
panel-smoke (tests/test_spike_markers_panel_dom.py) coverage, but NO dedicated
view-snapshot test - the ds_relscore-shaped gap. The R28 UI-audit cycle
swept its hardcoded off-grid spacing + raw 4px radii onto the
docs/UI_SCALE_SPEC_V2.md 8-px grid + --panel-radius-sm token; this test is the
RED-first guard for that sweep (it asserts the computed radius == 10px and the
head gap == 8px, which fail RED at the pre-sweep 4px / 6px) plus the durable
visual capture, mirroring the C1/C2/C3 + ds_relscore view-snapshot strategy.

renderSpikeMarkers(blockEl, payload) takes the backend payload directly (no
fetch), so we drive the real renderer into its live #am-spike-markers mount
with a deterministic payload (3 level + 3 item marks, the level-11 mark NEXT),
then assert the strip structure + grid tokens + screenshot it.
"""
from pathlib import Path

SCREENSHOTS = Path(__file__).parent / "screenshots"

# Deterministic /api/spike-markers-shaped payload: 3 level marks (6 crossed /
# 11 next / 16 future) + 3 item marks (1 crossed / 2,3 future), next = level 11.
_SPM_PAYLOAD = {
    "ok": True,
    "champion": "Caitlyn",
    "level": 11,
    "markers": [
        {"kind": "level", "threshold": 6, "label": "R unlock", "crossed": True, "next": False, "dps_at": 410},
        {"kind": "level", "threshold": 11, "label": "R rank 2", "crossed": False, "next": True, "dps_at": 560},
        {"kind": "level", "threshold": 16, "label": "R rank 3", "crossed": False, "next": False, "dps_at": 720},
        {"kind": "item", "threshold": 1, "label": "1st item", "crossed": True, "next": False},
        {"kind": "item", "threshold": 2, "label": "2nd item", "crossed": False, "next": False},
        {"kind": "item", "threshold": 3, "label": "3rd item", "crossed": False, "next": False},
    ],
    "next": {"kind": "level", "threshold": 11, "label": "R rank 2"},
    "count": 6,
}


def test_spike_markers_strip_renders(mock_server, pw_browser):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}

    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    # #active-match makes #view-active-match (the strip's host view) visible so
    # the rendered strip is screenshot-able.
    page.goto(
        mock_server.url + "/?ui_mock=1&mode=sr#active-match",
        wait_until="domcontentloaded", timeout=15_000,
    )
    # Let the one-shot mock render settle FIRST: _amMockLoad fetches the
    # active_match_sr fixture and re-fires renderActiveMatch (phase InProgress),
    # whose _renderSpikeMarkersFromCtx pass clears #am-spike-markers (no spike
    # payload in the fixture). Waiting on "InProgress" in #am-sub means that
    # one-shot pass is done, so our direct render below is the LAST DOM write
    # (the WS is stubbed - no further state ticks to clobber it).
    page.wait_for_function(
        "document.querySelector('#am-sub') && "
        "document.querySelector('#am-sub').textContent.indexOf('InProgress') >= 0",
        timeout=10_000,
    )

    # Render the real strip into its live mount with the deterministic payload
    # (renderSpikeMarkers takes the payload directly - no fetch race). Clear any
    # inline display:none the ctx hide-path may have stamped so the strip paints.
    page.evaluate(
        """async (payload) => {
          const m = await import('/js/panels/spike_markers.js');
          if (m._resetSpikeMarkers) m._resetSpikeMarkers();
          const el = document.getElementById('am-spike-markers');
          el.style.display = '';
          m.renderSpikeMarkers(el, payload);
        }""",
        _SPM_PAYLOAD,
    )

    page.wait_for_function(
        "document.querySelectorAll('#am-spike-markers .spm-cell').length > 0",
        timeout=10_000,
    )

    try:
        block = page.locator("#am-spike-markers")
        assert block.is_visible(), "#am-spike-markers not visible after render"

        # Structure: 3 level + 3 item = 6 cells; exactly one NEXT cell.
        cells = page.eval_on_selector_all(
            "#am-spike-markers .spm-cell", "els => els.length"
        )
        assert cells == 6, f"expected 6 spike cells, got {cells}"
        nexts = page.eval_on_selector_all(
            "#am-spike-markers .spm-cell[data-spm-state='next']", "els => els.length"
        )
        assert nexts == 1, f"expected exactly 1 NEXT cell, got {nexts}"
        next_txt = page.eval_on_selector(
            "#am-spike-markers .spm-next", "el => el.textContent.trim()"
        )
        assert "NEXT SPIKE" in next_txt, f"spm-next missing caption: {next_txt!r}"

        # Grid-compliance teeth (RED before the R28 sweep, GREEN after): both radii
        # must CONSUME a grid token, not a raw px. The card root uses --radius (the
        # unified panel-chrome radius since the 2026-07-22 chrome sweep), the cell uses
        # --panel-radius-sm. Assert each equals its own token's resolved value so the
        # test stays correct across theme swaps (Terminal default = 8px, Hextech = 16px)
        # instead of pinning one theme's literal.
        card_radius = page.eval_on_selector(
            "#am-spike-markers",
            "el => getComputedStyle(el).borderTopLeftRadius",
        )
        card_token = page.eval_on_selector(
            "#am-spike-markers",
            "el => getComputedStyle(el).getPropertyValue('--radius').trim()",
        )
        assert card_radius == card_token, (
            f"card radius should consume --radius ({card_token}): {card_radius}"
        )
        cell_radius = page.eval_on_selector(
            "#am-spike-markers .spm-cell",
            "el => getComputedStyle(el).borderTopLeftRadius",
        )
        cell_token = page.eval_on_selector(
            "#am-spike-markers .spm-cell",
            "el => getComputedStyle(el).getPropertyValue('--panel-radius-sm').trim()",
        )
        assert cell_radius == cell_token, (
            f"cell radius should consume --panel-radius-sm ({cell_token}): {cell_radius}"
        )
        head_gap = page.eval_on_selector(
            "#am-spike-markers .spm-head",
            "el => getComputedStyle(el).columnGap",
        )
        assert head_gap == "8px", f"head gap != 8px (--space-2 on-grid): {head_gap}"

        SCREENSHOTS.mkdir(exist_ok=True)
        block.screenshot(path=str(SCREENSHOTS / "spike-markers_strip.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s): {offenders[:5]}"
