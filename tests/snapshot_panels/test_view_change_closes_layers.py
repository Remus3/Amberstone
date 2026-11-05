"""
tests/snapshot_panels/test_view_change_closes_layers.py
RM-1368 (s144 uiux): a view change closes every transient layer it leaves
with no box.

THE DEFECT. applyView (web/js/main.js) only flips body[data-view]; it closed
nothing. MEASURED in headless Chromium under /?ui_mock=1 at 1920x920 before
the fix, opening each layer and then leaving its view by a hash change:
- Home Find Match picker (#home-find-match-picker, inside #home-overlay): the
  picker kept its open state with 0 rects on Replay, but its scrim
  (#home-find-match-backdrop, created on <body>, position:fixed, z 9100)
  stayed painted over the whole Replay view: elementFromPoint at the centre
  read the backdrop, so the first click on Replay only closed a picker nobody
  could see. Escape could not clear it either: since RM-1365 an unrendered
  layer takes no press. Back on Home the picker was still open. (Both s144
  u106 verifiers were half right: the picker has no box, its scrim does.)
- Lobby "Change Lobby Mode" menu (#lv-mode-menu) and lane popup
  (#lv-lane-popup): each kept its open class and its trigger kept
  aria-expanded "true" on Replay, and both were still open on return to
  Lobby, a stale dropdown over the party rows.

THE RULE. In the same task as the view flip, applyView dismisses every
Escape-registered layer that is open and has an element with no box
(escape_layers.js dismissStrandedLayers). A dismissal never moves focus (the
layers' no-refocus closer), so focus handling stays with RM-1367. A layer
still rendered after the change (the header view menu, the task modal) is
left alone.

The state is read inside a hashchange listener added after main.js wired its
own, so it runs in the same dispatch right after the view applied.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page

VP = VIEWPORTS[0]

_LAYERS = {
    # name: (view, opener selector, layer id, trigger id or None)
    "picker": ("home", "#home-hero-cta", "home-find-match-picker", None),
    "mode-menu": ("lobby", "#lv-mode-trigger", "lv-mode-menu", "lv-mode-trigger"),
    "lane-popup": ("lobby", "#lv-lane-primary", "lv-lane-popup", "lv-lane-primary"),
}

# Leave for Replay and read the layer in the same hashchange dispatch, after
# main.js's own listener applied the view.
_LEAVE_AND_READ = """
([route, layerId, trigId]) => new Promise((done) => {
  const read = () => {
    window.removeEventListener('hashchange', read);
    const L = document.getElementById(layerId);
    const bd = document.getElementById('home-find-match-backdrop');
    const hit = document.elementFromPoint(960, 460);
    const a = document.activeElement;
    done({
      view: document.body.dataset.view,
      open: !L.classList.contains('hidden'),
      ariaHidden: L.getAttribute('aria-hidden'),
      expanded: trigId ? document.getElementById(trigId).getAttribute('aria-expanded') : null,
      scrim: !!bd && bd.getClientRects().length > 0,
      hit: hit ? (hit.id || hit.className) : '',
      focusBoxless: !!a && a !== document.body && a.getClientRects().length === 0,
    });
  };
  window.addEventListener('hashchange', read);
  if (route === 'back') history.back(); else location.hash = '#replay';
})
"""


def _goto(page, mock_server, view, route):
    start = "/?ui_mock=1#replay" if route == "back" else f"/?ui_mock=1#{view}"
    page.goto(mock_server.url + start,
              wait_until="domcontentloaded", timeout=15_000)
    if route == "back":
        page.wait_for_function("() => document.body.dataset.view === 'replay'",
                               timeout=10_000)
        page.evaluate(f"() => {{ location.hash = '#{view}'; }}")
    page.wait_for_function(f"() => document.body.dataset.view === '{view}'",
                           timeout=10_000)


def _open(page, opener, layer_id):
    page.wait_for_selector(opener, state="visible", timeout=10_000)
    page.focus(opener)
    page.keyboard.press("Enter")
    assert page.evaluate(
        f"() => !document.getElementById('{layer_id}').classList.contains('hidden')"
    ), f"{layer_id} did not open"


@pytest.mark.parametrize("route", ["hash", "back"])
@pytest.mark.parametrize("name", list(_LAYERS))
def test_leaving_a_view_closes_its_open_layer(mock_server, pw_browser, name, route):
    view, opener, layer_id, trig_id = _LAYERS[name]
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    try:
        _goto(page, mock_server, view, route)
        _open(page, opener, layer_id)
        st = page.evaluate(_LEAVE_AND_READ, [route, layer_id, trig_id])
        assert st["view"] == "replay", st
        assert not st["open"], f"{layer_id} stayed open on Replay: {st}"
        assert st["ariaHidden"] == "true", st
        if trig_id:
            assert st["expanded"] == "false", st
        assert not st["scrim"], f"the Find Match scrim stayed over Replay: {st}"
        assert st["hit"] != "home-find-match-backdrop", st
        assert not st["focusBoxless"], f"focus left on an element with no box: {st}"
        # Coming back finds the layer closed, not a stale dropdown.
        page.evaluate(f"() => {{ location.hash = '#{view}'; }}")
        page.wait_for_function(f"() => document.body.dataset.view === '{view}'",
                               timeout=10_000)
        assert page.evaluate(
            f"() => document.getElementById('{layer_id}').classList.contains('hidden')"
        ), f"{layer_id} was still open on return to {view}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_click_on_replay_after_leaving_home_reaches_the_page(mock_server, pw_browser):
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    try:
        _goto(page, mock_server, "home", "hash")
        _open(page, "#home-hero-cta", "home-find-match-picker")
        page.evaluate("() => { location.hash = '#replay'; }")
        page.wait_for_function("() => document.body.dataset.view === 'replay'",
                               timeout=10_000)
        # The header view trigger is rendered on every view; the scrim used
        # to sit over it (z 9100) and take the click.
        page.click("#view-trigger", timeout=5_000)
        assert page.evaluate(
            "() => !document.getElementById('view-menu').classList.contains('hidden')"
        ), "the click on Replay did not reach the view trigger"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_view_menu_pick_still_routes_and_keeps_focus_on_the_trigger(
    mock_server, pw_browser
):
    # Positive control: the header view menu is rendered on every view, so
    # the dismissal leaves it to its own closer, and a keyboard pick still
    # lands focus on the rendered #view-trigger.
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    try:
        _goto(page, mock_server, "lobby", "hash")
        page.focus("#view-trigger")
        page.keyboard.press("Enter")
        row = '.view-menu-item[data-view="replay"]'
        page.wait_for_selector(row, state="visible", timeout=10_000)
        page.focus(row)
        page.keyboard.press("Enter")
        page.wait_for_function("() => document.body.dataset.view === 'replay'",
                               timeout=10_000)
        assert page.evaluate("() => document.activeElement.id") == "view-trigger"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
