"""
tests/snapshot_panels/test_champ_select_personal_build_contrast.py
S144-U-234 (s144 uiux): every text line of the champ-select personal
best-build card (#csv-personal-build, web/js/panels/personal_build.js,
styled in web/css/panels/personal_build.css) reaches its WCAG floor on its
resolved surface, in all six themes, in every state the card can paint:
the positive / negative / zero lift, the thin-sample note, the usual-build
line and the three insight kinds (swap, winner, loser).

MEASURED headless at 1920x1080 before the fix (colours resolved by the
browser and composited over the stacked backgrounds, lane doc traps 3 and
4). The negative lift "-4" (.pbw-lift[data-sign="neg"], bare
--signal-bad, 18 px / 800, so NOT WCAG large text: bold large text starts
at 14 pt = 18.67 px, the 4.5:1 floor applies) on the card's --surface read
under AA in the themes where bare red is darkest. It is the one number on
the row that says the item LOSES. Ruling: the RM-1550 red-text lift,
color-mix(in oklab, var(--signal-bad) 70%, var(--text)), as S144-U-204 /
U-223; the negative bar fill keeps bare --signal-bad, so the row still
reads red by hue, and the guard pins that the lifted text stays red.

The card is driven by renderPersonalBuild on synthetic payloads (DDragon
catalogue item ids and names, no game data), in the real champ-select DOM
and CSS, as test_champ_select_view.py does.
"""
import pytest

from tests.snapshot_panels.conftest import _PERSONAL_BUILD_FIXTURE
from tests.snapshot_panels.test_champ_select_view import _open_champ_select
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
# S144-U-241: the theme is flipped in-page, so every transition is off first
# (RM-1132); without it the reads straddle the swap in five themes.
_SHEET = "*, *::before, *::after { transition: none !important; }"


def _item(iid, name, games, lift, boots=False):
    return {"item_id": iid, "name": name, "games": games,
            "wins": games // 2, "win_rate": 0.5 + lift,
            "adj_win_rate": 0.5 + lift, "lift": lift, "is_boots": boots}


# Thin sample, the usual build holds a loser and no winner sits outside it:
# the "loser" insight (signal-warn) plus the thin note.
_LOSER = {
    "champion": "Jinx", "champion_id": 222, "mode": "sr", "games": 14,
    "win_rate": 0.5, "baseline_win_rate": 0.5, "confidence": "thin",
    "items": [_item(3031, "Infinity Edge", 9, 0.03),
              _item(3036, "Lord Dominik's Regards", 8, -0.06)],
    "most_common_build": [3031, 3036],
}
# A winner outside the usual build and a loser in it: the "swap" insight.
_SWAP = dict(_LOSER, confidence="ok", most_common_build=[3036])
# A winner outside the usual build only: the "winner" insight.
_WINNER = dict(_LOSER, confidence="ok",
               items=[_item(3031, "Infinity Edge", 9, 0.07),
                      _item(3094, "Rapid Firecannon", 8, 0.0)],
               most_common_build=[3094])

_STATES = {"base": _PERSONAL_BUILD_FIXTURE, "loser": _LOSER, "swap": _SWAP,
           "winner": _WINNER}

_MEASURE = """async (payloads) => {
  await document.fonts.ready;
""" + _HELPERS + """
  const m = await import('/js/panels/personal_build.js');
  const block = document.getElementById('csv-personal-build');
  const out = [];
  for (const [state, payload] of Object.entries(payloads)) {
    m._resetPersonalBuild();
    m.renderPersonalBuild(block, payload);
    for (const r of read(state, block)) {
      const el = [...block.querySelectorAll('*')].find(
        (e) => e.className === r[1] && e.textContent === r[2]);
      const cs = el ? getComputedStyle(el) : null;
      out.push(r.concat([cs ? parseFloat(cs.fontSize) : 0,
                         cs ? parseInt(cs.fontWeight, 10) : 400,
                         el ? (el.dataset.sign || el.dataset.kind || '') : '',
                         el ? el.getBoundingClientRect().width : 0]));
    }
    const fill = block.querySelector('.pbw-bar-fill[data-sign="neg"]');
    out.push([state, '__neg_fill__', '',
              fill ? rgba(getComputedStyle(fill).backgroundColor) : null,
              null, 0, 0, '', 0]);
  }
  out.push(['_', '__signal_bad__', '', rgba(
    getComputedStyle(document.documentElement)
      .getPropertyValue('--signal-bad').trim()), null, 0, 0, '', 0]);
  out.push(['_', '__theme__', document.documentElement.dataset.theme
            || 'hextech', null, null, 0, 0, '', 0]);
  return out;
}"""


