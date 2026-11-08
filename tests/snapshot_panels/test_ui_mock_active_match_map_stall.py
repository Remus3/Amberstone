"""
tests/snapshot_panels/test_ui_mock_active_match_map_stall.py
The Active Match MAP pane's status line when the vision feed stalls
(session 144, lane uiux, S144-U-221).

core/vision_tracker.py stamps each state it writes with t_now = time.time()
(every 0.75 s). When the Live Client relay goes stale (age past
_RELAY_MAX_AGE_S) the tracker resets in memory but stops writing, so
data/vision_state.json keeps its last in-game state and /api/vision-state
(dashboard/routes_diag.py _serve_vision_state) keeps serving it with a 200.
The status line repainted that same answer every 500 ms: "9:47 - 4 on bridge
- 1 dead" for the rest of the game, a count of enemies the feed no longer
watched. A poll that failed with an answer cached kept the last line too.

The pane now times how long the feed has gone without a new t_now (on the
page clock, so no skew between the box and the viewer) and past 10 s reads
"vision feed stalled at 9:47 - Ns ago". A feed whose t_now keeps moving
keeps its counts (the positive control), and a stalled feed that starts
writing again gets them back.

Time moves with Playwright's clock (installed before navigation). Drive
path: /?ui_mock=1&mode=mayhem#active-match with an empty /api/state.
"""
import json
import re

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_ENEMIES = ["Sett", "Jinx", "Brand", "Malphite", "Lux"]

_STATUS_JS = (
    "() => (document.getElementById('am-map-status') || {}).textContent || ''"
)
_FRESH = "9:47 - 4 on bridge - 1 dead"
_STALLED = re.compile(r"^vision feed stalled at 9:47 - (\d+)s ago$")


def _vs(t_now):
    """A Mayhem state at the fixture's 9:47, shaped like
    core/vision_tracker.py state(): KIWI, no positions, one enemy dead."""
    return {
        "t_now": t_now, "game_time": 587.0, "game_mode": "KIWI",
        "active_team": "ORDER",
        "enemies": {
            name: {"champion": name, "team": "CHAOS", "level": 12,
                   "is_dead": name == "Lux",
                   "respawn_in_s": 18.0 if name == "Lux" else None,
                   "visible": name != "Lux", "missing_for_s": None,
                   "last_seen_pos": None, "last_seen_t": 587.0,
                   "last_seen_zone": "on_bridge"}
            for name in _ENEMIES
        },
        "summary": {"visible_count": 4, "missing_count": 0, "dead_count": 1,
                    "total": 5},
    }


class _Feed:
    """The /api/vision-state stand-in. kind: 'live' writes a new t_now on
    every poll, 'frozen' serves one file forever, 'dead' answers 503.
    (main.js's Home minimap polls the same route, so a feed switches state
    by an explicit call, never by a hit count.)"""

    def __init__(self, kind):
        self.kind = kind
        self.hits = 0

    def __call__(self, route):
        self.hits += 1
        if self.kind == "dead":
            route.fulfill(status=503, content_type="application/json",
                          body="{}")
            return
        t_now = 1_700_000_000.0 + (self.hits if self.kind == "live" else 0)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(_vs(t_now)))


def _open(pw_browser, mock_server, feed):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.clock.install()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route("**/api/vision-state*", feed)
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
    page.wait_for_function(
        f"({_STATUS_JS})() === {json.dumps(_FRESH)}", timeout=10_000,
    )
    return ctx, page, errors


def _advance(page, ms):
    """Run the page clock forward, then let the polls it fired land."""
    page.clock.run_for(ms)
    page.wait_for_timeout(400)
    page.clock.run_for(500)
    page.wait_for_timeout(400)
    return page.evaluate(_STATUS_JS)


def test_a_live_feed_keeps_its_counts(mock_server, pw_browser):
    """Positive control: t_now moves on every poll, so 15 s on the line
    still paints the counts."""
    feed = _Feed("live")
    ctx, page, errors = _open(pw_browser, mock_server, feed)
    try:
        got = _advance(page, 15_000)
        assert got == _FRESH, got
        assert feed.hits > 10, feed.hits
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


@pytest.mark.parametrize("kind", ["frozen", "dead"])
def test_a_stalled_feed_says_so_instead_of_repeating_its_counts(
    kind, mock_server, pw_browser
):
    """frozen: the tracker stopped writing and the server keeps serving its
    last file. dead: the poll itself fails with an answer cached."""
    feed = _Feed("live")
    ctx, page, errors = _open(pw_browser, mock_server, feed)
    try:
        feed.kind = kind
        # Under the 10 s threshold the last counts still stand.
        got = _advance(page, 5_000)
        assert got == _FRESH, (kind, got)
        got = _advance(page, 10_000)
        m = _STALLED.match(got)
        assert m, (kind, got)
        assert 11 <= int(m.group(1)) <= 20, (kind, got)
        assert "on bridge" not in got and "dead" not in got, got
        # The line is drawn, not collapsed.
        assert page.evaluate(
            "document.getElementById('am-map-status').offsetHeight > 0"
        )
        # The tracker writes again: the counts come back.
        feed.kind = "live"
        got = _advance(page, 1_000)
        assert got == _FRESH, (kind, got)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
