"""
tests/snapshot_panels/test_replay_view.py
Replay VIEW snapshot coverage - RC2 redesign #11.

Renders the full-page Replay view (#view-replay, gated visible by
body[data-view="replay"]) against the ui_mock replay fixture through the
headless mock-server + Playwright harness. This is the reproducible
stand-in for the live self-signed-HTTPS :8888 visual check: Claude_Preview
cannot attach the self-signed cert and 1-PC (ADR-011) has no separate-
machine MCP visual path, so the redesign visual validation runs here in CI.
Mirrors test_session_view.py / test_history_view.py / test_lobby_view.py.

Drive path: /?ui_mock=1#replay. main.js boot flips body.dataset.uiMock;
with an empty SSE state the auto-derive lands on "home" (mode=client /
!live), and #replay is a sticky non-game-state hash (web/js/main.js
_viewResolveAndApply: only a hash matching _hashIsStaleGameState is
cleared), so the replay view wins the router (applyView("replay") stamps
body[data-view="replay"], which un-hides #view-replay through the
web/css/panels/header.css rule `body[data-view="replay"]
#view-replay { display: block; }`, aligned in the view-section group).
The `if (viewId === "replay")` branch of applyView in web/js/main.js fires
_replayViewWireOnce() + _replayViewRefresh(); under ui_mock the matches
fetch short-circuits to /data/ui_mock/replay.json (web/js/panels/dev.js
`function _replayMockLoad`) instead of the live /api/replay/matches feed.

The fixture's matches=4 paints one .replay-match-row per match into
#replay-match-list (the RECENT MATCHES list). Waiting for that row to mount
is the async-render landing signal - the same structure the redesign reskins
(the list pane takes the .hx-card gold-bracket frame).

Asserts: the replay view is visible with body[data-view]=="replay", the
match list mounted at least one row from the fixture, the list pane carries
the Hextech gold corner-bracket motif (the reskin's signature cue), and no
unhandled JS errors fire. Screenshots the view for the audit trail (this is
the capture the redesign cycle produces -> screenshots/replay.png).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"


def _open_replay(pw_browser, mock_server):
    from tests.snapshot_panels.conftest import _WS_STUB

    # Empty SSE state -> main.js auto-derive resolves to "home" (mode
    # client / no liveclient); #replay is a sticky non-game-state hash,
    # so the replay view wins the router.
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

    url = mock_server.url + "/?ui_mock=1#replay"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    # Wait for the async mock render: at least one match row mounts into
    # #replay-match-list (proves _replayViewRefresh landed the fixture).
    page.wait_for_function(
        "document.querySelectorAll("
        "'#replay-match-list .replay-match-row').length > 0",
        timeout=10_000,
    )
    return ctx, page, errors


def test_replay_view_renders(mock_server, pw_browser):
    ctx, page, errors = _open_replay(pw_browser, mock_server)
    try:
        view = page.locator("#view-replay")
        assert view.is_visible(), "#view-replay not visible on replay view"

        # body[data-view] drives the view-section's forced-visible CSS rule.
        dv = page.evaluate("document.body.dataset.view")
        assert dv == "replay", f"body[data-view] {dv!r} != 'replay'"

        SCREENSHOTS.mkdir(exist_ok=True)
        view.screenshot(path=str(SCREENSHOTS / "replay.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [replay]: {errors[:3]}"


def test_replay_match_rows(mock_server, pw_browser):
    """The match list mounts at least one row from the fixture matches
    (4 matches), proving _replayViewRefresh landed."""
    ctx, page, errors = _open_replay(pw_browser, mock_server)
    try:
        rows = page.locator("#replay-match-list .replay-match-row")
        assert rows.count() >= 1, (
            f"expected >=1 match row, got {rows.count()}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [replay rows]: {errors[:3]}"


def test_replay_pane_has_corner_brackets(mock_server, pw_browser):
    """RC2 Hextech reskin: the replay list pane carries the gold corner-
    bracket motif. The .replay-list-pane ::before pseudo paints a 14px
    L-stroke in the accent color - assert it computes a non-zero accent
    border so the bracket treatment is actually live (the reskin's
    signature cue, mirroring test_session_view's bracket assertion)."""
    ctx, page, errors = _open_replay(pw_browser, mock_server)
    try:
        pane = page.locator("#view-replay .replay-list-pane").first
        assert pane.count() > 0, "no .replay-list-pane in replay view"
        # The ::before bracket has a 2px top + left border in --accent.
        width = page.evaluate(
            "getComputedStyle("
            "document.querySelector('#view-replay .replay-list-pane'),"
            "'::before').borderTopWidth"
        )
        assert width and width != "0px", (
            f"replay pane corner bracket missing (border-top-width={width!r})"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [replay brackets]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text in the new test and its fixture.

    0 bytes above 0x7F in the new
    test + the replay fixture it drives. (primitives.css / replay_events.css
    carry CSS-escaped non-ASCII sigils, not literal glyphs; mirroring the
    sibling view tests, the CSS is not ASCII-checked here - only this
    slice's authored test + the JSON fixture are.)"""
    targets = [
        Path(__file__),
        ROOT / "web" / "data" / "ui_mock" / "replay.json",
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"


# RM-1183: the module docstring cites the router, CSS and mock-loader
# sites it describes by SYMBOL, never by file:line. Its line citations
# (main.js:958-959, main.js:781, header.css:663) had all drifted - the
# CSS one named a path that never existed (web/css/header.css; the
# file is web/css/panels/header.css) - and main.js line numbers move on
# every edit above them. Each anchor below must appear verbatim in the
# docstring AND in the source file it names, so a rename of the source
# symbol turns this red instead of leaving the prose pointing at nothing.
_DOC_ANCHORS = (
    ("web/js/main.js", "_hashIsStaleGameState"),
    ("web/js/main.js", 'if (viewId === "replay")'),
    ("web/css/panels/header.css", 'body[data-view="replay"]'),
    ("web/css/panels/header.css", "#view-replay { display: block; }"),
    ("web/js/panels/dev.js", "function _replayMockLoad"),
)


def test_docstring_cites_sites_by_symbol_not_line():
    import re
    import sys

    doc = sys.modules[__name__].__doc__ or ""
    line_cites = re.findall(r"[\w./-]+\.(?:js|css|py):\d+", doc)
    assert not line_cites, (
        f"docstring carries file:line citations that drift: {line_cites}"
    )
    for rel, needle in _DOC_ANCHORS:
        assert rel in doc, f"docstring does not name {rel}"
        assert needle in doc, f"docstring does not cite {needle!r}"
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert needle in src, f"{rel} no longer contains {needle!r}"
