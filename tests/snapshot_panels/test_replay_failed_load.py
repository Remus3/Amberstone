"""
tests/snapshot_panels/test_replay_failed_load.py
A Replay pick that does not load, or loads with no timeline frames, must not
leave the previous match on screen (s144 lane uiux, S144-U-184; the U-183
FUTURE row "when the NEWEST pick's reply fails, the meta line stays
'loading <id>...' and the grid keeps the previous match").

Before the fix, _replayLoadMatch (web/js/panels/dev.js) returned on a null
reply (a 404, or a ui_mock id the fixture lacks) and only logged a rejected
fetch, so after A loaded and B failed the meta line read "loading B..."
forever while the scrubber, clock, minimap and grid kept showing A under the
highlighted row B. The sibling case: a match stored with NO timeline frames
(the real store holds such rows - an ARAM Mayhem q2400 game, whose Match-V5
timeline is not served, among them) set the meta line to B but
_replayRenderSnapshot returned early, so A's clock and grid stayed under it.

Contract pinned here (live /api path, no ui_mock, replies routed from the
ui_mock replay fixture; A = MOCK_NORMAL_DRAFT_WIN, 4 frames):
  - B's reply fails (404, or a network error that rejects the fetch): the
    meta line reads "could not load B - pick it again to retry", the grid
    holds only the "match did not load" row, the scrubber is disabled at
    max 0, the clock reads "-", the minimap is hidden, row B stays the one
    active pick; picking B again once the reply succeeds loads B;
  - B loads with no frames: the meta line names B, the grid holds only the
    "no timeline frames stored for this match" row, the clock reads "-",
    the scrubber is disabled, the minimap is hidden;
  - the grid placeholder cell (those two notes and the page-open "no match
    selected") stays a table cell spanning the grid: display:flex from the
    shared .home-empty rule used to drop its colspan, leaving a 105 px
    column at the left edge;
  - control: A alone loads A's frame 0 grid and a frame clock (so the
    assertions are not satisfied by a view that never loaded A).
"""
import json
from pathlib import Path

import pytest

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
_FAILED = (
    "(id) => document.getElementById('replay-meta').textContent"
    ".startsWith('could not load ' + id)"
)

_READ = """() => {
  const rows = [...document.querySelectorAll('#replay-match-list .replay-match-row')];
  const slider = document.getElementById('replay-slider');
  const fig = document.getElementById('replay-map-figure');
  return {
    meta: document.getElementById('replay-meta').textContent,
    clock: document.getElementById('replay-clock').textContent,
    sliderMax: slider.max,
    sliderDisabled: slider.disabled,
    mapHidden: !fig || fig.hidden,
    champs: [...document.querySelectorAll(
      '#replay-grid-body .replay-col-champ span')].map((s) => s.textContent),
    gridRows: [...document.querySelectorAll('#replay-grid-body tr')]
      .map((tr) => tr.textContent.trim()),
    active: rows.filter((r) => r.classList.contains('active'))
      .map((r) => r.dataset.matchId),
    note: (() => {
      const td = document.querySelector('#replay-grid-body td.home-empty');
      if (!td) return null;
      const head = document.querySelector('.replay-grid thead tr');
      return {
        display: getComputedStyle(td).display,
        span: td.getBoundingClientRect().width
          / head.getBoundingClientRect().width,
      };
    })(),
  };
}"""


def _fixture():
    doc = json.loads(_MOCK.read_text(encoding="utf-8"))
    return doc, {m["match_id"]: m for m in doc["matches"]}


def _open(pw_browser, url, plan):
    """The Replay view on the live /api path with replies routed from the
    fixture. plan maps a match id to a list of one-shot actions for its
    match reply, consumed in order: "404", "abort" (the fetch rejects) or
    "noframes" (the row with its snapshots emptied); an id with no action
    left gets its fixture row."""
    doc, by_id = _fixture()
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)

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
        elif act == "noframes":
            _json(route, dict(by_id[mid], snapshots=[]))
        else:
            _json(route, by_id.get(mid))

    def on_events(route):
        mid = route.request.url.split("match_id=", 1)[1].split("&")[0]
        hit = by_id.get(mid) or {}
        _json(route, {"ok": True, "events": hit.get("events", []),
                      "you_flagged": []})

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
    return ctx, page, errors, by_id


