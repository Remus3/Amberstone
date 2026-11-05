"""
tests/snapshot_panels/test_home_find_match_picker_fits.py
RM-1430 (s144 uiux) - the Home Find Match picker is reachable whole at
every window size and zoom.

THE DEFECT. MEASURED in headless Chromium under /?ui_mock=1#home before the
fix. #home-find-match-picker (web/css/panels/home.css) is a position:fixed
popover centred by translate(-50%, -50%), width min(960px, 92vw), with no
max-height and overflow visible, on the 4-column 1fr grid of .lq-mode-menu
(web/css/panels/header.css). A fixed box does not scroll with the page, so
whatever falls outside the window is unreachable. 1920x920, 1366x768,
1280x720, 1024x600, 923x1280, 800x600 and 960x460 (200% zoom) fit. At
768x368 (250% zoom of the 1920x920 baseline) the picker ran from y -38.5 to
406.5 and one of its 11 items was cut off; at 640x307 (300%) 6 of 11 were
fully inside the window, at 480x230 (400%) and 320x256 (the WCAG 1.4.10
reflow reference) 3 of 11, with the top edge at y -121 / -108. At 480 and
320 wide the 1fr columns also stopped at their min-content width and the
grid ran out past the picker's right edge.

THE FIX (web/css/panels/home.css .home-find-match-picker.lq-mode-menu): the
picker is capped at the window less a --space-3 margin each side
(max-width / max-height) and scrolls its own content vertically
(overflow-y auto, overscroll contained), and its columns are
repeat(auto-fit, minmax(min(100%, 150px), 1fr)), so a narrow picker folds
its four queue groups into 3, 2 or 1 columns instead of overflowing
sideways. At every width that already fit, the grid still lays out 4 equal
columns and the box keeps its authored size (pinned below at 1920x920 and
923x1280).

Reachability is checked the way a keyboard user meets it: every item is
focused in turn (Tab order) and must then sit fully inside the window, which
the picker's own scroll provides; the picker box itself must be inside the
window. /api/lcu-cmd is intercepted at the page, so nothing but the local
mock is reached.
"""
import pytest

from tests.snapshot_panels.test_home_find_match_picker_focus import (
    _keyboard_open,
    _open_home,
)

_GEO = """
() => {
  const p = document.getElementById('home-find-match-picker');
  const box = (el) => { const b = el.getBoundingClientRect();
    return {top: b.top, bottom: b.bottom, left: b.left, right: b.right,
            w: b.width, h: b.height}; };
  return {
    vw: document.documentElement.clientWidth,
    vh: document.documentElement.clientHeight,
    picker: box(p),
    // Rendered groups, not the computed template: auto-fit reports its
    // collapsed empty tracks as 0px entries there.
    groups: Array.from(p.querySelectorAll('.lq-mode-column')).map(
      (c) => { const b = c.getBoundingClientRect();
               return {top: Math.round(b.top), w: b.width}; }),
    hOverflow: p.scrollWidth - p.clientWidth,
    nItems: p.querySelectorAll('.lq-mode-item').length,
  };
}
"""

# Focus each item and report where it sits once focused (a focused control
# inside a scroll container is scrolled into it by the browser).
_ITEMS_FOCUSED = """
() => {
  const p = document.getElementById('home-find-match-picker');
  const de = document.documentElement;
  const out = [];
  for (const el of p.querySelectorAll('.lq-mode-item')) {
    el.focus();
    const r = el.getBoundingClientRect();
    out.push({qid: el.dataset.hfmQid, focused: document.activeElement === el,
              top: r.top, bottom: r.bottom, left: r.left, right: r.right,
              open: !p.classList.contains('hidden')});
  }
  return {vw: de.clientWidth, vh: de.clientHeight, items: out};
}
"""

_SLACK = 0.5

# Desktop sizes plus the 1920x920 baseline at 200 / 250 / 300 / 400% zoom and
# the WCAG reflow reference.
_VPS = [(1920, 920), (1366, 768), (1280, 720), (1024, 600), (923, 1280),
        (800, 600), (960, 460), (768, 368), (640, 307), (480, 230), (320, 256)]


def _inside(r, vw, vh):
    return (r["top"] >= -_SLACK and r["left"] >= -_SLACK
            and r["bottom"] <= vh + _SLACK and r["right"] <= vw + _SLACK)


@pytest.mark.parametrize("vp", _VPS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_the_picker_box_is_inside_the_window(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        st = page.evaluate(_GEO)
        assert st["nItems"] == 11, f"anchor: the picker lost its items: {st}"
        assert _inside(st["picker"], st["vw"], st["vh"]), (
            f"{vp}: the fixed picker runs outside the window, "
            f"where no scroll can reach it: {st}")
        assert st["hOverflow"] <= 1, (
            f"{vp}: the queue grid overflows the picker sideways: {st}")
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", _VPS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_every_queue_item_is_reachable_inside_the_window(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        st = page.evaluate(_ITEMS_FOCUSED)
        assert len(st["items"]) == 11, st
        not_focused = [i for i in st["items"] if not i["focused"] or not i["open"]]
        assert not not_focused, f"{vp}: focusing an item failed or closed: {not_focused}"
        cut = [i for i in st["items"] if not _inside(i, st["vw"], st["vh"])]
        assert not cut, (
            f"{vp}: {len(cut)} of 11 queue items stay outside the window "
            f"when focused: {cut[:3]}")
        assert posts == [], "focusing an item fired an LCU command"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


# The authored layout where it already fit: 4 equal columns, the box at its
# measured pre-fix size, no internal scroll.
_AUTHORED = {(1920, 920): (960.0, 364.0), (923, 1280): (849.16, 391.0)}


@pytest.mark.parametrize("vp", list(_AUTHORED), ids=lambda v: f"{v[0]}x{v[1]}")
def test_a_picker_that_fit_keeps_its_authored_layout(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        st = page.evaluate(_GEO)
        scroll = page.evaluate(
            "() => { const p = document.getElementById('home-find-match-picker');"
            " return p.scrollHeight - p.clientHeight; }")
        w, h = _AUTHORED[vp]
        g = st["groups"]
        assert len(g) == 4 and len({c["top"] for c in g}) == 1, (
            f"{vp}: the 4 queue groups no longer sit in one row: {st}")
        assert max(c["w"] for c in g) - min(c["w"] for c in g) <= 1, (
            f"{vp}: the 4 queue columns are no longer equal: {st}")
        assert abs(st["picker"]["w"] - w) <= 1 and abs(st["picker"]["h"] - h) <= 1, (
            f"{vp}: the picker changed size where it already fit: {st}")
        assert scroll <= 1, f"{vp}: the picker scrolls where it already fit: {scroll}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
