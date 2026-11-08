"""
tests/snapshot_panels/test_ui_mock_active_match_map_hung_feed.py
The Active Match MAP pane when /api/vision-state stops ANSWERING (session
144, lane uiux, S144-U-224).

S144-U-220 / U-221 / U-222 taught the pane to say so when the feed fails
(an error status, a network error) or stalls (a 200 with the same t_now). A
request that never answers is neither: the poll fired a new fetch every
500 ms with no timeout and no limit on how many were open, so
- every tick added one more open request: measured 34 and 35 open (35
  and 36 sent) after 15 s of a hung server in two runs, each held until the server or the browser gave up;
- a hang before the first answer left "loading vision..." up for good,
  never "vision feed did not load" (the failure line is painted only when
  a request settles, and none did).
With an answer cached the stall line itself still came, through the
re-render every /api/state update makes (_renderAmMap repaints the cache);
the hung-feed test pins that it still does.

The poll now keeps at most one request open: a tick that finds one still
open repaints the cached answer against the feed's age and sends nothing,
and a request still unanswered after _AM_MAP_FETCH_TIMEOUT_MS (5 s) is
aborted and settles as a failure, so the next tick asks again.

The open-request count is measured in the page: an init script wraps
window.fetch and counts the /api/vision-state requests active_match.js
sends (by the caller's stack; main.js's Home minimap polls the same route)
until each settles or its signal aborts. Time moves with Playwright's clock.
Drive path: /?ui_mock=1&mode=mayhem#active-match with an empty /api/state.
"""
import json

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ui_mock_active_match_map_stall import (
    _FRESH,
    _MAP_PNG,
    _ROSTER_FRESH,
    _ROSTER_JS,
    _ROSTER_STALE,
    _STALLED,
    _STATUS_JS,
    _vs,
)

_COUNT_JS = r"""
(() => {
  const s = { open: 0, max: 0, started: 0 };
  window.__amVs = s;
  const orig = window.fetch;
  window.fetch = function (input, opts) {
    const p = orig.apply(this, arguments);
    const url = String((input && input.url) || input);
    if (url.indexOf('/api/vision-state') < 0) return p;
    if (String(new Error().stack).indexOf('active_match.js') < 0) return p;
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


class _Feed:
    """The /api/vision-state stand-in. kind: 'live' writes a new t_now on
    every answer, 'hung' never answers (the route is held, not fulfilled)."""

    def __init__(self, kind):
        self.kind = kind
        self.hits = 0
        self.held = []

    def __call__(self, route):
        self.hits += 1
        if self.kind == "hung":
            self.held.append(route)
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(_vs(1_700_000_000.0 + self.hits)))


def _open(pw_browser, mock_server, feed, fresh=_FRESH):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.clock.install()
    page.add_init_script(_WS_STUB)
    page.add_init_script(_COUNT_JS)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route("**/api/vision-state*", feed)
    page.route("**/img/map/*", lambda r: r.fulfill(
        status=200, content_type="image/png", body=_MAP_PNG))
    page.goto(
        mock_server.url + "/?ui_mock=1&mode=mayhem#active-match",
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    page.wait_for_function(
        "(document.getElementById('am-sub')?.textContent || '')"
        ".indexOf('InProgress') >= 0",
        timeout=10_000,
    )
    if fresh is not None:
        page.wait_for_function(
            f"({_STATUS_JS})() === {json.dumps(fresh)}", timeout=10_000,
        )
    return ctx, page, errors


def _advance(page, ms):
    """Run the page clock forward, then let the polls it fired land."""
    page.clock.run_for(ms)
    page.wait_for_timeout(400)
    page.clock.run_for(500)
    page.wait_for_timeout(400)
    return page.evaluate(_STATUS_JS)


def _counts(page):
    return page.evaluate("() => Object.assign({}, window.__amVs)")


def test_a_live_feed_keeps_one_request_open_at_a_time(
    mock_server, pw_browser
):
    """Positive control: a feed that answers keeps its counts and the poll
    keeps asking, one request at a time."""
    feed = _Feed("live")
    ctx, page, errors = _open(pw_browser, mock_server, feed)
    try:
        got = _advance(page, 6_000)
        assert got == _FRESH, got
        c = _counts(page)
        assert c["started"] >= 8, c
        assert c["max"] == 1, c
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


def test_a_hung_feed_reads_stalled_and_keeps_one_request_open(
    mock_server, pw_browser
):
    """The server stops answering after a live start: the counts stand
    under the 10 s cut, then the line reads stalled and the roster "no
    feed"; no more than one request is ever open, a hung one is given up
    and asked again, and the feed's return brings the counts back."""
    feed = _Feed("live")
    ctx, page, errors = _open(pw_browser, mock_server, feed)
    try:
        before = _counts(page)
        feed.kind = "hung"
        got = _advance(page, 5_000)
        assert got == _FRESH, got
        got = _advance(page, 10_000)
        m = _STALLED.match(got)
        assert m, got
        assert 11 <= int(m.group(1)) <= 20, got
        assert page.evaluate(_ROSTER_JS) == _ROSTER_STALE
        c = _counts(page)
        assert c["max"] == 1, c
        assert c["open"] <= 1, c
        # A hung request is given up on and asked again, not waited on for
        # good: about one new request per 5 s over 16 s.
        assert 2 <= c["started"] - before["started"] <= 6, (before, c)
        # The stall line keeps counting while the request is still open.
        later = _STALLED.match(_advance(page, 2_000))
        assert later and int(later.group(1)) > int(m.group(1)), (got, later)
        feed.kind = "live"
        got = _advance(page, 5_000)
        assert got == _FRESH, got
        assert page.evaluate(_ROSTER_JS) == _ROSTER_FRESH
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


def test_a_feed_that_hangs_before_its_first_answer_says_it_did_not_load(
    mock_server, pw_browser
):
    """Nothing cached and nothing coming: "loading vision..." gives way to
    "vision feed did not load" once the first request is given up on."""
    feed = _Feed("hung")
    ctx, page, errors = _open(pw_browser, mock_server, feed, fresh=None)
    try:
        page.wait_for_function(
            f"({_STATUS_JS})() === 'loading vision...'", timeout=10_000)
        got = _advance(page, 6_000)
        assert got == "vision feed did not load", got
        c = _counts(page)
        assert c["max"] == 1, c
        feed.kind = "live"
        got = _advance(page, 5_000)
        assert got == _FRESH, got
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
