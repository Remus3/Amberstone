"""
tests/snapshot_panels/test_replay_mock_minimap.py
The Replay ui_mock fixture carries the frame times, map positions and kill
positions the real match store serves, so the past-match minimap draws under
?ui_mock=1 and its "Map at" clock follows the scrubber (s144 lane uiux,
S144-U-193; the U-192 FUTURE row "the ui_mock replay fixture stores no `pos`
and no `timestamp_ms`, so the minimap never draws under ?ui_mock=1 and the
'Map at' clock reads 0:00 at every frame there").

Real shape (core/replay_history.py match_detail): every snapshot carries
`timestamp_ms` (the frame's own ms, a few hundred ms past the minute) with
`minute = round(timestamp_ms / 60000, 1)`; every frame entry carries
`pos` = [x, y] or null; the match carries `kills` = [{timestamp_ms, minute,
killer_id, victim_id, assists, pos}]. The minimap (web/js/panels/
replay_minimap.js buildModel) reads only those three.

Contract pinned here:
  - shape: every snapshot of every match carries an integer timestamp_ms
    whose rounded minute is the snapshot's minute; the SR win carries a
    pos on every frame entry inside the SR world square, team 100 spawning
    at the bottom-left fountain and team 200 at the top-right one, and one
    `kills` row per CHAMPION_KILL ribbon event (same second, killer, victim)
    with a pos; the ranked row keeps NO pos, so the no-positions branch of
    the map stays covered under ui_mock;
  - render at 1920x1080 under ?ui_mock=1: the SR win shows its map, the map
    draws, its clock reads 0:00 / 10:00 / 20:00 / 30:00 as the scrubber
    moves and the drawn map changes between frames, no revive flag is
    raised; a ribbon kill seek puts the map on the kill's own second
    (3:50, 24:48) while the grid shows the nearest frame;
  - the ranked row (no stored positions) hides the map;
  - the defect the refreshed fixture surfaced: where the Timeline wraps
    under the map (923x1280), the map note's line count (2 in the
    first-paint fallback, 3 in the Lato stub and in monospace) moved the
    whole ribbon 18 px on a webfont swap, failing RM-1072's 1 px in
    test_replay_font_swap.py and test_replay_filter_hit_targets.py. The
    note now reserves 3 lines (web/css/panels/primitives.css
    .replay-map-note), pinned below by computed value.
"""
import json
from pathlib import Path

from tests.snapshot_panels.test_replay_review_r30 import _open_replay

