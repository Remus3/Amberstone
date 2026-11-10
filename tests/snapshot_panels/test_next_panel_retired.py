"""
tests/snapshot_panels/test_next_panel_retired.py
S144-U-265 (s144 uiux): the never-rendered NEXT panel is retired - the
section, its head (title + staleness tag), its four coach rows, the module
that painted them (web/js/panels/next.js), its row in the main.js CADENCE
sweep, its state.lastTouch / CADENCE keys, the setMode title write and its
grid / zen / narrow-viewport / title / headline / wave-state CSS.

THE DEFECT. The panel sits in the top-level <main>, which header.css hides
for every VIEW_ID (RM-1552) and overlay.css hides in the overlay shell
(`main > .panel`, only #right-now is lifted out for its three widget
mounts). No view ever shows it, yet on every state envelope main.js ran the
whole module over the coach payload (four textContent writes, a 3-lane
wave-state innerHTML rebuild in SR, the kv condense pass), the 500 ms
staleness sweep wrote its badge and its root class for the page's life, and
setMode rewrote its title on every mode flip. RM-896 / RM-898 had to add a
B4 client mirror to the module because its hidden headline HELD a live SR
imperative in the DOM; the sink itself is now gone. MEASURED headless
before the fix (/?ui_mock=1&mode=sr#active-match, 1920x920): the panel was
served with 0 client rects and the module was loaded.

THE FIX. The markup, the module, its main.js import / render call / sweep
row / title write, the two state.js keys and the dead rules go. The two
kept CADENCE panels (right_now / item_build) keep their sweep; the RM-898
first-tick probes in test_tft_active_match_view.py now read the kept RIGHT
NOW sink, which reads the coach through the same B4 mirror.

Positive controls: the kept sweep still ages a kept badge, setMode still
retitles a kept panel, the CSSOM walk reads a kept panel-title rule and the
kept RIGHT NOW kv rule, and the name scan finds the panel's live neighbours.
"""
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

REPO = Path(__file__).resolve().parents[2]

# Names only the retired panel used, anywhere in web/css, web/js or the
# page (comments included).
_NAMES = (
    "panel-next", "nx-panel-title", "nx-next", "nx-objective",
    "nx-positioning", "nx-wave", 'data-for="next"', 'el("next")',
    "lastTouch.next", "renderNext(", "panels/next.js", "action-mid",
    "NX.staleness", "NX.root", "wave-line", "wave-verb",
)
_CSS_NAMES = ("panel-next", "nx-wave", "action-mid", "wave-line",
              "wave-pct", "wave-verb", "wave-marker")

