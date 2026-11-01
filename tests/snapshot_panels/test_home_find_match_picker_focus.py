"""
tests/snapshot_panels/test_home_find_match_picker_focus.py
RM-1312 (s144 uiux) - keyboard focus and the Home "Find Match" queue picker.

THE DEFECT. #home-find-match-picker (web/js/main.js _homeFindMatchPickerShow /
_homeFindMatchPickerHide) is a centred popover over a scrim backdrop, opened
from the hero Find Match CTA. MEASURED here in headless Chromium under
/?ui_mock=1#home at 1920x920 and 923x1280 before the fix:
- opening it from the keyboard (Enter on the CTA) left focus on the CTA, so
  the next four Tab presses walked the SR / ARAM / ARENA mode tabs BEHIND the
  scrim before the first queue item was reached;
- Tab past the last item (TFT Double-Up) moved focus to the footer action
  tiles behind the scrim and the picker stayed open over them;
- Shift+Tab from the CTA reached the view trigger behind the scrim, picker
  still open.
It closed only on a backdrop click, an item pick or Escape.

THE FIX. Opening the picker moves focus to its first queue item (the menu
pattern for role="menu") and remembers the control that opened it. A focusout
listener on the picker closes it when focus moves to an element outside it
(Tab past the last item, Shift+Tab off the first), with no refocus: focus
stays where Tab put it. Escape closes it and returns focus to the opener, so
hiding the focused item never drops focus to <body>. Moving between items
keeps it open, a focusout with no related target (a window blur) is left to
the existing closers, and a pointer pick still dispatches its LCU command and
routes to the lobby.

THE RING. Measured in the same run: a keyboard-focused queue item matched
:focus-visible but computed the UA `auto` outline only (no rule in
web/css/panels/header.css .lq-mode-item), the same defect RM-1249 fixed on
the Lobby mode trigger. Putting focus on the first item at open makes that
ring the only cue to where the keyboard is, so the slice gives
.lq-mode-item:focus-visible the Lobby precedent `outline: 2px solid
var(--accent)` (offset 1px, inside the 4px gap between items). The class is
shared, so the Lobby mode menu items get it too. Gated with the probe and
gates of test_home_history_nav_focus_ring.py (computed colour == resolved
--accent, >= 3:1 on the nearest opaque surface, not clipped, not reaching a
neighbour), in every :root[data-theme] block. A pointer open still focuses
the first item but does NOT match :focus-visible, so no ring is painted for
a mouse user.

/api/lcu-cmd is intercepted at the page, so nothing but the local mock is
reached, and the controls below pin that leaving the picker fires NO command.
"""
import json

import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page
from tests.snapshot_panels.test_home_history_nav_focus_ring import (
    _RING_JS,
    _assert_rings,
    _themes,
)

_HOME_ITEMS = "#home-find-match-picker .lq-mode-item"
_LOBBY_ITEMS = "#lv-mode-menu .lq-mode-item"

_STATE = """
() => {
  const p = document.getElementById('home-find-match-picker');
  const b = document.getElementById('home-find-match-backdrop');
  const ae = document.activeElement;
  let focus = null;
  if (ae) {
    if (ae.id) focus = ae.id;
    else if (ae.dataset && ae.dataset.hfmQid !== undefined)
      focus = 'qid:' + ae.dataset.hfmQid;
    else focus = ae.tagName + '.' + (ae.className || '');
  }
  return {
    open: !p.classList.contains('hidden'),
    ariaHidden: p.getAttribute('aria-hidden'),
    backdrop: !!b && !b.classList.contains('hidden'),
    focus: focus,
    inPicker: !!ae && p.contains(ae),
  };
}
"""

_FIRST = "qid:0"      # Practice Tool, the first item in DOM / tab order
_LAST = "qid:1160"    # TFT Double-Up, the last item in DOM / tab order
_ITEMS = 11


