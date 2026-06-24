"""
tests/snapshot_panels/test_user_builds_review_r30.py
R30 page-7 (User Builds) per-page DESIGN review - regression coverage for the
full-pass slice (2026-06-23, ledger 607).

gemini's view-job: "rapid CRUD for DS item/rune logic; the trap is burying
adjustments behind multi-click modals." The CRUD was already good (champion
datalist autocomplete, inline Edit/Delete, a side-pane editor (not a modal),
Delete confirm). The flaws this slice fixes:

  A. dead space: .ub-layout was a 1fr/1.3fr 2-up, but the editor pane is
     hidden at rest, so the build list was confined to the 1fr track (~43%)
     while the 1.3fr track sat empty. Now the list takes the FULL width at
     rest and collapses to the 2-up only while the editor is open (desktop).
  B. density: each build row now renders the actual item ICONS (resolved
     from the build's item names via _resolveItemId) instead of only "N
     items", so the build logic reads at a glance (gemini high-density).

Drive path: /?ui_mock=1#user-builds -> _userBuildsFetchAndRender loads
/data/ui_mock/user_builds.json (Tristana, 5 builds). Landing signal: a
.ub-build-row appears.
"""
import pytest
from pathlib import Path

SCREENSHOTS = Path(__file__).parent / "screenshots"


def _open_user_builds(pw_browser, mock_server, width=1920, height=1080):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": width, "height": height}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    url = mock_server.url + "/?ui_mock=1#user-builds"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_selector(".ub-build-row", timeout=10_000)
    return ctx, page, errors


def test_ub_build_rows_show_item_icons(mock_server, pw_browser):
    """B: build rows render resolved item icons (img -> /img/item/<id>.png),
    not just the 'N items' count."""
    ctx, page, errors = _open_user_builds(pw_browser, mock_server)
    try:
        icons = page.eval_on_selector_all(
            ".ub-build-row .ub-build-item-icon",
            "els => els.map(e => e.getAttribute('src') || '')"
        )
        # the Tristana mock has 23 item-name slots across its builds; even if
        # a few names don't resolve, most do -> a healthy icon count.
        assert len(icons) >= 5, f"too few item icons rendered: {len(icons)}"
        assert all("/img/item/" in s for s in icons), f"bad icon src: {icons[:3]}"
        # the first row ("lethality 3-item rush", 6 items) shows several.
        first_row_icons = page.eval_on_selector_all(
            ".ub-build-row:first-child .ub-build-item-icon", "els => els.length"
        )
        assert first_row_icons >= 1, "first build row has no item icons"
        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#view-user-builds").screenshot(
            path=str(SCREENSHOTS / "user-builds-review-r30.png")
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_ub_layout_full_width_at_rest(mock_server, pw_browser):
    """A: at desktop with the editor hidden, .ub-layout is single-column so
    the build list uses the full width (no empty form track)."""
    ctx, page, errors = _open_user_builds(pw_browser, mock_server)
    try:
        # editor pane is hidden at rest
        hidden = page.eval_on_selector("#ub-form-pane", "el => el.hasAttribute('hidden')")
        assert hidden, "form pane should be hidden at rest"
        tracks = page.evaluate(
            "() => getComputedStyle(document.querySelector('.ub-layout'))"
            ".gridTemplateColumns.trim().split(/\\s+/).length"
        )
        assert tracks == 1, f"ub-layout should be 1 col at rest, got {tracks}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def _select_champion_and_open_form(page):
    # The editor only opens once a champion is selected (_UB.champion); the
    # mock auto-load renders the list but does not set it. Select Tristana
    # (change fires _ubChampionPicked), then open the editor via + Add build.
    page.fill("#ub-champion-input", "Tristana")
    page.dispatch_event("#ub-champion-input", "change")
    page.wait_for_selector(".ub-build-row", timeout=10_000)
    page.click("#ub-add-btn")
    page.wait_for_function(
        "() => { const p = document.querySelector('#ub-form-pane');"
        " return p && !p.hasAttribute('hidden'); }",
        timeout=5_000,
    )


def test_ub_layout_two_up_when_editing(mock_server, pw_browser):
    """A: opening the editor expands .ub-layout to the 2-up at desktop so the
    list + form sit side-by-side."""
    ctx, page, errors = _open_user_builds(pw_browser, mock_server)
    try:
        _select_champion_and_open_form(page)
        tracks = page.evaluate(
            "() => getComputedStyle(document.querySelector('.ub-layout'))"
            ".gridTemplateColumns.trim().split(/\\s+/).length"
        )
        assert tracks == 2, f"ub-layout should be 2-up while editing, got {tracks}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_ub_companion_single_column(mock_server, pw_browser):
    """A: at companion width (923) .ub-layout stays single-column even while
    editing (the form stacks below the list)."""
    ctx, page, errors = _open_user_builds(pw_browser, mock_server, width=923, height=1316)
    try:
        _select_champion_and_open_form(page)
        tracks = page.evaluate(
            "() => getComputedStyle(document.querySelector('.ub-layout'))"
            ".gridTemplateColumns.trim().split(/\\s+/).length"
        )
        assert tracks == 1, f"ub-layout should stay 1 col at 923, got {tracks}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
