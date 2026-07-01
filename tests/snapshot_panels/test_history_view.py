"""
tests/snapshot_panels/test_history_view.py
History VIEW snapshot coverage - RC2 redesign #6.

Renders the full-page History view (#view-history, gated visible by
body[data-view="history"]) against the ui_mock history fixture through the
headless mock-server + Playwright harness. This is the reproducible
stand-in for the live self-signed-HTTPS :8888 visual check: Claude_Preview
cannot attach the self-signed cert and 1-PC (ADR-011) has no separate-
machine MCP visual path, so the redesign visual validation runs here in CI.
Mirrors test_lobby_view.py and test_home_view.py.

Drive path: /?ui_mock=1#history. main.js boot flips body.dataset.uiMock;
with an empty SSE state the auto-derive lands on "home" (mode=client /
!live), and #history is a sticky non-game-state hash (main.js:958-959), so
the history view wins the router (applyView("history") stamps
body[data-view="history"], which un-hides #view-history). The
viewId=="history" branch fires _historyWireOnce() + _historyFetchAndRender()
(main.js:765); under ui_mock the fetch short-circuits to
/data/ui_mock/history.json (_historyMockLoad, main.js:1856) and slices the
"14d" scope (5 sessions) instead of the live /api/history feed.

The fixture's scopes["14d"] has 5 sessions, so _historyFetchAndRender sets
#history-session-count to "5 sessions" (its pre-render placeholder is "-")
and paints one .history-session-row per session into #history-session-list.
Waiting for that count text to leave "-" is the async-render landing signal;
the session rows are the rendered-structure assertion.

Asserts: the history view is visible with body[data-view]=="history", the
session count rendered from the fixture, the session list mounted at least
one row, and no unhandled JS errors fire. Screenshots the view for the audit
trail (this is the capture the redesign cycle produces).
"""
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"


def _open_history(pw_browser, mock_server):
    from tests.snapshot_panels.conftest import _WS_STUB

    # Empty SSE state -> main.js auto-derive resolves to "home" (mode
    # client / no liveclient); #history is a sticky non-game-state hash,
    # so the history view wins the router.
    mock_server._store["data"] = {}

    # Spec 1920x1080 design baseline (docs/UI_SCALE_SPEC_V2.md) so the
    # capture matches the operator's monitor instead of Playwright's
    # default 1280-wide viewport.
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    url = mock_server.url + "/?ui_mock=1#history"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    # Wait for the async mock render: the session count replaces the "-"
    # placeholder in #history-session-count (proves _historyFetchAndRender
    # landed the fixture's "14d" scope slice).
    page.wait_for_function(
        "document.querySelector('#history-session-count') && "
        "document.querySelector('#history-session-count').textContent.trim() "
        "!== '-' && "
        "document.querySelector('#history-session-count').textContent.trim() "
        "!== ''",
        timeout=10_000,
    )
    return ctx, page, errors


