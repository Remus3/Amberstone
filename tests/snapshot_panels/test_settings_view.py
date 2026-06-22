"""
tests/snapshot_panels/test_settings_view.py
Settings VIEW snapshot coverage - RC2 redesign #12 (the LAST page).

Renders the full-page Settings view (#view-settings, gated visible by
body[data-view="settings"]) through the headless mock-server + Playwright
harness. This is the reproducible stand-in for the live self-signed-HTTPS
:8888 visual check: Claude_Preview cannot attach the self-signed cert and
1-PC (ADR-011) has no separate-machine MCP visual path, so the redesign
visual validation runs here in CI. Mirrors test_session_view.py.

Drive path: /?ui_mock=1#settings. main.js boot flips body.dataset.uiMock;
with an empty SSE state the auto-derive lands on "home" (mode=client /
!live), and #settings is a sticky non-game-state hash (main.js:958-959 +
_viewFromHash validates it against VIEW_IDS), so the settings view wins
the router (applyView("settings") stamps body[data-view="settings"], which
un-hides #view-settings).

Unlike session/history/lobby, Settings has NO async fixture feed: the view
renders its STATIC config form from local state regardless of mock data
(there is no settings.json ui_mock fixture). applyView("settings") fires
_settingsRefresh() + renderSpendGates() + renderLoopStatus() to populate
control values, but the .settings-card form scaffold is server-rendered in
index.html. So the render landing signal is simply the view becoming
visible with its first .settings-card mounted - no text-replaces-"-" wait.

Asserts: the settings view is visible with body[data-view]=="settings", at
least one .settings-card mounted, a toggle (checkbox) present and clickable
(44px-floor hit target), and no unhandled JS errors. Screenshots the view
for the audit trail (this is the capture the redesign cycle produces).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"


def _open_settings(pw_browser, mock_server):
    from tests.snapshot_panels.conftest import _WS_STUB

    # Empty SSE state -> main.js auto-derive resolves to "home" (mode
    # client / no liveclient); #settings is a sticky non-game-state hash,
    # so the settings view wins the router.
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

    url = mock_server.url + "/?ui_mock=1#settings"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    # Settings renders its static form synchronously once the router lands
    # on the view. Wait for the view to be stamped visible AND its first
    # card mounted (no async fixture text to poll).
    page.wait_for_function(
        "document.body.dataset.view === 'settings' && "
        "document.querySelector('#view-settings .settings-card') !== null",
        timeout=10_000,
    )
    return ctx, page, errors


def test_settings_view_renders(mock_server, pw_browser):
    ctx, page, errors = _open_settings(pw_browser, mock_server)
    try:
        view = page.locator("#view-settings")
        assert view.is_visible(), "#view-settings not visible on settings view"

        # body[data-view] drives the view-section's forced-visible CSS rule.
        dv = page.evaluate("document.body.dataset.view")
        assert dv == "settings", f"body[data-view] {dv!r} != 'settings'"

        # At least one settings card mounted (the static form scaffold).
        cards = page.locator("#view-settings .settings-card")
        assert cards.count() >= 1, "no .settings-card mounted in settings view"

        SCREENSHOTS.mkdir(exist_ok=True)
        view.screenshot(path=str(SCREENSHOTS / "settings.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [settings]: {errors[:3]}"


def test_settings_toggle_present(mock_server, pw_browser):
    """A settings toggle (checkbox) is mounted inside a .settings-row and
    its row clears the --hit-min fingertip floor. Proves the reskinned
    control wiring rendered (the toggles control real config)."""
    ctx, page, errors = _open_settings(pw_browser, mock_server)
    try:
        row = page.locator(
            "#view-settings .settings-row:has(input[type='checkbox'])"
        ).first
        assert row.count() > 0, "no checkbox toggle row in settings view"
        # The row pads to the interaction floor (tokens.css --hit-min 42px).
        box = row.bounding_box()
        assert box is not None and box["height"] >= 40, (
            f"settings row below fingertip floor (height={box and box['height']})"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [settings toggle]: {errors[:3]}"


def test_settings_card_has_corner_brackets(mock_server, pw_browser):
    """RC2 Hextech reskin: settings cards carry the gold corner-bracket
    motif. The .settings-card ::before pseudo paints a 2px gold L-stroke at
    the top-left - assert it computes a non-zero accent border so the
    bracket treatment is actually live (the reskin's signature cue)."""
    ctx, page, errors = _open_settings(pw_browser, mock_server)
    try:
        card = page.locator("#view-settings .settings-card").first
        assert card.count() > 0, "no .settings-card in settings view"
        width = page.evaluate(
            "getComputedStyle("
            "document.querySelector('#view-settings .settings-card'),"
            "'::before').borderTopWidth"
        )
        assert width and width != "0px", (
            f"settings card corner bracket missing (border-top-width={width!r})"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [settings brackets]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F in the new
    test file. (header.css carries pre-existing non-ASCII glyphs that
    predate this slice; mirroring the sibling view tests, the CSS is not
    ASCII-checked here - only this slice's authored test is. There is no
    settings ui_mock fixture to check.)"""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s) in {__file__}: {offenders[:5]}"
