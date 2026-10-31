"""
tests/snapshot_panels/test_champ_select_enemy_wr_slot_contrast.py
RM-1198 (s144 uiux): the SR champ-select enemy win-rate slot
(web/js/panels/champ_select.js _csvWrSlotApply, the leading
.csv-enemy-wr-slot on each enemy cell, styled in
web/css/panels/champ_select_view.css) reaches WCAG AA on its resolved
surface on all six themes, in every band it can paint.

The slot is fed per enemy by /api/personal-vs. The test routes that call
so the fixture's five enemies render one of each state:
  122 -> 62% (is-good)   121 -> 50% (is-mid)   157 -> 38% (is-bad)
  145 -> sample_n 0, the "--" no-games placeholder (is-new)
  412 -> the route answers 503, which paints the same "--" placeholder
All numbers are synthetic (RM-906).

MEASURED headless under /?ui_mock=1&mode=sr&theme=<t>#champ-select at
1920x1080 before the fix (colours resolved by the browser and composited
over the stacked backgrounds, lane doc traps 3 and 4): the "--"
placeholder (--text-faint on the --surface-2 enemy cell) measured
4.31 to 4.48:1 on hextech, ember, moonlit and arcane, and the is-bad
losing-matchup band (solid --bad) 3.89 to 4.45:1 on every theme but
terminal. After: the losing band is mixed 70% --bad / 30% --text
(5.78 to 7.49:1, pinned to stay red), and the placeholder is mixed 60%
--text-faint / 40% --text-dim (5.14 to 6.16:1). A plain --text-dim
placeholder was tried first and measured BRIGHTER than the red band on
all six themes and than every band on terminal, so the last test pins
that "--" stays dimmer than every real win-rate band and the enemy
name: no data never outshines data.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _lum, _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]

# champ id -> (/api/personal-vs body, expected band class, expected text)
_ROUTED = {
    122: ({"ok": True, "sample_n": 8, "wr_pct": 62, "wins": 5, "losses": 3,
           "days": 30, "champ_name": "Darius"}, "is-good", "62%"),
    121: ({"ok": True, "sample_n": 6, "wr_pct": 50, "wins": 3, "losses": 3,
           "days": 30, "champ_name": "Kha'Zix"}, "is-mid", "50%"),
    157: ({"ok": True, "sample_n": 8, "wr_pct": 38, "wins": 3, "losses": 5,
           "days": 30, "champ_name": "Yasuo"}, "is-bad", "38%"),
    145: ({"ok": True, "sample_n": 0, "wr_pct": 0, "wins": 0, "losses": 0,
           "days": 30}, "is-new", "--"),
    412: (None, "is-new", "--"),
}

_MEASURE = """async () => {
  await document.fonts.ready;
""" + _HELPERS + """
  // Wait and read in ONE task. A failed fetch is negative-cached since
  // RM-1199 (test_champ_select_enemy_wr_slot_negative_cache.py), but
  // the single-task read stays: poll until all five slots carry text,
  // then read synchronously so nothing repaints in between.
  const slots = () => [...document.querySelectorAll(
    '#view-champ-select #csv-enemies-list .csv-enemy-wr-slot')];
  const t0 = performance.now();
  while (!(slots().length === 5
           && slots().every((e) => e.textContent.trim()))) {
    if (performance.now() - t0 > 10000) return null;
    await new Promise((r) => setTimeout(r, 25));
  }
  const out = [];
  for (const cell of document.querySelectorAll(
      '#view-champ-select #csv-enemies-list .csv-team-cell')) {
    const slot = cell.querySelector('.csv-enemy-wr-slot');
    const name = cell.querySelector('.csv-team-cell-nm');
    if (!slot || !slot.checkVisibility()) continue;
    const s = surface(slot);
    const ns = name ? surface(name) : null;
    out.push({
      champ: slot.dataset.champId | 0,
      cls: slot.className,
      text: slot.textContent.trim(),
      fg: s ? over(rgba(getComputedStyle(slot).color), s) : null,
      bg: s,
      opacity: parseFloat(getComputedStyle(slot).opacity),
      name_fg: ns ? over(rgba(getComputedStyle(name).color), ns) : null,
    });
  }
  return out;
}"""


def _route(route):
    url = route.request.url
    cid = int(url.split("champ_id=")[1].split("&")[0])
    body = _ROUTED.get(cid, (None,))[0]
    if body is None:
        # The route's own failure answer (routes_personal_vs, db missing).
        route.fulfill(status=503, content_type="application/json",
                      body=json.dumps({"ok": False,
                                       "error": "rewind_history.db missing"}))
        return
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))


def _measure(mock_server, pw_browser, theme):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.route("**/api/personal-vs*", _route)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url
            + f"/?ui_mock=1&mode=sr&theme={theme}#champ-select",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_selector(
            "#view-champ-select #csv-enemies-list .csv-enemy-wr-slot",
            timeout=10_000,
        )
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        rows = page.evaluate(_MEASURE)
        assert rows is not None, "enemy WR slots never all painted"
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


@pytest.mark.parametrize("theme", _THEMES)
def test_every_wr_band_reaches_aa_on_the_enemy_cell(theme, measured,
                                                    mock_server, pw_browser):
    rows = _rows(measured, mock_server, pw_browser, theme)
    assert sorted(r["champ"] for r in rows) == sorted(_ROUTED), rows
    low = []
    for r in rows:
        _, band, text = _ROUTED[r["champ"]]
        assert band in r["cls"].split(), (r["champ"], r["cls"])
        assert r["text"] == text, (r["champ"], r["text"])
        # The surface helper ignores opacity; refuse a dimmed slot outright.
        assert r["opacity"] == 1, r
        assert r["fg"] and r["bg"], f"no resolved surface under {r}"
        ratio = _ratio(r["fg"], r["bg"])
        if ratio < 4.5:
            low.append(f"{band} {text!r} {ratio:.2f}:1")
    assert not low, f"{theme}: under 4.5:1 - " + "; ".join(low)


@pytest.mark.parametrize("theme", _THEMES)
def test_losing_band_stays_red(theme, measured, mock_server, pw_browser):
    rows = _rows(measured, mock_server, pw_browser, theme)
    bad = [r for r in rows if "is-bad" in r["cls"].split()]
    assert len(bad) == 1, rows
    fg = bad[0]["fg"]
    # Lifting the losing band for contrast must not wash it out to a
    # neutral or pink-grey: red stays the dominant channel by a clear
    # margin (the down-triangle glyph carries the non-hue cue, RC2 B3/C5).
    assert fg[0] - max(fg[1], fg[2]) >= 60, (
        f"{theme}: losing-matchup band lost its red {fg[:3]}")


@pytest.mark.parametrize("theme", _THEMES)
def test_no_games_placeholder_stays_dimmer_than_every_data_line(
        theme, measured, mock_server, pw_browser):
    rows = _rows(measured, mock_server, pw_browser, theme)
    new = [r for r in rows if "is-new" in r["cls"].split()]
    data = [r for r in rows if "is-new" not in r["cls"].split()]
    assert len(new) == 2 and len(data) == 3, rows
    for r in new:
        assert r["name_fg"], r
        assert _lum(r["fg"]) < _lum(r["name_fg"]), (
            f"{theme}: '--' placeholder is as bright as the enemy name")
        for d in data:
            band = d["cls"].split()[-1]
            assert _lum(r["fg"]) < _lum(d["fg"]), (
                f"{theme}: '--' placeholder outshines the {band} "
                f"{d['text']} win rate")
