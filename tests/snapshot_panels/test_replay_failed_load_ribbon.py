"""
tests/snapshot_panels/test_replay_failed_load_ribbon.py
A Replay pick that does not load must not leave timeline events in the
Timeline ribbon (s144 lane uiux, S144-U-186; the U-184 FUTURE row "a failed
pick's Timeline ribbon can still list its events under the 'could not load'
meta line").

The ribbon (web/js/panels/replay_events.js) and the match reply
(web/js/panels/dev.js _replayLoadMatch) are two fetches from two routes. The
match route can fail (a 404, a 5xx, a dropped connection) while the events
route answers, so before the fix a failed pick B read "could not load B"
over a ribbon that listed B's events, each one a "Jump the scrubber to
m:ss" button whose click did nothing (_replaySeekToClock returns with no
match loaded), and a filter toggle re-fetched events for the match that did
not load.

Contract pinned here (live /api path, no ui_mock, replies routed from the
ui_mock replay fixture; A = MOCK_NORMAL_DRAFT_WIN, 15 events; B = the Arena
row, 3 events and 3 frames):
  - B's match reply fails (404, or a network error that rejects the fetch)
    while its events reply succeeds: the ribbon lists no rows, its count
    reads 0, its note reads "No timeline events - the match did not load.";
  - B's events reply arrives AFTER the failure: it still lists nothing;
  - picking B again once the reply succeeds lists B's 3 events and the note
    is hidden again (and reads the plain "for this match" text when shown);
  - control: A alone lists A's 15 events (so the assertions are not met by
    a ribbon that never renders).
"""
import json
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_MOCK = Path(__file__).resolve().parents[2] / "web" / "data" / "ui_mock" / "replay.json"
_ROWS = "#replay-match-list .replay-match-row"
_A = "MOCK_NORMAL_DRAFT_WIN"
_B = "MOCK_ARENA_LOSS_OVERFLOW_LONG_NAME_FOR_ELLIPSIS_TEST"
_FAILED_NOTE = "No timeline events - the match did not load."
_PLAIN_NOTE = "No timeline events for this match."

_SETTLE = (
    "() => new Promise((ok) => setTimeout(() =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok)), 150))"
)
_LOADED = (
    "(id) => {"
    " const m = document.getElementById('replay-meta').textContent;"
    " return m.startsWith(id + ' - ') && / - patch /.test(m); }"
)
_FAILED = (
    "(id) => document.getElementById('replay-meta').textContent"
    ".startsWith('could not load ' + id)"
)
_COUNT = (
    "(n) => document.getElementById('replay-events-count').textContent"
    " === String(n)"
)

_READ = """() => {
  const empty = document.getElementById('replay-events-empty');
  const section = document.getElementById('replay-events-section');
  return {
    meta: document.getElementById('replay-meta').textContent,
    rows: document.querySelectorAll('#replay-events-list .replay-events-row')
      .length,
    count: document.getElementById('replay-events-count').textContent,
    sectionHidden: section.hidden,
    emptyShown: !empty.hidden && getComputedStyle(empty).display !== 'none',
    emptyText: empty.textContent.trim(),
  };
}"""


def _fixture():
    doc = json.loads(_MOCK.read_text(encoding="utf-8"))
    return doc, {m["match_id"]: m for m in doc["matches"]}


def _open(pw_browser, url, plan, hold_events=False):
    """The Replay view on the live /api path with replies routed from the
    fixture. plan maps a match id to one-shot actions for its match reply,
    consumed in order: "404" or "abort"; an id with no action left gets its
    fixture row. The events route always answers ok with the fixture's
    events. hold_events parks B's FIRST events reply until the test
    releases it (returned as held[0])."""
    doc, by_id = _fixture()
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    held: list = []

    def _json(route, obj, status=200):
        route.fulfill(status=status, content_type="application/json",
                      body=json.dumps(obj))

    def on_match(route):
        mid = route.request.url.rsplit("/", 1)[-1].split("?")[0]
        todo = plan.get(mid) or []
        act = todo.pop(0) if todo else None
        if act == "404":
            _json(route, {"error": "not found"}, status=404)
        elif act == "abort":
            route.abort("failed")
        else:
            _json(route, by_id.get(mid))

    def events_body(mid):
        hit = by_id.get(mid) or {}
        return {"ok": True, "events": hit.get("events", []), "you_flagged": []}

    def on_events(route):
        mid = route.request.url.split("match_id=", 1)[1].split("&")[0]
        if hold_events and mid == _B and not held:
            held.append(lambda: _json(route, events_body(mid)))
            return
        _json(route, events_body(mid))

    page.route("**/api/replay/matches*",
               lambda r: _json(r, {"matches": doc["matches"]}))
    page.route("**/api/replay/match/*", on_match)
    page.route("**/api/replay/events*", on_events)
    page.route("**/api/recordings/*", lambda r: _json(r, {"has_video": False}))
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(url + "/#replay", wait_until="domcontentloaded",
              timeout=15_000)
    page.wait_for_selector(_ROWS, timeout=10_000)
    return ctx, page, errors, by_id, held


