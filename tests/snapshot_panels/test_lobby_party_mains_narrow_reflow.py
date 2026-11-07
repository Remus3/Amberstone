"""
tests/snapshot_panels/test_lobby_party_mains_narrow_reflow.py
At 720 px and under the Pre-Game Lobby's PARTY MAINS tab fits its card and
no value in it is cut (s144 lane uiux, S144-U-180; the U-177 FUTURE row
"PARTY MAINS Player / Mastery / Recent cells at 320"). RM-1776 did the
YOUR MAINS tab (test_lobby_mains_top8_narrow_reflow.py); PARTY MAINS kept
its four desktop tracks (76px 1.4fr 1.2fr 1.0fr) at every width.

Data. The mock /api/state carries the ui_mock lobby (party_size 3, so the
tab shows member cards) and lcu.party_mains in the
dashboard/_party_mains.py card shape {name, player, mastery_level,
mastery_points}: a 16-character player name (the Riot ID name cap), the
longest champion names on the roster ("Nunu & Willump", "Aurelion Sol"),
a three-digit mastery level and points in the M / K / plain formats. One
card also carries `last_match`, the key web/js/main.js _renderPartyMains
reads for the RECENT cell (the backend does not emit it today, so live
cards show "-" there). Every name is synthetic (RM-906).

Measured before the fix (headless Chromium): at 400 the word "Mastery"
(66.6px at --fs-sm bold) overran its 59px cell and the KDA "12/4/8" its
49px cell; at 360 and 320 the PARTY header row grew to its labels' width
and ran 71px past the card (the card scrolled sideways), the short names
"BRAWLER" and "ALPHA" were cut to an ellipsis, and the placeholder rows'
"- points" overran a 33px cell.

Contract pinned at 640x900, 480x800, 400x740, 360x740 and 320x640:
  - the MAINS card lies inside the view's content box and does not scroll
    sideways;
  - a PARTY row does not scroll sideways, no text in it is broken inside a
    word, and no text but the player name is cut; the name shows its whole
    text or keeps at least 6em;
  - MASTERY and RECENT share the row's first line, the PLAYER cell (name
    over champion) spans both under them, and the champion names show
    whole;
  - the MASTERY and RECENT headers sit over their cells (centre in the
    cell, within 4px of its centre) and are not cut;
    the PLAYER header is hidden (the cell names itself).
Above the line (842x900, 1920x920; the Lobby's line is 840 px since
S144-U-197) the four desktop tracks and the one-line
row stand.
"""
import json
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_lobby_mains_top8_narrow_reflow import _SETTLE

_NARROW = ((640, 900), (480, 800), (400, 740), (360, 740), (320, 640))
_WIDE = ((842, 900), (1920, 920))
_IDS = [str(s[0]) for s in _NARROW]
_WIDE_IDS = [str(s[0]) for s in _WIDE]

_LOBBY = json.loads(
    (Path(__file__).resolve().parents[2] / "web" / "data" / "ui_mock"
     / "lobby.json").read_text(encoding="utf-8"))["lobby"]

_PARTY_MAINS = [
    {"name": "Nunu & Willump", "player": "QuietStormRider1",
     "mastery_level": 112, "mastery_points": 2456789},
    {"name": "Aurelion Sol", "player": "Brawler", "mastery_level": 7,
     "mastery_points": 843210,
     "last_match": {"result": "WIN", "kda": "12/4/8"}},
    {"name": "Jinx", "player": "Alpha", "mastery_level": 34,
     "mastery_points": 1000},
]

