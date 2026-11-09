"""
tests/snapshot_panels/test_ui_mock_active_match_map_return.py
The Active Match MAP pane on return to the view (session 144, lane uiux,
S144-U-232).

The MAP poll (web/js/panels/active_match.js _amStartMapPolling) sends nothing
while another view is shown, so the feed-age track (S144-U-221) stops at the
last answer seen before the operator left. On return the view-change render
repaints the cached answer at once (_renderAmMap), and that repaint judged the
feed's age against a track the page had stopped feeding: after 10 s or more
away, a feed that was writing the whole time read "vision feed stalled at
9:47 - 15s ago", every roster row "no feed" and the SR gank band down, until
the first poll after the return landed. Over a slow server that is up to the
5 s request timeout, on the one view whose only job is the live map.

Now the track is marked unobserved while the view is away (unless the line
already said stalled: a judged stall stays judged), and a paint while it is
unobserved does not judge the age. The first request to settle on the view
after the return clears the mark, whether it is the one still open from
before the away or the first sent after it: an answer with a new t_now is
fresh, an answer with the same t_now (the tracker stopped writing while the
operator was away) reads stalled with the whole age, and a failed or
timed-out request reads stalled too (the feed could not be confirmed), so
the return never hides a real stall for longer than one request (at most
the 5 s request timeout).

Time moves with Playwright's clock (installed before navigation). Drive
path: /?ui_mock=1&mode=<mayhem|sr>#active-match with an empty /api/state.
"""
import json

import pytest

from tests.snapshot_panels.test_ui_mock_active_match_map_stall import (
    _FRESH,
    _GANK_JS,
    _ROSTER_FRESH,
    _ROSTER_JS,
    _ROSTER_STALE,
    _SR_FRESH,
    _SR_GANK,
    _STALLED,
    _STATUS_JS,
    _Feed,
    _open,
    _vs_sr,
)

_VIEW_JS = "() => document.body.dataset.view || ''"


class _HoldFeed(_Feed):
    """_Feed plus kind 'hold': the request is kept open until release()
    answers it with a live (new t_now) state."""

    def __init__(self, kind, shape=None):
        if shape is None:
            super().__init__(kind)
        else:
            super().__init__(kind, shape)
        self.held = []

    def __call__(self, route):
        if self.kind == "hold":
            self.held.append(route)
            return
        super().__call__(route)

    def release(self):
        held, self.held = self.held, []
        self.kind = "live"
        for route in held:
            self.hits += 1
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(self.shape(
                              1_700_000_000.0 + self.hits)))


def _go(page, view):
    page.evaluate(f"() => {{ location.hash = '#{view}'; }}")
    page.wait_for_function(f"({_VIEW_JS})() === {json.dumps(view)}",
                           timeout=10_000)
    # The view-change render (the ui_mock dispatcher) lands on real time;
    # the page clock is not run, so no poll tick fires meanwhile.
    page.wait_for_timeout(400)


def _away(page, ms):
    """Leave for Home and run the page clock for ms while away."""
    _go(page, "home")
    page.clock.run_for(ms)
    page.wait_for_timeout(300)


def _tick(page, ms=600):
    page.clock.run_for(ms)
    page.wait_for_timeout(400)
    return page.evaluate(_STATUS_JS)


def test_return_repaint_does_not_call_a_live_feed_stalled(
    mock_server, pw_browser
):
    """15 s away from a feed that kept writing: the return paints the cached
    counts and roster, not "stalled", and keeps them while the first request
    after the return is still open; its answer keeps them."""
    feed = _HoldFeed("live")
    ctx, page, errors = _open(pw_browser, mock_server, feed)
    try:
        _away(page, 15_000)
        feed.kind = "hold"
        _go(page, "active-match")
        got = page.evaluate(_STATUS_JS)
        assert got == _FRESH, got
        assert page.evaluate(_ROSTER_JS) == _ROSTER_FRESH
        # The first poll after the return is sent and still open.
        got = _tick(page)
        assert feed.held, "no poll was sent after the return"
        assert got == _FRESH, got
        assert page.evaluate(_ROSTER_JS) == _ROSTER_FRESH
        feed.release()
        page.wait_for_timeout(300)
        got = _tick(page)
        assert got == _FRESH, got
        assert page.evaluate(_ROSTER_JS) == _ROSTER_FRESH
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


