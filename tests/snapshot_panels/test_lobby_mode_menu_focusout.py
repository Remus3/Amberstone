"""
tests/snapshot_panels/test_lobby_mode_menu_focusout.py
RM-1253 (s144 uiux) - keyboard focus leaving the Lobby "Change Lobby Mode"
trigger + menu pair closes the menu.

THE DEFECT. #lv-mode-menu (web/js/main.js _lobbyViewWireOnce) closed only on
a click (trigger toggle, item pick, the document closer) or on Escape. Found
by the RM-1252 verifier and MEASURED here in headless Chromium under
/?ui_mock=1#lobby at 1920x920 and 923x1280 before the fix: Tab past the last
item (TFT Double-Up), or Shift+Tab off the trigger, moved focus out of the
pair and the dropdown stayed open (aria-expanded "true"), hanging over the
party rows while the keyboard user worked elsewhere.

THE FIX. A focusout listener on the trigger and on the menu closes the menu
when the newly focused element is outside both, through the shared
closeModeMenu(false) helper (no refocus: focus stays where Tab put it).
Moving between the trigger and the items never closes it, a focus change
with no related target (a window blur, a click on bare page) is left to the
existing closers, and a pointer pick still dispatches its LCU command.

/api/lcu-cmd is intercepted at the page, so nothing but the local mock is
reached, and the controls below pin that leaving the menu fires NO command.
"""
import json

import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page

_STATE = """
() => {
  const m = document.getElementById('lv-mode-menu');
  const t = document.getElementById('lv-mode-trigger');
  const ae = document.activeElement;
  return {
    open: !!m && !m.classList.contains('hidden'),
    expanded: t.getAttribute('aria-expanded'),
    ariaHidden: m.getAttribute('aria-hidden'),
    focus: ae ? (ae.id || ae.dataset.qid && ('qid:' + ae.dataset.qid)
                 || ae.tagName) : null,
    inPair: !!ae && (ae === t || m.contains(ae)),
  };
}
"""

_LAST_QID = 1160  # TFT Double-Up, the last item in DOM / tab order


def _open_lobby(pw_browser, mock_server, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    posts: list[dict] = []

    def _lcu(route):
        try:
            posts.append(json.loads(route.request.post_data or "{}"))
        except ValueError:
            posts.append({})
        route.fulfill(status=200, content_type="application/json", body="{}")

    page.route("**/api/lcu-cmd", _lcu)
    page.goto(mock_server.url + "/?ui_mock=1#lobby",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function("() => document.body.dataset.view === 'lobby'",
                           timeout=10_000)
    page.wait_for_selector("#lv-mode-trigger", state="visible", timeout=10_000)
    return ctx, page, errors, posts


def _keyboard_open(page):
    page.focus("#lv-mode-trigger")
    page.keyboard.press("Enter")
    st = page.evaluate(_STATE)
    assert st["open"] and st["expanded"] == "true", st


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_tab_past_the_last_item_closes_the_menu(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        for _ in range(16):
            page.keyboard.press("Tab")
            if page.evaluate(_STATE)["focus"] == f"qid:{_LAST_QID}":
                break
        else:
            raise AssertionError("Tab never reached the last menu item")
        assert page.evaluate(_STATE)["open"], "menu closed before focus left it"
        page.keyboard.press("Tab")
        st = page.evaluate(_STATE)
        assert not st["inPair"], f"Tab did not leave the menu: {st}"
        assert not st["open"], f"focus left the menu but it stayed open: {st}"
        assert st["expanded"] == "false" and st["ariaHidden"] == "true", st
        assert posts == [], f"leaving the menu fired an LCU command: {posts}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_shift_tab_off_the_trigger_closes_the_menu(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        page.keyboard.press("Shift+Tab")
        st = page.evaluate(_STATE)
        assert not st["inPair"], f"Shift+Tab did not leave the trigger: {st}"
        assert not st["open"], f"focus left the trigger but the menu stayed open: {st}"
        assert st["expanded"] == "false" and st["ariaHidden"] == "true", st
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_moving_between_trigger_and_items_keeps_the_menu_open(
        mock_server, pw_browser, vp):
    """Control: Tab from the trigger into the items, through every item, and
    Shift+Tab back to the trigger never closes the menu."""
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        seen = []
        for _ in range(16):
            page.keyboard.press("Tab")
            st = page.evaluate(_STATE)
            assert st["open"] and st["expanded"] == "true", (
                f"moving focus inside the menu closed it: {st}")
            seen.append(st["focus"])
            if st["focus"] == f"qid:{_LAST_QID}":
                break
        assert seen[0] == "qid:0", seen
        assert seen[-1] == f"qid:{_LAST_QID}", seen
        for _ in range(len(seen)):
            page.keyboard.press("Shift+Tab")
            st = page.evaluate(_STATE)
            assert st["open"], f"Shift+Tab inside the menu closed it: {st}"
        assert page.evaluate(_STATE)["focus"] == "lv-mode-trigger"
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_pointer_pick_still_dispatches_and_refocuses(mock_server, pw_browser):
    """Control: the focusout closer must not pre-empt an item click."""
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, VIEWPORTS[0])
    try:
        page.click("#lv-mode-trigger")
        assert page.evaluate(_STATE)["open"]
        page.click('#lv-mode-menu .lq-mode-item[data-qid="440"]')
        st = page.evaluate(_STATE)
        assert not st["open"] and st["expanded"] == "false", st
        assert st["focus"] == "lv-mode-trigger", st
        for _ in range(40):
            if posts:
                break
            page.wait_for_timeout(50)
        assert {"cmd": "change_queue_type", "queue_id": 440} in posts, posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_window_blur_leaves_the_menu_open(mock_server, pw_browser):
    """Control: a focusout with no related target (window blur) is not a
    keyboard exit, so it is left to the click / Escape closers."""
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, VIEWPORTS[0])
    try:
        _keyboard_open(page)
        page.evaluate("""() => document.getElementById('lv-mode-trigger')
            .dispatchEvent(new FocusEvent('focusout',
                {bubbles: true, relatedTarget: null}))""")
        st = page.evaluate(_STATE)
        assert st["open"] and st["expanded"] == "true", st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
