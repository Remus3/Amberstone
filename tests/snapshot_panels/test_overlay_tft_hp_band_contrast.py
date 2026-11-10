"""
tests/snapshot_panels/test_overlay_tft_hp_band_contrast.py
S144-U-297 (s144 uiux): the TFT overlay vitals HP value in its HP band - the
amber "low" (HP <= 40) and the red "crit" (HP <= 20) - reaches the WCAG 1.4.3
AA text floor (4.5:1) on its own cell backing in all six themes, over any game
pixel, both while the widget is live and in the idle recede.

THE DEFECT. MEASURED headless (mock server, the live TFT overlay route
?overlay=1&theme=<t>, 1920x1080, the tft_overlay_live payload at a real crit
HP). The HP value is 18 px / 700 (--fs-sm on .ovt-major): under the 18.66 px
bold large-text size, so its floor is 4.5:1, not 3:1. The crit rule painted
--ovx-red itself, rgb(232, 64, 87): 4.45:1 live and 3.36:1 in the idle recede
(overlay.css section 6, widget opacity 0.85 - the state the TFT HUD sits in
most of a game, s136-T12) over a white game pixel, on the cell's 0.9
--ovx-bg-nested backing. The one number the vitals widget exists to shout at
crit HP was the one value on it under AA. No test rendered a banded vitals
cell's contrast (the S144-U-273 pin reads the "-" placeholder only).

THE FIX (web/css/overlay.css section 0 + web/js/lib/overlay_tft.js). A new
overlay token --ovx-red-text (239, 118, 135): the --ovx-red hue lifted in
lightness only (HLS L 0.58 -> 0.70), the text-floor sibling of S144-U-275's
non-text --ovx-red-ink. The crit HP value paints it. --ovx-red itself is
unchanged, so every other red use is untouched. The low band (--ovx-warn)
already cleared AA and is pinned as it is.

Contrast pair: the band ink composited down its own ancestor chain (every
background from the value up to the .ovx-widget, as the browser paints them)
over a game pixel G in {0, 64, 128, 192, 255}, against that same chain
without the ink; idle applies the widget's computed idle opacity to both.
The HP values are real readings from tft_qa run 20261025-104400 (crit 17,
low 30); the band is the one overlay_tft.js tftHpBand stamps from them.
"""
import colorsys

import pytest

from tests.snapshot_panels.test_overlay_tft_dim_ink_contrast import _worst
from tests.snapshot_panels.test_overlay_tft_view import _fixture, _open, _wait_tft

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
# Real HP readings (tft_qa run 20261025-104400) and the band each stamps.
_HP = {"crit": 17, "low": 30}
_AA = 4.5
_SHEET = "*, *::before, *::after { transition: none !important; }"
_VAL = '#ovt-hud .ovt-cell[data-k="hp"] .ovt-val'

# The HP value's ink, size and weight, its cell's band, every background from
# the value up to its .ovx-widget, the widget's opacity live and idle
# (transitions off, read synchronously, the attribute restored), the PLACE
# value beside it (an unbanded major value), and the two band tokens.
_MEASURE = """(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const parse = s => {
    const m = /rgba?\\(([^)]+)\\)/.exec(s);
    const p = m ? m[1].split(',').map(Number) : [0, 0, 0, 0];
    return p.length > 3 ? p : [...p, 1];
  };
  const chain = [];
  let n = el, widget = null;
  while (n && n !== document.body) {
    chain.push(parse(getComputedStyle(n).backgroundColor));
    if (n.classList.contains('ovx-widget')) { widget = n; break; }
    n = n.parentElement;
  }
  if (!widget) return null;
  const body = document.body;
  const had = body.getAttribute('data-rc-idle');
  widget.style.transition = 'none';
  body.setAttribute('data-rc-idle', '0');
  const live = parseFloat(getComputedStyle(widget).opacity);
  body.setAttribute('data-rc-idle', '1');
  const idle = parseFloat(getComputedStyle(widget).opacity);
  if (had === null) body.removeAttribute('data-rc-idle');
  else body.setAttribute('data-rc-idle', had);
  const cs = getComputedStyle(el);
  const place = getComputedStyle(
    document.querySelector('#ovt-hud .ovt-cell[data-k="place"] .ovt-val'));
  const root = getComputedStyle(body);
  return {text: el.textContent, band: el.parentElement.dataset.band || '',
          ink: parse(cs.color), size: cs.fontSize, weight: cs.fontWeight,
          placeInk: parse(place.color), placeSize: place.fontSize,
          placeWeight: place.fontWeight, chain, live, idle,
          red: root.getPropertyValue('--ovx-red').trim(),
          warn: root.getPropertyValue('--ovx-warn').trim()};
}"""


