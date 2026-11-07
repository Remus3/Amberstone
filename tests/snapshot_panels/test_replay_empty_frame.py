"""
tests/snapshot_panels/test_replay_empty_frame.py
A Replay frame that carries no player rows must say so in the grid, not leave
a bare header over an empty body (s144 lane uiux, S144-U-185; the U-184 FUTURE
row "a frame with zero `entries` (the ui_mock ARAM row) renders an empty grid
body with no note").

core/replay_history.py builds one entry per stored participant for every
frame, so a frame with zero entries is a match stored with frames but no
participant rows. The ui_mock fixture carries one (MOCK_ARAM_NEUTRAL, one frame,
`entries: []`). Before the fix, _replayRenderSnapshot (web/js/panels/dev.js)
emptied #replay-grid-body and appended nothing: the meta line and the frame
clock named the match while the grid under them was a header row and blank
space, the same look as a view that has not painted yet.

Contract pinned here:
  - ui_mock, pick MOCK_ARAM_NEUTRAL: the meta line names it, the clock reads
    the frame time ("t = 0.0min"), the grid holds exactly the one note row
    "no player rows stored for this frame", and that note stays a table cell
    spanning the grid;
  - live /api path, a match whose second frame has no entries (the fixture's
    MOCK_NORMAL_DRAFT_WIN with snapshots[1].entries emptied): scrubbing to
    frame 1 shows the note in place of frame 0's ten rows, scrubbing back to
    frame 0 brings the ten rows back with no note left behind;
  - control: frame 0 of that match renders its ten rows and no note;
  - audit MUST-FIX, pre-existing: at 480 px and under the scoreboard keeps
    its 414 px table and scrolls sideways inside .replay-grid-wrap (RM-1777),
    and the note sat centred across that whole table, so "no player rows
    stored for this frame" ran 23 px past the 348 px pane at 480 and "no
    match selected" (page open) ran 96 px past the 188 px pane at 320; the
    sigil sat off-view too. At 1920, 720, 480, 360 and 320 both notes, with
    their sigil, now sit inside the visible pane, centred in it.
"""
import json
from pathlib import Path

from tests.snapshot_panels.conftest import _WS_STUB

_MOCK = Path(__file__).resolve().parents[2] / "web" / "data" / "ui_mock" / "replay.json"
_ROWS = "#replay-match-list .replay-match-row"
_EMPTY = "MOCK_ARAM_NEUTRAL"
_MIXED = "MOCK_NORMAL_DRAFT_WIN"
_NOTE = "no player rows stored for this frame"

_SETTLE = (
    "() => new Promise((ok) => setTimeout(() =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok)), 150))"
)
_LOADED = (
    "(id) => {"
    " const m = document.getElementById('replay-meta').textContent;"
    " return m.startsWith(id + ' - ') && / - patch /.test(m); }"
)
_SCRUB = """(i) => {
  const s = document.getElementById('replay-slider');
  s.value = String(i);
  s.dispatchEvent(new Event('input', { bubbles: true }));
}"""

_READ = """() => {
  const notes = [...document.querySelectorAll('#replay-grid-body td.home-empty')];
  const td = notes[0] || null;
  const head = document.querySelector('.replay-grid thead tr');
  return {
    meta: document.getElementById('replay-meta').textContent,
    clock: document.getElementById('replay-clock').textContent,
    champs: [...document.querySelectorAll(
      '#replay-grid-body .replay-col-champ span')].map((s) => s.textContent),
    gridRows: [...document.querySelectorAll('#replay-grid-body tr')]
      .map((tr) => tr.textContent.trim()),
    noteCount: notes.length,
    note: td ? {
      display: getComputedStyle(td).display,
      colSpan: td.colSpan,
      span: td.getBoundingClientRect().width
        / head.getBoundingClientRect().width,
    } : null,
  };
}"""


def _fixture():
    doc = json.loads(_MOCK.read_text(encoding="utf-8"))
    return doc, {m["match_id"]: m for m in doc["matches"]}


def _assert_note_spans_the_grid(state, where):
    note = state["note"]
    assert note is not None, f"{where}: no note cell: {state}"
    assert note["display"] == "table-cell", (
        f"{where}: the note cell left table layout: {note}")
    assert note["colSpan"] == 7, f"{where}: the note does not span 7: {note}"
    assert note["span"] > 0.95, (
        f"{where}: the note cell does not span the grid: {note}")


def test_ui_mock_frame_with_no_entries_says_so(mock_server, pw_browser):
    mock_server._store["data"] = {}
    _doc, by_id = _fixture()
    # Anchor: the fixture row this contract rests on really is frame-full and
    # entry-empty, so a fixture edit cannot turn this into a no-frames test.
    snaps = by_id[_EMPTY]["snapshots"]
    assert len(snaps) == 1 and snaps[0]["entries"] == [], snaps
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + "/?ui_mock=1#replay",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_selector(_ROWS, timeout=10_000)
        page.locator(f'{_ROWS}[data-match-id="{_EMPTY}"]').click()
        page.wait_for_function(_LOADED, arg=_EMPTY, timeout=10_000)
        page.evaluate(_SETTLE)
        state = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert state["clock"] == "t = 0.0min", f"the frame clock: {state}"
    assert state["gridRows"] == [_NOTE], (
        f"the entry-less frame's grid: {state['gridRows']}")
    _assert_note_spans_the_grid(state, "ui_mock ARAM frame")


