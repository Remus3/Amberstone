"""
tests/snapshot_panels/test_menu_chrome_click_keeps_focus.py
RM-1555 (s144 uiux) - a click on a menu's non-focusable chrome (a divider,
a section heading, the lane name label) leaves keyboard focus where it was,
so the Escape that then closes the menu still hands focus back to its opener.

THE DEFECT, measured in headless Chromium under /?ui_mock=1 at local main
before the fix, the same in all four role="menu" popups of web/js/main.js:
  - the header view menu (#view-menu, its two .view-menu-divider rules);
  - the Lobby mode menu (#lv-mode-menu, its .lq-mode-section headings);
  - the Home Find Match picker (#home-find-match-picker, the same headings);
  - the Lobby lane popup (#lv-lane-popup, its hover label).
A press on that chrome moved focus to <body> (the browser's mousedown focus
fix-up: the target and its ancestors are not focusable). The focusout closers
ignore a null related target, so the menu stayed open, and the Escape that
then closed it found no focus inside (each close helper refocuses only when
`hadFocus`), so focus was left on <body>: the keyboard user lost their place
in a menu they never left. On the view menu a POINTER open did the same: the
trigger held focus until the divider click took it.

THE FIX (web/js/main.js _holdFocusOnMenuChrome): each menu cancels the
mousedown default when the press is not on a focusable control inside it.
A press on a row / item / cell is left alone, so picks are unchanged.

Every case checks first that the click really lands on the named chrome
(document.elementFromPoint), so a moved or zero-size element cannot pass the
test vacuously.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page

_NO_TRANSITIONS = "*, *::before, *::after { transition: none !important; }"

_STATE = """
(menuSel) => {
  const m = document.querySelector(menuSel);
  const ae = document.activeElement;
  let focus = null;
  if (ae === document.body) {
    focus = 'BODY';  // body carries data-view too; never read it as a row
  } else if (ae) {
    const d = ae.dataset || {};
    focus = ae.id || (d.view && 'view:' + d.view) || (d.qid && 'qid:' + d.qid)
      || (d.hfmQid && 'hfm:' + d.hfmQid) || (d.pref && 'pref:' + d.pref)
      || ae.tagName;
  }
  return {open: !!m && !m.classList.contains('hidden'), focus: focus};
}
"""

# Centre of the first visible match, and what really sits under it.
_AIM = """
(sel) => {
  const el = Array.from(document.querySelectorAll(sel))
    .find((n) => n.getClientRects().length);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  const hit = document.elementFromPoint(x, y);
  return {x: x, y: y, w: r.width, h: r.height,
          onTarget: !!hit && (hit === el || el.contains(hit))};
}
"""


def _goto(page, mock_server, view, ready):
    page.goto(mock_server.url + "/?ui_mock=1#" + view,
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        f"() => document.body.dataset.view === '{view}'", timeout=10_000)
    page.wait_for_selector(ready, state="visible", timeout=10_000)
    page.add_style_tag(content=_NO_TRANSITIONS)


def _open_view_menu_keyboard(page):
    page.wait_for_function(
        "() => !!document.querySelector("
        "'#view-menu .view-menu-item.active[data-view=\"history\"]')",
        timeout=10_000)
    page.focus("#view-trigger")
    page.keyboard.press("Enter")


def _open_view_menu_pointer(page):
    page.click("#view-trigger")


def _open_mode_menu(page):
    page.focus("#lv-mode-trigger")
    page.keyboard.press("Enter")
    # The trigger keeps focus on open; the keyboard user then moves in.
    page.focus("#lv-mode-menu .lq-mode-item[data-qid='420']")


def _open_find_match(page):
    page.focus("#home-hero-cta")
    page.keyboard.press("Enter")


def _open_lane_popup(page):
    page.wait_for_function(
        "() => document.getElementById('lv-lane-primary').dataset.pref"
        " === 'MIDDLE'", timeout=10_000)
    page.focus("#lv-lane-primary")
    page.keyboard.press("Enter")


def _stub_lcu(page):
    page.route("**/api/lcu-cmd", lambda r: r.fulfill(
        status=200, content_type="application/json", body="{}"))


# id: (view, ready selector, menu, opener, open fn, chrome, focus in menu)
_CASES = {
    "view-menu-keyboard": ("history", "#view-trigger", "#view-menu",
                           "view-trigger", _open_view_menu_keyboard,
                           "#view-menu .view-menu-divider", "view:history"),
    "view-menu-pointer": ("history", "#view-trigger", "#view-menu",
                          "view-trigger", _open_view_menu_pointer,
                          "#view-menu .view-menu-divider", "view-trigger"),
    "lobby-mode-menu": ("lobby", "#lv-mode-trigger", "#lv-mode-menu",
                        "lv-mode-trigger", _open_mode_menu,
                        "#lv-mode-menu .lq-mode-section", "qid:420"),
    "find-match-picker": ("home", "#home-hero-cta", "#home-find-match-picker",
                          "home-hero-cta", _open_find_match,
                          "#home-find-match-picker .lq-mode-section", "hfm:0"),
    "lobby-lane-popup": ("lobby", "#lv-lane-primary", "#lv-lane-popup",
                         "lv-lane-primary", _open_lane_popup,
                         "#lv-lane-popup-label", "pref:MIDDLE"),
}


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
@pytest.mark.parametrize("case", sorted(_CASES))
def test_chrome_click_then_escape_returns_focus_to_the_opener(
        mock_server, pw_browser, case, vp):
    view, ready, menu, opener, open_fn, chrome, inside = _CASES[case]
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    try:
        _stub_lcu(page)
        _goto(page, mock_server, view, ready)
        open_fn(page)
        st = page.evaluate(_STATE, menu)
        assert st["open"] and st["focus"] == inside, (case, st)
        aim = page.evaluate(_AIM, chrome)
        # Anchor: the press really lands on the named chrome.
        assert aim and aim["onTarget"] and aim["w"] > 0 and aim["h"] > 0, (
            case, aim)
        page.mouse.click(aim["x"], aim["y"])
        st = page.evaluate(_STATE, menu)
        assert st["open"], f"{case}: a chrome click closed the menu: {st}"
        assert st["focus"] == inside, (
            f"{case}: a click on {chrome} moved focus out of place: {st}")
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE, menu)
        assert not st["open"], f"{case}: Escape left the menu open: {st}"
        assert st["focus"] == opener, (
            f"{case}: Escape after a chrome click left focus on"
            f" {st['focus']}, not the opener {opener}")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_row_click_still_moves_focus_and_picks(mock_server, pw_browser):
    # Positive control: the guard must not swallow a press on a real row.
    ctx, page, errors = _new_page(pw_browser, mock_server, VIEWPORTS[0])
    try:
        _goto(page, mock_server, "history", "#view-trigger")
        _open_view_menu_pointer(page)
        page.click("#view-menu .view-menu-item[data-view='session']")
        page.wait_for_function(
            "() => document.body.dataset.view === 'session'", timeout=10_000)
        st = page.evaluate(_STATE, "#view-menu")
        assert not st["open"], st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_press_on_a_lane_cells_icon_still_picks_the_lane(
        mock_server, pw_browser):
    # Positive control: the press lands on the <img> inside the cell button,
    # so the guard's closest() must find the button and leave the press be.
    ctx, page, errors = _new_page(pw_browser, mock_server, VIEWPORTS[0])
    posts: list[str] = []
    try:
        page.route("**/api/lcu-cmd", lambda r: (
            posts.append(r.request.post_data or ""),
            r.fulfill(status=200, content_type="application/json", body="{}")))
        _goto(page, mock_server, "lobby", "#lv-lane-primary")
        page.wait_for_function(
            "() => document.getElementById('lv-lane-primary').dataset.pref"
            " === 'MIDDLE'", timeout=10_000)
        page.click("#lv-lane-primary")
        img = "#lv-lane-popup .lobby-lane-popup-cell[data-pref='TOP'] img"
        aim = page.evaluate(
            "(s) => { const r = document.querySelector(s)"
            ".getBoundingClientRect(); const x = r.left + r.width / 2,"
            " y = r.top + r.height / 2; return {x: x, y: y,"
            " hit: document.elementFromPoint(x, y).tagName}; }", img)
        assert aim["hit"] == "IMG", aim
        page.mouse.click(aim["x"], aim["y"])
        st = page.evaluate(_STATE, "#lv-lane-popup")
        assert not st["open"], f"the icon press picked nothing: {st}"
        assert any("TOP" in p for p in posts), posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
