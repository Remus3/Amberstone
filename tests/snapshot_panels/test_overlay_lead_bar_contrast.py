"""
tests/snapshot_panels/test_overlay_lead_bar_contrast.py
S144-U-277 (s144 uiux): the macro lead pill's state bar (#rn-lead, the 3 px
left border overlay.css paints for .rc-lead-ahead / .rc-lead-behind) is never
the emergency red, and both bars reach the WCAG 1.4.11 non-text floor (3:1)
on the pill's own backing in all six themes, over any game pixel, both while
the widget is live and in the idle recede.

THE RULING (QA ledger, S144-U-275 FILINGS). The bar is a GRAPHICAL OBJECT:
it repeats the state word the pill's tag already prints ("behind - large"),
so the floor is 3:1, and colour is not the only channel (1.4.1). The
doctrine decides the hue: OVERLAY_DOCTRINE section 5 reserves lethal red for
the ONE pop-out ("While an Emergency holds the primary, NOTHING else paints
red"), and w-lead is an AMBIENT widget (section 4 registry). A behind lead is
a caution, not an emergency, so it takes the caution hue --ovx-warn, as the
severe STALE tag (s136-T12) and the TFT crit opponent chip (RM-950) already
do for the same reason.

THE DEFECT. MEASURED headless (mock server, ?ui_mock=1&mode=sr&overlay=1,
1920x1080, six themes; the pill rendered by callouts.js renderLead). The
behind bar painted --ovx-red itself, rgb(232, 64, 87): a second red on the
field beside the w-call urgent band, and 3.85:1 live but 2.85:1 in the idle
recede (overlay.css section 6, widget opacity 0.85) over a white game pixel,
under the 3:1 floor.

THE FIX (web/css/overlay.css). The behind bar takes --ovx-warn (232, 163,
61). After: 7.08:1 live, 4.93:1 idle. The ahead bar (--ovx-good) is
unchanged at 7.67:1 live, 5.21:1 idle.

Contrast pair (the S144-U-275 method): the bar ink over the pill's own
background chain, then the widget opacity, over a game pixel G in {0, 64,
128, 192, 255}, against the same chain without the ink. The pill is the
.ovx-widget itself, so the chain is its own backing.
"""
import colorsys

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_STATES = ["ahead", "behind"]
_FLOOR = 3.0
_GAME = (0, 64, 128, 192, 255)
_SHEET = "*, *::before, *::after { transition: none !important; }"

