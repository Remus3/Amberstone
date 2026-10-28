"""
tests/snapshot_panels/test_replay_space_single_action.py
RM-1062 (s144 uiux), measured in headless Chromium before the fix: every
recording-player hotkey (Space, [ ], d / D, Esc) was DEAD on the real
dashboard. web/js/panels/review_player.js _visible() required
`!view.hidden` on #view-replay, but the view router (web/js/main.js) shows a
view through body[data-view] CSS and never clears the section's `hidden`
attribute, so the test was always false and _onKeydown returned at once
(the positive control below failed: 0 play calls on a plain Space). The fix
reads rendered visibility (getClientRects) instead.

Making the keys live exposes the double action the RM-1018 verifier
reported: with the Replay recording lane showing
(#replay-video-section visible, i.e. a recording sidecar exists), one Space
press on a focused Replay row did TWO things. The row's own keydown handler
acted (a .replay-events-row seeks the scrubber, web/js/panels/replay_events.js
wireReplayEventsOnce; the loaded .replay-match-row re-loads its match,
web/js/panels/dev.js _replayViewRefresh) and called preventDefault, and then
the document-level player hotkey (web/js/panels/review_player.js _onKeydown)
ignored ev.defaultPrevented and toggled video play as well, because
hotkeyAction (web/js/panels/review_player_model.js) maps a plain Space to
toggle-play for any non-typing target.

The fix: a key a closer handler already consumed (defaultPrevented) is not a
player hotkey, and the row handlers leave Ctrl / Alt / Meta + key alone, so
modifier+Space still toggles play from a focused row (the documented
"play from anywhere" key) without also acting on the row. The loaded match
row also carries aria-current="true" (one row at a time), so a screen reader
can tell which match the view shows. And a plain Space on a control it
activates (checkbox, radio, button, link, role=button, ...; marker buttons
excepted) stays that control's (review_player_model.js isSpaceActivated):
the verifier measured the live keys eating Space on the Replay filter
checkboxes and the header buttons.

The lane stays hidden under ?ui_mock=1 (loadReviewPlayer returns before the
/api/recordings fetch), so the test reveals the section itself, the way a
servable sidecar would, and counts HTMLMediaElement play / pause calls through
an init-script wrapper instead of decoding a real video.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page

_MATCH_ROWS = "#replay-match-list .replay-match-row"
_EVENT_ROWS = "#replay-events-list .replay-events-row"

# Count play() / pause() on any media element; play resolves at once so no
# decoder or source is needed.
_MEDIA_SPY = """
(() => {
  window.__rpCalls = { play: 0, pause: 0 };
  const P = HTMLMediaElement.prototype;
  P.play = function () { window.__rpCalls.play += 1; return Promise.resolve(); };
  P.pause = function () { window.__rpCalls.pause += 1; };
})();
"""

_STATE = """
() => {
  const act = document.querySelector('.replay-match-row.active');
  const cur = [...document.querySelectorAll('.replay-match-row')]
    .filter(r => r.getAttribute('aria-current') === 'true')
    .map(r => r.dataset.matchId);
  return {
    play: window.__rpCalls.play,
    pause: window.__rpCalls.pause,
    slider: document.getElementById('replay-slider').value,
    activeId: act ? act.dataset.matchId : null,
    current: cur,
    laneVisible: !document.getElementById('replay-video-section').hidden,
  };
}
"""


def _open_loaded(pw_browser, mock_server, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    page.add_init_script(_MEDIA_SPY)
    page.goto(mock_server.url + "/?ui_mock=1#replay",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_selector(_MATCH_ROWS, timeout=10_000)
    page.click(_MATCH_ROWS)
    page.wait_for_function(
        "() => document.querySelectorAll('.replay-events-row').length > 1"
        " && !document.getElementById('replay-slider').disabled",
        timeout=10_000,
    )
    # A servable sidecar would reveal the lane (review_player.js
    # loadReviewPlayer); ui_mock never fetches one, so reveal it here.
    page.evaluate(
        "() => { document.getElementById('replay-video-section').hidden = false; }"
    )
    return ctx, page, errors


def _focus_event_row_away_from_slider(page):
    """Focus a timeline row whose seek moves the slider off its current
    value, and return that row's index (so a seek is observable)."""
    idx = page.evaluate(
        f"""() => {{
          const rows = [...document.querySelectorAll('{_EVENT_ROWS}')];
          const clocks = rows.map(r => Number(r.dataset.clock));
          let best = clocks.length - 1;
          for (let i = clocks.length - 1; i >= 0; i--) {{
            if (clocks[i] > 60) {{ best = i; break; }}
          }}
          rows[best].focus();
          return best;
        }}"""
    )
    assert idx >= 0
    return idx


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_space_on_a_timeline_row_seeks_and_does_not_toggle_play(
    mock_server, pw_browser, vp
):
    ctx, page, errors = _open_loaded(pw_browser, mock_server, vp)
    try:
        page.evaluate("() => { document.getElementById('replay-slider').value = '0'; }")
        _focus_event_row_away_from_slider(page)
        before = page.evaluate(_STATE)
        assert before["laneVisible"] and before["slider"] == "0", before
        page.keyboard.press(" ")
        after = page.evaluate(_STATE)
        assert after["slider"] != "0", f"Space did not seek the row: {after}"
        assert after["play"] == before["play"], (
            f"Space on a timeline row also toggled video play: {before} -> {after}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_space_on_the_loaded_match_row_does_not_toggle_play(
    mock_server, pw_browser, vp
):
    ctx, page, errors = _open_loaded(pw_browser, mock_server, vp)
    try:
        page.focus(".replay-match-row.active")
        before = page.evaluate(_STATE)
        assert before["laneVisible"] and before["activeId"], before
        page.keyboard.press(" ")
        after = page.evaluate(_STATE)
        assert after["activeId"] == before["activeId"], after
        assert after["play"] == before["play"], (
            f"Space on the loaded match row also toggled video play: {before} -> {after}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_space_off_the_rows_still_toggles_play(mock_server, pw_browser, vp):
    # Positive control: the player still owns a plain Space when no row
    # (or other control) consumed it.
    ctx, page, errors = _open_loaded(pw_browser, mock_server, vp)
    try:
        page.evaluate("() => document.activeElement && document.activeElement.blur()")
        before = page.evaluate(_STATE)
        page.keyboard.press(" ")
        after = page.evaluate(_STATE)
        assert after["play"] == before["play"] + 1, f"{before} -> {after}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_a_key_consumed_upstream_is_not_a_player_hotkey(
    mock_server, pw_browser, vp
):
    # Pins the review_player.js defaultPrevented pass-through on its own: the
    # Replay rows are role=button, so isSpaceActivated alone already stands
    # Space down on them. The slider is a range input (Space would play), so
    # a closer handler that consumes Space there must win.
    ctx, page, errors = _open_loaded(pw_browser, mock_server, vp)
    try:
        page.evaluate(
            """() => document.getElementById('replay-slider')
                 .addEventListener('keydown', (e) => {
                   if (e.key === ' ' && e.altKey === false) e.preventDefault();
                 })"""
        )
        page.focus("#replay-slider")
        before = page.evaluate(_STATE)
        page.keyboard.press(" ")
        after = page.evaluate(_STATE)
        assert after["play"] == before["play"], (
            f"Space consumed by a closer handler still toggled play: {before} -> {after}"
        )
        # Control: unconsumed (Alt+Space skips the stand-in handler), the
        # same focused slider still hands the key to the player.
        page.keyboard.press("Alt+Space")
        end = page.evaluate(_STATE)
        assert end["play"] == after["play"] + 1, f"{after} -> {end}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_space_still_works_a_focused_checkbox_and_button(
    mock_server, pw_browser, vp
):
    # Found by the RM-1062 verifier: once the keys were live, a plain
    # Space on a Replay filter checkbox or a header button toggled play and
    # preventDefaulted, so the control never activated.
    ctx, page, errors = _open_loaded(pw_browser, mock_server, vp)
    try:
        page.evaluate(
            """() => {
              window.__clicks = 0;
              document.getElementById('view-trigger')
                .addEventListener('click', () => { window.__clicks += 1; });
            }"""
        )
        cb = "#replay-evt-items"
        page.focus(cb)
        was = page.eval_on_selector(cb, "el => el.checked")
        before = page.evaluate(_STATE)
        page.keyboard.press(" ")
        after = page.evaluate(_STATE)
        assert page.eval_on_selector(cb, "el => el.checked") is (not was), (
            "Space did not toggle the focused Replay filter checkbox"
        )
        assert after["play"] == before["play"], f"{before} -> {after}"

        page.focus("#view-trigger")
        page.keyboard.press(" ")
        end = page.evaluate(_STATE)
        assert page.evaluate("() => window.__clicks") == 1, (
            "Space did not press the focused header button"
        )
        assert end["play"] == after["play"], f"{after} -> {end}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_player_keys_stand_down_off_the_replay_view(mock_server, pw_browser, vp):
    # The lane section keeps hidden=false after leaving the view; rendered
    # visibility (the view is display: none) must still stand the keys down.
    ctx, page, errors = _open_loaded(pw_browser, mock_server, vp)
    try:
        page.evaluate("() => { location.hash = '#home'; }")
        page.wait_for_function(
            "() => document.body.dataset.view === 'home'", timeout=10_000
        )
        page.evaluate("() => document.activeElement && document.activeElement.blur()")
        before = page.evaluate(_STATE)
        assert before["laneVisible"], before
        page.keyboard.press(" ")
        after = page.evaluate(_STATE)
        assert after["play"] == before["play"], (
            f"Space toggled the Replay video from another view: {before} -> {after}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_ctrl_space_on_a_row_toggles_play_only(mock_server, pw_browser, vp):
    ctx, page, errors = _open_loaded(pw_browser, mock_server, vp)
    try:
        page.evaluate("() => { document.getElementById('replay-slider').value = '0'; }")
        _focus_event_row_away_from_slider(page)
        before = page.evaluate(_STATE)
        page.keyboard.press("Control+Space")
        after = page.evaluate(_STATE)
        assert after["play"] == before["play"] + 1, (
            f"Ctrl+Space on a timeline row did not toggle play: {before} -> {after}"
        )
        assert after["slider"] == "0", f"Ctrl+Space also seeked the row: {after}"

        page.focus(".replay-match-row:not(.active)")
        other = page.evaluate("() => document.activeElement.dataset.matchId")
        mid = page.evaluate(_STATE)
        page.keyboard.press("Control+Space")
        end = page.evaluate(_STATE)
        assert end["play"] == mid["play"] + 1, f"{mid} -> {end}"
        assert end["activeId"] == mid["activeId"] != other, (
            f"Ctrl+Space also loaded the focused match row: {mid} -> {end}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_the_loaded_match_row_is_aria_current(mock_server, pw_browser, vp):
    ctx, page, errors = _open_loaded(pw_browser, mock_server, vp)
    try:
        first = page.evaluate(_STATE)
        assert first["current"] == [first["activeId"]], first
        page.focus(".replay-match-row:not(.active)")
        nxt = page.evaluate("() => document.activeElement.dataset.matchId")
        page.keyboard.press("Enter")
        page.wait_for_function(
            "(id) => { const r = document.querySelector('.replay-match-row.active');"
            " return !!r && r.dataset.matchId === id; }",
            arg=nxt, timeout=10_000,
        )
        second = page.evaluate(_STATE)
        assert second["current"] == [nxt], second
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
