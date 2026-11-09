"""
tests/snapshot_panels/test_replay_pending_pick_main_pane.py
While a Replay pick is still loading, the scrubber, clock, minimap and grid
must not keep showing the previous pick (s144 lane uiux, S144-U-192; the
U-187 FUTURE row "the scrubber, clock and grid still show A under 'loading
B...' until B's match lands").

Before the fix, _replayLoadMatch (web/js/panels/dev.js) only rewrote the
meta line on a pick. Until B's match reply landed:
  - the scrubber stayed enabled on A's frames, so a drag moved A's clock
    and grid under "loading B...";
  - the clock, the minimap and the 10 rows of A's grid stayed on screen
    under the highlighted row B.

Contract pinned here (live /api path, replies routed from the ui_mock
replay fixture; A = MOCK_NORMAL_DRAFT_WIN, 4 frames of 10 rows, the SR map
shown; B = the Arena row, 3 frames of 2 rows), with B's match reply held:
  - the scrubber is disabled at 0, the clock reads "-", the grid holds one
    note row "loading this match...", and the grid table is aria-busy;
  - a scrubber input event (a drag that reaches the handler) changes none
    of that;
  - the minimap figure stays shown at its own height (so the map row, and
    the grid under it, do not collapse while B loads) with its clock "-",
    no flags and a blank canvas;
  - once B lands: B's meta line, an enabled scrubber with B's 3 frames,
    clock "t = 0.0min", B's 2 grid rows, and no aria-busy.
"""
import copy
import json

from tests.snapshot_panels.test_replay_pending_pick_ribbon import (
    _A, _B, _LOADED, _LOADING, _SETTLE, _row,
)
from tests.snapshot_panels.test_replay_pending_pick_ribbon import (
    _open as _ribbon_open,
)

_LOADING_NOTE = "loading this match..."

_READ = """() => {
  const slider = document.getElementById('replay-slider');
  const body = document.getElementById('replay-grid-body');
  const grid = [...body.querySelectorAll('tr')];
  const fig = document.getElementById('replay-map-figure');
  const canvas = document.getElementById('replay-map-canvas');
  let ink = null;
  try {
    const px = canvas.getContext('2d')
      .getImageData(0, 0, canvas.width, canvas.height).data;
    ink = 0;
    for (let i = 3; i < px.length; i += 4) if (px[i]) ink++;
  } catch (_) { ink = 'tainted'; }
  return {
    meta: document.getElementById('replay-meta').textContent,
    sliderValue: slider.value,
    sliderMax: slider.max,
    sliderDisabled: slider.disabled,
    clock: document.getElementById('replay-clock').textContent,
    rows: grid.length,
    grid: grid.map((r) => r.textContent.replace(/\\s+/g, ' ').trim()),
    busy: body.closest('table').getAttribute('aria-busy'),
    figHidden: fig.hidden,
    mapClock: document.getElementById('replay-map-clock').textContent,
    mapFlags: document.getElementById('replay-map-flags').textContent,
    ink,
    figH: Math.round(fig.getBoundingClientRect().height),
  };
}"""

_DRAG = """() => {
  const s = document.getElementById('replay-slider');
  s.value = '2';
  s.dispatchEvent(new Event('input', { bubbles: true }));
}"""


def _with_positions(match):
    """A copy of a fixture match whose frame entries carry map positions
    (the ui_mock rows store none, so the minimap would stay hidden). Values
    are inside the SR map's 0..14870 world square, team 100 from the
    bottom-left fountain and team 200 from the top-right one; each frame
    gets the timestamp_ms the real store carries (minute x 60 000)."""
    m = copy.deepcopy(match)
    team = {p["participant_id"]: p["team_id"] for p in m["participants"]}
    for i, snap in enumerate(m["snapshots"]):
        snap["timestamp_ms"] = int(snap["minute"] * 60_000)
        for e in snap["entries"]:
            pid = e["participant_id"]
            step = 1500 * i + 120 * (pid % 5)
            e["pos"] = ([560 + step, 580 + step] if team.get(pid) == 100
                        else [14300 - step, 14280 - step])
    return m


