"""
tests/snapshot_panels/test_tft_stat_strip_reflow.py
S144-U-294 (s144 uiux): the TFT Active Match stat strip (STAGE / LEVEL /
HP / GOLD, web/js/panels/active_match.js _amRenderLiveFallback) reads every
label and value whole at every window width, folding four columns to 2x2
when four no longer fit, never to a 3 + 1 orphan.

THE DEFECT. .am-tft-stats was a fixed repeat(4, minmax(0, 1fr)) grid
(web/css/panels/active_match.css). A cell needs about 79 px for the widest
real value (HP "100" at --fs-lg, plus 20 px padding and its border), and
the strip cut text when it was narrow. Measured headless
on /?ui_mock=1&mode=tft_live#active-match (the recorded 4-2 HUD read,
HP 100): at a 360 px window the cells were 57 px and "4-2" / "100" showed
35 of their 57 px ("4-..."), with STAGE / LEVEL cut too; at 320 px 25 of
57; and in the desktop three-pane band just over the 720 px reflow
breakpoint the CALL pane is narrow too - 721 px cut "100" to 37 px and
STAGE to 37 of 49, 800 px still cut STAGE. The ellipsis hid the round of
the stage, the one number the strip exists to show.

THE FIX. The four tracks take a width-driven minimum: (100% - 3 gaps) / 4
while the strip is at least 350 px wide, else (100% - 1 gap) / 2, chosen
by a clamp() on the strip's own width (auto-fit then lays out exactly four
or exactly two tracks). The column count depends only on the width, never
on the data, so a value landing changes text, never geometry (the S134 T1
no-reflow rule). The 1920x920 baseline and the 920x1280 companion keep
their four columns; the overlay's own 2x2 rule (overlay.css, w-call)
outranks this one and is untouched.

Contract pinned here, at 320 / 360 / 400 / 440 / 721 / 760 / 800 / 920 /
1280 / 1920 wide:
  - every label and value is whole (scrollWidth <= clientWidth);
  - the strip lays out 4 or 2 columns, never 3 (no orphan cell), with
    equal tracks, and every cell sits inside the strip;
  - 4 columns at the 1920x920 baseline and the 920x1280 companion, with the
    baseline's tracks unchanged (control);
  - the empty "-" strip (mode=tft) and the live strip share one geometry.
"""
import pytest

from tests.snapshot_panels.test_active_match_view_fits_viewport import _open

_MEASURE = """() => {
  const g = document.querySelector('#am-call-body .am-tft-stats');
  if (!g) return null;
  const gr = g.getBoundingClientRect();
  const cells = [...g.querySelectorAll('.am-tft-stat')].map(c => {
    const r = c.getBoundingClientRect();
    const l = c.querySelector('.am-tft-stat-label');
    const v = c.querySelector('.am-tft-stat-value');
    return {label: l.textContent, value: v.textContent,
            l: r.left, r: r.right, t: r.top,
            lCut: l.scrollWidth - l.clientWidth,
            vCut: v.scrollWidth - v.clientWidth};
  });
  return {gl: gr.left, gr: gr.right, gw: gr.width, gt: gr.top, gh: gr.height,
          cols: getComputedStyle(g).gridTemplateColumns.trim()
            .split(/\\s+/).map(parseFloat),
          cells};
}"""

# (width, height): the narrow single-column band, the desktop three-pane
# band just over the 720 px breakpoint, the companion and the baseline.
_SIZES = [(320, 900), (360, 900), (400, 900), (440, 900), (721, 900),
          (760, 900), (800, 900), (920, 1280), (1280, 900), (1920, 920)]


def _measure(pw_browser, mock_server, w, h, mode):
    ctx, page, errors = _open(pw_browser, mock_server, w, h,
                              f"/?ui_mock=1&mode={mode}#active-match")
    try:
        page.wait_for_function(
            "() => document.querySelectorAll("
            "'#am-call-body .am-tft-stats .am-tft-stat').length === 4",
            timeout=10_000)
        m = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert m is not None, (mode, w, "no stat strip")
    return m


@pytest.mark.parametrize("w,h", _SIZES)
def test_tft_stat_strip_reads_whole_at_every_width(w, h, mock_server,
                                                   pw_browser):
    m = _measure(pw_browser, mock_server, w, h, "tft_live")
    # Anchor: the recorded 4-2 HUD read, HP 100 the widest value.
    assert [(c["label"], c["value"]) for c in m["cells"]] == [
        ("STAGE", "4-2"), ("LEVEL", "8"), ("HP", "100"), ("GOLD", "57")
    ], m["cells"]
    cut = [(c["label"], c["value"], c["lCut"], c["vCut"])
           for c in m["cells"] if c["lCut"] > 0 or c["vCut"] > 0]
    assert not cut, (w, "cut", cut, m["cols"])
    n = len(m["cols"])
    assert n in (2, 4), (w, "columns", m["cols"])
    assert max(m["cols"]) - min(m["cols"]) <= 1, (w, "unequal", m["cols"])
    rows = sorted({round(c["t"]) for c in m["cells"]})
    assert len(rows) == 4 // n, (w, "rows", rows, m["cols"])
    for c in m["cells"]:
        assert c["l"] >= m["gl"] - 1 and c["r"] <= m["gr"] + 1, (
            w, "cell outside the strip", c, m["gl"], m["gr"])


@pytest.mark.parametrize("w,h", [(920, 1280), (1920, 920)])
def test_tft_stat_strip_keeps_four_columns_at_companion_and_baseline(
        w, h, mock_server, pw_browser):
    m = _measure(pw_browser, mock_server, w, h, "tft_live")
    assert len(m["cols"]) == 4, (w, m["cols"])
    if w == 1920:
        # Control: the baseline's tracks did not move (198.7 px measured
        # before the fix; four tracks share the strip less three 10 px gaps).
        assert all(abs(c - (m["gw"] - 30) / 4) <= 1 for c in m["cols"]), (
            m["cols"], m["gw"])
        assert all(c >= 190 for c in m["cols"]), m["cols"]


@pytest.mark.parametrize("w", [360, 721])
def test_tft_stat_strip_geometry_does_not_move_when_data_lands(
        w, mock_server, pw_browser):
    empty = _measure(pw_browser, mock_server, w, 900, "tft")
    live = _measure(pw_browser, mock_server, w, 900, "tft_live")
    assert [c["value"] for c in empty["cells"]] == ["-"] * 4, empty["cells"]
    assert empty["cols"] == live["cols"], (w, empty["cols"], live["cols"])
    assert empty["gh"] == live["gh"], (w, empty["gh"], live["gh"])

    def boxes(m):
        # Relative to the strip: the status line above it is a sentence
        # before data lands and "Live" after, so the strip itself may move.
        return [(round(c["l"] - m["gl"]), round(c["t"] - m["gt"]))
                for c in m["cells"]]

    assert boxes(empty) == boxes(live), (w, boxes(empty), boxes(live))
