"""
tests/snapshot_panels/test_replay_ribbon_disabled_row_title.py
A Replay Timeline row that cannot seek no longer offers "Jump the scrubber to
<clock>" on hover (s144 lane uiux, S144-U-189; the U-188 NEXT CANDIDATE nit
"disabled ribbon rows keep the 'Jump the scrubber' title").

Since U-188 a row of a match the scrubber does not hold yet, or of a match
stored with no timeline frames, is a disabled button and the hint above the
list says why. Its title attribute (the native hover tooltip, and the
accessible description a screen reader reads with the row) still promised
"Jump the scrubber to 7:52", the one thing the row could not do.

Contract pinned here (live /api path, replies routed from the ui_mock replay
fixture; A = MOCK_NORMAL_DRAFT_WIN, B = the Arena row, 3 events; B's events
reply carries one synthetic "you flagged" pin so the flag row is covered):
  - B's events land, B's match still pending: every row's title is
    "Jumps the scrubber to <its clock> once the match loads", no row's
    title contains "Jump the scrubber to";
  - B's match lands: the SAME nodes get back their own seek titles (event
    rows "Jump the scrubber to <clock>", the flag row "You flagged this
    moment in game - jump the scrubber to <clock>");
  - B's match lands with no timeline frames: every row's title is
    "No timeline frames are stored for this match, so this row cannot jump
    the scrubber to <its clock>";
  - control: A loaded the usual way keeps "Jump the scrubber to <clock>".
"""
import json

from tests.snapshot_panels.test_replay_pending_pick_ribbon import (
    _B,
    _LOADED,
    _LOADING,
    _SETTLE,
    _load_a,
    _open,
    _row,
)

_FLAG_S = 200  # synthetic pin, 3:20

_TITLES = """() => [...document.querySelectorAll(
  '#replay-events-list .replay-events-row')].map((r) => ({
    kind: r.dataset.kind,
    clock: r.querySelector('.replay-events-clock').textContent,
    title: r.getAttribute('title'),
    disabled: r.disabled,
    marked: r.__u189 === 1,
  }))"""

_MARK = """() => document.querySelectorAll(
  '#replay-events-list .replay-events-row').forEach((r) => { r.__u189 = 1; })"""

_ROWS_N = """(n) => document.querySelectorAll(
  '#replay-events-list .replay-events-row').length === n"""


def _route_b_events_with_flag(page, by_id):
    """B's events reply carries one synthetic flag pin; other matches fall
    through to the helper's own route."""
    def on_events(route):
        url = route.request.url
        if ("match_id=" + _B) not in url:
            route.fallback()
            return
        body = {"ok": True, "events": by_id[_B]["events"],
                "you_flagged": [{"game_time_s": _FLAG_S}]}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body))
    page.route("**/api/replay/events*", on_events)


def _seek_title(row):
    if row["kind"] == "flag":
        return ("You flagged this moment in game - jump the scrubber to "
                + row["clock"])
    return "Jump the scrubber to " + row["clock"]


def test_rows_of_a_match_still_loading_do_not_offer_a_jump(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, by_id, held = _open(
        pw_browser, mock_server.url, {"match:" + _B})
    n = len(by_id[_B]["events"]) + 1
    try:
        _route_b_events_with_flag(page, by_id)
        _load_a(page, by_id)
        _row(page, _B).click()
        page.wait_for_function(_LOADING, arg=_B, timeout=10_000)
        page.wait_for_function(_ROWS_N, arg=n, timeout=10_000)
        page.evaluate(_SETTLE)
        pending = page.evaluate(_TITLES)
        page.evaluate(_MARK)
        held["match:" + _B]()
        page.wait_for_function(_LOADED, arg=_B, timeout=10_000)
        page.evaluate(_SETTLE)
        loaded = page.evaluate(_TITLES)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert len(pending) == n, pending
    assert [r["kind"] for r in pending].count("flag") == 1, pending
    assert all(r["disabled"] for r in pending), pending
    for r in pending:
        assert "Jump the scrubber to" not in (r["title"] or ""), (
            f"a disabled row still offers the jump: {r}")
        assert r["title"] == (
            f"Jumps the scrubber to {r['clock']} once the match loads"), r
    assert len(loaded) == n and all(r["marked"] for r in loaded), (
        f"the rows were rebuilt, not enabled in place: {loaded}")
    for r in loaded:
        assert not r["disabled"], r
        assert r["title"] == _seek_title(r), (
            f"an enabled row lost its own seek title: {r}")


def test_rows_of_a_match_with_no_frames_say_they_cannot_jump(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, by_id, held = _open(pw_browser, mock_server.url, set())
    frameless = dict(by_id[_B], snapshots=[])
    n = len(by_id[_B]["events"]) + 1
    try:
        _route_b_events_with_flag(page, by_id)
        page.route(
            f"**/api/replay/match/{_B}",
            lambda r: r.fulfill(status=200, content_type="application/json",
                                body=json.dumps(frameless)))
        _load_a(page, by_id)
        _row(page, _B).click()
        page.wait_for_function(_LOADED, arg=_B, timeout=10_000)
        page.wait_for_function(_ROWS_N, arg=n, timeout=10_000)
        page.evaluate(_SETTLE)
        rows = page.evaluate(_TITLES)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert len(rows) == n and all(r["disabled"] for r in rows), rows
    for r in rows:
        assert r["title"] == (
            "No timeline frames are stored for this match, so this row "
            f"cannot jump the scrubber to {r['clock']}"), r


def test_control_a_loaded_match_keeps_its_seek_titles(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, by_id, held = _open(pw_browser, mock_server.url, set())
    try:
        _load_a(page, by_id)
        rows = page.evaluate(_TITLES)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert rows and not any(r["disabled"] for r in rows), rows
    for r in rows:
        assert r["title"] == _seek_title(r), r
