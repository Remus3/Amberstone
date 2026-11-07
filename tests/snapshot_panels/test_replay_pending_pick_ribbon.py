"""
tests/snapshot_panels/test_replay_pending_pick_ribbon.py
While a Replay pick is still loading, the Timeline ribbon must not list the
previous pick's events, and a ribbon row must never seek a match other than
its own (s144 lane uiux, S144-U-187; the U-186 FUTURE row "while a new pick
is loading, the ribbon still lists the previous pick's rows under 'loading
<id>...', and a click seeks the previous match").

The ribbon (web/js/panels/replay_events.js) and the match reply
(web/js/panels/dev.js _replayLoadMatch) are two fetches from two routes, and
the scrubber keeps the previous match until the new match reply lands
(S144-U-183). Before the fix:
  - pick A, then pick B: until B's events reply landed, the ribbon listed
    A's 15 rows under "loading B...", each a seek button for A;
  - when B's events reply landed before B's match reply, the ribbon listed
    B's rows while the scrubber still held A, so a click on B's 7:52 row
    moved A's scrubber to A's 10 min frame.

Contract pinned here (live /api path, no ui_mock, replies routed from the
ui_mock replay fixture; A = MOCK_NORMAL_DRAFT_WIN, 15 events, frames at
0/10/20/30 min; B = the Arena row, 3 events, frames at 0/5/10 min):
  - B's match and events replies both pending: 0 rows, count "-", note
    "Loading timeline events...", section shown, list aria-busy, and the
    section keeps A's height (nothing below it moves while B loads), with
    the note filling that held box (centred, not at its top);
  - B's events land, B's match still pending: B's 3 rows are listed, the
    plain note is hidden, aria-busy is gone; a click on B's 7:52 row leaves
    A's scrubber, clock and grid where they were;
  - B's match lands: the same row now seeks B (frame index 2, 10 min);
  - control: an items filter toggle on A (same match, re-fetch pending)
    keeps A's rows and never shows the loading note.
"""
import json
from pathlib import Path

from tests.snapshot_panels.conftest import _WS_STUB

_MOCK = Path(__file__).resolve().parents[2] / "web" / "data" / "ui_mock" / "replay.json"
_ROWS = "#replay-match-list .replay-match-row"
_A = "MOCK_NORMAL_DRAFT_WIN"
_B = "MOCK_ARENA_LOSS_OVERFLOW_LONG_NAME_FOR_ELLIPSIS_TEST"
_LOADING_NOTE = "Loading timeline events..."
_B_LAST_CLOCK = 472  # B's 7:52 event; nearest A frame 10 min, nearest B 10 min

_SETTLE = (
    "() => new Promise((ok) => setTimeout(() =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok)), 150))"
)
_LOADED = (
    "(id) => {"
    " const m = document.getElementById('replay-meta').textContent;"
    " return m.startsWith(id + ' - ') && / - patch /.test(m); }"
)
_LOADING = (
    "(id) => document.getElementById('replay-meta').textContent"
    " === 'loading ' + id + '...'"
)
_COUNT = (
    "(n) => document.getElementById('replay-events-count').textContent"
    " === String(n)"
)

_READ = """() => {
  const empty = document.getElementById('replay-events-empty');
  const section = document.getElementById('replay-events-section');
  const list = document.getElementById('replay-events-list');
  const rows = [...list.querySelectorAll('.replay-events-row')];
  const grid = [...document.querySelectorAll('#replay-grid-body tr')];
  return {
    meta: document.getElementById('replay-meta').textContent,
    rows: rows.length,
    clocks: rows.map((r) => r.getAttribute('data-clock')),
    count: document.getElementById('replay-events-count').textContent,
    sectionHidden: section.hidden,
    sectionH: Math.round(section.getBoundingClientRect().height),
    // the note's bottom gap to the section's content-box bottom (px)
    noteGap: Math.round(section.getBoundingClientRect().bottom
      - parseFloat(getComputedStyle(section).paddingBottom)
      - parseFloat(getComputedStyle(section).borderBottomWidth)
      - empty.getBoundingClientRect().bottom),
    busy: list.getAttribute('aria-busy'),
    emptyShown: !empty.hidden && getComputedStyle(empty).display !== 'none',
    emptyText: empty.textContent.trim(),
    slider: document.getElementById('replay-slider').value,
    clock: document.getElementById('replay-clock').textContent,
    grid: grid.map((r) => r.textContent.replace(/\\s+/g, ' ').trim()).join('|'),
  };
}"""


def _fixture():
    doc = json.loads(_MOCK.read_text(encoding="utf-8"))
    return doc, {m["match_id"]: m for m in doc["matches"]}


