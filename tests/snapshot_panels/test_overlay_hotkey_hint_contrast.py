"""
tests/snapshot_panels/test_overlay_hotkey_hint_contrast.py
S144-U-278 (s144 uiux): every overlay hotkey reminder (.ovx-hotkey-hint,
doctrine section 11) reaches the WCAG 1.4.3 AA text floor (4.5:1) on the
backing it really sits on, over any game pixel, both while its widget is
live and in the idle recede, in all six themes.

THE DEFECTS. MEASURED headless (mock server, ?ui_mock=1&mode=<sr|tft>
&overlay=1, 1920x1080, six themes; a synthetic two-chip A/B pick rendered so
the w-choices reminder shows too). Every reminder painted
rgba(--ovx-text, 0.55) at 12 px (--fs-ov-sigil):
- the w-launcher reminder "Ctrl+Shift+A" sits UNDER the 34 px launcher
  square (top 35 px, overlay.css), outside every box that has a background,
  so its only backing was the game itself: 1.00:1 over a white game pixel,
  live and idle, in every mode and every theme (it is the one reminder the
  TFT field shows too);
- the w-choices reminder sits on the see-through 0.58 widget wash: 2.36:1
  live, 1.99:1 idle;
- the w-build / w-ovds reminders sit on their widget's 0.9 nested backing
  and read AA live, but 4.18:1 - 4.48:1 in the idle recede (overlay.css
  section 6, widget opacity 0.85) over a white game pixel.

THE FIX (web/css/overlay.css). Every reminder carries its own nested
backing pill, the same rgba(--ovx-bg-nested, 0.9) every widget row uses,
and its ink rises from 0.55 to 0.70 (still neutral, still under the 0.75 /
0.92 body-ink tiers). The launcher's pill keeps inside the gap the
hotkey-hints audit pins (bottom <= design y 72, right <= design x 70).
After, worst over six themes: launcher 8.22 live / 5.64 idle, w-choices
9.12 / 6.45, w-build and w-ovds 9.57 / 7.05.

Contrast pair (the S144-U-275 method): the ink, with any opacity inside the
widget folded in, over the backgrounds of the reminder and of every ancestor
up to its widget WHOSE BOX CONTAINS THE REMINDER (a box the reminder sits
outside does not back it), then the widget opacity, over a game pixel G in
{0, 64, 128, 192, 255}, against the same chain without the ink.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_MODES = ["sr", "tft"]
_AA = 4.5
_GAME = (0, 64, 128, 192, 255)
_SHEET = "*, *::before, *::after { transition: none !important; }"
# The reminders each field shows (doctrine section 11 table; the TFT field
# carries the launcher only - test_overlay_hotkey_hints pins the same sets).
_EXPECT = {
    "sr": {"w-launcher", "w-build", "w-ovds", "w-choices"},
    "tft": {"w-launcher"},
}

_CHOICES = """async () => {
  const C = await import('/js/panels/coach_choices.js');
  C.renderCoachChoices({coach: {choices: [
    {key: 'A', label: 'Trade', confidence: 'high'},
    {key: 'B', label: 'Back off', confidence: 'mid'}]}});
  (await import('/js/lib/overlay_layout.js')).placeOverlayField();
}"""

# One synchronous read per idle state: no poll can repaint between the
# reminder reads and the opacity reads.
_READ = """(idle) => {
""" + _HELPERS + """
  const body = document.body;
  body.setAttribute('data-rc-idle', idle ? '1' : '0');
  const inside = (o, i) => i.left >= o.left - 0.5 && i.right <= o.right + 0.5
    && i.top >= o.top - 0.5 && i.bottom <= o.bottom + 0.5;
  const out = [];
  for (const h of document.querySelectorAll('.ovx-hotkey-hint')) {
    if (!h.checkVisibility()) continue;
    const w = h.closest('.ovx-widget');
    if (!w) continue;
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
    let wop = 1;
    for (let n = w; n; n = n.parentElement) {
      wop *= parseFloat(getComputedStyle(n).opacity);
    }
    const cs = getComputedStyle(h);
    out.push({id: w.dataset.ovxId, text: h.textContent.trim(),
              color: rgba(cs.color), inner: inner, layers: layers,
              wop: wop, size: parseFloat(cs.fontSize),
              box: {x: hb.left, y: hb.top, r: hb.right, b: hb.bottom},
              outside: !inside(w.getBoundingClientRect(), hb)});
  }
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


def _worst(hint):
    """Lowest ratio of the reminder over the game pixels."""
    ink = [*hint["color"][:3], hint["color"][3] * hint["inner"]]
    op = hint["wop"]
    worst = 99.0
    for gp in _GAME:
        pix = [float(gp)] * 3
        bg = pix
        for layer in reversed(hint["layers"]):
            bg = _over(layer, bg)
        fg = _over(ink, bg)
        worst = min(worst, _ratio(_over([*fg, op], pix),
                                  _over([*bg, op], pix)))
    return worst


@pytest.fixture(scope="module")
def measured():
    return {}


def _measure(mock_server, pw_browser, theme, mode):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url
                  + f"/?ui_mock=1&mode={mode}&overlay=1&theme={theme}",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "() => document.body.dataset.shell === 'overlay'"
            " && !!document.querySelector('#w-launcher > .ovx-hotkey-hint')",
            timeout=10_000)
        if mode != "tft":
            page.wait_for_selector("#am-pane-ovds > .ovx-hotkey-hint",
                                   state="attached", timeout=10_000)
            page.evaluate(_CHOICES)
        page.add_style_tag(content=_SHEET)
        got = {"live": page.evaluate(_READ, 0), "idle": page.evaluate(_READ, 1)}
        got["theme"] = page.evaluate(
            "() => document.documentElement.dataset.theme || 'hextech'")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert got["theme"] == theme, f"booted on {got['theme']}, not {theme}"
    return got


