"""
tests/snapshot_panels/test_build_insights_view.py
Build Insights VIEW snapshot coverage - RC2 redesign #10.

Renders the full-page Build Insights view (#view-build-insights, the
8-tab selection-bias-corrected WPA analytics view, gated visible by
body[data-view="build-insights"]) against the ui_mock build_insights
fixture through the headless mock-server + Playwright harness. This is the
reproducible stand-in for the live self-signed-HTTPS :8888 visual check:
Claude_Preview cannot attach the self-signed cert and 1-PC (ADR-011) has
no separate-machine MCP visual path, so the redesign visual validation
runs here in CI. Mirrors test_user_builds_view.py and test_session_view.py.

Drive path: /?ui_mock=1#build-insights. main.js boot flips
body.dataset.uiMock; with an empty SSE state the auto-derive lands on
"home" (mode=client / !live), and #build-insights is a sticky
non-game-state hash (_viewFromHash returns it because it is in VIEW_IDS,
main.js:573-574 / lib/state.js:40), so the build-insights view wins the
router (applyView("build-insights") stamps body[data-view="build-insights"],
which un-hides #view-build-insights). The viewId=="build-insights" branch
fires renderBuildInsights() (main.js:802); the default Items tab flows
through _ensureFetched(_ITEMS_TAB), and under ui_mock the live
/api/item-wpa fetch is short-circuited to /data/ui_mock/build_insights.json
(_isMock / _mockLoad, build_insights.js:280-290) instead of the live feed.

The fixture's items array (11 rows) paints a .bi-table into
#bi-table-mount (a populated array skips the .bi-empty state). Waiting for
that .bi-table to mount is the async-render landing signal AND the
rendered-structure assertion.

Asserts: the build-insights view is visible with
body[data-view]=="build-insights", the default Items table mounted from the
fixture, and no unhandled JS errors fire. Screenshots the view for the
audit trail (this is the capture the redesign cycle produces).
"""
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"


def _open_build_insights(pw_browser, mock_server):
    from tests.snapshot_panels.conftest import _WS_STUB

    # Empty SSE state -> main.js auto-derive resolves to "home" (mode
    # client / no liveclient); #build-insights is a sticky non-game-state
    # hash, so the build-insights view wins the router.
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

    url = mock_server.url + "/?ui_mock=1#build-insights"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    # Wait for the async mock render: the default Items tab paints a
    # .bi-table into #bi-table-mount once the fixture's items array loads
    # (proves renderBuildInsights -> _ensureFetched(_ITEMS_TAB) landed).
    page.wait_for_function(
        "document.querySelector('#bi-table-mount table.bi-table') !== null",
        timeout=10_000,
    )
    return ctx, page, errors


def test_build_insights_view_renders(mock_server, pw_browser):
    ctx, page, errors = _open_build_insights(pw_browser, mock_server)
    try:
        view = page.locator("#view-build-insights")
        assert view.is_visible(), (
            "#view-build-insights not visible on build-insights view"
        )

        # body[data-view] drives the view-section's forced-visible CSS rule.
        dv = page.evaluate("document.body.dataset.view")
        assert dv == "build-insights", (
            f"body[data-view] {dv!r} != 'build-insights'"
        )

        SCREENSHOTS.mkdir(exist_ok=True)
        view.screenshot(path=str(SCREENSHOTS / "build-insights.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [build-insights]: {errors[:3]}"


def test_build_insights_item_rows(mock_server, pw_browser):
    """The default Items tab mounts at least one row from the fixture
    items (11 items), proving renderBuildInsights landed the WPA table."""
    ctx, page, errors = _open_build_insights(pw_browser, mock_server)
    try:
        page.wait_for_function(
            "document.querySelectorAll("
            "'#bi-table-mount table.bi-table tbody tr').length > 0",
            timeout=10_000,
        )
        rows = page.locator("#bi-table-mount table.bi-table tbody tr")
        assert rows.count() >= 1, (
            f"expected >=1 item row, got {rows.count()}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [build-insights rows]: {errors[:3]}"


def test_build_insights_pane_has_corner_brackets(mock_server, pw_browser):
    """RC2 Hextech reskin: the visible tab pane carries the gold corner-
    bracket motif. The .bi-tab-pane ::before pseudo paints a 14px L-stroke
    in the accent color - assert it computes a non-zero accent border so
    the bracket treatment is actually live (the reskin's signature cue).
    The default Items pane is the visible (non-hidden) pane."""
    ctx, page, errors = _open_build_insights(pw_browser, mock_server)
    try:
        pane = page.locator(
            "#view-build-insights .bi-tab-pane[data-bi-pane='items']"
        ).first
        assert pane.count() > 0, "no items .bi-tab-pane in build-insights view"
        # The ::before bracket has a 2px top + left border in --accent.
        width = page.evaluate(
            "getComputedStyle("
            "document.querySelector("
            "'#view-build-insights .bi-tab-pane[data-bi-pane=\"items\"]'),"
            "'::before').borderTopWidth"
        )
        assert width and width != "0px", (
            f"build-insights pane corner bracket missing "
            f"(border-top-width={width!r})"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [build-insights brackets]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F in the new
    test + the build_insights fixture it drives. (header.css carries
    pre-existing non-ASCII glyphs that predate this slice; mirroring the
    sibling view tests, the CSS is not ASCII-checked here - only this
    slice's authored test + the JSON fixture are.)"""
    targets = [
        Path(__file__),
        ROOT / "web" / "data" / "ui_mock" / "build_insights.json",
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