def test_scrubbing_onto_and_off_an_empty_frame(mock_server, pw_browser):
    mock_server._store["data"] = {}
    doc, by_id = _fixture()
    mixed = json.loads(json.dumps(by_id[_MIXED]))
    assert len(mixed["snapshots"]) >= 2 and mixed["snapshots"][0]["entries"]
    mixed["snapshots"][1]["entries"] = []
    want = sorted(p["champion_name"] for p in mixed["participants"])
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)

    def _json(route, obj, status=200):
        route.fulfill(status=status, content_type="application/json",
                      body=json.dumps(obj))

    def on_match(route):
        mid = route.request.url.rsplit("/", 1)[-1].split("?")[0]
        _json(route, mixed if mid == _MIXED else by_id.get(mid))

    page.route("**/api/replay/matches*",
               lambda r: _json(r, {"matches": doc["matches"]}))
    page.route("**/api/replay/match/*", on_match)
    page.route("**/api/replay/events*",
               lambda r: _json(r, {"ok": True, "events": [], "you_flagged": []}))
    page.route("**/api/recordings/*", lambda r: _json(r, {"has_video": False}))
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + "/#replay", wait_until="domcontentloaded",
                  timeout=15_000)
        page.wait_for_selector(_ROWS, timeout=10_000)
        page.locator(f'{_ROWS}[data-match-id="{_MIXED}"]').click()
        page.wait_for_function(_LOADED, arg=_MIXED, timeout=10_000)
        page.evaluate(_SETTLE)
        frame0 = page.evaluate(_READ)
        page.evaluate(_SCRUB, 1)
        page.evaluate(_SETTLE)
        frame1 = page.evaluate(_READ)
        page.evaluate(_SCRUB, 0)
        page.evaluate(_SETTLE)
        back = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    # Control: frame 0 is a real grid with no note.
    assert sorted(frame0["champs"]) == want, f"frame 0: {frame0}"
    assert frame0["noteCount"] == 0, f"frame 0 carries a note: {frame0}"
    want_clock = f"t = {mixed['snapshots'][1]['minute']:.1f}min"
    assert frame1["clock"] == want_clock, f"frame 1 clock: {frame1}"
    assert frame1["gridRows"] == [_NOTE], (
        f"the empty frame's grid: {frame1['gridRows']}")
    _assert_note_spans_the_grid(frame1, "scrubbed to the empty frame")
    assert sorted(back["champs"]) == want, f"back on frame 0: {back}"
    assert back["noteCount"] == 0, f"the note stayed on frame 0: {back}"


_FIT = """() => {
  const td = document.querySelector('#replay-grid-body td.home-empty');
  const wrap = document.querySelector('.replay-grid-wrap');
  const w = wrap.getBoundingClientRect();
  const cs = getComputedStyle(wrap);
  const left = w.left + parseFloat(cs.borderLeftWidth);
  const right = left + wrap.clientWidth;
  const rg = document.createRange();
  rg.selectNodeContents(td);
  const t = rg.getBoundingClientRect();
  const holder = td.querySelector('.replay-grid-note') || td;
  const sig = getComputedStyle(holder, '::before');
  const h = holder.getBoundingClientRect();
  return {
    text: td.textContent.trim(),
    textL: t.left - left, textR: right - t.right,
    holderL: h.left - left, holderR: right - h.right,
    sigil: sig.content,
    visibleW: right - left,
  };
}"""


def test_grid_notes_sit_inside_the_visible_pane_down_to_320(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    seen = {}
    errors: list[str] = []
    for width in (1920, 720, 480, 360, 320):
        ctx = pw_browser.new_context(ignore_https_errors=True,
                                     viewport={"width": width, "height": 900})
        page = ctx.new_page()
        page.add_init_script(_WS_STUB)
        page.on("pageerror", lambda err: errors.append(str(err)))
        try:
            page.goto(mock_server.url + "/?ui_mock=1#replay",
                      wait_until="domcontentloaded", timeout=15_000)
            page.wait_for_selector(_ROWS, timeout=10_000)
            page.evaluate(_SETTLE)
            opened = page.evaluate(_FIT)
            page.locator(f'{_ROWS}[data-match-id="{_EMPTY}"]').click()
            page.wait_for_function(_LOADED, arg=_EMPTY, timeout=10_000)
            page.evaluate(_SETTLE)
            empty = page.evaluate(_FIT)
        finally:
            ctx.close()
        seen[width] = (opened, empty)
    assert not errors, f"page errors: {errors[:3]}"
    for width, (opened, empty) in seen.items():
        assert opened["text"] == "no match selected", (width, opened)
        assert empty["text"] == _NOTE, (width, empty)
        for state in (opened, empty):
            where = f"{width} px, {state['text']!r}"
            assert state["textL"] >= 0 and state["textR"] >= 0, (
                f"{where}: the note runs past the visible pane: {state}")
            assert abs(state["textL"] - state["textR"]) <= 2, (
                f"{where}: the note is not centred in the pane: {state}")
            assert state["sigil"] not in ("none", "normal"), (
                f"{where}: the note lost its sigil: {state}")
            assert state["holderL"] >= -1 and state["holderR"] >= -1, (
                f"{where}: the sigil box runs past the pane: {state}")