def _row(page, mid):
    return page.locator(f'{_ROWS}[data-match-id="{mid}"]')


def _load_a(page, by_id):
    _row(page, _A).click()
    page.wait_for_function(_LOADED, arg=_A, timeout=10_000)
    page.evaluate(_SETTLE)
    state = page.evaluate(_READ)
    want = sorted(p["champion_name"] for p in by_id[_A]["participants"])
    assert sorted(state["champs"]) == want, f"A did not load: {state}"
    return state


def _assert_note_spans_the_grid(state, where):
    note = state["note"]
    assert note is not None, f"{where}: no placeholder cell: {state}"
    assert note["display"] == "table-cell", (
        f"{where}: the placeholder cell left table layout: {note}")
    assert note["span"] > 0.95, (
        f"{where}: the placeholder cell does not span the grid: {note}")


def _assert_nothing_of_a(state, by_id, where):
    a_champs = {p["champion_name"] for p in by_id[_A]["participants"]}
    assert not a_champs & set(state["champs"]), (
        f"{where}: the grid still shows A: {state['champs']}")
    assert state["clock"] == "-", f"{where}: A's clock stayed: {state}"
    assert state["sliderDisabled"] and state["sliderMax"] == "0", (
        f"{where}: the scrubber still spans A: {state}")
    assert state["mapHidden"], f"{where}: the minimap still shows A: {state}"
    assert state["active"] == [_B], f"{where}: the active pick is not B: {state}"


@pytest.mark.parametrize("failure", ["404", "abort"])
def test_a_failed_pick_says_so_and_drops_the_previous_match(
        mock_server, pw_browser, failure):
    mock_server._store["data"] = {}
    plan = {_B: [failure]}
    ctx, page, errors, by_id = _open(pw_browser, mock_server.url, plan)
    try:
        _load_a(page, by_id)
        _row(page, _B).click()
        page.wait_for_function(_FAILED, arg=_B, timeout=10_000)
        page.evaluate(_SETTLE)
        failed = page.evaluate(_READ)
        _row(page, _B).click()
        page.wait_for_function(_LOADED, arg=_B, timeout=10_000)
        page.evaluate(_SETTLE)
        retried = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert failed["meta"] == f"could not load {_B} - pick it again to retry", (
        f"the failed pick's meta line: {failed['meta']!r}")
    assert failed["gridRows"] == ["match did not load"], (
        f"the failed pick's grid: {failed['gridRows']}")
    _assert_nothing_of_a(failed, by_id, f"B failed ({failure})")
    _assert_note_spans_the_grid(failed, f"B failed ({failure})")
    want = sorted(p["champion_name"] for p in by_id[_B]["participants"])
    assert sorted(retried["champs"]) == want, (
        f"picking B again did not load B: {retried}")
    assert retried["clock"].startswith("t = "), f"B's clock: {retried}"
    assert not retried["sliderDisabled"], f"B's scrubber: {retried}"
    assert retried["active"] == [_B], f"B's pick: {retried}"


def test_a_pick_with_no_timeline_frames_drops_the_previous_grid(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    plan = {_B: ["noframes"]}
    ctx, page, errors, by_id = _open(pw_browser, mock_server.url, plan)
    try:
        _load_a(page, by_id)
        _row(page, _B).click()
        page.wait_for_function(_LOADED, arg=_B, timeout=10_000)
        page.evaluate(_SETTLE)
        state = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert state["gridRows"] == ["no timeline frames stored for this match"], (
        f"the frameless pick's grid: {state['gridRows']}")
    _assert_nothing_of_a(state, by_id, "B has no frames")
    _assert_note_spans_the_grid(state, "B has no frames")


def test_control_a_alone_loads_a(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, by_id = _open(pw_browser, mock_server.url, {})
    try:
        state = _load_a(page, by_id)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert state["clock"].startswith("t = "), f"A's clock: {state}"
    assert not state["sliderDisabled"], f"A's scrubber: {state}"
    assert state["sliderMax"] == str(len(by_id[_A]["snapshots"]) - 1)
    assert state["active"] == [_A]


def test_the_page_open_placeholder_spans_the_grid(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, _by_id = _open(pw_browser, mock_server.url, {})
    try:
        page.evaluate(_SETTLE)
        state = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert state["gridRows"] == ["no match selected"], state["gridRows"]
    _assert_note_spans_the_grid(state, "page open")
