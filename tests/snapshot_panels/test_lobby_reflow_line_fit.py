"""
tests/snapshot_panels/test_lobby_reflow_line_fit.py
The Pre-Game Lobby reflows at 840 px and under, so from 841 px up its
desktop row templates have room and below that the narrow layout takes
over: no window width scrolls the view sideways or puts a card past the
view's content box (s144 lane uiux, S144-U-197).

Measured before the fix (ui_mock lobby, with and without a populated Top 8
and YOUR MAINS, LoL and TFT, headless Chromium): the narrow layout
(RM-1775, RM-1776, S144-U-180) started at 720 px, but below 1200 px the
Lobby grid is one `1fr` track that cannot shrink below its widest row's
min-content. The PARTY row's six-track desktop template needs 700 px, so
every card stayed 734 px wide from 721 to 807 px: 87 px past the view's
content box at 721 (the view scrolled 69 px sideways), 48 at 760, and
from 788 to 807 the cards sat in the view's right padding (8 px at 800).
The desktop templates first fit at 808 px; the line sits at 840 so a
window a few dozen px wider than that still gets them with room to spare.

Contract pinned here with the populated Top 8 / YOUR MAINS data of
test_lobby_mains_top8_narrow_reflow.py (synthetic Riot IDs, RM-906):
  - at 722x900, 760x900, 800x900 and 840x900 the view does not scroll
    sideways, every card lies inside the view's content box and no
    displayed descendant of a card reaches past that card's frame;
  - there the PARTY and TOP 8 rows use the narrow (flex) layout and the
    QUEUE buttons may wrap;
  - at 842x900 and 1199x900 the PARTY row keeps its six desktop tracks,
    a TOP 8 row its nine, and the cards still fit the view.
The PARTY card's duo-synergy block (RM-881, the queue lane's) is pinned
elsewhere (test_lobby_narrow_reflow.py); at these widths it fits.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_lobby_mains_top8_narrow_reflow import (
    _MAINS,
    _TOP8,
)

_GAP = ((722, 900), (760, 900), (800, 900), (840, 900))
_DESK = ((842, 900), (1199, 900))
_GAP_IDS = [str(s[0]) for s in _GAP]
_DESK_IDS = [str(s[0]) for s in _DESK]

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)

_READ = """() => {
  const sec = document.getElementById("view-lobby");
  if (!sec || getComputedStyle(sec).display === "none") return null;
  const scs = getComputedStyle(sec);
  const sr = sec.getBoundingClientRect();
  const content = {
    l: sr.left + parseFloat(scs.borderLeftWidth) + parseFloat(scs.paddingLeft),
    r: sr.right - parseFloat(scs.borderRightWidth)
      - parseFloat(scs.paddingRight),
  };
  const shown = (e) => getComputedStyle(e).display !== "none"
    && getComputedStyle(e).visibility !== "hidden"
    && e.getBoundingClientRect().width > 0;
  const cards = {};
  for (const c of sec.querySelectorAll(".lobby-view-card")) {
    const key = Array.from(c.classList)
      .find((k) => k.startsWith("lobby-view-card-")).slice(16);
    const cr = c.getBoundingClientRect();
    const past = [];
    for (const d of c.querySelectorAll("*")) {
      if (!shown(d)) continue;
      const r = d.getBoundingClientRect();
      if (r.right > cr.right + 1 || r.left < cr.left - 1) {
        past.push([d.tagName + "." + String(d.className).slice(0, 48),
                   Math.round(r.left), Math.round(r.right)]);
      }
    }
    cards[key] = {l: cr.left, r: cr.right, past: past.slice(0, 6)};
  }
  const tracks = (sel) => Array.from(sec.querySelectorAll(sel))
    .filter(shown).map((e) => ({
      display: getComputedStyle(e).display,
      n: getComputedStyle(e).gridTemplateColumns.split(" ").length,
    }));
  const de = document.documentElement;
  return {
    content, cards,
    view: {sw: sec.scrollWidth, cw: sec.clientWidth},
    doc: {sw: de.scrollWidth, cw: de.clientWidth},
    party: tracks(".lobby-members-list .lobby-member-row"),
    top8: tracks("#lv-top8-list .lv-top8-row"),
    qwrap: getComputedStyle(
      sec.querySelector(".lobby-view-queue-controls")).flexWrap,
  };
}"""


def _read(pw_browser, url, size):
    ctx = pw_browser.new_context(
        ignore_https_errors=True,
        viewport={"width": size[0], "height": size[1]},
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(url + "/?ui_mock=1#lobby", wait_until="domcontentloaded",
                  timeout=15_000)
        page.wait_for_function(
            "document.body.dataset.view === 'lobby'"
            " && document.querySelectorAll('#lv-top8-list .lv-top8-name')"
            ".length === 3"
            " && document.querySelectorAll('#lv-mainchamps-list .lv-mc-copy')"
            ".length === 4"
            " && document.querySelectorAll('.lobby-members-list"
            " .lobby-member-row[data-member-idx]').length >= 2",
            timeout=10_000,
        )
        page.evaluate(_SETTLE)
        got = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors at {size}: {errors[:3]}"
    assert got is not None, size
    return got


@pytest.fixture(scope="module")
def measured(mock_server, pw_browser):
    mock_server._store["data"] = {"lcu": {"top8": _TOP8,
                                          "main_champs": _MAINS}}
    try:
        return {s: _read(pw_browser, mock_server.url, s)
                for s in _GAP + _DESK}
    finally:
        mock_server._store["data"] = {}


@pytest.mark.parametrize("size", _GAP + _DESK, ids=_GAP_IDS + _DESK_IDS)
def test_view_does_not_scroll_sideways(measured, size):
    r = measured[size]
    assert r["view"]["sw"] <= r["view"]["cw"] + 1, (size, r["view"])
    assert r["doc"]["sw"] <= r["doc"]["cw"], (size, r["doc"])


@pytest.mark.parametrize("size", _GAP + _DESK, ids=_GAP_IDS + _DESK_IDS)
@pytest.mark.parametrize("card", ("queue", "party", "mainchamps", "friends"))
def test_every_card_lies_inside_the_view(measured, size, card):
    r = measured[size]
    c = r["cards"][card]
    assert c["l"] >= r["content"]["l"] - 1, (size, card, c, r["content"])
    assert c["r"] <= r["content"]["r"] + 1, (size, card, c, r["content"])
    assert not c["past"], (size, card, c["past"])


@pytest.mark.parametrize("size", _GAP, ids=_GAP_IDS)
def test_rows_use_the_narrow_layout_up_to_840(measured, size):
    r = measured[size]
    assert len(r["party"]) == 5, r["party"]
    assert all(p["display"] == "flex" for p in r["party"]), (size, r["party"])
    assert len(r["top8"]) == 8, r["top8"]
    assert all(t["display"] == "flex" for t in r["top8"]), (size, r["top8"])
    assert r["qwrap"] == "wrap", (size, r["qwrap"])


@pytest.mark.parametrize("size", _DESK, ids=_DESK_IDS)
def test_desktop_templates_hold_above_840(measured, size):
    r = measured[size]
    assert len(r["party"]) == 5, r["party"]
    for p in r["party"]:
        assert p["display"] == "grid" and p["n"] == 6, (size, p)
    assert len(r["top8"]) == 8, r["top8"]
    for t in r["top8"]:
        assert t["display"] == "grid" and t["n"] == 9, (size, t)
    assert r["qwrap"] == "nowrap", (size, r["qwrap"])
