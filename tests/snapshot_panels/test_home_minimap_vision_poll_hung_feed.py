"""
tests/snapshot_panels/test_home_minimap_vision_poll_hung_feed.py
The Home minimap's /api/vision-state poll when the server stops ANSWERING
(session 144, lane uiux, S144-U-225; the sibling S144-U-224 filed).

web/js/main.js refreshVisionOverlay draws the enemy dots on the Home
minimap and, in the shared-vision modes (ARAM / KIWI), writes the MAP STATE
pill ("4 on bridge . 1 dead") from the vision tracker's summary. It runs
every 500 ms on EVERY view (only a hidden tab skips it), and it sent a new
fetch each tick with no timeout and no limit on how many were open, so
- every tick of a server that stopped answering added one more open
  request (the S144-U-224 measurement for the Active Match poll of the same
  route was 34 to 35 open after 15 s);
- answers could land out of order, so an old one could paint over a newer.

The poll now keeps at most one request open: a tick that finds one still
open sends nothing, and a request still unanswered after
VT_FETCH_TIMEOUT_MS (5 s) is aborted and settles as a failure, so the next
tick asks again; an answer for a request given up on never paints.

The open-request count is measured in the page: an init script wraps
window.fetch and counts the /api/vision-state requests sent from
refreshVisionOverlay (by the caller's stack; active_match.js polls the same
route) until each settles or its signal aborts. Time moves with
Playwright's clock. Drive path: / with the ARAM fixture (an in-game
envelope, so the empty-state "awaiting liveclient data..." line does not
replace the pill the poll writes), with the Map State panel rendered by
show_coaching_main (S144-U-227: the poll sends nothing while the panel is
not rendered, and no view renders it).
"""
import json

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_home_minimap_crop_poll_hung_feed import (
    show_coaching_main,
)
from tests.snapshot_panels.test_ui_mock_active_match_map_stall import _vs

_COUNT_JS = r"""
(() => {
  const s = { open: 0, max: 0, started: 0 };
  window.__hmVs = s;
  const orig = window.fetch;
  window.fetch = function (input, opts) {
    const p = orig.apply(this, arguments);
    const url = String((input && input.url) || input);
    if (url.indexOf('/api/vision-state') < 0) return p;
    if (String(new Error().stack).indexOf('refreshVisionOverlay') < 0) {
      return p;
    }
    s.started += 1;
    s.open += 1;
    if (s.open > s.max) s.max = s.open;
    let closed = false;
    const close = () => { if (!closed) { closed = true; s.open -= 1; } };
    const sig = opts && opts.signal;
    if (sig) sig.addEventListener('abort', close);
    p.then(close, close);
    return p;
  };
})();
"""

_COUNTS_JS = (
    "() => (document.querySelector('#mm-state .mm-counts') || {})"
    ".textContent || null"
)
_FOUR = "4 on bridge \u00b7 1 dead"
_THREE = "3 on bridge \u00b7 2 dead"


def _vs_three(t_now):
    vs = _vs(t_now)
    vs["summary"] = {"visible_count": 3, "missing_count": 0,
                     "dead_count": 2, "total": 5}
    return vs


class _Feed:
    """The /api/vision-state stand-in. kind: 'live' answers with `shape`,
    'hung' never answers (the route is held, not fulfilled)."""

    def __init__(self, kind, shape=_vs):
        self.kind = kind
        self.shape = shape
        self.hits = 0
        self.held = []

    def __call__(self, route):
        self.hits += 1
        if self.kind == "hung":
            self.held.append(route)
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(self.shape(1_700_000_000.0 + self.hits)))


def _open(pw_browser, mock_server, feed, want=_FOUR):
    mock_server.set_fixture("aram")
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.clock.install()
    page.add_init_script(_WS_STUB)
    page.add_init_script(_COUNT_JS)
    # S144-U-227: the poll sends nothing while the Map State panel is not
    # rendered, and no view renders it.
    show_coaching_main(page)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route("**/api/vision-state*", feed)
    page.goto(mock_server.url + "/", wait_until="domcontentloaded",
              timeout=15_000)
    page.wait_for_function(
        "() => (window.__hmVs || {}).started >= 1", timeout=10_000)
    if want is not None:
        page.wait_for_function(
            f"({_COUNTS_JS})() === {json.dumps(want)}", timeout=10_000)
    return ctx, page, errors


def _advance(page, ms):
    """Run the page clock forward, then let the polls it fired land."""
    page.clock.run_for(ms)
    page.wait_for_timeout(400)
    page.clock.run_for(500)
    page.wait_for_timeout(400)
    return page.evaluate(_COUNTS_JS)


def _counts(page):
    return page.evaluate("() => Object.assign({}, window.__hmVs)")


def test_a_live_feed_keeps_one_request_open_at_a_time(
    mock_server, pw_browser
):
    """Positive control: a feed that answers keeps the shared-vision pill
    and the poll keeps asking, one request at a time."""
    feed = _Feed("live")
    ctx, page, errors = _open(pw_browser, mock_server, feed)
    try:
        got = _advance(page, 6_000)
        assert got == _FOUR, got
        c = _counts(page)
        assert c["started"] >= 8, c
        assert c["max"] == 1, c
        # A new summary reaches the pill on the next answer.
        feed.shape = _vs_three
        got = _advance(page, 1_000)
        assert got == _THREE, got
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


def test_a_hung_feed_keeps_one_request_open_and_asks_again(
    mock_server, pw_browser
):
    """The server stops answering after a live start: no more than one
    request is ever open, a hung one is given up on and asked again about
    every 5 s, and the feed's return brings the new summary through."""
    feed = _Feed("live")
    ctx, page, errors = _open(pw_browser, mock_server, feed)
    try:
        before = _counts(page)
        feed.kind = "hung"
        got = _advance(page, 15_000)
        # Nothing new arrived, so the pill keeps the last summary.
        assert got == _FOUR, got
        c = _counts(page)
        assert c["max"] == 1, c
        assert c["open"] <= 1, c
        # About one new request per 5 s over 16 s, not one per tick.
        assert 2 <= c["started"] - before["started"] <= 6, (before, c)
        feed.kind = "live"
        feed.shape = _vs_three
        got = _advance(page, 5_000)
        assert got == _THREE, got
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


def test_a_feed_that_hangs_from_the_start_recovers(mock_server, pw_browser):
    """Nothing cached and nothing coming: the first request is given up on
    and asked again, one at a time, and the first real answer paints."""
    feed = _Feed("hung")
    ctx, page, errors = _open(pw_browser, mock_server, feed, want=None)
    try:
        before = _counts(page)
        _advance(page, 11_000)
        c = _counts(page)
        assert c["max"] == 1, c
        assert 1 <= c["started"] - before["started"] <= 4, (before, c)
        feed.kind = "live"
        got = _advance(page, 5_000)
        assert got == _FOUR, got
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
