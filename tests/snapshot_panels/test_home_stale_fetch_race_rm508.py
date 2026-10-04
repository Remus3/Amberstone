"""RM-508: the home-view Playwright "flake" is a stale-response race.

Two home tests flaked the same way on CI (LEDGER 1456 companion reflow; RM-508
test_home_wl_strip) and both passed on a same-sha re-run. Root cause, found by
reading the render path rather than by re-running:

  * The startup tick can fire `_homeFetchAndRender` BEFORE the `?ui_mock=1`
    flag lands, so it requests the LIVE `/api/home/summary`
    (main.js applyView("home") comment says exactly this).
  * applyView("home") then clears the in-flight guard and fetches the MOCK
    fixture, which renders.
  * If the live request resolves SECOND, its payload (the mock server answers
    any unstubbed /api/* with `{}`) is rendered on top: `_homeRenderWlStrip(null)`
    wipes the 20 pips while `tonight_pick` is absent, so the coach pick that
    `_open_home` waits on stays painted. The next refetch is 20 s away, beyond
    the 10 s wait. A slow runner widens the window; Legion rarely opens it.

The fix is a request generation: a response that is not the newest request's
is dropped. This test forces the losing order deterministically by holding the
live response until after the mock render, then releasing it.
"""
from __future__ import annotations

import time

def test_a_stale_live_summary_cannot_overwrite_the_mock_render(mock_server, pw_browser):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    held = []
    page.route("**/api/home/summary*", lambda route: held.append(route))
    try:
        page.goto(mock_server.url + "/?ui_mock=1#home",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "document.querySelectorAll('#home-hero-rank-wl .home-wl-pip').length === 20",
            timeout=10_000,
        )
        if not held:
            # Force the live request the startup tick may or may not have made:
            # a mode-tab round trip clears the guard and refetches.
            page.evaluate("document.body.dataset.uiMock = '0'")
            page.locator(".home-mode-tab[data-hmode='ALL']").first.click()
            page.evaluate("document.body.dataset.uiMock = '1'")
            page.locator(".home-mode-tab[data-hmode='ALL']").first.click()
            page.wait_for_function(
                "document.querySelectorAll('#home-hero-rank-wl .home-wl-pip').length === 20",
                timeout=10_000,
            )
        assert held, "no live /api/home/summary request was made - race not exercised"
        for route in held:
            route.fulfill(status=200, content_type="application/json", body="{}")
        deadline = time.time() + 2.0
        while time.time() < deadline:
            page.wait_for_timeout(100)
        n = page.evaluate(
            "document.querySelectorAll('#home-hero-rank-wl .home-wl-pip').length")
        assert n == 20, f"a stale live response wiped the W/L strip ({n} pips left)"
    finally:
        ctx.close()
