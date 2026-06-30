"""
tests/snapshot_panels/test_overlay_stats_role.py

R38 (DIRECTOR REFILL 2026-06-30) - VISUAL PROOF + live hit-target regression for
the Electron-overlay stats mini-panel (w-stats) role <select>. The static CSS
guard lives in tests/test_overlay_stats_role_hit_target.py; this proves the
RENDERED pixels: it imports the real web/js/panels/stats_panel.js module,
renders its scaffold with a synthetic live block (hp_max gates the render), and
confirms the .sp-role select renders at >= --hit-min (42px) in a real browser. A
screenshot is written for operator review (the panel is data-gated, so it never
appears in the static overlay-field snapshot).
"""
from tests.snapshot_panels.test_overlay_view import _open_overlay, SCREENSHOTS

_HIT_MIN = 42

# Import the REAL panel module and render its scaffold with a synthetic live
# block (Number(lc.hp_max) gates renderStatsPanel). Returns the rendered role
# <select> offsetHeight so the test measures the actual applied CSS, not a stub.
_RENDER_STATS = """
async () => {
  const m = await import('/js/panels/stats_panel.js');
  m.renderStatsPanel({ hp_max: 1000, level: 7, cs: 80, kda: '2/1/3', game_time_s: 600 });
  const sel = document.querySelector('#am-statspanel .sp-role');
  return sel ? sel.offsetHeight : -1;
}
"""


def test_stats_role_select_renders_at_hit_min(mock_server, pw_browser):
    """Render the real stats panel scaffold and confirm the role <select>
    renders at >= --hit-min (42px) in a real browser."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        height = page.evaluate(_RENDER_STATS)
        assert height >= _HIT_MIN, (
            "overlay stats role select rendered offsetHeight "
            f"{height}px < --hit-min {_HIT_MIN}px"
        )

        # Visual proof artifact for the operator.
        SCREENSHOTS.mkdir(parents=True, exist_ok=True)
        panel = page.query_selector("#am-statspanel")
        if panel:
            panel.screenshot(path=str(SCREENSHOTS / "overlay_stats_role.png"))

        assert not errors, f"overlay page errors: {errors}"
    finally:
        ctx.close()