def test_history_view_renders(mock_server, pw_browser):
    ctx, page, errors = _open_history(pw_browser, mock_server)
    try:
        view = page.locator("#view-history")
        assert view.is_visible(), "#view-history not visible on history view"

        # body[data-view] drives the view-section's forced-visible CSS rule.
        dv = page.evaluate("document.body.dataset.view")
        assert dv == "history", f"body[data-view] {dv!r} != 'history'"

        # Session count rendered from the fixture (placeholder "-" replaced).
        count = (
            page.locator("#history-session-count").text_content() or ""
        ).strip()
        assert count and count != "-", (
            "session count not rendered from fixture"
        )

        SCREENSHOTS.mkdir(exist_ok=True)
        view.screenshot(path=str(SCREENSHOTS / "history.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [history]: {errors[:3]}"


def test_history_session_rows(mock_server, pw_browser):
    """The session list mounts at least one row from the fixture
    scopes["14d"].sessions (5 sessions), proving the render landed."""
    ctx, page, errors = _open_history(pw_browser, mock_server)
    try:
        page.wait_for_function(
            "document.querySelectorAll("
            "'#history-session-list .history-session-row').length > 0",
            timeout=10_000,
        )
        rows = page.locator("#history-session-list .history-session-row")
        assert rows.count() >= 1, (
            f"expected >=1 session row, got {rows.count()}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [history rows]: {errors[:3]}"


def test_history_card_has_corner_brackets(mock_server, pw_browser):
    """RC2 Hextech reskin: history panels carry the gold corner-bracket
    motif. The .history-card ::before pseudo paints a 14px L-stroke in the
    accent color - assert it computes a non-zero accent border so the
    bracket treatment is actually live (the reskin's signature cue)."""
    ctx, page, errors = _open_history(pw_browser, mock_server)
    try:
        card = page.locator("#view-history .history-card").first
        assert card.count() > 0, "no .history-card in history view"
        # The ::before bracket has a 2px top + left border in --accent.
        width = page.evaluate(
            "getComputedStyle("
            "document.querySelector('#view-history .history-card'),"
            "'::before').borderTopWidth"
        )
        assert width and width != "0px", (
            f"history card corner bracket missing (border-top-width={width!r})"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [history brackets]: {errors[:3]}"


def test_history_season_win_rate(mock_server, pw_browser):
    """LIFT 4 (Part 1): the season-stats card surfaces the fixture
    win_rate as a percentage and the stale "(needs Riot key)" stub note
    is gone. The 14d fixture win_rate is 64.3 (percent) -> "64.3%"."""
    ctx, page, errors = _open_history(pw_browser, mock_server)
    try:
        page.wait_for_function(
            "document.querySelector('#history-season-wr') && "
            "document.querySelector('#history-season-wr')"
            ".textContent.indexOf('%') >= 0",
            timeout=10_000,
        )
        wr = (page.locator("#history-season-wr").text_content() or "").strip()
        assert wr == "64.3%", f"season WR {wr!r} != '64.3%'"
        assert "needs Riot key" not in wr, (
            "stale '(needs Riot key)' note still present in season WR"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [history WR]: {errors[:3]}"


def _count_match_rows(page, result=None):
    sel = "#history-match-list .history-match-row"
    if result:
        sel = f"#history-match-list .history-match-row[data-result='{result}']"
    return page.locator(sel).count()


def test_history_client_side_filters(mock_server, pw_browser):
    """LIFT 4 (Part 2): the result toggle + champion select filter the
    GLOBAL match list (all sessions in scope). The 14d fixture has 8 wins
    / 6 losses across 14 matches; clicking W shows only win rows; then
    narrowing to Jinx leaves only the 2 Jinx wins. Interactive controls
    clear the 44px fingertip floor."""
    ctx, page, errors = _open_history(pw_browser, mock_server)
    try:
        # Toolbar populated from the fixture (champion select gets the
        # distinct champions plus the "All" default).
        page.wait_for_function(
            "document.querySelectorAll("
            "'#history-filter-champion option').length > 1",
            timeout=10_000,
        )

        # 44px hit-target floor on every interactive control.
        for css in (
            "#history-filter-champion",
            "#history-filter-mode",
            "#history-filter-result .history-filter-rbtn",
            ".history-filter-grade",
        ):
            h = page.evaluate(
                "(s) => document.querySelector(s)"
                ".getBoundingClientRect().height",
                css,
            )
            assert h >= 44, f"control {css!r} height {h} < 44px"

        # Result -> W: only win rows render, count == fixture win count (8).
        page.click("#history-filter-result .history-filter-rbtn[data-result='win']")
        page.wait_for_function(
            "document.querySelector('#history-detail-head')"
            ".textContent.indexOf('FILTERED') >= 0",
            timeout=10_000,
        )
        total = _count_match_rows(page)
        wins = _count_match_rows(page, result="win")
        assert total == 8, f"expected 8 win rows, got {total}"
        assert wins == 8, f"expected 8 data-result=win rows, got {wins}"
        cnt = (page.locator("#history-filter-count").text_content() or "").strip()
        assert cnt.startswith("8"), f"count readout {cnt!r} != '8 matches'"

        # Narrow to Jinx: only the 2 Jinx wins remain.
        page.select_option("#history-filter-champion", "Jinx")
        page.wait_for_function(
            "document.querySelectorAll("
            "'#history-match-list .history-match-row').length === 2",
            timeout=10_000,
        )
        jinx = _count_match_rows(page)
        assert jinx == 2, f"expected 2 Jinx win rows, got {jinx}"
        champs = page.evaluate(
            "Array.from(document.querySelectorAll("
            "'#history-match-list .history-match-row'))"
            ".map(r => r.dataset.champion)"
        )
        assert all(c == "Jinx" for c in champs), (
            f"non-Jinx rows leaked into filter: {champs}"
        )

        SCREENSHOTS.mkdir(exist_ok=True)
        body = page.locator("#history-body")
        body.screenshot(path=str(SCREENSHOTS / "history_filters.png"))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [history filters]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F in the new
    test + the history fixture it drives. (header.css carries pre-existing
    non-ASCII glyphs that predate this slice; mirroring the sibling view
    tests, the CSS is not ASCII-checked here - only this slice's authored
    test + the JSON fixture are.)"""
    targets = [
        Path(__file__),
        ROOT / "web" / "data" / "ui_mock" / "history.json",
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"


def test_history_session_wl_rollup(mock_server, pw_browser):
    """OQ8 (QA37): each session row carries a client-computed W-L chip
    (strict win === true / === false counts over the session's matches),
    and clicking a session lands the W-L in the detail head. Expected
    values derive from the fixture's 14d scope (session 0: 2W-2L over 4
    matches; session 3: 1W-0L; session 4: 0W-1L)."""
    ctx, page, errors = _open_history(pw_browser, mock_server)
    try:
        rows = page.locator("#history-session-list .history-session-row")
        assert rows.count() == 5, f"expected 5 session rows, got {rows.count()}"
        first_wl = rows.nth(0).locator(".hs-wl")
        assert first_wl.count() == 1, "first session row missing the .hs-wl chip"
        assert first_wl.inner_text().replace("\n", "") == "2W-2L", (
            f"first session W-L chip wrong: {first_wl.inner_text()!r}"
        )
        # Wins/losses are separately colored spans (redundant W/L letters).
        assert rows.nth(0).locator(".hs-wl .hs-w").inner_text() == "2W"
        assert rows.nth(0).locator(".hs-wl .hs-l").inner_text() == "2L"
        # Session 4 (0 wins, 1 loss) still shows a chip - decided matches
        # exist even though wins are zero.
        assert rows.nth(4).locator(".hs-wl").inner_text().replace("\n", "") == "0W-1L"
        # Clicking the first session lands the W-L in the detail head.
        rows.nth(0).click()
        page.wait_for_function(
            "document.querySelector('#history-detail-head').textContent"
            ".includes('2W-2L')",
            timeout=5_000,
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [session W-L]: {errors[:3]}"
