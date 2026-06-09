"""HIST1 + HIST2 end-to-end view flow (Playwright).

Drives the real DOM through the headless mock-server + Playwright harness
to prove the full operator flow:

  1. The live Post Game Review (#view-last-match) renders the operator's
     real most-recent match (LIVE champion).
  2. Clicking a populated History match row (HIST1) opens the DETACHED
     historical PGR view (#view-historical-pgr) populated with THAT match
     (HISTORICAL champion) - "as if it had just ended".
  3. NO CLOBBER: the live PGR's hero champion is UNCHANGED after opening
     the historical match - the operator's real most-recent-game state is
     never mutated.
  4. The Back action returns to the History view.

The shared conftest mock-server returns {} for unmatched /api/*, so this
test installs page.route stubs for /api/history, the live /api/last-match
(latest), and the historical /api/last-match?match_ts= (a DIFFERENT
match). This keeps the stub local - it does NOT modify the shared
conftest. Mirrors test_last_match_view.py's harness + _WS_STUB usage.

ASCII-only authored content (CLAUDE.md hard rule).
"""
import json
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"

LIVE_CHAMP = "Jhin"           # operator's real most-recent game
HIST_CHAMP = "Orianna"        # the clicked archived match
HIST_TS = "2026-05-30 21:15:00"

# Minimal /api/last-match payloads. enriched=None keeps the roster table
# in its pending state - we only assert on the hero champion here, which
# is the load-bearing no-clobber signal.
_LIVE_PAYLOAD = {
    "found": True, "history_count": 0,
    "match": {
        "id": 999, "timestamp": "2026-05-31 23:00:00", "mode": "SR",
        "champion": LIVE_CHAMP, "grade": "A", "kda_str": "8/3/10",
        "kda_ratio": 6.0, "duration_s": 1700, "kills": 8, "deaths": 3,
        "assists": 10, "cs": 190, "cs_per_min": 6.7, "gold": 13500,
        "gold_per_min": 476, "kp_pct": 60, "label": "", "ds_picks": [],
        "enriched": None,
    },
    "quick_review": {"right": [], "wrong_team": [], "my_chronic": []},
}
_HIST_PAYLOAD = {
    "found": True, "history_count": 5,
    "match": {
        "id": 412, "timestamp": HIST_TS, "mode": "SR",
        "champion": HIST_CHAMP, "grade": "S", "kda_str": "12/2/14",
        "kda_ratio": 13.0, "duration_s": 1600, "kills": 12, "deaths": 2,
        "assists": 14, "cs": 230, "cs_per_min": 8.6, "gold": 15800,
        "gold_per_min": 593, "kp_pct": 72, "label": "", "ds_picks": [],
        "enriched": None,
    },
    "quick_review": {"right": [], "wrong_team": [], "my_chronic": []},
}
_HISTORY_PAYLOAD = {
    "scope": "14d",
    "season_stats": {"total": 100, "avg_kda": 2.5, "favorite": HIST_CHAMP},
    "sessions": [
        {
            "date": "2026-05-30", "games": 1, "duration_label": "26m",
            "started_at": HIST_TS, "last_at": HIST_TS,
            "matches": [
                {"timestamp": HIST_TS, "mode": "SR", "champion": HIST_CHAMP,
                 "grade": "S", "kda": "12/2/14"},
            ],
        },
    ],
}


def _install_routes(page):
    """Stub the three endpoints the flow touches. The historical fetch is
    distinguished from the live fetch by the match_ts query param."""
    def _handler(route):
        req = route.request
        url = req.url
        if "/api/history" in url:
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps(_HISTORY_PAYLOAD))
        if "/api/last-match" in url:
            payload = _HIST_PAYLOAD if "match_ts=" in url else _LIVE_PAYLOAD
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps(payload))
        return route.continue_()

    page.route("**/api/history*", _handler)
    page.route("**/api/last-match*", _handler)


def _new_page(pw_browser, mock_server):
    from tests.snapshot_panels.conftest import _WS_STUB
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    _install_routes(page)
    return ctx, page


