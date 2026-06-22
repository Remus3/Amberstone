"""
tests/snapshot_panels/test_session_view.py
Session VIEW snapshot coverage - RC2 redesign #8.

Renders the full-page Session view (#view-session, gated visible by
body[data-view="session"]) against the ui_mock session fixture through the
headless mock-server + Playwright harness. This is the reproducible
stand-in for the live self-signed-HTTPS :8888 visual check: Claude_Preview
cannot attach the self-signed cert and 1-PC (ADR-011) has no separate-
machine MCP visual path, so the redesign visual validation runs here in CI.
Mirrors test_history_view.py and test_lobby_view.py.

Drive path: /?ui_mock=1#session. main.js boot flips body.dataset.uiMock;
with an empty SSE state the auto-derive lands on "home" (mode=client /
!live), and #session is a sticky non-game-state hash (main.js:958-959), so
the session view wins the router (applyView("session") stamps
body[data-view="session"], which un-hides #view-session). The
viewId=="session" branch fires _sessionFetchAndRender() (main.js:764);
under ui_mock the fetch short-circuits to /data/ui_mock/session.json
(_sessionMockLoad, main.js:1781) instead of the live /api/session/summary
feed.

The fixture's games=6 populates #session-games (its pre-render placeholder
is "-"). Waiting for that text to leave "-" is the async-render landing
signal. The same render paints one .history-match-row per fixture match
into #session-matches (the session JS reuses the .history-match-row class
for its match + champion list rows), so the match list is the
rendered-structure assertion.

Asserts: the session view is visible with body[data-view]=="session", the
games count rendered from the fixture, the match list mounted at least one
row, and no unhandled JS errors fire. Screenshots the view for the audit
trail (this is the capture the redesign cycle produces).
"""
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"


def _open_session(pw_browser, mock_server):
    from tests.snapshot_panels.conftest import _WS_STUB

    # Empty SSE state -> main.js auto-derive resolves to "home" (mode
    # client / no liveclient); #session is a sticky non-game-state hash,
    # so the session view wins the router.
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

    url = mock_server.url + "/?ui_mock=1#session"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    # Wait for the async mock render: the games count replaces the "-"
    # placeholder in #session-games (proves _sessionFetchAndRender landed
    # the fixture).
    page.wait_for_function(
        "document.querySelector('#session-games') && "
        "document.querySelector('#session-games').textContent.trim() "
        "!== '-' && "
        "document.querySelector('#session-games').textContent.trim() "
        "!== ''",
        timeout=10_000,
    )
    return ctx, page, errors


def test_session_view_renders(mock_server, pw_browser):
    ctx, page, errors = _open_session(pw_browser, mock_server)
    try:
        view = page.locator("#view-session")
        assert view.is_visible(), "#view-session not visible on session view"

        # body[data-view] drives the view-section's forced-visible CSS rule.
        dv = page.evaluate("document.body.dataset.view")
        assert dv == "session", f"body[data-view] {dv!r} != 'session'"

        # Games count rendered from the fixture (placeholder "-" replaced).
        games = (
            page.locator("#session-games").text_content() or ""
        ).strip()
        assert games and games != "-", "games count not rendered from fixture"

        SCREENSHOTS.mkdir(exist_ok=True)
        view.screenshot(path=str(SCREENSHOTS / "session.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [session]: {errors[:3]}"


def test_session_match_rows(mock_server, pw_browser):
    """The match list mounts at least one row from the fixture matches
    (6 matches), proving _sessionFetchAndRender landed. The session JS
    reuses the .history-match-row class for its list rows."""
    ctx, page, errors = _open_session(pw_browser, mock_server)
    try:
        page.wait_for_function(
            "document.querySelectorAll("
            "'#session-matches .history-match-row').length > 0",
            timeout=10_000,
        )
        rows = page.locator("#session-matches .history-match-row")
        assert rows.count() >= 1, (
            f"expected >=1 match row, got {rows.count()}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [session rows]: {errors[:3]}"


def test_session_card_has_corner_brackets(mock_server, pw_browser):
    """RC2 Hextech reskin: session panels carry the gold corner-bracket
    motif. The .session-card ::before pseudo paints a 14px L-stroke in the
    accent color - assert it computes a non-zero accent border so the
    bracket treatment is actually live (the reskin's signature cue)."""
    ctx, page, errors = _open_session(pw_browser, mock_server)
    try:
        card = page.locator("#view-session .session-card").first
        assert card.count() > 0, "no .session-card in session view"
        # The ::before bracket has a 2px top + left border in --accent.
        width = page.evaluate(
            "getComputedStyle("
            "document.querySelector('#view-session .session-card'),"
            "'::before').borderTopWidth"
        )
        assert width and width != "0px", (
            f"session card corner bracket missing (border-top-width={width!r})"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [session brackets]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F in the new
    test + the session fixture it drives. (header.css carries pre-existing
    non-ASCII glyphs that predate this slice; mirroring the sibling view
    tests, the CSS is not ASCII-checked here - only this slice's authored
    test + the JSON fixture are.)"""
    targets = [
        Path(__file__),
        ROOT / "web" / "data" / "ui_mock" / "session.json",
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
