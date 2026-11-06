"""
tests/snapshot_panels/test_shortcuts_behind_a_modal.py
RM-1364 (s144 uiux): a page shortcut never acts behind an open modal.

RM-1323 made the global letter shortcuts in web/js/main.js stand down behind a
rendered role="menu", and RM-1324 did the same for the Replay player's own keys
(web/js/panels/review_player.js). Neither looked at the two full-window modals,
the task detail modal (#task-modal, opened from an activity row) and the
cross-session digest popout (#digest-popout), which RM-1427 (s150) later
retired, so only the task modal is tested here. Each was a position: fixed
scrim over the whole page, so whatever a key did there it did to a page the
operator cannot see. Measured in headless
Chromium at 1920x920 under ?ui_mock=1 before the fix, focus on the body, on
Home, Settings, Replay, Lobby and Session alike: A clicked ANALYZE NOW and Z
flipped zen behind either modal, Shift+R would wipe the saved preferences and
reload the page out from under it, and on Replay ] seeked a showing recording
from 20 to 30 behind the task modal.

Ruling: an open, rendered modal owns the page's shortcuts the way a menu does.
A modal layer carries `modal: true` in its web/js/lib/escape_layers.js
registration; escape_layers.modalLayerRendered() answers whether one is open
with a box, and main.js _letterShortcutsYield and the player's hotkeyAction
(as `modalOpen`) both read it, so the two cannot drift apart.

What stays as it was, each pinned below:
- Escape closes the modal (the dispatcher), and the shortcuts act again after.
- Space behind a modal is left to the browser, not held: with focus on the
  body it scrolled nothing on any of those five views, and a click inside the
  modal's own content may want it to scroll that content. It no longer plays.
- Ctrl+Space still plays (the documented play-from-anywhere chord, kept above
  the check exactly as RM-1324 kept it for a menu).
- A modal open by class but with no box (the overlay shell hides it with
  display: none !important) is over nothing and kills no key.

The modal is opened by class, as the RM-1323 / RM-1324 guards open menus:
ui_mock has no activity row to click, and the escape layer's isOpen() reads
the same class.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page
from tests.snapshot_panels.test_held_key_one_action import _expose_player_state
from tests.snapshot_panels.test_hotkey_letter_owners import (
    _ARM,
    _SPY,
    _assert_nothing_fired,
    _baseline,
    _press_and_assert_fired,
)
from tests.snapshot_panels.test_replay_space_single_action import (
    _MATCH_ROWS,
    _MEDIA_SPY,
)

VP = VIEWPORTS[0]

_MODALS = {
    "task": ("#task-modal", "#task-modal-close"),
}
_KEYS = ["a", "f", "z", "h", "?", "Shift+R"]


def _open_view(pw_browser, mock_server, view):
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    page.add_init_script(_SPY)
    page.goto(mock_server.url + f"/?ui_mock=1#{view}",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "(v) => document.body.dataset.view === v", arg=view, timeout=10_000
    )
    # A disabled ANALYZE NOW would make every "A did nothing" below vacuous.
    assert page.evaluate(_ARM) is True, "analyze-now is disabled in this view"
    return ctx, page, errors


def _modal_open(page, sel):
    return page.evaluate(
        "(s) => !document.querySelector(s).classList.contains('hidden')", sel
    )


def _open_modal(page, modal, focus):
    sel, close_btn = _MODALS[modal]
    rects = page.evaluate(
        """(s) => {
          const m = document.querySelector(s);
          m.classList.remove('hidden');
          return m.getClientRects().length;
        }""",
        sel,
    )
    assert rects > 0, f"{sel} is not rendered; the fixture is wrong"
    if focus == "close":
        page.focus(close_btn)
    else:
        page.evaluate("() => document.activeElement && document.activeElement.blur()")
    got = page.evaluate("() => document.activeElement === document.body")
    assert got == (focus == "body"), f"focus is not where the route leaves it: {focus}"


@pytest.mark.parametrize("focus", ["body", "close"])
@pytest.mark.parametrize("key", _KEYS)
@pytest.mark.parametrize("modal", list(_MODALS))
def test_a_letter_shortcut_does_not_fire_behind_an_open_modal(
    mock_server, pw_browser, modal, key, focus
):
    ctx, page, errors = _open_view(pw_browser, mock_server, "settings")
    try:
        _open_modal(page, modal, focus)
        before = _baseline(page)
        page.keyboard.press(key)
        _assert_nothing_fired(page, before, key)
        assert _modal_open(page, _MODALS[modal][0]), f"{key!r} closed the modal"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("key", _KEYS)
@pytest.mark.parametrize("modal", list(_MODALS))
def test_every_shortcut_acts_again_once_escape_has_closed_the_modal(
    mock_server, pw_browser, modal, key
):
    ctx, page, errors = _open_view(pw_browser, mock_server, "settings")
    try:
        _open_modal(page, modal, "body")
        page.keyboard.press("Escape")
        assert not _modal_open(page, _MODALS[modal][0]), "Escape left the modal open"
        _press_and_assert_fired(page, key)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("modal", list(_MODALS))
def test_a_modal_with_no_box_kills_no_shortcut(mock_server, pw_browser, modal):
    # Rendered is what counts: the overlay shell hides the modal with
    # display: none !important, the same state as here.
    ctx, page, errors = _open_view(pw_browser, mock_server, "settings")
    try:
        sel = _MODALS[modal][0]
        rects = page.evaluate(
            """(s) => {
              const m = document.querySelector(s);
              m.classList.remove('hidden');
              m.style.display = 'none';
              return m.getClientRects().length;
            }""",
            sel,
        )
        assert rects == 0, "the modal still has a box; the fixture is wrong"
        assert _modal_open(page, sel)
        _press_and_assert_fired(page, "a")
        _press_and_assert_fired(page, "z")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


# -- the Replay player's own keys ---------------------------------------------

_NOW = "() => document.getElementById('replay-video').currentTime"
_PLAYS = "() => window.__rpCalls.play + window.__rpCalls.pause"
_START = 20
_SEEKS = {"]": 30, "[": 10, "d": 25, "D": 15}


def _open_player(pw_browser, mock_server):
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    page.add_init_script(_MEDIA_SPY)
    page.route("**/panels/review_player.js*", _expose_player_state)
    page.goto(mock_server.url + "/?ui_mock=1#replay",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_selector(_MATCH_ROWS, timeout=10_000)
    page.click(_MATCH_ROWS)
    page.wait_for_function(
        "() => document.querySelectorAll('.replay-events-row').length > 1",
        timeout=10_000,
    )
    page.evaluate(
        """(start) => {
          document.getElementById('replay-video-section').hidden = false;
          window.__RP.markers = [{ t: 10 }, { t: 20 }, { t: 30 }];
          window.__RP.deaths = [15, 25];
          document.getElementById('replay-video').currentTime = start;
          window.__space = { total: 0, prevented: 0 };
          window.addEventListener('keydown', (e) => {
            if (e.key !== ' ') return;
            window.__space.total += 1;
            if (e.defaultPrevented) window.__space.prevented += 1;
          });
        }""",
        _START,
    )
    return ctx, page, errors


@pytest.mark.parametrize("focus", ["body", "close"])
@pytest.mark.parametrize("key", list(_SEEKS))
def test_a_replay_seek_key_stands_down_behind_the_task_modal(
    mock_server, pw_browser, key, focus
):
    ctx, page, errors = _open_player(pw_browser, mock_server)
    try:
        _open_modal(page, "task", focus)
        page.keyboard.press(key)
        assert page.evaluate(_NOW) == _START, (
            f"{key!r} seeked the video behind the modal, focus on {focus}"
        )
        assert _modal_open(page, "#task-modal"), f"{key!r} closed the modal"
        # Positive control: the same key seeks once Escape has closed it.
        page.keyboard.press("Escape")
        assert not _modal_open(page, "#task-modal")
        page.evaluate("() => document.activeElement && document.activeElement.blur()")
        page.keyboard.press(key)
        assert page.evaluate(_NOW) == _SEEKS[key], f"{key!r} is dead with no modal"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_space_behind_the_task_modal_plays_nothing_and_is_left_to_the_browser(
    mock_server, pw_browser
):
    ctx, page, errors = _open_player(pw_browser, mock_server)
    try:
        _open_modal(page, "task", "body")
        page.keyboard.press(" ")
        assert page.evaluate(_PLAYS) == 0, "Space toggled play behind the modal"
        got = page.evaluate("() => window.__space")
        assert got == {"total": 1, "prevented": 0}, (
            f"Space behind a modal is the browser's, not held: {got}"
        )
        assert _modal_open(page, "#task-modal"), "Space closed the modal"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_the_play_from_anywhere_chord_still_plays_behind_the_task_modal(
    mock_server, pw_browser
):
    ctx, page, errors = _open_player(pw_browser, mock_server)
    try:
        _open_modal(page, "task", "body")
        page.keyboard.press("Control+Space")
        assert page.evaluate(_PLAYS) == 1, "Ctrl+Space did not play"
        assert _modal_open(page, "#task-modal"), "Ctrl+Space closed the modal"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
