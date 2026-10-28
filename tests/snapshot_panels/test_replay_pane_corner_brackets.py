"""
tests/snapshot_panels/test_replay_pane_corner_brackets.py
RM-1064 (s144 uiux): the gold corner brackets of `.replay-main-pane`
scrolled away with the pane's content.

RM-1019 made the pane a y scroll container (web/css/panels/primitives.css),
but its Hextech brackets were still `position: absolute` ::before / ::after
boxes. An absolute box inside a scroll container is laid out against the
scrolled content, so it moves with it: measured headless at the 1920x920
baseline with a match loaded, at the pane's max scroll the top-left bracket
was gone and the bottom-right one floated about 211px above the pane's
visible bottom edge.

The fix paints the two brackets as background layers of the pane. A
background with `background-attachment: scroll` (the default) is fixed to
the element's own box, so it stays on the visible corners at every scroll
offset. That background also runs under the scrollbar, where a classic
opaque Windows scrollbar hid the bottom-right bracket, so the pane styles a
12px scrollbar with a transparent gutter whose track margins keep the thumb
out of the corners.

This is a rendered-pixel question (CLAUDE.md R3), so the test samples the
accent colour in a 16px square at each visible corner of the pane (inside
its border, scrollbar included), at rest and at max scroll. The harness
browser runs with Chromium's headless default --hide-scrollbars, which
cannot show the scrollbar half, so each case also runs in a second browser
launched without that switch.
"""
import io

import pytest
from PIL import Image

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page
# Waits for the timeline rows as well as the grid: the timeline fills in
# after the grid, and the pane only overflows once both are in.
from tests.snapshot_panels.test_replay_timeline_rows_and_grid_reach import (
    _load_first_match,
)

# Sampled square, in CSS px, at each corner of the pane's visible padding box.
_SQ = 16
# A quarter ring 2px thick and 14px in radius covers about 40 px; anti-aliased
# edges blend, so count the clearly gold pixels and ask for a fraction of it.
_MIN_GOLD_PX = 10
_MAX_DIST = 48

# Resolve --accent to sRGB bytes through a canvas: themes.css declares it in
# oklch(), which getComputedStyle returns unresolved.
_ACCENT_RGB = """
() => {
  const probe = document.createElement('div');
  probe.style.color = 'var(--accent)';
  document.body.appendChild(probe);
  const css = getComputedStyle(probe).color;
  probe.remove();
  const c = document.createElement('canvas');
  c.width = c.height = 1;
  const g = c.getContext('2d');
  g.fillStyle = css;
  g.fillRect(0, 0, 1, 1);
  const d = g.getImageData(0, 0, 1, 1).data;
  return [d[0], d[1], d[2]];
}
"""

# The pane's box inside its border, scrollbar included (the visible corner
# a reader sees); sb = the scrollbar's width.
_PANE_BOX = """
(top) => {
  const el = document.querySelector('.replay-main-pane');
  el.scrollTop = top === 'max' ? el.scrollHeight : 0;
  const r = el.getBoundingClientRect();
  const cs = getComputedStyle(el);
  const bl = parseFloat(cs.borderLeftWidth), br = parseFloat(cs.borderRightWidth);
  const bt = parseFloat(cs.borderTopWidth), bb = parseFloat(cs.borderBottomWidth);
  const w = r.width - bl - br;
  return {
    x: r.left + bl, y: r.top + bt, w, h: r.height - bt - bb,
    sb: w - el.clientWidth,
    st: el.scrollTop, sh: el.scrollHeight, ch: el.clientHeight,
  };
}
"""


@pytest.fixture(scope="module")
def pw_browser_scrollbars(pw_browser):
    """A second headless browser that draws real (non-overlay) scrollbars."""
    b = pw_browser.browser_type.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        ignore_default_args=["--hide-scrollbars"],
    )
    yield b
    b.close()


def _gold_px(page, x, y, accent):
    png = page.screenshot(clip={"x": x, "y": y, "width": _SQ, "height": _SQ})
    img = Image.open(io.BytesIO(png)).convert("RGB")
    n = 0
    for px in img.getdata():
        d = sum((a - b) ** 2 for a, b in zip(px, accent)) ** 0.5
        if d <= _MAX_DIST:
            n += 1
    return n


