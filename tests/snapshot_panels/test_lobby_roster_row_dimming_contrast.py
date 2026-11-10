"""
tests/snapshot_panels/test_lobby_roster_row_dimming_contrast.py
S144-U-237 (s144 uiux): every text line of the Pre-Game Lobby's two roster
lists - My Top 8 (#lv-top8-list) and the party roster (#lv-members-list) -
reaches its WCAG floor on its resolved surface in all six themes, in every
row state the Top 8 paints: online, offline (.is-offline, at rest and
hovered), unranked ("LVL n : Unranked", .lv-top8-rank-empty) and the empty
slot (.is-placeholder, "-" cells), plus the party roster's empty slot.

MEASURED headless under /?ui_mock=1#lobby at 1920x920 before the fix, with
ancestor opacity folded in (the shared _HELPERS read() does not fold it, so
test_lobby_text_contrast.py read these lines at full alpha and passed):
- the offline Top 8 row (opacity 0.72, cells in --dim over a red tint):
  name, games, role and tag 3.31 to 4.13:1; its rank pip 4.45; its
  unranked mark 2.36 to 2.78;
- the online unranked mark, --text-faint italic: 3.64 to 4.59:1, under 4.5
  in five themes (the same figures S144-U-202 fixed on the party row's
  .lv-party-empty, which this mark says it mirrors);
- the Top 8 empty slot "-" (row opacity 0.5): 3.93 to 4.80:1;
- the party empty slot "-" (row opacity 0.5 over --text-dim): 2.69 to
  2.97:1;
- the offline row's icon buttons (invite, reorder, remove): 3.98 to
  4.26:1, under 4.5 in five themes.
No documented exception covers them, and this program already rejected
dimming text by opacity because it sinks it under its floor (S144-U-235,
S144-U-236). Ruling: the rows drop the opacity; the offline row keeps its
red tint and --dim cells, the empty slots keep their dashed border, and
every "-" / unranked mark paints --text-dim, still under the --text names.

The ui_mock lobby fixture's own top8 block is not read (main.js
_top8Load hydrates from /api/top8), so this test answers /api/top8 itself
with SYNTHETIC entries (RM-906: no real ids) in the shape
dashboard/routes_lobby_aux.py documents.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _lum, _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_SHEET = "*, *::before, *::after { transition: none !important; }"

_TOP8 = {"ok": True, "entries": [
    {"riot_id": "Alpha#AAA", "summoner_name": "Alpha", "games_with_me": 41,
     "preferred_role": "TOP", "is_online": True, "user_tag": "duo",
     "rank": {"tier": "GOLD", "division": "II", "lp": 40}},
    {"riot_id": "Bravo#BBB", "summoner_name": "Bravo", "games_with_me": 12,
     "preferred_role": "JUNGLE", "is_online": False, "user_tag": "flex",
     "rank": {"tier": "PLATINUM", "division": "IV", "lp": 12}},
    {"riot_id": "Charlie#CCC", "summoner_name": "Charlie", "games_with_me": 3,
     "preferred_role": "UTILITY", "is_online": False, "rank": None,
     "summoner_level": 87},
    {"riot_id": "Delta#DDD", "summoner_name": "Delta", "games_with_me": 7,
     "preferred_role": "MIDDLE", "is_online": True, "rank": None,
     "summoner_level": 212},
]}

_MEASURE = """async () => {
  await document.fonts.ready;
""" + _HELPERS + """
  const alpha = (el) => {
    let a = 1;
    for (let n = el; n; n = n.parentElement) {
      a *= parseFloat(getComputedStyle(n).opacity);
    }
    return a;
  };
  const line = (el) => {
    const cs = getComputedStyle(el);
    const fg = rgba(cs.color);
    fg[3] *= alpha(el);
    const s = surface(el);
    const row = el.closest('li');
    return {row: row ? String(row.className) : '', cls: String(el.className),
            text: el.textContent.trim(), alpha: alpha(el),
            fg: s ? over(fg, s) : null, bg: s,
            px: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight, 10),
            inactive: !!el.closest(':disabled, [aria-disabled="true"]')};
  };
  const lines = (host) => [...host.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map(line);
  const top8 = document.getElementById('lv-top8-list');
  const party = document.getElementById('lv-members-list');
  const name = (who) => {
    const e = [...top8.querySelectorAll('.lv-top8-name')]
      .find((n) => n.textContent.trim() === who);
    return e ? line(e) : null;
  };
  const rowBg = (who) => {
    const e = [...top8.querySelectorAll('.lv-top8-name')]
      .find((n) => n.textContent.trim() === who);
    return e ? surface(e.closest('li')) : null;
  };
  const root = getComputedStyle(document.documentElement);
  return {
    theme: document.documentElement.dataset.theme || 'hextech',
    top8: lines(top8),
    party: [...party.querySelectorAll('.lobby-member-row.is-placeholder')]
      .flatMap(lines),
    alpha: name('Alpha'), bravo: name('Bravo'),
    alphaBg: rowBg('Alpha'), bravoBg: rowBg('Bravo'),
    dim: rgba(root.getPropertyValue('--text-dim').trim()),
  };
}"""

_HOVER = """async () => {
""" + _HELPERS + """
  const e = [...document.querySelectorAll('#lv-top8-list .lv-top8-name')]
    .find((n) => n.textContent.trim() === 'Bravo');
  let a = 1;
  for (let n = e; n; n = n.parentElement) {
    a *= parseFloat(getComputedStyle(n).opacity);
  }
  const fg = rgba(getComputedStyle(e).color); fg[3] *= a;
  const s = surface(e);
  return {fg: over(fg, s), bg: s,
          hovered: e.closest('li').matches(':hover')};
}"""


def _large(row) -> bool:
    return row["px"] >= 24 or (row["px"] >= 18.66 and row["weight"] >= 700)


def _measure(mock_server, pw_browser, theme):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 920}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route("**/api/top8*", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(_TOP8)))
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&theme={theme}#lobby",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "() => document.querySelectorAll("
            "'#lv-top8-list .lv-top8-name').length === 4"
            " && document.querySelector("
            "'#lv-members-list .lobby-member-row.is-placeholder')",
            timeout=10_000,
        )
        page.add_style_tag(content=_SHEET)
        got = page.evaluate(_MEASURE)
        page.hover("#lv-top8-list .lv-top8-row.is-offline .lv-top8-name")
        got["hover"] = page.evaluate(_HOVER)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return got


@pytest.fixture(scope="module")
def measured():
    return {}


def _got(measured, mock_server, pw_browser, theme):
    if theme not in measured:
        measured[theme] = _measure(mock_server, pw_browser, theme)
    return measured[theme]


@pytest.mark.parametrize("theme", _THEMES)
def test_every_roster_row_line_reaches_its_floor(theme, measured,
                                                 mock_server, pw_browser):
    got = _got(measured, mock_server, pw_browser, theme)
    assert got["theme"] == theme, "theme did not apply"
    rows = [r for r in got["top8"] + got["party"] if not r["inactive"]]
    # Anchor: every row state was read (an empty sweep would pass).
    states = {
        "offline": [r for r in rows if "is-offline" in r["row"]],
        "top8 empty": [r for r in rows
                       if "lv-top8-row is-placeholder" in r["row"]],
        "party empty": [r for r in rows if "lobby-member-row" in r["row"]],
        "unranked": [r for r in rows if "lv-top8-rank-empty" in r["cls"]],
    }
    for key, picked in states.items():
        assert picked, f"{theme}: no {key} line rendered"
    assert len(states["unranked"]) == 2, states["unranked"]
    assert {r["text"] for r in states["top8 empty"]} == {"-"}
    assert len(states["top8 empty"]) == 4 * 5, len(states["top8 empty"])
    low = []
    for r in rows:
        assert r["fg"] and r["bg"], f"no resolved surface under {r}"
        assert r["px"] >= 14, f"{r['cls']} {r['text']!r} at {r['px']}px"
        floor = 3.0 if _large(r) else 4.5
        ratio = _ratio(r["fg"], r["bg"])
        if ratio < floor:
            low.append((r["row"], r["cls"], r["text"], round(ratio, 2),
                        floor))
    assert not low, f"{theme}: {low}"


@pytest.mark.parametrize("theme", _THEMES)
def test_hovered_offline_row_reaches_aa(theme, measured, mock_server,
                                        pw_browser):
    hov = _got(measured, mock_server, pw_browser, theme)["hover"]
    assert hov["hovered"], "the offline row did not take :hover"
    ratio = _ratio(hov["fg"], hov["bg"])
    assert ratio >= 4.5, f"{theme}: hovered offline name {ratio:.2f}:1"


@pytest.mark.parametrize("theme", _THEMES)
def test_offline_and_empty_marks_stay_secondary(theme, measured,
                                                mock_server, pw_browser):
    """The lift must not flatten the roster. An offline friend still reads
    dimmer than an online one and keeps the red tint; an empty slot "-"
    and an unranked mark paint --text-dim and stay under the online name."""
    got = _got(measured, mock_server, pw_browser, theme)
    on, off = got["alpha"], got["bravo"]
    assert on and off, "online / offline Top 8 names not rendered"
    assert _lum(off["fg"]) < _lum(on["fg"]), (theme, off, on)
    # The offline row's surface leans red against the online row's.
    a, b = got["alphaBg"], got["bravoBg"]
    assert (b[0] - max(b[1], b[2])) > (a[0] - max(a[1], a[2])), (a, b)
    marks = [r for r in got["top8"] + got["party"]
             if r["text"] == "-" or "lv-top8-rank-empty" in r["cls"]]
    assert marks, "no empty / unranked mark rendered"
    for r in marks:
        assert all(abs(r["fg"][i] - got["dim"][i]) <= 3 for i in range(3)), (
            theme, r, got["dim"])
        assert _lum(r["fg"]) < _lum(on["fg"]), (theme, r)
