"""
tests/snapshot_panels/test_replay_keys_behind_menu.py
RM-1324 (s144 uiux): the Replay recording player's own keys stay out of an
open menu's way.

web/js/panels/review_player.js has its own document keydown handler and did not
consult the rule RM-1323 gave the global letter shortcuts in web/js/main.js.
With the view menu open over a showing recording, ], [, d and D seeked the video
behind the menu, whether focus was on a menu row, on the trigger (a pointer open
leaves it there) or on the body (a click on the menu's divider leaves it there),
and with focus on the body a plain Space toggled play.

What stays as it was, each pinned below:
- Space on a focused trigger or row is that control's: it closes the menu or
  picks the row, and does not play.
- Ctrl / Alt + Space still toggles play: it is the documented "play from
  anywhere" chord, and the menu handlers ignore a modified key, so nobody can
  mean it for the menu.
- Escape belongs to the dispatcher (web/js/lib/escape_layers.js): it closes the
  menu, and the player sees a consumed key.
- With no menu rendered the keys act, including over a Lobby menu left open by a
  view change, which is not displayed on Replay.

A plain Space with focus on the body stays prevented while it stands down, as it
is with no menu open. A right-click on a bare part of the Replay pane fires no
click and moves focus to nothing, so the menu stays open with focus on the body,
and an unprevented Space then scrolled .replay-main-pane behind it (pinned below at
1920x920). A right-click on a control takes focus, which closes the menu. On the
divider-click route an unprevented Space moved nothing at any viewport measured
(800x600 up to 2560x1440), so that route's test pins the preventDefault rather
than a scroll.

ui_mock never fetches a sidecar, so the player's private state is exposed through
the same response rewrite test_held_key_one_action.py uses, and play / pause are
counted by its media spy instead of decoding a real video.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page
from tests.snapshot_panels.test_held_key_one_action import _expose_player_state
from tests.snapshot_panels.test_replay_space_single_action import (
    _MATCH_ROWS,
    _MEDIA_SPY,
)
from tests.snapshot_panels.test_space_behind_a_menu_any_view import _strip_main_hold

VP = VIEWPORTS[0]

_NOW = "() => document.getElementById('replay-video').currentTime"
_PLAYS = "() => window.__rpCalls.play + window.__rpCalls.pause"
_START = 20

# From t=20 every key has somewhere to go, so "did not move" means it stood down.
_SEEKS = {"]": 30, "[": 10, "d": 25, "D": 15}

_HOLD = 'isSpace && !isSpaceActivated(ev.target) ? { type: "hold-space" } : null'
_PANE_TOP = "() => document.querySelector('.replay-main-pane').scrollTop"


def _remove_the_hold(route):
    """Serve the model without hold-space, to prove a route really scrolls."""
    resp = route.fetch()
    body = resp.text()
    assert _HOLD in body, "hotkeyAction's hold moved; fix this seam"
    route.fulfill(response=resp, body=body.replace(_HOLD, "null", 1))


def _open_player(pw_browser, mock_server, hold_removed=False):
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    page.add_init_script(_MEDIA_SPY)
    page.route("**/panels/review_player.js*", _expose_player_state)
    if hold_removed:
        page.route("**/panels/review_player_model.js*", _remove_the_hold)
        # RM-1366: main.js now holds the same press on every view, so the
        # control takes out both holds.
        page.route("**/js/main.js*", _strip_main_hold)
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


def _menu_open(page):
    return page.evaluate(
        "() => !document.getElementById('view-menu').classList.contains('hidden')"
    )


def _focus(page):
    return page.evaluate(
        """() => {
          const a = document.activeElement;
          if (!a || a === document.body) return 'body';
          if (a.id === 'view-trigger') return 'trigger';
          return a.closest('#view-menu') ? 'row' : a.id || a.tagName;
        }"""
    )


def _open_menu(page, focus):
    """Open the view menu with focus where this route really leaves it."""
    if focus == "row":
        page.focus("#view-trigger")
        page.keyboard.press("Enter")
    else:
        page.click("#view-trigger")
        if focus == "body":
            page.click("#view-menu .view-menu-divider")
    assert _menu_open(page), "the view menu did not open"
    assert _focus(page) == focus, f"focus is on {_focus(page)}, wanted {focus}"


def _close_and_blur(page):
    page.keyboard.press("Escape")
    assert not _menu_open(page), "Escape did not close the view menu"
    page.evaluate("() => document.activeElement && document.activeElement.blur()")


@pytest.mark.parametrize("focus", ["trigger", "row", "body"])
@pytest.mark.parametrize("key", list(_SEEKS))
def test_a_seek_key_stands_down_behind_an_open_menu(
    mock_server, pw_browser, key, focus
):
    ctx, page, errors = _open_player(pw_browser, mock_server)
    try:
        _open_menu(page, focus)
        page.keyboard.press(key)
        assert page.evaluate(_NOW) == _START, (
            f"{key!r} seeked the video behind the menu, focus on {focus}"
        )
        assert _menu_open(page), f"{key!r} closed the menu"
        # Positive control: the same key seeks once the menu has closed.
        _close_and_blur(page)
        page.keyboard.press(key)
        assert page.evaluate(_NOW) == _SEEKS[key], f"{key!r} is dead with no menu"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_space_on_the_body_behind_an_open_menu_plays_nothing_and_stays_prevented(
    mock_server, pw_browser
):
    ctx, page, errors = _open_player(pw_browser, mock_server)
    try:
        _open_menu(page, "body")
        page.keyboard.press(" ")
        assert page.evaluate(_PLAYS) == 0, "Space toggled play behind the menu"
        got = page.evaluate("() => window.__space")
        assert got == {"total": 1, "prevented": 1}, (
            f"Space reached the browser's default action behind the menu: {got}"
        )
        assert _menu_open(page), "Space on the body closed the menu"
        # Positive control: the same press plays once the menu has closed.
        _close_and_blur(page)
        page.keyboard.press(" ")
        assert page.evaluate(_PLAYS) == 1, "Space is dead with no menu"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def _right_click_the_pane_with_the_menu_open(page):
    """A right-click fires no click, so the menu stays open, focus on the body."""
    page.click("#view-trigger")
    box = page.evaluate(
        """() => {
          const r = document.querySelector('.replay-main-pane')
            .getBoundingClientRect();
          return { x: r.x + r.width - 30, y: r.y + 12 };
        }"""
    )
    page.mouse.click(box["x"], box["y"], button="right")
    assert _menu_open(page), "the right-click closed the menu"
    assert _focus(page) == "body", f"focus is on {_focus(page)}"
    assert page.evaluate(_PANE_TOP) == 0


def test_space_after_a_right_click_does_not_scroll_the_pane_behind_the_menu(
    mock_server, pw_browser
):
    ctx, page, errors = _open_player(pw_browser, mock_server)
    try:
        _right_click_the_pane_with_the_menu_open(page)
        page.keyboard.press(" ")
        page.wait_for_timeout(800)
        assert page.evaluate(_PANE_TOP) == 0, "Space scrolled the pane behind the menu"
        assert page.evaluate(_PLAYS) == 0, "Space toggled play behind the menu"
        assert _menu_open(page), "Space closed the menu"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_that_route_really_scrolls_without_the_hold(mock_server, pw_browser):
    # The control for the test above: a pane that cannot scroll would pass it.
    ctx, page, errors = _open_player(pw_browser, mock_server, hold_removed=True)
    try:
        _right_click_the_pane_with_the_menu_open(page)
        page.keyboard.press(" ")
        page.wait_for_function(
            "() => document.querySelector('.replay-main-pane').scrollTop > 0",
            timeout=5_000,
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_space_on_the_trigger_closes_the_menu_and_does_not_play(
    mock_server, pw_browser
):
    ctx, page, errors = _open_player(pw_browser, mock_server)
    try:
        _open_menu(page, "trigger")
        page.keyboard.press(" ")
        assert not _menu_open(page), "Space on the trigger did not close the menu"
        assert page.evaluate(_PLAYS) == 0, "Space on the trigger also played"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_space_on_a_row_picks_it_and_does_not_play(mock_server, pw_browser):
    ctx, page, errors = _open_player(pw_browser, mock_server)
    try:
        _open_menu(page, "row")
        # Another view's row: closing alone cannot pass for a pick.
        page.focus('#view-menu .view-menu-item[data-view="home"]')
        page.keyboard.down(" ")
        # Read between keydown and the keyup that picks: Replay is still showing,
        # so the player's own check really did run on this press.
        assert page.evaluate("() => document.body.dataset.view") == "replay"
        assert page.evaluate(_PLAYS) == 0, "Space on a row also played"
        page.keyboard.up(" ")
        page.wait_for_function(
            "() => document.body.dataset.view === 'home'", timeout=10_000
        )
        assert not _menu_open(page), "Space on a row did not close the menu"
        assert page.evaluate(_PLAYS) == 0, "Space on a row also played"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("chord", ["Control+Space", "Alt+Space"])
@pytest.mark.parametrize("focus", ["trigger", "row", "body"])
def test_the_play_from_anywhere_chord_still_plays(
    mock_server, pw_browser, focus, chord
):
    ctx, page, errors = _open_player(pw_browser, mock_server)
    try:
        _open_menu(page, focus)
        page.keyboard.press(chord)
        assert page.evaluate(_PLAYS) == 1, f"{chord} did not play, focus on {focus}"
        assert _menu_open(page), f"{chord} closed the menu"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("focus", ["trigger", "row", "body"])
def test_escape_closes_the_menu_and_leaves_the_player_alone(
    mock_server, pw_browser, focus
):
    ctx, page, errors = _open_player(pw_browser, mock_server)
    try:
        _open_menu(page, focus)
        page.keyboard.press("Escape")
        assert not _menu_open(page), "Escape did not close the menu"
        assert page.evaluate(_NOW) == _START
        assert page.evaluate(_PLAYS) == 0
        # The player's release-focus parks focus on the lane section. A press the
        # dispatcher consumed must not reach it.
        assert page.evaluate("() => document.activeElement.id") != (
            "replay-video-section"
        ), "the player also acted on the Escape that closed the menu"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_lobby_menu_left_open_off_screen_does_not_kill_the_keys(
    mock_server, pw_browser
):
    # Rendered is what counts: the Lobby view is display: none here, so its open
    # menu is not over anything. A check on the class alone would go dead.
    ctx, page, errors = _open_player(pw_browser, mock_server)
    try:
        rects = page.evaluate(
            """() => {
              const m = document.getElementById('lv-mode-menu');
              m.classList.remove('hidden');
              // Off the match row the load click left it on: Space would be its.
              document.activeElement.blur();
              return m.getClientRects().length;
            }"""
        )
        assert rects == 0, "the Lobby menu is rendered on Replay; fixture is wrong"
        page.keyboard.press("]")
        assert page.evaluate(_NOW) == 30, "a hidden Lobby menu killed the seek keys"
        page.keyboard.press(" ")
        assert page.evaluate(_PLAYS) == 1, "a hidden Lobby menu killed Space"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
