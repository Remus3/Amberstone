"""
tests/snapshot_panels/test_overlay_tft_dim_ink_contrast.py
S144-U-273 (s144 uiux): the TFT overlay's dimmed ink - the "-" no-data
placeholder in a vitals cell (.ovt-cell.is-empty .ovt-val) and an eliminated
opponent's OUT chip in the Lobby HP widget (.ovt-opp.is-out) - reaches the
WCAG 1.4.3 AA text floor (4.5:1) on its own backing, over any game pixel,
both while the widget is live and in the idle recede.

THE DEFECT. Both rules painted white at alpha 0.45. On the resolved
--ovx-bg-nested chip backing (#0A0E14 at 0.9, over the 0.58 --ovx-bg widget
frame) that is 4.48 - 4.53:1 live, and in the idle recede
(overlay.css section 6, body[data-rc-idle="1"] .ovx-widget opacity 0.85 -
the state the TFT HUD sits in most of a game, s136-T12) 3.52 - 3.83:1 over a
black to white game pixel. Every other dimmed overlay ink rule is 0.55
(overlay.css: the OBJECTIVE footer, --signal-dim and six others); these two
were the only sub-0.55 ink rules in the overlay.

THE FIX (web/js/lib/overlay_tft.js TFT_OVERLAY_CSS). Both rules take the
overlay dim tier, alpha 0.55: 6.06 - 6.24:1 live, 4.63 - 4.99:1 idle. The
dim still reads dimmer than the live ink beside it (0.92 chip / 0.95 value)
and no brighter than the 0.62 cell label. Sizes, weights and boxes are
unchanged.

Contrast pair: the dimmed ink composited down its own ancestor chain (every
background from the element up to the .ovx-widget, as the browser paints
them) over a game pixel G in {0, 64, 128, 192, 255}, against that same chain
without the ink; idle applies the widget's computed idle opacity to both.
"""
import re

from tests.snapshot_panels.test_overlay_tft_view import (
    _fixture,
    _open,
    _wait_tft,
    _with_engine_unknown_coach,
)

_AA = 4.5
_GAME = (0, 64, 128, 192, 255)

# Reads the element's ink, every background from it up to its .ovx-widget,
# and the widget's opacity live and with data-rc-idle="1" (transitions off,
# read synchronously, then restored so no page timer sees the probe).
_READ = """(sel) => {
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
  const tr = widget.style.transition;
  widget.style.transition = 'none';
  body.setAttribute('data-rc-idle', '0');
  const live = parseFloat(getComputedStyle(widget).opacity);
  body.setAttribute('data-rc-idle', '1');
  const idle = parseFloat(getComputedStyle(widget).opacity);
  if (had === null) body.removeAttribute('data-rc-idle');
  else body.setAttribute('data-rc-idle', had);
  widget.style.transition = tr;
  return {text: el.textContent, ink: parse(getComputedStyle(el).color),
          chain, live, idle};
}"""


def _lum(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(float(v)) for v in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(a, b):
    x, y = sorted((_lum(a), _lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def _over(top, base):
    a = top[3]
    return [a * t + (1 - a) * b for t, b in zip(top[:3], base)]


def _worst(read):
    """Lowest (live, idle) ratio over the game pixels for one reading."""
    live = idle = 99.0
    for g in _GAME:
        pix = [float(g)] * 3
        bg = pix
        for layer in reversed(read["chain"]):  # widget frame first
            bg = _over(layer, bg)
        ink = _over(read["ink"], bg)
        live = min(live, _ratio(_over([*ink, read["live"]], pix),
                                _over([*bg, read["live"]], pix)))
        idle = min(idle, _ratio(_over([*ink, read["idle"]], pix),
                                _over([*bg, read["idle"]], pix)))
    return live, idle


def _read(pw_browser, mock_server, st, sel, sib_sel, ready=None):
    ctx, page, errors = _open(pw_browser, mock_server, st)
    try:
        _wait_tft(page)
        if ready:
            page.wait_for_function(ready, timeout=10_000)
        out = page.evaluate(_READ, sel)
        sib = page.evaluate(
            "(s) => [...document.querySelectorAll(s)].map(e => getComputedStyle(e).color)",
            sib_sel,
        )
        label = page.eval_on_selector(
            "#ovt-hud .ovt-lab", "e => getComputedStyle(e).color")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{sel}]: {errors[:3]}"
    assert out is not None, f"{sel} not rendered inside an .ovx-widget"
    return out, sib, label


def _alpha(css):
    p = [float(v) for v in re.search(r"\(([^)]+)\)", css).group(1).split(",")]
    return p[3] if len(p) > 3 else 1.0


def _check(name, read, sib, label):
    # The pair is honest only if the widget really recedes and every layer
    # read resolved to a colour (an unparsed background would read 0 alpha).
    assert 0 < read["idle"] < read["live"] == 1.0, (name, read["live"], read["idle"])
    assert read["chain"][-1][3] > 0, (name, "widget frame unread", read["chain"])
    assert any(c[3] >= 0.85 for c in read["chain"][:-1]), (name, "no chip backing", read["chain"])
    live, idle = _worst(read)
    assert live >= _AA, f"{name} {live:.2f}:1 live, under AA {_AA}"
    assert idle >= _AA, f"{name} {idle:.2f}:1 in the idle recede, under AA {_AA}"
    # HIERARCHY: still the dim tier - dimmer than the live ink beside it and
    # no brighter than the cell label.
    dim = read["ink"][3]
    assert sib, f"{name}: no live sibling to compare against"
    assert all(dim < _alpha(c) for c in sib), (name, dim, sib)
    assert dim <= _alpha(label), (name, dim, label)


def test_tft_overlay_out_chip_reaches_aa_live_and_idle(mock_server, pw_browser):
    """The feed fixture's real end-game lobby (QA match 3) carries one
    eliminated opponent: its OUT chip."""
    read, sib, label = _read(
        pw_browser, mock_server, _fixture("tft_overlay_feed"),
        "#ovt-lobby .ovt-opp.is-out", "#ovt-lobby .ovt-opp:not(.is-out)",
        ready="() => !document.getElementById('ovt-lobby').hidden",
    )
    assert read["text"] == "OUT", read["text"]
    _check("OUT chip", read, sib, label)


def test_tft_overlay_no_data_placeholder_reaches_aa_live_and_idle(mock_server, pw_browser, tmp_path):
    """The s136 T11 engine-unknown payload paints "-" in the HP / level /
    gold cells, each dimmed as is-empty."""
    st = _with_engine_unknown_coach(_fixture("tft_overlay_sentinel"), tmp_path)
    read, sib, label = _read(
        pw_browser, mock_server, st, "#ovt-hud .ovt-cell.is-empty .ovt-val",
        "#ovt-hud .ovt-cell:not(.is-empty) .ovt-val")
    assert read["text"] == "-", read["text"]
    _check("no-data placeholder", read, sib, label)
