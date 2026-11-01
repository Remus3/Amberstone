"""
tests/snapshot_panels/test_hotkey_letter_owners.py
RM-1323 (s144 uiux): a global letter hotkey never fires from a control that
is already using the letter keys, or from behind an open menu.

The document keydown handler in web/js/main.js skipped its single-key shortcuts
only for INPUT and TEXTAREA. Measured in headless Chromium before the fix:
- On a focused <select>, A clicked ANALYZE NOW, F asked for fullscreen, Z flipped
  zen and Shift+R wiped the saved preferences and reloaded. A, F and Z also
  called preventDefault, so the select's own type-ahead never ran: on the real
  Settings theme picker, A could not reach Arcane, it started the analyzer.
- With a menu open, the same keys acted on the page behind it. That holds with
  focus on a menu row (the view menu, the Home Find Match picker, the Lobby lane
  popup), with focus still on the trigger of an open menu (the Lobby mode menu
  on open, the view menu after a pointer open), and with focus on the body after
  a click on a menu's non-interactive part, which leaves the menu open.
- A contenteditable host had the same hole; none ships today, the rule covers
  it so that the first one does not reopen this.

Positive controls: with focus on the body or on an ordinary button, on a trigger
whose menu has closed, and in another view with a Lobby menu left open behind a
view change (it is not displayed there), every shortcut still acts.

Out of scope: web/js/panels/review_player.js has its own Replay keys (Space, d,
D, ], [) and does not consult this rule, so they still act behind an open menu.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page

VP = VIEWPORTS[0]

_SPY = """
(() => {
  window.__fsCalls = 0;
  Element.prototype.requestFullscreen = function () {
    window.__fsCalls += 1;
    return Promise.resolve();
  };
})();
"""

# Counted at the click and swallowed, so the real handler cannot run the
# analyzer. Shift+R is read through the preference it wipes, which is removed
# synchronously, so the read cannot race the reload it also starts.
_ARM = """
() => {
  window.__analyze = 0;
  const btn = document.getElementById('analyze-now');
  btn.addEventListener(
    'click',
    (e) => { window.__analyze += 1; e.stopImmediatePropagation(); },
    true);
  localStorage.setItem('rc-header-lock', 'probe');
  return !btn.disabled;
}
"""

_FIRED = """
() => ({
  analyze: window.__analyze,
  fullscreen: window.__fsCalls,
  zen: document.body.dataset.zen || '',
  toast: !!document.querySelector('#keybinds-toast.show'),
  prefs: localStorage.getItem('rc-header-lock'),
})
"""

# Every letter shortcut in the handler; "?" shares H's branch.
_KEYS = ["a", "f", "z", "h", "?", "Shift+R"]
_MENUS = {
    "view": ("home", "#view-trigger", "#view-menu"),
    "find_match": ("home", "#home-hero-cta", "#home-find-match-picker"),
    "lobby_lane": ("lobby", "#lv-lane-primary", "#lv-lane-popup"),
    "lobby_mode": ("lobby", "#lv-mode-trigger", "#lv-mode-menu"),
}
# A click here leaves the menu open with focus on the body. The Lobby mode menu
# has no entry: a click on its non-interactive part closes it.
_MENU_GAPS = {
    "view": ".view-menu-divider",
    "find_match": ".lq-mode-section",
    "lobby_lane": "#lv-lane-popup-label",
}


def _open(pw_browser, mock_server, view):
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    page.add_init_script(_SPY)
    page.goto(mock_server.url + f"/?ui_mock=1#{view}",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        f"() => document.body.dataset.view === '{view}'", timeout=10_000
    )
    if view == "lobby":
        # The lane triggers act only once the mock self row has been rendered.
        page.wait_for_function(
            "() => document.getElementById('lv-lane-primary').dataset.pref"
            " === 'MIDDLE'", timeout=10_000)
    # A disabled ANALYZE NOW would make every "A did nothing" below vacuous.
    assert page.evaluate(_ARM) is True, "analyze-now is disabled in this view"
    return ctx, page, errors


def _baseline(page):
    return page.evaluate(_FIRED)


def _assert_nothing_fired(page, before, key):
    after = page.evaluate(_FIRED)
    assert after == before, f"{key!r} fired a global shortcut: {before} -> {after}"


def _assert_fired(page, before, key):
    """The one observable this key owns moved, and no other did."""
    after = page.evaluate(_FIRED)
    expected = dict(before)
    if key == "a":
        expected["analyze"] = before["analyze"] + 1
    elif key == "f":
        expected["fullscreen"] = before["fullscreen"] + 1
    elif key == "z":
        expected["zen"] = "" if before["zen"] == "1" else "1"
    elif key in ("h", "?"):
        expected["toast"] = True
    else:
        expected["prefs"] = None
    assert after == expected, f"{key!r}: {before} -> {after}, wanted {expected}"


def _press_and_assert_fired(page, key):
    """Shift+R reloads, which resets the page's own counters; only the wiped
    preference outlives it, so it is read after the navigation has finished."""
    before = _baseline(page)
    if key == "Shift+R":
        with page.expect_navigation(timeout=15_000):
            page.keyboard.press(key)
        assert page.evaluate("() => localStorage.getItem('rc-header-lock')") is None
        return
    page.keyboard.press(key)
    _assert_fired(page, before, key)


def _menu_is_open(page, menu):
    return page.evaluate(
        "(sel) => !document.querySelector(sel).classList.contains('hidden')", menu
    )


@pytest.mark.parametrize("key", ["a", "f", "z"])
def test_a_letter_on_a_select_reaches_its_type_ahead_and_no_hotkey(
    mock_server, pw_browser, key
):
    ctx, page, errors = _open(pw_browser, mock_server, "home")
    try:
        page.evaluate(
            """(k) => {
              const s = document.createElement('select');
              s.id = 'probe-select';
              for (const v of ['x', k + 'ed']) {
                const o = document.createElement('option');
                o.value = o.textContent = v;
                s.appendChild(o);
              }
              document.body.appendChild(s);
              s.focus();
            }""",
            key,
        )
        before = _baseline(page)
        page.keyboard.press(key)
        _assert_nothing_fired(page, before, key)
        assert page.input_value("#probe-select") == key + "ed", (
            f"{key!r} did not reach the select's type-ahead"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_on_the_settings_theme_picker_picks_arcane_not_the_analyzer(
    mock_server, pw_browser
):
    """The real control: Arcane is the option A has always been meant to reach."""
    ctx, page, errors = _open(pw_browser, mock_server, "settings")
    try:
        page.wait_for_selector("#set-theme", state="visible", timeout=10_000)
        page.select_option("#set-theme", "hextech")
        page.focus("#set-theme")
        before = _baseline(page)
        page.keyboard.press("a")
        _assert_nothing_fired(page, before, "a")
        assert page.input_value("#set-theme") == "arcane"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("key", ["h", "Shift+R"])
def test_the_other_shortcuts_stay_out_of_a_focused_select(
    mock_server, pw_browser, key
):
    ctx, page, errors = _open(pw_browser, mock_server, "settings")
    try:
        page.wait_for_selector("#set-theme", state="visible", timeout=10_000)
        page.focus("#set-theme")
        before = _baseline(page)
        page.keyboard.press(key)
        _assert_nothing_fired(page, before, key)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("menu", sorted(_MENUS))
@pytest.mark.parametrize("key", _KEYS)
def test_a_shortcut_does_not_fire_behind_an_open_menu(
    mock_server, pw_browser, menu, key
):
    view, trigger, panel = _MENUS[menu]
    ctx, page, errors = _open(pw_browser, mock_server, view)
    try:
        page.wait_for_selector(trigger, state="visible", timeout=10_000)
        page.focus(trigger)
        page.keyboard.press("Enter")
        assert _menu_is_open(page, panel), f"{menu} did not open"
        before = _baseline(page)
        page.keyboard.press(key)
        _assert_nothing_fired(page, before, key)
        assert _menu_is_open(page, panel), f"{key!r} closed {menu}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("key", _KEYS)
def test_a_shortcut_does_not_fire_from_the_trigger_of_a_pointer_opened_menu(
    mock_server, pw_browser, key
):
    """A pointer open leaves focus on the trigger, outside the menu itself."""
    ctx, page, errors = _open(pw_browser, mock_server, "home")
    try:
        page.click("#view-trigger")
        assert _menu_is_open(page, "#view-menu")
        assert page.evaluate(
            "() => document.activeElement.id === 'view-trigger'"
        ), "the premise moved: a pointer open no longer leaves focus on the trigger"
        before = _baseline(page)
        page.keyboard.press(key)
        _assert_nothing_fired(page, before, key)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("menu", sorted(_MENU_GAPS))
@pytest.mark.parametrize("key", _KEYS)
def test_a_shortcut_does_not_fire_after_a_click_on_a_menus_label(
    mock_server, pw_browser, menu, key
):
    """The click drops focus to the body with the menu still open."""
    view, trigger, panel = _MENUS[menu]
    ctx, page, errors = _open(pw_browser, mock_server, view)
    try:
        page.wait_for_selector(trigger, state="visible", timeout=10_000)
        page.focus(trigger)
        page.keyboard.press("Enter")
        assert _menu_is_open(page, panel), f"{menu} did not open"
        page.click(f"{panel} {_MENU_GAPS[menu]}")
        assert _menu_is_open(page, panel), f"the click closed {menu}"
        assert page.evaluate(
            "() => document.activeElement === document.body"
        ), "the premise moved: the click no longer drops focus to the body"
        before = _baseline(page)
        page.keyboard.press(key)
        _assert_nothing_fired(page, before, key)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("key", _KEYS)
@pytest.mark.parametrize("menu", ["lobby_lane", "lobby_mode"])
def test_a_lobby_menu_left_open_by_a_view_change_does_not_kill_the_shortcuts(
    mock_server, pw_browser, menu, key
):
    view, trigger, panel = _MENUS[menu]
    ctx, page, errors = _open(pw_browser, mock_server, view)
    try:
        page.wait_for_selector(trigger, state="visible", timeout=10_000)
        page.focus(trigger)
        page.keyboard.press("Enter")
        assert _menu_is_open(page, panel), f"{menu} did not open"
        page.evaluate("() => { location.hash = '#home'; }")
        page.wait_for_function(
            "() => document.body.dataset.view === 'home'", timeout=10_000
        )
        assert page.evaluate(
            "(sel) => document.querySelector(sel).getClientRects().length", panel
        ) == 0, f"{menu} is still displayed in the next view"
        assert _menu_is_open(page, panel), (
            f"the premise moved: a view change now closes {menu}"
        )
        page.evaluate("() => document.activeElement && document.activeElement.blur()")
        _press_and_assert_fired(page, key)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


_TYPED = [("a", "a"), ("f", "f"), ("z", "z"), ("h", "h"), ("?", "?"), ("Shift+R", "R")]


@pytest.mark.parametrize("key,char", _TYPED)
@pytest.mark.parametrize("host", ["contenteditable", "textarea", "input"])
def test_a_letter_in_a_text_control_is_text(mock_server, pw_browser, host, key, char):
    ctx, page, errors = _open(pw_browser, mock_server, "home")
    try:
        page.evaluate(
            """(host) => {
              const d = document.createElement(host === 'contenteditable' ? 'div' : host);
              d.id = 'probe-text';
              if (host === 'contenteditable') d.contentEditable = 'true';
              document.body.appendChild(d);
              d.focus();
            }""",
            host,
        )
        before = _baseline(page)
        page.keyboard.press(key)
        _assert_nothing_fired(page, before, key)
        typed = page.evaluate(
            "() => { const d = document.getElementById('probe-text');"
            " return d.value !== undefined ? d.value : d.textContent; }"
        )
        assert typed == char, f"{key!r} in a {host} gave {typed!r}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("key", _KEYS)
def test_every_shortcut_still_acts_from_the_page_body(mock_server, pw_browser, key):
    ctx, page, errors = _open(pw_browser, mock_server, "home")
    try:
        page.evaluate("() => document.activeElement && document.activeElement.blur()")
        _press_and_assert_fired(page, key)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("key", _KEYS)
def test_every_shortcut_still_acts_from_an_ordinary_button(
    mock_server, pw_browser, key
):
    ctx, page, errors = _open(pw_browser, mock_server, "home")
    try:
        page.wait_for_selector("#home-hero-cta", state="visible", timeout=10_000)
        page.focus("#home-hero-cta")
        _press_and_assert_fired(page, key)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("menu", sorted(_MENUS))
@pytest.mark.parametrize("key", _KEYS)
def test_every_shortcut_acts_again_once_the_menu_has_closed(
    mock_server, pw_browser, menu, key
):
    """Escape hands focus back to the trigger, which is an ordinary button now."""
    view, trigger, panel = _MENUS[menu]
    ctx, page, errors = _open(pw_browser, mock_server, view)
    try:
        page.wait_for_selector(trigger, state="visible", timeout=10_000)
        page.focus(trigger)
        page.keyboard.press("Enter")
        assert _menu_is_open(page, panel), f"{menu} did not open"
        page.keyboard.press("Escape")
        assert not _menu_is_open(page, panel), f"{menu} did not close"
        assert page.evaluate(
            "(sel) => document.activeElement === document.querySelector(sel)", trigger
        ), f"{menu}: Escape did not return focus to the trigger"
        _press_and_assert_fired(page, key)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