_READ = """() => {
  const sec = document.getElementById("view-lobby");
  if (!sec || getComputedStyle(sec).display === "none") return null;
  const box = (e) => {
    const r = e.getBoundingClientRect();
    return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width,
            h: r.height, sw: e.scrollWidth, cw: e.clientWidth,
            text: e.textContent.trim(),
            em: parseFloat(getComputedStyle(e).fontSize)};
  };
  const shown = (e) => !!e && getComputedStyle(e).display !== "none"
    && e.getBoundingClientRect().width > 0;
  const scs = getComputedStyle(sec);
  const sr = sec.getBoundingClientRect();
  const content = {
    l: sr.left + parseFloat(scs.borderLeftWidth) + parseFloat(scs.paddingLeft),
    r: sr.right - parseFloat(scs.borderRightWidth)
      - parseFloat(scs.paddingRight),
  };
  const brokenWords = (root) => {
    const out = [];
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      const words = n.textContent.trim().split(/\\s+/).filter(Boolean);
      if (!words.length || !shown(n.parentElement)) continue;
      const rg = document.createRange();
      rg.selectNodeContents(n);
      const lines = new Set(Array.from(rg.getClientRects())
        .filter((q) => q.width > 0).map((q) => Math.round(q.top)));
      if (lines.size > words.length) out.push([n.textContent, lines.size]);
    }
    return out;
  };
  // Every shown leaf that holds text, whatever its overflow: a cell with
  // overflow visible spills into its neighbour instead of clipping.
  const leaves = (root) => Array.from(root.querySelectorAll("*"))
    .filter((e) => shown(e) && e.children.length === 0
      && e.textContent.trim() !== "")
    .map((e) => ({cls: String(e.className), ...box(e)}));
  const list = document.getElementById("lv-mainchamps-list");
  const rows = Array.from(list.querySelectorAll(".lv-mc-row"))
    .filter(shown).map((li) => {
      const q = (s) => li.querySelector(s);
      return {
        row: box(li), tracks: getComputedStyle(li).gridTemplateColumns,
        placeholder: li.classList.contains("is-placeholder"),
        leaves: leaves(li), broken: brokenWords(li),
        player: box(q(".lv-mc-party-id")),
        name: box(q(".lv-mc-summoner-name")),
        champName: box(q(".lv-mc-party-champ")),
        mastery: box(q(".lv-mc-mastery")),
        recent: box(q(".lv-mc-recent")),
      };
    });
  const cats = Array.from(document.querySelectorAll(
    ".lv-mainchamps-categories .lv-mc-cats-party .lv-mc-cat"))
    .map((c) => ({shown: shown(c), ...box(c)}));
  return {
    tab: list.dataset.tab, content,
    card: box(sec.querySelector(".lobby-view-card-mainchamps")),
    rows, cats,
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
            " && !!document.getElementById('lv-mc-tab-party')",
            timeout=10_000,
        )
        page.click("#lv-mc-tab-party")
        page.wait_for_function(
            "() => { const l = document.getElementById('lv-mainchamps-list');"
            " return !!l && l.dataset.tab === 'party'"
            " && l.querySelectorAll('.lv-mc-row[data-member-idx]').length"
            " === 3; }",
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
    mock_server._store["data"] = {"lcu": {"lobby": _LOBBY,
                                          "party_mains": _PARTY_MAINS}}
    try:
        return {s: _read(pw_browser, mock_server.url, s)
                for s in _NARROW + _WIDE}
    finally:
        mock_server._store["data"] = {}


def _rows(got, size):
    assert got["tab"] == "party", (size, got["tab"])
    rows = got["rows"]
    # Three member cards plus one placeholder slot; the cards are real.
    assert len(rows) == 4, (size, len(rows))
    assert [r["placeholder"] for r in rows] == [False, False, False, True]
    assert rows[0]["name"]["text"] == "QuietStormRider1", rows[0]["name"]
    return rows


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_mains_card_fits_the_view(measured, size):
    got = measured[size]
    card, content = got["card"], got["content"]
    assert card["l"] >= content["l"] - 0.5, (size, card, content)
    assert card["r"] <= content["r"] + 0.5, (size, card, content)
    assert card["sw"] <= card["cw"] + 1, (size, card)


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_no_party_row_scrolls_or_cuts_a_value(measured, size):
    for i, row in enumerate(_rows(measured[size], size)):
        assert row["row"]["sw"] <= row["row"]["cw"] + 1, (size, i, row["row"])
        assert not row["broken"], (size, i, row["broken"])
        for leaf in row["leaves"]:
            if "lv-mc-summoner-name" in leaf["cls"]:
                continue
            assert leaf["sw"] <= leaf["cw"] + 1, (size, i, leaf)
            assert leaf["l"] >= row["row"]["l"] - 0.5, (size, i, leaf)
            assert leaf["r"] <= row["row"]["r"] + 0.5, (size, i, leaf)


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_player_name_shows_whole_or_keeps_6em(measured, size):
    for i, row in enumerate(_rows(measured[size], size)):
        n = row["name"]
        assert n["sw"] <= n["cw"] + 1 or n["w"] >= 6 * n["em"] - 0.5, \
            (size, i, n)
    rows = _rows(measured[size], size)
    # The short names never need an ellipsis.
    for i in (1, 2):
        assert rows[i]["name"]["sw"] <= rows[i]["name"]["cw"] + 1, \
            (size, i, rows[i]["name"])


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_player_spans_under_mastery_and_recent(measured, size):
    for i, row in enumerate(_rows(measured[size], size)):
        p, m, r = row["player"], row["mastery"], row["recent"]
        assert abs(m["t"] - r["t"]) < 0.5 or abs(
            (m["t"] + m["b"]) - (r["t"] + r["b"])) < 1, (size, i, m, r)
        assert m["r"] <= r["l"], (size, i, m, r)
        assert p["t"] >= max(m["b"], r["b"]) - 0.5, (size, i, p, m, r)
        assert abs(p["l"] - m["l"]) < 0.5, (size, i, p, m)
        assert abs(p["r"] - r["r"]) < 0.5, (size, i, p, r)
        cn = row["champName"]
        assert cn["sw"] <= cn["cw"] + 1, (size, i, cn)


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_headers_sit_over_their_cells(measured, size):
    got = measured[size]
    cats = got["cats"]
    assert [c["text"] for c in cats] == ["", "Player", "Mastery", "Recent"]
    assert not cats[1]["shown"], (size, cats[1])
    row = _rows(got, size)[0]
    for cat, cell in ((cats[2], row["mastery"]), (cats[3], row["recent"])):
        assert cat["shown"], (size, cat)
        assert cat["sw"] <= cat["cw"] + 1, (size, cat)
        # The header row is inset 4px, a row 7px (padding + border), so
        # the edges differ by a few px; each header's centre lies in its
        # cell and the two centres stay within 4px.
        mid = (cat["l"] + cat["r"]) / 2
        cmid = (cell["l"] + cell["r"]) / 2
        assert cell["l"] <= mid <= cell["r"], (size, cat, cell)
        assert abs(mid - cmid) <= 4, (size, cat, cell)
        assert cat["r"] <= got["card"]["r"] + 0.5, (size, cat, got["card"])


@pytest.mark.parametrize("size", _WIDE, ids=_WIDE_IDS)
def test_desktop_keeps_four_tracks_on_one_line(measured, size):
    got = measured[size]
    assert all(c["shown"] for c in got["cats"][1:]), (size, got["cats"])
    for i, row in enumerate(_rows(got, size)):
        assert len(row["tracks"].split()) == 4, (size, i, row["tracks"])
        p, m, r = row["player"], row["mastery"], row["recent"]
        assert p["r"] <= m["l"] and m["r"] <= r["l"], (size, i, p, m, r)
        assert p["b"] > m["t"] and m["b"] > p["t"], (size, i, p, m)
