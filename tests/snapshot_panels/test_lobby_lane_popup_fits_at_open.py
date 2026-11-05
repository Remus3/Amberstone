"""
tests/snapshot_panels/test_lobby_lane_popup_fits_at_open.py
RM-1428 (s144 uiux) - the Lobby lane popup is whole inside the view at open.

THE DEFECT. MEASURED in headless Chromium under /?ui_mock=1#lobby before the
fix. The lane popup (#lv-lane-popup) is position:absolute inside the lane pair
and always opened ABOVE it (bottom: calc(100% + 8px)). At every viewport where
the Lobby view stacks to one column (923x1280, 1024x600, 800x600) the lane
pair's top sits 79 px below #view-lobby's top edge while the popup needs 105 px
(97.2 px tall plus the 8 px gap), so it opened at y 30.8 against a view top of
57: its lane-label row (y 41.8 to 61) was cut off by the view. The overflow is
ABOVE the view's scroll origin, so no scroll could ever bring it into sight.
At 1920x920, 1280x720 and 1366x768 it fit (top 108.4 to 110.4).

THE FIX (web/js/main.js _openLanePopup, header.css .lobby-lane-popup.is-below):
at open the popup is placed above; when its top would sit above the view's
scroll origin (content space, so a view merely scrolled down still opens
above and scrolls back) it flips below the lane pair. Then the whole popup is
scrolled into view (block / inline nearest), before the scroll-away arm.

The rect checks clip against #view-lobby's padding box and the window, the
same clip rects escape_layers.js visibleArea uses. /api/lcu-cmd is intercepted
at the page, so nothing but the local mock is reached.
"""
import pytest

from tests.snapshot_panels.test_lobby_popup_closes_on_scroll import _open_lobby

_GEO = """
() => {
  const box = (el) => { const b = el.getBoundingClientRect();
    return {top: b.top, bottom: b.bottom, left: b.left, right: b.right}; };
  const v = document.getElementById('view-lobby');
  const p = document.getElementById('lv-lane-popup');
  const vr = v.getBoundingClientRect();
  const clip = {top: Math.max(0, vr.top + v.clientTop),
                left: Math.max(0, vr.left + v.clientLeft)};
  clip.bottom = Math.min(innerHeight, vr.top + v.clientTop + v.clientHeight);
  clip.right = Math.min(innerWidth, vr.left + v.clientLeft + v.clientWidth);
  const ae = document.activeElement;
  return {
    open: !p.classList.contains('hidden'),
    below: p.classList.contains('is-below'),
    popup: box(p),
    label: box(document.getElementById('lv-lane-popup-label')),
    pair: box(p.parentElement),
    clip,
    scroll: v.scrollTop,
    focus: !ae ? null : (ae.id || (p.contains(ae) && ae.dataset.pref
                                    ? 'cell:' + ae.dataset.pref : ae.tagName)),
  };
}
"""

_SLACK = 0.5


def _inside(r, c):
    return (r["top"] >= c["top"] - _SLACK and r["bottom"] <= c["bottom"] + _SLACK
            and r["left"] >= c["left"] - _SLACK and r["right"] <= c["right"] + _SLACK)


def _open(page, how):
    if how == "pointer":
        page.click("#lv-lane-primary")
    else:
        page.focus("#lv-lane-primary")
        page.keyboard.press("Enter")
    page.wait_for_timeout(250)
    st = page.evaluate(_GEO)
    assert st["open"] and st["focus"] == "cell:MIDDLE", st
    return st


def _assert_fits(st, label):
    assert _inside(st["popup"], st["clip"]), (
        f"{label}: the popup is cut off by the view at open: {st}")
    assert _inside(st["label"], st["clip"]), f"{label}: label row cut off: {st}"
    p, pair = st["popup"], st["pair"]
    # It never covers the lane triggers it serves.
    assert p["bottom"] <= pair["top"] + _SLACK or p["top"] >= pair["bottom"] - _SLACK, (
        f"{label}: the popup overlaps the lane pair: {st}")


_VPS = [(1920, 920), (1280, 720), (1366, 768), (923, 1280), (1024, 600), (800, 600)]


@pytest.mark.parametrize("vp", _VPS, ids=lambda v: f"{v[0]}x{v[1]}")
@pytest.mark.parametrize("how", ["pointer", "keyboard"])
def test_the_lane_popup_is_whole_inside_the_view_at_open(
        mock_server, pw_browser, vp, how):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, vp)
    try:
        st = _open(page, how)
        _assert_fits(st, f"{vp} {how}")
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", _VPS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_opening_from_a_view_scrolled_to_its_end_fits(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, vp)
    try:
        page.evaluate("() => { const v = document.getElementById('view-lobby');"
                      " v.scrollTop = v.scrollHeight; }")
        page.wait_for_timeout(200)
        st = _open(page, "keyboard")
        _assert_fits(st, f"{vp} scrolled")
        # The arm ran after the into-view scroll: the popup is still open.
        page.wait_for_timeout(300)
        assert page.evaluate(_GEO)["open"], "the open's own scroll closed it"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_scroll_that_leaves_the_flipped_popup_whole_keeps_it_open(
        mock_server, pw_browser):
    """Control for the RM-1422 scroll-away close: at 923x1280 the view
    scrolls 30 px, and the popup below the pair is still whole after it, so
    it stays open with focus on its cell."""
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, (923, 1280))
    try:
        st = _open(page, "pointer")
        assert st["below"] and st["scroll"] == 0, st
        box = page.locator("#lv-lane-primary").bounding_box()
        page.mouse.move(box["x"] + 5, st["popup"]["bottom"] + 40)
        page.mouse.wheel(0, 600)
        page.wait_for_function(
            "() => document.getElementById('view-lobby').scrollTop > 0",
            timeout=5_000)
        page.wait_for_timeout(300)
        st = page.evaluate(_GEO)
        assert st["scroll"] > 0, st
        assert st["open"] and st["focus"] == "cell:MIDDLE", st
        _assert_fits(st, "923x1280 after a scroll")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_placement_is_above_where_it_fits_and_below_where_it_cannot(
        mock_server, pw_browser):
    """Anchors: the wide baseline keeps the authored above placement, the
    stacked layout flips below, and the flip is recomputed on every open, so
    a resize between two opens never leaves a stale side."""
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, (1920, 920))
    try:
        st = _open(page, "keyboard")
        assert not st["below"] and st["popup"]["bottom"] <= st["pair"]["top"], st
        page.keyboard.press("Escape")
        page.set_viewport_size({"width": 923, "height": 1280})
        page.wait_for_timeout(300)
        st = _open(page, "keyboard")
        assert st["below"] and st["popup"]["top"] >= st["pair"]["bottom"], st
        _assert_fits(st, "923x1280 after resize")
        page.keyboard.press("Escape")
        page.set_viewport_size({"width": 1920, "height": 920})
        page.wait_for_timeout(300)
        st = _open(page, "keyboard")
        assert not st["below"], f"a stale below flip survived the reopen: {st}"
        _assert_fits(st, "1920x920 after resize back")
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
