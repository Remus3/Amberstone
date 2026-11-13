"""
tests/snapshot_panels/test_replay_reentry_keeps_loaded_mark.py
RM-2102 (s163 uiux; LEDGER 2023 "LEFT", MAIN 0341 item 2 (a)): the Replay
match list dropped the loaded match's mark on every view re-entry.
web/js/main.js `applyView("replay")` calls `_replayViewRefresh()` on each
entry; it empties `#replay-match-list` and rebuilds every row button with
no `.active` and no `aria-current`. The only writer of the mark was
`_replayLoadMatch`, at pick time. The match stayed loaded (`_REPLAY.match`
kept it, the meta line still named it, the scrubber stayed live), so the
list told a screen reader and a sighted user that nothing was picked.
Measured in headless Chromium before the fix: after a load, leave and
re-enter, `.replay-match-row.active` was absent and the `[aria-current]`
list was empty.

Contract pinned here (live /api path, no ui_mock, replies routed from the
ui_mock replay fixture, so every match fetch is counted):
  - a loaded match, after leave and re-enter: exactly one row, the one
    whose data-match-id is the loaded match's id, carries .active and
    aria-current="true"; every other row carries neither; and the
    re-entry makes no /api/replay/match fetch (the mark is applied from
    the held state, never by loading again);
  - a failed load (the newest pick's reply fails, `failed()` clears
    `_REPLAY.match`), after leave and re-enter: no row is marked. The
    failed row stays marked in place until then, as
    test_replay_failed_load.py pins (S144-U-184);
  - a pick still in flight at re-entry (decision, RM-2102): the rebuilt
    list marks that pick's row at once, as the pick itself did before
    the view was left (RM-1062 marks on pick, before the reply), and the
    row keeps the mark when the reply lands; a pick a newer one
    superseded never marks a row when its late reply lands (the
    S144-U-183 sequence guard), whether the newer pick came before the
    re-entry or after it;
  - control: a re-entry with nothing picked marks no row.
"""
import json
from pathlib import Path

from tests.snapshot_panels.conftest import _WS_STUB

_MOCK = Path(__file__).resolve().parents[2] / "web" / "data" / "ui_mock" / "replay.json"
_ROWS = "#replay-match-list .replay-match-row"
_A = "MOCK_NORMAL_DRAFT_WIN"
_B = "MOCK_RANKED_SOLO_WIN_ZERO_KDA"

_SETTLE = (
    "() => new Promise((ok) => setTimeout(() =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok)), 150))"
)
_LOADED = (
    "(id) => {"
    " const m = document.getElementById('replay-meta').textContent;"
    " return m.startsWith(id + ' - ') && / - patch /.test(m); }"
)
_PENDING = (
    "(id) => document.getElementById('replay-meta').textContent"
    " === 'loading ' + id + '...'"
)
_FAILED = (
    "(id) => document.getElementById('replay-meta').textContent"
    ".startsWith('could not load ' + id)"
)
# Every row now on the page, stamped before the view is left, so the wait
# after re-entry can tell the rebuilt rows from the ones it replaced.
_STAMP = (
    "() => document.querySelectorAll('#replay-match-list .replay-match-row')"
    ".forEach((r) => r.setAttribute('data-rm2102-old', ''))"
)
_REBUILT = (
    "(n) => { const rows = [...document.querySelectorAll("
    "'#replay-match-list .replay-match-row')];"
    " return rows.length === n"
    " && rows.every((r) => !r.hasAttribute('data-rm2102-old')); }"
)

_READ = """() => {
  const rows = [...document.querySelectorAll('#replay-match-list .replay-match-row')];
  return {
    meta: document.getElementById('replay-meta').textContent,
    sliderDisabled: document.getElementById('replay-slider').disabled,
    active: rows.filter((r) => r.classList.contains('active'))
      .map((r) => r.dataset.matchId),
    current: rows.filter((r) => r.getAttribute('aria-current') === 'true')
      .map((r) => r.dataset.matchId),
    anyCurrent: [...document.querySelectorAll('#replay-match-list [aria-current]')]
      .map((e) => ({ tag: e.tagName, val: e.getAttribute('aria-current'),
                     id: e.dataset.matchId || null })),
  };
}"""


