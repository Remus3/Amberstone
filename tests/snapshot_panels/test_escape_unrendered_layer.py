"""
tests/snapshot_panels/test_escape_unrendered_layer.py
RM-1365 (s144 uiux): an Escape is never spent on a layer nobody can see.

THE DEFECT. The one Escape dispatcher (web/js/lib/escape_layers.js) asked each
registered layer isOpen(), and every Lobby layer answers from its class alone
(web/js/main.js: "lobby-mode-menu" and "lobby-lane-popup" read
!el.classList.contains("hidden")). A view change does not close them: open the
Lobby "Change Lobby Mode" menu or the lane popup from the keyboard, then leave
the Lobby view by a hash change or the browser's Back, and the layer keeps its
open class inside the now display:none Lobby view. MEASURED in headless
Chromium under /?ui_mock=1 before the fix, at 1920x920: on Replay with zen on,
the first Escape picked that unrendered layer as the topmost open one, closed
it and consumed the press, so zen stayed on and nothing the operator could see
changed; only a second Escape exited zen.

THE FIX. The dispatcher skips an open layer whose element has no box
(getClientRects() is empty), the rendered test main.js _letterShortcutsYield
and review_player.js _menuOpen already use for the same stranded menu. The
press then goes where it would with nothing open: here, the general Escape
chain exits zen.

Positive controls: a rendered layer still takes the press over the stranded
one (the view menu opened on Replay closes and zen stays), and on the Lobby
view itself the same layer still closes on Escape with zen kept
(test_lobby_mode_menu_escape.py and test_lobby_lane_popup_keyboard.py pin the
rest of that half). The stranded layer is left with its class as it was; what
it shows when the operator returns to Lobby is a separate row.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page

VP = VIEWPORTS[0]

# layer id -> the trigger that opens it from the keyboard (Enter).
_LAYERS = {
    "lv-mode-menu": "lv-mode-trigger",
    "lv-lane-popup": "lv-lane-primary",
}

_STATE = """
(id) => {
  const m = document.getElementById(id);
  const vm = document.getElementById('view-menu');
  return {
    view: document.body.dataset.view,
    open: !!m && !m.classList.contains('hidden'),
    rects: m ? m.getClientRects().length : -1,
    viewMenuOpen: !!vm && !vm.classList.contains('hidden'),
    zen: document.body.dataset.zen || '',
  };
}
"""


def _strand(pw_browser, mock_server, layer, route):
    """Open `layer` on Lobby, then leave Lobby for Replay by `route`."""
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    start = "/?ui_mock=1#replay" if route == "back" else "/?ui_mock=1#lobby"
    page.goto(mock_server.url + start,
              wait_until="domcontentloaded", timeout=15_000)
    if route == "back":
        page.wait_for_function("() => document.body.dataset.view === 'replay'",
                               timeout=10_000)
        page.evaluate("() => { location.hash = '#lobby'; }")
    page.wait_for_function("() => document.body.dataset.view === 'lobby'",
                           timeout=10_000)
    trigger = _LAYERS[layer]
    page.wait_for_selector("#" + trigger, state="visible", timeout=10_000)
    page.focus("#" + trigger)
    page.keyboard.press("Enter")
    st = page.evaluate(_STATE, layer)
    assert st["open"] and st["rects"] > 0, f"{layer} did not open: {st}"
    if route == "back":
        page.go_back()
    else:
        page.evaluate("() => { location.hash = '#replay'; }")
    page.wait_for_function("() => document.body.dataset.view === 'replay'",
                           timeout=10_000)
    st = page.evaluate(_STATE, layer)
    # The fixture this row is about: still open by class, rendered nowhere.
    assert st["open"] and st["rects"] == 0, f"{layer} not stranded: {st}"
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    page.keyboard.press("z")
    assert page.evaluate(_STATE, layer)["zen"] == "1", "Z did not turn zen on"
    return ctx, page, errors


@pytest.mark.parametrize("route", ["hash", "back"])
@pytest.mark.parametrize("layer", sorted(_LAYERS))
def test_one_escape_exits_zen_past_a_stranded_layer(
    mock_server, pw_browser, layer, route
):
    ctx, page, errors = _strand(pw_browser, mock_server, layer, route)
    try:
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE, layer)
        assert st["zen"] == "", (
            f"the Escape was spent on the unrendered {layer}: {st}"
        )
        # Nothing rendered took the press, so nothing else moved either.
        assert not st["viewMenuOpen"], st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("layer", sorted(_LAYERS))
def test_a_rendered_layer_still_takes_the_press_over_a_stranded_one(
    mock_server, pw_browser, layer
):
    ctx, page, errors = _strand(pw_browser, mock_server, layer, "hash")
    try:
        page.focus("#view-trigger")
        page.keyboard.press("Enter")
        assert page.evaluate(_STATE, layer)["viewMenuOpen"], "view menu shut"
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE, layer)
        assert not st["viewMenuOpen"], f"the view menu stayed open: {st}"
        assert st["zen"] == "1", f"the press leaked to the zen chain: {st}"
        page.keyboard.press("Escape")
        assert page.evaluate(_STATE, layer)["zen"] == "", (
            "the second Escape was spent on the stranded layer"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("layer", sorted(_LAYERS))
def test_on_lobby_the_same_layer_still_closes_and_keeps_zen(
    mock_server, pw_browser, layer
):
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    try:
        page.goto(mock_server.url + "/?ui_mock=1#lobby",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function("() => document.body.dataset.view === 'lobby'",
                               timeout=10_000)
        trigger = _LAYERS[layer]
        page.wait_for_selector("#" + trigger, state="visible", timeout=10_000)
        page.keyboard.press("z")
        assert page.evaluate(_STATE, layer)["zen"] == "1", "Z did not turn zen on"
        page.focus("#" + trigger)
        page.keyboard.press("Enter")
        assert page.evaluate(_STATE, layer)["rects"] > 0, f"{layer} not shown"
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE, layer)
        assert not st["open"], f"{layer} stayed open on Lobby: {st}"
        assert st["zen"] == "1", f"the press leaked to the zen chain: {st}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
