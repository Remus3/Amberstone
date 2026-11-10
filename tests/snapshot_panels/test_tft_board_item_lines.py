"""
tests/snapshot_panels/test_tft_board_item_lines.py
The TFT Active Match BOARD shows each unit's items whole (s144 lane uiux,
S144-U-290, S144-U-291).

A board chip (web/js/panels/active_match.js _amTftBoardNode) is the unit name
on one line and its items joined by " / " below it. That line was one nowrap,
ellipsised line (web/css/panels/active_match.css .am-tft-unit-items) in a
chip with 142 px of text at the baseline. S144-U-290 made it wrap, clamped
at three lines, in a box reserving three item lines (212 px). Measured
(S144-U-291, headless, 1920x920): of the 9139 three-item sets of the 39
crafted Set 18 items, 3608 need four to six lines at 142 px (the
harness's offline Lato), so the clamp cut about two in five full chips
(the QA ledger's FUTURE (m): "Infinity Edge / Last Whisper / Guinsoo's
Rageblade" is four lines); with one Radiant item
94 percent were cut. A clamp leaves the chip title as the only carrier, and
a hover is not a read during a round.

Contract pinned here:
  - the items line wraps (never nowrap) and is NEVER clamped: every name
    stays whole at any width, at --fs-xs (16 px), its text unchanged;
  - the fixed board box reserves two chip rows of a name and FOUR item lines
    (252 px at the v2.1 tokens; 8725 of the 9139 crafted sets fit in four
    lines at the baseline), the same with or without units, so a round
    landing still never reflows the pane grid;
  - a full level-10 board of three-item chips at four lines each fits both
    rows whole inside the box at the baseline, the cue hidden (the FUTURE (m)
    board itself);
  - a chip longer than four lines is whole too: its row grows inside the
    fixed box, the board scrolls, and the RM-1771 "+N BELOW" cue counts the
    chips it pushed below; scrolled to the bottom every chip is whole;
  - control: the 1920x920 page geometry does not move (BUILD pane rect,
    five columns, no page scroll), the box is no taller than its pane body.

Drive path: /?ui_mock=1&mode=tft_round#active-match (web/data/ui_mock/
active_match_tft_round.json, a recorded S134 round row: seven units). The
full-board cases serve a copy of that row with a ten-unit board through
page.route; the crafted names are the real TFT names in
web/data/ui_mock/last_match_tft.json, the Radiant names the
tft/tft_standalone.py clean_item_name form of real Set 18 apiNames.
"""
import copy
import json
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_ROUND = (Path(__file__).resolve().parents[2] / "web" / "data" / "ui_mock"
          / "active_match_tft_round.json")

_RECORDED_ITEMS = [
    "BF Sword / Guinsoos Rageblade", "no items", "no items",
    "Guinsoos Rageblade", "Bramble Vest", "no items", "no items",
]

_FULL_ITEMS = ["Infinity Edge", "Last Whisper", "Guinsoo's Rageblade"]
_RADIANT_ITEMS = ["Radiant Guinsoos Rageblade", "Radiant Gargoyle Stoneplate",
                  "Radiant Rabadons Deathcap"]
_FULL_NAMES = ["Yunara", "Rakan", "Yorick", "Karma", "Diana",
               "Fiddlesticks", "Vi", "Jinx", "Caitlyn", "Lulu"]

_MEASURE = r"""
async () => {
  await document.fonts.ready;
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r())));
  const root = getComputedStyle(document.documentElement);
  const fsXs = parseFloat(root.getPropertyValue('--fs-xs'));
  const fsSm = parseFloat(root.getPropertyValue('--fs-sm'));
  const wrap = document.querySelector('#am-build-body .am-tft-board-wrap');
  const wr = wrap.getBoundingClientRect();
  const visBottom = wr.top + wrap.clientTop + wrap.clientHeight;
  const units = Array.from(wrap.querySelectorAll('.am-tft-unit')).map(u => {
    const it = u.querySelector('.am-tft-unit-items');
    const cs = getComputedStyle(it);
    const ur = u.getBoundingClientRect();
    const ir = it.getBoundingClientRect();
    return {text: it.textContent, sw: it.scrollWidth, cw: it.clientWidth,
            sh: it.scrollHeight, ch: it.clientHeight,
            lines: Math.round(ir.height / parseFloat(cs.lineHeight)),
            whiteSpace: cs.whiteSpace, clamp: cs.webkitLineClamp,
            overflowY: cs.overflowY, fontSize: cs.fontSize,
            inChip: ir.left >= ur.left - 0.5 && ir.right <= ur.right + 0.5
                    && ir.bottom <= ur.bottom + 0.5,
            below: ur.bottom > visBottom + 0.5};
  });
  const rect = s => { const r = document.querySelector(s).getBoundingClientRect();
    return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; };
  const body = document.getElementById('am-build-body');
  const cue = wrap.querySelector('.am-tft-more');
  return {fsXs, fsSm, units,
          wrapH: wrap.clientHeight, wrapScroll: wrap.scrollHeight,
          bodyH: body.clientHeight,
          cue: cue ? {hidden: cue.hidden, text: cue.textContent} : null,
          cols: getComputedStyle(wrap.querySelector('.am-tft-board'))
            .gridTemplateColumns.trim().split(/\s+/).length,
          buildPane: rect('#view-active-match .am-pane-build'),
          docH: document.documentElement.scrollHeight,
          vh: window.innerHeight};
}
"""

_SCROLL_END = r"""
async () => {
  const wrap = document.querySelector('#am-build-body .am-tft-board-wrap');
  wrap.scrollTop = wrap.scrollHeight;
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r())));
}
"""


