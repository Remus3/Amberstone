"""
tests/snapshot_panels/test_overlay_tft_text_contrast.py
S144-U-298 (s144 uiux): EVERY text line of the three TFT overlay widgets -
TFT Vitals (#ovt-hud), Board (#ovt-board) and Lobby HP (#ovt-lobby) - reaches
the WCAG 1.4.3 AA text floor (4.5:1) on its own backing in all six themes,
over any game pixel, both while the widget is live and in the idle recede.

WHY. Three pins each read ONE element: S144-U-273 the "-" placeholder and the
OUT chip, S144-U-297 the banded vitals HP value. Nothing read the rest: the
11 px gold pane titles, the cyan source tag, the 0.62 cell labels, the head
clocks, the board unit names, and the crit opponent chip (RM-950 recorded
9.0:1 for it on the bare backing, never live or idle over a game pixel).
Two of the three single-element pins found a defect (0.45 dim ink, the
--ovx-red crit value), so the next sub-floor rule would land unseen on any
line no pin happens to name.

MEASURED headless (mock server, the live TFT overlay route
?overlay=1&theme=<t>, 1920x1080, the tft_overlay_feed payload: the real
round-feed state of QA match 3 with its end-game lobby). No defect: the same
figures in all six themes (the overlay palette is theme-invariant), lowest
first, worst game pixel:
  - "-" no-data value, OUT chip (0.55 dim tier):  6.06 live, 4.63 idle
  - pane titles (gold 0.90, 11 px / 700):          6.63 live, 4.96 idle
  - crit opponent chip (--ovx-warn, 13 px / 700):  8.17 live, 5.82 idle
Every other line reads 5.0 or more idle.

Contrast pair, as the S144-U-273 / U-297 pins: the ink (times every ancestor
opacity below the widget) composited down its own ancestor chain (every
background from the line up to the .ovx-widget, as the browser paints them)
over a game pixel G in {0, 64, 128, 192, 255}, against that same chain
without the ink; idle applies the widget's computed idle opacity
(body[data-rc-idle="1"], overlay.css section 6) to both. No line is 18.66 px
or larger, so the floor is 4.5:1 for every one.
"""
import pytest

from tests.snapshot_panels.test_overlay_tft_dim_ink_contrast import _worst
from tests.snapshot_panels.test_overlay_tft_view import _fixture, _open, _wait_tft

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_AA = 4.5
_LARGE = 18.66
_SHEET = "*, *::before, *::after { transition: none !important; }"
_WIDGETS = ("ovt-hud", "ovt-board", "ovt-lobby")

# Per widget: its opacity live and idle (its own transition off inline, the
# attribute restored), then every visible element holding a text node, with
# its ink (alpha times every ancestor opacity below the widget), every
# background from it up to the widget, its size, weight and band.
_MEASURE = """(ids) => {
  const parse = s => {
    const m = /rgba?\\(([^)]+)\\)/.exec(s);
    const p = m ? m[1].split(',').map(Number) : [0, 0, 0, 0];
    return p.length > 3 ? p : [...p, 1];
  };
  const body = document.body;
  const out = {};
  for (const id of ids) {
    const w = document.getElementById(id);
    if (!w || w.hidden || !w.classList.contains('ovx-widget')) {
      out[id] = null;
      continue;
    }
    const had = body.getAttribute('data-rc-idle');
    w.style.transition = 'none';
    body.setAttribute('data-rc-idle', '0');
    const live = parseFloat(getComputedStyle(w).opacity);
    body.setAttribute('data-rc-idle', '1');
    const idle = parseFloat(getComputedStyle(w).opacity);
    if (had === null) body.removeAttribute('data-rc-idle');
    else body.setAttribute('data-rc-idle', had);
    const lines = [];
    for (const el of w.querySelectorAll('*')) {
      if (![...el.childNodes].some(
          n => n.nodeType === 3 && n.textContent.trim())) continue;
      if (!el.checkVisibility()) continue;
      const chain = [];
      let a = 1;
      for (let n = el; n; n = n.parentElement) {
        chain.push(parse(getComputedStyle(n).backgroundColor));
        if (n === w) break;
        a *= parseFloat(getComputedStyle(n).opacity);
      }
      const cs = getComputedStyle(el);
      const ink = parse(cs.color);
      ink[3] *= a;
      lines.push({cls: el.className, text: el.textContent.trim().slice(0, 24),
                  band: el.dataset.band || '', ink, chain, live, idle,
                  size: parseFloat(cs.fontSize), weight: cs.fontWeight});
    }
    out[id] = lines;
  }
  return out;
}"""