def _row(page, mid):
    return page.locator(f'{_ROWS}[data-match-id="{mid}"]')


def _load_a(page, by_id):
    _row(page, _A).click()
    page.wait_for_function(_LOADED, arg=_A, timeout=10_000)
    n = len(by_id[_A]["events"])
    page.wait_for_function(_COUNT, arg=n, timeout=10_000)
    page.evaluate(_SETTLE)
    state = page.evaluate(_READ)
    assert state["rows"] == n, f"A's ribbon did not render: {state}"
    return state


def _assert_cleared(state, where):
    assert state["rows"] == 0, (
        f"{where}: the ribbon still lists {state['rows']} event rows "
        f"under a match that did not load: {state}")
    assert state["count"] == "0", f"{where}: the count: {state}"
    assert not state["sectionHidden"], f"{where}: the section hid: {state}"
    assert state["emptyShown"], f"{where}: no ribbon note: {state}"
    assert state["emptyText"] == _FAILED_NOTE, (
        f"{where}: the ribbon note: {state['emptyText']!r}")


@pytest.mark.parametrize("failure", ["404", "abort"])
def test_a_failed_pick_lists_no_timeline_events(
        mock_server, pw_browser, failure):
    mock_server._store["data"] = {}
    plan = {_B: [failure]}
    ctx, page, errors, by_id, _held = _open(pw_browser, mock_server.url, plan)
    try:
        _load_a(page, by_id)
        _row(page, _B).click()
        page.wait_for_function(_FAILED, arg=_B, timeout=10_000)
        page.evaluate(_SETTLE)
        failed = page.evaluate(_READ)
        _row(page, _B).click()
        page.wait_for_function(_LOADED, arg=_B, timeout=10_000)
        page.wait_for_function(_COUNT, arg=len(by_id[_B]["events"]),
                               timeout=10_000)
        page.evaluate(_SETTLE)
        retried = page.evaluate(_READ)
        page.evaluate("() => { document.getElementById("
                      "'replay-events-empty').hidden = false; }")
        retried_note = page.evaluate(_READ)["emptyText"]
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    _assert_cleared(failed, f"B failed ({failure})")
    assert retried["rows"] == len(by_id[_B]["events"]), (
        f"picking B again did not list B's events: {retried}")
    assert not retried["emptyShown"], f"B's ribbon note: {retried}"
    assert retried_note == _PLAIN_NOTE, (
        f"the failed note outlived the failed pick: {retried_note!r}")


def test_a_late_events_reply_for_a_failed_pick_lists_nothing(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    plan = {_B: ["404"]}
    ctx, page, errors, by_id, held = _open(
        pw_browser, mock_server.url, plan, hold_events=True)
    try:
        _load_a(page, by_id)
        _row(page, _B).click()
        page.wait_for_function(_FAILED, arg=_B, timeout=10_000)
        page.evaluate(_SETTLE)
        assert held, "B's events request never reached the route"
        held[0]()
        page.evaluate(_SETTLE)
        page.evaluate(_SETTLE)
        late = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    _assert_cleared(late, "B failed, events late")


def test_control_a_alone_lists_its_events(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, by_id, _held = _open(pw_browser, mock_server.url, {})
    try:
        state = _load_a(page, by_id)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert state["count"] == str(len(by_id[_A]["events"]))
    assert not state["emptyShown"], state
