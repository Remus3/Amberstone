"""
tests/snapshot_panels/test_home_view.py
Home (landing / player-profile) VIEW snapshot coverage - RC2 redesign #4.

Renders the full-page Home view (#home-overlay, gated visible by
body[data-view="home"]) against the ui_mock home fixture through the
headless mock-server + Playwright harness. This is the reproducible
stand-in for the live self-signed-HTTPS :8888 visual check: Claude_Preview
cannot attach the self-signed cert and 1-PC (ADR-011) has no separate-
machine MCP visual path, so the redesign visual validation runs here in CI.
Mirrors test_champ_select_view.py and test_last_match_view.py.

Drive path: /?ui_mock=1#home. main.js boot flips body.dataset.uiMock; with
an empty SSE state the auto-derive lands on "home" (mode=client / !live),
and the #home hash agrees, so applyView("home") stamps
body[data-view="home"] and the home-overlay CSS un-hides. _homeWireStartup
fires _homeFetchAndRender() unconditionally at boot (main.js:3445); under
ui_mock that short-circuits to /data/ui_mock/home.json (_homeMockLoad,
main.js:3008) and paints the fixture instead of /api/home/summary.

The fixture's tonight_pick.champion ("Jinx") populates #home-coach-pick-champ
(its pre-render placeholder is "-") and unhides #home-combo + the
#home-coach-pick HERO card, so waiting for that text to change is the
async-render landing signal AND proves the Tonight's Pick hero mounted.
Asserts: the home overlay is visible, the Tonight's Pick hero + Today
identity hero render, the THIS WEEK champ-pool rows render, and no
unhandled JS errors fire. Screenshots the view for the audit trail (this
is the capture the redesign cycle produces).
"""
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"


def _open_home(pw_browser, mock_server):
    from tests.snapshot_panels.conftest import _WS_STUB

    # Empty SSE state -> main.js auto-derive resolves to "home" (mode
    # client / no liveclient), so the #home hash is not treated as a stale
    # game-state surface and the home view wins the router.
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

    url = mock_server.url + "/?ui_mock=1#home"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    # Wait for the async mock render: tonight_pick.champion replaces the
    # "-" placeholder in #home-coach-pick-champ (proves _homeFetchAndRender
    # -> _homeRenderCoach landed the fixture).
    page.wait_for_function(
        "document.querySelector('#home-coach-pick-champ') && "
        "document.querySelector('#home-coach-pick-champ').textContent.trim() "
        "!== '-' && "
        "document.querySelector('#home-coach-pick-champ').textContent.trim() "
        "!== ''",
        timeout=10_000,
    )
    return ctx, page, errors


def test_home_view_renders(mock_server, pw_browser):
    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        overlay = page.locator("#home-overlay")
        assert overlay.is_visible(), "#home-overlay not visible on home view"

        # body[data-view] drives the overlay's forced-visible CSS rule.
        view = page.evaluate("document.body.dataset.view")
        assert view == "home", f"body[data-view] {view!r} != 'home'"

        # Tonight's Pick HERO rendered from the fixture (champion populated).
        champ = (
            page.locator("#home-coach-pick-champ").text_content() or ""
        ).strip()
        assert champ and champ != "-", "Tonight's Pick champion not rendered"

        # The Today identity hero card is present.
        assert page.locator("#home-hero").count() > 0, "home hero missing"

        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#home-overlay").screenshot(
            path=str(SCREENSHOTS / "home.png")
        )
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [home]: {errors[:3]}"


def test_home_week_pool_rows(mock_server, pw_browser):
    """THIS WEEK champ-pool renders one row per fixture this_week champ."""
    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        # The fixture ships 5 this_week champs; _homeRenderWeek paints one
        # .home-week-bar-row per champ.
        page.wait_for_function(
            "document.querySelectorAll("
            "'#home-week-list .home-week-bar-row').length > 0",
            timeout=10_000,
        )
        rows = page.locator("#home-week-list .home-week-bar-row")
        assert rows.count() >= 1, (
            f"expected >=1 THIS WEEK pool row, got {rows.count()}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [home week]: {errors[:3]}"


def test_home_tonight_pick_is_hero(mock_server, pw_browser):
    """The Tonight's Pick card is the focal hero: it carries the teal glow
    box-shadow (the reskin's single focal treatment) and is visible."""
    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        pick = page.locator("#home-coach-pick")
        assert pick.is_visible(), "Tonight's Pick hero not visible"
        # The hero glow is a non-none box-shadow (the reskin focal cue).
        shadow = page.evaluate(
            "getComputedStyle("
            "document.querySelector('#home-coach-pick')).boxShadow"
        )
        assert shadow and shadow != "none", (
            f"Tonight's Pick hero missing focal glow box-shadow: {shadow!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [home hero]: {errors[:3]}"


def test_home_wl_strip(mock_server, pw_browser):
    """LIFT 3: the last-20 W/L pip strip renders below the rank header.

    Asserts the strip is visible, carries exactly 20 pips, the count of
    WIN pips (data-result="W") matches the fixture wins, and the
    recent-form label shows the fixture win_rate."""
    import json

    fixture = json.loads(
        (ROOT / "web" / "data" / "ui_mock" / "home.json").read_text()
    )
    last20 = fixture["last20"]

    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        # _homeRenderWlStrip runs in the same _homeFetchAndRender pass as
        # the coach pick we already waited on, but wait on the pips to be
        # safe against render ordering.
        page.wait_for_function(
            "document.querySelectorAll("
            "'#home-hero-rank-wl .home-wl-pip').length > 0",
            timeout=10_000,
        )
        strip = page.locator("#home-hero-rank-wl")
        assert strip.is_visible(), "#home-hero-rank-wl not visible"

        pips = page.locator("#home-hero-rank-wl .home-wl-pip")
        assert pips.count() == 20, (
            f"expected 20 W/L pips, got {pips.count()}"
        )

        win_pips = page.locator(
            "#home-hero-rank-wl .home-wl-pip[data-result='W']"
        )
        assert win_pips.count() == last20["wins"], (
            f"win pips {win_pips.count()} != fixture wins {last20['wins']}"
        )

        form = (
            page.locator("#home-hero-rank-wl .home-wl-form").text_content()
            or ""
        )
        # JS renders the JSON number 65.0 as "65" (trailing .0 dropped),
        # so compare against the win_rate stringified the JS way - both
        # the float and its integer form (when whole) are accepted.
        wr = last20["win_rate"]
        wr_strs = {str(wr)}
        if float(wr).is_integer():
            wr_strs.add(str(int(wr)))
        assert any(s in form for s in wr_strs), (
            f"recent-form label {form!r} missing win_rate {wr}"
        )
        # The wins-losses record + the L20 tag both render in the label.
        assert f"{last20['wins']}-{last20['losses']}" in form, (
            f"recent-form label {form!r} missing record"
        )
        assert "L20" in form, f"recent-form label {form!r} missing 'L20'"

        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#home-hero-rank-wl").screenshot(
            path=str(SCREENSHOTS / "home_wl-strip.png")
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [home wl-strip]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F in the new
    test + the home fixture it drives. (home.css carries pre-existing
    U+2500 box-drawing comment dividers + U+2192 arrows that predate this
    slice; mirroring the sibling view tests, the CSS is not ASCII-checked
    here - only this slice's authored test + the JSON fixture are.)"""
    targets = [
        Path(__file__),
        ROOT / "web" / "data" / "ui_mock" / "home.json",
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