def _open(pw_browser, mock_server, w: int, h: int, payload: dict | None = None):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": w, "height": h})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    if payload is not None:
        body = json.dumps(payload)
        page.route(
            "**/active_match_tft_round.json*",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body=body),
        )
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


def _measure(pw_browser, mock_server, w, h, payload=None,
             scroll_end: bool = False) -> tuple[dict, dict | None]:
    ctx, page, errors = _open(pw_browser, mock_server, w, h, payload)
    try:
        m = page.evaluate(_MEASURE)
        end = None
        if scroll_end:
            page.evaluate(_SCROLL_END)
            end = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors at {w}x{h}: {errors[:3]}"
    assert m["fsXs"] == 16 and m["fsSm"] == 18, (m["fsXs"], m["fsSm"])
    return m, end


def _board(items_for) -> dict:
    payload = copy.deepcopy(json.loads(_ROUND.read_text(encoding="utf-8")))
    payload["coach"]["tft_board"] = [
        {"name": n, "star": 2, "items": list(items_for(i))}
        for i, n in enumerate(_FULL_NAMES)
    ]
    return payload


def _box_px(fs_xs: float, fs_sm: float) -> int:
    # Eyebrow line + its 6 px gap, two chip rows of a name line, four item
    # lines and 8 px of chip padding + border, and the 6 px row gap.
    return int(fs_xs * 1.2 + 6 + 2 * (fs_sm * 1.25 + 4 * fs_xs * 1.25 + 8) + 6)


def _assert_whole(u: dict, where: str) -> None:
    assert u["whiteSpace"] != "nowrap", u
    assert u["clamp"] == "none", f"{where}: items line clamped: {u}"
    assert u["fontSize"] == "16px", u
    assert u["sw"] <= u["cw"] and u["sh"] <= u["ch"] + 0.5, (
        f"{where}: items line cut: {u}")
    assert u["inChip"], f"{where}: items line leaves its chip: {u}"


def _assert_baseline_geometry(m: dict) -> None:
    assert m["cols"] == 5, m["cols"]
    assert m["buildPane"] == [37, 496, 855, 379], m["buildPane"]
    assert m["wrapH"] <= m["bodyH"], (m["wrapH"], m["bodyH"])
    assert m["docH"] == m["vh"] == 920, (m["docH"], m["vh"])


@pytest.mark.parametrize("w,h", [(1920, 920), (1440, 900), (923, 1280)])
def test_recorded_board_shows_every_item_whole(w, h, mock_server, pw_browser):
    m, _ = _measure(pw_browser, mock_server, w, h)
    assert [u["text"] for u in m["units"]] == _RECORDED_ITEMS, m["units"]
    for u in m["units"]:
        _assert_whole(u, f"{w}x{h}")
        assert 1 <= u["lines"] <= 4, u
    # The one-item chip that was cut at the baseline reads on its own.
    karma = m["units"][3]
    assert karma["text"] == "Guinsoos Rageblade" and karma["lines"] <= 2, karma


def test_box_reserves_four_item_lines_and_keeps_the_baseline(
        mock_server, pw_browser):
    m, _ = _measure(pw_browser, mock_server, 1920, 920)
    assert m["wrapH"] == _box_px(m["fsXs"], m["fsSm"]) == 252, m["wrapH"]
    assert m["wrapScroll"] <= m["wrapH"], m
    assert not any(u["below"] for u in m["units"]), m["units"]
    _assert_baseline_geometry(m)


def test_full_three_item_board_is_whole_at_the_baseline(
        mock_server, pw_browser):
    # The QA ledger's FUTURE (m) board: ten units of "Infinity Edge / Last
    # Whisper / Guinsoo's Rageblade", four lines each in a 142 px chip.
    m, _ = _measure(pw_browser, mock_server, 1920, 920,
                    _board(lambda i: _FULL_ITEMS))
    want = " / ".join(_FULL_ITEMS)
    assert [u["text"] for u in m["units"]] == [want] * 10, m["units"]
    for u in m["units"]:
        _assert_whole(u, "1920x920 full board")
        assert u["lines"] == 4, u
    assert m["wrapH"] == 252 and m["wrapScroll"] <= m["wrapH"], m
    assert not any(u["below"] for u in m["units"]), m["units"]
    assert m["cue"] is not None and m["cue"]["hidden"], m["cue"]
    _assert_baseline_geometry(m)


def test_a_chip_past_four_lines_is_whole_and_the_board_scrolls(
        mock_server, pw_browser):
    # A three-Radiant chip needs more than four lines at the baseline. It is
    # never clamped: its row grows inside the fixed box, the second row is
    # pushed below, the cue counts it, and a scroll shows it whole.
    m, end = _measure(
        pw_browser, mock_server, 1920, 920,
        _board(lambda i: _RADIANT_ITEMS if i == 0 else _FULL_ITEMS),
        scroll_end=True)
    first = m["units"][0]
    assert first["text"] == " / ".join(_RADIANT_ITEMS), first
    assert first["lines"] > 4, f"not a past-four-lines chip: {first}"
    for u in m["units"]:
        _assert_whole(u, "1920x920 radiant board")
    assert m["wrapH"] == 252 and m["wrapScroll"] > m["wrapH"], m
    below = sum(u["below"] for u in m["units"])
    assert below == 5 and not any(u["below"] for u in m["units"][:5]), m["units"]
    assert m["cue"] == {"hidden": False, "text": "+5 BELOW"}, m["cue"]
    _assert_baseline_geometry(m)
    # Scrolled to the bottom: nothing below, the cue hides, still whole.
    assert not any(u["below"] for u in end["units"]), end["units"]
    assert end["cue"]["hidden"], end["cue"]
    for u in end["units"]:
        _assert_whole(u, "1920x920 radiant board scrolled")
    _assert_baseline_geometry(end)
