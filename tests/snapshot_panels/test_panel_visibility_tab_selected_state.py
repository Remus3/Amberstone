"""
tests/snapshot_panels/test_panel_visibility_tab_selected_state.py
RM-1082 (s144 uiux): the PANEL VISIBILITY selected context tab did not read
as selected. web/css/panels/panel_visibility.css drew every `.pv-tab` in
var(--text-dim) and the selected one in var(--clock) with a --clock border,
nothing else. Measured in headless Chromium under /?ui_mock=1#settings at
1920x920: on the default arcane theme --clock (oklch 0.72) is DIMMER than
--text-dim (oklch 0.74), so the selected tab was the darker of the pair, and
on every theme the only other cue was a 1px border colour. The tab that
names which context the checkboxes below edit was the hardest one to find.

Fix: the selected tab takes the brightest text token (var(--text)), the
input-well fill (var(--surface-3)) and a 2px inset --clock underline - the
same fill + underline idiom as `.home-mode-tab.active` (web/css/panels/
home.css). The --clock border stays. A focused tab still draws the system
--focus-ring (RM-1061 / RM-1081); that rule comes later in the file and
replaces the underline while focus is on the tab, the fill and text remain.

Colours are RESOLVED, not grepped: each computed colour (themes.css declares
several as oklch() over a hex sibling) is painted onto a 1x1 canvas and read
back as sRGB, composited over the card surface the tab actually sits on, so
every ratio below is a named PAIR (text on the tab's own effective fill).
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

VIEWPORT = {"width": 1920, "height": 920}

# Every theme the picker offers (web/js/lib/theme.js THEMES). hextech is the
# ABSENCE of the attribute; the others stamp <html data-theme>.
_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]

_MEASURE = """
(themes) => {
  const root = document.documentElement;
  const card = document.getElementById('panel-visibility-card');
  const cv = document.createElement('canvas');
  cv.width = 1; cv.height = 1;
  const g = cv.getContext('2d', {willReadFrequently: true});
  // Paint `layers` (CSS colours, bottom first) and read the pixel back.
  const px = (layers) => {
    g.clearRect(0, 0, 1, 1);
    g.fillStyle = '#000'; g.fillRect(0, 0, 1, 1);
    for (const c of layers) { g.fillStyle = c; g.fillRect(0, 0, 1, 1); }
    const d = g.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2]];
  };
  if (document.activeElement) document.activeElement.blur();
  const out = {};
  for (const t of themes) {
    if (t === 'hextech') root.removeAttribute('data-theme');
    else root.dataset.theme = t;
    const cardBg = getComputedStyle(card).backgroundColor;
    const tabs = Array.from(card.querySelectorAll('.pv-tab')).map((el) => {
      const cs = getComputedStyle(el);
      const fill = px([cardBg, cs.backgroundColor]);
      const fillCss = 'rgb(' + fill.join(',') + ')';
      return {
        ctx: el.dataset.pvTab,
        selected: el.getAttribute('aria-selected') === 'true',
        focused: el === document.activeElement,
        bg: cs.backgroundColor,
        shadow: cs.boxShadow,
        weight: cs.fontWeight,
        minHeight: parseFloat(cs.minHeight),
        height: el.getBoundingClientRect().height,
        fill,
        text: px([fillCss, cs.color]),
        cardFill: px([cardBg]),
      };
    });
    out[t] = tabs;
  }
  return out;
}
"""


def _lum(rgb):
    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


@pytest.fixture
def measured(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(ignore_https_errors=True, viewport=VIEWPORT)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url + "/?ui_mock=1#settings",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "document.body.dataset.view === 'settings' && "
            "document.querySelector('#panel-visibility-card .pv-cell') !== null",
            timeout=10_000,
        )
        yield page.evaluate(_MEASURE, _THEMES), errors
    finally:
        page.close()
        ctx.close()


def _split(tabs, theme):
    sel = [t for t in tabs if t["selected"]]
    other = [t for t in tabs if not t["selected"]]
    # Anchors: five tabs, exactly one selected, none focused (the blur ran),
    # so the selected tab's box-shadow is its own rule, not the focus ring.
    assert len(tabs) == 5, f"{theme}: {len(tabs)} tabs"
    assert len(sel) == 1 and len(other) == 4, f"{theme}: {[t['ctx'] for t in sel]}"
    assert not any(t["focused"] for t in tabs), f"{theme}: a tab holds focus"
    return sel[0], other


def test_measured_every_theme(measured):
    by_theme, errors = measured
    assert sorted(by_theme) == sorted(_THEMES), list(by_theme)
    # The canvas readback really resolved distinct colours per theme (an
    # all-black readback would pass every comparison below by accident).
    cards = {tuple(tabs[0]["cardFill"]) for tabs in by_theme.values()}
    assert len(cards) >= 3, f"card surface did not vary by theme: {cards}"
    assert not errors, errors[:3]


@pytest.mark.parametrize("theme", _THEMES)
def test_selected_tab_text_is_the_brightest_of_the_bar(measured, theme):
    sel, other = _split(measured[0][theme], theme)
    sel_l = _lum(sel["text"])
    for o in other:
        assert sel_l > _lum(o["text"]), (
            f"{theme}: selected {sel['ctx']} text {sel['text']} "
            f"(L={sel_l:.3f}) is not brighter than {o['ctx']} text "
            f"{o['text']} (L={_lum(o['text']):.3f})"
        )


@pytest.mark.parametrize("theme", _THEMES)
def test_selected_tab_carries_a_fill_and_an_underline(measured, theme):
    sel, other = _split(measured[0][theme], theme)
    # Fill: the selected tab's effective background differs from the card it
    # sits on; every unselected tab is the card itself (transparent).
    assert sel["fill"] != sel["cardFill"], (
        f"{theme}: selected fill {sel['fill']} == card {sel['cardFill']}"
    )
    for o in other:
        assert o["fill"] == o["cardFill"], f"{theme}: {o['ctx']} is filled {o['bg']}"
    # Underline: an inset bottom stroke on the selected tab only.
    assert "inset" in sel["shadow"] and "-2px" in sel["shadow"], (
        f"{theme}: selected box-shadow {sel['shadow']!r}"
    )
    for o in other:
        assert o["shadow"] == "none", f"{theme}: {o['ctx']} shadow {o['shadow']!r}"


@pytest.mark.parametrize("theme", _THEMES)
def test_tab_text_clears_aa_on_its_own_fill(measured, theme):
    sel, other = _split(measured[0][theme], theme)
    # PAIRS: selected = --text on (--surface-3 over the card surface);
    # unselected = --text-dim on the card surface (--surface).
    r = _ratio(sel["text"], sel["fill"])
    assert r >= 4.5, f"{theme}: selected text on its fill {r:.2f}:1"
    for o in other:
        r = _ratio(o["text"], o["fill"])
        assert r >= 4.5, f"{theme}: {o['ctx']} text on card {r:.2f}:1"


@pytest.mark.parametrize("theme", _THEMES)
def test_selection_keeps_the_hit_target_and_does_not_reflow(measured, theme):
    sel, other = _split(measured[0][theme], theme)
    # Same weight and height selected or not: no shift when selection moves.
    assert {t["weight"] for t in [sel, *other]} == {sel["weight"]}, theme
    assert {t["height"] for t in [sel, *other]} == {sel["height"]}, theme
    assert sel["height"] >= sel["minHeight"] >= 42, (theme, sel["height"])