_MOCK = Path(__file__).resolve().parents[2] / "web" / "data" / "ui_mock" / "replay.json"
_SR = "MOCK_NORMAL_DRAFT_WIN"
_NO_POS = "MOCK_RANKED_SOLO_WIN_ZERO_KDA"
_SR_WORLD = 14800
# replay_minimap.js FOUNTAIN_FALLBACK.sr and ECHO_TOL_UNITS
_FOUNTAIN = {100: (362, 401), 200: (14321, 14454)}
_TOL = 1500

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
  const fig = document.getElementById('replay-map-figure');
  const canvas = document.getElementById('replay-map-canvas');
  let ink = null, sum = null;
  try {
    const px = canvas.getContext('2d')
      .getImageData(0, 0, canvas.width, canvas.height).data;
    ink = 0; sum = 0;
    for (let i = 0; i < px.length; i += 4) {
      if (px[i + 3]) ink++;
      sum = (sum * 31 + px[i] + 7 * px[i + 1] + 13 * px[i + 2]) % 1000000007;
    }
  } catch (_) { ink = 'tainted'; }
  return {
    figHidden: fig.hidden,
    figH: Math.round(fig.getBoundingClientRect().height),
    ink, sum,
    slider: document.getElementById('replay-slider').value,
    clock: document.getElementById('replay-clock').textContent,
    mapClock: document.getElementById('replay-map-clock').textContent,
    mapFlags: document.getElementById('replay-map-flags').textContent,
  };
}"""
_DRAG = """(v) => {
  const s = document.getElementById('replay-slider');
  s.value = String(v);
  s.dispatchEvent(new Event('input', { bubbles: true }));
}"""


def _matches():
    return {m["match_id"]: m for m in json.loads(_MOCK.read_text("utf-8"))["matches"]}


def _valid_pos(p):
    return (isinstance(p, list) and len(p) == 2
            and all(isinstance(v, int) and 0 <= v <= _SR_WORLD for v in p))


def test_every_snapshot_carries_the_real_frame_time():
    for mid, m in _matches().items():
        assert m["snapshots"], mid
        for s in m["snapshots"]:
            ts = s.get("timestamp_ms")
            assert isinstance(ts, int) and ts >= 0, f"{mid}: {s.get('minute')}"
            assert round(ts / 60000.0, 1) == s["minute"], f"{mid}: {ts}"


def test_the_sr_win_carries_frame_and_kill_positions():
    m = _matches()[_SR]
    team = {p["participant_id"]: p["team_id"] for p in m["participants"]}
    for s in m["snapshots"]:
        assert len(s["entries"]) == 10, s["minute"]
        for e in s["entries"]:
            assert _valid_pos(e.get("pos")), (s["minute"], e)
            if s["timestamp_ms"] == 0:
                fx, fy = _FOUNTAIN[team[e["participant_id"]]]
                x, y = e["pos"]
                assert ((x - fx) ** 2 + (y - fy) ** 2) ** 0.5 <= _TOL, e
    kills = m.get("kills")
    assert isinstance(kills, list) and kills, "no kills rows"
    ribbon = [(e["clock_s"], e["actor"], e["victim"]) for e in m["events"]
              if e["type"] == "CHAMPION_KILL"]
    got = [(k["timestamp_ms"] // 1000, k["killer_id"], k["victim_id"]) for k in kills]
    assert got == ribbon, (got, ribbon)
    for k in kills:
        assert _valid_pos(k.get("pos")), k
        assert k["minute"] == round(k["timestamp_ms"] / 60000.0, 1), k
        assert isinstance(k.get("assists"), list), k


def test_the_ranked_row_keeps_no_positions():
    m = _matches()[_NO_POS]
    assert not m.get("kills")
    for s in m["snapshots"]:
        for e in s["entries"]:
            assert "pos" not in e, e


def _pick(page, mid):
    page.locator(f'#replay-match-list .replay-match-row[data-match-id="{mid}"]').click()
    page.wait_for_function(_LOADED, arg=mid, timeout=10_000)
    page.evaluate(_SETTLE)


def _seek(page, clock_s):
    page.locator(f'.replay-events-row[data-clock="{clock_s}"]').click()
    page.evaluate(_SETTLE)
    return page.evaluate(_READ)


def test_the_mock_minimap_draws_and_follows_the_scrubber(mock_server, pw_browser):
    ctx, page, errors = _open_replay(pw_browser, mock_server)
    try:
        _pick(page, _SR)
        frames = []
        for i in range(4):
            page.evaluate(_DRAG, i)
            page.evaluate(_SETTLE)
            frames.append(page.evaluate(_READ))
        for i, (r, want) in enumerate(zip(frames, ("0:00", "10:00", "20:00", "30:00"))):
            assert not r["figHidden"] and r["figH"] > 0, f"map hidden at frame {i}: {r}"
            assert r["ink"] not in (0, None, "tainted"), f"map drew nothing: {r}"
            assert r["mapClock"] == "Map at " + want, f"frame {i}: {r}"
            assert r["mapFlags"] == "", f"frame {i}: {r}"
        sums = [r["sum"] for r in frames]
        assert len(set(sums)) == 4, f"the map did not change between frames: {sums}"

        a = _seek(page, 230)
        assert a["mapClock"] == "Map at 3:50", a
        assert a["clock"] == "t = 0.0min" and a["slider"] == "0", a
        assert a["mapFlags"] == "", a
        b = _seek(page, 1488)
        assert b["mapClock"] == "Map at 24:48", b
        assert b["clock"] == "t = 20.0min" and b["slider"] == "2", b
        assert b["sum"] != frames[2]["sum"], "the kill seek drew the 20 min frame"

        # The note reserves its 3 lines in every face, so where the Timeline
        # wraps under the map a webfont swap cannot move it (the stacked
        # move itself is pinned by test_replay_font_swap.py and
        # test_replay_filter_hit_targets.py at 923x1280, now that this
        # fixture shows the map).
        note = page.evaluate(
            "() => { const s = getComputedStyle("
            "document.querySelector('.replay-map-note'));"
            " return [parseFloat(s.minHeight), parseFloat(s.lineHeight)]; }")
        # (1/64 px layout rounding: 57.5625 for 3 x 19.2)
        assert abs(note[0] - 3 * note[1]) < 0.1, note

        _pick(page, _NO_POS)
        n = page.evaluate(_READ)
        assert n["figHidden"], f"a match with no stored positions shows a map: {n}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_no_non_ascii_in_this_file():
    raw = Path(__file__).read_bytes()
    assert all(b < 0x80 for b in raw)
    assert b"\r" not in raw
