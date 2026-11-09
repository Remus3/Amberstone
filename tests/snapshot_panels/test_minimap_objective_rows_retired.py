"""
tests/snapshot_panels/test_minimap_objective_rows_retired.py
S144-U-262 (s144 uiux): the never-rendered Map State objective rows
(#mm-objectives-view: Dragon / Baron / Herald), their 1 s countdown tick
and the CSS that styled them are retired.

THE DEFECT. The rows sit in the #minimap panel, which renders in no view
(it is in the top-level <main>, hidden for every VIEW_ID and in the overlay
shell - S144-U-227 / U-246), yet every state envelope stored the objective
text on all three rows and map_state.js ran a module-level 1 s interval for
the page's life that re-parsed that text, rewrote each row's textContent,
toggled its obj-soon / obj-up classes and lazily created an .obj-bar child
for it - all on nodes with no layout box. item_build.css and grid.css kept
the rules for those rows (.kv-with-icon, the #mm-dragon / baron / herald /
atakhan tints and countdown cues, .minimap-grid, the .obj-bar fill) and for
the tower / score chip row removed 2026-04-23 (.mm-chips / .mm-chip);
map_state.css kept three #mm-objectives-view mode hides. MEASURED headless
before the fix (/?ui_mock=1&mode=sr#active-match, 1920x920): the rows were
served with 0 client rects, map_state.js registered 2 intervals (the spell
cooldown tick and the objective tick), and one second of the tick after a
renderMinimap call mutated the rows.

THE FIX. The markup, the tick and its helpers (_tickObjectiveCountdowns,
_extractSpawnTime, _OBJ_CYCLE, _kindOf, _currentGameTimeS), the three MM
slots, renderMinimap's raw-text writes and the dead rules are removed.
The live overlay objective chips (web/js/panels/objective_chips.js) keep
their own spawn cycle and are untouched.

KEPT, and pinned as positive controls: the #minimap shell with its
staleness tag (MM.root / MM.staleness feed the CADENCE sweep), the spell
cooldown tick that feeds the header summoner-spell pill, renderMinimap's
live half (body[data-phase], state.lastTouch.minimap), the shared .obj-ico
rule the header vision pill uses.
"""
import re
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

REPO = Path(__file__).resolve().parents[2]
MAP_STATE = REPO / "web/js/panels/map_state.js"

_ROW_SEL = (
    "#mm-objectives-view, #mm-dragon, #mm-baron, #mm-herald, #mm-atakhan, "
    ".minimap-grid, .kv-with-icon, .obj-bar, .mm-chips, .mm-chip"
)

# Names that only the retired rows, tick and rules used.
_NAMES = (
    "mm-objectives-view", "mm-dragon", "mm-baron", "mm-herald", "mm-atakhan",
    "kv-with-icon", "minimap-grid", "obj-bar", "obj-soon", "obj-up",
    "mm-chip", "_tickObjectiveCountdowns", "_extractSpawnTime", "_OBJ_CYCLE",
    "_kindOf", "_currentGameTimeS",
)

# Records every setInterval whose caller is map_state.js, from page start.
_INTERVAL_SPY = r"""(() => {
  const orig = window.setInterval;
  window.__mmIntervals = 0;
  window.setInterval = function () {
    const st = String(new Error().stack || '');
    if (st.includes('/panels/map_state.js')) window.__mmIntervals += 1;
    return orig.apply(this, arguments);
  };
})();"""

