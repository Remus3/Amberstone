"""
tests/snapshot_panels/test_minimap_canvas_stack_retired.py
S144-U-258 (s144 uiux): the never-rendered canvas stack of the #minimap
panel (the stack div with its 720x720 ZOI and position canvases), the
map_state.js painters that drew into it (the per-pixel ZOI field, the
objective glyphs, the champion dots and ghost rings), the hidden-tab
redraw deferral that existed only to skip that paint, the main.js
visibilitychange flush and the ?map-br / ?map-sat backdrop override are
retired, with the grid.css / map_state.css rules that sized, framed and
faded the stack.

THE DEFECT. The #minimap panel sits in the top-level <main>, which
header.css hides for every VIEW_ID and overlay.css hides in the overlay
shell (S144-U-227, S144-U-246). S144-U-246 gated the paint on a layout
box, so no real view painted, but every state tick still ran the gate and
every tab return could flush a deferred call; and while the tab was
hidden the header zone pill, the function's one visible output, waited
for the tab to come back because the deferral sat in front of it.

KEPT, and pinned here as positive controls so the retirement cannot pass
by breaking a live neighbour:
- the header zone pill and body[data-zone] / body[data-myteam]
  (map_state.js renderMinimapCanvases -> _updateZone, the exported name
  kept so its callers and pins do not move);
- the overlay ZOI canvas #am-zoi-canvas, which carries the shared
  .mm-zoi-canvas class (its grid.css rule stays) and is painted by
  panels/minimap_zoi.js, not by map_state.js;
- the #minimap panel shell and its objective rows.
"""
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

REPO = Path(__file__).resolve().parents[2]

# Names that only the retired parts used, anywhere in web/css, web/js or
# the page. The ZOI class name itself is NOT here: #am-zoi-canvas keeps it.
_NAMES = (
    "mm-canvas-stack", "mm-pos-canvas", 'id="mm-zoi-canvas"',
    '"mm-zoi-canvas")', "_paintMinimapCanvases", "_drawZoi",
    "pendingZoi", "mapFadeIn", "mapFilterOverride", '"map-br"',
    '"map-sat"',
)
# Helpers only the painters used; scoped to map_state.js.
_MAP_STATE_NAMES = ("_dataRGB", "_DATA_SENTINEL", "_rgbCss", "loRes",
                    "getContext(", "createElement(\"canvas\")")


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


def test_map_state_js_keeps_no_painter_helper():
    text = (REPO / "web/js/panels/map_state.js").read_text(encoding="utf-8")
    hits = [n for n in _MAP_STATE_NAMES if n in text]
    assert hits == [], hits


def test_anchor_the_scans_read_real_files():
    # An empty scan would pass both tests above; prove they read the live
    # files by finding the live neighbours of the retired parts.
    files = dict(_live_web_text())
    assert len(files) > 20, len(files)
    html = files["web/index.html"]
    # S144-U-264 retired the #minimap shell; the kept neighbours anchor.
    assert 'id="zone-pill"' in html
    assert 'class="mm-zoi-canvas" id="am-zoi-canvas"' in html
    ms = files["web/js/panels/map_state.js"]
    assert "export function renderMinimapCanvases(" in ms or (
        "function renderMinimapCanvases(" in ms
        and "renderMinimapCanvases," in ms)
    assert "function _updateZone(" in ms
    assert "function _bubbleKernel(" in ms
    assert ".mm-zoi-canvas {" in files["web/css/panels/grid.css"]
    assert 'document.getElementById("am-zoi-canvas")' in files[
        "web/js/panels/minimap_zoi.js"]
    assert "(function setupMinimapPoller()" in files["web/js/main.js"]


_DOM = r"""() => {
  const p = document.getElementById('minimap');
  const am = document.getElementById('am-zoi-canvas');
  return {
    panel: !!p,
    staleness: !!document.querySelector('.staleness[data-for="minimap"]'),
    panelCanvases: p ? p.querySelectorAll('canvas').length : -1,
    retired: document.querySelectorAll(
      '#mm-canvas-stack, #mm-zoi-canvas, #mm-pos-canvas, '
      + '.mm-canvas-stack, .mm-pos-canvas').length,
    amZoi: !!am && am.classList.contains('mm-zoi-canvas'),
  };
}"""


@pytest.mark.parametrize("mode", ["sr", "aram"])
def test_the_served_page_has_no_canvas_stack(mock_server, pw_browser, mode):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + f"/?ui_mock=1&mode={mode}#active-match",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "() => document.body.dataset.view === 'active-match'",
            timeout=10_000)
        got = page.evaluate(_DOM)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    # Positive control: the overlay ZOI canvas (shared class) is still
    # served. S144-U-264 retired the panel shell and its staleness tag
    # (test_minimap_panel_shell_retired.py), so no panel canvas can exist.
    assert got["amZoi"], got
    assert got["panel"] is False and got["staleness"] is False, got
    assert got["retired"] == 0, got
    assert got["panelCanvases"] == -1, got


