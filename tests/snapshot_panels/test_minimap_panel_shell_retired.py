"""
tests/snapshot_panels/test_minimap_panel_shell_retired.py
S144-U-264 (s144 uiux): the never-rendered Map State panel SHELL is
retired - the section, its head (title + staleness tag), its empty body,
the MM handle in map_state.js, its row in the main.js CADENCE sweep, its
state.lastTouch / CADENCE keys, the setMode class + title writes and its
grid / zen / narrow-viewport / title CSS.

THE DEFECT. The panel sits in the top-level <main>, which header.css hides
for every VIEW_ID and overlay.css hides in the overlay shell (S144-U-227 /
U-246). Cycles U-254..U-262 retired every part it held, so after U-262 the
panel was an empty shell with no layout box, yet main.js still ran it
through the 500 ms staleness sweep (a textContent + className write on its
badge and a classList remove on its root every tick for the page's life),
renderMinimap stamped state.lastTouch.minimap for that sweep, and setMode
rewrote its className and title on every mode flip. MEASURED headless
before the fix (/?ui_mock=1&mode=sr#active-match, 1920x920): the shell was
served with 0 client rects, with its staleness tag and title node.

THE FIX. The markup, the MM handle and export, the sweep row, the two
state.js keys, both setMode writes and the dead rules go. The three kept
CADENCE panels (right_now / next / item_build) keep their sweep;
renderMinimap keeps its live half (body[data-phase], the header spell pill,
the Active Match item-value bar, the header zone pill).

Positive controls: the kept sweep still ages a kept badge, setMode still
retitles a kept panel, renderMinimap still stamps body[data-phase], and the
CSSOM walk reads a kept panel-title rule.
"""
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

REPO = Path(__file__).resolve().parents[2]
MAP_STATE = REPO / "web/js/panels/map_state.js"

# Names only the retired shell used, anywhere in web/css, web/js or the
# page (comments included).
_NAMES = (
    "panel-minimap", "minimap-body", "mm-panel-title",
    'data-for="minimap"', 'id="minimap"', 'el("minimap")',
    "lastTouch.minimap", "MM.root", "MM.staleness",
)
_CSS_NAMES = ("panel-minimap", "minimap-body", "mm-panel-title")

