"""
tests/snapshot_panels/test_lobby_mains_top8_narrow_reflow.py
At 720 px and under (300% zoom of the 1920x920 baseline is 640 wide, 400% is
480; WCAG 1.4.10 reflows at 320) the Pre-Game Lobby's MAINS and TOP 8 cards
fit the view and no value in them is cut (s144 lane uiux, RM-1776;
RM-1775 did the QUEUE and PARTY cards, pinned by
test_lobby_narrow_reflow.py).

Data. The ui_mock lobby fixture's `mains` and `top8` keys never reach the
renderers (_renderMains reads state.latest.lcu.main_champs, _top8Load reads
state.latest.lcu.top8 or /api/top8), so under plain ?ui_mock=1 both cards
show placeholders and hide this defect. Here the mock /api/state carries a
Top 8 and a YOUR MAINS list in the dashboard/routes_lobby_aux.py response
shapes: a 16-character Riot ID name (the Riot ID name cap), a ranked entry
with LP, an unranked one ("LVL 412 : Unranked"), a tag, five empty slots,
and four mains with three-digit game counts. Every Riot ID is synthetic
(RM-906).

Measured before the fix (headless Chromium): the nine-track TOP 8 row
shrank every cell - the rank pill showed 93 of its 157 px at 640, 52 at
480, 10 at 320, a 16-character name 12 of 130 px at 320 - and the YOUR
MAINS FORM cells ran 33 px past their row at 360, so RM-1775 held both
cards at their content width (MAINS 302 px, past the view at 360 and 320).

Contract pinned here at 640x900, 480x800, 360x740 and 320x640:
  - the MAINS and TOP 8 cards lie inside the view's content box;
  - a TOP 8 row does not scroll sideways; games, role and rank are never
    cut; the name keeps at least 6em (or its whole text) and the tag 4em
    (or its whole text); name, games and role share the first line and the
    tag starts below it; the dot, invite, reorder and remove controls share
    one line at the row's right edge, the 26 px action boxes intact, and
    the search row's add button lines up under the invite buttons;
  - no TOP 8 overlay takes the centre of a name, games, role or rank cell;
  - a YOUR MAINS row does not scroll sideways, no text in it is cut or
    broken inside a word, FORM sits under RECENT and OVERALL, the RECENT
    and OVERALL headers sit over their cells, the FORM header is hidden,
    and the copy button keeps its 22 px box; at 400 px and under the copy
    button sits under the icon (a 50 px icon column).
The view stops scrolling sideways at 640 and 480. At 360 and 320 the PARTY
card's duo-synergy block (RM-881, the queue lane's) still scrolls it, so
those two are strict xfails that turn red when that fix lands.
Above the line (722x900) both cards keep the desktop templates.
"""
import json

import pytest

from tests.snapshot_panels import _webfont_stub
from tests.snapshot_panels.conftest import _WS_STUB

_NARROW = ((640, 900), (480, 800), (360, 740), (320, 640))
_WIDE = (722, 900)
_IDS = [str(s[0]) for s in _NARROW]

_TOP8 = [
    {"riot_id": "QuietStormRider1#NA1", "summoner_name": "QuietStormRider1",
     "games_with_me": 142, "preferred_role": "UTILITY", "is_online": True,
     "rank": {"tier": "DIAMOND", "division": "II", "lp": 67},
     "user_tag": "duo main"},
    {"riot_id": "Brawler#NA1", "summoner_name": "Brawler",
     "games_with_me": 88, "preferred_role": "JUNGLE", "is_online": False,
     "rank": {"tier": "PLATINUM", "division": "IV", "lp": 0}},
    {"riot_id": "Alpha#AAA", "summoner_name": "Alpha",
     "games_with_me": 7, "preferred_role": "MIDDLE", "is_online": True,
     "rank": None, "summoner_level": 412},
]


def _champ(name, result, kda, games, wins, total_kda, kp, dmg, cspm):
    return {"name": name, "last_match": {"result": result, "kda": kda},
            "overall": {"games": games, "wins": wins,
                        "losses": games - wins, "total_kda": total_kda},
            "averaged": {"kp": kp, "dmg": dmg, "cs_per_min": cspm}}


