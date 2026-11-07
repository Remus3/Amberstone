"""
tests/snapshot_panels/test_build_insights_chart_tabs_narrow.py
In a narrow window the five Build Insights chart tabs (Game Length,
Snowball, Game Flow, OP Score, Benchmarks) fit their pane: the mode
buttons wrap, the Game Length champion filter shrinks its input, and a
Game Length / Snowball bar row puts its label and value on one line and
the bar on its own full-width line, so the bar never shrinks to nothing
(s144 lane uiux, RM-1778). 400% zoom of the 1920x920 baseline is 480
wide; WCAG 1.4.10 reflows at 320.

Measured before the fix (headless Chromium, the ui_mock
duration_winrate, snowball_elasticity, perf_curve, op_score and
champ_benchmarks fixtures):
  - every ARAM / SR / ARENA mode row (.dw-modes, .pf-modes, .op-modes,
    .cb-modes) was one 257 px nowrap line, ARENA ending at x 315: past
    the pane at 360, and past the view at 320 (a 204 px pane box), so
    the view scrolled sideways;
  - the Game Length champion filter (a 13em input plus the ALL clear
    button) was 300 px wide, past the pane at 400, 360 and 320, the
    clear button ending at x 358;
  - a bar row is label | track | value with fixed 88 + 116 px (Game
    Length) and 104 + 128 px (Snowball) side columns, so the track
    shrank to a sliver from about 400 down (2 px, its border, at 320)
    and the value ran past the pane (Snowball values ended at x 316
    at 360 and 320).
The Benchmarks table already scrolls inside .cb-table-wrap; that wrap
is the one sideways scroller allowed here.

Contract pinned for each chart tab at 722x900, 640x900, 480x800,
400x800, 360x740 and 320x640:
  - the view and the page do not scroll sideways;
  - every rendered element of the tab lies inside the pane's content
    box (inside the Benchmarks table wrap only the wrap itself is
    checked: its table scrolls inside it);
  - every mode button keeps the 42 px hit floor;
  - a bar track is at least 96 px wide;
  - the Game Length filter input is at least 120 px wide and its ALL
    clear button is wholly inside the pane.
At 480 and under a bar row stacks: label and value share the first
line (value at the right edge), the bar fills the second line. Above
480 nothing moves: at 1920x920, 722 and 640 the label, bar and value
sit on one line, the mode row is one line and the filter input keeps
its 13em width.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_MOUNT = {"duration": "#bi-duration-mount", "snowball": "#bi-snowball-mount",
          "flow": "#bi-flow-mount", "opscore": "#bi-opscore-mount",
          "bench": "#bi-bench-mount"}
_READY = {"duration": ".dw-row", "snowball": ".se-row",
          "flow": ".pf-mode-btn", "opscore": ".op-mode-btn",
          "bench": ".cb-table"}
_MODEBTN = {"duration": ".dw-mode-btn", "snowball": None,
            "flow": ".pf-mode-btn", "opscore": ".op-mode-btn",
            "bench": ".cb-mode-btn"}
_ROW = {"duration": "dw", "snowball": "se"}
_SIZES = ((1920, 920), (722, 900), (640, 900), (480, 800), (400, 800),
          (360, 740), (320, 640))
_STACK_MAX = 480
_CASES = [(w, h, t) for (w, h) in _SIZES for t in _MOUNT]
_IDS = [f"{w}-{t}" for (w, h, t) in _CASES]

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)

_READ = """([sel, modeSel, rowPfx]) => {
  const sec = document.getElementById("view-build-insights");
  const mount = document.querySelector(sel);
  const pane = mount.closest(".bi-tab-pane");
  const pcs = getComputedStyle(pane);
  const pr = pane.getBoundingClientRect();
  const left = pr.left + parseFloat(pcs.borderLeftWidth)
    + parseFloat(pcs.paddingLeft);
  const right = pr.right - parseFloat(pcs.borderRightWidth)
    - parseFloat(pcs.paddingRight);
  const out = [];
  let n = 0;
  for (const el of mount.querySelectorAll("*")) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    n += 1;
    if (el.closest(".cb-table-wrap") && !el.classList.contains(
        "cb-table-wrap")) continue;
    if (r.left < left - 1 || r.right > right + 1) {
      const cls = typeof el.className === "string" ? el.className
        : (el.className.baseVal || "");
      out.push(`${el.tagName}.${cls} ${Math.round(r.left)}-`
        + `${Math.round(r.right)}`);
    }
  }
  const btns = modeSel ? [...mount.querySelectorAll(modeSel)] : [];
  const btnTops = btns.map((b) => Math.round(b.getBoundingClientRect().top));
  const rows = rowPfx ? [...mount.querySelectorAll("." + rowPfx + "-row")]
    .map((row) => {
      const g = (c) => row.querySelector("." + rowPfx + "-" + c)
        .getBoundingClientRect();
      const lab = g("label"), trk = g("track"), val = g("val");
      return {lab: [lab.left, lab.right, lab.top, lab.bottom],
              trk: [trk.left, trk.right, trk.top, trk.bottom],
              val: [val.left, val.right, val.top, val.bottom],
              row: [row.getBoundingClientRect().left,
                    row.getBoundingClientRect().right]};
    }) : [];
  const inp = mount.querySelector(".dw-champ-input");
  const clr = mount.querySelector(".dw-champ-clear");
  const se = document.scrollingElement;
  return {
    sec: [sec.scrollWidth, sec.clientWidth],
    doc: [se.scrollWidth, se.clientWidth],
    box: [left, right], n, out,
    btnH: btns.map((b) => b.getBoundingClientRect().height),
    btnTops,
    rows,
    inp: inp ? inp.getBoundingClientRect().width : null,
    em: inp ? parseFloat(getComputedStyle(inp).fontSize) : null,
    clr: clr ? [clr.getBoundingClientRect().left,
                clr.getBoundingClientRect().right] : null,
  };
}"""


@pytest.fixture(scope="module", params=_CASES, ids=_IDS)
def tab_at(request, mock_server, pw_browser):
    w, h, tab = request.param
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": w, "height": h})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + "/?ui_mock=1#build-insights",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "document.querySelector('#bi-tabs [data-bi-tab]') !== null",
            timeout=10_000)
        page.click(f'#bi-tabs [data-bi-tab="{tab}"]')
        page.wait_for_function(
            f"document.querySelector('{_MOUNT[tab]} {_READY[tab]}')"
            " !== null", timeout=10_000)
        page.evaluate(_SETTLE)
        data = page.evaluate(
            _READ, [_MOUNT[tab], _MODEBTN[tab], _ROW.get(tab)])
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors at {w} {tab}: {errors[:3]}"
    return {"w": w, "tab": tab, "d": data}


def test_view_does_not_scroll_sideways(tab_at):
    d, w, t = tab_at["d"], tab_at["w"], tab_at["tab"]
    assert d["sec"][0] <= d["sec"][1] + 1, (
        f"{w} {t}: #view-build-insights scrolls sideways "
        f"({d['sec'][0]} > {d['sec'][1]})")
    assert d["doc"][0] <= d["doc"][1] + 1, (
        f"{w} {t}: the page scrolls sideways ({d['doc'][0]} > "
        f"{d['doc'][1]})")


def test_every_element_inside_the_pane(tab_at):
    d, w, t = tab_at["d"], tab_at["w"], tab_at["tab"]
    # An empty walk would pass vacuously: the tab must have rendered.
    assert d["n"] >= 10, f"{w} {t}: only {d['n']} rendered elements"
    assert not d["out"], (
        f"{w} {t}: past the pane content box "
        f"{d['box'][0]:.0f}-{d['box'][1]:.0f}: {d['out'][:6]}")


def test_mode_buttons_keep_the_hit_floor(tab_at):
    d, w, t = tab_at["d"], tab_at["w"], tab_at["tab"]
    if _MODEBTN[t] is None:
        return  # not this case: the Snowball tab has no mode row
    assert len(d["btnH"]) >= 3, f"{w} {t}: {len(d['btnH'])} mode buttons"
    assert min(d["btnH"]) >= 42 - 0.5, (
        f"{w} {t}: a mode button is {min(d['btnH']):.1f} px tall")


def test_mode_row_is_one_line_above_the_narrow_range(tab_at):
    d, w, t = tab_at["d"], tab_at["w"], tab_at["tab"]
    if _MODEBTN[t] is None or w <= 400:
        return  # not this case: mode row may wrap at 400 and under
    assert len(set(d["btnTops"])) == 1, (
        f"{w} {t}: the mode row wrapped (tops {d['btnTops']})")


def test_bar_track_keeps_a_readable_width(tab_at):
    d, w, t = tab_at["d"], tab_at["w"], tab_at["tab"]
    if t not in _ROW:
        return  # not this case: no bar rows on this tab
    assert len(d["rows"]) >= 4, f"{w} {t}: {len(d['rows'])} bar rows"
    for i, r in enumerate(d["rows"]):
        tw = r["trk"][1] - r["trk"][0]
        assert tw >= 96, f"{w} {t}: row {i} bar is {tw:.0f} px wide"


def test_bar_row_layout(tab_at):
    d, w, t = tab_at["d"], tab_at["w"], tab_at["tab"]
    if t not in _ROW:
        return  # not this case: no bar rows on this tab
    for i, r in enumerate(d["rows"]):
        lab, trk, val, row = r["lab"], r["trk"], r["val"], r["row"]
        if w <= _STACK_MAX:
            # Label and value on line one, the bar below them, full width.
            assert trk[2] >= max(lab[3], val[3]) - 1, (
                f"{w} {t}: row {i} bar top {trk[2]:.0f} is not below "
                f"the label / value line ({lab[3]:.0f} / {val[3]:.0f})")
            assert abs(lab[2] - val[2]) <= 4, (
                f"{w} {t}: row {i} label and value are not on one line")
            assert val[1] >= row[1] - 1 and lab[0] <= row[0] + 1, (
                f"{w} {t}: row {i} label / value do not span the row")
            assert trk[1] - trk[0] >= (row[1] - row[0]) - 1, (
                f"{w} {t}: row {i} bar does not fill its line")
        else:
            # Desktop: one line, label | bar | value left to right.
            assert lab[1] <= trk[0] + 1 and trk[1] <= val[0] + 1, (
                f"{w} {t}: row {i} is not label | bar | value")
            assert trk[2] < lab[3] and trk[3] > lab[2], (
                f"{w} {t}: row {i} bar is not on the label's line")


def test_champion_filter_fits(tab_at):
    d, w, t = tab_at["d"], tab_at["w"], tab_at["tab"]
    if t != "duration":
        return  # not this case: the champion filter is on Game Length only
    assert d["inp"] is not None and d["clr"] is not None
    assert d["inp"] >= 120, f"{w}: the filter input is {d['inp']:.0f} px"
    assert d["clr"][0] >= d["box"][0] - 1 and \
        d["clr"][1] <= d["box"][1] + 1, (
            f"{w}: ALL clear button {d['clr'][0]:.0f}-{d['clr'][1]:.0f} "
            f"past the pane {d['box'][0]:.0f}-{d['box'][1]:.0f}")
    if w > _STACK_MAX:
        assert abs(d["inp"] - 13 * d["em"]) <= 1, (
            f"{w}: the filter input moved off 13em ({d['inp']:.1f} px)")
