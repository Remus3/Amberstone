"""
tests/snapshot_panels/test_view_menu_keyboard.py
RM-1321 (s144 uiux) - the header view menu (#view-menu, opened by
#view-trigger) from the keyboard. It is the only route to every dashboard
view, and web/js/main.js _viewWireOnce reparents it to the END of <body>, so
in tab order it sits after the whole page, not under its trigger.

THE DEFECTS. MEASURED in headless Chromium under /?ui_mock=1#history before
the fix:

1. Enter on #view-trigger opened the menu and left focus on the trigger. The
   next Tab went to the next header control with the menu left open.
2. Escape from a focused row closed the menu and left document.activeElement
   on the now display:none row.
3. Picking a row with Enter dropped focus to <body>.
4. Tab off the last row (Auto) dropped focus to <body> with the menu open.
5. Focus leaving the trigger + menu pair left the menu open over the page.
6. The role="menu" rows answered no arrow key, Home or End.

THE FIX follows the Lobby lane popup (RM-1320) and the Lobby mode menu
(RM-1249..1253), with two deliberate differences:
- A POINTER open leaves focus on the trigger, the contract
  test_escape_one_action.py pins; only a keyboard open (a click with detail 0,
  or ArrowDown) moves into the menu.
- A POINTER pick does not refocus the trigger. This header control stays on
  screen over the Replay player, and a parked focus would take the next Space.
A held Enter is suppressed on the trigger and the rows, because the focus moves
would otherwise carry the autorepeat from an open into a pick into a reopen.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page
from tests.snapshot_panels.test_home_history_nav_focus_ring import _themes
from tests.snapshot_panels.test_replay_space_single_action import (
    _STATE as _REPLAY_STATE,
)
from tests.snapshot_panels.test_replay_space_single_action import _open_loaded

_VIEW = "history"
_ROWS = "#view-menu .view-menu-item"
_N_ROWS = 12
_NO_TRANSITIONS = "*, *::before, *::after { transition: none !important; }"

_STATE = """
() => {
  const m = document.getElementById('view-menu');
  const t = document.getElementById('view-trigger');
  const ae = document.activeElement;
  return {
    open: !m.classList.contains('hidden'),
    ariaHidden: m.getAttribute('aria-hidden'),
    expanded: t.getAttribute('aria-expanded'),
    view: document.body.dataset.view || '',
    focus: !ae ? null : (ae.id || (m.contains(ae) ? 'row:' + ae.dataset.view
                                                  : ae.tagName)),
    ring: !!ae && ae.matches(':focus-visible'),
    zen: document.body.dataset.zen || '',
  };
}
"""


_FOCUS_IS = "(sel) => document.activeElement === document.querySelector(sel)"
_MANUAL = "() => [localStorage.getItem('rc-view-manual'), location.hash]"


def _open_view(pw_browser, mock_server, vp=VIEWPORTS[0], view=_VIEW):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    page.goto(mock_server.url + "/?ui_mock=1#" + view,
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        f"() => document.body.dataset.view === '{view}'", timeout=10_000)
    page.add_style_tag(content=_NO_TRANSITIONS)
    # The current row is marked by the view router; every assertion below
    # that names the current row rests on this anchor.
    page.wait_for_function(
        f"() => !!document.querySelector('{_ROWS}.active[data-view=\"{view}\"]')",
        timeout=10_000)
    return ctx, page, errors


def _state(page):
    return page.evaluate(_STATE)


def _assert_closed(st):
    assert not st["open"], f"view menu stayed open: {st}"
    assert st["ariaHidden"] == "true" and st["expanded"] == "false", st


def _assert_open(st):
    assert st["open"], f"view menu is not open: {st}"
    assert st["ariaHidden"] == "false" and st["expanded"] == "true", st


def _keyboard_open(page, key="Enter"):
    page.focus("#view-trigger")
    page.keyboard.press(key)
    st = _state(page)
    _assert_open(st)
    return st


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
@pytest.mark.parametrize("key", ["Enter", "Space", "ArrowDown"])
def test_keyboard_open_moves_focus_to_the_current_view(
        mock_server, pw_browser, vp, key):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp)
    try:
        st = _keyboard_open(page, key)
        assert st["focus"] == "row:history", (
            f"{key} opened the view menu and left focus outside it: {st}")
        assert st["ring"], f"the current row drew no ring: {st}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_keyboard_open_with_no_current_row_lands_on_the_first(
        mock_server, pw_browser):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        page.evaluate(
            "(s) => document.querySelectorAll(s)"
            ".forEach((r) => r.classList.remove('active'))", _ROWS)
        st = _keyboard_open(page)
        assert st["focus"] == "row:home", st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_pointer_open_leaves_focus_on_the_trigger(mock_server, pw_browser):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        page.click("#view-trigger")
        st = _state(page)
        _assert_open(st)
        assert st["focus"] == "view-trigger", st
        assert not st["ring"], f"a pointer open painted a focus ring: {st}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("key", ["Tab", "ArrowDown"])
def test_key_after_a_pointer_open_enters_the_menu(mock_server, pw_browser, key):
    # Tab from the trigger would otherwise walk the whole page first: the
    # menu is appended at the end of <body>.
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        page.click("#view-trigger")
        page.keyboard.press(key)
        st = _state(page)
        _assert_open(st)
        assert st["focus"] == "row:history", st
        assert st["ring"], st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_shift_tab_off_the_open_trigger_closes_the_menu(mock_server, pw_browser):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        page.click("#view-trigger")
        page.keyboard.press("Shift+Tab")
        st = _state(page)
        _assert_closed(st)
        assert st["focus"] != "view-trigger" and not st["focus"].startswith("row:"), st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_returns_focus_to_the_trigger(mock_server, pw_browser, vp):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        page.keyboard.press("Escape")
        st = _state(page)
        _assert_closed(st)
        assert st["focus"] == "view-trigger", (
            f"Escape dropped focus out of the closed view menu: {st}")
        assert st["ring"], st
        # Positive control: the trigger is live, so Enter opens it again on
        # the same row.
        page.keyboard.press("Enter")
        st = _state(page)
        _assert_open(st)
        assert st["focus"] == "row:history", st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
@pytest.mark.parametrize("key", ["Enter", "Space"])
def test_keyboard_pick_navigates_and_returns_focus_to_the_trigger(
        mock_server, pw_browser, vp, key):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        page.keyboard.press("ArrowUp")
        assert _state(page)["focus"] == "row:session"
        page.keyboard.press(key)
        page.wait_for_function(
            "() => document.body.dataset.view === 'session'", timeout=10_000)
        st = _state(page)
        _assert_closed(st)
        assert st["focus"] == "view-trigger", (
            f"a keyboard pick dropped focus out of the menu: {st}")
        assert st["ring"], st
        assert page.evaluate("() => location.hash") == "#session"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_keyboard_pick_of_auto_returns_focus_to_the_trigger(mock_server, pw_browser):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        _keyboard_open(page)
        page.keyboard.press("End")
        assert _state(page)["focus"] == "row:auto"
        page.keyboard.press("Enter")
        st = _state(page)
        _assert_closed(st)
        assert st["focus"] == "view-trigger", st
        assert page.evaluate("() => location.hash") == "", "Auto kept its hash"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("opener", ["pointer", "keyboard"])
def test_pointer_pick_does_not_park_focus_on_the_trigger(
        mock_server, pw_browser, opener):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        if opener == "pointer":
            page.click("#view-trigger")
        else:
            _keyboard_open(page)
        page.click(_ROWS + '[data-view="session"]')
        page.wait_for_function(
            "() => document.body.dataset.view === 'session'", timeout=10_000)
        st = _state(page)
        _assert_closed(st)
        assert st["focus"] != "view-trigger", (
            f"a pointer pick moved focus to the trigger: {st}")
        assert not st["ring"], f"a pointer pick painted a focus ring: {st}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_space_after_a_pointer_pick_of_replay_still_plays(mock_server, pw_browser):
    # Found by the RM-1321 verifier against the first cut, which refocused
    # the trigger after every pick: the next Space reopened the menu on the
    # Replay row instead of toggling the recording.
    ctx, page, errors = _open_loaded(pw_browser, mock_server, VIEWPORTS[0])
    try:
        for view in ("home", "replay"):
            page.click("#view-trigger")
            page.click(_ROWS + f'[data-view="{view}"]')
            page.wait_for_function(
                f"() => document.body.dataset.view === '{view}'", timeout=10_000)
        page.wait_for_selector("#replay-video-section", state="visible",
                               timeout=10_000)
        before = page.evaluate(_REPLAY_STATE)
        page.keyboard.press(" ")
        after = page.evaluate(_REPLAY_STATE)
        assert after["play"] == before["play"] + 1, f"{before} -> {after}"
        _assert_closed(_state(page))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_pointer_pick_leaves_no_focus_on_the_hidden_row(mock_server, pw_browser):
    # The nightly red on the test above. A pointer pick hid the row and left it
    # document.activeElement until the browser's focus fixup at the next frame.
    # A Space landing in that window went to the display:none row: no play, and
    # its keyup clicked the row again, which re-picked the view and parked focus
    # on the trigger. Read in the click's own task, so no frame can intervene
    # and this does not depend on the timing that made the red intermittent.
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        page.click("#view-trigger")
        got = page.evaluate(
            """(sel) => {
              const row = document.querySelector(sel);
              row.focus();
              const held = document.activeElement === row;
              row.dispatchEvent(new MouseEvent('click', {bubbles: true, detail: 1}));
              return {
                held,
                onRow: document.activeElement === row,
                rects: row.getClientRects().length,
              };
            }""",
            _ROWS + '[data-view="session"]')
        assert got["held"], f"positive control, the row never took focus: {got}"
        assert got["rects"] == 0, f"the pick did not hide the row: {got}"
        assert not got["onRow"], f"focus stayed on the hidden row: {got}"
        _assert_closed(_state(page))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_held_enter_on_the_trigger_opens_and_picks_nothing(mock_server, pw_browser):
    # A real autorepeat is a keydown with repeat=true, which is what a second
    # keyboard.down of a held key sends.
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        manual = page.evaluate(_MANUAL)
        page.focus("#view-trigger")
        page.keyboard.down("Enter")
        page.keyboard.down("Enter")
        page.keyboard.down("Enter")
        page.keyboard.up("Enter")
        st = _state(page)
        _assert_open(st)
        assert st["focus"] == "row:history", st
        assert page.evaluate(_MANUAL) == manual, "a held Enter pinned a manual view"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_held_enter_on_a_row_picks_once_and_does_not_reopen(mock_server, pw_browser):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        _keyboard_open(page)
        page.keyboard.press("ArrowUp")
        assert _state(page)["focus"] == "row:session"
        # Exactly one repeat: unguarded it would reopen the menu from the
        # refocused trigger, and a second repeat would pick and close it again,
        # which an odd keydown count cannot tell from one pick.
        page.keyboard.down("Enter")
        page.keyboard.down("Enter")
        page.keyboard.up("Enter")
        page.wait_for_function(
            "() => document.body.dataset.view === 'session'", timeout=10_000)
        st = _state(page)
        _assert_closed(st)
        assert st["focus"] == "view-trigger", st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_held_space_arriving_on_the_trigger_does_not_open(mock_server, pw_browser):
    # Space activates on keyup, so a repeat that lands on the trigger after
    # focus moved there would open the menu when the key is released.
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        page.focus("#history-scope-tabs .view-tab")
        page.keyboard.down(" ")
        page.focus("#view-trigger")
        page.keyboard.down(" ")
        page.keyboard.up(" ")
        st = _state(page)
        _assert_closed(st)
        assert st["focus"] == "view-trigger", st
        # Positive control: a fresh Space still opens it.
        page.keyboard.press(" ")
        _assert_open(_state(page))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("mod", ["Control", "Alt", "Meta"])
def test_a_modified_key_is_left_alone(mock_server, pw_browser, mod):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        page.focus("#view-trigger")
        page.keyboard.press(f"{mod}+ArrowDown")
        _assert_closed(_state(page))
        _keyboard_open(page)
        page.keyboard.press(f"{mod}+End")
        st = _state(page)
        _assert_open(st)
        assert st["focus"] == "row:history", f"{mod}+End moved the row focus: {st}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_arrows_home_end_walk_the_rows_and_wrap(mock_server, pw_browser):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        _keyboard_open(page)
        order = page.evaluate(
            "(s) => Array.from(document.querySelectorAll(s))"
            ".map((r) => r.dataset.view)", _ROWS)
        assert len(order) == _N_ROWS, order
        assert order[0] == "home" and order[-1] == "auto", order
        i = order.index("history")
        # Forward across the divider, and round the end of the list.
        for step in range(_N_ROWS + 1):
            page.keyboard.press("ArrowDown")
            want = order[(i + step + 1) % _N_ROWS]
            assert _state(page)["focus"] == "row:" + want, f"step {step}"
        page.keyboard.press("Home")
        assert _state(page)["focus"] == "row:home"
        page.keyboard.press("ArrowUp")
        assert _state(page)["focus"] == "row:auto", "ArrowUp did not wrap"
        page.keyboard.press("Home")
        page.keyboard.press("End")
        st = _state(page)
        assert st["focus"] == "row:auto", st
        _assert_open(st)
        assert page.evaluate("() => window.scrollY") == 0, "a key scrolled the page"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_tab_walks_the_rows_and_shift_tab_off_the_first_reaches_the_trigger(
        mock_server, pw_browser):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        _keyboard_open(page)
        page.keyboard.press("Tab")
        st = _state(page)
        _assert_open(st)
        assert st["focus"] == "row:replay", st
        page.keyboard.press("Home")
        page.keyboard.press("Shift+Tab")
        st = _state(page)
        _assert_open(st)
        assert st["focus"] == "view-trigger", (
            f"Shift+Tab off the first row skipped the trigger: {st}")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_tab_off_the_last_row_lands_after_the_trigger(mock_server, pw_browser):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        # Positive control: where Tab goes from the trigger with the menu
        # closed is where Tab off the last row must land, so the menu reads
        # as if it sat directly under its trigger.
        page.focus("#view-trigger")
        page.keyboard.press("Tab")
        want = _state(page)["focus"]
        assert want not in (None, "BODY", "view-trigger"), want
        assert not want.startswith("row:"), want

        _keyboard_open(page)
        page.keyboard.press("End")
        page.keyboard.press("Tab")
        st = _state(page)
        _assert_closed(st)
        assert st["focus"] == want, (
            f"Tab off the last row landed on {st['focus']!r}, want {want!r}")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_focus_leaving_closes_and_does_not_pull_it_back(mock_server, pw_browser):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        elsewhere = "#history-scope-tabs .view-tab"
        _keyboard_open(page)
        page.focus(elsewhere)
        st = _state(page)
        _assert_closed(st)
        assert page.evaluate(_FOCUS_IS, elsewhere), st
        # The same from the trigger half of the pair.
        page.click("#view-trigger")
        _assert_open(_state(page))
        page.focus(elsewhere)
        st = _state(page)
        _assert_closed(st)
        assert page.evaluate(_FOCUS_IS, elsewhere), st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_window_blur_alone_leaves_the_menu_open(mock_server, pw_browser):
    # A focusout with no related target (window blur, alt-tab) is not the
    # user leaving the menu.
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        _keyboard_open(page)
        page.evaluate("() => document.activeElement.blur()")
        _assert_open(_state(page))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_outside_click_closes_without_refocusing_the_trigger(
        mock_server, pw_browser):
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        _keyboard_open(page)
        page.mouse.click(1000, 600)
        st = _state(page)
        _assert_closed(st)
        assert st["focus"] != "view-trigger", (
            f"an outside click pulled focus back to the trigger: {st}")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_escape_from_a_row_still_keeps_zen(mock_server, pw_browser):
    # RM-1067 is pinned on a pointer open; the keyboard open now has focus in
    # the menu, and the dispatcher must still consume the press.
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        page.evaluate("() => document.activeElement && document.activeElement.blur()")
        page.keyboard.press("z")
        assert _state(page)["zen"] == "1"
        _keyboard_open(page)
        page.keyboard.press("Escape")
        st = _state(page)
        _assert_closed(st)
        assert st["zen"] == "1", f"closing the view menu also exited zen: {st}"
        assert st["focus"] == "view-trigger", st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_trigger_ring_clears_3_to_1_in_every_theme(mock_server, pw_browser):
    # Every close now lands on the trigger, so its ring carries the whole
    # keyboard state. Measured on the resolved ring colour against the
    # trigger's own opaque backdrop, never on a token read by grep.
    themes = _themes()
    assert len(themes) >= 5, f"theme scan anchor: {themes}"
    ctx, page, errors = _open_view(pw_browser, mock_server)
    try:
        page.keyboard.press("Shift")
        seen = set()
        for t in [None] + themes:
            if t:
                page.evaluate(
                    "(t) => document.documentElement"
                    ".setAttribute('data-theme', t)", t)
            got = page.evaluate(_TRIGGER_RING)
            seen.add(tuple(got["ring"]))
            assert got["fv"], f"[{t}] trigger not :focus-visible: {got}"
            assert got["style"] == "solid" and got["width"] >= 2, f"[{t}] {got}"
            assert got["contrast"] >= 3.0, f"[{t}] trigger ring {got}"
        assert len(seen) >= 3, f"theme flip inert: {seen}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


_TRIGGER_RING = r"""
() => {
  const cv = document.createElement('canvas');
  cv.width = 1; cv.height = 1;
  const c2 = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (col) => {
    c2.clearRect(0, 0, 1, 1);
    c2.fillStyle = '#000';
    c2.fillStyle = col;
    c2.fillRect(0, 0, 1, 1);
    const d = c2.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3]];
  };
  const lum = (p) => {
    const ch = p.slice(0, 3).map((v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
  };
  const t = document.getElementById('view-trigger');
  t.blur();
  t.focus();
  const cs = getComputedStyle(t);
  const ring = rgba(cs.outlineColor);
  // The outline paints OUTSIDE the trigger, so its backdrop is the first
  // opaque ancestor, not the trigger's own fill.
  let bg = null;
  for (let a = t.parentElement; a; a = a.parentElement) {
    const p = rgba(getComputedStyle(a).backgroundColor);
    if (p[3] === 255) { bg = p; break; }
  }
  if (!bg) bg = rgba(getComputedStyle(document.documentElement)
    .getPropertyValue('--canvas').trim());
  const la = lum(ring), lb = lum(bg);
  return {
    fv: t.matches(':focus-visible'),
    style: cs.outlineStyle,
    width: parseFloat(cs.outlineWidth),
    ring, bg,
    contrast: (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05),
  };
}
"""