def test_history_row_click_opens_detached_pgr_without_clobber(mock_server, pw_browser):
    ctx, page = _new_page(pw_browser, mock_server)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        # 1. Land on the live PGR and let it render the LIVE champion.
        page.goto(mock_server.url + "/#last-match",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "document.querySelector('#lm-champion-name') && "
            f"document.querySelector('#lm-champion-name').textContent.trim() === '{LIVE_CHAMP}'",
            timeout=10_000,
        )

        # 2. Navigate to History; the single session auto-selects? No - the
        # session list requires a click. Select the session, then the match
        # row renders. Drive via hash + the in-page wiring.
        page.evaluate("location.hash = '#history'")
        page.wait_for_selector("#history-session-list .history-session-row",
                               timeout=10_000)
        page.locator("#history-session-list .history-session-row").first.click()
        row = page.wait_for_selector("#history-match-list .history-match-row",
                                     timeout=10_000)

        # 3. HIST1: click the match row -> detached historical PGR.
        row.click()
        # The section keeps its `hidden` attribute; the active view is
        # revealed via CSS (body[data-view] #view-X { display:block }) like
        # every other view, so wait on computed visibility, not the attr.
        page.wait_for_selector("#view-historical-pgr", state="visible", timeout=10_000)
        page.wait_for_function(
            "document.querySelector('#hpgr-champion-name') && "
            f"document.querySelector('#hpgr-champion-name').textContent.trim() === '{HIST_CHAMP}'",
            timeout=10_000,
        )

        # The detached view is visible + shows the HISTORICAL champion.
        assert page.locator("#view-historical-pgr").is_visible()
        hpgr_champ = (page.locator("#hpgr-champion-name").text_content() or "").strip()
        assert hpgr_champ == HIST_CHAMP, f"detached PGR champ {hpgr_champ!r} != {HIST_CHAMP!r}"

        # 4. NO CLOBBER: the live PGR hero champion is UNCHANGED. The live
        # #view-last-match section is hidden now, but its DOM must still
        # carry the operator's real most-recent champion - the historical
        # render must not have written into it.
        lm_champ = (page.locator("#lm-champion-name").text_content() or "").strip()
        assert lm_champ == LIVE_CHAMP, (
            f"live PGR clobbered: #lm-champion-name {lm_champ!r} != {LIVE_CHAMP!r}"
        )

        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#view-historical-pgr").screenshot(
            path=str(SCREENSHOTS / "historical-pgr.png"))

        # 5. Back returns to History.
        page.locator("#hpgr-back").click()
        page.wait_for_selector("#view-history", state="visible", timeout=10_000)
        assert page.locator("#view-history").is_visible()
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors: {errors[:3]}"


def test_session_row_click_opens_detached_pgr(mock_server, pw_browser):
    """The Session page rows are wired too (they were equally inert
    pre-fix). The session summary endpoint returns the same single match;
    clicking it opens the detached PGR."""
    ctx, page = _new_page(pw_browser, mock_server)

    # Add a /api/session/summary stub for this test.
    def _sess_handler(route):
        body = {
            "window_label": "current session", "games": 1,
            "time_played_s": 1600, "started_at": HIST_TS, "last_at": HIST_TS,
            "total_kda": "12/2/14", "avg_kda": 13.0, "grades": {"S": 1},
            "modes": {"SR": 1}, "champions": [],
            "matches": [
                {"timestamp": HIST_TS, "mode": "SR", "champion": HIST_CHAMP,
                 "grade": "S", "kda": "12/2/14"},
            ],
        }
        return route.fulfill(status=200, content_type="application/json",
                             body=json.dumps(body))
    page.route("**/api/session/summary*", _sess_handler)

    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + "/#session",
                  wait_until="domcontentloaded", timeout=15_000)
        row = page.wait_for_selector("#session-matches .history-match-row",
                                     timeout=10_000)
        row.click()
        # The section keeps its `hidden` attribute; the active view is
        # revealed via CSS (body[data-view] #view-X { display:block }) like
        # every other view, so wait on computed visibility, not the attr.
        page.wait_for_selector("#view-historical-pgr", state="visible", timeout=10_000)
        page.wait_for_function(
            "document.querySelector('#hpgr-champion-name') && "
            f"document.querySelector('#hpgr-champion-name').textContent.trim() === '{HIST_CHAMP}'",
            timeout=10_000,
        )
        assert page.locator("#view-historical-pgr").is_visible()
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
