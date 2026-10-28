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

RM-1068 (s144 uiux) closes the same double action on two more layers
outside main.js: the Right Now cross-session digest popover
(#digest-popout, web/js/panels/right_now.js bindDigestIcon) and the
draft-elo contributions overlay (.draft-elo-contributions,
web/js/panels/draft_elo.js, the hover-only overlay Escape dismisses). Each
closed AND exited zen on one press; each now consumes the press it acts on,
and only that press.

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


# RM-1068 ----------------------------------------------------------------

_DIGEST_OPEN = (
    "() => !document.getElementById('digest-popout').classList.contains('hidden')"
)


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_closes_the_digest_popover_and_keeps_zen(
        mock_server, pw_browser, vp):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp, "home")
    try:
        _zen_on(page)
        # #digest-icon stays [hidden] until a digest payload arrives (the
        # fixtures carry none); its click handler is the real opener.
        page.evaluate("() => document.getElementById('digest-icon').click()")
        assert page.evaluate(_DIGEST_OPEN), "the digest popover did not open"
        page.keyboard.press("Escape")
        assert not page.evaluate(_DIGEST_OPEN), "Escape did not close the popover"
        st = page.evaluate(_STATE)
        assert st["zen"] == "1", f"closing the digest popover also exited zen: {st}"
        page.keyboard.press("Escape")
        assert page.evaluate(_STATE)["zen"] == "", "a second Escape no longer exits zen"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


_CONTRIB_SHOWN = """
() => {
  const o = document.querySelector('#am-draft-elo .draft-elo-contributions');
  return !!o && getComputedStyle(o).display !== 'none';
}
"""


def test_escape_dismisses_the_draft_elo_overlay_and_keeps_zen(
        mock_server, pw_browser):
    from tests.snapshot_panels.conftest import DRAFT_ELO_GOOD_BAND
    from tests.snapshot_panels.test_active_match_view import _open_active_match

    mock_server.set_draft_elo(DRAFT_ELO_GOOD_BAND)
    try:
        ctx, page, errors = _open_active_match(pw_browser, mock_server, "sr")
        try:
            page.wait_for_function(
                "document.querySelector('#am-draft-elo') && "
                "document.querySelector('#am-draft-elo').dataset.deState "
                "=== 'ready'",
                timeout=15_000,
            )
            _zen_on(page)
            page.hover("#am-draft-elo")
            assert page.evaluate(_CONTRIB_SHOWN), "hover did not show the overlay"
            page.keyboard.press("Escape")
            assert not page.evaluate(_CONTRIB_SHOWN), "Escape did not dismiss it"
            st = page.evaluate(_STATE)
            assert st["zen"] == "1", (
                f"dismissing the draft-elo overlay also exited zen: {st}"
            )
            # Nothing left to dismiss (still hovered, inline display:none),
            # so the next Escape reaches the zen exit.
            page.keyboard.press("Escape")
            assert page.evaluate(_STATE)["zen"] == "", (
                "a second Escape no longer exits zen"
            )
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors: {errors[:3]}"
    finally:
        mock_server.set_draft_elo(None)


# RM-1069 ----------------------------------------------------------------
# Two layers open at once: the cross-session digest popover (#digest-popout,
# z-index 9500, web/css/panels/header.css) over the task modal (#task-modal,
# z-index 200, web/css/panels/input_activity.css), with zen on underneath.
# Every layer listens on document in the capture phase; before the fix none
# of them checked e.defaultPrevented, so one Escape closed BOTH layers (and
# only zen survived, because the bubble-phase chain does check it). Each
# layer now stands down on a press another layer consumed, so the press goes
# to the first registered listener: right_now.js is imported by main.js and
# binds at module evaluation, before main.js wires the task modal, which is
# also the topmost layer here. One press peels one layer; for THIS pair the
# registration order is also top down. Close order is registration order,
# not z-order: a view menu or Find Match picker open over the task modal
# would lose the press to the modal first (filed RM-1070).