def _get(measured, mock_server, pw_browser, theme, mode):
    key = (theme, mode)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, mode)
    return measured[key]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("theme", _THEMES)
def test_every_hotkey_hint_reaches_aa_live_and_idle(
        theme, mode, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, mode)
    bad = []
    for state in ("live", "idle"):
        hints = got[state]
        # The field's reminders are on the page, so an empty read cannot pass.
        assert {h["id"] for h in hints} == _EXPECT[mode], (state, hints)
        for h in hints:
            ratio = _worst(h)
            if ratio < _AA:
                bad.append(f"{state} {h['id']} {h['text']!r} {ratio:.2f}:1"
                           f" (ink {h['color']}, wop {h['wop']:.2f},"
                           f" {len(h['layers'])} backing layers)")
    assert not bad, f"{theme} {mode}: " + "; ".join(bad)


@pytest.mark.parametrize("theme", ["hextech", "arcane"])
def test_the_recede_is_real_and_the_hint_stays_a_quiet_neutral(
        theme, measured, mock_server, pw_browser):
    # The idle pair is honest only if the widgets really recede; the
    # reminder stays neutral ink (no status hue, doctrine section 11) and
    # quieter than the 0.75 / 0.92 body-ink tiers.
    got = _get(measured, mock_server, pw_browser, theme, "sr")
    live = {h["id"]: h for h in got["live"]}
    idle = {h["id"]: h for h in got["idle"]}
    for wid, h in live.items():
        assert h["wop"] == 1.0, (wid, h["wop"])
        assert 0 < idle[wid]["wop"] < 1.0, (wid, idle[wid]["wop"])
        r, g, b, a = h["color"]
        assert r == g == b == 255, (wid, h["color"])
        assert 0.6 <= a < 0.75, (wid, h["color"])
        assert h["size"] == 12.0, (wid, h["size"])
        assert h["inner"] == 1.0, (wid, h["inner"])


@pytest.mark.parametrize("theme", ["hextech", "arcane"])
def test_the_launcher_hint_carries_its_own_backing_in_its_gap(
        theme, measured, mock_server, pw_browser):
    # The launcher reminder sits under the square, outside its box, so the
    # square's background does not back it: it carries its own. It stays in
    # the gap the hotkey-hints audit pins (bottom <= design y 72, above the
    # rc-shell ON/OFF icon; right <= design x 70, left of the TFT vitals).
    for mode in _MODES:
        got = _get(measured, mock_server, pw_browser, theme, mode)
        h = {x["id"]: x for x in got["live"]}["w-launcher"]
        assert h["outside"], (mode, h["box"])
        assert h["layers"], (mode, h)
        own = h["layers"][0]
        assert own[3] >= 0.85, (mode, own)
        assert h["box"]["b"] <= 72 and h["box"]["r"] <= 70, (mode, h["box"])
        assert h["box"]["x"] >= 0 and h["box"]["y"] >= 0, (mode, h["box"])
