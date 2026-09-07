"""
tests/snapshot_panels/test_aram_balance_view.py
ARAM balance-adjustment grid panel - populated capture + ui_mock wiring
regression (clears the R20 VISUAL OWED, ledger item 590/R20 `32467bb7`).

The #aram-balance-panel lives in the active-match view's BUILD pane and is
ARAM-mode-gated. It shipped wired into the LIVE-state render branch only
(main.js renderAramBalance call) - the ui_mock active-match branch
(`if (_amIsMock() && _amMockUrl())`) dispatched every sibling panel (ward
cue / spike cue / minimap / objective chips) but NOT renderAramBalance, so
the documented `?ui_mock=1&mode=aram#active-match` audit/preview path could
not render it. That gap is exactly why the populated capture was OWED.

Two layers:
  - test_main_js_wires_aram_balance_in_both_branches: a cheap static-source
    regression guard that renderAramBalance is dispatched in BOTH the
    ui_mock and the live branch (RED before the wiring fix: only 1 call).
  - test_aram_balance_panel_populated: drives the real ui_mock audit path,
    stubs /api/aram-balance with a populated map (the conftest mock returns
    {} for it), waits for the populated grid, asserts the self gold row +
    ally + enemy rows + buff/nerf chips, and writes the screenshot.

Mirrors test_active_match_view.py (the active-match view's nav path) rather
than test_augment_reco_panel.py (which uses /#last-match, a different view).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MAIN_JS = ROOT / "web" / "js" / "main.js"
SCREENSHOTS = Path(__file__).parent / "screenshots"

# Real 16.12.1 ARAM modifiers (canonical DDragon ids) for the
# active_match_aram.json fixture roster (Senna self + 4 ally + 5 enemy).
# Diverse spread so the capture exercises every chip kind: pure buff
# (Garen take-less), multi-nerf (Senna/Karthus/Annie/Janna/DrMundo), a
# deal-more buff (Ashe), healing/shielding nerfs, and fully-neutral rows
# (Lulu/Sona/Yasuo render the "neutral" path). "Mundo" is included as a
# display-name alias of the canonical "DrMundo" so the row resolves
# deterministically in the headless harness regardless of alias loading.
_BALANCE_MAP = {
    "ok": True,
    "patch": "16.12.1",
    "champions": {
        "Senna":   {"aramDamageDealt": 0.92, "aramDamageTaken": 1.05},
        "Lulu":    {},
        "Karthus": {"aramDamageDealt": 0.93, "aramDamageTaken": 1.05},
        "Garen":   {"aramDamageTaken": 0.95},
        "Sona":    {},
        "Yasuo":   {},
        "Ashe":    {"aramDamageDealt": 1.05},
        "Annie":   {"aramDamageDealt": 0.95, "aramDamageTaken": 1.05, "aramShielding": 0.9},
        "DrMundo": {"aramDamageDealt": 0.9, "aramDamageTaken": 1.05, "aramHealing": 0.9},
        "Mundo":   {"aramDamageDealt": 0.9, "aramDamageTaken": 1.05, "aramHealing": 0.9},
        "Janna":   {"aramDamageDealt": 0.95, "aramDamageTaken": 1.05, "aramHealing": 0.9},
    },
}


def test_main_js_wires_aram_balance_in_both_branches():
    """renderAramBalance must dispatch in BOTH render branches: the ui_mock
    active-match path AND the live-state path. A single call site means the
    ui_mock audit/preview path (`?ui_mock=1&mode=aram#active-match`) renders
    every other panel but not this one - the regression that left the
    populated capture OWED."""
    src = MAIN_JS.read_text(encoding="utf-8")
    calls = src.count("renderAramBalance(")
    assert calls >= 2, (
        f"renderAramBalance dispatched at only {calls} call site(s); expected "
        ">=2 (ui_mock branch + live branch). The ui_mock branch wiring is "
        "what makes the panel renderable on the documented audit path."
    )


def test_aram_balance_panel_populated(mock_server, pw_browser):
    """Drive the documented ui_mock audit path and capture the populated
    grid. RED before the ui_mock-branch wiring fix (panel never renders on
    this path -> no .ab-row-self)."""
    from tests.snapshot_panels.conftest import _WS_STUB

    # Empty SSE state -> main.js auto-derive resolves to "home"/"client", so
    # the #active-match hash is honored by the view router (mirrors
    # test_active_match_view._open_active_match).
    mock_server._store["data"] = {}

    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    # Serve the populated balance map (the conftest mock returns {} for it,
    # which would render every row "neutral").
    page.route("**/api/aram-balance", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(_BALANCE_MAP)))
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    try:
        url = mock_server.url + "/?ui_mock=1&mode=aram#active-match"
        page.goto(url, wait_until="domcontentloaded", timeout=15_000)
        # Wait for the populated grid: the self row plus at least one
        # buff/nerf chip (proves the stubbed map landed + re-rendered).
        page.wait_for_function(
            "document.querySelector('#aram-balance-panel .ab-row-self') && "
            "document.querySelectorAll('#aram-balance-panel .ab-chip').length > 0",
            timeout=10_000,
        )

        panel = page.locator("#aram-balance-panel")
        assert panel.is_visible(), "#aram-balance-panel not visible"

        # One self (gold-edge) row.
        assert page.locator("#aram-balance-panel .ab-row-self").count() == 1, (
            "expected exactly one SELF row"
        )
        # Enemy rows (5 CHAOS in the fixture; tolerate alias-resolution slack).
        assert page.locator("#aram-balance-panel .ab-row-enemy").count() >= 4, (
            "expected the enemy rows to render"
        )
        # Full roster populated (Senna self + 4 ally + 5 enemy = 10; tolerate
        # one alias miss).
        assert page.locator("#aram-balance-panel .ab-row").count() >= 9, (
            "expected the full ARAM roster to render"
        )
        # Status is never color-alone: both buff (good) and nerf (bad) chips
        # render, and the signed +/- value text carries the meaning.
        assert page.locator("#aram-balance-panel .ab-chip.ab-good").count() >= 1, (
            "expected at least one buff (ab-good) chip"
        )
        assert page.locator("#aram-balance-panel .ab-chip.ab-bad").count() >= 1, (
            "expected at least one nerf (ab-bad) chip"
        )

        SCREENSHOTS.mkdir(exist_ok=True)
        panel.screenshot(path=str(SCREENSHOTS / "aram-balance_aram.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors: {errors[:3]}"


def test_aram_balance_panel_is_placed_in_the_am_grid(mock_server, pw_browser):
    """R213: the panel must occupy a NAMED third row under BUILD, not an
    implicit auto-placed one.

    Before R213 `#aram-balance-panel` was the only visible direct .am-grid
    child with no `grid-area`, so the browser invented row 3 and the panel grew
    unbounded with the roster (measured 456px). The 1fr panes were NOT squeezed
    by it - see the active_match.css note - so what is pinned here is the named
    placement and the cap, not a height recovery. This drives the real page and
    reads COMPUTED style, so a mis-parsed `:has()` selector (which would
    silently drop the whole rule) fails here rather than in a live game.
    """
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.route("**/api/aram-balance", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(_BALANCE_MAP)))
    try:
        page.goto(mock_server.url + "/?ui_mock=1&mode=aram#active-match",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "document.querySelector('#aram-balance-panel .ab-row-self')",
            timeout=10_000,
        )
        geom = page.evaluate(
            "() => {"
            " const p = document.querySelector('#aram-balance-panel');"
            " const g = p.closest('.am-grid');"
            " const cs = getComputedStyle(g);"
            " return {rows: cs.gridTemplateRows.split(' ').length,"
            "         areas: cs.gridTemplateAreas,"
            "         rowStart: getComputedStyle(p).gridRowStart,"
            "         panelTop: p.getBoundingClientRect().top,"
            "         buildTop: g.querySelector('.am-pane-build')"
            "                    .getBoundingClientRect().top};"
            "}"
        )
        assert "aram" in geom["areas"], (
            "the live .am-grid carries no named aram area - the :has() rule "
            f"did not apply (areas={geom['areas']!r})"
        )
        assert geom["rows"] == 3, f"expected 3 explicit rows, got {geom['rows']}"
        assert geom["rowStart"] == "aram", (
            f"panel not placed in the named row (gridRowStart={geom['rowStart']!r})"
        )
        assert geom["panelTop"] > geom["buildTop"], "panel must sit under BUILD"

        # Visual proof at the 1920x1080 baseline. The active-match section is
        # content-sized by the MAP pane and already scrolls well past one
        # viewport, so scroll the placed row into view rather than capturing
        # the top of the page and calling it a capture of this panel.
        page.locator("#aram-balance-panel").scroll_into_view_if_needed()
        SCREENSHOTS.mkdir(exist_ok=True)
        page.screenshot(path=str(SCREENSHOTS / "aram-balance_grid_1920.png"))
    finally:
        page.close()
        ctx.close()


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s) in {Path(__file__)}: {offenders[:5]}"
