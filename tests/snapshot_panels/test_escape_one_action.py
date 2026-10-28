"""
tests/snapshot_panels/test_escape_one_action.py
RM-1067 (s144 uiux): one Escape press does ONE thing.

Measured in headless Chromium before the fix (web/js/main.js), an Escape
pressed to close a transient layer was not consumed, so the next
document-level Escape handler acted on the same press:
- the view menu (#view-menu, _viewWireOnce) closed AND the Replay recording
  player released focus (web/js/panels/review_player.js _onKeydown moved
  focus from #view-trigger to #replay-video-section), as the RM-1062
  verifier reported;
- the view menu, the task modal (#task-modal) or the Home Find Match picker
  (#home-find-match-picker) closed AND the general Escape chain (the
  keyboard-shortcut handler: modal -> reply toast -> zen) exited zen mode,
  so an operator in zen who opened the menu and backed out of it lost zen.

The fix: each of the three layers consumes the Escape that closes it
(preventDefault, in the capture phase, so it runs before every bubble-phase
document handler whatever order they were added in), and the general Escape
chain, like the player (review_player_model.js hotkeyAction), stands down on
a press already consumed. A second Escape still reaches the next handler
(positive controls below), and an Escape with no layer open is untouched.

The Replay lane stays hidden under ?ui_mock=1, so the player tests reveal
#replay-video-section the way a servable sidecar would (the helper from
test_replay_space_single_action.py).
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page
from tests.snapshot_panels.test_replay_space_single_action import _open_loaded

_STATE = """
() => {
  const vm = document.getElementById('view-menu');
  const tm = document.getElementById('task-modal');
  const fp = document.getElementById('home-find-match-picker');
  const ae = document.activeElement;
  return {
    menuOpen: !!vm && !vm.classList.contains('hidden'),
    expanded: document.getElementById('view-trigger').getAttribute('aria-expanded'),
    modalOpen: !!tm && !tm.classList.contains('hidden'),
    pickerOpen: !!fp && !fp.classList.contains('hidden'),
    zen: document.body.dataset.zen || '',
    focus: ae ? (ae.id || ae.tagName) : null,
  };
}
"""


def _open_view(pw_browser, mock_server, vp, view):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    page.goto(mock_server.url + "/?ui_mock=1#" + view,
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        f"() => document.body.dataset.view === '{view}'", timeout=10_000
    )
    return ctx, page, errors


def _zen_on(page):
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    page.keyboard.press("z")
    assert page.evaluate(_STATE)["zen"] == "1", "Z did not turn zen on"


def _open_view_menu(page):
    page.click("#view-trigger")
    st = page.evaluate(_STATE)
    assert st["menuOpen"] and st["expanded"] == "true", st
    return st


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_closes_the_view_menu_without_moving_replay_focus(
        mock_server, pw_browser, vp):
    ctx, page, errors = _open_loaded(pw_browser, mock_server, vp)
    try:
        st = _open_view_menu(page)
        assert st["focus"] == "view-trigger", st
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert not st["menuOpen"] and st["expanded"] == "false", st
        assert st["focus"] == "view-trigger", (
            f"the Escape that closed the view menu also ran the player's "
            f"release-focus: {st}"
        )
        # Positive control: the player key is live, so the NEXT Escape
        # releases focus to the lane.
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert st["focus"] == "replay-video-section", st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_closes_the_view_menu_and_keeps_zen(mock_server, pw_browser, vp):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp, "home")
    try:
        _zen_on(page)
        _open_view_menu(page)
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert not st["menuOpen"], st
        assert st["zen"] == "1", f"closing the view menu also exited zen: {st}"
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert st["zen"] == "", f"a second Escape no longer exits zen: {st}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_closes_the_task_modal_and_keeps_zen(mock_server, pw_browser, vp):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp, "home")
    try:
        _zen_on(page)
        # openTaskModal (main.js) shows the modal by dropping .hidden; its
        # opener is a task-id chip in a coach card the fixtures do not carry.
        page.evaluate(
            "() => document.getElementById('task-modal').classList.remove('hidden')"
        )
        assert page.evaluate(_STATE)["modalOpen"]
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert not st["modalOpen"], st
        assert st["zen"] == "1", f"closing the task modal also exited zen: {st}"
        page.keyboard.press("Escape")
        assert page.evaluate(_STATE)["zen"] == ""
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_closes_the_find_match_picker_and_keeps_zen(
        mock_server, pw_browser, vp):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp, "home")
    try:
        page.wait_for_selector("#home-hero-cta", state="visible", timeout=10_000)
        _zen_on(page)
        page.click("#home-hero-cta")
        assert page.evaluate(_STATE)["pickerOpen"]
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert not st["pickerOpen"], st
        assert st["zen"] == "1", f"closing the Find Match picker also exited zen: {st}"
        page.keyboard.press("Escape")
        assert page.evaluate(_STATE)["zen"] == ""
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_with_no_layer_open_still_exits_zen(mock_server, pw_browser, vp):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp, "home")
    try:
        _zen_on(page)
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert st["zen"] == "", st
        assert not (st["menuOpen"] or st["modalOpen"] or st["pickerOpen"]), st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
