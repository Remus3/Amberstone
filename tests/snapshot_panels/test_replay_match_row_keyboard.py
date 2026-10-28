"""
tests/snapshot_panels/test_replay_match_row_keyboard.py
RM-1018 (s144 uiux): the Replay view's RECENT MATCHES rows were
mouse-only. web/js/panels/dev.js `_replayViewRefresh` built each
`li.replay-match-row` with a click listener and nothing else: no tabindex,
no role, no key handler. Picking a match is the gate for everything else in
the view (the timeline ribbon, the scrubber, the grid), so a keyboard user
could reach none of it. Measured in headless Chromium under /?ui_mock=1#replay
before the fix: Tab never landed on a row and `row.focus()` left focus on
<body>. The scrubber `#replay-slider` (web/css/panels/primitives.css
`.replay-slider`) had no :focus-visible rule and showed only the UA `auto`
outline, unlike every other Replay control after RM-1017.

The fix: each row is a keyboard button (since RM-1066 a real
`<button type="button">` inside its li, which keeps the listitem role; see
test_replay_row_list_semantics.py), Enter and Space load the match exactly
like a click, and rows and the slider paint the system
--focus-ring box-shadow under keyboard focus. Rows draw it INSET because
#replay-match-list scrolls (an outer ring would be clipped), and a won / lost
row keeps its 3px result stripe under focus.

The list is rebuilt with innerHTML only when the view activates
(web/js/main.js `_replayViewRefresh` call on view switch), never on a timer,
so no focus preservation is needed (headless-uiux.md section 6, trap 2).
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import (
    VIEWPORTS,
    _assert_rings,
    _new_page,
    _rings,
)

_ROWS = "#replay-match-list .replay-match-row"

# Scroll offsets of the window and of the two boxes a Space page-step can
# move. The Replay view scrolls in SECTION#view-replay, not the window: an
# unhandled Space on a focused row scrolls that section while window.scrollY
# stays 0 (measured by the RM-1018 verifier).
_SCROLLS = """
() => {
  const out = { window: window.scrollY };
  for (const id of ['view-replay', 'replay-match-list']) {
    const el = document.getElementById(id);
    if (el) out[id] = el.scrollTop;
  }
  return out;
}
"""


def _goto_replay(page, mock_server):
    page.goto(mock_server.url + "/?ui_mock=1#replay",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_selector(_ROWS, timeout=10_000)


def _tab_until_row(page, bound=80):
    """Tab from <body> until a match row holds focus; returns the press
    count, or -1 when no row was reached inside the bound."""
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    for n in range(1, bound + 1):
        page.keyboard.press("Tab")
        if page.evaluate(
            "() => !!(document.activeElement && document.activeElement"
            ".matches('.replay-match-row'))"
        ):
            return n
    return -1


def _active_state(page):
    return page.evaluate(
        """() => {
          const act = document.querySelector('.replay-match-row.active');
          const foc = document.activeElement;
          return {
          activeId: act ? act.dataset.matchId : null,
          focusedId: foc && foc.matches('.replay-match-row')
            ? foc.dataset.matchId : null,
          events: document.querySelectorAll('.replay-events-row').length,
          sliderDisabled: document.getElementById('replay-slider').disabled,
          scrollY: window.scrollY,
          };
        }"""
    )


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_match_rows_are_keyboard_buttons(mock_server, pw_browser, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    try:
        _goto_replay(page, mock_server)
        attrs = page.evaluate(
            f"""() => [...document.querySelectorAll('{_ROWS}')].map(r => ({{
              id: r.dataset.matchId, tab: r.tabIndex,
              tag: r.tagName, type: r.getAttribute('type')
            }}))"""
        )
        # Anchor: the fixture (web/data/ui_mock/replay.json) carries 4 matches.
        assert len(attrs) == 4, attrs
        bad = [a for a in attrs if a["tab"] != 0 or a["tag"] != "BUTTON"
               or a["type"] != "button"]
        assert not bad, f"match rows not keyboard buttons: {bad}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_enter_and_space_load_a_match_from_the_keyboard(
    mock_server, pw_browser, vp
):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    try:
        _goto_replay(page, mock_server)
        before = _active_state(page)
        assert before["activeId"] is None and before["sliderDisabled"], before
        presses = _tab_until_row(page)
        assert presses > 0, "Tab never reached a .replay-match-row"
        first = _active_state(page)["focusedId"]
        assert first, "focused row carries no data-match-id"

        page.keyboard.press("Enter")
        page.wait_for_function(
            "() => document.querySelectorAll('.replay-events-row').length > 0"
            " && !document.getElementById('replay-slider').disabled",
            timeout=10_000,
        )
        after_enter = _active_state(page)
        assert after_enter["activeId"] == first, after_enter

        # Next row by Tab, then Space: loads that match, and Space does not
        # scroll the page (the handler takes the key from the browser).
        page.keyboard.press("Tab")
        second = _active_state(page)["focusedId"]
        assert second and second != first, f"second Tab left the rows: {second}"
        y0 = page.evaluate(_SCROLLS)
        assert "view-replay" in y0, f"scroll anchor missing: {y0}"
        page.keyboard.press(" ")
        page.wait_for_function(
            "(id) => { const r = document.querySelector('.replay-match-row.active');"
            " return !!r && r.dataset.matchId === id; }",
            arg=second, timeout=10_000,
        )
        y1 = page.evaluate(_SCROLLS)
        assert y1 == y0, f"Space scrolled the page: {y0} -> {y1}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_match_rows_and_slider_paint_a_focus_ring(mock_server, pw_browser, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    try:
        _goto_replay(page, mock_server)
        page.click(_ROWS)
        page.wait_for_function(
            "() => !document.getElementById('replay-slider').disabled",
            timeout=10_000,
        )
        page.keyboard.press("Tab")
        rows = _rings(page, _ROWS)
        _assert_rings(rows, ".replay-match-row", 4)
        # A won / lost row keeps its 3px result stripe while focused.
        striped = page.evaluate(
            f"""() => [...document.querySelectorAll('{_ROWS}')]
              .filter(r => r.classList.contains('won')
                        || r.classList.contains('lost'))
              .map(r => {{ r.focus();
                return {{ id: r.dataset.matchId,
                         shadow: getComputedStyle(r).boxShadow }}; }})"""
        )
        assert len(striped) == 3, striped
        lost = [s for s in striped if "3px 0px 0px 0px" not in s["shadow"]]
        assert not lost, f"focus ring replaced the result stripe: {lost}"
        _assert_rings(_rings(page, "#replay-slider"), "#replay-slider", 1)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