# Render the pill per state through the real renderer, then read the bar,
# the pill's background chain, its tag and the widget opacity live and idle,
# all in one synchronous run after the import (no poll can repaint between).
_READ = """async (states) => {
""" + _HELPERS + """
  const m = await import('/js/panels/callouts.js');
  const lead = document.getElementById('rn-lead');
  if (!lead) return null;
  const body = document.body;
  const root = getComputedStyle(body);
  const out = {red: root.getPropertyValue('--ovx-red').trim(),
               warn: root.getPropertyValue('--ovx-warn').trim(),
               states: {}};
  for (const s of states) {
    m.renderLead({lead_projection: {state: s, magnitude: 'large',
                  line: 'Synthetic lead line for ' + s + '.'}});
    const cs = getComputedStyle(lead);
    const tag = lead.querySelector('.rc-lead-tag');
    out.states[s] = {cls: lead.className,
                     shown: !lead.hidden && lead.getClientRects().length > 0,
                     widget: lead.classList.contains('ovx-widget'),
                     bar: rgba(cs.borderLeftColor),
                     barW: parseFloat(cs.borderLeftWidth),
                     bg: rgba(cs.backgroundColor),
                     tag: tag ? tag.textContent.trim() : null};
  }
  const had = body.getAttribute('data-rc-idle');
  lead.style.transition = 'none';
  body.setAttribute('data-rc-idle', '0');
  out.live = parseFloat(getComputedStyle(lead).opacity);
  body.setAttribute('data-rc-idle', '1');
  out.idle = parseFloat(getComputedStyle(lead).opacity);
  if (had === null) body.removeAttribute('data-rc-idle');
  else body.setAttribute('data-rc-idle', had);
  m.renderLead({});
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


def _worst(ink, bg_layer, live_op, idle_op):
    """Lowest (live, idle) ratio of the bar over the game pixels."""
    live = idle = 99.0
    for gp in _GAME:
        pix = [float(gp)] * 3
        bg = _over(bg_layer, pix)
        fg = _over(ink, bg)
        live = min(live, _ratio(_over([*fg, live_op], pix),
                                _over([*bg, live_op], pix)))
        idle = min(idle, _ratio(_over([*fg, idle_op], pix),
                                _over([*bg, idle_op], pix)))
    return live, idle


def _hue(c):
    return colorsys.rgb_to_hls(*(x / 255 for x in c[:3]))[0] * 360


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
            "() => document.body.dataset.shell === 'overlay'"
            " && !!document.querySelector('#rn-lead.ovx-widget')",
            timeout=10_000)
        page.add_style_tag(content=_SHEET)
        got = page.evaluate(_READ, _STATES)
        booted = page.evaluate(
            "() => document.documentElement.dataset.theme || 'hextech'")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert booted == theme, f"booted on {booted}, not {theme}"
    assert got is not None, "no #rn-lead mount on the overlay"
    return got


def _get(measured, mock_server, pw_browser, theme):
    if theme not in measured:
        measured[theme] = _measure(mock_server, pw_browser, theme)
    return measured[theme]


@pytest.mark.parametrize("theme", _THEMES)
def test_lead_bars_reach_non_text_floor(
        theme, measured, mock_server, pw_browser):
    read = _get(measured, mock_server, pw_browser, theme)
    # The pair is honest only if the widget really recedes and the pill's
    # backing resolved (an unread layer would be alpha 0).
    assert 0 < read["idle"] < read["live"] == 1.0, (read["live"], read["idle"])
    bad = []
    for state, v in read["states"].items():
        assert v["shown"] and v["widget"], (state, v)
        assert f"rc-lead-{state}" in v["cls"].split(), (state, v["cls"])
        assert v["bg"][3] > 0, (state, v["bg"])
        assert v["barW"] == 3, (state, v["barW"])
        live, idle = _worst(v["bar"], v["bg"], read["live"], read["idle"])
        if min(live, idle) < _FLOOR:
            bad.append(f"{state} bar {v['bar'][:3]} live {live:.2f}"
                       f" idle {idle:.2f}")
    assert not bad, f"{theme}: " + "; ".join(bad)


@pytest.mark.parametrize("theme", _THEMES)
def test_lead_behind_bar_is_not_the_emergency_red(
        theme, measured, mock_server, pw_browser):
    # Doctrine rule 4 / section 5: red is the ONE pop-out. The behind bar
    # takes the caution hue, and stays a different hue from the ahead bar.
    read = _get(measured, mock_server, pw_browser, theme)
    red = [float(p) for p in read["red"].split(",")]
    assert red == [232.0, 64.0, 87.0], read["red"]
    warn = [float(p) for p in read["warn"].split(",")]
    behind = read["states"]["behind"]["bar"]
    ahead = read["states"]["ahead"]["bar"]
    gap = abs(_hue(behind) - _hue(red))
    assert min(gap, 360 - gap) > 20, (behind, red)
    assert [float(x) for x in behind[:3]] == warn, (behind, read["warn"])
    assert abs(_hue(behind) - _hue(ahead)) > 60, (behind, ahead)


@pytest.mark.parametrize("theme", ["hextech", "arcane"])
def test_lead_state_is_also_in_words(
        theme, measured, mock_server, pw_browser):
    # The ruling rests on this: the bar repeats the tag, so colour is never
    # the only channel and the bar is a graphical object (3:1), not text.
    read = _get(measured, mock_server, pw_browser, theme)
    for state, v in read["states"].items():
        assert v["tag"] == f"{state} - large", (state, v["tag"])
