"""
tests/snapshot_panels/test_view_change_stranded_focus.py
RM-1367 (s144 uiux): after a view change, keyboard focus never stays on an
element with no box.

THE DEFECT. Every top-level view is a .view-section that is display:none unless
the matching body[data-view] rule shows it, and applyView (web/js/main.js) only
flips that attribute. Focus the Lobby "Change Lobby Mode" trigger (#lv-mode-trigger) from
the keyboard, or open its menu with Enter, then leave Lobby by a hash change or
the browser's Back: document.activeElement stays on #lv-mode-trigger inside the
now display:none Lobby view. MEASURED in headless Chromium under /?ui_mock=1
at 1920x920 before the fix: Chromium's own focus fixup drops it to <body> only
at the next rendering frame (a setTimeout 0 after the hash change still read
lv-mode-trigger with 0 rects; one requestAnimationFrame later it read BODY).
Inside that window the hidden control still owns the keyboard: an Enter
pressed right after the hash change clicked #lv-mode-trigger (1 click) and
opened the Lobby mode menu on the Replay view, where nobody can see it. The
same window is what the RM-1321 view-menu close already guards against.

THE RULE. applyView drops focus that the view change left on an element with no
box (getClientRects() empty, the rendered test escape_layers.js, main.js
_letterShortcutsYield and review_player.js _menuOpen already use), in the same
task as the change. It only blurs; it never pulls focus anywhere, so focus on a
rendered control (the header view trigger after a keyboard pick from the view
menu, or the Lobby trigger the Home Find Match pick moves focus to) is left
alone.

The state check reads focus inside a hashchange listener added after main.js
wired its own, so it runs in the same dispatch right after the view applied:
deterministic, no frame race. The Enter test pins the consequence but rides
that race: on the unfixed code it failed in 2 of 3 runs (a frame can slip in
before the key event), so it can false-pass there, never false-fail on the fix,
where the blur is synchronous. Positive control: a keyboard pick from the header
view menu still lands focus on #view-trigger, rendered across the change.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page

VP = VIEWPORTS[0]

# Leave Lobby for Replay and read focus in the same hashchange dispatch,
# after main.js's own listener applied the view.
_LEAVE_AND_READ = """
(route) => new Promise((done) => {
  const read = () => {
    window.removeEventListener('hashchange', read);
    const a = document.activeElement;
    done({
      view: document.body.dataset.view,
      id: a ? (a.id || a.tagName) : '',
      body: !a || a === document.body,
      rects: a ? a.getClientRects().length : 0,
    });
  };
  window.addEventListener('hashchange', read);
  if (route === 'back') history.back(); else location.hash = '#replay';
})
"""

_COUNT_CLICKS = """
() => {
  window.__lvTriggerClicks = 0;
  document.getElementById('lv-mode-trigger').addEventListener('click', () => {
    window.__lvTriggerClicks += 1;
  });
}
"""

_MENU_OPEN = """
() => !document.getElementById('lv-mode-menu').classList.contains('hidden')
"""


def _goto_lobby(page, mock_server, route):
    start = "/?ui_mock=1#replay" if route == "back" else "/?ui_mock=1#lobby"
    page.goto(mock_server.url + start,
              wait_until="domcontentloaded", timeout=15_000)
    if route == "back":
        page.wait_for_function("() => document.body.dataset.view === 'replay'",
                               timeout=10_000)
        page.evaluate("() => { location.hash = '#lobby'; }")
    page.wait_for_function("() => document.body.dataset.view === 'lobby'",
                           timeout=10_000)
    page.wait_for_selector("#lv-mode-trigger", state="visible", timeout=10_000)


def _focus_trigger(page, menu):
    page.focus("#lv-mode-trigger")
    if menu == "open":
        page.keyboard.press("Enter")
        assert page.evaluate(_MENU_OPEN), "the Lobby mode menu did not open"
    assert page.evaluate("() => document.activeElement.id") == "lv-mode-trigger"


@pytest.mark.parametrize("route", ["hash", "back"])
@pytest.mark.parametrize("menu", ["closed", "open"])
def test_leaving_lobby_never_strands_focus_on_its_hidden_trigger(
    mock_server, pw_browser, route, menu
):
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    try:
        _goto_lobby(page, mock_server, route)
        _focus_trigger(page, menu)
        st = page.evaluate(_LEAVE_AND_READ, route)
        assert st["view"] == "replay", st
        assert st["body"] or st["rects"] > 0, (
            f"focus stranded on an element with no box: {st}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_an_enter_right_after_leaving_lobby_never_clicks_the_hidden_trigger(
    mock_server, pw_browser
):
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    try:
        _goto_lobby(page, mock_server, "hash")
        _focus_trigger(page, "closed")
        page.evaluate(_COUNT_CLICKS)
        # Not awaited past the change: the hashchange task runs before the
        # key event, and the Enter lands before the next rendering frame,
        # inside the window Chromium's own focus fixup leaves open.
        page.evaluate("() => { location.hash = '#replay'; }")
        page.keyboard.press("Enter")
        assert page.evaluate("() => document.body.dataset.view") == "replay"
        clicks = page.evaluate("() => window.__lvTriggerClicks")
        assert clicks == 0, f"Enter clicked the hidden Lobby trigger {clicks}x"
        assert not page.evaluate(_MENU_OPEN), (
            "the Lobby mode menu opened on the Replay view"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_keyboard_view_menu_pick_still_keeps_focus_on_the_trigger(
    mock_server, pw_browser
):
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    try:
        _goto_lobby(page, mock_server, "hash")
        page.focus("#view-trigger")
        page.keyboard.press("Enter")
        row = '.view-menu-item[data-view="replay"]'
        page.wait_for_selector(row, state="visible", timeout=10_000)
        page.focus(row)
        page.keyboard.press("Enter")
        page.wait_for_function("() => document.body.dataset.view === 'replay'",
                               timeout=10_000)
        a = page.evaluate(
            "() => { const a = document.activeElement;"
            " return [a.id, a.getClientRects().length]; }"
        )
        assert a[0] == "view-trigger" and a[1] > 0, (
            f"the view change pulled focus off the rendered trigger: {a}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
