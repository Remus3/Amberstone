"""
tests/snapshot_panels/test_tft_strip_hp_band_colour.py
S144-U-296 (s144 uiux): the dashboard TFT stat strip's HP value is painted
in its HP band - amber at low, red at crit - as the overlay vitals HP is,
at its WCAG 1.4.3 floor in all six themes, at the 1920x920 baseline and
the 923x1280 companion size.

WHY. RM-949 (fc6823acd) stamped the overlay vitals band (tftHpBand, the
one source in web/js/lib/overlay_tft.js) on the strip's HP cell as
data-band="low" / "crit", and said in its message that the colour, the
CSS half, was "filed separately". No rule in web/css ever read it: the
strip painted 36 HP and 13 HP in the same --text as 70 HP, while the
overlay vitals painted the same HP amber (--ovx-warn) and red (--ovx-red)
(overlay_tft.js .ovt-cell[data-band]). The band was in the DOM and on no
screen.

THE FIX (web/css/panels/active_match.css): the HP value takes
--signal-warn at data-band="low" and --signal-bad at data-band="crit".
They are the dashboard's semantic amber and red (the 2-star amber on the
board, the crit-red lobby fill), and inside the overlay shell the same two
tokens are re-pointed to --ovx-warn / --ovx-red (web/css/overlay.css
section 0a), so the strip and the overlay vitals paint one band in one
hue on either shell. The label stays --text-dim; only the value carries
the band.

THE FLOOR. The value is --fs-lg (29 px) at weight 700, WCAG large text
(24 px, or 18.66 px bold), so its floor is 3:1, the program's ruling for
large text (docs/qa/UI_UX_PROGRAM_QA_2026-07-22.md, .home-coach-pick-champ).
MEASURED on the pane at 1920x920: amber 7.14 (arcane) to 8.60
(bloodmoon), red 3.89 (arcane) to 5.02 (terminal). The pin derives the
floor from the computed size and weight, so a value that ever drops below
large text is held to 4.5.

Drive path: the live /api/state path (no ui_mock), real tft_qa rows as
the RM-949 pin uses them (test_tft_active_match_view
test_strip_hp_cell_band_matches_the_overlay_vitals): run 20261025-162857
line 77 (stage 4-6, 5th at 36 HP, low) and line 95 (stage 5-5, 5th at
13 HP, crit), then 70 HP (no band) as the control, painted as successive
ticks of one page per theme and size.
"""
import copy

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio
from tests.snapshot_panels.test_tft_active_match_view import (
    _LIVE_TICK_MS,
    _load,
    _wait_fallback,
)

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_SIZES = [(1920, 920), (923, 1280)]
_SHEET = ("*, *::before, *::after { transition: none !important;"
          " animation: none !important; }")

# (coach update, HP text, data-band, colour token the value must resolve to)
_TICKS = [
    ({"hp": 36, "standing": 5, "stage_round": "4-6"}, "36", "low",
     "--signal-warn"),
    ({"hp": 13, "health": 26, "standing": 5, "stage_round": "5-5"}, "13",
     "crit", "--signal-bad"),
    ({"hp": 70, "health": 70, "standing": 3, "stage_round": "3-2"}, "70", "",
     "--text"),
]

_MEASURE = """async (token) => {
  await document.fonts.ready;
""" + _HELPERS + """
  const cells = [...document.querySelectorAll('#am-call-body .am-tft-stat')];
  const hp = cells.find(
    (c) => c.querySelector('.am-tft-stat-label').textContent === 'HP');
  const stage = cells.find(
    (c) => c.querySelector('.am-tft-stat-label').textContent === 'STAGE');
  const v = hp.querySelector('.am-tft-stat-value');
  const cs = getComputedStyle(v);
  const s = surface(v);
  // The token's own resolved colour, through a probe in the same cascade.
  const probe = document.createElement('span');
  probe.style.color = `var(${token})`;
  hp.appendChild(probe);
  const want = rgba(getComputedStyle(probe).color);
  probe.remove();
  return {
    text: v.textContent,
    band: hp.dataset.band || '',
    visible: v.checkVisibility(),
    color: rgba(cs.color),
    want,
    text_ink: rgba(getComputedStyle(
      stage.querySelector('.am-tft-stat-value')).color),
    fg: s ? over(rgba(cs.color), s) : null,
    bg: s,
    px: parseFloat(cs.fontSize),
    weight: parseInt(cs.fontWeight, 10),
    cut: v.scrollWidth - v.clientWidth,
  };
}"""


