"""
tests/snapshot_panels/test_active_match_narrow_reflow.py
At 720 px and under (300% zoom of the 1920x920 baseline is 640 wide, 400% is
480; WCAG 1.4.10 reflows at 320) the dashboard Active Match view stacks its
panes in ONE full-width column and the view section scrolls them as a page,
instead of squeezing the two desktop columns (s144 lane uiux, RM-1772).

Measured before the fix (ui_mock, headless Chromium):
  - the 1.4fr / 1.6fr columns held at every width: 258 / 294 px at 640,
    183 / 209 at 480, 127 / 145 at 360;
  - the BUILD pane content needs 205 px, so at 480 and 360 it scrolled
    SIDEWAYS inside its own vertical scroller (scrollWidth 205 in a
    clientWidth of 181 / 125);
  - the combo action input was 54 px wide at 640 and 12 px at 480 and 360,
    beside a 176 px keystone select;
  - at 360 and 320 the view head's sub line ran past the view, so the
    section scrolled sideways (scrollWidth 359 in 322).

Contract pinned here, ui_mock sr / aram / arena / tft at 640x900, 480x800,
360x740 and 320x640:
  - the grid is one column and every displayed pane spans its full width;
  - the panes run CALL, BUILD, MAP top to bottom without overlapping;
  - neither the document nor the view scrolls sideways, and no element in
    the view reaches past the view's content box;
  - the BUILD pane is not a scroller of its own (a nested scroller in a
    scrolling page traps the wheel and the touch drag), and its head stays
    pinned at the view top while the page scrolls through it;
  - the combo action input keeps most of its row and the hit floor;
  - a live ARAM balance row sits between BUILD and MAP at full width.
Above the line the two columns stay (722x900, the 923x1280 companion; the
1920x920 baseline is pinned by test_active_match_view_fits_viewport.py), and
the overlay shell keeps its own block layout.
"""
import pytest

from tests.snapshot_panels.test_active_match_view_fits_viewport import (
    _ARAM_LIVE,
    _open,
)

_MEASURE = """() => {
  const q = (s) => document.querySelector(s);
  const box = (e) => { const r = e.getBoundingClientRect();
    return {t: r.top, b: r.bottom, l: r.left, r: r.right, w: r.width,
            h: r.height}; };
  const shown = (e) => !!e && getComputedStyle(e).display !== 'none'
    && e.getBoundingClientRect().height > 0;
  const view = q('#view-active-match');
  const grid = q('#view-active-match .am-grid');
  const vr = view.getBoundingClientRect();
  const lim = vr.left + view.clientLeft + view.clientWidth;
  const past = [];
  for (const d of view.querySelectorAll('*')) {
    if (getComputedStyle(d).display === 'none') continue;
    const r = d.getBoundingClientRect();
    if (r.width > 0 && r.right > lim + 1) {
      past.push([d.id || String(d.className).slice(0, 40), r.right, lim]);
    }
  }
  const panes = {};
  for (const e of [...grid.children].filter(shown)) {
    const k = e.id === 'aram-balance-panel' ? 'aram'
      : (e.className.match(/am-pane-(call|build|map)/) || [])[1];
    if (k) panes[k] = box(e);
  }
  const bp = q('#view-active-match .am-pane-build');
  const inp = q('#view-active-match .dscombo-input');
  const row = q('#view-active-match .dscombo-input-row');
  return {
    docSW: document.documentElement.scrollWidth, iw: innerWidth,
    view: {sw: view.scrollWidth, cw: view.clientWidth},
    cols: getComputedStyle(grid).gridTemplateColumns.split(' ').length,
    grid: box(grid), panes, past: past.slice(0, 6),
    build: {sh: bp.scrollHeight, ch: bp.clientHeight,
            oy: getComputedStyle(bp).overflowY},
    input: inp && shown(inp) ? box(inp) : null,
    row: row && shown(row) ? box(row) : null,
  };
}"""

_NARROW = [(640, 900), (480, 800), (360, 740), (320, 640)]
_MODES = ["sr", "aram", "arena", "tft"]


def _measure(pw_browser, mock_server, w, h, query, prep=None):
    ctx, page, errors = _open(pw_browser, mock_server, w, h, query)
    try:
        if prep:
            page.evaluate(prep)
            page.evaluate("() => new Promise((r) => requestAnimationFrame("
                          "() => requestAnimationFrame(() => r())))")
        m = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return m


