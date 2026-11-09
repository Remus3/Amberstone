"""
tests/snapshot_panels/test_game_clock_state_retired.py
S144-U-267 (s144 uiux): the write-only `state.gameClock` slot and the
`_updateGameClock` wrapper that fed it are retired; renderMinimap stamps
body[data-phase] straight from `game_time_s`.

THE DEFECT. map_state.js created `state.gameClock = {startedAt, anchorS,
raw}` at module load and `_updateGameClock` rewrote it on every state
envelope (renderMinimap), yet no byte of web/js, web/index.html, tools/ or
tests/ ever read it (git grep): its only consumer was the Map State game
time chip, retired 2026-04-23 (S144-U-261 removed the last guarded write).
main.js also imported `_updateGameClock` and `_applyGamePhase` without
calling either. map_state.js also assigned `state.spellCds = {}` twice at
module load; the second assignment (beside the spell-cooldown helpers)
was kept, then S144-U-268 dropped it too, since lib/state.js already
creates state.spellCds. MEASURED headless before the fix
(/?ui_mock=1&mode=sr#active-match, 1920x920): `state.gameClock` was present
and renderMinimap({game_time_s: 1000, game_time: '16:40'}) rewrote it to
anchorS 1000 / raw '16:40'.

THE FIX. The slot, the wrapper, its export and main.js's two unused import
names go; renderMinimap calls `_applyGamePhase(game_time_s)` when the field
is a number, the same gate the wrapper used.

Positive controls: renderMinimap still stamps body[data-phase] for a
numeric game_time_s (early / mid / late), leaves the phase alone when the
field is absent or a string, and still feeds the spell-cooldown tracker
(state.spellCds), so the retirement cannot pass by breaking renderMinimap.
"""
import re
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

REPO = Path(__file__).resolve().parents[2]
MAP_STATE = REPO / "web/js/panels/map_state.js"
MAIN_JS = REPO / "web/js/main.js"

_NAMES = ("gameClock", "_updateGameClock")

_DRIVE = r"""async () => {
  const res = performance.getEntriesByType('resource').map((e) => e.name);
  const murl = res.find((n) => n.includes('/panels/map_state.js'));
  const surl = res.find((n) => n.includes('/lib/state.js'));
  if (!murl || !surl) return {err: 'map_state.js or state.js not loaded'};
  const m = await import(murl);
  const s = await import(surl);
  const out = {threw: null};
  out.exports = Object.keys(m).sort();
  out.hasSlotBefore = Object.prototype.hasOwnProperty.call(
    s.state, 'gameClock');
  const phases = [];
  try {
    m.renderMinimap({game_time_s: 1000, game_time: '16:40'});
    phases.push(document.body.dataset.phase ?? null);
    m.renderMinimap({game_time_s: 300, game_time: '5:00'});
    phases.push(document.body.dataset.phase ?? null);
    // Absent / non-numeric game_time_s leaves the phase where it was.
    m.renderMinimap({game_time: '40:00'});
    phases.push(document.body.dataset.phase ?? null);
    m.renderMinimap({game_time_s: '1600', game_time: '26:40'});
    phases.push(document.body.dataset.phase ?? null);
    m.renderMinimap({game_time_s: 1600, game_time: '26:40',
      ally_spells: {Jinx: [{spell: 'Flash', cd_remaining_s: 120}]}});
    phases.push(document.body.dataset.phase ?? null);
  } catch (e) {
    out.threw = String(e);
  }
  out.phases = phases;
  out.hasSlotAfter = Object.prototype.hasOwnProperty.call(
    s.state, 'gameClock');
  out.spellKeys = Object.keys(s.state.spellCds || {});
  return out;
}"""


@pytest.fixture(scope="module")
def drive(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 920}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url + "/?ui_mock=1&mode=sr#active-match",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "() => document.body.dataset.view === 'active-match'",
            timeout=10_000)
        got = page.evaluate(_DRIVE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert "err" not in got, got
    return got


def test_state_holds_no_game_clock_slot(drive):
    assert drive["hasSlotBefore"] is False, drive
    assert drive["hasSlotAfter"] is False, drive


def test_map_state_no_longer_exports_the_wrapper(drive):
    assert "_updateGameClock" not in drive["exports"], drive
    # Counter-control: the export list is real (the kept test seam).
    assert {"renderMinimap", "_applyGamePhase"} <= set(drive["exports"]), drive


def test_positive_control_render_minimap_still_stamps_the_phase(drive):
    assert drive["threw"] is None, drive
    # mid (1000 s), early (300 s), held on absent, held on a string,
    # late (1600 s).
    assert drive["phases"] == ["mid", "early", "early", "early", "late"], drive


def test_positive_control_render_minimap_still_feeds_spell_cds(drive):
    assert drive["spellKeys"] == ["Jinx|Flash"], drive


def test_map_state_js_never_reassigns_spell_cds():
    # S144-U-268: lib/state.js creates state.spellCds; map_state.js only
    # reads and writes its keys.
    text = MAP_STATE.read_text(encoding="utf-8")
    assert len(re.findall(r"^state\.spellCds\s*=", text, re.M)) == 0
    assert "state.spellCds[key]" in text


def test_main_js_imports_no_unused_map_state_clock_names():
    text = MAIN_JS.read_text(encoding="utf-8")
    m = re.search(r"^import \{([^}]*)\} from '\./panels/map_state\.js';",
                  text, re.M)
    assert m, "main.js map_state import line not found"
    names = {n.strip() for n in m.group(1).split(",") if n.strip()}
    assert "renderMinimap" in names, names  # anchor: the line is the real one
    assert not names & {"_updateGameClock", "_applyGamePhase"}, names


def test_no_script_or_page_names_the_retired_slot():
    hits = []
    files = sorted((REPO / "web/js").rglob("*.js"))
    files.append(REPO / "web/index.html")
    for p in files:
        text = p.read_text(encoding="utf-8")
        for n in _NAMES:
            if n in text:
                hits.append(f"{p.relative_to(REPO).as_posix()}: {n}")
    # Anchor: the scan really read map_state.js (an empty walk would pass).
    assert MAP_STATE in files and len(files) > 50, len(files)
    assert hits == [], hits