def _floor(px: float, weight: int) -> float:
    """WCAG 1.4.3: large text (24 px, or 18.66 px at bold) is 3:1."""
    return 3.0 if px >= 24 or (px >= 18.66 and weight >= 700) else 4.5


@pytest.fixture(scope="module")
def measured():
    return {}


def _measure(mock_server, pw_browser, theme, size):
    data = copy.deepcopy(_load("tft_live_s134"))
    data["coach"].update(_TICKS[0][0])
    mock_server._store["data"] = data
    ctx = pw_browser.new_context(viewport={"width": size[0],
                                           "height": size[1]})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    out = {}
    try:
        page.goto(mock_server.url + f"/?theme={theme}",
                  wait_until="domcontentloaded", timeout=15_000)
        _wait_fallback(page, "tft")
        page.add_style_tag(content=_SHEET)
        out["theme"] = page.evaluate(
            "() => document.documentElement.dataset.theme || 'hextech'")
        for coach, hp_text, _band, token in _TICKS:
            data["coach"].update(coach)
            mock_server._store["data"] = data
            page.wait_for_function(
                "(t) => [...document.querySelectorAll("
                "'#am-call-body .am-tft-stat-value')]"
                ".some(v => v.textContent === t)",
                arg=hp_text, timeout=_LIVE_TICK_MS,
            )
            page.evaluate("() => new Promise((r) => requestAnimationFrame("
                          "() => requestAnimationFrame(() => r())))")
            out[hp_text] = page.evaluate(_MEASURE, token)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return out


def _get(measured, mock_server, pw_browser, theme, size):
    key = (theme, size)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, size)
    return measured[key]


@pytest.mark.parametrize("size", _SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("theme", _THEMES)
def test_strip_hp_value_paints_its_band(measured, mock_server, pw_browser,
                                        theme, size):
    got = _get(measured, mock_server, pw_browser, theme, size)
    assert got["theme"] == theme, f"booted on {got['theme']}, not {theme}"
    seen = {}
    for _coach, hp_text, band, token in _TICKS:
        m = got[hp_text]
        assert (m["text"], m["band"]) == (hp_text, band), m
        assert m["visible"], m
        # The token resolved to an opaque colour. An undefined var would
        # make the value and the probe both inherit --text and match here;
        # the three-distinct-colours check below is what refuses that.
        assert m["want"][3] == 1, (token, m["want"])
        assert m["color"] == m["want"], (theme, band or "none", token,
                                         m["color"], m["want"])
        seen[band] = tuple(m["color"])
    # The control row stays --text, the STAGE value's ink; the two bands
    # are two hues, neither of them that ink.
    assert seen[""] == tuple(got["70"]["text_ink"]), seen
    assert len(set(seen.values())) == 3, (theme, seen)


@pytest.mark.parametrize("size", _SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("theme", _THEMES)
def test_strip_hp_value_reaches_its_wcag_floor(measured, mock_server,
                                               pw_browser, theme, size):
    got = _get(measured, mock_server, pw_browser, theme, size)
    for _coach, hp_text, band, _token in _TICKS:
        m = got[hp_text]
        assert m["fg"] and m["bg"], f"no opaque surface under {m}"
        floor = _floor(m["px"], m["weight"])
        # Pinned size: the value is large text on both sizes today.
        assert floor == 3.0, (m["px"], m["weight"])
        r = _ratio(m["fg"], m["bg"])
        assert r >= floor, (theme, size, band or "none", round(r, 2))
        assert m["cut"] <= 0, (theme, size, hp_text, m["cut"])
