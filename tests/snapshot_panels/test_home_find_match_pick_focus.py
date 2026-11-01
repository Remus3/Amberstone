"""
tests/snapshot_panels/test_home_find_match_pick_focus.py
RM-1313 (s144 uiux) - where keyboard focus lands after a queue is picked in
the Home "Find Match" picker.

THE DEFECT. Picking a queue item in #home-find-match-picker (web/js/main.js
_homeWireStartup, the .lq-mode-item[data-hfm-qid] click handler) hides the
picker and routes to #lobby, but places focus nowhere. The focused item goes
display:none with the picker, so focus drops to <body> on the newly shown
Lobby view. MEASURED here in headless Chromium under /?ui_mock=1#home at
1920x920 and 923x1280 before the fix: after Enter on Ranked Solo/Duo (420)
or Practice Tool (0), and after a pointer click on either, document.
activeElement was BODY within 1.5 s in all 8 runs, with the view on "lobby"
and #lv-mode-trigger rendered. A keyboard user had to Tab from the top of the
page to get back to the lobby controls.

THE FIX. When focus was inside the picker at the pick, focus moves to the
Lobby view's #lv-mode-trigger ("Change Lobby Mode") once the route has
applied: the control that shows the queue just chosen and the one that
changes it again. It is the same rule the Lobby mode menu follows on an item
pick (RM-1252 closeModeMenu(true), which also refocuses after a pointer
pick, since a click focuses the button first). A pointer pick lands focus
there without matching :focus-visible, so no ring is painted for a mouse
user; a keyboard pick does match it. Nothing is focused when the view did
not become "lobby" or the trigger is not rendered, and focus is never moved
when it was outside the picker.

/api/lcu-cmd is intercepted at the page, so nothing but the local mock is
reached.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS
from tests.snapshot_panels.test_home_find_match_picker_focus import (
    _STATE,
    _assert_closed,
    _keyboard_open,
    _open_home,
)

_ITEM = '#home-find-match-picker .lq-mode-item[data-hfm-qid="{qid}"]'

_AFTER = """
() => {
  const ae = document.activeElement;
  const t = document.getElementById('lv-mode-trigger');
  return {
    focus: ae ? (ae.id || ae.tagName) : null,
    ring: !!ae && ae.matches(':focus-visible'),
    view: document.body.dataset.view,
    hash: location.hash,
    trigger: !!t && t.getClientRects().length > 0,
  };
}
"""

# Ranked Solo/Duo goes through change_queue_type; Practice Tool through
# lobby.create_practice_tool. Both route to #lobby.
_PICKS = [
    ("420", {"cmd": "change_queue_type", "queue_id": 420}),
    ("0", {"cmd": "lobby.create_practice_tool"}),
]


def _wait_posts(page, posts):
    for _ in range(40):
        if posts:
            return
        page.wait_for_timeout(50)


def _assert_on_trigger(page, ring):
    after = page.evaluate(_AFTER)
    assert after["view"] == "lobby" and after["hash"] == "#lobby", after
    assert after["trigger"], f"#lv-mode-trigger not rendered: {after}"
    assert after["focus"] == "lv-mode-trigger", (
        f"focus did not land on the Lobby mode trigger: {after}")
    assert after["ring"] is ring, after
    # The Lobby view's own refresh must not throw it away again.
    page.wait_for_timeout(1500)
    later = page.evaluate(_AFTER)
    assert later["focus"] == "lv-mode-trigger", (
        f"focus left the trigger after the lobby refresh: {later}")


@pytest.mark.parametrize("qid,cmd", _PICKS, ids=["ranked", "practice"])
@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_keyboard_pick_lands_focus_on_the_lobby_mode_trigger(
        mock_server, pw_browser, vp, qid, cmd):
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        page.focus(_ITEM.format(qid=qid))
        page.keyboard.press("Enter")
        _assert_closed(page.evaluate(_STATE))
        _wait_posts(page, posts)
        assert cmd in posts, posts
        _assert_on_trigger(page, ring=True)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_pointer_pick_lands_focus_without_a_ring(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, vp)
    try:
        page.click("#home-hero-cta")
        page.click(_ITEM.format(qid="440"))
        _assert_closed(page.evaluate(_STATE))
        _wait_posts(page, posts)
        assert {"cmd": "change_queue_type", "queue_id": 440} in posts, posts
        _assert_on_trigger(page, ring=False)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_pick_with_focus_outside_the_picker_does_not_steal_it(
        mock_server, pw_browser):
    """Control: focus is moved only when it was inside the picker."""
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, VIEWPORTS[0])
    try:
        page.click("#home-hero-cta")
        page.focus("#view-trigger")
        page.evaluate(
            "(s) => document.querySelector(s).click()", _ITEM.format(qid="420"))
        _wait_posts(page, posts)
        assert {"cmd": "change_queue_type", "queue_id": 420} in posts, posts
        after = page.evaluate(_AFTER)
        assert after["view"] == "lobby", after
        assert after["focus"] == "view-trigger", (
            f"a pick moved focus that was not in the picker: {after}")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_no_refocus_when_the_lobby_trigger_is_not_rendered(
        mock_server, pw_browser):
    """Control: a hidden trigger is never focused (focus is left as is)."""
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, VIEWPORTS[0])
    try:
        page.add_style_tag(content="#lv-mode-trigger { display: none !important; }")
        _keyboard_open(page)
        page.focus(_ITEM.format(qid="420"))
        page.keyboard.press("Enter")
        _wait_posts(page, posts)
        after = page.evaluate(_AFTER)
        assert after["view"] == "lobby" and not after["trigger"], after
        assert after["focus"] != "lv-mode-trigger", after
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