def _open(pw_browser, url, hold):
    """The ribbon test's routed Replay view, with A's match reply carrying
    map positions so A's minimap is drawn."""
    ctx, page, errors, by_id, held = _ribbon_open(pw_browser, url, hold)
    a = _with_positions(by_id[_A])
    by_id[_A] = a
    page.route(f"**/api/replay/match/{_A}", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(a)))
    return ctx, page, errors, by_id, held


def _load_a_on_frame_2(page):
    _row(page, _A).click()
    page.wait_for_function(_LOADED, arg=_A, timeout=10_000)
    page.evaluate(_DRAG)
    page.evaluate(_SETTLE)
    a = page.evaluate(_READ)
    assert a["sliderValue"] == "2" and not a["sliderDisabled"], a
    assert a["clock"] == "t = 20.0min", f"A's 20 min frame: {a}"
    assert a["rows"] == 10, f"A's grid did not render: {a}"
    assert not a["figHidden"], f"A's SR map is not shown: {a}"
    assert a["ink"] not in (0, None, "tainted"), f"A's map drew nothing: {a}"
    assert a["mapClock"] == "Map at 20:00", f"A's map clock: {a}"
    assert a["busy"] is None, a
    return a


def test_a_pending_pick_drops_the_previous_match_from_the_main_pane(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, by_id, held = _open(
        pw_browser, mock_server.url, {"match:" + _B})
    try:
        a = _load_a_on_frame_2(page)
        _row(page, _B).click()
        page.wait_for_function(_LOADING, arg=_B, timeout=10_000)
        page.evaluate(_SETTLE)
        pending = page.evaluate(_READ)
        page.evaluate(_DRAG)
        page.evaluate(_SETTLE)
        dragged = page.evaluate(_READ)
        assert "match:" + _B in held, "B's match request never arrived"
        held["match:" + _B]()
        page.wait_for_function(_LOADED, arg=_B, timeout=10_000)
        page.evaluate(_SETTLE)
        loaded = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert pending["meta"] == "loading " + _B + "...", pending
    assert pending["sliderDisabled"], (
        f"A's scrubber stays live under 'loading B...': {pending}")
    assert pending["sliderValue"] == "0", pending
    assert pending["clock"] == "-", (
        f"A's clock stays under 'loading B...': {pending['clock']!r}")
    assert pending["grid"] == [_LOADING_NOTE], (
        f"the grid while B loads: {pending['grid'][:3]} "
        f"({pending['rows']} rows)")
    assert pending["busy"] == "true", f"grid not aria-busy: {pending}"
    assert not pending["figHidden"], (
        f"the map figure hid while B loads (the row reflows): {pending}")
    assert pending["figH"] == a["figH"], (
        f"the map figure changed height while B loads: {a['figH']} -> "
        f"{pending['figH']}")
    assert pending["mapClock"] == "-", pending
    assert pending["mapFlags"] == "", pending
    assert pending["ink"] == 0, (
        f"A's map stays drawn under 'loading B...': {pending['ink']} px")
    for k in ("sliderValue", "clock", "grid", "ink", "busy"):
        assert dragged[k] == pending[k], (
            f"a scrubber input while B loads changed {k}: "
            f"{pending[k]!r} -> {dragged[k]!r}")
    b = by_id[_B]
    assert not loaded["sliderDisabled"], loaded
    assert loaded["sliderMax"] == str(len(b["snapshots"]) - 1), loaded
    assert loaded["sliderValue"] == "0", loaded
    assert loaded["clock"] == "t = 0.0min", loaded
    assert loaded["rows"] == len(b["snapshots"][0]["entries"]), loaded
    assert _LOADING_NOTE not in loaded["grid"], loaded
    assert loaded["busy"] is None, f"aria-busy left behind: {loaded}"
