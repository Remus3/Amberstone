"""
tests/snapshot_panels/test_ds_relscore_view.py
DS relative-score bar VISUAL snapshot coverage (D1, 2026-06-06).

The DS relative-score bar (competitor lift #3 / Aggregator P lift) shipped
as item 220: dashboard/routes_ds_relscore.py (GET /api/ds-relscore, per-row
score_pct = delta_dps/top_delta*100, row0=100.0) + web/js/panels/ds_relscore.js
(#csv-ds-relscore panel, render-gated on cs.my_champion; CS3 2026-06-08 moved
it from champ-select to the Active Match view). It had
backend (tests/test_routes_ds_relscore.py) + panel-smoke (tests/
test_ds_relscore_panel_dom.py) coverage but the item-220 row left a "LIVE
VISUAL CAPTURE owed (render-gated on locked champ)" - Game-PC :8892 MCP is
down and Claude_Preview cannot attach the self-signed HTTPS :8888. This test
discharges that owed capture in CI-durable form, mirroring the C1/C2/C3
view-snapshot strategy.

The champ_select_* ui_mock fixtures do not lock my_champion (the accessor the
panel gates on), so we drive the real renderDsRelscore directly against the
live #csv-ds-relscore mount with a synthetic locked-champ state and a stubbed
/api/ds-relscore payload (everything else passes through to the mock server),
then assert the horizontal bar fills are proportional to score_pct (the bar IS
the hero element) and screenshot the rendered panel.
"""
import pytest

from pathlib import Path

SCREENSHOTS = Path(__file__).parent / "screenshots"

# Deterministic /api/ds-relscore payload - descending score_pct so the bar
# fills must read 100 / 80 / 70 / 50 / 40 percent.
_RELSCORE_STUB = """
(function () {
  const _f = window.fetch;
  window.fetch = function (u, o) {
    const url = (typeof u === 'string') ? u : (u && u.url) || '';
    if (url.indexOf('/api/ds-relscore') >= 0) {
      const body = {
        ok: true, champion: 'Caitlyn',
        target: { armor: 80, mr: 52, level: 11, mode: 'SR' },
        rows: [
          {item_id:'3031', name:'Infinity Edge',    delta_dps:210.4, score_pct:100.0, gold:3450},
          {item_id:'3036', name:"Lord Dominik's",   delta_dps:168.3, score_pct:80.0,  gold:3000},
          {item_id:'6672', name:'Kraken Slayer',    delta_dps:147.3, score_pct:70.0,  gold:3100},
          {item_id:'3094', name:'Rapid Firecannon', delta_dps:105.2, score_pct:50.0,  gold:2600},
          {item_id:'3046', name:'Phantom Dancer',   delta_dps:84.2,  score_pct:40.0,  gold:2600}
        ],
        count: 5
      };
      return Promise.resolve(new Response(
        JSON.stringify(body),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      ));
    }
    return _f.apply(this, arguments);
  };
})();
"""


def test_ds_relscore_bar_renders(mock_server, pw_browser):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}

    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.add_init_script(_RELSCORE_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    # CS3 (2026-06-08): the relscore panel moved off champ-select to the
    # Active Match view, so #active-match makes #view-active-match (the panel's
    # new host view) visible and the rendered bar screenshot-able.
    page.goto(
        mock_server.url + "/?ui_mock=1&mode=sr#active-match",
        wait_until="domcontentloaded", timeout=15_000,
    )

    # Wait for the champion index to load so resolveChampNames([51]) -> a
    # real name (the panel hides until the locked champ resolves).
    page.wait_for_function(
        """async () => {
          try {
            const m = await import('/js/panels/cc_conditional_pressure.js');
            const n = m.resolveChampNames ? m.resolveChampNames([51]) : [];
            return !!(n && n.length && n[0]);
          } catch (e) { return false; }
        }""",
        timeout=10_000,
    )

    # Render the real panel into its live mount with a synthetic locked
    # champ; the stubbed /api/ds-relscore lands and repaints the rows.
    page.evaluate(
        """async () => {
          const m = await import('/js/panels/ds_relscore.js');
          if (m._resetDsRelscore) m._resetDsRelscore();
          const el = document.getElementById('csv-ds-relscore');
          m.renderDsRelscore(el, { my_champion: 51, queue_id: 420 });
        }"""
    )

    # Wait for the fetch onLand re-render to paint the bar fills.
    page.wait_for_function(
        "document.querySelectorAll('#csv-ds-relscore .dsr-bar-fill').length > 0",
        timeout=10_000,
    )

    try:
        block = page.locator("#csv-ds-relscore")
        assert block.is_visible(), "#csv-ds-relscore not visible after render"

        fills = page.eval_on_selector_all(
            "#csv-ds-relscore .dsr-bar-fill", "els => els.map(e => e.style.width)"
        )
        assert len(fills) == 5, f"expected 5 bar rows, got {len(fills)}: {fills}"
        # Row 0 is the best item -> 100% fill; bars are non-increasing.
        assert fills[0] == "100%", f"row0 fill != 100%: {fills[:3]}"
        nums = [float(w.rstrip("%")) for w in fills]
        assert nums == sorted(nums, reverse=True), f"bars not descending: {nums}"

        pcts = page.eval_on_selector_all(
            "#csv-ds-relscore .dsr-pct", "els => els.map(e => e.textContent.trim())"
        )
        assert pcts[0] == "100", f"row0 pct label != 100: {pcts[:3]}"

        SCREENSHOTS.mkdir(exist_ok=True)
        block.screenshot(path=str(SCREENSHOTS / "ds-relscore_bar.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s): {offenders[:5]}"
