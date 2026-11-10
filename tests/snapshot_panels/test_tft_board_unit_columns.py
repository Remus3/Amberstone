"""
tests/snapshot_panels/test_tft_board_unit_columns.py
The TFT Active Match BOARD keeps every unit chip wide enough to read its name
(s144 lane uiux, RM-1766).

The board list (web/js/panels/active_match.js _amTftBoardNode) was a fixed
`repeat(5, minmax(0, 1fr))` grid in web/css/panels/active_match.css. That is
right at the 1920x920 baseline (855 px pane, 160 px chips), but the BOARD pane
narrows with the window and five columns stayed five: measured on the
tft_round fixture, 67 px chips at the 923x1280 companion size cut "Rakan" and
"Yorick" to 24 px ("Ra..."), 41 px chips at 640 px showed 0 to 7 px of every
name, and at 320 px a chip spilled out of the board.

Contract pinned here:
  - at most five columns, and at the 1920x920 baseline exactly five 160 px
    columns, as before (control: the baseline does not move);
  - a chip is never narrower than 6 x --fs-sm (108 px) unless the board itself
    is narrower, so a column drops before a name is cut;
  - every chip stays inside the board (no spill, no page overflow);
  - every fixture name of six letters or fewer is whole at every size where
    the board is at least one chip wide (a longer name may ellipsise; the
    chip's title and aria-label carry it whole);
  - the board wrapper keeps its fixed height (no reflow when units land), and
    a board that no longer fits scrolls inside it, as a named region.

Drive path: /?ui_mock=1&mode=tft_round#active-match (web/data/ui_mock/
active_match_tft_round.json, a recorded S134 round row: seven units).
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_UNITS = ["Yunara", "Rakan", "Yorick", "Karma", "Diana", "Fiddlesticks", "Vi"]

_MEASURE = r"""
async () => {
  await document.fonts.ready;
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r())));
  const board = document.querySelector('#am-build-body .am-tft-board');
  const wrap = document.querySelector('#am-build-body .am-tft-board-wrap');
  const br = board.getBoundingClientRect();
  const fsSm = parseFloat(getComputedStyle(document.documentElement)
    .getPropertyValue('--fs-sm'));
  const cols = getComputedStyle(board).gridTemplateColumns.trim().split(/\s+/)
    .map(parseFloat);
  const units = Array.from(board.querySelectorAll('.am-tft-unit')).map(u => {
    const r = u.getBoundingClientRect();
    const n = u.querySelector('.am-tft-unit-name');
    return {name: n.textContent, left: r.left, right: r.right, width: r.width,
            nameScroll: n.scrollWidth, nameClient: n.clientWidth,
            title: u.title, label: u.getAttribute('aria-label')};
  });
  return {boardLeft: br.left, boardRight: br.right, boardWidth: br.width,
          fsSm, cols, units,
          wrapH: wrap.clientHeight, wrapScroll: wrap.scrollHeight,
          wrapRole: wrap.getAttribute('role'),
          wrapLabel: wrap.getAttribute('aria-label'),
          docOverflow: document.documentElement.scrollWidth
                       > document.documentElement.clientWidth};
}
"""

_SIZES = [(1920, 920), (1440, 900), (1199, 920), (1024, 768), (923, 1280),
          (768, 1024), (640, 900), (480, 800), (320, 700)]


def _open(pw_browser, mock_server, w: int, h: int):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": w, "height": h})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + "/?ui_mock=1&mode=tft_round#active-match",
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    page.wait_for_function(
        "document.querySelectorAll('#am-build-body .am-tft-unit').length > 0",
        timeout=10_000,
    )
    return ctx, page, errors


def _measure(pw_browser, mock_server, w: int, h: int) -> dict:
    ctx, page, errors = _open(pw_browser, mock_server, w, h)
    try:
        m = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors at {w}x{h}: {errors[:3]}"
    assert [u["name"] for u in m["units"]] == _UNITS, m["units"]
    assert m["fsSm"] == 18, m["fsSm"]
    return m


def test_baseline_keeps_five_columns(mock_server, pw_browser):
    # Control: the 1920x920 design baseline is unchanged - five equal
    # columns, two chip rows inside the fixed wrapper, every name whole.
    m = _measure(pw_browser, mock_server, 1920, 920)
    assert len(m["cols"]) == 5, m["cols"]
    assert all(abs(c - 160.2) < 1.0 for c in m["cols"]), m["cols"]
    assert m["wrapScroll"] <= m["wrapH"], (m["wrapScroll"], m["wrapH"])
    assert all(u["nameScroll"] <= u["nameClient"] for u in m["units"]), m["units"]


@pytest.mark.parametrize("w,h", _SIZES)
def test_chip_floor_and_containment(w, h, mock_server, pw_browser):
    m = _measure(pw_browser, mock_server, w, h)
    floor = min(6 * m["fsSm"], m["boardWidth"])
    assert 1 <= len(m["cols"]) <= 5, m["cols"]
    for u in m["units"]:
        assert u["width"] >= floor - 0.5, (
            f"{w}x{h}: {u['name']} chip {u['width']:.1f}px under the "
            f"{floor:.1f}px floor (board {m['boardWidth']:.1f}px, "
            f"cols {m['cols']})")
        assert u["left"] >= m["boardLeft"] - 0.5, (w, h, u)
        assert u["right"] <= m["boardRight"] + 0.5, (
            f"{w}x{h}: {u['name']} chip spills past the board")
    assert not m["docOverflow"], f"{w}x{h}: horizontal page overflow"


@pytest.mark.parametrize("w,h", _SIZES)
def test_short_names_are_whole(w, h, mock_server, pw_browser):
    m = _measure(pw_browser, mock_server, w, h)
    if m["boardWidth"] < 6 * m["fsSm"]:
        return  # not this case: board Npx is narrower than one chip
    cut = [f"{u['name']} {u['nameClient']}/{u['nameScroll']}px"
           for u in m["units"]
           if len(u["name"]) <= 6 and u["nameScroll"] > u["nameClient"]]
    assert not cut, f"{w}x{h}: short unit names cut: {cut}"
    # A longer name may ellipsise; the chip still carries it whole.
    for u in m["units"]:
        assert u["title"].startswith(u["name"] + ", "), u
        assert u["label"] == u["title"], u


@pytest.mark.parametrize("w,h", [(1920, 920), (923, 1280), (640, 900)])
def test_wrapper_height_is_fixed_and_overflow_scrolls_inside(
        w, h, mock_server, pw_browser):
    # No reflow when the board lands: the wrapper is the fixed two-chip-row
    # box (eyebrow + 2 rows of a name and three item lines, 212 px at the
    # v2.1 tokens since S144-U-290, 132 px before) at every width; a
    # board needing more rows scrolls inside it, as the named region.
    m = _measure(pw_browser, mock_server, w, h)
    assert m["wrapH"] == 212, m["wrapH"]
    assert m["wrapRole"] == "region" and m["wrapLabel"] == "Your board"
