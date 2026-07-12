"""
tests/snapshot_panels/test_overlay_stats_role.py

VISUAL PROOF for the reworked Electron-overlay stats mini-panel (w-stats,
overlay item 8). The in-panel role <select> (.sp-role) is RETIRED - the
rank-tier + compare-role selectors moved to DS Settings (the static hit-target
guard for those relocated selects lives in
tests/test_overlay_stats_role_hit_target.py). This proves the RENDERED pixels of
the new panel: it imports the real web/js/panels/stats_panel.js module, renders
its scaffold with a synthetic live block + mode (hp_max gates the render), and
confirms the vertical compare rows paint (each .sp-row reserves real height) with
NO leftover .sp-role control. A screenshot is written for operator review (the
panel is data-gated, so it never appears in the static overlay-field snapshot).
"""
from tests.snapshot_panels.test_overlay_view import _open_overlay, SCREENSHOTS

# Import the REAL panel module and render its scaffold with a synthetic live
# block + mode. Number(lc.hp_max) gates renderStatsPanel. Returns the rendered
# first .sp-row offsetHeight + whether any retired .sp-role control survived.
_RENDER_STATS = """
async () => {
  const m = await import('/js/panels/stats_panel.js');
  m.renderStatsPanel(
    { hp_max: 1000, level: 7, cs: 80, kda: '2/1/3', game_time_s: 600 },
    { mode: 'sr' }
  );
  const row = document.querySelector('#am-statspanel .sp-row');
  const staleRole = document.querySelector('#am-statspanel .sp-role');
  return { rowHeight: row ? row.offsetHeight : -1, staleRole: !!staleRole };
}
"""


def test_stats_panel_renders_vertical_rows(mock_server, pw_browser):
    """Render the real reworked stats panel scaffold and confirm the compare
    rows paint (real height) with the retired role <select> gone."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        res = page.evaluate(_RENDER_STATS)
        assert res["rowHeight"] > 0, (
            f"overlay stats panel rows did not render (offsetHeight {res['rowHeight']})"
        )
        assert not res["staleRole"], (
            "retired in-panel .sp-role control still present after the item 8 rework"
        )

        # Visual proof artifact for the operator.
        SCREENSHOTS.mkdir(parents=True, exist_ok=True)
        panel = page.query_selector("#am-statspanel")
        if panel:
            panel.screenshot(path=str(SCREENSHOTS / "overlay_stats_role.png"))

        assert not errors, f"overlay page errors: {errors}"
    finally:
        ctx.close()