def _measure(mock_server, pw_browser, theme):
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, "aram")
    try:
        page.add_style_tag(content=_SHEET)
        page.evaluate(
            "(t) => { document.documentElement.dataset.theme = t; }", theme)
        rows = page.evaluate(_MEASURE, _STATES)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return rows


@pytest.fixture(scope="module")
def measured():
    return {}


def _rows(measured, mock_server, pw_browser, theme):
    if theme not in measured:
        measured[theme] = _measure(mock_server, pw_browser, theme)
    return measured[theme]


def _texts(rows):
    return [r for r in rows if not r[1].startswith("__")]


def _floor(px, weight):
    # WCAG large text: 18 pt (24 px), or 14 pt (18.67 px) at bold.
    return 3.0 if px >= 24 or (px >= 18.66 and weight >= 700) else 4.5


def _special(rows, name, state="_"):
    hit = [r for r in rows if r[1] == name and r[0] == state]
    assert hit, f"{name} ({state}) not measured"
    return hit[0]


@pytest.mark.parametrize("theme", _THEMES)
def test_every_card_line_reaches_its_floor(theme, measured, mock_server,
                                           pw_browser):
    rows = _rows(measured, mock_server, pw_browser, theme)
    assert _special(rows, "__theme__")[2] == theme, "theme did not apply"
    texts = _texts(rows)
    # Anchor: every state painted, and every class the ruling covers read.
    for state in _STATES:
        assert len([r for r in texts if r[0] == state]) >= 6, (
            f"{state}: card did not render")
    seen = {(r[1], r[7]) for r in texts}
    for want in [("pbw-lift", "pos"), ("pbw-lift", "neg"),
                 ("pbw-lift", "zero"), ("pbw-thin", ""),
                 ("pbw-usual-label", ""), ("pbw-insight", "swap"),
                 ("pbw-insight", "winner"), ("pbw-insight", "loser"),
                 ("pbw-head-title", ""), ("pbw-games", "")]:
        assert want in seen, f"{want} not rendered"
    low = []
    for state, cls, text, fg, bg, px, weight, _sign, _w in texts:
        assert fg and bg, f"no resolved surface under {cls!r}"
        r = _ratio(fg, bg)
        floor = _floor(px, weight)
        if r < floor:
            low.append(f"{cls} {text.strip()!r} ({state}, {px:g}px/"
                       f"{weight}) {r:.2f}:1 < {floor}")
    assert not low, f"{theme}: " + "; ".join(low)


@pytest.mark.parametrize("theme", ["hextech", "arcane", "terminal"])
def test_negative_lift_still_reads_red_and_the_bar_keeps_bare_red(
        theme, measured, mock_server, pw_browser):
    rows = _rows(measured, mock_server, pw_browser, theme)
    neg = [r for r in _texts(rows)
           if r[1] == "pbw-lift" and r[7] == "neg"]
    assert neg, "negative lift not rendered"
    for r in neg:
        red, green, blue = r[3][:3]
        assert red - max(green, blue) >= 60, (
            f"{theme}: negative lift {r[2]!r} no longer reads red: {r[3]}")
    bare = _special(rows, "__signal_bad__")[3]
    fill = _special(rows, "__neg_fill__", "base")[3]
    assert fill and [round(c) for c in fill[:3]] == [
        round(c) for c in bare[:3]], (
        f"{theme}: negative bar fill {fill} is not bare --signal-bad {bare}")
