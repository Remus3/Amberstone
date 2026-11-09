"""
tests/snapshot_panels/test_replay_kill_seek_exact_ms.py
A Timeline kill row puts the Replay minimap on the kill's own millisecond,
so the map shows the victim dead at the moment the row names (s144 lane
uiux, S144-U-195; the U-193 FUTURE row "a ribbon seek uses clock_s * 1000,
which lands before a kill's own ms (230000 < 230254), so at the seek moment
the victim is not yet dead on the map - live behaviour too").

Before: the ribbon row carried only data-clock (whole seconds) and
_replaySeekToClock (web/js/panels/dev.js) set the map to clock_s * 1000.
The minimap (web/js/panels/replay_minimap.js) opens a death window at the
kill's own timestamp_ms, so every kill seek landed 0-999 ms before it: on
the ui_mock SR win all five kill rows showed the victim alive (no death
cross) and the killer at its last frame instead of at the kill spot.

Contract pinned here (?ui_mock=1, 1920x1080, the SR win):
  - fixture: every CHAMPION_KILL ribbon event carries timestamp_ms equal
    to its `kills` row's timestamp_ms (real, copied with the kills by
    U-193), with clock_s == timestamp_ms // 1000;
  - each kill row carries data-ms = that timestamp_ms; a row whose event
    has no timestamp_ms carries no data-ms;
  - a click (and an Enter) on a kill row sets the map to the kill's own
    ms (the canvas data-t-ms), and at that moment the pure model shows the
    victim dead at the kill spot; the map clock still reads the row's
    m:ss and the grid shows the nearest frame;
  - a row with no data-ms still seeks on its clock (clock_s * 1000), and
    that draws a different map from the exact-ms seek (the victim is not
    yet dead there), so the precision is what changes the drawing.
"""
import json
from pathlib import Path

from tests.snapshot_panels.test_replay_review_r30 import _open_replay

_MOCK = Path(__file__).resolve().parents[2] / "web" / "data" / "ui_mock" / "replay.json"
_SR = "MOCK_NORMAL_DRAFT_WIN"

_SETTLE = (
    "() => new Promise((ok) => setTimeout(() =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok)), 150))"
)
_LOADED = (
    "(id) => {"
    " const m = document.getElementById('replay-meta').textContent;"
    " return m.startsWith(id + ' - ') && / - patch /.test(m); }"
)
_READ = """() => {
  const canvas = document.getElementById('replay-map-canvas');
  let sum = 0;
  const px = canvas.getContext('2d')
    .getImageData(0, 0, canvas.width, canvas.height).data;
  for (let i = 0; i < px.length; i += 4) {
    sum = (sum * 31 + px[i] + 7 * px[i + 1] + 13 * px[i + 2]) % 1000000007;
  }
  return {
    tMs: canvas.dataset.tMs === undefined ? null : Number(canvas.dataset.tMs),
    sum,
    slider: document.getElementById('replay-slider').value,
    mapClock: document.getElementById('replay-map-clock').textContent,
  };
}"""
# The pure minimap model over the fixture match: is `victim` dead at `t`,
# and where is the death cross drawn.
_STATE = """async ([mid, victim, t]) => {
  const mm = await import('/js/panels/replay_minimap.js');
  const r = await fetch('/data/ui_mock/replay.json', { cache: 'no-store' });
  const d = (await r.json()).matches.find((m) => m.match_id === mid);
  const s = mm.stateAt(mm.buildModel(d), victim, t);
  return { dead: !!s.dead, deathPos: s.deathPos || null };
}"""


def _sr():
    for m in json.loads(_MOCK.read_text("utf-8"))["matches"]:
        if m["match_id"] == _SR:
            return m
    raise AssertionError(f"{_SR} missing from the fixture")


def _kill_events():
    return [e for e in _sr()["events"] if e["type"] == "CHAMPION_KILL"]


