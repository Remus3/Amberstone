"""
tests/snapshot_panels/test_lobby_mains_recent_cell.py
The Pre-Game Lobby MAINS card's RECENT cell, on both tabs (YOUR MAINS and
PARTY MAINS): the WIN / LOSS word takes its colour, and a two-digit KDA
shows whole at every window width (s144 lane uiux, S144-U-194; the U-180
FUTURE row "a KDA wider than about 60 px at 320 was not measured").

Data. The mock /api/state carries YOUR MAINS (lcu.main_champs) and PARTY
MAINS (lcu.lobby + lcu.party_mains) in the dashboard/routes_lobby_aux.py
and dashboard/_party_mains.py shapes. dashboard/routes_lobby_aux.py
writes last_match.result as "WIN" / "LOSS" and last_match.kda as
"<k>/<d>/<a>". The KDA values are real-shaped: in data/rewind_history.db
(30440 participant rows) 7051 KDAs are 8 characters ("24/14/20") and 9224
are 7 ("15/10/7"), so more than half are 7 or 8 characters. All names are
synthetic (RM-906).

Measured before the fix (headless Chromium, ?ui_mock=1#lobby):
  - web/js/main.js writes the result class as lv-mc-result-win /
    lv-mc-result-loss (the word lower-cased) on both tabs, while
    web/css/panels/header.css styled lv-mc-result-won / lv-mc-result-lost,
    so no rule ever matched: WIN and LOSS both rendered in the inherited
    --text colour since the s162 Lobby v2 redesign;
  - at 320 the RECENT cell is 61.4 px wide on both tabs and a monospace
    KDA does not break (UAX 14 keeps "24/14/20" one numeric run), so an 8
    character KDA (72.5 px) ran 11 px past its cell and past the row's
    right edge, and a 7 character one (63.5 px) 2 px;
  - with the class fixed, plain --bad measured 3.28 (arcane), 3.31
    (moonlit), 3.66 (hextech), 3.79 (ember, bloodmoon):1 on the row's
    --surface-alt, under AA, so LOSS takes the lift.

Contract pinned on both tabs:
  - WIN renders in the resolved --good colour, LOSS in the RM-1550 lift
    of --bad (mixed 30 percent toward --text in oklab, still a red), the
    "-" placeholder in neither (arcane, 1920x920);
  - in every theme the WIN and LOSS words keep WCAG AA (4.5:1; 16 px bold
    is not large text) against the row's own --surface-alt fill;
  - on YOUR MAINS the OVERALL W - L counts on the same row use the same
    two colours and keep AA too (the losses count was plain --bad, 3.28:1
    in arcane, a second, darker red beside the lifted LOSS);
  - at 1920, 722, 640, 480, 400, 360 and 320 every KDA's text lies inside
    its RECENT cell, and a KDA that wraps breaks only after a slash; from
    360 up it stays on one line.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_lobby_mains_top8_narrow_reflow import (
    _SETTLE,
    _TOP8,
)
from tests.snapshot_panels.test_lobby_party_mains_narrow_reflow import _LOBBY

_SIZES = ((1920, 920), (722, 900), (640, 900), (480, 800), (400, 740),
          (360, 740), (320, 640))
_ONE_LINE_MIN = 360
_TABS = ("you", "party")
_THEMES = ("arcane", "hextech", "terminal", "ember", "bloodmoon", "moonlit")
_AA = 4.5

_KDAS = ("24/14/20", "15/10/7", "12/13/59")


def _champ(name, result, kda):
    return {"name": name, "last_match": {"result": result, "kda": kda},
            "overall": {"games": 40, "wins": 21, "losses": 19,
                        "total_kda": "8.3/4.1/6.7"},
            "averaged": {"kp": 58.2, "dmg": 18500, "cs_per_min": 7.8}}


_MAINS = {"champions": [
    _champ("Jinx", "WIN", _KDAS[0]),
    _champ("Vayne", "LOSS", _KDAS[1]),
    _champ("Tristana", "WIN", _KDAS[2]),
    {"name": "Caitlyn", "last_match": {},
     "overall": {"games": 9, "wins": 4, "losses": 5,
                 "total_kda": "6.0/5.5/5.9"},
     "averaged": {"kp": 47.3, "dmg": 15200, "cs_per_min": 7.2}},
]}

_PARTY_MAINS = [
    {"name": "Jinx", "player": "QuietStormRider1", "mastery_level": 112,
     "mastery_points": 2456789,
     "last_match": {"result": "WIN", "kda": _KDAS[0]}},
    {"name": "Aurelion Sol", "player": "Brawler", "mastery_level": 7,
     "mastery_points": 843210,
     "last_match": {"result": "LOSS", "kda": _KDAS[1]}},
    {"name": "Nunu & Willump", "player": "Alpha", "mastery_level": 34,
     "mastery_points": 1000,
     "last_match": {"result": "WIN", "kda": _KDAS[2]}},
]

_STATE = {"lcu": {"top8": _TOP8, "main_champs": _MAINS, "lobby": _LOBBY,
                  "party_mains": _PARTY_MAINS}}

# The LOSS word's colour: the RM-1550 lift of --bad (header.css).
_LOSS_EXPR = "color-mix(in oklab, var(--bad) 70%, var(--text))"

# Resolve any CSS colour (oklch included) to sRGB bytes through a canvas.
_READ = """(lossExpr) => {
  const cv = document.createElement("canvas"); cv.width = cv.height = 1;
  const cx = cv.getContext("2d", {willReadFrequently: true});
  const rgb = (c) => {
    cx.clearRect(0, 0, 1, 1); cx.fillStyle = "#000"; cx.fillStyle = c;
    cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2]];
  };
  const tok = (expr) => {
    const s = document.createElement("span");
    s.style.color = expr;
    document.body.appendChild(s);
    const c = getComputedStyle(s).color;
    s.remove();
    return rgb(c);
  };
  const list = document.getElementById("lv-mainchamps-list");
  const rows = Array.from(list.querySelectorAll(".lv-mc-row")).map((li) => {
    const res = li.querySelector(".lv-mc-result");
    const kda = li.querySelector(".lv-mc-kda");
    const cell = li.querySelector(".lv-mc-recent").getBoundingClientRect();
    const rr = li.getBoundingClientRect();
    // One rect per character of the KDA text, across every text node
    // (a <wbr> splits the text into several).
    const chars = [];
    const walk = document.createTreeWalker(kda, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      for (let i = 0; i < n.textContent.length; i += 1) {
        const rg = document.createRange();
        rg.setStart(n, i); rg.setEnd(n, i + 1);
        const q = rg.getBoundingClientRect();
        chars.push({c: n.textContent[i], l: q.left, r: q.right,
                    t: Math.round(q.top), w: q.width});
      }
    }
    // YOUR MAINS only: the OVERALL W - L counts on the same row.
    const w = li.querySelector(".lv-mc-wl .lv-mc-w");
    const l = li.querySelector(".lv-mc-wl .lv-mc-l");
    return {
      placeholder: li.classList.contains("is-placeholder"),
      wins: w ? rgb(getComputedStyle(w).color) : null,
      losses: l ? rgb(getComputedStyle(l).color) : null,
      result: res.textContent.trim(),
      color: rgb(getComputedStyle(res).color),
      surface: rgb(getComputedStyle(li).backgroundColor),
      kda: kda.textContent,
      chars,
      cell: {l: cell.left, r: cell.right},
      row: {l: rr.left, r: rr.right},
    };
  });
  return {tab: list.dataset.tab, good: tok("var(--good)"),
          loss: tok(lossExpr), text: tok("var(--text)"), rows};
}"""


def _lum(c) -> float:
    def ch(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def _ratio(a, b) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _read(pw_browser, url, size, tab, theme="arcane"):
    ctx = pw_browser.new_context(
        ignore_https_errors=True,
        viewport={"width": size[0], "height": size[1]},
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(url + f"/?ui_mock=1&theme={theme}#lobby",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "document.body.dataset.view === 'lobby'"
            " && !!document.getElementById('lv-mc-tab-party')",
            timeout=10_000,
        )
        page.click(f"#lv-mc-tab-{tab}")
        page.wait_for_function(
            "(tab) => { const l = document.getElementById("
            "'lv-mainchamps-list'); return !!l && l.dataset.tab === tab"
            " && l.querySelectorAll('.lv-mc-kda').length >= 3"
            " && Array.from(l.querySelectorAll('.lv-mc-kda'))"
            ".some((k) => k.textContent.includes('/')); }",
            arg=tab, timeout=10_000,
        )
        page.evaluate(_SETTLE)
        got = page.evaluate(_READ, _LOSS_EXPR)
    finally:
        ctx.close()
    assert not errors, f"page errors at {size} {tab}: {errors[:3]}"
    assert got["tab"] == tab, (size, tab, got["tab"])
    return got


@pytest.fixture(scope="module")
def measured(mock_server, pw_browser):
    mock_server._store["data"] = _STATE
    try:
        return {(s, t): _read(pw_browser, mock_server.url, s, t)
                for s in _SIZES for t in _TABS}
    finally:
        mock_server._store["data"] = {}


@pytest.fixture(scope="module")
def themed(mock_server, pw_browser):
    mock_server._store["data"] = _STATE
    try:
        return {(th, t): _read(pw_browser, mock_server.url, _SIZES[0], t, th)
                for th in _THEMES for t in _TABS}
    finally:
        mock_server._store["data"] = {}


def _data_rows(got):
    rows = [r for r in got["rows"] if "/" in r["kda"]]
    # Three KDAs per tab; an empty measurement must not pass.
    assert sorted(r["kda"] for r in rows) == sorted(_KDAS), got["rows"]
    return rows


@pytest.mark.parametrize("tab", _TABS)
def test_result_word_takes_its_colour(measured, tab):
    got = measured[(_SIZES[0], tab)]
    words = {r["result"] for r in got["rows"]}
    assert {"WIN", "LOSS", "-"} <= words, words
    for r in got["rows"]:
        if r["result"] == "WIN":
            assert r["color"] == got["good"], (tab, r["color"], got["good"])
        elif r["result"] == "LOSS":
            assert r["color"] == got["loss"], (tab, r["color"], got["loss"])
            # Still a red, not the plain text colour.
            assert r["color"] != got["text"], (tab, r["color"])
            assert r["color"][0] > max(r["color"][1:]) + 40, (tab, r)
        else:
            assert r["color"] not in (got["good"], got["loss"]), (tab, r)


@pytest.mark.parametrize("theme", _THEMES)
@pytest.mark.parametrize("tab", _TABS)
def test_result_word_keeps_aa_on_its_row(themed, tab, theme):
    got = themed[(theme, tab)]
    seen = set()
    for r in got["rows"]:
        if r["result"] not in ("WIN", "LOSS"):
            continue
        seen.add(r["result"])
        want = got["good"] if r["result"] == "WIN" else got["loss"]
        assert r["color"] == want, (theme, tab, r["result"], r["color"])
        ratio = _ratio(r["color"], r["surface"])
        assert ratio >= _AA, (
            f"{theme} {tab}: {r['result']} {r['color']} on --surface-alt"
            f" {r['surface']} is {ratio:.2f}:1")
    assert seen == {"WIN", "LOSS"}, (theme, tab, seen)


@pytest.mark.parametrize("theme", _THEMES)
def test_overall_win_loss_counts_match_and_keep_aa(themed, theme):
    got = themed[(theme, "you")]
    rows = [r for r in got["rows"] if r["wins"] and r["losses"]]
    # Four YOUR MAINS rows carry OVERALL; an empty measurement must not pass.
    assert len(rows) == 4, (theme, got["rows"])
    for r in rows:
        assert r["wins"] == got["good"], (theme, r["wins"], got["good"])
        assert r["losses"] == got["loss"], (theme, r["losses"], got["loss"])
        for name, c in (("W", r["wins"]), ("L", r["losses"])):
            ratio = _ratio(c, r["surface"])
            assert ratio >= _AA, (
                f"{theme}: OVERALL {name} {c} on --surface-alt"
                f" {r['surface']} is {ratio:.2f}:1")


@pytest.mark.parametrize("tab", _TABS)
@pytest.mark.parametrize("size", _SIZES, ids=[str(s[0]) for s in _SIZES])
def test_kda_shows_whole_inside_its_cell(measured, size, tab):
    for r in _data_rows(measured[(size, tab)]):
        assert "".join(c["c"] for c in r["chars"]) == r["kda"], r
        ink = [c for c in r["chars"] if c["w"] > 0]
        assert len(ink) == len(r["kda"]), (size, tab, r["kda"])
        lo = min(c["l"] for c in ink)
        hi = max(c["r"] for c in ink)
        assert lo >= r["cell"]["l"] - 0.5, (size, tab, r["kda"], lo, r)
        assert hi <= r["cell"]["r"] + 0.5, (
            f"{size[0]} {tab}: {r['kda']} ends at {hi:.1f}, its cell at"
            f" {r['cell']['r']:.1f}, its row at {r['row']['r']:.1f}")


@pytest.mark.parametrize("tab", _TABS)
@pytest.mark.parametrize("size", _SIZES, ids=[str(s[0]) for s in _SIZES])
def test_kda_breaks_only_after_a_slash(measured, size, tab):
    for r in _data_rows(measured[(size, tab)]):
        chars = r["chars"]
        lines = len({c["t"] for c in chars})
        if size[0] >= _ONE_LINE_MIN:
            assert lines == 1, (size, tab, r["kda"], lines)
        for a, b in zip(chars, chars[1:]):
            if b["t"] != a["t"]:
                assert a["c"] == "/", (
                    f"{size[0]} {tab}: {r['kda']} breaks after"
                    f" {a['c']!r}, not after a slash")
