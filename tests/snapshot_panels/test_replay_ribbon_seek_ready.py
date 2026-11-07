"""
tests/snapshot_panels/test_replay_ribbon_seek_ready.py
A Replay Timeline row that cannot seek is a disabled button, and the ribbon
says why (s144 lane uiux, S144-U-188; the U-187 FUTURE row "B's rows that
land before B's match are listed, but a click on one does nothing until the
match loads, and nothing on screen says so").

The ribbon (web/js/panels/replay_events.js) and the match reply
(web/js/panels/dev.js _replayLoadMatch) come from two routes. Since U-187 a
row of a match the scrubber does not hold yet does not seek, but before this
fix it still looked and acted like a live control: pointer cursor, hover
fill, a tab stop, "Jump the scrubber to 7:52" on hover, and a click that did
nothing with nothing on screen saying why. The same held for every row of a
match stored with no timeline frames (U-184), whose scrubber has nothing to
seek.

Contract pinned here (live /api path, replies routed from the ui_mock
replay fixture; A = MOCK_NORMAL_DRAFT_WIN, B = the Arena row, 3 events,
frames at 0/5/10 min):
  - B's events land, B's match still pending: every row is a disabled
    button (cursor default, out of the tab order), the hint above the list
    reads the pending text and is drawn between the head and the list, in
    --text-dim at >= 4.5:1 on the section's resolved background;
  - B's match lands: the SAME row nodes are enabled in place (no rebuild,
    so nothing focused is thrown), the hint hides, a row seeks B;
  - B's match lands with no timeline frames: the rows stay disabled and the
    hint says there are no frames;
  - a pick that empties the ribbon (B pending with its hint up, then
    MOCK_ARAM_NEUTRAL, 0 events, its match also pending) drops the hint
    with the rows (verifier MUST-FIX: the empty branch kept it);
  - control: A loaded the usual way has enabled rows and no hint.
"""
import json

from tests.snapshot_panels.test_replay_pending_pick_ribbon import (
    _B,
    _B_LAST_CLOCK,
    _COUNT,
    _LOADED,
    _LOADING,
    _SETTLE,
    _load_a,
    _open,
    _row,
)

_HINT_PENDING = "These rows jump the scrubber once the match loads."
_HINT_NOFRAMES = ("No timeline frames are stored for this match, so these "
                  "rows cannot jump the scrubber.")

_STATE = """() => {
  const hint = document.getElementById('replay-events-hint');
  const list = document.getElementById('replay-events-list');
  const head = document.querySelector('#replay-events-section .replay-events-head');
  const rows = [...list.querySelectorAll('.replay-events-row')];
  const hr = hint.getBoundingClientRect();
  return {
    meta: document.getElementById('replay-meta').textContent,
    rows: rows.length,
    disabled: rows.filter((r) => r.disabled).length,
    tabbable: rows.filter((r) => r.tabIndex >= 0 && !r.disabled).length,
    cursors: [...new Set(rows.map((r) => getComputedStyle(r).cursor))],
    marked: rows.filter((r) => r.__u188 === 1).length,
    hintShown: !hint.hidden && getComputedStyle(hint).display !== 'none'
      && hr.height > 0,
    hintText: hint.textContent,
    hintBelowHead: hr.top >= head.getBoundingClientRect().bottom - 1,
    hintAboveList: hr.bottom <= list.getBoundingClientRect().top + 1,
    slider: document.getElementById('replay-slider').value,
  };
}"""

# Resolved sRGB of a computed colour (oklch / color-mix included) via a
# 1x1 canvas, then the WCAG ratio of the hint text on the section fill.
_CONTRAST = """() => {
  const cv = document.createElement('canvas');
  cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgb = (c) => {
    cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c;
    cx.fillRect(0, 0, 1, 1);
    return [...cx.getImageData(0, 0, 1, 1).data].slice(0, 3);
  };
  const lum = (v) => {
    const f = v.map((x) => { x /= 255;
      return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); });
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2];
  };
  const hint = document.getElementById('replay-events-hint');
  const sec = document.getElementById('replay-events-section');
  const fg = lum(rgb(getComputedStyle(hint).color));
  const bg = lum(rgb(getComputedStyle(sec).backgroundColor));
  return (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
}"""

_MARK = """() => document.querySelectorAll(
  '#replay-events-list .replay-events-row').forEach((r) => { r.__u188 = 1; })"""


