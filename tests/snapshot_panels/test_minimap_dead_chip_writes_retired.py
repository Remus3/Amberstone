"""
tests/snapshot_panels/test_minimap_dead_chip_writes_retired.py
S144-U-261 (s144 uiux): the guarded writes to the Map State tower / team
score / game time chips (#mm-towers, #mm-score, #mm-gametime) and the three
item_build.css `.kv:has(#mm-...)` icon-tint rules for them are retired.

THE DEFECT. Those three chips were removed from the Map State panel on
2026-04-23 (their signals live on header row 2), but map_state.js kept
looking them up at module load (MM.towers / MM.score / MM.gameTime), kept a
null-guarded write branch for each in renderMinimap, kept a null-guarded
game-time write in the 1 s countdown tick, and item_build.css kept three
unscoped `.kv:has(#mm-towers|score|gametime) .obj-ico` rules, which every
style recalc of a .kv row still tests. No index.html, JS template or
other stylesheet has created any of the three ids since (git grep of the
tree). MEASURED headless before the fix (/?ui_mock=1&mode=sr#active-match,
1920x920): 0 nodes carry any of the ids, while the served CSSOM held 3
rules whose selector named them.

THE FIX. The three MM slots, both write sites and the three CSS rules are
removed; the renderMinimap comment no longer lists the fields only they
read. The 1 s tick keeps the objective countdowns.

The positive controls pin the live half of the same calls: renderMinimap
still sets body[data-phase] from game_time_s (the game-clock update) and
still stores the objective raw text on #mm-dragon, so the retirement cannot
pass by breaking renderMinimap.
"""
import re
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

REPO = Path(__file__).resolve().parents[2]
MAP_STATE = REPO / "web/js/panels/map_state.js"
ITEM_BUILD = REPO / "web/css/panels/item_build.css"

_IDS = ("mm-towers", "mm-score", "mm-gametime")

_DRIVE = r"""async () => {
  const url = performance.getEntriesByType('resource')
    .map((e) => e.name).find((n) => n.includes('/panels/map_state.js'));
  if (!url) return {err: 'map_state.js not loaded'};
  const m = await import(url);
  const ids = ['mm-towers', 'mm-score', 'mm-gametime'];
  const out = {threw: null};
  out.rules = [];
  out.sheets = 0;
  // dashboard.css pulls the panel sheets in through @import, so the walk
  // follows each import rule's own sheet as well as grouping rules.
  const seen = new Set();
  const walkSheet = (sheet) => {
    if (!sheet || seen.has(sheet)) return;
    seen.add(sheet);
    let rules;
    try { rules = sheet.cssRules; } catch (e) { return; }
    out.sheets += 1;
    const walk = (list) => {
      for (const r of list) {
        if (r.styleSheet) walkSheet(r.styleSheet);
        if (r.cssRules) walk(r.cssRules);
        const sel = r.selectorText || '';
        if (ids.some((id) => sel.includes('#' + id))) out.rules.push(sel);
        if (sel.includes('#mm-dragon')) out.dragonRules = true;
      }
    };
    walk(rules);
  };
  for (const sheet of document.styleSheets) walkSheet(sheet);
  const p = {
    game_time_s: 1000, game_time: '16:40',
    towers_us: 3, towers_them: 5, kda_aggregate: '12-8',
    dragon_state: 'Dragon spawns 20:00',
  };
  try {
    m.renderMinimap(p);
    m.renderMinimap(p);
  } catch (e) {
    out.threw = String(e);
  }
  out.nodes = document.querySelectorAll(
    ids.map((id) => '#' + id).join(', ')).length;
  out.phase = document.body.dataset.phase ?? null;
  out.dragonRaw = (document.getElementById('mm-dragon') || {dataset: {}})
    .dataset.raw ?? null;
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


def test_the_served_cssom_holds_no_rule_for_the_removed_chips(drive):
    assert drive["sheets"] > 5, drive
    assert drive["rules"] == [], drive


def test_counter_control_the_cssom_walk_reads_the_objective_rules(drive):
    # The walk above would pass on an unread CSSOM; prove it reads the
    # live item_build.css rules that name the kept objective rows.
    assert drive.get("dragonRules") is True, drive


def test_no_node_carries_a_removed_chip_id(drive):
    assert drive["threw"] is None, drive
    assert drive["nodes"] == 0, drive


def test_positive_control_render_minimap_keeps_its_live_half(drive):
    assert drive["phase"] == "mid", drive
    assert drive["dragonRaw"] == "Dragon spawns 20:00", drive


def test_map_state_js_no_longer_looks_up_or_writes_the_chips():
    text = MAP_STATE.read_text(encoding="utf-8")
    hits = [n for n in _IDS + ("MM.towers", "MM.score", "MM.gameTime")
            if n in text]
    assert hits == [], hits
    assert not re.search(r"^\s*(towers|score|gameTime)\s*:\s*el\(", text,
                         re.M), "a removed MM slot is back"


def test_no_stylesheet_script_or_page_names_the_removed_chips():
    hits = []
    for sub, pat in (("web/css", "*.css"), ("web/js", "*.js")):
        for p in sorted((REPO / sub).rglob(pat)):
            text = p.read_text(encoding="utf-8")
            hits += [(p.relative_to(REPO).as_posix(), i)
                     for i in _IDS if i in text]
    html = (REPO / "web/index.html").read_text(encoding="utf-8")
    hits += [("web/index.html", i) for i in _IDS if i in html]
    assert hits == [], hits


def test_anchor_the_scans_read_the_live_neighbours():
    js = MAP_STATE.read_text(encoding="utf-8")
    css = ITEM_BUILD.read_text(encoding="utf-8")
    html = (REPO / "web/index.html").read_text(encoding="utf-8")
    assert 'dragon: el("mm-dragon")' in js
    assert "_tickObjectiveCountdowns();" in js
    assert "function renderMinimap(p)" in js
    assert ".kv:has(#mm-dragon)  .obj-ico" in css
    assert 'id="mm-dragon"' in html