def test_sr_return_keeps_the_gank_band_of_a_live_feed(
    mock_server, pw_browser
):
    """SR: the gank band of a live feed is not taken down by the return
    repaint after 15 s away."""
    feed = _HoldFeed("live", _vs_sr)
    ctx, page, errors = _open(pw_browser, mock_server, feed, mode="sr",
                              fresh=_SR_FRESH)
    try:
        page.wait_for_function(
            f"({_GANK_JS})() === {json.dumps(_SR_GANK)}", timeout=10_000)
        _away(page, 15_000)
        feed.kind = "hold"
        _go(page, "active-match")
        assert page.evaluate(_STATUS_JS) == _SR_FRESH
        assert page.evaluate(_GANK_JS) == _SR_GANK
        feed.release()
        page.wait_for_timeout(300)
        assert _tick(page) == _SR_FRESH
        assert page.evaluate(_GANK_JS) == _SR_GANK
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


@pytest.mark.parametrize("kind", ["frozen", "dead"])
def test_a_feed_that_stalled_while_away_reads_stalled_once_polled(
    kind, mock_server, pw_browser
):
    """The tracker stopped writing (frozen) or the route failed (dead) while
    the operator was away: the first poll after the return says stalled,
    with the whole age, not a fresh 0 s."""
    feed = _HoldFeed("live")
    ctx, page, errors = _open(pw_browser, mock_server, feed)
    try:
        # _Feed's frozen t_now is a new value once, so one poll lands on the
        # view first (its 0.6 s of age stays under the stale cut).
        feed.kind = kind
        assert _tick(page) == _FRESH, kind
        _away(page, 15_000)
        _go(page, "active-match")
        got = _tick(page)
        m = _STALLED.match(got)
        assert m, (kind, got)
        assert int(m.group(1)) >= 15, (kind, got)
        assert page.evaluate(_ROSTER_JS) == _ROSTER_STALE, kind
        feed.kind = "live"
        assert _tick(page) == _FRESH, kind
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


def test_a_hung_first_poll_after_the_return_reads_stalled_at_its_timeout(
    mock_server, pw_browser
):
    """The first request after the return never answers: the cached counts
    stand while it is open, and its 5 s timeout leaves the feed unconfirmed,
    so the line then reads stalled with the whole age."""
    feed = _HoldFeed("live")
    ctx, page, errors = _open(pw_browser, mock_server, feed)
    try:
        _away(page, 15_000)
        feed.kind = "hold"
        _go(page, "active-match")
        got = _tick(page, 4_000)
        assert got == _FRESH, got
        got = _tick(page, 1_500)
        m = _STALLED.match(got)
        assert m, got
        assert int(m.group(1)) >= 19, got
        assert page.evaluate(_ROSTER_JS) == _ROSTER_STALE
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


def test_a_stall_judged_before_leaving_stays_on_the_return_paint(
    mock_server, pw_browser
):
    """The line already said stalled when the operator left: the return
    paint keeps saying so, with the age still running, instead of the
    frozen counts. The request open across the away is held, so nothing
    settles the return before the read."""
    feed = _HoldFeed("live")
    ctx, page, errors = _open(pw_browser, mock_server, feed)
    try:
        feed.kind = "dead"
        got = _tick(page, 15_000)
        assert _STALLED.match(got), got
        feed.kind = "hold"
        _away(page, 2_000)
        _go(page, "active-match")
        got = page.evaluate(_STATUS_JS)
        m = _STALLED.match(got)
        assert m, got
        assert int(m.group(1)) >= 17, got
        assert page.evaluate(_ROSTER_JS) == _ROSTER_STALE
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


def test_a_request_open_across_a_short_away_settles_the_return(
    mock_server, pw_browser
):
    """The feed hangs; the operator leaves at about 7.5 s of age with a
    request open and is back 1 s later. That request's own timeout, on the
    view, settles the return, so the line says stalled once the age is past
    the cut, not one more 5 s request later."""
    feed = _HoldFeed("live")
    ctx, page, errors = _open(pw_browser, mock_server, feed)
    try:
        feed.kind = "hold"
        # R1 sent at once and timed out at about 5 s; R2 open from about 6 s.
        assert _tick(page, 7_000) == _FRESH
        _away(page, 1_000)
        _go(page, "active-match")
        assert page.evaluate(_STATUS_JS) == _FRESH
        # R2 times out at 10.5 to 11 s, on the view.
        got = _tick(page, 2_500)
        m = _STALLED.match(got)
        assert m, got
        assert int(m.group(1)) >= 10, got
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
