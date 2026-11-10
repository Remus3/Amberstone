"""
tests/snapshot_panels/test_tft_board_unit_names_whole.py
S144-U-300 (s144 uiux): a TFT Active Match BOARD chip shows its unit's
name whole at every window size, wrapping it inside the chip, instead of
ellipsising it.

THE DEFECT. The chip's name line was one nowrap line with an ellipsis
(web/css/panels/active_match.css .am-tft-unit-name), and RM-1766 let a
"longer name" ellipsise because the chip's title and aria-label carry it.
MEASURED headless on the tft_round fixture with recorded unit names
(clean_unit_name output for character ids under ops/runtime/tft_qa:
DA_CrimsonRaptor18, DA_Fiddlesticks18, DA_18_MasterYi_AD; Brambleback and
Scuttlecrab from the same captures): at the 1920x920 baseline a 3-star
"CrimsonRaptor" lost 11 px and a 3-star "Fiddlesticks" 2 px; at 1600x900
every name of 11 letters or more lost 23 px or more ("Brambleback" read
"Brambl..."), at the 923x1280 companion size 37 to 55 px. A hover is not a
read (the S144-U-291 ruling for this chip's items), so the name is the one
line of the chip that was still cut.

THE FIX. The name line wraps: the star drops under a name that fills the
line, and a name wider than the chip breaks at a word joint
(active_match.js _amTftUnitName puts a <wbr> between "Crimson" and
"Raptor", after "MasterYi_"), then anywhere as a last resort. A taller
chip grows inside the fixed board box, which scrolls with its "+N BELOW"
cue (RM-1771), as the items line already does (S144-U-290 / U-291).

Pinned here, at the RM-1766 sizes where the board is at least one chip
wide: every name and star is inside its chip and no name is cut; the
name's text is exactly the unit name (a <wbr> adds no character); the
camel and underscore joints are the only places a joint-carrying name
breaks while each part fits; the title and aria-label are unchanged; and
the 1920x920 control keeps five columns and the 252 px box.
"""
import json
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_FIXTURE = (Path(__file__).resolve().parents[2]
            / "web" / "data" / "ui_mock" / "active_match_tft_round.json")

# Recorded names (see the docstring), at the star levels that cut them.
_BOARD = [
    {"name": "CrimsonRaptor", "star": 3, "items": []},
    {"name": "Fiddlesticks", "star": 3, "items": ["Bramble Vest"]},
    {"name": "MasterYi_AD", "star": 2, "items": []},
    {"name": "Brambleback", "star": 1, "items": []},
    {"name": "Scuttlecrab", "star": 1, "items": []},
    {"name": "Rakan", "star": 2, "items": []},
    {"name": "Vi", "star": 1, "items": []},
]
# The joints a name may break at while each part fits the chip.
_JOINTS = {"CrimsonRaptor": {7}, "MasterYi_AD": {6, 9}}
# Sizes where "CrimsonRaptor" (118 px) is wider than its chip, so it must
# wrap, and at its joint: anchors the joints case (the old nowrap name
# never broke, so a subset check alone passed on it).
_MUST_WRAP = {(1440, 900), (923, 1280), (480, 800)}

_SIZES = [(1920, 920), (1600, 900), (1440, 900), (1199, 920), (1024, 768),
          (923, 1280), (768, 1024), (721, 900), (640, 900), (480, 800),
          (400, 800)]

_MEASURE = r"""
async () => {
  await document.fonts.ready;
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r())));
  const board = document.querySelector('#am-build-body .am-tft-board');
  const wrap = document.querySelector('#am-build-body .am-tft-board-wrap');
  const fsSm = parseFloat(getComputedStyle(document.documentElement)
    .getPropertyValue('--fs-sm'));
  const cols = getComputedStyle(board).gridTemplateColumns.trim().split(/\s+/);
  // Where each line of a text box starts: the index of every character
  // whose top is below the previous character's.
  const breaks = (el) => {
    const out = [];
    let i = 0, top = null;
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let t = walker.nextNode(); t; t = walker.nextNode()) {
      for (let k = 0; k < t.length; k++, i++) {
        const r = document.createRange();
        r.setStart(t, k); r.setEnd(t, k + 1);
        const y = r.getBoundingClientRect().top;
        if (top !== null && y > top + 2) out.push(i);
        top = y;
      }
    }
    return out;
  };
  const units = Array.from(board.querySelectorAll('.am-tft-unit')).map(u => {
    const cs = getComputedStyle(u);
    const ur = u.getBoundingClientRect();
    const inL = ur.left + parseFloat(cs.borderLeftWidth) + parseFloat(cs.paddingLeft);
    const inR = ur.right - parseFloat(cs.borderRightWidth) - parseFloat(cs.paddingRight);
    const n = u.querySelector('.am-tft-unit-name');
    const s = u.querySelector('.am-tft-unit-star');
    const nr = n.getBoundingClientRect();
    const sr = s.getBoundingClientRect();
    return {name: n.textContent, star: s.textContent,
            inL, inR, nL: nr.left, nR: nr.right, sL: sr.left, sR: sr.right,
            sVisible: s.checkVisibility() && sr.width > 0,
            cutX: n.scrollWidth - n.clientWidth,
            cutY: n.scrollHeight - n.clientHeight,
            breaks: breaks(n),
            title: u.title, label: u.getAttribute('aria-label')};
  });
  return {cols: cols.length, boardWidth: board.getBoundingClientRect().width,
          fsSm, units, wrapH: wrap.clientHeight,
          docOverflow: document.documentElement.scrollWidth
                       > document.documentElement.clientWidth};
}
"""


