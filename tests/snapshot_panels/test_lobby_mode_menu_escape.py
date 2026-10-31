"""
tests/snapshot_panels/test_lobby_mode_menu_escape.py
RM-1251 (s144 uiux) - Escape closes the open Lobby "Change Lobby Mode"
menu and hands focus back to its trigger.

THE DEFECT. The Lobby mode menu (#lv-mode-menu, opened by #lv-mode-trigger,
wired in web/js/main.js _lobbyViewWireOnce) closed only on a trigger click,
an item click or a document click. It never registered with the one Escape
dispatcher (web/js/lib/escape_layers.js, RM-1070) the view menu, the task
modal and the Home Find Match picker use. MEASURED in headless Chromium
under /?ui_mock=1#lobby before the fix, at 1920x920 and 923x1280: a keyboard
user who opened the menu (Enter on the trigger) and pressed Escape left it
open with aria-expanded="true"; with focus on a menu item the press did
nothing either, so the only way out was to Tab past all 11 items or click.
With zen on, the same Escape fell through to the general chain and exited
zen while the menu stayed open.

THE FIX. The menu registers as a layer ("lobby-mode-menu"); the dispatcher
closes it and consumes the press, so zen stays. When focus was inside the
menu, close() returns it to the trigger (a hidden menu item would otherwise
drop focus to <body>); when it was on the trigger it stays there.

Positive controls: a second Escape still exits zen, and a press another
listener already consumed leaves the menu open.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page

_STATE = """
() => {
  const m = document.getElementById('lv-mode-menu');
  const t = document.getElementById('lv-mode-trigger');
  const ae = document.activeElement;
  return {
    open: !!m && !m.classList.contains('hidden'),
    shown: !!m && getComputedStyle(m).display !== 'none',
    expanded: t.getAttribute('aria-expanded'),
    ariaHidden: m.getAttribute('aria-hidden'),
    zen: document.body.dataset.zen || '',
    focus: ae ? (ae.id || ae.dataset.qid && ('qid:' + ae.dataset.qid)
                 || ae.tagName) : null,
  };
}
"""


def _open_lobby(pw_browser, mock_server, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    page.goto(mock_server.url + "/?ui_mock=1#lobby",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function("() => document.body.dataset.view === 'lobby'",
                           timeout=10_000)
    page.wait_for_selector("#lv-mode-trigger", state="visible", timeout=10_000)
    return ctx, page, errors


def _keyboard_open(page):
    """Open the menu the way the keyboard does: focus the trigger, Enter."""
    page.focus("#lv-mode-trigger")
    page.keyboard.press("Enter")
    st = page.evaluate(_STATE)
    assert st["open"] and st["shown"] and st["expanded"] == "true", st
    assert st["focus"] == "lv-mode-trigger", st
    return st


def _zen_on(page):
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    page.keyboard.press("z")
    assert page.evaluate(_STATE)["zen"] == "1", "Z did not turn zen on"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_on_the_trigger_closes_the_menu(mock_server, pw_browser, vp):
    ctx, page, errors = _open_lobby(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert not st["open"] and not st["shown"], (
            f"Escape left the Lobby mode menu open: {st}"
        )
        assert st["expanded"] == "false" and st["ariaHidden"] == "true", st
        assert st["focus"] == "lv-mode-trigger", st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_inside_the_menu_returns_focus_to_the_trigger(
        mock_server, pw_browser, vp):
    ctx, page, errors = _open_lobby(pw_browser, mock_server, vp)
    try:
        _keyboard_open(page)
        page.keyboard.press("Tab")
        st = page.evaluate(_STATE)
        assert st["focus"] == "qid:0", (
            f"Tab from the trigger did not reach the first menu item: {st}"
        )
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert not st["open"] and st["expanded"] == "false", st
        assert st["focus"] == "lv-mode-trigger", (
            f"closing the menu from an item dropped focus: {st}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_closes_the_menu_and_keeps_zen(mock_server, pw_browser, vp):
    ctx, page, errors = _open_lobby(pw_browser, mock_server, vp)
    try:
        _zen_on(page)
        _keyboard_open(page)
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert not st["open"], st
        assert st["zen"] == "1", f"closing the mode menu also exited zen: {st}"
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert st["zen"] == "", f"a second Escape no longer exits zen: {st}"
        assert not st["open"], st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_press_consumed_upstream_leaves_the_menu_open(mock_server, pw_browser):
    ctx, page, errors = _open_lobby(pw_browser, mock_server, VIEWPORTS[0])
    try:
        _keyboard_open(page)
        page.evaluate(
            """() => window.addEventListener('keydown', (e) => {
                 if (e.key === 'Escape') e.preventDefault();
               }, true)"""
        )
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert st["open"] and st["expanded"] == "true", (
            f"the menu closed on an Escape another listener had consumed: {st}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_trigger_and_document_click_still_close_the_menu(mock_server, pw_browser):
    """The pointer paths the fix must not disturb: a second trigger click
    and a click outside the menu each close it."""
    ctx, page, errors = _open_lobby(pw_browser, mock_server, VIEWPORTS[0])
    try:
        page.click("#lv-mode-trigger")
        assert page.evaluate(_STATE)["open"]
        page.click("#lv-mode-trigger")
        st = page.evaluate(_STATE)
        assert not st["open"] and st["expanded"] == "false", st
        page.click("#lv-mode-trigger")
        assert page.evaluate(_STATE)["open"]
        page.evaluate("() => document.body.click()")
        st = page.evaluate(_STATE)
        assert not st["open"] and st["expanded"] == "false", st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
