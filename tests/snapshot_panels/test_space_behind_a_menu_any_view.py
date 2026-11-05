"""
tests/snapshot_panels/test_space_behind_a_menu_any_view.py
RM-1366 (s144 uiux): a plain Space never scrolls the view behind an open menu.

RM-1324 held a Space behind a menu inside the Replay player only, and the player
stands down when no recording shows. The route is not the player's: open the view
menu, right-click a bare spot of the view (a right-click fires no click, so the
menu stays open, and a spot that takes no focus leaves focus on the body), then
press Space. The browser scrolls the scroller under that spot. Measured
unprevented at 1920x920 on six views: Settings 718 px, Session 716, Replay with no
recording 253, Champ Select 139, Historical PGR 65, Build Insights 31.

Ruling: the open menu owns that press, on every view. web/js/main.js holds a
plain or Shift+Space when a role="menu" is rendered and focus is on nothing a
Space activates or types into, and does nothing else with it: the menu stays
open, and Escape or a click closes it as before.

What stays as it was, each pinned below or in test_replay_keys_behind_menu.py:
- With no menu rendered, Space scrolls the view exactly as the browser does.
- A menu left open by class on another view is not rendered and holds nothing.
- Space on the focused trigger is the trigger's (it closes the menu).
- Ctrl+Space is not held (the Replay player's play-from-anywhere chord).

Each scroll test has a control that serves main.js without the hold and proves
the same route really scrolls, so a pane that cannot scroll cannot pass it.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page

VP = VIEWPORTS[0]

# The one line in web/js/main.js the controls take out.
MAIN_HOLD = "if (_spaceHeldBehindMenu(e)) e.preventDefault();"

# Historical PGR left this list with RM-1552: its 65 px of scroll came from
# the five coaching panels header.css failed to hide on that view, which
# squeezed the review into a 245 px band. With them hidden the hash-reached
# review fits at 1920x920 and has no scroller; the last test below pins that,
# so a review that grows a scroller again comes back here.
_VIEWS = ["settings", "session", "replay", "champ-select", "build-insights"]

# A bare spot (no focusable ancestor) inside the first rendered scroller of the
# showing view. Fails loud rather than clicking somewhere that cannot scroll.
_BARE_SPOT = """() => {
  const foc = "a[href],button,input,select,textarea,[tabindex],summary,"
    + "[contenteditable],[role=menu]";
  const view = document.querySelector('.view-section:not([hidden]), '
    + '#view-' + document.body.dataset.view);
  for (const e of document.querySelectorAll('*')) {
    if (!e.getClientRects().length) continue;
    if (e.scrollHeight <= e.clientHeight + 2) continue;
    if (!/(auto|scroll)/.test(getComputedStyle(e).overflowY)) continue;
    if (view && !(view.contains(e) || e.contains(view))) continue;
    const b = e.getBoundingClientRect();
    for (let y = b.y + 8; y < Math.min(b.bottom, innerHeight - 8); y += 13) {
      for (let x = b.right - 12; x > b.x; x -= 37) {
        const h = document.elementFromPoint(x, y);
        if (h && e.contains(h) && !h.closest(foc)) {
          return { x, y, id: e.id || e.className };
        }
      }
    }
  }
  return null;
}"""

_SCROLL_OF = """(id) => {
  const e = document.getElementById(id) || document.getElementsByClassName(id)[0];
  return e ? e.scrollTop : -1;
}"""

_SPACE_SPY = """() => {
  window.__space = { total: 0, prevented: 0 };
  window.addEventListener('keydown', (e) => {
    if (e.key !== ' ') return;
    window.__space.total += 1;
    if (e.defaultPrevented) window.__space.prevented += 1;
  });
}"""


def _strip_main_hold(route):
    resp = route.fetch()
    body = resp.text()
    assert MAIN_HOLD in body, "main.js's Space hold moved; fix this seam"
    route.fulfill(response=resp, body=body.replace(MAIN_HOLD, "", 1))


def _open_view(pw_browser, mock_server, view, hold_removed=False):
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    if hold_removed:
        page.route("**/js/main.js*", _strip_main_hold)
    page.goto(mock_server.url + "/?ui_mock=1#" + view,
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "(v) => document.body.dataset.view === v", arg=view, timeout=10_000
    )
    if view == "replay":
        # Load a match so the pane has rows to scroll; no recording shows.
        page.wait_for_selector(".replay-match-row", timeout=10_000)
        page.click(".replay-match-row")
        page.wait_for_function(
            "() => document.querySelectorAll('.replay-events-row').length > 1",
            timeout=10_000,
        )
        assert page.evaluate(
            "() => document.getElementById('replay-video-section')"
            ".getClientRects().length"
        ) == 0, "a recording shows; this file is about the no-recording route"
    page.wait_for_timeout(600)
    page.evaluate(_SPACE_SPY)
    return ctx, page, errors


def _menu_open(page):
    return page.evaluate(
        "() => !document.getElementById('view-menu').classList.contains('hidden')"
    )


def _on_body(page):
    return page.evaluate("() => document.activeElement === document.body")


def _right_click_bare_spot_with_menu_open(page):
    page.click("#view-trigger")
    assert _menu_open(page), "the view menu did not open"
    spot = page.evaluate(_BARE_SPOT)
    assert spot, "no bare spot in a scroller on this view; fixture changed"
    assert page.evaluate(_SCROLL_OF, spot["id"]) == 0
    page.mouse.click(spot["x"], spot["y"], button="right")
    assert _menu_open(page), "the right-click closed the menu"
    assert _on_body(page), "the right-click moved focus"
    return spot["id"]


@pytest.mark.parametrize("view", _VIEWS)
def test_space_behind_an_open_menu_does_not_scroll_the_view(
    mock_server, pw_browser, view
):
    ctx, page, errors = _open_view(pw_browser, mock_server, view)
    try:
        scroller = _right_click_bare_spot_with_menu_open(page)
        page.keyboard.press(" ")
        page.wait_for_timeout(700)
        assert page.evaluate(_SCROLL_OF, scroller) == 0, (
            f"Space scrolled {scroller} behind the open menu on {view}"
        )
        assert page.evaluate("() => window.__space") == {"total": 1, "prevented": 1}
        assert _menu_open(page), "Space closed the menu"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("hold_removed", [False, True], ids=["held", "control"])
def test_shift_space_behind_an_open_menu(mock_server, pw_browser, hold_removed):
    ctx, page, errors = _open_view(
        pw_browser, mock_server, "settings", hold_removed=hold_removed
    )
    try:
        scroller = _right_click_bare_spot_with_menu_open(page)
        page.evaluate(
            "(id) => { document.getElementById(id).scrollTop = 300; }", scroller
        )
        page.keyboard.press("Shift+Space")
        if hold_removed:
            # The control: without the hold the same press scrolls back.
            page.wait_for_function(
                f"() => ({_SCROLL_OF})({scroller!r}) < 300", timeout=5_000
            )
        else:
            page.wait_for_timeout(700)
            assert page.evaluate(_SCROLL_OF, scroller) == 300, "Shift+Space scrolled"
            assert _menu_open(page)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("view", _VIEWS)
def test_that_route_really_scrolls_without_the_hold(mock_server, pw_browser, view):
    ctx, page, errors = _open_view(pw_browser, mock_server, view, hold_removed=True)
    try:
        scroller = _right_click_bare_spot_with_menu_open(page)
        page.keyboard.press(" ")
        page.wait_for_function(
            f"() => ({_SCROLL_OF})({scroller!r}) > 0", timeout=5_000
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_historical_pgr_has_no_scroller_to_hold(mock_server, pw_browser):
    # Why historical-pgr is not in _VIEWS: nothing on it scrolls at this
    # viewport. If this fails, the view scrolls again - put it back in _VIEWS.
    ctx, page, errors = _open_view(pw_browser, mock_server, "historical-pgr")
    try:
        assert page.evaluate(
            "() => document.getElementById('view-historical-pgr')"
            ".getClientRects().length"
        ) == 1, "the review is not rendered; the check below would be empty"
        assert page.evaluate(_BARE_SPOT) is None
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_with_no_menu_open_space_still_scrolls_the_view(mock_server, pw_browser):
    ctx, page, errors = _open_view(pw_browser, mock_server, "settings")
    try:
        spot = page.evaluate(_BARE_SPOT)
        page.mouse.click(spot["x"], spot["y"])
        assert not _menu_open(page) and _on_body(page)
        page.keyboard.press(" ")
        page.wait_for_function(
            f"() => ({_SCROLL_OF})({spot['id']!r}) > 0", timeout=5_000
        )
        assert page.evaluate("() => window.__space")["prevented"] == 0
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_menu_open_only_by_class_on_another_view_holds_nothing(
    mock_server, pw_browser
):
    # Rendered is what counts: the Lobby view is display: none on Settings.
    ctx, page, errors = _open_view(pw_browser, mock_server, "settings")
    try:
        rects = page.evaluate(
            """() => {
              const m = document.getElementById('lv-mode-menu');
              m.classList.remove('hidden');
              return m.getClientRects().length;
            }"""
        )
        assert rects == 0, "the Lobby menu is rendered on Settings; fixture is wrong"
        spot = page.evaluate(_BARE_SPOT)
        page.mouse.click(spot["x"], spot["y"])
        page.keyboard.press(" ")
        page.wait_for_function(
            f"() => ({_SCROLL_OF})({spot['id']!r}) > 0", timeout=5_000
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_space_on_the_focused_trigger_is_still_the_triggers(mock_server, pw_browser):
    ctx, page, errors = _open_view(pw_browser, mock_server, "settings")
    try:
        page.click("#view-trigger")
        assert _menu_open(page)
        assert page.evaluate("() => document.activeElement.id") == "view-trigger"
        page.keyboard.press(" ")
        assert not _menu_open(page), "Space on the trigger did not close the menu"
        assert page.evaluate("() => window.__space")["prevented"] == 0
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_ctrl_space_is_not_held(mock_server, pw_browser):
    ctx, page, errors = _open_view(pw_browser, mock_server, "settings")
    try:
        _right_click_bare_spot_with_menu_open(page)
        page.keyboard.press("Control+Space")
        assert page.evaluate("() => window.__space") == {"total": 1, "prevented": 0}
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