def _payload() -> str:
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(data["coach"]["tft_board"], list)
    data["coach"]["tft_board"] = _BOARD
    return json.dumps(data)


@pytest.fixture(scope="module")
def payload():
    return _payload()


def _measure(pw_browser, mock_server, payload, w: int, h: int) -> dict:
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": w, "height": h})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    hits: list[str] = []

    def _serve(route):
        hits.append(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=payload)

    page.route("**/ui_mock/active_match_tft_round.json*", _serve)
    page.route("**/api/minimap-crop*",
               lambda r: r.fulfill(status=404, body=""))
    page.route("**/api/vision-state*", lambda r: r.fulfill(
        status=503, content_type="application/json", body="{}"))
    try:
        page.goto(mock_server.url + "/?ui_mock=1&mode=tft_round#active-match",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "document.querySelectorAll('#am-build-body .am-tft-unit').length"
            f" === {len(_BOARD)}", timeout=10_000)
        m = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors at {w}x{h}: {errors[:3]}"
    assert hits, "the routed fixture was never fetched"
    assert m["fsSm"] == 18, m["fsSm"]
    # Anchor: the board rendered the routed names, in order.
    assert [u["name"] for u in m["units"]] == [b["name"] for b in _BOARD], (
        m["units"])
    assert [u["star"] for u in m["units"]] == ["*" * b["star"] for b in _BOARD]
    return m


@pytest.mark.parametrize("w,h", _SIZES)
def test_every_unit_name_is_whole_inside_its_chip(
        w, h, mock_server, pw_browser, payload):
    m = _measure(pw_browser, mock_server, payload, w, h)
    assert m["boardWidth"] >= 6 * m["fsSm"], m["boardWidth"]
    bad = []
    for u in m["units"]:
        if u["cutX"] > 0 or u["cutY"] > 0:
            bad.append((u["name"], "cut", u["cutX"], u["cutY"]))
        if u["nL"] < u["inL"] - 0.5 or u["nR"] > u["inR"] + 0.5:
            bad.append((u["name"], "name outside chip",
                        round(u["nL"] - u["inL"], 1),
                        round(u["inR"] - u["nR"], 1)))
        if not u["sVisible"] or u["sL"] < u["inL"] - 0.5 or (
                u["sR"] > u["inR"] + 0.5):
            bad.append((u["name"], "star outside chip",
                        round(u["sR"] - u["inR"], 1)))
    assert not bad, (w, h, m["cols"], bad)
    assert not m["docOverflow"], f"{w}x{h}: horizontal page overflow"


@pytest.mark.parametrize("w,h", _SIZES)
def test_a_wrapped_name_breaks_at_its_joints(
        w, h, mock_server, pw_browser, payload):
    m = _measure(pw_browser, mock_server, payload, w, h)
    for u in m["units"]:
        joints = _JOINTS.get(u["name"])
        if joints is None:
            continue
        assert set(u["breaks"]) <= joints, (w, h, u["name"], u["breaks"])
        if u["name"] == "CrimsonRaptor" and (w, h) in _MUST_WRAP:
            assert u["breaks"] == [7], (w, h, u["breaks"])
        # The hover and the accessible name still carry the whole chip.
        assert u["title"].startswith(u["name"] + ", "), u
        assert u["label"] == u["title"], u


def test_baseline_control_keeps_five_columns_and_the_box(
        mock_server, pw_browser, payload):
    m = _measure(pw_browser, mock_server, payload, 1920, 920)
    assert m["cols"] == 5, m["cols"]
    assert m["wrapH"] == 252, m["wrapH"]