_DRIVE = r"""async () => {
  const res = performance.getEntriesByType('resource').map((e) => e.name);
  const surl = res.find((n) => n.includes('/lib/state.js'));
  if (!surl) return {err: 'state.js not loaded'};
  const s = await import(surl);
  const out = {};
  out.nextModuleLoaded = res.some((n) => /\/panels\/next\.js(\?|$)/.test(n));
  out.nextBuyLoaded = res.some((n) => n.includes('/panels/next_buy.js'));
  out.panel = !!document.getElementById('next');
  out.badge = !!document.querySelector('.staleness[data-for="next"]');
  out.title = !!document.getElementById('nx-panel-title');
  out.head = !!document.getElementById('nx-next');
  out.wave = !!document.getElementById('nx-wave');
  out.classNode = !!document.querySelector('.panel-next');
  out.touchKeys = Object.keys(s.state.lastTouch).sort();
  out.cadenceKeys = Object.keys(s.CADENCE).sort();
  out.mode = document.body.dataset.mode;
  out.rnTitle = (document.getElementById('rn-panel-title') || {}).textContent;
  // The kept sweep: age a kept panel past its stale bound and read its
  // badge after the next 500 ms tick.
  s.state.lastTouch.right_now = Date.now() / 1000 - 6;
  await new Promise((r) => setTimeout(r, 1100));
  const rb = document.querySelector('.staleness[data-for="right-now"]');
  out.rnBadge = rb ? rb.textContent : null;
  out.rnBadgeClass = rb ? rb.className : null;
  out.rnRootStale = document.getElementById('right-now')
    .classList.contains('stale');
  out.touchKeysAfter = Object.keys(s.state.lastTouch).sort();
  out.mainIds = Array.from(document.querySelectorAll('body > main > section'))
    .map((e) => e.id);
  // CSSOM walk through dashboard.css's @import chain.
  out.rules = [];
  out.sheets = 0;
  out.keptTitleRule = false;
  out.keptRnKvRule = false;
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
        if (t === '.panel-right-now .kv > span:last-child') out.keptRnKvRule = true;
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


def test_the_panel_is_not_served(drive):
    assert drive["panel"] is False, drive
    assert drive["badge"] is False, drive
    assert drive["title"] is False, drive
    assert drive["head"] is False, drive
    assert drive["wave"] is False, drive
    assert drive["classNode"] is False, drive


def test_the_panel_module_is_not_loaded(drive):
    assert drive["nextModuleLoaded"] is False, drive


def test_counter_control_the_resource_scan_sees_a_sibling_panel(drive):
    # An empty resource list would pass the check above.
    assert drive["nextBuyLoaded"] is True, drive


def test_main_keeps_the_three_other_panels_in_order(drive):
    assert drive["mainIds"] == ["right-now", "item-build", "adaptation"], drive


def test_the_sweep_keys_drop_the_panel(drive):
    kept = ["item_build", "right_now"]
    assert drive["touchKeys"] == kept, drive
    assert drive["cadenceKeys"] == kept, drive
    # No state tick re-stamps a key for the retired sweep row.
    assert drive["touchKeysAfter"] == kept, drive


def test_positive_control_the_kept_sweep_still_ages_a_badge(drive):
    assert drive["rnBadgeClass"] == "staleness stale", drive
    assert drive["rnBadge"] in ("6s", "7s"), drive
    assert drive["rnRootStale"] is True, drive


def test_positive_control_set_mode_still_retitles_a_kept_panel(drive):
    in_game = drive["mode"] in ("sr", "aram", "arena", "brawl", "tft")
    want = "RIGHT NOW" if in_game else "SESSION SUMMARY"
    assert drive["rnTitle"] == want, drive


def test_the_served_cssom_holds_no_rule_for_the_panel(drive):
    assert drive["sheets"] > 5, drive
    assert drive["rules"] == [], drive


def test_counter_control_the_cssom_walk_reads_kept_rules(drive):
    assert drive["keptTitleRule"] is True, drive
    assert drive["keptRnKvRule"] is True, drive


def _live_web_text():
    out = []
    for sub, pat in (("web/css", "*.css"), ("web/js", "*.js")):
        for p in sorted((REPO / sub).rglob(pat)):
            out.append((p.relative_to(REPO).as_posix(),
                        p.read_text(encoding="utf-8")))
    out.append(("web/index.html",
                (REPO / "web/index.html").read_text(encoding="utf-8")))
    return out


def test_the_panel_module_file_is_gone():
    assert not (REPO / "web/js/panels/next.js").exists()


def test_no_stylesheet_script_or_page_still_names_the_panel():
    hits = [(rel, n) for rel, text in _live_web_text()
            for n in _NAMES if n in text]
    assert hits == [], hits


def test_anchor_the_name_scan_reads_real_files():
    # An empty scan would pass the scan above; prove it reads the live
    # files by finding the panel's live neighbours.
    files = dict(_live_web_text())
    assert len(files) > 20, len(files)
    html = files["web/index.html"]
    assert 'id="right-now"' in html
    assert 'data-for="item-build"' in html
    main_js = files["web/js/main.js"]
    assert '["right_now",  RN.staleness, RN.root],' in main_js
    assert '["item_build", IB.staleness, IB.root],' in main_js
    assert "renderRightNow(p);" in main_js
    assert ".panel-right-now .kv > span:last-child {" in files[
        "web/css/panels/next.css"]
