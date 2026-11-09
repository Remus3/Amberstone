"""
tests/snapshot_panels/test_overlay_call_glyph_contrast.py
S144-U-275 (s144 uiux): the w-call ACTION row's band channel - the band glyph
(.am-call-glyph, U+26A0 urgent / U+25BA fight / U+2713 good) and the 3 px
color bar on the row's left edge - reaches the WCAG 1.4.11 non-text floor
(3:1) on the call pane in all six themes, over any game pixel, both while the
widget is live and in the idle recede.

THE RULING (QA ledger FUTURE (g)). The glyph is a GRAPHICAL OBJECT, not text:
it is aria-hidden, a symbol from a fixed set of three, and it repeats what the
bar and the verb beside it already say (doctrine sections 5 and 6: the band is
carried by the glyph AND the bar, never by recoloring the verb). WCAG 1.4.11
treats icon glyphs as graphical objects, so the floor is 3:1, not 4.5:1.

THE DEFECT. MEASURED headless (mock server, ?ui_mock=1&mode=sr&overlay=1,
1920x1080, six themes). The QA ledger had pinned the 3.89 - 4.14 reading on
the gold FIGHT glyph, but gold reads 6.91 - 8.15:1. The 3.89 - 4.58 reading is
the red URGENT glyph and bar (--ovx-red, rgb(232, 64, 87)). Live, that clears
3:1. In the idle recede (overlay.css section 6: body[data-rc-idle="1"]
.ovx-widget opacity 0.85, reached by an urgent call left unchanged for 8 s
outside a fight) it falls to 2.90 arcane, 2.93 moonlit and 2.95 ember over a
white game pixel.

THE FIX (web/css/overlay.css). The urgent glyph and bar take --ovx-red-ink
(235, 91, 111): the same red hue, lifted in lightness only. After: 4.59:1 or
better live, 3.41:1 or better idle. --ovx-red itself is unchanged.

Contrast pair: the ink composited over the pane's own background chain, then
the widget opacity, over a game pixel G in {0, 64, 128, 192, 255}, against the
same chain without the ink. The band is set on the rendered ACTION row's
data-call-band, the attribute overlay.css keys every band rule on.
"""
import colorsys

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_BANDS = ["urgent", "fight", "good"]
_FLOOR = 3.0
_GAME = (0, 64, 128, 192, 255)
_ROW = '#am-call-body > div[data-call-line="action"]'
_GLYPHS = {"urgent": 0x26A0, "fight": 0x25BA, "good": 0x2713}
_SHEET = "*, *::before, *::after { transition: none !important; }"

# Per band: the glyph ink, the bar color, the background chain from the glyph
# up to its .ovx-widget, and the widget opacity live and idle (transitions
# off, read synchronously, the attributes restored).
_READ = """(bands) => {
""" + _HELPERS + """
  const row = document.querySelector('""" + _ROW + """');
  const g = row.querySelector('.am-call-glyph');
  const chain = [];
  let n = g, widget = null;
  while (n && n !== document.body) {
    chain.push(rgba(getComputedStyle(n).backgroundColor));
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
  const rendered = row.dataset.callBand;
  const root = getComputedStyle(body);
  const out = {rendered, aria: g.getAttribute('aria-hidden'),
               glyph: g.textContent.trim(), chain, live, idle,
               red: root.getPropertyValue('--ovx-red').trim(), bands: {}};
  for (const b of bands) {
    row.dataset.callBand = b;
    out.bands[b] = {ink: rgba(getComputedStyle(g).color),
                    bar: rgba(getComputedStyle(row).borderLeftColor),
                    barW: parseFloat(getComputedStyle(row).borderLeftWidth)};
  }
  row.dataset.callBand = rendered;
  return out;
}"""


