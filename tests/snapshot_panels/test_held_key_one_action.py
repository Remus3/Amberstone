"""
tests/snapshot_panels/test_held_key_one_action.py
RM-1322 (s144 uiux): a HELD key does one thing, however long it is held.

RM-1067 / RM-1070 made one Escape PRESS do one thing, but a held key is one
press that arrives as a stream of keydown events with event.repeat set, and
neither the Escape dispatcher nor the global hotkeys read that flag. Measured
in headless Chromium before the fix:
- Holding Escape on the view menu in zen closed the menu, then the first
  autorepeat exited zen. With two layers open it walked the whole stack.
- Holding Z flipped zen on every autorepeat and wrote localStorage each time.
- Holding F re-ran the fullscreen toggle on every autorepeat (4 keydowns gave
  4 requestFullscreen calls; the spy never enters fullscreen, so only the
  enter side was counted).
- Holding A clicked ANALYZE NOW on every autorepeat (4 keydowns, 4 clicks, with
  the real click handler swallowed so it could not disable the button).
- Holding Space on the Replay lane toggled play / pause on every autorepeat
  (4 keydowns, 4 calls).

Playwright's keyboard.down() sends event.repeat = true from the second call
on, so these are real autorepeat events, not synthesized ones.

The positive controls matter as much: a release and a fresh press still act,
the marker keys ] and [ still walk on autorepeat (a held seek key is the
point), and a held Space still does not scroll the page.

The first cut returned from the hotkey handler on any autorepeat, which also
skipped the preventDefault of the Z and F branches, so a held Z typed into a
focused <select> through its type-ahead. The verifier measured that, hence the
per-branch guard. RM-1323 then gave a focused select its letters outright
(tests/snapshot_panels/test_hotkey_letter_owners.py), so
test_a_held_hotkey_stays_out_of_a_focused_select now pins that a hold changes
the select and fires no shortcut. Held H is left alone on purpose: it only
re-arms the keybind toast's hide timer.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page
from tests.snapshot_panels.test_replay_space_single_action import (
    _MATCH_ROWS,
    _MEDIA_SPY,
    _open_loaded,
)

VP = VIEWPORTS[0]

_SPY = """
(() => {
  window.__fsCalls = { enter: 0, exit: 0 };
  Element.prototype.requestFullscreen = function () {
    window.__fsCalls.enter += 1;
    return Promise.resolve();
  };
})();
"""


def _open_home(pw_browser, mock_server):
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    page.add_init_script(_SPY)
    page.goto(mock_server.url + "/?ui_mock=1#home",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "() => document.body.dataset.view === 'home'", timeout=10_000
    )
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    return ctx, page, errors


def _hold(page, key, repeats=3):
    """One press plus `repeats` autorepeat keydowns, then the release."""
    page.keyboard.down(key)
    for _ in range(repeats):
        page.keyboard.down(key)
    page.keyboard.up(key)


def _zen(page):
    return page.evaluate("() => document.body.dataset.zen || ''")


def _set_zen(page, on):
    page.evaluate(
        "(on) => { document.body.dataset.zen = on ? '1' : ''; }", on
    )


def _menu_open(page):
    return page.evaluate(
        "() => !document.getElementById('view-menu').classList.contains('hidden')"
    )


def test_a_held_escape_closes_the_view_menu_and_keeps_zen(mock_server, pw_browser):
    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        _set_zen(page, True)
        page.click("#view-trigger")
        assert _menu_open(page)
        _hold(page, "Escape")
        assert not _menu_open(page)
        assert _zen(page) == "1", "the Escape autorepeat exited zen"
        # Positive control: a release and a fresh press reaches the zen exit.
        page.keyboard.press("Escape")
        assert _zen(page) == ""
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_held_escape_closes_one_layer_of_a_stack(mock_server, pw_browser):
    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        page.evaluate(
            "() => document.getElementById('task-modal').classList.remove('hidden')"
        )
        # The modal's backdrop covers the trigger, so a pointer click cannot
        # reach it; the trigger's own click handler is the real opener.
        page.evaluate("() => document.getElementById('view-trigger').click()")
        assert _menu_open(page), "setup: the view menu did not open over the modal"
        _hold(page, "Escape")
        assert not _menu_open(page), "the topmost layer did not close"
        assert page.evaluate(
            "() => !document.getElementById('task-modal').classList.contains('hidden')"
        ), "the autorepeat closed the modal under the view menu too"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_the_first_keydown_of_a_held_escape_still_exits_zen(mock_server, pw_browser):
    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        _set_zen(page, True)
        _hold(page, "Escape")
        # A control: it passes with or without the guards, and would fail on
        # a guard that swallowed the first keydown as well.
        assert _zen(page) == "", "the first keydown of a hold must still act"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_held_z_toggles_zen_once(mock_server, pw_browser):
    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        _set_zen(page, False)
        # An odd count of keydowns lands where one flip would, which hides a
        # flip-per-repeat bug, so the first hold is two keydowns.
        _hold(page, "z", repeats=1)
        assert _zen(page) == "1", "one press and one repeat flipped zen twice"
        _hold(page, "z", repeats=1)
        assert _zen(page) == "", "a fresh hold did not flip zen back once"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_held_f_requests_fullscreen_once(mock_server, pw_browser):
    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        _hold(page, "f")
        assert page.evaluate("() => window.__fsCalls.enter") == 1
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_held_a_clicks_analyze_once(mock_server, pw_browser):
    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        # Counted at the click and swallowed, so the real handler cannot
        # disable the button mid-hold and hide a per-repeat click.
        page.evaluate(
            """() => {
              window.__analyze = 0;
              document.getElementById('analyze-now').addEventListener(
                'click',
                (e) => { window.__analyze += 1; e.stopImmediatePropagation(); },
                true);
            }"""
        )
        _hold(page, "a")
        assert page.evaluate("() => window.__analyze") == 1
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_held_shift_r_reloads_once(mock_server, pw_browser):
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    page.add_init_script(
        "sessionStorage.setItem('held-loads',"
        " String(Number(sessionStorage.getItem('held-loads') || 0) + 1));"
    )
    loads = "() => Number(sessionStorage.getItem('held-loads'))"
    ready = "() => document.body.dataset.view === 'home'"
    try:
        page.goto(mock_server.url + "/?ui_mock=1#home",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(ready, timeout=10_000)
        assert page.evaluate(loads) == 1
        page.keyboard.down("Shift")
        with page.expect_navigation(wait_until="domcontentloaded", timeout=15_000):
            page.keyboard.down("R")
        page.wait_for_function(ready, timeout=10_000)
        assert page.evaluate(loads) == 2, "the first keydown did not reload"
        # The key is still down, so these reach the reloaded page as repeats.
        page.keyboard.down("R")
        page.keyboard.down("R")
        page.wait_for_timeout(700)
        page.wait_for_function(ready, timeout=10_000)
        page.keyboard.up("R")
        page.keyboard.up("Shift")
        assert page.evaluate(loads) == 2, "a Shift+R autorepeat reloaded again"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_held_letter_still_types_in_an_input(mock_server, pw_browser):
    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        page.evaluate(
            """() => {
              const i = document.createElement('input');
              i.id = 'held-probe';
              document.body.appendChild(i);
              i.focus();
            }"""
        )
        _hold(page, "z", repeats=3)
        assert page.input_value("#held-probe") == "zzzz"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_held_ctrl_k_stays_on_the_prompt_input(mock_server, pw_browser):
    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        page.evaluate(
            """() => {
              // #input-text has no box in the views this fixture reaches, so
              // focus() on it is a no-op; lift it out to give it one.
              document.body.appendChild(document.getElementById('input-text'));
              window.__ctrlK = { total: 0, prevented: 0 };
              window.addEventListener('keydown', (e) => {
                if (e.key.toLowerCase() !== 'k' || !e.ctrlKey) return;
                window.__ctrlK.total += 1;
                if (e.defaultPrevented) window.__ctrlK.prevented += 1;
              });
            }"""
        )
        page.keyboard.down("Control")
        _hold(page, "k", repeats=2)
        page.keyboard.up("Control")
        got = page.evaluate("() => window.__ctrlK")
        # Every repeat stays prevented, or the browser's own Ctrl+K takes
        # the held key away from the page.
        assert got == {"total": 3, "prevented": 3}, got
        focused = page.evaluate("() => document.activeElement.id")
        assert focused == "input-text", f"Ctrl+K left focus on {focused!r}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("key", ["z", "f", "a"])
def test_a_held_hotkey_stays_out_of_a_focused_select(mock_server, pw_browser, key):
    """RM-1323 gave a focused select its letters, so a hold now reaches the
    type-ahead and fires no shortcut."""
    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        # The one option past the first starts with the held key.
        page.evaluate(
            """(k) => {
              window.__analyze = 0;
              document.getElementById('analyze-now').addEventListener(
                'click',
                (e) => { window.__analyze += 1; e.stopImmediatePropagation(); },
                true);
              const s = document.createElement('select');
              s.id = 'held-select';
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
        zen_before = _zen(page)
        _hold(page, key)
        assert page.input_value("#held-select") == key + "ed", (
            f"a held {key!r} did not reach the focused select's type-ahead"
        )
        assert page.evaluate("() => window.__analyze") == 0
        assert page.evaluate("() => window.__fsCalls.enter") == 0
        assert _zen(page) == zen_before
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def _calls(page):
    return page.evaluate("() => window.__rpCalls.play + window.__rpCalls.pause")


def _player_ready(pw_browser, mock_server):
    ctx, page, errors = _open_loaded(pw_browser, mock_server, VP)
    page.evaluate("() => document.getElementById('replay-video-section').focus()")
    return ctx, page, errors


def test_a_held_space_toggles_play_once_and_does_not_scroll(mock_server, pw_browser):
    ctx, page, errors = _player_ready(pw_browser, mock_server)
    try:
        page.evaluate(
            """() => {
              window.__space = { total: 0, prevented: 0 };
              window.addEventListener('keydown', (e) => {
                if (e.key !== ' ') return;
                window.__space.total += 1;
                if (e.defaultPrevented) window.__space.prevented += 1;
              });
            }"""
        )
        _hold(page, " ")
        assert _calls(page) == 1, "a held Space toggled play on an autorepeat"
        got = page.evaluate("() => window.__space")
        assert got == {"total": 4, "prevented": 4}, (
            f"an autorepeat Space went to the page and would scroll it: {got}"
        )
        # Positive control: a fresh press toggles again.
        page.keyboard.press(" ")
        assert _calls(page) == 2
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def _expose_player_state(route):
    """Serve review_player.js with its private state on window: ui_mock never
    fetches a sidecar, so nothing else can give the player markers to walk."""
    resp = route.fetch()
    body = resp.text()
    assert "const _RP = {" in body, "review_player.js state moved; fix this seam"
    route.fulfill(
        response=resp,
        body=body.replace("const _RP = {", "const _RP = window.__RP = {"),
    )


def test_a_held_marker_key_still_walks(mock_server, pw_browser):
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    page.add_init_script(_MEDIA_SPY)
    page.route("**/panels/review_player.js*", _expose_player_state)
    try:
        page.goto(mock_server.url + "/?ui_mock=1#replay",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_selector(_MATCH_ROWS, timeout=10_000)
        page.click(_MATCH_ROWS)
        page.wait_for_function(
            "() => document.querySelectorAll('.replay-events-row').length > 1",
            timeout=10_000,
        )
        page.evaluate(
            """() => {
              const sec = document.getElementById('replay-video-section');
              sec.hidden = false;
              sec.focus();
              window.__RP.markers = [{ t: 10 }, { t: 20 }, { t: 30 }];
              document.getElementById('replay-video').currentTime = 0;
            }"""
        )
        now = "() => document.getElementById('replay-video').currentTime"
        _hold(page, "]", repeats=2)
        assert page.evaluate(now) == 30, "a held ] did not walk all three markers"
        _hold(page, "[", repeats=1)
        assert page.evaluate(now) == 10, "a held [ did not walk back two markers"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
