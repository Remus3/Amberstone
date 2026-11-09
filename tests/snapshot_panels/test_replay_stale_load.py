"""
tests/snapshot_panels/test_replay_stale_load.py
A Replay pick whose reply lands after a LATER pick's reply must not paint
over the later pick (s144 lane uiux, S144-U-183; the U-182 FUTURE row "the
pre-existing stale-load race in _replayLoadMatch").

Before the fix, _replayLoadMatch (web/js/panels/dev.js) and
loadReplayEvents (web/js/panels/replay_events.js) applied every reply they
got, in arrival order. Pick A on a slow reply, then pick B: B loaded, then
A's late reply set _REPLAY.match, the meta line, the scrubber range, the
minimap and the grid back to A while row B stayed the highlighted,
aria-current pick; A's late events reply replaced B's timeline ribbon; and
the late A reply called loadReviewPlayer(A, team), which (its match id now
B) reset the recording lane to A and fetched /api/recordings/A again.

Contract pinned here (live /api path, no ui_mock, replies routed from the
ui_mock replay fixture; A = MOCK_NORMAL_DRAFT_WIN, 4 frames and 15 events;
B = the Arena row, 3 frames and 3 events):
  - after A's held match and events replies are released, the meta line
    still names B, the scrubber max is B's last frame index, the grid
    shows B's frame 0 rows, the event count and ribbon rows are B's, and
    row B is the only active, aria-current row;
  - /api/recordings/A is not fetched again once B was picked;
  - control: B picked alone loads exactly that state (so the assertions
    are not satisfied by an empty or never-loaded view).
"""
import json
from pathlib import Path

from tests.snapshot_panels.conftest import _WS_STUB

_MOCK = Path(__file__).resolve().parents[2] / "web" / "data" / "ui_mock" / "replay.json"
_ROWS = "#replay-match-list .replay-match-row"
_A = "MOCK_NORMAL_DRAFT_WIN"

_SETTLE = (
    "() => new Promise((ok) => setTimeout(() =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok)), 150))"
)
_LOADED = (
    "(id) => {"
    " const m = document.getElementById('replay-meta').textContent;"
    " return m.startsWith(id + ' - ') && / - patch /.test(m); }"
)
_EVENTS_FOR = (
    "(n) => document.getElementById('replay-events-count').textContent"
    " === String(n)"
)

_READ = """() => {
  const rows = [...document.querySelectorAll('#replay-match-list .replay-match-row')];
  const active = rows.filter((r) => r.classList.contains('active'))
    .map((r) => r.dataset.matchId);
  const current = rows.filter((r) => r.getAttribute('aria-current') === 'true')
    .map((r) => r.dataset.matchId);
  const champs = [...document.querySelectorAll(
      '#replay-grid-body .replay-col-champ span')].map((s) => s.textContent);
  return {
    meta: document.getElementById('replay-meta').textContent,
    sliderMax: document.getElementById('replay-slider').max,
    champs,
    eventCount: document.getElementById('replay-events-count').textContent,
    eventRows: document.querySelectorAll(
      '#replay-events-list .replay-events-row').length,
    active, current,
  };
}"""


def _fixture():
    doc = json.loads(_MOCK.read_text(encoding="utf-8"))
    by_id = {m["match_id"]: m for m in doc["matches"]}
    b_id = next(i for i in by_id if i.startswith("MOCK_ARENA"))
    return doc, by_id, b_id


def _open(pw_browser, url, hold_ids):
    """The Replay view on the live /api path with replies routed from the
    fixture. A match or events reply for an id in hold_ids is parked until
    the test releases it; recordings requests are logged and answered
    has_video false."""
    doc, by_id, b_id = _fixture()
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    held: list = []
    recordings: list[str] = []

    def _json(route, obj):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(obj))

    def on_list(route):
        _json(route, {"matches": doc["matches"]})

    def on_match(route):
        mid = route.request.url.rsplit("/", 1)[-1].split("?")[0]
        reply = by_id.get(mid)
        if mid in hold_ids:
            held.append((route, reply))
        else:
            _json(route, reply)

    def on_events(route):
        mid = route.request.url.split("match_id=", 1)[1].split("&")[0]
        hit = by_id.get(mid) or {}
        reply = {"ok": True, "events": hit.get("events", []),
                 "you_flagged": []}
        if mid in hold_ids:
            held.append((route, reply))
        else:
            _json(route, reply)

    def on_recording(route):
        recordings.append(route.request.url.rsplit("/", 1)[-1])
        _json(route, {"has_video": False})

    page.route("**/api/replay/matches*", on_list)
    page.route("**/api/replay/match/*", on_match)
    page.route("**/api/replay/events*", on_events)
    page.route("**/api/recordings/*", on_recording)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(url + "/#replay", wait_until="domcontentloaded",
              timeout=15_000)
    page.wait_for_selector(_ROWS, timeout=10_000)
    return ctx, page, errors, held, recordings, by_id, b_id


def _row(page, mid):
    return page.locator(f'{_ROWS}[data-match-id="{mid}"]')


def _assert_shows_b(state, b, b_id, where):
    assert state["meta"].startswith(b_id + " - "), (
        f"{where}: the meta line names another match: {state['meta']!r}")
    assert state["sliderMax"] == str(len(b["snapshots"]) - 1), (
        f"{where}: the scrubber range is not B's: {state}")
    want = sorted(p["champion_name"] for p in b["participants"])
    assert sorted(state["champs"]) == want, (
        f"{where}: the grid is not B's frame 0: {state['champs']}")
    assert state["eventCount"] == str(len(b["events"])), (
        f"{where}: the event count is not B's: {state}")
    assert state["eventRows"] == len(b["events"]), (
        f"{where}: the ribbon rows are not B's: {state}")
    assert state["active"] == [b_id] and state["current"] == [b_id], (
        f"{where}: the highlighted pick is not B alone: {state}")


def test_a_late_reply_for_an_earlier_pick_does_not_paint_over_the_later_pick(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, held, recordings, by_id, b_id = _open(
        pw_browser, mock_server.url, {_A})
    try:
        _row(page, _A).click()
        page.wait_for_function(
            "(id) => document.getElementById('replay-meta').textContent"
            " === 'loading ' + id + '...'", arg=_A, timeout=10_000)
        _row(page, b_id).click()
        page.wait_for_function(_LOADED, arg=b_id, timeout=10_000)
        page.wait_for_function(_EVENTS_FOR, arg=len(by_id[b_id]["events"]),
                               timeout=10_000)
        page.evaluate(_SETTLE)
        assert len(held) == 2, f"expected A's match + events held: {held}"
        rec_before = list(recordings)
        for route, reply in held:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(reply))
        page.evaluate(_SETTLE)
        page.evaluate(_SETTLE)
        state = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    _assert_shows_b(state, by_id[b_id], b_id, "after A's late reply")
    late = recordings[len(rec_before):]
    assert _A not in late, (
        f"the late A reply re-armed the recording lane for A: {recordings}")


def test_control_b_picked_alone_loads_b(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, held, _rec, by_id, b_id = _open(
        pw_browser, mock_server.url, set())
    try:
        _row(page, b_id).click()
        page.wait_for_function(_LOADED, arg=b_id, timeout=10_000)
        page.wait_for_function(_EVENTS_FOR, arg=len(by_id[b_id]["events"]),
                               timeout=10_000)
        page.evaluate(_SETTLE)
        state = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert not held
    _assert_shows_b(state, by_id[b_id], b_id, "B alone")
