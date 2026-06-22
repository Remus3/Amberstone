"""
tests/snapshot_panels/test_lobby_view.py
Pre-Game Lobby VIEW snapshot coverage - RC2 redesign #5.

Renders the full-page Lobby view (#view-lobby, gated visible by
body[data-view="lobby"]) against the ui_mock lobby fixture through the
headless mock-server + Playwright harness. This is the reproducible
stand-in for the live self-signed-HTTPS :8888 visual check: Claude_Preview
cannot attach the self-signed cert and 1-PC (ADR-011) has no separate-
machine MCP visual path, so the redesign visual validation runs here in CI.
Mirrors test_home_view.py and test_champ_select_view.py.

Drive path: /?ui_mock=1#lobby. main.js boot flips body.dataset.uiMock; with
an empty SSE state the auto-derive lands on "home" (mode=client / !live), so
the #lobby hash is NOT treated as a stale game-state surface and the lobby
view wins the router (applyView("lobby") stamps body[data-view="lobby"],
which un-hides #view-lobby). The viewId=="lobby" branch fires
_lobbyViewWireOnce() + _lobbyViewRefresh() (main.js:731); under ui_mock the
refresh short-circuits to /data/ui_mock/lobby.json (_lobbyMockLoad,
main.js:3542) and paints the fixture's `lobby` block instead of the live
state.latest.lcu feed.

The fixture's lobby.queue_name ("Ranked Solo/Duo") populates #lv-queue-name
(its pre-render placeholder is "-"); _lobbyViewRefresh uppercases it
(main.js:4863). Waiting for that text to leave "-" is the async-render
landing signal. The same refresh calls _renderPartyMembers(lobby), which
paints one .lobby-member-row per fixture member into #lv-members-list, so
the party roster is the rendered-structure assertion. (Note: the fixture's
top-level `mains` + `top8` keys do NOT flow through ui_mock - _renderMains
/ _renderTop8 read state.latest.lcu directly, which is empty here - so this
test asserts only the lobby/party block that the mock path actually drives.)

Asserts: the lobby view is visible with body[data-view]=="lobby", the queue
name rendered from the fixture, the party roster mounted at least one
member row, and no unhandled JS errors fire. Screenshots the view for the
audit trail (this is the capture the redesign cycle produces).
"""
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"


def _open_lobby(pw_browser, mock_server):
    from tests.snapshot_panels.conftest import _WS_STUB

    # Empty SSE state -> main.js auto-derive resolves to "home" (mode
    # client / no liveclient), so the #lobby hash is not treated as a
    # stale game-state surface and the lobby view wins the router.
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

    url = mock_server.url + "/?ui_mock=1#lobby"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    # Wait for the async mock render: lobby.queue_name replaces the "-"
    # placeholder in #lv-queue-name (proves _lobbyViewRefresh landed the
    # fixture's lobby block).
    page.wait_for_function(
        "document.querySelector('#lv-queue-name') && "
        "document.querySelector('#lv-queue-name').textContent.trim() "
        "!== '-' && "
        "document.querySelector('#lv-queue-name').textContent.trim() "
        "!== ''",
        timeout=10_000,
    )
    return ctx, page, errors


def test_lobby_view_renders(mock_server, pw_browser):
    ctx, page, errors = _open_lobby(pw_browser, mock_server)
    try:
        view = page.locator("#view-lobby")
        assert view.is_visible(), "#view-lobby not visible on lobby view"

        # body[data-view] drives the view-section's forced-visible CSS rule.
        dv = page.evaluate("document.body.dataset.view")
        assert dv == "lobby", f"body[data-view] {dv!r} != 'lobby'"

        # Queue name rendered from the fixture (placeholder "-" replaced).
        qname = (
            page.locator("#lv-queue-name").text_content() or ""
        ).strip()
        assert qname and qname != "-", "queue name not rendered from fixture"

        SCREENSHOTS.mkdir(exist_ok=True)
        view.screenshot(path=str(SCREENSHOTS / "lobby.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [lobby]: {errors[:3]}"


def test_lobby_party_roster_rows(mock_server, pw_browser):
    """The party roster mounts at least one member row from the fixture
    lobby.members (3 members), proving _renderPartyMembers landed."""
    ctx, page, errors = _open_lobby(pw_browser, mock_server)
    try:
        page.wait_for_function(
            "document.querySelectorAll("
            "'#lv-members-list .lobby-member-row').length > 0",
            timeout=10_000,
        )
        rows = page.locator("#lv-members-list .lobby-member-row")
        assert rows.count() >= 1, (
            f"expected >=1 party member row, got {rows.count()}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [lobby roster]: {errors[:3]}"


def test_lobby_card_has_corner_brackets(mock_server, pw_browser):
    """RC2 Hextech reskin: lobby panels carry the gold corner-bracket
    motif. The .lobby-view-card ::before pseudo paints a 14px L-stroke in
    the accent color - assert it computes a non-zero accent border so the
    bracket treatment is actually live (the reskin's signature cue)."""
    ctx, page, errors = _open_lobby(pw_browser, mock_server)
    try:
        card = page.locator("#view-lobby .lobby-view-card").first
        assert card.count() > 0, "no .lobby-view-card in lobby view"
        # The ::before bracket has a 2px top + left border in --accent.
        width = page.evaluate(
            "getComputedStyle("
            "document.querySelector('#view-lobby .lobby-view-card'),"
            "'::before').borderTopWidth"
        )
        assert width and width != "0px", (
            f"lobby card corner bracket missing (border-top-width={width!r})"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [lobby brackets]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F in the new
    test + the lobby fixture it drives. (header.css carries pre-existing
    non-ASCII glyphs that predate this slice; mirroring the sibling view
    tests, the CSS is not ASCII-checked here - only this slice's authored
    test + the JSON fixture are.)"""
    targets = [
        Path(__file__),
        ROOT / "web" / "data" / "ui_mock" / "lobby.json",
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