def _open(pw_browser, url, hold):
    """The Replay view on the live /api path with replies routed from the
    fixture. hold is a set of keys whose FIRST reply is parked until the
    test releases it: "match:<id>", "events:<id>", "events-include:<id>"
    (an events request carrying an include= filter). Parked replies are
    returned in the dict `held`, keyed the same way."""
    doc, by_id = _fixture()
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    held: dict = {}
    hold = set(hold)

    def _json(route, obj, status=200):
        route.fulfill(status=status, content_type="application/json",
                      body=json.dumps(obj))

    def _maybe_hold(key, fire):
        if key in hold:
            hold.discard(key)
            held[key] = fire
            return
        fire()

    def on_match(route):
        mid = route.request.url.rsplit("/", 1)[-1].split("?")[0]
        _maybe_hold("match:" + mid, lambda: _json(route, by_id.get(mid)))

    def on_events(route):
        url = route.request.url
        mid = url.split("match_id=", 1)[1].split("&")[0]
        hit = by_id.get(mid) or {}
        body = {"ok": True, "events": hit.get("events", []), "you_flagged": []}
        key = ("events-include:" if "include=" in url else "events:") + mid
        _maybe_hold(key, lambda: _json(route, body))

    page.route("**/api/replay/matches*",
               lambda r: _json(r, {"matches": doc["matches"]}))
    page.route("**/api/replay/match/*", on_match)
    page.route("**/api/replay/events*", on_events)
    page.route("**/api/recordings/*", lambda r: _json(r, {"has_video": False}))
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.add_init_script(
        "try { localStorage.removeItem('rc-replay-events-include'); } catch (_) {}")
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
    assert state["slider"] == "0", f"A did not open on frame 0: {state}"
    return state


def _click_ribbon_row(page, clock_s, force=False):
    # force: since S144-U-188 a row that cannot seek is a disabled button,
    # which Playwright's actionability wait would never click; a forced
    # click still lands the real pointer events on it.
    page.locator(
        f'#replay-events-list .replay-events-row[data-clock="{clock_s}"]'
    ).click(force=force)
    page.evaluate(_SETTLE)


def test_a_pending_pick_lists_none_of_the_previous_rows(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, by_id, held = _open(
        pw_browser, mock_server.url, {"match:" + _B, "events:" + _B})
    try:
        a = _load_a(page, by_id)
        _row(page, _B).click()
        page.wait_for_function(_LOADING, arg=_B, timeout=10_000)
        page.evaluate(_SETTLE)
        pending = page.evaluate(_READ)
        assert "events:" + _B in held, "B's events request never arrived"
        held["events:" + _B]()
        page.wait_for_function(_COUNT, arg=len(by_id[_B]["events"]),
                               timeout=10_000)
        page.evaluate(_SETTLE)
        listed = page.evaluate(_READ)
        held["match:" + _B]()
        page.wait_for_function(_LOADED, arg=_B, timeout=10_000)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert pending["rows"] == 0, (
        f"the ribbon lists {pending['rows']} of A's rows under "
        f"'loading B...': {pending}")
    assert pending["count"] == "-", f"the count while loading: {pending}"
    assert not pending["sectionHidden"], f"the section hid: {pending}"
    assert pending["emptyShown"], f"no ribbon note while loading: {pending}"
    assert pending["emptyText"] == _LOADING_NOTE, (
        f"the ribbon note while loading: {pending['emptyText']!r}")
    assert pending["busy"] == "true", f"list not aria-busy: {pending}"
    assert pending["sectionH"] == a["sectionH"], (
        f"the section changed height while B loads: {a['sectionH']} -> "
        f"{pending['sectionH']}")
    assert abs(pending["noteGap"]) <= 1, (
        f"the loading note does not fill the held section (it sits at the "
        f"top over {pending['noteGap']} px of blank space): {pending}")
    assert listed["rows"] == len(by_id[_B]["events"]), listed
    assert not listed["emptyShown"], f"note left behind: {listed}"
    assert listed["busy"] is None, f"aria-busy left behind: {listed}"


def test_a_row_of_a_pending_pick_never_seeks_the_previous_match(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, by_id, held = _open(
        pw_browser, mock_server.url, {"match:" + _B})
    try:
        a = _load_a(page, by_id)
        _row(page, _B).click()
        page.wait_for_function(_COUNT, arg=len(by_id[_B]["events"]),
                               timeout=10_000)
        page.evaluate(_SETTLE)
        _click_ribbon_row(page, _B_LAST_CLOCK, force=True)
        before_load = page.evaluate(_READ)
        held["match:" + _B]()
        page.wait_for_function(_LOADED, arg=_B, timeout=10_000)
        page.evaluate(_SETTLE)
        _click_ribbon_row(page, _B_LAST_CLOCK)
        after_load = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert before_load["meta"] == "loading " + _B + "...", before_load
    assert str(_B_LAST_CLOCK) in before_load["clocks"], before_load
    assert before_load["slider"] == a["slider"], (
        f"B's row moved A's scrubber: {a['slider']} -> "
        f"{before_load['slider']}")
    assert before_load["clock"] == a["clock"], (
        f"B's row moved A's clock: {a['clock']!r} -> "
        f"{before_load['clock']!r}")
    assert before_load["grid"] == a["grid"], "B's row repainted A's grid"
    assert after_load["slider"] == "2", (
        f"B's row does not seek B once B is loaded: {after_load}")


def test_control_a_filter_toggle_keeps_the_rows(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, by_id, held = _open(
        pw_browser, mock_server.url, {"events-include:" + _A})
    try:
        a = _load_a(page, by_id)
        page.locator("#replay-evt-items").check()
        page.evaluate(_SETTLE)
        toggled = page.evaluate(_READ)
        assert "events-include:" + _A in held, "the toggle did not re-fetch"
        held["events-include:" + _A]()
        page.evaluate(_SETTLE)
        _click_ribbon_row(page, 612)
        seeked = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert toggled["rows"] == a["rows"], (
        f"a filter toggle on the same match dropped its rows: {toggled}")
    assert toggled["emptyText"] != _LOADING_NOTE or not toggled["emptyShown"]
    assert seeked["slider"] == "1", (
        f"A's own row does not seek A (10 min frame): {seeked}")
