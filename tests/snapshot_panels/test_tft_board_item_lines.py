"""
tests/snapshot_panels/test_tft_board_item_lines.py
The TFT Active Match BOARD shows each unit's items whole at the 1920x920
baseline (s144 lane uiux, S144-U-290).

A board chip (web/js/panels/active_match.js _amTftBoardNode) is the unit name
on one line and its items joined by " / " on a second line. That line was one
nowrap, ellipsised line (web/css/panels/active_match.css .am-tft-unit-items),
and a chip is 160 px at the baseline (142 px of text). Measured on the
recorded tft_round row: Karma's ONE item, "Guinsoos Rageblade", needs 146 px
and was cut; Yunara's "BF Sword / Guinsoos Rageblade" needs 235 px and showed
about half. At the 923x1280 companion size the chip text is 98 px and both
were cut further. The title carried the names, but a hover is not a read
during a round.

Contract pinned here:
  - the items line wraps (never nowrap) and is clamped at three lines (a
    unit holds at most three items, _amTftBoard);
  - on the recorded board every items line is whole (no hidden width or
    height) at the baseline, 1440x900 and the companion size, inside its own
    chip, at --fs-xs (16 px), its text unchanged;
  - the fixed board box reserves two chip rows of name + three item lines
    (212 px at the v2.1 tokens), the same with or without units, so a round
    landing still never reflows the pane grid;
  - control: the 1920x920 page geometry does not move (BUILD pane rect,
    five columns, no page scroll), the box is no taller than its pane body,
    and nothing sits below the box;
  - a full level-10 board, ten units of three items each, still fits its two
    rows inside the box at the baseline with every line clamped at three.
    That case pins the box and the clamp, NOT whole text: "Infinity Edge /
    Last Whisper / Guinsoo's Rageblade" needs four lines in a 142 px chip
    (80 px of text in a 60 px clamp, measured), so its last name is cut and
    the chip title carries it (filed FUTURE in the QA ledger).

Drive path: /?ui_mock=1&mode=tft_round#active-match (web/data/ui_mock/
active_match_tft_round.json, a recorded S134 round row: seven units). The
full-board case serves a copy of that row with a ten-unit board through
page.route; its item names are the real TFT names in
web/data/ui_mock/last_match_tft.json.
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
            fontSize: cs.fontSize,
            inChip: ir.left >= ur.left - 0.5 && ir.right <= ur.right + 0.5
                    && ir.bottom <= ur.bottom + 0.5,
            below: ur.bottom > visBottom + 0.5};
  });
  const rect = s => { const r = document.querySelector(s).getBoundingClientRect();
    return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; };
  const body = document.getElementById('am-build-body');
  return {fsXs, fsSm, units,
          wrapH: wrap.clientHeight, wrapScroll: wrap.scrollHeight,
          bodyH: body.clientHeight,
          cols: getComputedStyle(wrap.querySelector('.am-tft-board'))
            .gridTemplateColumns.trim().split(/\s+/).length,
          buildPane: rect('#view-active-match .am-pane-build'),
          docH: document.documentElement.scrollHeight,
          vh: window.innerHeight};
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


def _measure(pw_browser, mock_server, w, h, payload=None) -> dict:
    ctx, page, errors = _open(pw_browser, mock_server, w, h, payload)
    try:
        m = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors at {w}x{h}: {errors[:3]}"
    assert m["fsXs"] == 16 and m["fsSm"] == 18, (m["fsXs"], m["fsSm"])
    return m


def _box_px(fs_xs: float, fs_sm: float) -> int:
    # Eyebrow line + its 6 px gap, two chip rows of a name line, three item
    # lines and 8 px of chip padding + border, and the 6 px row gap.
    return int(fs_xs * 1.2 + 6 + 2 * (fs_sm * 1.25 + 3 * fs_xs * 1.25 + 8) + 6)


@pytest.mark.parametrize("w,h", [(1920, 920), (1440, 900), (923, 1280)])
def test_recorded_board_shows_every_item_whole(w, h, mock_server, pw_browser):
    m = _measure(pw_browser, mock_server, w, h)
    assert [u["text"] for u in m["units"]] == _RECORDED_ITEMS, m["units"]
    for u in m["units"]:
        assert u["whiteSpace"] != "nowrap", u
        assert u["clamp"] == "3", u
        assert u["fontSize"] == "16px", u
        assert u["sw"] <= u["cw"] and u["sh"] <= u["ch"] + 0.5, (
            f"{w}x{h}: items line cut: {u}")
        assert 1 <= u["lines"] <= 3, u
        assert u["inChip"], f"{w}x{h}: items line leaves its chip: {u}"
    # The one-item chip that was cut at the baseline reads on its own.
    karma = m["units"][3]
    assert karma["text"] == "Guinsoos Rageblade" and karma["lines"] <= 2, karma


def test_box_reserves_three_item_lines_and_keeps_the_baseline(
        mock_server, pw_browser):
    m = _measure(pw_browser, mock_server, 1920, 920)
    assert m["wrapH"] == _box_px(m["fsXs"], m["fsSm"]) == 212, m["wrapH"]
    assert m["wrapScroll"] <= m["wrapH"], m
    assert not any(u["below"] for u in m["units"]), m["units"]
    # Control: the pane grid at the baseline is where it was.
    assert m["cols"] == 5, m["cols"]
    assert m["buildPane"] == [37, 496, 855, 379], m["buildPane"]
    assert m["wrapH"] <= m["bodyH"], (m["wrapH"], m["bodyH"])
    assert m["docH"] == m["vh"] == 920, (m["docH"], m["vh"])


def test_full_board_fits_its_two_rows_at_the_baseline(mock_server, pw_browser):
    payload = json.loads(_ROUND.read_text(encoding="utf-8"))
    payload = copy.deepcopy(payload)
    payload["coach"]["tft_board"] = [
        {"name": n, "star": 2, "items": list(_FULL_ITEMS)} for n in _FULL_NAMES
    ]
    m = _measure(pw_browser, mock_server, 1920, 920, payload)
    want = " / ".join(_FULL_ITEMS)
    assert [u["text"] for u in m["units"]] == [want] * 10, m["units"]
    assert m["wrapH"] == 212 and m["wrapScroll"] <= m["wrapH"], m
    assert not any(u["below"] for u in m["units"]), m["units"]
    for u in m["units"]:
        assert u["lines"] <= 3 and u["inChip"], u
        assert u["sw"] <= u["cw"], u
    assert m["buildPane"] == [37, 496, 855, 379], m["buildPane"]
    assert m["docH"] == 920, m["docH"]
