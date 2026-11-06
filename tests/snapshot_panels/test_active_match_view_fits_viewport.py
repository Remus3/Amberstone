"""
tests/snapshot_panels/test_active_match_view_fits_viewport.py
The dashboard Active Match view fits the window below the header: CALL, BUILD
and MAP all start and end inside the view, the view itself never scrolls, and
the BUILD pane scrolls its own content under a pinned head (s144 lane uiux,
RM-1770).

The view router showed #view-active-match as display: block (header.css), so
.am-grid's own `flex: 1 1 auto; min-height: 0` ("so the three panes flex to
fill the viewport below the header") was inert and the grid was content-sized.
Its content size came from the MAP pane, which spans both rows and whose
shell (height: 100%) and figure (max-height: 50%) are percent heights with no
definite base, so the two 1fr rows inflated (measured, ui_mock, headless):
  - 1920x920: grid 3139 px tall in an 823 px view, rows 1562.55px x 2, the
    BUILD pane top at y = 1680 (760 px below the window), the CALL pane 1563 px
    tall around about 380 px of content; the view scrolled 3189 into 821;
  - aram 2981 / arena 2949 px at 1920x920, sr 3219 px at 1280x720 and 3876 px
    at 923x1280 - in every League mode at every size. TFT (no map figure) fit.

A flex column alone is not the fix: the BUILD pane holds the DS card cluster
(spike curve, matchup, combo, profile...) ABOVE #am-build-body in a pane that
is overflow: hidden, so a definite row squeezed the body to 28 px of its 453
(measured) and its ranks scrolled in a sliver. The BUILD pane therefore
scrolls as a whole, the body keeps its natural height, and the pane head stays
pinned. The overlay shell (body[data-shell="overlay"]) keeps its own layout.

Contract pinned here, ui_mock sr / aram / arena / tft at 1920x920 (the
baseline), 1280x720, 1024x768 and 923x1280:
  - the view does not scroll, and the grid ends inside it;
  - every displayed pane's box lies inside the view (top below the view top,
    bottom above the view bottom), so BUILD is above the fold;
  - #am-build-body is never a scroller squeezed under the cards: its client
    height covers its scroll height;
  - the BUILD pane scrolls when its content is taller than it, and its head
    stays at the pane top after scrolling to the end;
  - a live ARAM balance panel (its third grid row) fits too;
  - under ?overlay=1 the view and the grid stay display: block.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_MEASURE = """() => {
  const q = (s) => document.querySelector(s);
  const box = (e) => { const r = e.getBoundingClientRect();
    return {t: r.top, b: r.bottom, l: r.left, r: r.right, h: r.height}; };
  const shown = (e) => !!e && getComputedStyle(e).display !== 'none'
    && e.getBoundingClientRect().height > 0;
  const view = q('#view-active-match');
  const grid = q('#view-active-match .am-grid');
  const panes = [...grid.children].filter(shown).map(
    (e) => ({name: (e.id || e.className), box: box(e)}));
  const bp = q('#view-active-match .am-pane-build');
  const bb = q('#am-build-body');
  return {
    vh: innerHeight, view: box(view),
    viewScroll: view.scrollHeight - view.clientHeight,
    grid: box(grid), rows: getComputedStyle(grid).gridTemplateRows,
    panes,
    buildPane: {sh: bp.scrollHeight, ch: bp.clientHeight,
                oy: getComputedStyle(bp).overflowY},
    buildBody: {sh: bb.scrollHeight, ch: bb.clientHeight},
  };
}"""

_SIZES = [(1920, 920), (1280, 720), (1024, 768), (923, 1280)]
_MODES = ["sr", "aram", "arena", "tft"]


def _open(pw_browser, mock_server, w, h, query):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": w, "height": h})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    # Deterministic: no live minimap crop and no vision answer (the map
    # figure keeps its no-image box), so only layout is under test.
    page.route("**/api/minimap-crop*", lambda r: r.fulfill(status=404, body=""))
    page.route("**/api/vision-state*", lambda r: r.fulfill(
        status=503, content_type="application/json", body="{}"))
    page.goto(mock_server.url + query, wait_until="domcontentloaded",
              timeout=15_000)
    page.wait_for_function(
        "(() => { const b = document.getElementById('am-build-body');"
        " return !!b && document.body.dataset.view === 'active-match'; })()",
        timeout=10_000)
    # Let the ui_mock fetches land and the panes fill.
    page.wait_for_timeout(900)
    page.evaluate("() => new Promise((r) => requestAnimationFrame("
                  "() => requestAnimationFrame(() => r())))")
    return ctx, page, errors


def _check_fits(m, label):
    view = m["view"]
    assert m["viewScroll"] <= 1, (label, "view scrolls", m["viewScroll"],
                                  m["rows"])
    assert m["grid"]["b"] <= view["b"] + 1, (label, "grid past view",
                                             m["grid"], view)
    assert m["panes"], (label, "no pane displayed")
    for p in m["panes"]:
        b = p["box"]
        assert b["t"] >= view["t"] - 1 and b["b"] <= view["b"] + 1, (
            label, p["name"], b, view)
        assert b["t"] < m["vh"], (label, p["name"], "below the fold", b)
    bb = m["buildBody"]
    assert bb["ch"] >= bb["sh"] - 1, (label, "build body squeezed", bb)
    bp = m["buildPane"]
    if bp["sh"] > bp["ch"] + 1:
        assert bp["oy"] in ("auto", "scroll"), (label, "build pane clips", bp)


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("w,h", _SIZES)
def test_active_match_view_fits_the_window(w, h, mode, mock_server,
                                           pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, w, h,
                              f"/?ui_mock=1&mode={mode}#active-match")
    try:
        m = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    _check_fits(m, (mode, w, h))


_SCROLL_END = """() => {
  const bp = document.querySelector('#view-active-match .am-pane-build');
  const head = bp.querySelector(':scope > .am-pane-head');
  bp.scrollTop = bp.scrollHeight;
  const a = bp.getBoundingClientRect(), b = head.getBoundingClientRect();
  return {scrolled: bp.scrollTop, headTop: b.top, paneTop: a.top,
          headH: b.height, sh: bp.scrollHeight, ch: bp.clientHeight};
}"""


@pytest.mark.parametrize("mode", ["sr", "arena"])
@pytest.mark.parametrize("w,h", [(1920, 920), (1280, 720)])
def test_build_pane_scrolls_under_a_pinned_head(w, h, mode, mock_server,
                                                pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, w, h,
                              f"/?ui_mock=1&mode={mode}#active-match")
    try:
        r = page.evaluate(_SCROLL_END)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    # The fixture BUILD content is taller than its row at these sizes, so
    # the pane must actually scroll (a vacuous pass would read 0 here).
    assert r["sh"] > r["ch"] + 1 and r["scrolled"] > 0, r
    assert abs(r["headTop"] - r["paneTop"]) <= 2.0, r
    assert r["headH"] > 0, r


_ARAM_LIVE = """() => {
  const p = document.getElementById('aram-balance-panel');
  p.hidden = false;
  p.style.display = 'block';
  p.dataset.abState = 'live';
  p.innerHTML = '<div style="height:600px">live balance rows</div>';
}"""


@pytest.mark.parametrize("w,h", [(1920, 920), (1280, 720)])
def test_live_aram_balance_row_fits(w, h, mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, w, h,
                              "/?ui_mock=1&mode=aram#active-match")
    try:
        page.evaluate(_ARAM_LIVE)
        page.evaluate("() => new Promise((r) => requestAnimationFrame("
                      "() => requestAnimationFrame(() => r())))")
        m = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert len(m["rows"].split()) == 3, m["rows"]
    _check_fits(m, ("aram-live", w, h))


def test_overlay_shell_keeps_its_block_layout(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, 1920, 1080,
                              "/?ui_mock=1&mode=sr&overlay=1")
    try:
        r = page.evaluate("""() => ({
          shell: document.body.dataset.shell,
          view: getComputedStyle(document.getElementById('view-active-match'))
                  .display,
          grid: getComputedStyle(document.querySelector(
                  '#view-active-match .am-grid')).display,
          build: getComputedStyle(document.querySelector(
                  '#view-active-match .am-pane-build')).overflowY})""")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert r["shell"] == "overlay", r
    assert r["view"] == "block" and r["grid"] == "block", r
    assert r["build"] != "auto", r
