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

# Wait predicate: the menu is open AND its first action row has rendered.
_MENU_READY = (
    "document.querySelector('#ovx-launcher-menu.ovx-menu-open "
    "  .ovx-menu-row') !== null"
)

# Describe document.activeElement in menu terms: which control class it carries,
# which panel row it belongs to (row.dataset.ovxTarget - the STABLE key the fix
# must restore by, since _renderMenu destroys the node itself), and the toggle's
# rendered on/off state. Returns tag "BODY" with empty fields when focus has been
# dropped to the document, which is exactly the defect this pins.
_ACTIVE_INFO = """
() => {
  const a = document.activeElement;
  if (!a) return null;
  const row = (a.closest && a.closest('.ovx-menu-prow')) || null;
  return {
    tag: a.tagName || '',
    cls: (a.className && String(a.className)) || '',
    target: row ? (row.dataset.ovxTarget || '') : '',
    on: (a.dataset && a.dataset.on) || '',
    text: (a.textContent || '').slice(0, 32),
    in_menu: !!(a.closest && a.closest('#ovx-launcher-menu')),
  };
}
"""


def _open_menu(pw_browser, mock_server):
    """Open the overlay and tap the launcher so the layout menu is rendered."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    assert page.query_selector("#w-launcher"), "launcher widget must mount in overlay mode"
    assert page.evaluate(_TAP_LAUNCHER) is True, "launcher tap dispatched"
    page.wait_for_function(_MENU_READY, timeout=5_000)
    return ctx, page, errors


def test_launcher_menu_toggle_keyboard_activation_keeps_focus(mock_server, pw_browser):
    """Keyboard-activating a per-panel toggle must not drop focus to <body>.

    _renderMenu rebuilds the whole menu (menu.innerHTML = "") on every toggle, so
    the button the operator just pressed Enter on is destroyed under them. Without
    a focus-restore across the rebuild, document.activeElement falls back to BODY
    and a keyboard operator has to re-tab from the top of a 400+ element document
    after EVERY one of the 10 toggles - i.e. the menu is mouse-only.

    Repo trap class: any repainting host preserves document.activeElement across
    the repaint (see web/js/panels/overlay_ds_controls.js:367-378 for the sibling
    "never clobber a control the operator is interacting with" half).
    """
    ctx, page, errors = _open_menu(pw_browser, mock_server)
    try:
        toggle = page.locator("#ovx-launcher-menu .ovx-menu-toggle").first
        before = toggle.evaluate(
            "el => ({"
            " target: el.closest('.ovx-menu-prow').dataset.ovxTarget,"
            " on: el.dataset.on,"
            " prefix: el.textContent.slice(0, 4) })"
        )
        assert before["target"], "per-panel row must carry data-ovx-target"
        assert before["on"] in ("0", "1"), f"unexpected toggle state {before['on']!r}"

        # KEYBOARD activation (locator.press focuses, then sends the key) - the
        # mouse path is already covered by the hit-target test above.
        toggle.press("Enter")
        page.wait_for_timeout(120)  # let any restore land (sync or rAF-deferred)

        after = page.evaluate(_ACTIVE_INFO)
        assert after is not None, "document.activeElement unreadable"
        assert after["tag"] != "BODY", (
            "focus was dropped to <body> by the _renderMenu rebuild - a keyboard "
            "operator must re-tab the whole document after every toggle "
            f"(activeElement: {after})"
        )
        assert after["in_menu"], f"focus left the launcher menu entirely: {after}"
        assert "ovx-menu-toggle" in after["cls"], (
            f"focus did not land back on a panel toggle: {after}"
        )
        assert after["target"] == before["target"], (
            "focus landed on a DIFFERENT panel's toggle "
            f"(was {before['target']}, now {after['target']})"
        )

        # The guarded behaviour still happens: the panel actually toggled.
        assert after["on"] != before["on"], (
            f"toggle state did not flip (still {after['on']!r})"
        )
        now_prefix = page.evaluate(
            "() => document.querySelector('#ovx-launcher-menu .ovx-menu-toggle')"
            ".textContent.slice(0, 4)"
        )
        assert now_prefix != before["prefix"], (
            f"rendered [x]/[ ] prefix did not change (still {now_prefix!r})"
        )
        assert now_prefix in ("[x] ", "[ ] "), f"unexpected prefix {now_prefix!r}"

        assert not errors, f"overlay page errors: {errors}"
    finally:
        ctx.close()


def test_launcher_menu_reset_keyboard_activation_keeps_focus(mock_server, pw_browser):
    """"Reset all panels" rebuilds the menu the same way - focus must survive.

    Same root cause as the per-panel toggle: the handler calls resetOverlayLayout()
    then _renderMenu(menu), which destroys the .ovx-menu-reset button that is
    currently focused.
    """
    ctx, page, errors = _open_menu(pw_browser, mock_server)
    try:
        reset = page.locator("#ovx-launcher-menu .ovx-menu-reset")
        assert reset.count() == 1, "exactly one reset button must render"

        reset.press("Enter")
        page.wait_for_timeout(120)

        after = page.evaluate(_ACTIVE_INFO)
        assert after is not None, "document.activeElement unreadable"
        assert after["tag"] != "BODY", (
            "focus was dropped to <body> by the reset rebuild "
            f"(activeElement: {after})"
        )
        assert after["in_menu"], f"focus left the launcher menu entirely: {after}"
        assert "ovx-menu-reset" in after["cls"], (
            f"focus did not land back on the reset button: {after}"
        )

        assert not errors, f"overlay page errors: {errors}"
    finally:
        ctx.close()


def test_launcher_menu_render_does_not_steal_focus(mock_server, pw_browser):
    """The restore must be a RESTORE, never a grab.

    _renderMenu also runs on plain menu-open (_setMenu(true)), where focus was
    never inside the menu - a pointer tap on the launcher square focuses nothing.
    The focus-preservation fix must be a no-op on that path; pulling focus into
    the menu would move the operator's caret out from under them. This is the
    other half of the requirement and is NOT covered by the two red-first tests
    above (it guards the fix against over-reach rather than pinning the defect).
    """
    ctx, page, errors = _open_menu(pw_browser, mock_server)
    try:
        # Close, then re-open: the second open re-runs _renderMenu while focus
        # sits on <body> (a pointer tap on a plain div focuses nothing).
        page.evaluate(_TAP_LAUNCHER)
        page.wait_for_function(
            "document.querySelector('#ovx-launcher-menu.ovx-menu-open') === null",
            timeout=5_000,
        )
        assert page.evaluate("() => document.activeElement.tagName") == "BODY"

        page.evaluate(_TAP_LAUNCHER)
        page.wait_for_function(_MENU_READY, timeout=5_000)

        after = page.evaluate(_ACTIVE_INFO)
        assert after is not None, "document.activeElement unreadable"
        assert not after["in_menu"], (
            f"menu render STOLE focus from outside the menu: {after}"
        )
        assert after["tag"] == "BODY", f"focus moved unexpectedly: {after}"

        assert not errors, f"overlay page errors: {errors}"
    finally:
        ctx.close()


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
