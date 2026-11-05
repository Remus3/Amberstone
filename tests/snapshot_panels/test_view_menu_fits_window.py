"""
tests/snapshot_panels/test_view_menu_fits_window.py
RM-1435 (s144 uiux) - every row of the header view menu (#view-menu) is
reachable inside the window at every window size and zoom.

THE DEFECT. MEASURED in headless Chromium under /?ui_mock=1#history before
the fix. #view-menu (web/css/panels/header.css) is position:fixed at
top 70px, left 30px, reparented to the end of <body> by web/js/main.js
_viewWireOnce, 616 px tall (12 rows, 2 dividers) with no max-height and
overflow visible. A fixed box does not scroll with the page, so every row
below the window's bottom edge is out of reach, by pointer and by keyboard
alike (focus() cannot scroll a fixed box into view). The box runs from y 70
to 686: 1920x920, 1366x768 and 1280x720 fit, but at 1024x600 and 800x600
the lowest row (Auto) is cut, at 960x460 (the 1920x920 baseline at 200%
zoom) 3 rows are, and at 480x230 / 320x256 (400% zoom, the WCAG 1.4.10
reflow reference) only the first rows are whole. This menu is the only
route to every dashboard view.

THE FIX (web/css/panels/header.css .view-menu): the menu is capped at the
window less its 70 px top and an 8 px bottom margin, and scrolls its own
rows vertically (overflow-y auto, overscroll contained). Its rows and
dividers do not shrink (flex: none), so a capped menu scrolls instead of
squashing a 1 px divider to nothing. Where the menu already fit it keeps
its authored 616 px with no internal scroll (pinned at 1920x920 and
923x1280).

Reachability is checked the way a keyboard user meets it: every row is
focused in turn and must then sit fully inside both the window and the
menu's own visible box, which the menu's scroll provides.
"""
import pytest

from tests.snapshot_panels.test_view_menu_keyboard import (
    _N_ROWS,
    _keyboard_open,
    _open_view,
)

_GEO = """
() => {
  const m = document.getElementById('view-menu');
  const b = m.getBoundingClientRect();
  const cs = getComputedStyle(m);
  return {
    vw: document.documentElement.clientWidth,
    vh: document.documentElement.clientHeight,
    menu: {top: b.top, bottom: b.bottom, left: b.left, right: b.right,
           w: b.width, h: b.height},
    overflowY: cs.overflowY,
    vScroll: m.scrollHeight - m.clientHeight,
    hScroll: m.scrollWidth - m.clientWidth,
    dividers: Array.from(m.querySelectorAll('.view-menu-divider')).map(
      (d) => d.getBoundingClientRect().height),
    rows: Array.from(m.querySelectorAll('.view-menu-item')).map(
      (r) => r.getBoundingClientRect().height),
  };
}
"""

# Focus each row and report where it sits once focused (a focused control
# inside a scroll container is scrolled into it by the browser). The menu's
# visible box is its client area, so a row hidden under the menu's own
# clip edge is caught as well as one outside the window, and so is a row
# whose focus ring the clip edge cuts.
_ROWS_FOCUSED = """
() => {
  const m = document.getElementById('view-menu');
  const de = document.documentElement;
  const out = [];
  for (const el of m.querySelectorAll('.view-menu-item')) {
    el.focus();
    const r = el.getBoundingClientRect();
    const mb = m.getBoundingClientRect();
    const clipTop = mb.top + m.clientTop;
    const clipBottom = clipTop + m.clientHeight;
    out.push({view: el.dataset.view,
              focused: document.activeElement === el,
              open: !m.classList.contains('hidden'),
              top: r.top, bottom: r.bottom, left: r.left, right: r.right,
              // The row's 2 px --focus-ring included: a row scrolled flush
              // to the clip edge would lose that side of its ring.
              inMenu: r.top - 2 >= clipTop - 0.5
                      && r.bottom + 2 <= clipBottom + 0.5});
  }
  return {vw: de.clientWidth, vh: de.clientHeight, rows: out};
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
def test_the_menu_box_is_inside_the_window(mock_server, pw_browser, vp):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        st = page.evaluate(_GEO)
        assert len(st["rows"]) == _N_ROWS, f"anchor: the menu lost rows: {st}"
        assert _inside(st["menu"], st["vw"], st["vh"]), (
            f"{vp}: the fixed view menu runs outside the window, "
            f"where no scroll can reach it: {st}")
        assert st["hScroll"] <= 1, f"{vp}: the menu scrolls sideways: {st}"
        assert all(h >= 0.99 for h in st["dividers"]), (
            f"{vp}: a divider was squashed: {st['dividers']}")
        assert min(st["rows"]) >= 42 - _SLACK, (
            f"{vp}: a row was squashed under --hit-min: {st['rows']}")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", _VPS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_every_row_is_reachable_inside_the_window(mock_server, pw_browser, vp):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        st = page.evaluate(_ROWS_FOCUSED)
        assert len(st["rows"]) == _N_ROWS, st
        not_focused = [r for r in st["rows"] if not r["focused"] or not r["open"]]
        assert not not_focused, (
            f"{vp}: focusing a row failed or closed the menu: {not_focused}")
        cut = [r for r in st["rows"]
               if not _inside(r, st["vw"], st["vh"]) or not r["inMenu"]]
        assert not cut, (
            f"{vp}: {len(cut)} of {_N_ROWS} view rows stay outside the window "
            f"or the menu's visible box when focused: {cut[:3]}")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_end_key_scrolls_the_last_row_into_a_short_menu(mock_server, pw_browser):
    """The menu's own End key (main.js menu keydown) lands on Auto, whole."""
    vp = (480, 230)
    ctx, page, errors = _open_view(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        page.keyboard.press("End")
        st = page.evaluate(
            """() => {
              const m = document.getElementById('view-menu');
              const ae = document.activeElement;
              const r = ae.getBoundingClientRect();
              const mb = m.getBoundingClientRect();
              return {view: ae.dataset ? ae.dataset.view : null,
                      top: r.top, bottom: r.bottom,
                      clipBottom: mb.top + m.clientTop + m.clientHeight,
                      vh: document.documentElement.clientHeight,
                      scrollTop: m.scrollTop};
            }""")
        assert st["view"] == "auto", f"End did not reach the last row: {st}"
        assert st["bottom"] <= min(st["vh"], st["clipBottom"]) + _SLACK, (
            f"End focused the last row out of sight: {st}")
        assert st["scrollTop"] > 0, f"anchor: the menu did not need to scroll: {st}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


# The authored layout where it already fit: the box at its measured pre-fix
# size, no internal scroll.
_AUTHORED = {(1920, 920): 616.0, (923, 1280): 616.0}


@pytest.mark.parametrize("vp", list(_AUTHORED), ids=lambda v: f"{v[0]}x{v[1]}")
def test_a_menu_that_fit_keeps_its_authored_layout(mock_server, pw_browser, vp):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        st = page.evaluate(_GEO)
        assert abs(st["menu"]["h"] - _AUTHORED[vp]) <= 1, (
            f"{vp}: the menu changed height where it already fit: {st}")
        assert abs(st["menu"]["top"] - 70) <= _SLACK, (
            f"{vp}: the menu moved off its 70 px anchor: {st}")
        assert st["vScroll"] <= 1, f"{vp}: the menu scrolls where it fit: {st}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
