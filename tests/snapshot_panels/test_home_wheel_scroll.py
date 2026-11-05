"""
tests/snapshot_panels/test_home_wheel_scroll.py
RM-1433 (s144 uiux) - the mouse wheel reaches all of Home in a short window.

THE DEFECT. MEASURED in headless Chromium under /?ui_mock=1#home before the
fix. #home-overlay is a flex child of the body column (flex 1 1 auto,
min-height 0), so it is held to the height the header and footer leave, and
`body { overflow: hidden }` turns off page scrolling. Its content ran out of
its own box, under the footer, and a wheel over it scrolled nothing (overlay,
body and document scrollTop all stayed 0). Content height vs box height:
687 / 661 at 1366x768, 687 / 613 at 1280x720, 1049 / 493 at 1024x600,
1049 / 353 at 960x460, 1098 / 261 at 768x368, 1287 / 200 at 640x307,
1442 / 72 at 480x230 and 1872 / 98 at 320x256. Only keyboard focus could
bring the lower rows (THIS WEEK, the launcher rail) into view.

THE FIX (web/css/panels/home.css, the .home-overlay rule): the panel is its
own vertical scroll container (overflow-y: auto, overscroll contained). Its
box and its children's layout are unchanged; content that runs past the box
now scrolls inside it instead of painting under the footer. At 1920x920 and
923x1280 the content fits, so there is no scroll and no scrollbar.

What is checked:
- at every short size, a wheel over the panel scrolls it, and wheeling to the
  end brings the last launcher tile whole into the panel's visible box;
- no Home content paints below the panel's box onto the footer;
- Tab through the panel shows each control with its whole :focus-visible
  ring inside the panel's viewport (the 5-phase audit measured the scroll
  container cutting a launcher tile's ring by 4.4 px at 1366x768 until the
  rule gained scroll-padding-block);
- at 1920x920 and 923x1280 nothing scrolls and no descendant reaches outside
  the panel's box, so the new clip hides nothing there (the authored layout
  itself is pinned by test_home_narrow_reflow.py).
"""
import pytest

from tests.snapshot_panels.test_home_find_match_picker_focus import _open_home

_STATE = """
() => {
  const ov = document.getElementById('home-overlay');
  const r = ov.getBoundingClientRect();
  const cs = getComputedStyle(ov);
  const tiles = Array.from(ov.querySelectorAll('.home-action-tile'))
    .filter((t) => t.getClientRects().length);
  const last = tiles[tiles.length - 1].getBoundingClientRect();
  // The panel's visible box: its padding box (border excluded).
  const bt = parseFloat(cs.borderTopWidth), bb = parseFloat(cs.borderBottomWidth);
  const box = {top: r.top + bt, bottom: r.bottom - bb, left: r.left, right: r.right};
  const footer = document.querySelector('footer');
  const outside = [];
  for (const el of ov.querySelectorAll('*')) {
    if (!el.getClientRects().length) continue;
    const b = el.getBoundingClientRect();
    if (!b.width && !b.height) continue;
    if (b.left < r.left - 0.5 || b.right > r.right + 0.5
        || b.top < r.top - 0.5 || b.bottom > r.bottom + 0.5) {
      outside.push(el.id || String(el.className).slice(0, 40));
    }
  }
  return {
    overflowY: cs.overflowY,
    clientH: ov.clientHeight, scrollH: ov.scrollHeight, scrollTop: ov.scrollTop,
    clientW: ov.clientWidth, offsetW: ov.offsetWidth,
    docTop: document.documentElement.scrollTop, bodyTop: document.body.scrollTop,
    box, lastTile: {top: last.top, bottom: last.bottom},
    footerTop: footer ? footer.getBoundingClientRect().top : null,
    nOutside: outside.length, outside: outside.slice(0, 8),
  };
}
"""

_SHORT = [(1366, 768), (1280, 720), (1024, 600), (960, 460),
          (768, 368), (640, 307), (480, 230), (320, 256)]
_TALL = [(1920, 920), (923, 1280)]


def _settle(page):
    page.wait_for_function(
        "() => document.querySelectorAll('#home-overlay .home-recent-card').length > 0"
        " && document.querySelectorAll('#home-overlay .home-action-tile').length > 0",
        timeout=10_000)


def _wheel_point(page):
    return page.evaluate(
        "() => { const b = document.getElementById('home-overlay')"
        ".getBoundingClientRect(); return [b.left + b.width / 2,"
        " b.top + Math.min(b.height / 2, 30)]; }")


