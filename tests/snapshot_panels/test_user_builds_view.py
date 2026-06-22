"""
tests/snapshot_panels/test_user_builds_view.py
User Builds VIEW snapshot coverage - RC2 redesign #9.

Renders the full-page User Builds view (#view-user-builds, the SR Draft
Theatre build curator, gated visible by body[data-view="user-builds"])
against the ui_mock user_builds fixture through the headless mock-server +
Playwright harness. This is the reproducible stand-in for the live
self-signed-HTTPS :8888 visual check: Claude_Preview cannot attach the
self-signed cert and 1-PC (ADR-011) has no separate-machine MCP visual
path, so the redesign visual validation runs here in CI. Mirrors
test_session_view.py and test_history_view.py.

Drive path: /?ui_mock=1#user-builds. main.js boot flips body.dataset.uiMock;
with an empty SSE state the auto-derive lands on "home" (mode=client /
!live), and #user-builds is a sticky non-game-state hash (main.js:958-959),
so the user-builds view wins the router (applyView("user-builds") stamps
body[data-view="user-builds"], which un-hides #view-user-builds). The
viewId=="user-builds" branch fires _userBuildsWireOnce() +
_userBuildsFetchAndRender() (main.js:782-784); under ui_mock with no champion
typed, _userBuildsFetchAndRender does NOT early-return (uiMockOn is true),
the live /api/sr-draft/user-builds fetch resolves null, and the render
short-circuits to /data/ui_mock/user_builds.json (main.js:2208-2215) instead
of the live feed.

The fixture's builds array has 5 builds, so _userBuildsFetchAndRender sets
#ub-count to "5 builds (mock)" (its pre-render placeholder is "-") and
paints one .ub-build-row per build into #ub-build-list. Waiting for that
count text to leave "-" is the async-render landing signal; the build rows
are the rendered-structure assertion.

Asserts: the user-builds view is visible with body[data-view]=="user-builds",
the build count rendered from the fixture, the build list mounted at least
one row, and no unhandled JS errors fire. Screenshots the view for the audit
trail (this is the capture the redesign cycle produces).
"""
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"


def _open_user_builds(pw_browser, mock_server):
    from tests.snapshot_panels.conftest import _WS_STUB

    # Empty SSE state -> main.js auto-derive resolves to "home" (mode
    # client / no liveclient); #user-builds is a sticky non-game-state
    # hash, so the user-builds view wins the router.
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

    url = mock_server.url + "/?ui_mock=1#user-builds"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    # Wait for the async mock render: the build count replaces the "-"
    # placeholder in #ub-count (proves _userBuildsFetchAndRender landed
    # the fixture's builds array).
    page.wait_for_function(
        "document.querySelector('#ub-count') && "
        "document.querySelector('#ub-count').textContent.trim() "
        "!== '-' && "
        "document.querySelector('#ub-count').textContent.trim() "
        "!== ''",
        timeout=10_000,
    )
    return ctx, page, errors


def test_user_builds_view_renders(mock_server, pw_browser):
    ctx, page, errors = _open_user_builds(pw_browser, mock_server)
    try:
        view = page.locator("#view-user-builds")
        assert view.is_visible(), (
            "#view-user-builds not visible on user-builds view"
        )

        # body[data-view] drives the view-section's forced-visible CSS rule.
        dv = page.evaluate("document.body.dataset.view")
        assert dv == "user-builds", (
            f"body[data-view] {dv!r} != 'user-builds'"
        )

        # Build count rendered from the fixture (placeholder "-" replaced).
        count = (
            page.locator("#ub-count").text_content() or ""
        ).strip()
        assert count and count != "-", "build count not rendered from fixture"

        SCREENSHOTS.mkdir(exist_ok=True)
        view.screenshot(path=str(SCREENSHOTS / "user-builds.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [user-builds]: {errors[:3]}"


def test_user_builds_build_rows(mock_server, pw_browser):
    """The build list mounts at least one row from the fixture builds
    (5 builds), proving _userBuildsFetchAndRender landed."""
    ctx, page, errors = _open_user_builds(pw_browser, mock_server)
    try:
        page.wait_for_function(
            "document.querySelectorAll("
            "'#ub-build-list .ub-build-row').length > 0",
            timeout=10_000,
        )
        rows = page.locator("#ub-build-list .ub-build-row")
        assert rows.count() >= 1, (
            f"expected >=1 build row, got {rows.count()}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [user-builds rows]: {errors[:3]}"


def test_user_builds_pane_has_corner_brackets(mock_server, pw_browser):
    """RC2 Hextech reskin: the build-list pane carries the gold corner-
    bracket motif. The .ub-list-pane ::before pseudo paints a 14px L-stroke
    in the accent color - assert it computes a non-zero accent border so the
    bracket treatment is actually live (the reskin's signature cue)."""
    ctx, page, errors = _open_user_builds(pw_browser, mock_server)
    try:
        pane = page.locator("#view-user-builds .ub-list-pane").first
        assert pane.count() > 0, "no .ub-list-pane in user-builds view"
        # The ::before bracket has a 2px top + left border in --accent.
        width = page.evaluate(
            "getComputedStyle("
            "document.querySelector('#view-user-builds .ub-list-pane'),"
            "'::before').borderTopWidth"
        )
        assert width and width != "0px", (
            f"user-builds pane corner bracket missing "
            f"(border-top-width={width!r})"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [user-builds brackets]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F in the new
    test + the user_builds fixture it drives. (header.css carries pre-existing
    non-ASCII glyphs that predate this slice; mirroring the sibling view
    tests, the CSS is not ASCII-checked here - only this slice's authored
    test + the JSON fixture are.)"""
    targets = [
        Path(__file__),
        ROOT / "web" / "data" / "ui_mock" / "user_builds.json",
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
