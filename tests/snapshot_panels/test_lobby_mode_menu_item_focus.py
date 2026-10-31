"""
tests/snapshot_panels/test_lobby_mode_menu_item_focus.py
RM-1252 (s144 uiux) - choosing a Lobby "Change Lobby Mode" item closes the
menu and hands keyboard focus back to its trigger.

THE DEFECT. #lv-mode-menu (web/js/main.js _lobbyViewWireOnce) hid itself on
an item click but left document.activeElement on the item it had just
hidden. MEASURED in headless Chromium under /?ui_mock=1#lobby at 1920x920
and 923x1280 before the fix: Enter on a menu item closed the menu and focus
stayed on the display:none button, so the keyboard user's next Tab started
from an invisible control. The Escape path (RM-1251) already returned
focus to the trigger; the item path did not.

THE FIX. Every close of the menu goes through one helper. An item activation
with focus inside the menu returns focus to #lv-mode-trigger; a click
OUTSIDE the menu never moves focus (it stays where the click put it).

The LCU command the item fires is intercepted at the page (route on
/api/lcu-cmd), so the test never reaches anything but the local mock and
also pins that the item still dispatches its command.
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
    focusVisible: ae ? ae.getClientRects().length > 0 : false,
  };
}
"""


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


def _keyboard_open_and_reach(page, qid):
    """Enter on the trigger, then Tab until the item with ``qid`` has focus."""
    page.focus("#lv-mode-trigger")
    page.keyboard.press("Enter")
    st = page.evaluate(_STATE)
    assert st["open"] and st["expanded"] == "true", st
    for _ in range(12):
        page.keyboard.press("Tab")
        if page.evaluate(_STATE)["focus"] == f"qid:{qid}":
            return
    raise AssertionError(f"Tab never reached menu item qid {qid}")


def _wait_post(page, posts, n=1):
    for _ in range(40):
        if len(posts) >= n:
            return
        page.wait_for_timeout(50)


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_enter_on_a_queue_item_returns_focus_to_the_trigger(
        mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, vp)
    try:
        _keyboard_open_and_reach(page, 480)
        page.keyboard.press("Enter")
        st = page.evaluate(_STATE)
        assert not st["open"], f"the item did not close the menu: {st}"
        assert st["expanded"] == "false" and st["ariaHidden"] == "true", st
        assert st["focus"] == "lv-mode-trigger", (
            f"choosing a mode left focus on the hidden item: {st}"
        )
        assert st["focusVisible"], st
        _wait_post(page, posts)
        assert {"cmd": "change_queue_type", "queue_id": 480} in posts, posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_enter_on_practice_tool_returns_focus_to_the_trigger(
        mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, vp)
    try:
        _keyboard_open_and_reach(page, 0)
        page.keyboard.press("Enter")
        st = page.evaluate(_STATE)
        assert not st["open"] and st["expanded"] == "false", st
        assert st["focus"] == "lv-mode-trigger", st
        _wait_post(page, posts)
        assert {"cmd": "lobby.create_practice_tool"} in posts, posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_pointer_click_on_an_item_does_not_strand_focus(mock_server, pw_browser):
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, VIEWPORTS[0])
    try:
        page.click("#lv-mode-trigger")
        assert page.evaluate(_STATE)["open"]
        page.click('#lv-mode-menu .lq-mode-item[data-qid="420"]')
        st = page.evaluate(_STATE)
        assert not st["open"] and st["expanded"] == "false", st
        assert st["focus"] == "lv-mode-trigger", (
            f"a pointer pick left focus on the hidden item: {st}"
        )
        _wait_post(page, posts)
        assert {"cmd": "change_queue_type", "queue_id": 420} in posts, posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_outside_click_closes_without_moving_focus(mock_server, pw_browser):
    """Positive control: a click outside the menu closes it and focus stays
    on what the click focused - the close never steals it to the trigger.
    Run at 923x1280, where the YOUR MAINS tab sits clear of the open menu
    (at 1920x920 the menu covers it); the tab's click handler does not stop
    propagation, so the document closer runs."""
    ctx, page, errors, posts = _open_lobby(pw_browser, mock_server, VIEWPORTS[1])
    try:
        page.click("#lv-mode-trigger")
        assert page.evaluate(_STATE)["open"]
        page.click("#lv-mc-tab-you")
        st = page.evaluate(_STATE)
        assert not st["open"] and st["expanded"] == "false", st
        assert st["focus"] == "lv-mc-tab-you", (
            f"an outside click moved focus away from what it clicked: {st}"
        )
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