def _pick_b_events_first(page, by_id):
    _row(page, _B).click()
    page.wait_for_function(_LOADING, arg=_B, timeout=10_000)
    page.wait_for_function(_COUNT, arg=len(by_id[_B]["events"]),
                           timeout=10_000)
    page.evaluate(_SETTLE)


def test_rows_of_a_match_still_loading_are_disabled_and_say_why(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, by_id, held = _open(
        pw_browser, mock_server.url, {"match:" + _B})
    try:
        _load_a(page, by_id)
        _pick_b_events_first(page, by_id)
        pending = page.evaluate(_STATE)
        ratio = page.evaluate(_CONTRAST)
        page.evaluate(_MARK)
        held["match:" + _B]()
        page.wait_for_function(_LOADED, arg=_B, timeout=10_000)
        page.evaluate(_SETTLE)
        loaded = page.evaluate(_STATE)
        page.locator(
            '#replay-events-list .replay-events-row'
            f'[data-clock="{_B_LAST_CLOCK}"]').click()
        page.evaluate(_SETTLE)
        seeked = page.evaluate(_STATE)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    n = len(by_id[_B]["events"])
    assert pending["meta"] == "loading " + _B + "...", pending
    assert pending["rows"] == n, pending
    assert pending["disabled"] == n, (
        f"rows of a match the scrubber does not hold are live: {pending}")
    assert pending["tabbable"] == 0, pending
    assert pending["cursors"] == ["default"], pending
    assert pending["hintShown"], f"no hint over rows that cannot seek: {pending}"
    assert pending["hintText"] == _HINT_PENDING, pending
    assert pending["hintBelowHead"] and pending["hintAboveList"], pending
    assert ratio >= 4.5, f"hint on the section fill is {ratio:.2f}:1"
    assert loaded["disabled"] == 0, f"rows stay disabled once B loads: {loaded}"
    assert loaded["marked"] == n, (
        f"the rows were rebuilt, not enabled in place: {loaded}")
    assert loaded["cursors"] == ["pointer"], loaded
    assert not loaded["hintShown"], f"hint left behind: {loaded}"
    assert seeked["slider"] == "2", f"B's row does not seek B: {seeked}"


def test_rows_of_a_match_with_no_frames_are_disabled_and_say_why(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, by_id, held = _open(pw_browser, mock_server.url, set())
    frameless = dict(by_id[_B], snapshots=[])
    try:
        page.route(
            f"**/api/replay/match/{_B}",
            lambda r: r.fulfill(status=200, content_type="application/json",
                                body=json.dumps(frameless)))
        _load_a(page, by_id)
        _row(page, _B).click()
        page.wait_for_function(_LOADED, arg=_B, timeout=10_000)
        page.wait_for_function(_COUNT, arg=len(by_id[_B]["events"]),
                               timeout=10_000)
        page.evaluate(_SETTLE)
        state = page.evaluate(_STATE)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    n = len(by_id[_B]["events"])
    assert state["rows"] == n, state
    assert state["disabled"] == n, (
        f"rows of a frame-less match look seekable: {state}")
    assert state["hintShown"] and state["hintText"] == _HINT_NOFRAMES, state


def test_a_pick_that_empties_the_ribbon_drops_the_hint(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    empty_pick = "MOCK_ARAM_NEUTRAL"
    ctx, page, errors, by_id, held = _open(
        pw_browser, mock_server.url, {"match:" + _B, "match:" + empty_pick})
    try:
        _load_a(page, by_id)
        _pick_b_events_first(page, by_id)
        with_rows = page.evaluate(_STATE)
        _row(page, empty_pick).click()
        page.wait_for_function(_LOADING, arg=empty_pick, timeout=10_000)
        page.wait_for_function(_COUNT, arg=0, timeout=10_000)
        page.evaluate(_SETTLE)
        emptied = page.evaluate(_STATE)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert by_id[empty_pick]["events"] == [], "fixture drifted"
    assert with_rows["hintShown"], f"precondition: B's hint: {with_rows}"
    assert emptied["rows"] == 0, emptied
    assert not emptied["hintShown"] and emptied["hintText"] == "", (
        f"the hint talks about rows that are gone: {emptied}")


def test_control_a_loaded_match_has_live_rows_and_no_hint(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors, by_id, held = _open(pw_browser, mock_server.url, set())
    try:
        _load_a(page, by_id)
        state = page.evaluate(_STATE)
    finally:
        ctx.close()
    assert not errors, f"page errors: {errors[:3]}"
    assert state["rows"] > 0 and state["disabled"] == 0, state
    assert state["tabbable"] == state["rows"], state
    assert not state["hintShown"] and state["hintText"] == "", state