# Drives renderMinimapCanvases with a deep-enemy value shape (three enemies
# stacked on you, one ally far away) and counts every canvas the call
# creates or opens. `forceShown` forces the #minimap panel on screen, so on
# the pre-fix tree the paint ran (S144-U-264 removed the panel node, so it
# now forces only the hidden <main> on); `tabHidden` reports document.hidden true,
# so on the pre-fix tree the call deferred before the zone pill.
_DRIVE = """async ({forceShown, tabHidden}) => {
  const url = performance.getEntriesByType('resource')
    .map((e) => e.name).find((n) => n.includes('/panels/map_state.js'));
  if (!url) return {err: 'map_state.js not loaded'};
  const m = await import(url);
  if (forceShown) {
    const st = document.createElement('style');
    st.textContent = 'body main, #minimap { display: block !important; }';
    document.head.appendChild(st);
  }
  const counts = {getContext: 0, createCanvas: 0};
  const C = HTMLCanvasElement.prototype;
  const savedGet = C.getContext;
  C.getContext = function (...a) {
    counts.getContext += 1;
    return savedGet.apply(this, a);
  };
  const savedCreate = Document.prototype.createElement;
  Document.prototype.createElement = function (tag, ...rest) {
    if (String(tag).toLowerCase() === 'canvas') counts.createCanvas += 1;
    return savedCreate.call(this, tag, ...rest);
  };
  const hiddenDesc = Object.getOwnPropertyDescriptor(Document.prototype, 'hidden');
  if (tabHidden) {
    Object.defineProperty(document, 'hidden',
      {configurable: true, get: () => true});
  }
  let control = 0;
  const deep = {
    champion: 'Ahri', my_team: 'blue', game_time_s: 900, mode: 'sr',
    positions: {
      allies: {Ahri: {x: 0.80, y: 0.20}, Garen: {x: 0.20, y: 0.80}},
      enemies: {Zed: {x: 0.80, y: 0.20}, Lux: {x: 0.80, y: 0.21},
                Jinx: {x: 0.81, y: 0.20}},
    },
  };
  let threw = null;
  let hiddenSeen = null;
  let paint = null;
  try {
    hiddenSeen = document.hidden;
    m.renderMinimapCanvases(deep);
    paint = {...counts};
    // Positive control: the counters see a canvas made and opened here.
    const before = counts.getContext + counts.createCanvas;
    document.createElement('canvas').getContext('2d');
    control = counts.getContext + counts.createCanvas - before;
  } catch (e) {
    threw = String(e);
  } finally {
    C.getContext = savedGet;
    Document.prototype.createElement = savedCreate;
    if (tabHidden) delete document.hidden;
  }
  const zp = document.getElementById('zone-pill');
  const zl = document.getElementById('zone-label');
  return {
    threw, counts: paint, control, hiddenSeen,
    hiddenRestored: !!hiddenDesc && document.hidden === false,
    pill: String(zp.className), label: zl.textContent,
    zone: document.body.dataset.zone ?? null,
    myteam: document.body.dataset.myteam ?? null,
  };
}"""


def _drive(mock_server, pw_browser, force_shown, tab_hidden):
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
        got = page.evaluate(
            _DRIVE, {"forceShown": force_shown, "tabHidden": tab_hidden})
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert "err" not in got, got
    assert got["threw"] is None, got
    return got


@pytest.fixture(scope="module")
def shown(mock_server, pw_browser):
    return _drive(mock_server, pw_browser, True, False)


@pytest.fixture(scope="module")
def hidden_tab(mock_server, pw_browser):
    return _drive(mock_server, pw_browser, False, True)


def test_positive_control_the_counters_see_a_canvas(shown, hidden_tab):
    assert shown["control"] == 2, shown
    assert hidden_tab["control"] == 2, hidden_tab


def test_a_rendered_panel_gets_no_canvas_work(shown):
    # Pre-fix: the forced-on panel had a box, so the ZOI field made an
    # offscreen canvas and opened both stack canvases every call.
    assert shown["counts"] == {"getContext": 0, "createCanvas": 0}, shown


def test_the_zone_pill_reads_deep_enemy(shown):
    assert "zone-deep" in shown["pill"].split(), shown
    assert "DEEP ENEMY" in shown["label"], shown
    assert shown["zone"] == "deep", shown
    assert shown["myteam"] == "blue", shown


def test_a_hidden_tab_updates_the_zone_pill_at_once(hidden_tab):
    # Anchor: the probe really reported a hidden tab, and put it back.
    assert hidden_tab["hiddenSeen"] is True, hidden_tab
    assert hidden_tab["hiddenRestored"] is True, hidden_tab
    # Pre-fix: the call parked the state for a tab-return flush and left
    # the pill at its "-" placeholder.
    assert "zone-deep" in hidden_tab["pill"].split(), hidden_tab
    assert "DEEP ENEMY" in hidden_tab["label"], hidden_tab
    assert hidden_tab["zone"] == "deep", hidden_tab
    assert hidden_tab["counts"] == {"getContext": 0, "createCanvas": 0}, (
        hidden_tab)
