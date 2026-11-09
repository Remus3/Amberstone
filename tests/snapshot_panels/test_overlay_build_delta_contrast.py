"""
tests/snapshot_panels/test_overlay_build_delta_contrast.py
S144-U-281 (s144 uiux): the BUILD widget's power-delta numbers - the "+Ndps"
gain under each Daemon Slayer item icon (active_match.js _dsIcon, the LIVE
row only; Meta and Ultimate pass noDelta) - reach the WCAG 1.4.3 AA text
floor (4.5:1) in the overlay shell live and in the idle recede, in all six
themes and every League mode, and keep the accent hue that marks them as
the module's key build signal.

THE DEFECT. QA ledger FUTURE (g) filed the numbers at 4.48:1 idle while the
rerank row still painted outside the w-build clip (fixed in S144-U-280), so
the reading needed a fresh pin. Re-measured headless (mock server,
?ui_mock=1&mode=<sr|aram|mayhem|arena>&overlay=1, 1920x1080 and 1920x920,
every visible text line of w-build, six themes, five game pixels): the
numbers were the only text inside the clip under its floor. They painted
var(--accent) from an inline style (16 px --fs-xs, weight 600, not WCAG
large text). Arcane's accent is a muted lavender (#ad9dbd), so on the 0.9
nested backing they read 6.12:1 live and 4.48:1 in the idle recede (widget
opacity 0.85), in all four modes. Every other theme's accent is a bright
gold and passed.

THE FIX. The inline style becomes the .bm-delta class (build_module.css,
the same values, so the dashboard copy keeps var(--accent): 6.12:1 at worst
on the opaque pane, arcane). In the overlay BUILD widget only, overlay.css
lifts the ink toward --text, color-mix(in oklab, var(--accent) 80%,
var(--text)), the RM-1550 lift: the hue stays, the floor holds idle.

Contrast pair (the S144-U-275 / S144-U-278 method): the ink, with any
opacity inside the widget folded in, over the backgrounds of the line and
of every ancestor up to its widget whose box contains the line, then the
widget opacity, over a game pixel G in {0, 64, 128, 192, 255}, against the
same chain without the ink.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_overlay_hotkey_hint_contrast import _worst

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_MODES = ["sr", "aram", "mayhem", "arena"]
_AA = 4.5
_SHEET = "*, *::before, *::after { transition: none !important; }"
_W = '.ovx-widget[data-ovx-id="w-build"]'
_DELTA = ".bm-live .bm-strip .bm-delta"

# One synchronous read per idle state: no poll can repaint between the
# delta reads and the opacity reads.
_READ = """([idle, wsel, dsel]) => {
""" + _HELPERS + """
  const body = document.body;
  body.setAttribute('data-rc-idle', idle ? '1' : '0');
  const inside = (o, i) => i.left >= o.left - 0.5 && i.right <= o.right + 0.5
    && i.top >= o.top - 0.5 && i.bottom <= o.bottom + 0.5;
  const w = document.querySelector(wsel);
  if (!w) return null;
  const wr = w.getBoundingClientRect();
  const clip = {left: wr.left + w.clientLeft, top: wr.top + w.clientTop};
  clip.right = clip.left + w.clientWidth;
  clip.bottom = clip.top + w.clientHeight;
  let wop = 1;
  for (let n = w; n; n = n.parentElement) {
    wop *= parseFloat(getComputedStyle(n).opacity);
  }
  const accent = rgba(getComputedStyle(body).getPropertyValue('--accent'));
  const text = rgba(getComputedStyle(body).getPropertyValue('--text'));
  const deltas = [];
  for (const h of w.querySelectorAll(dsel)) {
    const hb = h.getBoundingClientRect();
    const layers = [];
    let inner = 1;
    for (let n = h; n; n = n.parentElement) {
      const cs = getComputedStyle(n);
      const b = rgba(cs.backgroundColor);
      if (b[3] > 0 && inside(n.getBoundingClientRect(), hb)) layers.push(b);
      if (n === w) break;
      inner *= parseFloat(cs.opacity);
    }
    const cs = getComputedStyle(h);
    deltas.push({text: h.textContent.trim(), color: rgba(cs.color),
                 inner: inner, layers: layers, wop: wop,
                 size: parseFloat(cs.fontSize), weight: cs.fontWeight,
                 inline: h.getAttribute('style') || '',
                 inClip: inside(clip, hb), visible: h.checkVisibility()});
  }
  return {deltas: deltas, accent: accent, text: text};
}"""

# The dashboard copy (no overlay shell): the same class, untouched ink.
_DASH = """(dsel) => {
""" + _HELPERS + """
  const body = document.body;
  const accent = rgba(getComputedStyle(body).getPropertyValue('--accent'));
  return {accent: accent, shell: body.dataset.shell || '',
          deltas: [...document.querySelectorAll('#am-build-body ' + dsel)]
            .map((h) => {
              const cs = getComputedStyle(h);
              return {text: h.textContent.trim(), color: rgba(cs.color),
                      size: parseFloat(cs.fontSize), weight: cs.fontWeight,
                      inline: h.getAttribute('style') || '',
                      visible: h.checkVisibility()};
            })};
}"""


def _open(mock_server, pw_browser, url, height):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": height})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + url, wait_until="domcontentloaded",
              timeout=15_000)
    return ctx, page, errors


@pytest.fixture(scope="module")
def measured():
    return {}


def _measure(mock_server, pw_browser, theme, mode):
    ctx, page, errors = _open(
        mock_server, pw_browser,
        f"/?ui_mock=1&mode={mode}&overlay=1&theme={theme}", 1080)
    try:
        page.wait_for_function(
            "() => document.body.dataset.shell === 'overlay'", timeout=10_000)
        page.wait_for_selector(f"{_W} {_DELTA}", state="visible",
                               timeout=10_000)
        page.add_style_tag(content=_SHEET)
        got = {"live": page.evaluate(_READ, [0, _W, _DELTA]),
               "idle": page.evaluate(_READ, [1, _W, _DELTA])}
        got["theme"] = page.evaluate(
            "() => document.documentElement.dataset.theme || 'hextech'")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert got["theme"] == theme, f"booted on {got['theme']}, not {theme}"
    assert got["live"] and got["idle"], "w-build is not on the page"
    return got


def _get(measured, mock_server, pw_browser, theme, mode):
    key = (theme, mode)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, mode)
    return measured[key]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("theme", _THEMES)
def test_the_power_deltas_reach_aa_live_and_idle(
        theme, mode, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, mode)
    bad = []
    for state in ("live", "idle"):
        deltas = got[state]["deltas"]
        # The LIVE row carries a number under every item: an empty read
        # cannot pass.
        assert len(deltas) >= 3, (state, deltas)
        for x in deltas:
            assert x["text"].startswith("+"), x["text"]
            assert x["visible"] and x["inClip"], (
                f"{theme} {mode} {state}: {x['text']} is not painted inside"
                f" the w-build clip")
            assert x["layers"], (state, x)
            ratio = _worst(x)
            if ratio < _AA:
                bad.append(f"{state} {x['text']} {ratio:.2f}:1 (ink"
                           f" {x['color']}, wop {x['wop']:.2f})")
    # The idle pair is honest only if the widget really recedes.
    assert got["live"]["deltas"][0]["wop"] == 1.0
    assert 0 < got["idle"]["deltas"][0]["wop"] < 1.0
    assert not bad, f"{theme} {mode}: " + "; ".join(bad[:4])


@pytest.mark.parametrize("theme", _THEMES)
def test_the_overlay_delta_keeps_its_type_and_the_accent_hue(
        theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, "sr")["live"]
    acc, txt = got["accent"], got["text"]
    for x in got["deltas"]:
        # Styled by the class, not an inline style CSS cannot reach.
        assert "color" not in x["inline"], x["inline"]
        assert x["size"] == 16.0 and x["weight"] == "600", x
        ink = x["color"][:3]
        # A hue tier, not body ink: nearer the theme accent than --text.
        d_acc = sum((a - b) ** 2 for a, b in zip(ink, acc[:3]))
        d_txt = sum((a - b) ** 2 for a, b in zip(ink, txt[:3]))
        assert d_acc < d_txt, (theme, ink, acc, txt)


@pytest.mark.parametrize("theme", ["hextech", "arcane"])
def test_the_dashboard_delta_keeps_the_bare_accent(
        theme, mock_server, pw_browser):
    # The Active Match route (#active-match) mounts the dashboard BUILD pane.
    ctx, page, errors = _open(
        mock_server, pw_browser,
        f"/?ui_mock=1&mode=sr&theme={theme}#active-match", 920)
    try:
        page.wait_for_selector(f"#am-build-body {_DELTA}", state="visible",
                               timeout=10_000)
        got = page.evaluate(_DASH, _DELTA)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert got["shell"] != "overlay"
    assert len(got["deltas"]) >= 3, got
    for x in got["deltas"]:
        assert x["visible"], x
        assert x["inline"] == "", x["inline"]
        assert x["size"] == 16.0 and x["weight"] == "600", x
        assert x["color"] == got["accent"], (theme, x["color"], got["accent"])