_MAINS = {"champions": [
    _champ("Jinx", "WIN", "12/4/8", 124, 68, "8.3/4.1/6.7", 58.2, 18500, 7.8),
    _champ("Vayne", "LOSS", "4/9/3", 24, 10, "5.1/6.2/4.0", 41.0, 21400, 8.4),
    _champ("Tristana", "WIN", "10/2/11", 311, 170, "7.9/4.4/6.0", 62.5,
           24800, 8.1),
    _champ("Caitlyn", "LOSS", "3/7/5", 9, 4, "6.0/5.5/5.9", 47.3, 15200, 7.2),
]}

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
  const shown = (e) => e && getComputedStyle(e).display !== "none"
    && e.getBoundingClientRect().width > 0;
  const box = (e) => {
    const r = e.getBoundingClientRect();
    return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width,
            h: r.height, sw: e.scrollWidth, cw: e.clientWidth};
  };
  const card = (k) => box(sec.querySelector(".lobby-view-card-" + k));
  const inner = (e) => {
    const r = e.getBoundingClientRect();
    const cs = getComputedStyle(e);
    return {l: r.left + parseFloat(cs.borderLeftWidth)
              + parseFloat(cs.paddingLeft),
            r: r.right - parseFloat(cs.borderRightWidth)
              - parseFloat(cs.paddingRight)};
  };
  const owns = (e) => {
    const r = e.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2,
                                          r.top + r.height / 2);
    return !!hit && (hit === e || e.contains(hit));
  };
  // A text node broken inside a word draws more line boxes than words.
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
  const cut = (root) => Array.from(root.querySelectorAll("*")).filter((e) =>
    shown(e) && getComputedStyle(e).overflowX !== "visible"
    && e.scrollWidth > e.clientWidth + 1)
    .map((e) => [String(e.className).slice(0, 40), e.textContent.slice(0, 24),
                 e.clientWidth, e.scrollWidth]);
  const em = (e) => parseFloat(getComputedStyle(e).fontSize);
  const top8 = Array.from(sec.querySelectorAll("#lv-top8-list .lv-top8-row"))
    .filter(shown).map((li) => {
      const q = (s) => li.querySelector(s);
      const filled = !!q(".lv-top8-name");
      const ctl = Array.from(li.children).slice(5).filter(shown).map(box);
      const row = {
        filled, display: getComputedStyle(li).display,
        tracks: getComputedStyle(li).gridTemplateColumns,
        sw: li.scrollWidth, cw: li.clientWidth, inner: inner(li),
        ctl, cut: cut(li),
      };
      if (filled) {
        for (const k of ["name", "games", "role", "rank", "tag"]) {
          const e = q(".lv-top8-" + k);
          row[k] = {...box(e), em: em(e)};
        }
        const t = q(".lv-top8-tag-text");
        row.tagText = {...box(t), em: em(t)};
        row.invite = box(q('[data-action="invite"]'));
        row.remove = box(q('[data-action="remove"]'));
      }
      return row;
    });
  const srch = sec.querySelector("#lv-top8-search");
  const search = {
    ...box(srch), inner: inner(srch),
    display: getComputedStyle(srch).display,
    input: box(srch.querySelector(".lv-top8-search-input")),
    add: box(srch.querySelector("#lv-top8-search-add")),
  };
  const mainsRows = Array.from(sec.querySelectorAll(
    "#lv-mainchamps-list .lv-mc-row")).filter(shown).map((li) => {
    const q = (s) => li.querySelector(s);
    return {
      sw: li.scrollWidth, cw: li.clientWidth, row: box(li),
      tracks: getComputedStyle(li).gridTemplateColumns,
      cut: cut(li), broken: brokenWords(li),
      champDir: getComputedStyle(q(".lv-mc-champ")).flexDirection,
      champ: box(q(".lv-mc-champ")), copy: box(q(".lv-mc-copy")),
      recent: box(q(".lv-mc-recent")), overall: box(q(".lv-mc-overall")),
      form: box(q(".lv-mc-form")),
    };
  });
  const cats = Array.from(sec.querySelectorAll(
    ".lv-mainchamps-categories .lv-mc-cats-you .lv-mc-cat"))
    .map((c) => ({shown: getComputedStyle(c).display !== "none",
                  text: c.textContent.trim(), ...box(c)}));
  // Hit ownership last: elementFromPoint sees only the viewport, so each
  // cell is scrolled into view first, after every geometry read above.
  const cells = Array.from(sec.querySelectorAll("#lv-top8-list .lv-top8-row"))
    .filter(shown).filter((li) => li.querySelector(".lv-top8-name"));
  cells.forEach((li) => {
    const row = top8[Array.from(li.parentElement.children).indexOf(li)];
    for (const k of ["name", "games", "role", "rank"]) {
      const e = li.querySelector(".lv-top8-" + k);
      e.scrollIntoView({block: "center", inline: "nearest"});
      row[k].owns = owns(e);
    }
  });
  return {
    content, view: {sw: sec.scrollWidth, cw: sec.clientWidth},
    cards: {mainchamps: card("mainchamps"), friends: card("friends")},
    top8, search, mainsRows, cats,
    catsBox: box(sec.querySelector(".lv-mc-cats-you")),
  };
}"""


# RM-2041 (s154), two host facts this module used to read.
#
# 1. The YOUR MAINS rows have two sources: the fixture's lcu.main_champs and
# the /api/mains hydrate (dashboard/routes_lobby_aux.py). When the champion
# index lands before the first state envelope, _renderMains (web/js/main.js)
# finds no lcu.main_champs and fires the hydrate; the plain mock answers it {},
# and if that reply lands after the lcu-fed render, its callback draws the
# empty placeholder over the four rows until the next state poll, seconds
# later. On Windows the state lands first and the hydrate never fires; on the
# hosted Linux runner it raced: run 42427610342 read no rows at 480 and 320,
# run 42427673121 none at 480 (delaying the state 400 ms and the hydrate
# 1200 ms on Windows wipes the rows for about 5 s). The live server answers
# /api/mains with the mains themselves, so here it answers with the same four:
# whichever source lands last draws the same rows.
#
# 2. The RECENT KDA and the OVERALL W - L are set in "SF Mono", Consolas,
# monospace, which the RM-1078 stub does not cover: Consolas on Windows,
# DejaVu Sans Mono (0.05em a glyph wider) on the runner, where run
# 42427673121 read the "10/2/11" RECENT cell 69 px wide in its 66 px box at
# 320 (a 0.6em mono face on Windows reads the same 66 / 69). So every host
# gets a stub face as "SF Mono" with Consolas's advance (1126 / 2048 em, 550
# units): the glyph widths Windows draws, from a font the test serves.
_MAINS_REPLY = json.dumps({"ok": True, "puuid": "",
                           "main_champs": _MAINS["champions"]})
_MONO_ADVANCE = 550
_MONO_URL = "/__rm2041__/mono-stub.ttf"


def _mono_stub_ttf():
    saved = _webfont_stub.ADVANCE
    _webfont_stub.ADVANCE = _MONO_ADVANCE
    try:
        return _webfont_stub.build_stub_ttf()
    finally:
        _webfont_stub.ADVANCE = saved


_MONO_TTF = _mono_stub_ttf()
_MONO_FACE = """(() => {
  const add = () => {
    const s = document.createElement("style");
    s.textContent = '@font-face { font-family: "SF Mono"; font-style: normal;'
      + ' font-weight: 100 900; src: url("URL") format("truetype"); }';
    (document.head || document.documentElement).appendChild(s);
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", add);
  } else {
    add();
  }
})();""".replace("URL", _MONO_URL)
# Anchor: the stand-in is the face that drew the mains. Every KDA and W - L
# cell names "SF Mono" first, and that face is loaded and draws (a 40 px probe
# reads the same width over a serif and a sans-serif fallback); a stylesheet
# that stops naming "SF Mono" would hand the cells back to the host's face.
_MONO_USED = """() => {
  const cells = Array.from(document.querySelectorAll(
    "#lv-mainchamps-list .lv-mc-kda, #lv-mainchamps-list .lv-mc-wl"));
  const first = (e) => getComputedStyle(e).fontFamily.split(",")[0].trim()
    .replace(/"/g, "");
  const width = (fam) => {
    const s = document.createElement("span");
    s.style.cssText = "position: absolute; white-space: pre; font: 400 40px "
      + fam;
    s.textContent = "iiiiMMMM";
    document.body.appendChild(s);
    const w = s.getBoundingClientRect().width;
    s.remove();
    return w;
  };
  return {
    cells: cells.length,
    named: cells.every((e) => first(e) === "SF Mono"),
    loaded: Array.from(document.fonts).some((f) =>
      f.family.replace(/"/g, "") === "SF Mono" && f.status === "loaded"),
    draws: Math.abs(width('"SF Mono", serif')
      - width('"SF Mono", sans-serif')) < 0.5,
  };
}"""


def _read(pw_browser, url, size):
    ctx = pw_browser.new_context(
        ignore_https_errors=True,
        viewport={"width": size[0], "height": size[1]},
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.add_init_script(_MONO_FACE)
    page.route("**" + _MONO_URL, lambda route: route.fulfill(
        status=200, body=_MONO_TTF, content_type="font/ttf"))
    page.route("**/api/mains*", lambda route: route.fulfill(
        status=200, body=_MAINS_REPLY, content_type="application/json"))
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
        mono = page.evaluate(_MONO_USED)
    finally:
        ctx.close()
    assert not errors, f"page errors at {size}: {errors[:3]}"
    assert mono == {"cells": 8, "named": True, "loaded": True,
                    "draws": True}, (
        f"{size}: the SF Mono stand-in did not draw the mains: {mono}")
    return got


@pytest.fixture(scope="module")
def narrow(mock_server, pw_browser):
    mock_server._store["data"] = {"lcu": {"top8": _TOP8,
                                          "main_champs": _MAINS}}
    try:
        return {s: _read(pw_browser, mock_server.url, s) for s in _NARROW}
    finally:
        mock_server._store["data"] = {}


@pytest.fixture(scope="module")
def wide(mock_server, pw_browser):
    mock_server._store["data"] = {"lcu": {"top8": _TOP8,
                                          "main_champs": _MAINS}}
    try:
        return _read(pw_browser, mock_server.url, _WIDE)
    finally:
        mock_server._store["data"] = {}


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
@pytest.mark.parametrize("card", ("mainchamps", "friends"))
def test_mains_and_top8_cards_fit_the_view(narrow, size, card):
    r = narrow[size]
    assert r is not None, size
    b = r["cards"][card]
    assert b["l"] >= r["content"]["l"] - 1, (size, card, b, r["content"])
    assert b["r"] <= r["content"]["r"] + 1, (size, card, b, r["content"])


@pytest.mark.parametrize("size", _NARROW[:2], ids=_IDS[:2])
def test_view_does_not_scroll_sideways(narrow, size):
    v = narrow[size]["view"]
    assert v["sw"] <= v["cw"] + 1, (size, v)


@pytest.mark.xfail(strict=True, reason=(
    "RM-881 (queue lane): the PARTY card's duo-synergy win-rate cells"
    " overflow their 0 px boxes at 360 and under, so the view still"
    " scrolls sideways there"))
@pytest.mark.parametrize("size", _NARROW[2:], ids=_IDS[2:])
def test_view_does_not_scroll_sideways_at_360_and_under(narrow, size):
    v = narrow[size]["view"]
    assert v["sw"] <= v["cw"] + 1, (size, v)


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_top8_rows_cut_no_value(narrow, size):
    rows = narrow[size]["top8"]
    assert len(rows) == 8 and sum(r["filled"] for r in rows) == 3, rows
    for row in rows:
        assert row["sw"] <= row["cw"] + 1, (size, row)
        if not row["filled"]:
            continue
        for k in ("games", "role", "rank"):
            c = row[k]
            assert c["sw"] <= c["cw"] + 1, (size, k, c)
        n = row["name"]
        assert n["w"] + 0.5 >= min(n["sw"], 6 * n["em"]), (size, n)
        t = row["tagText"]
        assert t["w"] + 0.5 >= min(t["sw"], 4 * t["em"]), (size, t)
        # Only the name and the tag text may ellipsize.
        for c in row["cut"]:
            assert ("lv-top8-name" in c[0]
                    or c[0].startswith("lv-top8-tag-text")), (size, c)


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_top8_rows_are_two_line_with_controls_at_the_right(narrow, size):
    r = narrow[size]
    for row in r["top8"]:
        ctl = row["ctl"]
        # dot (or spacer) + invite + reorder + remove (placeholders carry
        # spacers, which are 0 px tall but still laid out on that line)
        assert len(ctl) == 4, (size, row)
        mids = [c["t"] + c["h"] / 2 for c in ctl]
        assert max(mids) - min(mids) < 1.5, (size, ctl)
        assert abs(ctl[-1]["r"] - row["inner"]["r"]) < 1, (size, row)
        if not row["filled"]:
            continue
        n, g, ro, t = row["name"], row["games"], row["role"], row["tag"]
        assert abs(n["t"] - g["t"]) < 1 and abs(n["t"] - ro["t"]) < 1, \
            (size, n, g, ro)
        assert t["t"] >= n["b"] - 0.5, (size, n, t)
        for b in (row["invite"], row["remove"]):
            assert abs(b["w"] - 26) < 0.5 and abs(b["h"] - 26) < 0.5, \
                (size, b)
        assert abs(r["search"]["add"]["l"] - row["invite"]["l"]) < 1, \
            (size, r["search"]["add"], row["invite"])


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_top8_overlays_leave_the_value_cells_alone(narrow, size):
    for row in narrow[size]["top8"]:
        if not row["filled"]:
            continue
        for k in ("name", "games", "role", "rank"):
            assert row[k]["owns"], (size, k, row[k])


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_top8_search_row_fits(narrow, size):
    s = narrow[size]["search"]
    assert s["sw"] <= s["cw"] + 1, (size, s)
    assert s["input"]["h"] >= 42 - 0.5, (size, s["input"])
    assert s["input"]["l"] >= s["inner"]["l"] - 0.5, (size, s)
    assert abs(s["add"]["w"] - 26) < 0.5, (size, s["add"])


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_mains_rows_cut_and_break_nothing(narrow, size):
    rows = narrow[size]["mainsRows"]
    assert len(rows) == 4, rows
    for row in rows:
        assert row["sw"] <= row["cw"] + 1, (size, row)
        assert not row["cut"], (size, row["cut"])
        assert not row["broken"], (size, row["broken"])
        # The champ cell's scrollWidth counts the copy button's 44 px
        # ::before hit overlay (desktop too), so the copy box is checked.
        assert row["copy"]["r"] <= row["row"]["r"] + 0.5, (size, row)
        for k in ("recent", "overall", "form"):
            c = row[k]
            assert c["sw"] <= c["cw"] + 1, (size, k, c)
            assert c["r"] <= row["row"]["r"] + 0.5, (size, k, c, row["row"])
        assert row["form"]["t"] >= max(row["recent"]["b"],
                                       row["overall"]["b"]) - 0.5, (size, row)
        # The copy button keeps its 22 px box, stacked or beside the icon
        # (S144-U-177: the 76 px column now holds 50 + 4 + 22; pinned at
        # every width on both tabs by test_lobby_mains_copy_box.py).
        assert abs(row["copy"]["w"] - 22) < 0.5, (size, row["copy"])
        assert abs(row["copy"]["h"] - 22) < 0.5, (size, row["copy"])


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_mains_headers_sit_over_their_cells(narrow, size):
    r = narrow[size]
    cats = {c["text"]: c for c in r["cats"] if c["text"]}
    assert not cats["Form"]["shown"], cats["Form"]
    row = r["mainsRows"][0]
    for label, cell in (("Recent", "recent"), ("Overall", "overall")):
        c = cats[label]
        assert c["shown"] and c["sw"] <= c["cw"] + 1, (size, c)
        mid = (c["l"] + c["r"]) / 2
        cmid = (row[cell]["l"] + row[cell]["r"]) / 2
        assert abs(mid - cmid) < 2, (size, label, c, row[cell])
    assert r["catsBox"]["sw"] <= r["catsBox"]["cw"] + 1, (size, r["catsBox"])


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_mains_copy_button_stacks_only_at_400_and_under(narrow, size):
    # An empty row list would pass the loop below vacuously.
    assert len(narrow[size]["mainsRows"]) == 4, narrow[size]["mainsRows"]
    for row in narrow[size]["mainsRows"]:
        want = "column" if size[0] <= 400 else "row"
        assert row["champDir"] == want, (size, row["champDir"])
        icon_col = float(row["tracks"].split()[0][:-2])
        assert icon_col == (50 if size[0] <= 400 else 76), (size, row)


def test_desktop_templates_are_unchanged_above_the_line(wide):
    # Empty lists would pass the loops below vacuously.
    assert len(wide["top8"]) == 8 and len(wide["mainsRows"]) == 4, wide
    for row in wide["top8"]:
        assert row["display"] == "grid", row
        tracks = row["tracks"].split()
        assert len(tracks) == 9, row
        assert tracks[5:] == ["14px", "26px", "26px", "26px"], row
    for row in wide["mainsRows"]:
        tracks = row["tracks"].split()
        assert len(tracks) == 4 and tracks[0] == "76px", row
        assert row["champDir"] == "row", row
    assert wide["search"]["display"] == "grid", wide["search"]
    cats = {c["text"]: c for c in wide["cats"] if c["text"]}
    assert cats["Form"]["shown"], cats
    assert wide["search"]["input"]["w"] > 300, wide["search"]