def _fixture():
    doc = json.loads(_MOCK.read_text(encoding="utf-8"))
    return doc, {m["match_id"]: m for m in doc["matches"]}


def _open(pw_browser, url, plan=None, hold=()):
    """The Replay view on the live /api path with replies routed from the
    fixture. plan maps a match id to one-shot actions for its match reply
    ("404"); a match or events reply for an id in hold is parked until the
    test releases it. Every match fetch's id is logged in order."""
    plan = plan or {}
    doc, by_id = _fixture()
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    held: list = []
    fetched: list[str] = []

    def _json(route, obj, status=200):
        route.fulfill(status=status, content_type="application/json",
                      body=json.dumps(obj))

    def on_match(route):
        mid = route.request.url.rsplit("/", 1)[-1].split("?")[0]
        fetched.append(mid)
        todo = plan.get(mid) or []
        act = todo.pop(0) if todo else None
        if act == "404":
            _json(route, {"error": "not found"}, status=404)
        elif mid in hold:
            held.append((mid, route, by_id.get(mid)))
        else:
            _json(route, by_id.get(mid))

    def on_events(route):
        mid = route.request.url.split("match_id=", 1)[1].split("&")[0]
        hit = by_id.get(mid) or {}
        reply = {"ok": True, "events": hit.get("events", []),
                 "you_flagged": []}
        if mid in hold:
            held.append((mid, route, reply))
        else:
            _json(route, reply)

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
    return ctx, page, errors, held, fetched, len(doc["matches"])


def _row(page, mid):
    return page.locator(f'{_ROWS}[data-match-id="{mid}"]')


def _release(page, held, mid):
    """Answer every parked reply for mid (match and events), then settle."""
    for item in [h for h in held if h[0] == mid]:
        held.remove(item)
        _hid, route, reply = item
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(reply))
    page.evaluate(_SETTLE)


def _leave_and_return(page, n_rows):
    page.evaluate(_STAMP)
    page.evaluate("location.hash = '#home'")
    page.wait_for_function("document.body.dataset.view === 'home'",
                           timeout=10_000)
    page.evaluate("location.hash = '#replay'")
    page.wait_for_function("document.body.dataset.view === 'replay'",
                           timeout=10_000)
    page.wait_for_function(_REBUILT, arg=n_rows, timeout=10_000)
    page.evaluate(_SETTLE)


def _assert_marked(state, mid, where):
    assert state["active"] == [mid] and state["current"] == [mid], (
        f"{where}: the mark is not on {mid} alone: {state}")
    assert state["anyCurrent"] == [
        {"tag": "BUTTON", "val": "true", "id": mid}], (
        f"{where}: aria-current sits elsewhere too: {state['anyCurrent']}")


def _assert_unmarked(state, where):
    assert state["active"] == [] and state["anyCurrent"] == [], (
        f"{where}: a row is marked: {state}")


