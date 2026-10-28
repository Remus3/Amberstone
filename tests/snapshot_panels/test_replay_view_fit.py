"""
tests/snapshot_panels/test_replay_view_fit.py
RM-1063 (s144 uiux): the Replay view overflowed its own section by the
height of its head, measured in headless Chromium under /?ui_mock=1#replay.

`.replay-body` (web/css/panels/primitives.css) was `height: 100%` of the
#view-replay content box, but the view head (about 44px with its margin)
sits above it in the same box. The body therefore ended about 44px below
the section's padding edge: at the 1920x920 baseline #view-replay measured
scrollHeight 865 against clientHeight 821, at rest and after a match load,
so both panes' bottom borders, the bottom corner brackets and the view's
bottom padding sat under the fold behind a section scrollbar.

The fix makes the active #view-replay a flex column and lets the body take
the height left under the head (flex: 1 1 auto; min-height: 0) instead of
100% of the whole box. The panes keep their own scroll (the match list and
.replay-main-pane), so nothing is lost: the view itself just stops scrolling.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page


def _open_replay(page, mock_server, load_match):
    page.goto(mock_server.url + "/?ui_mock=1#replay",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_selector("#replay-match-list .replay-match-row", timeout=10_000)
    if load_match:
        page.click("#replay-match-list .replay-match-row")
        page.wait_for_function(
            "() => document.querySelectorAll("
            "'.replay-grid-wrap tbody tr').length > 0",
            timeout=10_000,
        )


# The section's own clip edge is its padding box bottom; a pane that ends
# below it is only visible by scrolling the whole view.
_FIT = """
() => {
  const view = document.getElementById('view-replay');
  const vb = view.getBoundingClientRect();
  const clipBottom = vb.top + view.clientTop + view.clientHeight;
  const pane = sel => {
    const r = document.querySelector(sel).getBoundingClientRect();
    return {top: r.top, bottom: r.bottom, h: r.height};
  };
  const head = view.querySelector('.view-section-head').getBoundingClientRect();
  return {
    display: getComputedStyle(view).display,
    sh: view.scrollHeight,
    ch: view.clientHeight,
    clipBottom,
    winH: window.innerHeight,
    headBottom: head.bottom,
    list: pane('.replay-list-pane'),
    main: pane('.replay-main-pane'),
    body: pane('#replay-body'),
  };
}
"""


@pytest.mark.parametrize("load_match", [False, True], ids=["rest", "loaded"])
@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_replay_view_does_not_scroll(mock_server, pw_browser, vp, load_match):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    try:
        _open_replay(page, mock_server, load_match)
        m = page.evaluate(_FIT)
        assert m["display"] != "none", m
        assert m["sh"] <= m["ch"], (
            f"#view-replay scrolls: scrollHeight {m['sh']} > clientHeight "
            f"{m['ch']}: {m}"
        )
        for name in ("list", "main"):
            assert m[name]["bottom"] <= m["clipBottom"] + 0.5, (
                f"{name} pane bottom {m[name]['bottom']} below the view clip "
                f"edge {m['clipBottom']}: {m}"
            )
            # The body sits under the head, not over it.
            assert m[name]["top"] >= m["headBottom"] - 0.5, m
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_replay_panes_still_fill_the_view(mock_server, pw_browser, vp):
    """Anti-vacuity: the fix must not pass by collapsing the body. The two
    panes stay equal-height and fill the section down to its padding, and
    the list pane keeps a usable height at the 1920x920 baseline."""
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    try:
        _open_replay(page, mock_server, True)
        m = page.evaluate(_FIT)
        assert abs(m["list"]["h"] - m["main"]["h"]) <= 1, m
        # Body ends at the section's bottom padding (--space-6, 32px in
        # web/css/tokens.css), with a little slack for subpixel rounding.
        gap = m["clipBottom"] - m["body"]["bottom"]
        assert 0 <= gap <= 36, f"body ends {gap}px above the clip edge: {m}"
        assert m["list"]["h"] >= 500, m
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
