"""
tests/snapshot_panels/test_lobby_popup_closes_on_scroll.py
RM-1422 (s144 uiux) - a Lobby menu scrolled out of sight closes.

THE DEFECT. MEASURED in headless Chromium under /?ui_mock=1#lobby before the
fix. The lane popup (#lv-lane-popup) and the mode menu (#lv-mode-menu) are
position:absolute inside #view-lobby, which scrolls (overflow-y auto) when
the view is shorter than its content: 200 px at 1280x720, 30 px at 923x1280,
0 at 1920x920. With the lane popup open, a real wheel scroll over the view
(page.mouse.wheel, 600 px) carried it to y -90 to 8 at 1280x720 (the view's
top edge is at 57, so none of it showed): still open, still rendered, focus
still on its MIDDLE cell, so every letter shortcut stayed dead
(main.js _menuRendered) until an Escape or a click outside.

THE FIX (web/js/lib/escape_layers.js armScrollAway / scrollAway): a scroll
that leaves an open Lobby menu showing less than the most it has shown since
it opened closes it. Focus that was inside it goes back to its trigger
without scrolling the trigger into view; a scroll that reveals more of a menu
keeps it open; the focus scroll of the open itself never closes it.

/api/lcu-cmd is intercepted at the page, so nothing but the local mock is
reached.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import _new_page

_STATE = """
() => {
  const p = document.getElementById('lv-lane-popup');
  const m = document.getElementById('lv-mode-menu');
  const v = document.getElementById('view-lobby');
  const ae = document.activeElement;
  return {
    lane: !p.classList.contains('hidden'),
    laneAria: p.getAttribute('aria-hidden'),
    priExpanded: document.getElementById('lv-lane-primary').getAttribute('aria-expanded'),
    mode: !m.classList.contains('hidden'),
    modeAria: m.getAttribute('aria-hidden'),
    modeExpanded: document.getElementById('lv-mode-trigger').getAttribute('aria-expanded'),
    menusRendered: Array.from(document.querySelectorAll('[role="menu"]'))
      .filter((x) => x.getClientRects().length > 0).map((x) => x.id),
    focus: !ae ? null : (ae.id || (p.contains(ae) && ae.dataset.pref
                                    ? 'cell:' + ae.dataset.pref : ae.tagName)),
    scroll: v.scrollTop,
    maxScroll: v.scrollHeight - v.clientHeight,
    zen: document.body.dataset.zen || '',
  };
}
"""


def _open_lobby(pw_browser, mock_server, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    posts: list[str] = []

    def _lcu(route):
        posts.append(route.request.post_data or "")
        route.fulfill(status=200, content_type="application/json", body="{}")

    page.route("**/api/lcu-cmd", _lcu)
    page.goto(mock_server.url + "/?ui_mock=1#lobby",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function("() => document.body.dataset.view === 'lobby'",
                           timeout=10_000)
    page.wait_for_selector("#lv-lane-primary", state="visible", timeout=10_000)
    page.wait_for_function(
        "() => document.getElementById('lv-lane-primary').dataset.pref"
        " === 'MIDDLE'", timeout=10_000)
    page.evaluate("() => { try { localStorage.removeItem('rc-zen'); } catch (_) {} "
                  "document.body.dataset.zen = ''; }")
    return ctx, page, errors, posts


def _wheel(page, dy, settle_js):
    """A real wheel over the view, below the lane pair (never over a menu)."""
    box = page.locator("#lv-lane-primary").bounding_box()
    page.mouse.move(box["x"] + 5, box["y"] + box["height"] + 40)
    page.mouse.wheel(0, dy)
    page.wait_for_function(settle_js, timeout=5_000)
    page.wait_for_timeout(200)


def _open_lane(page, how):
    if how == "pointer":
        page.click("#lv-lane-primary")
    else:
        page.focus("#lv-lane-primary")
        page.keyboard.press("Enter")
    st = page.evaluate(_STATE)
    assert st["lane"] and st["focus"] == "cell:MIDDLE", st
    return st


# RM-1428: the second viewport was 923x1280 until the stacked layout's
# popup moved below the lane pair; there the view scrolls only 30 px, which
# leaves the popup whole, so it now stays open (pinned as a control in
# test_lobby_lane_popup_fits_at_open.py). 1024x600 is the same stacked
# layout with 710 px of scroll, which does carry it out of sight.
@pytest.mark.parametrize("vp", [(1280, 720), (1024, 600)],
                         ids=lambda v: f"{v[0]}x{v[1]}")
@pytest.mark.parametrize("how", ["pointer", "keyboard"])
def test_a_wheel_scroll_away_closes_the_lane_popup(mock_server, pw_browser, vp, how):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, vp)
    try:
        st0 = _open_lane(page, how)
        assert st0["scroll"] == 0 and st0["maxScroll"] > 0, (
            f"scroll anchor: the view must scroll at {vp}: {st0}")
        _wheel(page, 600, "() => document.getElementById('view-lobby').scrollTop > 0")
        st = page.evaluate(_STATE)
        assert not st["lane"], f"the popup stayed open out of sight: {st}"
        assert st["laneAria"] == "true" and st["priExpanded"] == "false", st
        assert "lv-lane-popup" not in st["menusRendered"], st
        # Focus that was on the hidden cell goes back to the trigger, and the
        # page stays where the wheel put it (no jump back to the trigger).
        assert st["focus"] == "lv-lane-primary", st
        assert st["scroll"] == min(600, st["maxScroll"]), st
        # The shortcuts are the page's again.
        page.keyboard.press("z")
        assert page.evaluate(_STATE)["zen"] == "1", "Z stayed dead after the scroll"
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_opening_from_a_scrolled_view_stays_open(mock_server, pw_browser):
    """The focus scroll of the open itself is not a scroll away: with the
    view scrolled to its end, the popup would open above the view's top edge,
    so focusing its cell scrolls the view back; the popup must stay open."""
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, (1280, 720))
    try:
        page.evaluate("() => { const v = document.getElementById('view-lobby');"
                      " v.scrollTop = v.scrollHeight; }")
        page.wait_for_timeout(200)
        before = page.evaluate(_STATE)["scroll"]
        assert before > 0, before
        _open_lane(page, "keyboard")
        page.wait_for_timeout(400)
        st = page.evaluate(_STATE)
        assert st["scroll"] < before, f"open scroll anchor: {before} -> {st}"
        assert st["lane"] and st["focus"] == "cell:MIDDLE", (
            f"the open's own focus scroll closed the popup: {st}")
        assert st["laneAria"] == "false" and st["priExpanded"] == "true", st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_no_scroll_no_close_at_the_baseline(mock_server, pw_browser):
    """Control: at 1920x920 the view does not scroll, so a wheel over it
    moves nothing and the popup stays open with focus on its cell."""
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, (1920, 920))
    try:
        st0 = _open_lane(page, "pointer")
        assert st0["maxScroll"] == 0, st0
        box = page.locator("#lv-lane-primary").bounding_box()
        page.mouse.move(box["x"] + 5, box["y"] + box["height"] + 40)
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(400)
        st = page.evaluate(_STATE)
        assert st["lane"] and st["focus"] == "cell:MIDDLE", st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_mode_menu_stays_open_while_revealed_and_closes_when_scrolled_away(
        mock_server, pw_browser):
    """At 1280x720 the mode menu opens with its bottom cut off by the view.
    Scrolling down reveals it: it stays open. Scrolling back up hides what it
    showed: it closes, and focus (on the trigger) is left where it is."""
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, (1280, 720))
    try:
        page.click("#lv-mode-trigger")
        st = page.evaluate(_STATE)
        assert st["mode"] and st["modeExpanded"] == "true", st
        assert st["focus"] == "lv-mode-trigger", st
        _wheel(page, 120, "() => document.getElementById('view-lobby').scrollTop > 0")
        st = page.evaluate(_STATE)
        assert st["scroll"] > 0, st
        assert st["mode"], f"a scroll that revealed the menu closed it: {st}"
        _wheel(page, -600, "() => document.getElementById('view-lobby').scrollTop === 0")
        st = page.evaluate(_STATE)
        assert not st["mode"], f"the mode menu stayed open scrolled away: {st}"
        assert st["modeAria"] == "true" and st["modeExpanded"] == "false", st
        assert st["focus"] == "lv-mode-trigger" and st["scroll"] == 0, st
        assert st["menusRendered"] == [], st
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_mode_menu_with_focus_inside_hands_it_back_in_place(mock_server, pw_browser):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, (1280, 720))
    try:
        page.click("#lv-mode-trigger")
        page.focus("#lv-mode-menu .lq-mode-item")
        assert page.evaluate(_STATE)["mode"]
        _wheel(page, 600, "() => document.getElementById('view-lobby').scrollTop > 0")
        st = page.evaluate(_STATE)
        # Scrolling down 200 px moves the whole menu up inside the view, so
        # it shows more, not less: it stays open, focus still inside it.
        assert st["mode"] and st["focus"] != "lv-mode-trigger", st
        _wheel(page, -600,
               "() => document.getElementById('view-lobby').scrollTop === 0")
        st = page.evaluate(_STATE)
        assert not st["mode"], st
        assert st["focus"] == "lv-mode-trigger", (
            f"focus inside the closed menu was dropped: {st}")
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