_DRIVE = r"""async () => {
  const res = performance.getEntriesByType('resource').map((e) => e.name);
  const url = res.find((n) => n.includes('/panels/map_state.js'));
  const surl = res.find((n) => n.includes('/lib/state.js'));
  if (!url || !surl) return {err: 'map_state.js or state.js not loaded'};
  const m = await import(url);
  const s = await import(surl);
  const out = {threw: null};
  out.panel = !!document.getElementById('minimap');
  out.badge = !!document.querySelector('.staleness[data-for="minimap"]');
  out.title = !!document.getElementById('mm-panel-title');
  out.classNode = !!document.querySelector('.panel-minimap');
  out.exportsMM = ('MM' in m);
  out.touchKeys = Object.keys(s.state.lastTouch).sort();
  out.cadenceKeys = Object.keys(s.CADENCE).sort();
  out.mode = document.body.dataset.mode;
  out.rnTitle = (document.getElementById('rn-panel-title') || {}).textContent;
  try {
    m.renderMinimap({game_time_s: 1000, game_time: '16:40'});
  } catch (e) {
    out.threw = String(e);
  }
  out.phase = document.body.dataset.phase ?? null;
  out.touchKeysAfter = Object.keys(s.state.lastTouch).sort();
  // The kept sweep: age a kept panel past its stale bound and read its
  // badge after the next 500 ms tick.
  s.state.lastTouch.right_now = Date.now() / 1000 - 6;
  await new Promise((r) => setTimeout(r, 1100));
  const rb = document.querySelector('.staleness[data-for="right-now"]');
  out.rnBadge = rb ? rb.textContent : null;
  out.rnBadgeClass = rb ? rb.className : null;
  out.rnRootStale = document.getElementById('right-now')
    .classList.contains('stale');
  out.mainIds = Array.from(document.querySelectorAll('body > main > section'))
    .map((e) => e.id);
  // CSSOM walk through dashboard.css's @import chain.
  out.rules = [];
  out.sheets = 0;
  out.keptTitleRule = false;
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
        if (t.includes('.panel-right-now .panel-title')) out.keptTitleRule = true;
      }
    };
    walk(rules);
  };
  for (const sheet of document.styleSheets) walkSheet(sheet);
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
            "() => document.body.dataset.view === 'active-match'"
            " && !!document.body.dataset.mode",
            timeout=10_000)
        js = _DRIVE.replace(
            "%NAMES%", "[" + ", ".join(repr(n) for n in _CSS_NAMES) + "]")
        got = page.evaluate(js)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert "err" not in got, got
    return got


def test_the_shell_is_not_served(drive):
    assert drive["panel"] is False, drive
    assert drive["badge"] is False, drive
    assert drive["title"] is False, drive
    assert drive["classNode"] is False, drive


def test_main_keeps_the_four_other_panels_in_order(drive):
    assert drive["mainIds"] == ["right-now", "next", "item-build",
                                "adaptation"], drive


def test_map_state_exports_no_shell_handle(drive):
    assert drive["exportsMM"] is False, drive


def test_the_sweep_keys_drop_the_shell(drive):
    kept = ["item_build", "next", "right_now"]
    assert drive["touchKeys"] == kept, drive
    assert drive["cadenceKeys"] == kept, drive
    # renderMinimap no longer stamps a key for the retired sweep row.
    assert drive["touchKeysAfter"] == kept, drive


def test_positive_control_render_minimap_keeps_its_live_half(drive):
    assert drive["threw"] is None, drive
    assert drive["phase"] == "mid", drive


def test_positive_control_the_kept_sweep_still_ages_a_badge(drive):
    assert drive["rnBadgeClass"] == "staleness stale", drive
    assert drive["rnBadge"] in ("6s", "7s"), drive
    assert drive["rnRootStale"] is True, drive


def test_positive_control_set_mode_still_retitles_a_kept_panel(drive):
    # The page has no game behind it, so the health envelope stamps
    # "client"; setMode's title block then writes the client title over
    # the markup's RIGHT NOW. Either way the title follows the mode.
    in_game = drive["mode"] in ("sr", "aram", "arena", "brawl", "tft")
    want = "RIGHT NOW" if in_game else "SESSION SUMMARY"
    assert drive["rnTitle"] == want, drive


def test_the_served_cssom_holds_no_rule_for_the_shell(drive):
    assert drive["sheets"] > 5, drive
    assert drive["rules"] == [], drive


def test_counter_control_the_cssom_walk_reads_a_kept_title_rule(drive):
    assert drive["keptTitleRule"] is True, drive


def _live_web_text():
    out = []
    for sub, pat in (("web/css", "*.css"), ("web/js", "*.js")):
        for p in sorted((REPO / sub).rglob(pat)):
            out.append((p.relative_to(REPO).as_posix(),
                        p.read_text(encoding="utf-8")))
    out.append(("web/index.html",
                (REPO / "web/index.html").read_text(encoding="utf-8")))
    return out


def test_no_stylesheet_script_or_page_still_names_the_shell():
    hits = [(rel, n) for rel, text in _live_web_text()
            for n in _NAMES if n in text]
    assert hits == [], hits


def test_anchor_the_name_scan_reads_real_files():
    # An empty scan would pass the scan above; prove it reads the live
    # files by finding the shell's live neighbours.
    files = dict(_live_web_text())
    assert len(files) > 20, len(files)
    html = files["web/index.html"]
    assert 'id="right-now"' in html
    assert 'data-for="right-now"' in html
    assert 'id="rn-panel-title"' in html
    main_js = files["web/js/main.js"]
    assert '["right_now",  RN.staleness, RN.root],' in main_js
    assert 'el("rn-panel-title")' in main_js
    assert ".panel-right-now  .panel-title" in files[
        "web/css/panels/map_state.css"]
    assert "function renderMinimap(p)" in MAP_STATE.read_text(
        encoding="utf-8")