def _open_home(pw_browser, mock_server, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    posts: list[dict] = []

    def _lcu(route):
        try:
            posts.append(json.loads(route.request.post_data or "{}"))
        except ValueError:
            posts.append({})
        route.fulfill(status=200, content_type="application/json", body="{}")

    page.route("**/api/lcu-cmd", _lcu)
    page.goto(mock_server.url + "/?ui_mock=1#home",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_selector("#home-hero-cta", state="visible", timeout=10_000)
    return ctx, page, errors, posts


def _keyboard_open(page):
    page.focus("#home-hero-cta")
    page.keyboard.press("Enter")
    st = page.evaluate(_STATE)
    assert st["open"] and st["backdrop"] and st["ariaHidden"] == "false", st
    return st


def _assert_closed(st):
    assert not st["open"], f"picker stayed open: {st}"
    assert st["ariaHidden"] == "true" and not st["backdrop"], st


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_keyboard_open_moves_focus_to_the_first_item(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, vp)
    try:
        st = _keyboard_open(page)
        assert st["inPicker"] and st["focus"] == _FIRST, (
            f"opening the picker left focus behind the scrim: {st}")
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_tab_past_the_last_item_closes_the_picker(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        for _ in range(_ITEMS + 4):
            st = page.evaluate(_STATE)
            if st["focus"] == _LAST:
                break
            assert st["inPicker"] and st["open"], (
                f"Tab left the picker before its last item: {st}")
            page.keyboard.press("Tab")
        else:
            raise AssertionError("Tab never reached the last picker item")
        page.keyboard.press("Tab")
        st = page.evaluate(_STATE)
        assert not st["inPicker"], f"Tab did not leave the picker: {st}"
        _assert_closed(st)
        assert posts == [], f"leaving the picker fired an LCU command: {posts}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_shift_tab_off_the_first_item_closes_the_picker(
        mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, vp)
    try:
        st = _keyboard_open(page)
        assert st["focus"] == _FIRST, st
        page.keyboard.press("Shift+Tab")
        st = page.evaluate(_STATE)
        assert not st["inPicker"], f"Shift+Tab did not leave the picker: {st}"
        _assert_closed(st)
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_returns_focus_to_the_cta(mock_server, pw_browser, vp):
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        page.keyboard.press("Tab")
        assert page.evaluate(_STATE)["focus"] == "qid:480"
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        _assert_closed(st)
        assert st["focus"] == "home-hero-cta", (
            f"Escape dropped focus instead of returning it to the CTA: {st}")
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_moving_between_items_keeps_the_picker_open(mock_server, pw_browser, vp):
    """Control: Tab through every item and Shift+Tab back to the first never
    closes the picker."""
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, vp)
    try:
        seen = [_keyboard_open(page)["focus"]]
        for _ in range(_ITEMS - 1):
            page.keyboard.press("Tab")
            st = page.evaluate(_STATE)
            assert st["open"] and st["inPicker"], (
                f"moving focus inside the picker closed it: {st}")
            seen.append(st["focus"])
        assert seen[0] == _FIRST and seen[-1] == _LAST, seen
        assert len(set(seen)) == _ITEMS, seen
        for _ in range(_ITEMS - 1):
            page.keyboard.press("Shift+Tab")
            st = page.evaluate(_STATE)
            assert st["open"] and st["inPicker"], (
                f"Shift+Tab inside the picker closed it: {st}")
        assert page.evaluate(_STATE)["focus"] == _FIRST
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_pointer_pick_still_dispatches_and_routes(mock_server, pw_browser):
    """Control: the focusout closer must not pre-empt an item click."""
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, VIEWPORTS[0])
    try:
        page.click("#home-hero-cta")
        assert page.evaluate(_STATE)["open"]
        page.click('#home-find-match-picker .lq-mode-item[data-hfm-qid="440"]')
        _assert_closed(page.evaluate(_STATE))
        for _ in range(40):
            if posts:
                break
            page.wait_for_timeout(50)
        assert {"cmd": "change_queue_type", "queue_id": 440} in posts, posts
        assert page.evaluate("() => location.hash") == "#lobby"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_backdrop_click_still_closes(mock_server, pw_browser):
    """Control: the scrim closer is unchanged."""
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, VIEWPORTS[0])
    try:
        page.click("#home-hero-cta")
        assert page.evaluate(_STATE)["open"]
        page.mouse.click(5, 5)
        _assert_closed(page.evaluate(_STATE))
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_window_blur_leaves_the_picker_open(mock_server, pw_browser):
    """Control: a focusout with no related target (window blur) is not a
    keyboard exit, so it is left to the click / Escape closers."""
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, VIEWPORTS[0])
    try:
        _keyboard_open(page)
        page.evaluate("""() => document.querySelector(
              '#home-find-match-picker .lq-mode-item')
            .dispatchEvent(new FocusEvent('focusout',
                {bubbles: true, relatedTarget: null}))""")
        st = page.evaluate(_STATE)
        assert st["open"] and st["backdrop"], st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


_NO_TRANSITIONS = "*, *::before, *::after { transition: none !important; }"


def test_picker_items_paint_the_accent_ring_in_every_theme(
        mock_server, pw_browser):
    themes = _themes()
    assert len(themes) >= 5, f"theme scan anchor: {themes}"
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, VIEWPORTS[0])
    try:
        page.add_style_tag(content=_NO_TRANSITIONS)
        _keyboard_open(page)
        accents = set()
        for t in [None] + themes:
            if t:
                page.evaluate(
                    "(t) => document.documentElement"
                    ".setAttribute('data-theme', t)", t)
            page.keyboard.press("Shift")
            rows = page.evaluate(_RING_JS, _HOME_ITEMS)
            _assert_rings(rows, _ITEMS, f"Home picker item [{t}]")
            accents.add(rows[0]["accent"])
            assert page.evaluate(_STATE)["open"], f"ring probe closed it [{t}]"
        assert len(accents) >= 3, f"theme flip inert: {accents}"
        assert posts == [], posts
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_lobby_mode_menu_items_paint_the_accent_ring(mock_server, pw_browser):
    """The rule is on the shared .lq-mode-item class, so the Lobby menu
    items carry it too."""
    ctx, page, errors = _new_page(pw_browser, mock_server, VIEWPORTS[0])
    try:
        page.route("**/api/lcu-cmd", lambda r: r.fulfill(
            status=200, content_type="application/json", body="{}"))
        page.goto(mock_server.url + "/?ui_mock=1#lobby",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_selector("#lv-mode-trigger", state="visible",
                               timeout=10_000)
        page.add_style_tag(content=_NO_TRANSITIONS)
        page.focus("#lv-mode-trigger")
        page.keyboard.press("Enter")
        page.keyboard.press("Shift")
        rows = page.evaluate(_RING_JS, _LOBBY_ITEMS)
        _assert_rings(rows, _ITEMS, "Lobby mode menu item")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_pointer_open_focuses_the_first_item_without_a_ring(
        mock_server, pw_browser):
    """A mouse user gets focus moved too (so Tab continues in the picker),
    but :focus-visible stays off, so no ring is painted on Practice Tool."""
    ctx, page, errors, posts = _open_home(pw_browser, mock_server, VIEWPORTS[0])
    try:
        page.click("#home-hero-cta")
        st = page.evaluate(_STATE)
        assert st["open"] and st["focus"] == _FIRST, st
        fv = page.evaluate("() => document.activeElement.matches(':focus-visible')")
        assert fv is False, "a pointer open painted the keyboard ring"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