_DRIVE = r"""async () => {
  const res = performance.getEntriesByType('resource').map((e) => e.name);
  const url = res.find((n) => n.includes('/panels/map_state.js'));
  const surl = res.find((n) => n.includes('/lib/state.js'));
  if (!url || !surl) return {err: 'map_state.js or state.js not loaded'};
  const m = await import(url);
  const s = await import(surl);
  const sel = %SEL%;
  const out = {threw: null, intervals: window.__mmIntervals};
  out.before = document.querySelectorAll(sel).length;
  out.rowRects = Array.from(document.querySelectorAll(sel))
    .reduce((n, e) => n + e.getClientRects().length, 0);
  out.panel = !!document.getElementById('minimap');
  out.staleness = !!document.querySelector('.staleness[data-for="minimap"]');
  out.exportsTick = ('_tickObjectiveCountdowns' in m);
  out.exportsSpellTick = (typeof m._tickSpellCooldowns === 'function');
  s.state.lastTouch.minimap = 0;
  // Count only records whose target is (inside) a retired row node.
  out.rowMutations = 0;
  const obs = new MutationObserver((list) => {
    for (const rec of list) {
      const t = rec.target.nodeType === 1
        ? rec.target : rec.target.parentElement;
      if (t && t.closest(sel)) out.rowMutations += 1;
    }
  });
  obs.observe(document.body,
    {subtree: true, childList: true, characterData: true, attributes: true,
     attributeFilter: ['class', 'data-raw', 'style']});
  try {
    m.renderMinimap({
      game_time_s: 1000, game_time: '16:40',
      dragon_state: 'Dragon spawns 17:30',
      baron_state: 'Baron next 20:00',
      herald_state: 'Herald in 16:50',
    });
  } catch (e) {
    out.threw = String(e);
  }
  await new Promise((r) => setTimeout(r, 1250));
  obs.disconnect();
  out.phase = document.body.dataset.phase ?? null;
  out.touched = s.state.lastTouch.minimap > 0;
  // CSSOM walk through dashboard.css's @import chain.
  out.rules = [];
  out.sheets = 0;
  out.visPillRule = false;
  const seen = new Set();
  const names = %NAMES%;
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
        const t = r.selectorText || '';
        if (names.some((n) => t.includes(n))) out.rules.push(t);
        if (t.includes('.vis-pill .obj-ico')) out.visPillRule = true;
      }
    };
    walk(rules);
  };
  for (const sheet of document.styleSheets) walkSheet(sheet);
  return out;
}"""


def _drive_js() -> str:
    css_names = [n for n in _NAMES if not n.startswith("_")]
    return (_DRIVE.replace("%SEL%", repr(_ROW_SEL))
            .replace("%NAMES%", "[" + ", ".join(repr(n) for n in css_names)
                     + "]"))


@pytest.fixture(scope="module", params=["sr", "aram"])
def drive(request, mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 920}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.add_init_script(_INTERVAL_SPY)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url
            + f"/?ui_mock=1&mode={request.param}#active-match",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "() => document.body.dataset.view === 'active-match'",
            timeout=10_000)
        got = page.evaluate(_drive_js())
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert "err" not in got, got
    return got


def test_the_objective_rows_are_not_served(drive):
    assert drive["before"] == 0, drive


def test_the_objective_tick_is_gone_and_mutates_nothing(drive):
    assert drive["threw"] is None, drive
    assert drive["exportsTick"] is False, drive
    assert drive["rowMutations"] == 0, drive
    # One interval left in map_state.js: the spell cooldown tick.
    assert drive["intervals"] == 1, drive


def test_the_served_cssom_holds_no_rule_for_the_retired_rows(drive):
    assert drive["sheets"] > 5, drive
    assert drive["rules"] == [], drive


def test_counter_control_the_cssom_walk_reads_the_kept_icon_rule(drive):
    # The header vision pill keeps .obj-ico; an unread CSSOM would also
    # report no retired rule.
    assert drive["visPillRule"] is True, drive


def test_positive_control_the_shell_and_live_half_stay(drive):
    assert drive["panel"] and drive["staleness"], drive
    assert drive["exportsSpellTick"] is True, drive
    assert drive["phase"] == "mid", drive
    assert drive["touched"] is True, drive


def _live_web_text():
    out = []
    for sub, pat in (("web/css", "*.css"), ("web/js", "*.js")):
        for p in sorted((REPO / sub).rglob(pat)):
            out.append((p.relative_to(REPO).as_posix(),
                        p.read_text(encoding="utf-8")))
    out.append(("web/index.html",
                (REPO / "web/index.html").read_text(encoding="utf-8")))
    return out


def test_no_stylesheet_script_or_page_still_names_the_retired_parts():
    hits = [(rel, n) for rel, text in _live_web_text()
            for n in _NAMES if n in text]
    assert hits == [], hits


def test_map_state_js_keeps_no_objective_slot():
    text = MAP_STATE.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(dragon|baron|herald)\s*:\s*el\(", text,
                         re.M), "a retired MM slot is back"


def test_anchor_the_name_scan_reads_real_files():
    # An empty scan would pass the scan above; prove it reads the live
    # files by finding the live neighbours of the retired parts.
    files = dict(_live_web_text())
    assert len(files) > 20, len(files)
    html = files["web/index.html"]
    assert 'id="minimap"' in html
    assert 'data-for="minimap"' in html
    assert 'class="obj-ico"' in html
    ms = files["web/js/panels/map_state.js"]
    assert "setInterval(_tickSpellCooldowns, 1000);" in ms
    assert "function renderMinimap(p)" in ms
    assert ".vis-pill .obj-ico" in files["web/css/panels/header.css"]
    assert "const OBJ_CYCLE = {" in files["web/js/panels/objective_chips.js"]