def _check_column(m, label, order):
    assert m["cols"] == 1, (label, "columns", m["cols"])
    g = m["grid"]
    assert list(m["panes"]) and all(k in m["panes"] for k in order), (
        label, "panes shown", sorted(m["panes"]))
    for k in order:
        p = m["panes"][k]
        assert abs(p["l"] - g["l"]) <= 1 and abs(p["w"] - g["w"]) <= 1, (
            label, k, "not full width", p, g)
    for a, b in zip(order, order[1:]):
        assert m["panes"][a]["b"] <= m["panes"][b]["t"] + 1, (
            label, a, "not above", b, m["panes"][a], m["panes"][b])
    assert m["docSW"] <= m["iw"], (label, "document scrolls sideways", m)
    assert m["view"]["sw"] <= m["view"]["cw"] + 1, (
        label, "view scrolls sideways", m["view"], m["past"])
    assert not m["past"], (label, "past the view", m["past"])
    b = m["build"]
    assert b["oy"] == "visible" and b["sh"] <= b["ch"] + 1, (
        label, "build pane is a nested scroller", b)


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("w,h", _NARROW)
def test_narrow_window_stacks_one_full_width_column(w, h, mode, mock_server,
                                                    pw_browser):
    m = _measure(pw_browser, mock_server, w, h,
                 f"/?ui_mock=1&mode={mode}#active-match")
    _check_column(m, (mode, w, h), ["call", "build", "map"])
    if mode != "tft":
        inp, row = m["input"], m["row"]
        assert inp and row, (mode, w, "combo input not shown")
        # Measured before: 54 px at 640, 12 at 480 and 360. Beside the
        # select or wrapped above it, the input keeps at least 160 px.
        assert inp["w"] >= 160, (mode, w, "input squeezed", inp, row)
        assert inp["r"] <= row["r"] + 1, (mode, w, "input past its row")
        assert inp["h"] >= 42 - 0.5, (mode, w, "input under the floor", inp)


def test_live_aram_balance_row_sits_between_build_and_map(mock_server,
                                                          pw_browser):
    m = _measure(pw_browser, mock_server, 480, 800,
                 "/?ui_mock=1&mode=aram#active-match", prep=_ARAM_LIVE)
    _check_column(m, ("aram-live", 480), ["call", "build", "aram", "map"])


_PINNED = """() => {
  const view = document.querySelector('#view-active-match');
  const bp = view.querySelector('.am-pane-build');
  const head = bp.querySelector(':scope > .am-pane-head');
  // Sticky pins against the scrollport's padding edge.
  const vTop = view.getBoundingClientRect().top + view.clientTop
    + parseFloat(getComputedStyle(view).paddingTop);
  view.scrollTop += bp.getBoundingClientRect().top - vTop + 400;
  const h = head.getBoundingClientRect(), p = bp.getBoundingClientRect();
  return {scrolled: view.scrollTop, headTop: h.top, vTop, paneTop: p.top,
          paneBottom: p.bottom, pos: getComputedStyle(head).position};
}"""


@pytest.mark.parametrize("mode", ["sr", "arena"])
def test_build_head_stays_pinned_while_the_page_scrolls(mode, mock_server,
                                                        pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, 480, 800,
                              f"/?ui_mock=1&mode={mode}#active-match")
    try:
        r = page.evaluate(_PINNED)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert r["scrolled"] > 0, r
    assert r["paneTop"] < r["vTop"] - 300 and r["paneBottom"] > r["vTop"], r
    assert r["pos"] == "sticky", r
    assert abs(r["headTop"] - r["vTop"]) <= 1, r


@pytest.mark.parametrize("w,h", [(722, 900), (923, 1280)])
def test_two_columns_above_the_line(w, h, mock_server, pw_browser):
    m = _measure(pw_browser, mock_server, w, h,
                 "/?ui_mock=1&mode=sr#active-match")
    assert m["cols"] == 2, (w, m["cols"])
    p = m["panes"]
    assert abs(p["call"]["l"] - p["build"]["l"]) <= 1, p
    assert p["map"]["l"] >= p["call"]["r"], p
    assert m["build"]["oy"] == "auto", m["build"]


def test_overlay_shell_is_untouched_at_a_narrow_width(mock_server,
                                                      pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, 640, 900,
                              "/?ui_mock=1&mode=sr&overlay=1")
    try:
        r = page.evaluate("""() => {
          const g = document.querySelector('#view-active-match .am-grid');
          const b = document.querySelector('#view-active-match .am-pane-build');
          return {shell: document.body.dataset.shell,
                  grid: getComputedStyle(g).display,
                  areas: getComputedStyle(g).gridTemplateAreas,
                  ox: getComputedStyle(b).overflowX};
        }""")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert r["shell"] == "overlay", r
    assert r["grid"] == "block", r
    # The desktop template, not the narrow single column.
    assert r["areas"] == '"call map" "build map"', r
    assert r["ox"] != "clip", r
