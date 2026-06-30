"""
tests/snapshot_panels/test_overlay_launcher_menu.py

R36 (DIRECTOR REFILL 2026-06-30) - VISUAL PROOF + live hit-target regression for
the Electron-overlay launcher control center (#w-launcher), the 5-phase fixture
audit that LEDGER 688 shipped without. Drives the real ?overlay=1 page, taps the
launcher to open + render its layout menu, and measures the menu's action rows
and slider rows in a real browser (the static CSS guard lives in
tests/test_overlay_launcher_hit_targets.py; this proves the rendered pixels).

HIT-TARGETS MUST-FIX (docs/UI_SCALE_SPEC_V2.md line 112): every menu action row
(per-panel toggle / reset / done) and every opacity/scale slider row reserves the
--hit-min 42px tap target. A screenshot of the open menu is written for the
operator's visual review (the launcher menu is only reachable by interaction, so
it never appears in the static overlay-field snapshots).
"""
from tests.snapshot_panels.test_overlay_view import _open_overlay, SCREENSHOTS

# A no-move pointerdown+pointerup on the launcher square = a TAP (open the menu)
# in lib/overlay_layout.js _installLauncher; a real drag would need movement past
# the 4px threshold. setPointerCapture is wrapped in try/catch in the handler, so
# a headless pointerId that cannot be captured degrades cleanly.
_TAP_LAUNCHER = """
() => {
  const el = document.querySelector('#w-launcher');
  if (!el) return false;
  const o = { clientX: 30, clientY: 30, pointerId: 1, bubbles: true, cancelable: true };
  el.dispatchEvent(new PointerEvent('pointerdown', o));
  el.dispatchEvent(new PointerEvent('pointerup', o));
  return true;
}
"""

_HIT_MIN = 42


def test_launcher_menu_opens_and_rows_meet_hit_min(mock_server, pw_browser):
    """Tap the launcher, render the menu, and confirm the action rows + slider
    rows render at >= --hit-min (42px) in a real browser."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        assert page.query_selector("#w-launcher"), "launcher widget must mount in overlay mode"

        assert page.evaluate(_TAP_LAUNCHER) is True, "launcher tap dispatched"
        # The menu populates on open (_renderMenu); wait for the first action row.
        page.wait_for_function(
            "document.querySelector('#ovx-launcher-menu.ovx-menu-open "
            "  .ovx-menu-row') !== null",
            timeout=5_000,
        )

        # Every rendered action row (toggle/reset/done) meets the tap floor.
        row_min = page.evaluate(
            "() => Math.min(...[...document.querySelectorAll("
            "'#ovx-launcher-menu .ovx-menu-row')].map(e => e.offsetHeight))"
        )
        assert row_min >= _HIT_MIN, (
            f"launcher menu action row shortest offsetHeight {row_min}px < "
            f"--hit-min {_HIT_MIN}px"
        )

        # Every slider row (opacity/scale thumb drag target) meets the tap floor.
        slider_min = page.evaluate(
            "() => Math.min(...[...document.querySelectorAll("
            "'#ovx-launcher-menu .ovx-menu-slider')].map(e => e.offsetHeight))"
        )
        assert slider_min >= _HIT_MIN, (
            f"launcher menu slider row shortest offsetHeight {slider_min}px < "
            f"--hit-min {_HIT_MIN}px"
        )

        # The retired panel-set quick-swap leaves no element in the live menu.
        assert page.evaluate(
            "() => document.querySelectorAll("
            "'#ovx-launcher-menu .ovx-menu-panelset').length"
        ) == 0, "no .ovx-menu-panelset element may render (panel-set retired)"

        # Visual proof artifact for the operator (menu only exists post-tap).
        SCREENSHOTS.mkdir(parents=True, exist_ok=True)
        menu = page.query_selector("#ovx-launcher-menu")
        menu.screenshot(path=str(SCREENSHOTS / "overlay_launcher_menu.png"))

        assert not errors, f"overlay page errors: {errors}"
    finally:
        ctx.close()
