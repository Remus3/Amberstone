"""
tests/snapshot_panels/test_home_companion_view.py
Home view COMPANION-width reflow regression (R29, 2026-06-23).

The rc-shell out-of-game companion (mainWindow, docs/ELECTRON_OVERLAY.md
section 3.7) loads the full :8888 dashboard in a narrow window (size presets
380-640px; the operator runs it ~920px wide). The home view's wide
multi-column grids (.home-body 2-col Recent5|ThisWeek, .home-hero 3-col
greet|headline|chips) are authored for the 1920 desktop and overflowed the
narrow companion: the THIS WEEK column + hero stat chips clipped off the
right edge, and the hero's explicit min-height:120px let flex-shrink collapse
it inside the .home-overlay flex column so the headline/chips spilled onto the
Tonight's Pick card. The R29 fix added a max-width:1200px reflow (home.css)
that single-columns the wide grids and drops the hero min-height floor.

This guards both directions: at the companion width the home grids are
single-column, the hero contains its stacked content (no collapse/overlap),
and nothing in the overlay overflows the viewport; at the 1920 desktop the
multi-column layout is preserved. Drives the same ui_mock home fixture as
test_home_view.py (the grid structure under test is CSS-driven, so the
assertions hold regardless of fixture content).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"

COMPANION_W, COMPANION_H = 923, 1316


def _open_home_at(pw_browser, mock_server, w, h):
    from tests.snapshot_panels.conftest import _WS_STUB

    # Empty SSE state -> main.js auto-derive resolves to "home" (mode client /
    # no liveclient); the #home hash agrees so the home view wins the router.
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": w, "height": h}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + "/?ui_mock=1#home",
        wait_until="domcontentloaded", timeout=15_000,
    )
    # The fixture's tonight_pick.champion replaces the "-" placeholder once
    # _homeFetchAndRender lands - the async-render settled signal.
    page.wait_for_function(
        "document.querySelector('#home-coach-pick-champ') && "
        "document.querySelector('#home-coach-pick-champ').textContent.trim() "
        "!== '-' && "
        "document.querySelector('#home-coach-pick-champ').textContent.trim() "
        "!== ''",
        timeout=10_000,
    )
    return ctx, page, errors


def _track_count(gtc):
    # getComputedStyle grid-template-columns is a space-separated px list;
    # one track == one value (no internal space).
    return len((gtc or "").split())


def test_home_companion_reflows_single_column(mock_server, pw_browser):
    ctx, page, errors = _open_home_at(
        pw_browser, mock_server, COMPANION_W, COMPANION_H
    )
    try:
        # .home-body (Recent 5 | This Week) collapses to one column.
        body_cols = page.evaluate(
            "getComputedStyle(document.querySelector('.home-body'))"
            ".gridTemplateColumns"
        )
        assert _track_count(body_cols) == 1, (
            f"home-body not single-column at {COMPANION_W}px: {body_cols!r}"
        )
        # .home-hero stacks to one column too.
        hero_cols = page.evaluate(
            "getComputedStyle(document.querySelector('.home-hero'))"
            ".gridTemplateColumns"
        )
        assert _track_count(hero_cols) == 1, (
            f"home-hero not single-column at {COMPANION_W}px: {hero_cols!r}"
        )
        # The hero box contains its own chips row and ends above the Tonight's
        # Pick card (the min-height floor is dropped so flex-shrink cannot
        # collapse the hero and spill its content onto the card below).
        geo = page.evaluate(
            """() => {
              const hero = document.querySelector('.home-hero');
              const chips = document.querySelector('.home-hero-chips');
              const pick = document.querySelector('.home-coach-pick');
              if (!hero || !chips || !pick) return null;
              const h = hero.getBoundingClientRect();
              const c = chips.getBoundingClientRect();
              const p = pick.getBoundingClientRect();
              return {
                heroContainsChips: c.bottom <= h.bottom + 1,
                heroAbovePick: h.bottom <= p.top + 1,
              };
            }"""
        )
        assert geo, "home hero / chips / pick element missing"
        assert geo["heroContainsChips"], (
            "hero chips overflow the hero box (min-height flex-collapse)"
        )
        assert geo["heroAbovePick"], "hero overlaps the Tonight's Pick card"

        # Nothing in the home overlay overflows the companion viewport width.
        over = page.evaluate(
            """() => {
              const vw = document.documentElement.clientWidth;
              let worst = 0, worstSel = '';
              document.querySelectorAll('#home-overlay *').forEach(el => {
                if (getComputedStyle(el).display === 'none') return;
                const r = el.getBoundingClientRect();
                if (r.width >= 40 && r.right > worst) {
                  worst = r.right;
                  worstSel = el.className || el.tagName;
                }
              });
              return { vw, worst: Math.round(worst), worstSel };
            }"""
        )
        assert over["worst"] <= over["vw"] + 2, (
            f"home content overflows companion width: rightmost "
            f"{over['worst']} > {over['vw']} ({over['worstSel']})"
        )

        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#home-overlay").screenshot(
            path=str(SCREENSHOTS / "home_companion.png")
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [home companion]: {errors[:3]}"


def test_home_desktop_keeps_multicolumn(mock_server, pw_browser):
    """Regression guard the other way: the 1920 desktop is unaffected by the
    companion reflow - .home-body keeps its two columns."""
    ctx, page, errors = _open_home_at(pw_browser, mock_server, 1920, 1080)
    try:
        body_cols = page.evaluate(
            "getComputedStyle(document.querySelector('.home-body'))"
            ".gridTemplateColumns"
        )
        assert _track_count(body_cols) == 2, (
            f"home-body lost its desktop two-column layout: {body_cols!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [home desktop]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text in this test file (home.css is
    excluded - it carries pre-existing U+2500 box-drawing comment dividers
    that predate this slice, mirroring test_home_view.py)."""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s): {offenders[:5]}"