def _lum(c):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def _ratio(a, b):
    x, y = sorted((_lum(a), _lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def _over(top, base):
    a = top[3]
    return [a * t + (1 - a) * b for t, b in zip(top[:3], base)]


def _worst(ink, read):
    """Lowest (live, idle) ratio of one ink over the game pixels."""
    live = idle = 99.0
    for gp in _GAME:
        pix = [float(gp)] * 3
        bg = pix
        for layer in reversed(read["chain"]):  # widget frame first
            bg = _over(layer, bg)
        fg = _over(ink, bg)
        live = min(live, _ratio(_over([*fg, read["live"]], pix),
                                _over([*bg, read["live"]], pix)))
        idle = min(idle, _ratio(_over([*fg, read["idle"]], pix),
                                _over([*bg, read["idle"]], pix)))
    return live, idle


@pytest.fixture(scope="module")
def measured():
    return {}


def _measure(mock_server, pw_browser, theme):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url
                  + f"/?ui_mock=1&mode=sr&overlay=1&theme={theme}",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            f"() => !!document.querySelector('{_ROW} .am-call-glyph')",
            timeout=10_000)
        page.add_style_tag(content=_SHEET)
        got = page.evaluate(_READ, _BANDS)
        booted = page.evaluate(
            "() => document.documentElement.dataset.theme || 'hextech'")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert booted == theme, f"booted on {booted}, not {theme}"
    assert got is not None, "the glyph is not inside an .ovx-widget"
    return got


def _get(measured, mock_server, pw_browser, theme):
    if theme not in measured:
        measured[theme] = _measure(mock_server, pw_browser, theme)
    return measured[theme]


@pytest.mark.parametrize("theme", _THEMES)
def test_call_band_glyph_and_bar_reach_non_text_floor(
        theme, measured, mock_server, pw_browser):
    read = _get(measured, mock_server, pw_browser, theme)
    # The pair is honest only if the widget really recedes and the pane's
    # chain resolved to an opaque base (an unread layer would be alpha 0).
    assert 0 < read["idle"] < read["live"] == 1.0, (read["live"], read["idle"])
    assert read["chain"][-1][3] > 0, read["chain"]
    # The real render stamped a band and drew that band's glyph.
    assert read["rendered"] in _BANDS, read["rendered"]
    assert read["glyph"] == chr(_GLYPHS[read["rendered"]]), read["glyph"]
    bad = []
    for band, v in read["bands"].items():
        for part in ("ink", "bar"):
            live, idle = _worst(v[part], read)
            if min(live, idle) < _FLOOR:
                bad.append(f"{band} {part} live {live:.2f} idle {idle:.2f}")
    assert not bad, f"{theme}: " + "; ".join(bad)


@pytest.mark.parametrize("theme", _THEMES)
def test_call_band_glyph_is_a_graphical_object(
        theme, measured, mock_server, pw_browser):
    # The ruling rests on these: the glyph is hidden from assistive tech, and
    # every band also paints the bar in the glyph's own color.
    read = _get(measured, mock_server, pw_browser, theme)
    assert read["aria"] == "true", read["aria"]
    for band, v in read["bands"].items():
        assert v["barW"] == 3, (band, v["barW"])
        assert v["bar"] == v["ink"], (band, v["bar"], v["ink"])


@pytest.mark.parametrize("theme", ["hextech", "arcane"])
def test_urgent_ink_stays_the_emergency_red(
        theme, measured, mock_server, pw_browser):
    # The lift is lightness only: the urgent ink keeps --ovx-red's hue, so the
    # ONE emergency red (doctrine rule 4, section 5) is still one hue, and it
    # stays the only red band.
    read = _get(measured, mock_server, pw_browser, theme)
    red = [float(p) for p in read["red"].split(",")]
    assert red == [232.0, 64.0, 87.0], read["red"]

    def hue(c):
        return colorsys.rgb_to_hls(*(x / 255 for x in c[:3]))[0] * 360

    ink = read["bands"]["urgent"]["ink"]
    assert abs(hue(ink) - hue(red)) < 2.0, (ink, red)
    for band in ("fight", "good"):
        h = hue(read["bands"][band]["ink"])
        assert 20 < h < 340, (band, h)