def _measure(mock_server, pw_browser, theme):
    ctx, page, errors = _open(
        pw_browser, mock_server, _fixture("tft_overlay_feed"),
        query=f"?overlay=1&theme={theme}")
    try:
        _wait_tft(page)
        page.wait_for_function(
            "() => { const l = document.getElementById('ovt-lobby');"
            " return !!l && !l.hidden"
            " && !!l.querySelector('.ovt-opp[data-band=\"crit\"]'); }",
            timeout=10_000)
        page.add_style_tag(content=_SHEET)
        got = page.evaluate(_MEASURE, list(_WIDGETS))
        booted = page.evaluate(
            "() => document.documentElement.dataset.theme || 'hextech'")
    finally:
        page.close()
        ctx.close()
        mock_server._store["data"] = {}
    assert not errors, f"JS errors [{theme}]: {errors[:3]}"
    assert booted == theme, f"booted on {booted}, not {theme}"
    return got


@pytest.fixture(scope="module")
def measured():
    return {}


def _get(measured, mock_server, pw_browser, theme):
    if theme not in measured:
        measured[theme] = _measure(mock_server, pw_browser, theme)
    return measured[theme]


@pytest.mark.parametrize("theme", _THEMES)
def test_every_tft_overlay_line_reaches_aa_live_and_idle(
        theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme)
    low = []
    for wid in _WIDGETS:
        lines = got[wid]
        # Anchor: a hidden widget or an empty read would pass the loop.
        assert lines, f"{theme}: #{wid} not shown or read no text"
        for ln in lines:
            # The pair is honest only if the widget really recedes and every
            # layer resolved (an unparsed background reads 0 alpha).
            assert 0 < ln["idle"] < ln["live"] == 1.0, (wid, ln["live"], ln["idle"])
            assert ln["chain"][-1][3] > 0, (wid, "widget frame unread", ln["chain"])
            # Every line is under large-text size: the floor is 4.5:1.
            assert ln["size"] < _LARGE, (wid, ln["cls"], ln["size"])
            live, idle = _worst(ln)
            if min(live, idle) < _AA:
                low.append((wid, ln["cls"], ln["band"], ln["text"],
                            round(live, 2), round(idle, 2)))
    assert not low, (theme, low)


@pytest.mark.parametrize("theme", ["hextech", "arcane"])
def test_the_sweep_reads_every_tft_overlay_line_kind(
        theme, measured, mock_server, pw_browser):
    # The sweep covers the lines no single-element pin names: the three pane
    # titles, the source tag, the head clocks, all six cell labels and values,
    # the nine board units and the seven lobby chips with their bands.
    got = _get(measured, mock_server, pw_browser, theme)
    hud, board, lobby = (got[w] for w in _WIDGETS)

    def cls(lines, name):
        return [ln for ln in lines if ln["cls"].split()[0] == name]

    titles = [ln["text"] for w in (hud, board, lobby) for ln in cls(w, "ovt-title")]
    assert titles == ["TFT Vitals", "Board", "Lobby HP"], titles
    assert [ln["text"] for ln in cls(hud, "ovt-src")] == ["ROUND FEED"]
    assert len(cls(hud, "ovt-lab")) == 6 and len(cls(hud, "ovt-val")) == 6
    assert len(cls(board, "ovt-unit-name")) == 9, cls(board, "ovt-unit-name")
    for w in (hud, board, lobby):
        assert len(cls(w, "ovt-time")) == 1, w
    chips = cls(lobby, "ovt-opp")
    assert len(chips) == 7, chips
    bands = sorted(ln["band"] for ln in chips if "is-out" not in ln["cls"])
    assert bands.count("crit") == 2 and bands.count("low") == 4, bands
    assert sum("is-out" in ln["cls"] for ln in chips) == 1, chips