def _state(hp):
    st = _fixture("tft_overlay_live")
    return {
        **st,
        "liveclient": {**st["liveclient"], "hp": hp},
        "coach": {**st["coach"], "hp": hp, "health": hp},
    }


def _measure(mock_server, pw_browser, theme, band="crit"):
    ctx, page, errors = _open(
        pw_browser, mock_server, _state(_HP[band]),
        query=f"?overlay=1&theme={theme}")
    try:
        _wait_tft(page)
        page.wait_for_function(
            "(s) => { const e = document.querySelector(s);"
            " return !!e && !!e.parentElement.dataset.band; }",
            arg=_VAL, timeout=10_000)
        page.add_style_tag(content=_SHEET)
        got = page.evaluate(_MEASURE, _VAL)
        booted = page.evaluate(
            "() => document.documentElement.dataset.theme || 'hextech'")
    finally:
        page.close()
        ctx.close()
        mock_server._store["data"] = {}
    assert not errors, f"JS errors [{theme} {band}]: {errors[:3]}"
    assert booted == theme, f"booted on {booted}, not {theme}"
    assert got is not None, "the HP value is not inside an .ovx-widget"
    return got


@pytest.fixture(scope="module")
def measured():
    return {}


def _get(measured, mock_server, pw_browser, theme, band):
    if (theme, band) not in measured:
        measured[(theme, band)] = _measure(mock_server, pw_browser, theme, band)
    return measured[(theme, band)]


def _hue(rgb):
    return colorsys.rgb_to_hls(*(float(v) / 255 for v in rgb[:3]))[0] * 360


def _hue_gap(a, b):
    d = abs(_hue(a) - _hue(b)) % 360
    return min(d, 360 - d)


def _parts(token):
    return [float(p) for p in token.split(",")]


@pytest.mark.parametrize("band", sorted(_HP))
@pytest.mark.parametrize("theme", _THEMES)
def test_hp_band_value_reaches_aa_live_and_idle(
        theme, band, measured, mock_server, pw_browser):
    read = _get(measured, mock_server, pw_browser, theme, band)
    # The real render stamped this band from this HP.
    assert read["band"] == band, (read["band"], read["text"])
    assert read["text"] == str(_HP[band]), read["text"]
    # The pair is honest only if the widget really recedes and every layer
    # read resolved to a colour (an unparsed background would read 0 alpha).
    assert 0 < read["idle"] < read["live"] == 1.0, (read["live"], read["idle"])
    assert read["chain"][-1][3] > 0, ("widget frame unread", read["chain"])
    assert any(c[3] >= 0.85 for c in read["chain"][:-1]), ("no cell backing", read["chain"])
    # 18 px bold is under the 18.66 px large-text size: the floor is 4.5:1.
    assert float(read["size"].rstrip("px")) < 18.66, read["size"]
    live, idle = _worst(read)
    assert live >= _AA, f"{theme} {band} HP {live:.2f}:1 live, under AA {_AA}"
    assert idle >= _AA, f"{theme} {band} HP {idle:.2f}:1 idle, under AA {_AA}"


@pytest.mark.parametrize("theme", ["hextech", "arcane"])
def test_hp_band_keeps_its_hue(theme, measured, mock_server, pw_browser):
    # HIERARCHY: the lift is lightness only. Crit keeps the --ovx-red hue (the
    # doctrine's ONE emergency pop-out, rule 4), low keeps --ovx-warn's, the
    # two stay apart by hue, and --ovx-red itself is unchanged.
    crit = _get(measured, mock_server, pw_browser, theme, "crit")
    low = _get(measured, mock_server, pw_browser, theme, "low")
    assert _parts(crit["red"]) == [232.0, 64.0, 87.0], crit["red"]
    assert _hue_gap(crit["ink"], _parts(crit["red"])) <= 2, crit["ink"]
    assert _hue_gap(low["ink"], _parts(low["warn"])) <= 2, low["ink"]
    assert _hue_gap(crit["ink"], low["ink"]) > 20, (crit["ink"], low["ink"])
    # Each band reads as a colour, not as the neutral ink beside it.
    for read in (crit, low):
        assert read["ink"][:3] != read["placeInk"][:3], read["ink"]


@pytest.mark.parametrize("band", sorted(_HP))
def test_hp_band_changes_colour_only(band, measured, mock_server, pw_browser):
    # TYPOGRAPHY: the band is a colour; the HP value keeps the major-value
    # size and weight of the unbanded PLACE value beside it.
    read = _get(measured, mock_server, pw_browser, "hextech", band)
    assert (read["size"], read["weight"]) == (read["placeSize"], read["placeWeight"]), read
    assert read["ink"][3] == 1, read["ink"]