def test_reentry_marks_the_loaded_match_row_with_no_second_load(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, _held, fetched, n = _open(pw_browser, mock_server.url)
    try:
        _row(page, _B).click()
        page.wait_for_function(_LOADED, arg=_B, timeout=10_000)
        page.evaluate(_SETTLE)
        before = page.evaluate(_READ)
        fetched_before = list(fetched)
        _leave_and_return(page, n)
        first = page.evaluate(_READ)
        _leave_and_return(page, n)
        second = page.evaluate(_READ)
        fetched_after = list(fetched)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    # Control: the pick loaded B and marked it before the view was left.
    _assert_marked(before, _B, "after the pick")
    assert fetched_before == [_B], fetched_before
    for where, state in (("first re-entry", first), ("second re-entry", second)):
        # The match is still the one held: meta names B, scrubber live.
        assert state["meta"].startswith(_B + " - "), (where, state)
        assert not state["sliderDisabled"], (where, state)
        _assert_marked(state, _B, where)
    assert fetched_after == fetched_before, (
        f"a re-entry loaded a match again: {fetched_before} -> {fetched_after}")


def test_reentry_after_a_failed_load_marks_no_row(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, _held, fetched, n = _open(
        pw_browser, mock_server.url, plan={_B: ["404"]})
    try:
        _row(page, _A).click()
        page.wait_for_function(_LOADED, arg=_A, timeout=10_000)
        _row(page, _B).click()
        page.wait_for_function(_FAILED, arg=_B, timeout=10_000)
        page.evaluate(_SETTLE)
        in_place = page.evaluate(_READ)
        fetched_before = list(fetched)
        _leave_and_return(page, n)
        state = page.evaluate(_READ)
        fetched_after = list(fetched)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    # In place the failed row stays the pick (test_replay_failed_load.py).
    _assert_marked(in_place, _B, "the failed pick, in place")
    assert state["meta"].startswith("could not load " + _B), state
    _assert_unmarked(state, "re-entry after a failed load")
    assert fetched_after == fetched_before, (fetched_before, fetched_after)


def test_reentry_with_a_pick_in_flight_marks_it_and_keeps_it_on_resolve(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, held, fetched, n = _open(
        pw_browser, mock_server.url, hold={_A})
    try:
        _row(page, _A).click()
        page.wait_for_function(_PENDING, arg=_A, timeout=10_000)
        _leave_and_return(page, n)
        pending = page.evaluate(_READ)
        assert any(h[0] == _A for h in held), f"A's reply not parked: {held}"
        _release(page, held, _A)
        page.wait_for_function(_LOADED, arg=_A, timeout=10_000)
        page.evaluate(_SETTLE)
        resolved = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert pending["meta"] == f"loading {_A}...", pending
    _assert_marked(pending, _A, "re-entry with A in flight")
    _assert_marked(resolved, _A, "A's reply landed after the re-entry")
    assert fetched == [_A], f"A was fetched more than once: {fetched}"


def test_a_superseded_pick_never_marks_when_its_late_reply_lands(
        mock_server, pw_browser):
    """A then B both in flight at re-entry: B (the newest) is marked, and
    A's late reply moves nothing; B's reply keeps B marked."""
    mock_server._store["data"] = {}
    ctx, page, errors, held, _fetched, n = _open(
        pw_browser, mock_server.url, hold={_A, _B})
    try:
        _row(page, _A).click()
        page.wait_for_function(_PENDING, arg=_A, timeout=10_000)
        _row(page, _B).click()
        page.wait_for_function(_PENDING, arg=_B, timeout=10_000)
        _leave_and_return(page, n)
        both_pending = page.evaluate(_READ)
        _release(page, held, _A)
        page.evaluate(_SETTLE)
        after_a = page.evaluate(_READ)
        _release(page, held, _B)
        page.wait_for_function(_LOADED, arg=_B, timeout=10_000)
        page.evaluate(_SETTLE)
        after_b = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    _assert_marked(both_pending, _B, "re-entry with A then B in flight")
    assert after_a["meta"] == f"loading {_B}...", after_a
    _assert_marked(after_a, _B, "A's late reply after the re-entry")
    _assert_marked(after_b, _B, "B's reply after the re-entry")


def test_a_pick_after_reentry_supersedes_the_in_flight_one(
        mock_server, pw_browser):
    """A in flight at re-entry, then B picked on the rebuilt list and
    loaded: A's late reply leaves B the only marked row."""
    mock_server._store["data"] = {}
    ctx, page, errors, held, _fetched, n = _open(
        pw_browser, mock_server.url, hold={_A})
    try:
        _row(page, _A).click()
        page.wait_for_function(_PENDING, arg=_A, timeout=10_000)
        _leave_and_return(page, n)
        _row(page, _B).click()
        page.wait_for_function(_LOADED, arg=_B, timeout=10_000)
        page.evaluate(_SETTLE)
        _release(page, held, _A)
        page.evaluate(_SETTLE)
        state = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert state["meta"].startswith(_B + " - "), state
    _assert_marked(state, _B, "A's late reply after B was picked")


def test_control_reentry_with_nothing_picked_marks_no_row(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, _held, fetched, n = _open(pw_browser, mock_server.url)
    try:
        _leave_and_return(page, n)
        state = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    _assert_unmarked(state, "re-entry with nothing picked")
    assert fetched == [], fetched