def test_every_kill_event_carries_its_kill_rows_ms():
    m = _sr()
    kills = {(k["timestamp_ms"] // 1000, k["killer_id"], k["victim_id"]): k
             for k in m["kills"]}
    evs = _kill_events()
    assert len(evs) == len(kills) == 5, (len(evs), len(kills))
    for e in evs:
        k = kills[(e["clock_s"], e["actor"], e["victim"])]
        assert e.get("timestamp_ms") == k["timestamp_ms"], (e, k)
        assert e["clock_s"] == e["timestamp_ms"] // 1000, e


def _open_sr(pw_browser, mock_server):
    ctx, page, errors = _open_replay(pw_browser, mock_server)
    page.locator(
        f'#replay-match-list .replay-match-row[data-match-id="{_SR}"]').click()
    page.wait_for_function(_LOADED, arg=_SR, timeout=10_000)
    page.wait_for_selector(".replay-events-row:not([disabled])",
                           timeout=10_000)
    page.evaluate(_SETTLE)
    return ctx, page, errors


def _row(page, clock_s):
    return page.locator(f'.replay-events-row[data-clock="{clock_s}"]')


def test_kill_rows_carry_their_ms(mock_server, pw_browser):
    ctx, page, errors = _open_sr(pw_browser, mock_server)
    try:
        rows = page.evaluate(
            "() => [...document.querySelectorAll('.replay-events-row')]"
            ".map((b) => [Number(b.dataset.clock),"
            " b.hasAttribute('data-ms') ? Number(b.dataset.ms) : null])")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
    want = {e["clock_s"]: e.get("timestamp_ms") for e in _sr()["events"]}
    assert len(rows) == len(want), rows
    for clock, ms in rows:
        assert ms == want[clock], (clock, ms, want[clock])


def test_a_kill_row_puts_the_map_on_the_kill_ms(mock_server, pw_browser):
    ctx, page, errors = _open_sr(pw_browser, mock_server)
    try:
        for i, e in enumerate(_kill_events()):
            row = _row(page, e["clock_s"])
            if i % 2:
                row.focus()
                page.keyboard.press("Enter")
            else:
                row.click()
            page.evaluate(_SETTLE)
            r = page.evaluate(_READ)
            mm, ss = divmod(e["clock_s"], 60)
            assert r["tMs"] == e["timestamp_ms"], (e, r)
            assert r["mapClock"] == f"Map at {mm}:{ss:02d}", (e, r)
            st = page.evaluate(_STATE, [_SR, e["victim"], r["tMs"]])
            k = next(k for k in _sr()["kills"]
                     if k["timestamp_ms"] == e["timestamp_ms"])
            assert st["dead"], f"victim {e['victim']} alive at {r['tMs']}: {st}"
            assert st["deathPos"] == k["pos"], (st, k)
            # The grid shows the frame nearest the kill (frames 10 min apart).
            want_idx = round(e["timestamp_ms"] / 600000)
            assert r["slider"] == str(want_idx), (e, r)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_row_without_ms_seeks_on_its_clock(mock_server, pw_browser):
    first = _kill_events()[0]
    ctx, page, errors = _open_sr(pw_browser, mock_server)
    try:
        _row(page, first["clock_s"]).click()
        page.evaluate(_SETTLE)
        exact = page.evaluate(_READ)
        page.evaluate(
            "(c) => document.querySelector("
            "`.replay-events-row[data-clock=\"${c}\"]`)"
            ".removeAttribute('data-ms')", first["clock_s"])
        _row(page, first["clock_s"]).click()
        page.evaluate(_SETTLE)
        coarse = page.evaluate(_READ)
        st = page.evaluate(_STATE, [_SR, first["victim"], coarse["tMs"]])
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
    assert exact["tMs"] == first["timestamp_ms"], exact
    assert coarse["tMs"] == first["clock_s"] * 1000, coarse
    assert coarse["mapClock"] == exact["mapClock"], (coarse, exact)
    assert not st["dead"], st
    assert coarse["sum"] != exact["sum"], (
        "the exact-ms seek drew the same map as the whole-second one")


def test_no_non_ascii_in_this_file():
    raw = Path(__file__).read_bytes()
    assert all(b < 0x80 for b in raw)
    assert b"\r" not in raw