_STACK = """
() => ({
  digest: !document.getElementById('digest-popout').classList.contains('hidden'),
  modal: !document.getElementById('task-modal').classList.contains('hidden'),
  zen: document.body.dataset.zen || '',
})
"""


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_peels_stacked_layers_one_per_press(mock_server, pw_browser, vp):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp, "home")
    try:
        _zen_on(page)
        page.evaluate(
            "() => document.getElementById('task-modal').classList.remove('hidden')"
        )
        page.evaluate("() => document.getElementById('digest-icon').click()")
        st = page.evaluate(_STACK)
        assert st == {"digest": True, "modal": True, "zen": "1"}, st
        page.keyboard.press("Escape")
        st = page.evaluate(_STACK)
        assert st == {"digest": False, "modal": True, "zen": "1"}, (
            f"the first Escape did not close only the topmost layer: {st}"
        )
        page.keyboard.press("Escape")
        st = page.evaluate(_STACK)
        assert st == {"digest": False, "modal": False, "zen": "1"}, (
            f"the second Escape did not close only the task modal: {st}"
        )
        page.keyboard.press("Escape")
        st = page.evaluate(_STACK)
        assert st["zen"] == "", f"the third Escape no longer exits zen: {st}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


# A press consumed UPSTREAM is not taken again, by any layer. The stack test
# above can only reach the listeners registered after another layer's, so
# this one consumes the Escape in a window capture listener (window runs
# before every document listener) and asserts each layer stays open. The
# first-registered layer (the digest popover) is pinned only here.

_CONSUME_UPSTREAM = """
() => window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') e.preventDefault();
}, true)
"""

_LAYER_OPEN = {
    "task-modal": "() => !document.getElementById('task-modal').classList.contains('hidden')",
    "view-menu": "() => !document.getElementById('view-menu').classList.contains('hidden')",
    "find-match-picker": (
        "() => !document.getElementById('home-find-match-picker')"
        ".classList.contains('hidden')"
    ),
    "digest-popover": _DIGEST_OPEN,
}


def _open_layer(page, layer):
    if layer == "task-modal":
        page.evaluate(
            "() => document.getElementById('task-modal').classList.remove('hidden')"
        )
    elif layer == "view-menu":
        page.click("#view-trigger")
    elif layer == "find-match-picker":
        page.wait_for_selector("#home-hero-cta", state="visible", timeout=10_000)
        page.click("#home-hero-cta")
    else:
        page.evaluate("() => document.getElementById('digest-icon').click()")


@pytest.mark.parametrize("layer", sorted(_LAYER_OPEN))
def test_a_press_consumed_upstream_leaves_the_layer_open(
        mock_server, pw_browser, layer):
    ctx, page, errors = _open_view(pw_browser, mock_server, VIEWPORTS[0], "home")
    try:
        _open_layer(page, layer)
        assert page.evaluate(_LAYER_OPEN[layer]), f"{layer} did not open"
        page.evaluate(_CONSUME_UPSTREAM)
        page.keyboard.press("Escape")
        assert page.evaluate(_LAYER_OPEN[layer]), (
            f"{layer} closed on an Escape another listener had consumed"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_press_consumed_upstream_leaves_the_draft_elo_overlay_shown(
        mock_server, pw_browser):
    from tests.snapshot_panels.conftest import DRAFT_ELO_GOOD_BAND
    from tests.snapshot_panels.test_active_match_view import _open_active_match

    mock_server.set_draft_elo(DRAFT_ELO_GOOD_BAND)
    try:
        ctx, page, errors = _open_active_match(pw_browser, mock_server, "sr")
        try:
            page.wait_for_function(
                "document.querySelector('#am-draft-elo') && "
                "document.querySelector('#am-draft-elo').dataset.deState "
                "=== 'ready'",
                timeout=15_000,
            )
            page.hover("#am-draft-elo")
            assert page.evaluate(_CONTRIB_SHOWN), "hover did not show the overlay"
            page.evaluate(_CONSUME_UPSTREAM)
            page.keyboard.press("Escape")
            assert page.evaluate(_CONTRIB_SHOWN), (
                "the draft-elo overlay was dismissed by an Escape another "
                "listener had consumed"
            )
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors: {errors[:3]}"
    finally:
        mock_server.set_draft_elo(None)