@pytest.mark.parametrize("vp", _SHORT, ids=lambda v: f"{v[0]}x{v[1]}")
def test_the_wheel_scrolls_home_to_its_last_row(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, vp)
    try:
        _settle(page)
        st0 = page.evaluate(_STATE)
        assert st0["scrollH"] > st0["clientH"], (
            f"anchor: {vp} no longer overflows the panel, re-measure: {st0}")
        x, y = _wheel_point(page)
        page.mouse.move(x, y)
        page.mouse.wheel(0, 120)
        page.wait_for_function(
            "() => document.getElementById('home-overlay').scrollTop > 0",
            timeout=3_000)
        # Wheel on to the end; stop once the panel reports it is there, or
        # after three steps in a row that move nothing.
        still = 0
        prev = -1
        for _ in range(80):
            top, end = page.evaluate(
                "() => { const o = document.getElementById('home-overlay');"
                " return [o.scrollTop, o.scrollHeight - o.clientHeight]; }")
            if top >= end - 1:
                break
            still = still + 1 if top == prev else 0
            if still >= 3:
                break
            prev = top
            page.mouse.wheel(0, 400)
            page.wait_for_timeout(80)
        st = page.evaluate(_STATE)
        assert st["overflowY"] == "auto", st
        assert st["docTop"] == 0 and st["bodyTop"] == 0, (
            f"{vp}: the page scrolled instead of the Home panel: {st}")
        assert st["scrollTop"] >= st["scrollH"] - st["clientH"] - 1, (
            f"{vp}: the wheel stopped short of the end of Home: {st}")
        lt, box = st["lastTile"], st["box"]
        assert lt["top"] >= box["top"] - 0.5 and lt["bottom"] <= box["bottom"] + 0.5, (
            f"{vp}: the last launcher tile is not whole inside the panel: {st}")
        if st["footerTop"] is not None:
            assert box["bottom"] <= st["footerTop"] + 0.5, (
                f"{vp}: the Home panel runs onto the footer: {st}")
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


_RING = """
() => {
  const ov = document.getElementById('home-overlay');
  const el = document.activeElement;
  if (!el || !ov.contains(el)) return null;
  const r = ov.getBoundingClientRect();
  const port = {top: r.top + ov.clientTop, left: r.left + ov.clientLeft};
  port.bottom = port.top + ov.clientHeight;
  port.right = port.left + ov.clientWidth;
  const cs = getComputedStyle(el);
  const ext = cs.outlineStyle === 'none' ? 0
    : parseFloat(cs.outlineWidth) + Math.max(0, parseFloat(cs.outlineOffset) || 0);
  const b = el.getBoundingClientRect();
  return {id: el.id || String(el.className).slice(0, 40), ext,
          visible: el.matches(':focus-visible'),
          clip: Math.max(port.top - (b.top - ext), (b.bottom + ext) - port.bottom,
                         port.left - (b.left - ext), (b.right + ext) - port.right)};
}
"""

# 480x230 leaves the panel a 72 px viewport, shorter than a launcher tile plus
# its ring, so no scroll position can show a whole ring there (audit, the
# limit of that size); every other short size must.
_RING_SIZES = [(1366, 768), (1024, 600), (768, 368), (640, 307), (320, 256)]


@pytest.mark.parametrize("vp", _RING_SIZES, ids=lambda v: f"{v[0]}x{v[1]}")
def test_tab_shows_each_home_control_with_its_whole_focus_ring(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, vp)
    try:
        _settle(page)
        seen = []
        for _ in range(80):
            page.keyboard.press("Tab")
            st = page.evaluate(_RING)
            if st is None:
                if seen:
                    break
                continue
            seen.append(st)
        assert len(seen) >= 6, f"anchor: Tab reached {len(seen)} Home controls: {seen}"
        assert all(s["visible"] and s["ext"] > 0 for s in seen), (
            f"{vp}: a Tab-focused Home control shows no :focus-visible ring: {seen}")
        cut = [s for s in seen if s["clip"] > 0.5]
        assert not cut, (
            f"{vp}: the panel edge cuts a Tab-focused control's ring (px): {cut}")
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", _TALL, ids=lambda v: f"{v[0]}x{v[1]}")
def test_a_tall_window_neither_scrolls_nor_clips_home(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, vp)
    try:
        _settle(page)
        x, y = _wheel_point(page)
        page.mouse.move(x, y)
        page.mouse.wheel(0, 400)
        page.wait_for_timeout(200)
        st = page.evaluate(_STATE)
        assert st["scrollH"] <= st["clientH"], (
            f"{vp}: Home overflows its panel at a tall window: {st}")
        assert st["scrollTop"] == 0 and st["docTop"] == 0 and st["bodyTop"] == 0, st
        # No scrollbar gutter: the content box keeps its full width.
        assert st["offsetW"] - st["clientW"] <= 2, (
            f"{vp}: a scrollbar took width from Home: {st}")
        assert st["nOutside"] == 0, (
            f"{vp}: Home content reaches outside its panel and would be clipped:"
            f" {st['outside']}")
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
