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


def _open_lobby_capture_autoaccept(pw_browser, mock_server):
    """Unified-toggle opener: same router drive as _open_lobby but records
    every POST to /api/lcu/auto-accept (the in-process pref route) AND stubs
    /api/lcu-cmd (the LCU-agent set_config path the existing #lv-auto-accept
    toggle already fires) so neither hits the 404 mock backend. The routes are
    registered on the context BEFORE navigation. This proves the SINGLE
    existing "Auto Accept" toggle now also drives core.auto_accept_pref."""
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    # Captured pref POSTs (each entry is the decoded JSON body). A list so the
    # route handler (a closure) can append across calls.
    pref_posts: list = []

    def _handle_pref(route, request):
        import json as _json

        if request.method == "POST":
            try:
                pref_posts.append(_json.loads(request.post_data or "{}"))
            except Exception:  # noqa: BLE001
                pref_posts.append({})
        route.fulfill(
            status=200,
            content_type="application/json",
            body=_json.dumps({"ok": True, "enabled": True}),
        )

    def _handle_lcu_cmd(route, request):
        import json as _json

        # The existing set_config path posts here first; answer with a queue
        # id so lcuPollResult resolves quickly and the inflight guard clears.
        route.fulfill(
            status=200,
            content_type="application/json",
            body=_json.dumps({"ok": True, "id": "stub-1"}),
        )

    def _handle_lcu_cmd_result(route, request):
        import json as _json

        route.fulfill(
            status=200,
            content_type="application/json",
            body=_json.dumps({"result": {"ok": True}}),
        )

    ctx.route("**/api/lcu/auto-accept", _handle_pref)
    ctx.route("**/api/lcu-cmd", _handle_lcu_cmd)
    ctx.route("**/api/lcu-cmd-result*", _handle_lcu_cmd_result)

    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    url = mock_server.url + "/?ui_mock=1#lobby"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "document.querySelector('#lv-queue-name') && "
        "document.querySelector('#lv-queue-name').textContent.trim() "
        "!== '-' && "
        "document.querySelector('#lv-queue-name').textContent.trim() "
        "!== ''",
        timeout=10_000,
    )
    return ctx, page, errors, pref_posts


def test_existing_autoaccept_toggle_also_posts_pref(mock_server, pw_browser):
    """Unified toggle: clicking the EXISTING #lv-auto-accept control now also
    fires a POST to /api/lcu/auto-accept with an {enabled: <bool>} body, so the
    one toggle gates BOTH the LCU-agent set_config path and the frozen
    in-process auto-accept loop (core.auto_accept_pref). Screenshots the lobby
    queue card for the audit trail."""
    ctx, page, errors, pref_posts = _open_lobby_capture_autoaccept(
        pw_browser, mock_server
    )
    try:
        sw = page.locator("#lv-auto-accept")
        assert sw.count() > 0, "#lv-auto-accept not in lobby view"

        # The control is enabled once the mock lobby block paints.
        page.wait_for_function(
            "document.querySelector('#lv-auto-accept') && "
            "!document.querySelector('#lv-auto-accept').disabled",
            timeout=10_000,
        )

        SCREENSHOTS.mkdir(exist_ok=True)
        card = page.locator("#view-lobby .lobby-view-card-queue").first
        if card.count() > 0:
            card.screenshot(path=str(SCREENSHOTS / "lobby_autoaccept.png"))
        else:
            page.locator("#view-lobby").screenshot(
                path=str(SCREENSHOTS / "lobby_autoaccept.png")
            )

        # Click the existing toggle -> the unified handler must POST the pref.
        sw.click()
        # Poll until the captured POST list records the pref write.
        import time as _time

        deadline = _time.time() + 8
        while _time.time() < deadline and not pref_posts:
            page.wait_for_timeout(100)
        assert pref_posts, (
            "clicking #lv-auto-accept fired NO POST to /api/lcu/auto-accept "
            "(unified toggle did not drive the pref route)"
        )
        body = pref_posts[-1]
        assert isinstance(body, dict) and "enabled" in body, (
            f"pref POST body missing 'enabled': {body!r}"
        )
        assert isinstance(body["enabled"], bool), (
            f"pref POST 'enabled' not a bool: {body!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [autoaccept]: {errors[:3]}"


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
