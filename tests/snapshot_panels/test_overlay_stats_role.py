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


# The LOAD-BEARING provenance badge (.sp-src) must never clip its caveat
# suffix ("estimate" / "live avg") - if it ellipsizes, coaching can read the
# rank-tier ESTIMATE as ground truth (the whole point of the badge). The
# longest bounded case is the widest tier ("Grandmaster") + " estimate"
# uppercased + letter-spaced. Setting the shared rc-pgr-rank-tier key makes
# _paintBadge render that string with no bench data fetched (Phase-5 audit
# SHOULD-FIX: overlay item 8). scrollWidth > clientWidth means the box
# ellipsized the caveat - the guard fails.
_RENDER_WORST_BADGE = """
async () => {
  localStorage.setItem('rc-pgr-rank-tier', 'grandmaster');
  const m = await import('/js/panels/stats_panel.js');
  m._resetStatsPanel && m._resetStatsPanel();
  m.renderStatsPanel(
    { hp_max: 1000, level: 7, cs: 80, kda: '2/1/3', game_time_s: 600 },
    { mode: 'sr' }
  );
  const src = document.querySelector('#am-statspanel .sp-src');
  return src
    ? { text: src.textContent, scrollW: src.scrollWidth, clientW: src.clientWidth }
    : { text: null, scrollW: -1, clientW: -1 };
}
"""


def test_stats_provenance_badge_not_clipped(mock_server, pw_browser):
    """The widest bounded provenance badge ("Grandmaster estimate") must fit
    the panel without ellipsizing its load-bearing caveat suffix."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        res = page.evaluate(_RENDER_WORST_BADGE)
        assert res["text"] == "Grandmaster estimate", (
            f"provenance badge text unexpected: {res['text']!r}"
        )
        # +1px tolerance for sub-pixel rounding; a real ellipsis clip overflows
        # by many px (the caveat word is ~60px).
        assert res["scrollW"] <= res["clientW"] + 1, (
            "provenance badge clips the estimate caveat "
            f"(scrollWidth {res['scrollW']} > clientWidth {res['clientW']}) - "
            "coaching could read the rank-tier estimate as ground truth"
        )

        SCREENSHOTS.mkdir(parents=True, exist_ok=True)
        panel = page.query_selector("#am-statspanel")
        if panel:
            panel.screenshot(path=str(SCREENSHOTS / "overlay_stats_badge_grandmaster.png"))

        assert not errors, f"overlay page errors: {errors}"
    finally:
        ctx.close()