@pytest.mark.parametrize("bars", ["hidden", "shown"])
@pytest.mark.parametrize("scroll", ["rest", "max"])
@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_main_pane_brackets_stay_on_visible_corners(
        mock_server, request, vp, scroll, bars):
    browser = request.getfixturevalue(
        "pw_browser" if bars == "hidden" else "pw_browser_scrollbars")
    ctx, page, errors = _new_page(browser, mock_server, vp)
    try:
        _load_first_match(page, mock_server)
        accent = page.evaluate(_ACCENT_RGB)
        box = page.evaluate(_PANE_BOX, 0 if scroll == "rest" else "max")
        page.wait_for_timeout(50)
        if vp == (1920, 920):
            # Non-vacuous: at the baseline the loaded pane really scrolls,
            # and the second browser really draws its scrollbar.
            assert box["sh"] > box["ch"] + 50, box
            if scroll == "max":
                assert box["st"] > 50, box
            if bars == "shown":
                assert box["sb"] > 0, box
        tl = _gold_px(page, box["x"], box["y"], accent)
        br = _gold_px(page, box["x"] + box["w"] - _SQ,
                      box["y"] + box["h"] - _SQ, accent)
        assert tl >= _MIN_GOLD_PX, (
            f"top-left bracket not on the visible corner ({tl} gold px, "
            f"accent {accent}): {box}")
        assert br >= _MIN_GOLD_PX, (
            f"bottom-right bracket not on the visible corner ({br} gold px, "
            f"accent {accent}): {box}")
        assert not errors, errors
    finally:
        ctx.close()


def _square(page, x, y):
    png = page.screenshot(clip={"x": x, "y": y, "width": _SQ, "height": _SQ})
    return Image.open(io.BytesIO(png)).convert("RGB")


@pytest.mark.parametrize("bars", ["hidden", "shown"])
@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_main_pane_corners_look_the_same_at_every_scroll(
        mock_server, request, vp, bars):
    """Each corner square renders the same at rest and at max scroll: the
    bracket does not move, and the scrollbar thumb never reaches it (a
    gold count alone passed with a translucent thumb laid over the ring)."""
    browser = request.getfixturevalue(
        "pw_browser" if bars == "hidden" else "pw_browser_scrollbars")
    ctx, page, errors = _new_page(browser, mock_server, vp)
    try:
        _load_first_match(page, mock_server)
        shots = {}
        for scroll in (0, "max"):
            box = page.evaluate(_PANE_BOX, scroll)
            page.wait_for_timeout(50)
            shots[scroll] = (
                _square(page, box["x"], box["y"]),
                _square(page, box["x"] + box["w"] - _SQ,
                        box["y"] + box["h"] - _SQ),
                box,
            )
        for i, name in enumerate(("top-left", "bottom-right")):
            a, b = shots[0][i], shots["max"][i]
            worst = max(max(abs(p - q) for p, q in zip(pa, pb))
                        for pa, pb in zip(a.getdata(), b.getdata()))
            assert worst <= 8, (
                f"{name} corner changes between rest and max scroll "
                f"(max channel diff {worst}): {shots[0][2]} vs {shots['max'][2]}")
        assert not errors, errors
    finally:
        ctx.close()


def _luminance(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_main_pane_scrollbar_thumb_is_visible(mock_server, pw_browser_scrollbars):
    """The thumb is the only cue that grid rows sit below the fold, so it
    must meet WCAG 1.4.11 non-text contrast (3:1) against the pane surface,
    measured on rendered pixels: the thumb column vs the padding beside it."""
    ctx, page, errors = _new_page(pw_browser_scrollbars, mock_server, (1920, 920))
    try:
        _load_first_match(page, mock_server)
        box = page.evaluate(_PANE_BOX, 0)
        page.wait_for_timeout(50)
        assert box["sb"] > 0 and box["sh"] > box["ch"] + 50, box
        y = box["y"] + 60
        thumb = _square(page, box["x"] + box["w"] - box["sb"] / 2 - _SQ / 2, y)
        pad = _square(page, box["x"] + box["w"] - box["sb"] - _SQ - 2, y)
        t = thumb.getpixel((_SQ // 2, _SQ // 2))
        s = pad.getpixel((_SQ // 2, _SQ // 2))
        hi, lo = sorted((_luminance(t), _luminance(s)), reverse=True)
        ratio = (hi + 0.05) / (lo + 0.05)
        assert ratio >= 3.0, (
            f"scrollbar thumb {t} on surface {s}: {ratio:.2f}:1 < 3:1")
        assert not errors, errors
    finally:
        ctx.close()


# The list pane does not scroll (its <ul> does), so its pseudo-element
# brackets stay; pin that they still paint, as the positive control for the
# sampler above.
_LIST_BOX = """
() => {
  const el = document.querySelector('.replay-list-pane');
  const r = el.getBoundingClientRect();
  return {x: r.left + el.clientLeft, y: r.top + el.clientTop,
          w: el.clientWidth, h: el.clientHeight};
}
"""


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_list_pane_brackets_still_paint(mock_server, pw_browser, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    try:
        _load_first_match(page, mock_server)
        accent = page.evaluate(_ACCENT_RGB)
        box = page.evaluate(_LIST_BOX)
        tl = _gold_px(page, box["x"], box["y"], accent)
        br = _gold_px(page, box["x"] + box["w"] - _SQ,
                      box["y"] + box["h"] - _SQ, accent)
        assert tl >= _MIN_GOLD_PX and br >= _MIN_GOLD_PX, (tl, br, box)
        assert not errors, errors
    finally:
        ctx.close()
