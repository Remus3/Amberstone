"""
tests/snapshot_panels/test_tab_bars_selected_state.py
RM-1083 (s144 uiux): RM-1082 found the PANEL VISIBILITY selected tab
drawn in an accent colour only, dimmer than its unselected siblings on the
arcane theme. This is the sweep of every OTHER tab bar the dashboard renders
under /?ui_mock=1 at 1920x920, on all six themes: Home mode tabs, the History
scope tabs, the Build Insights tab strip and the five selector bars its chart
tabs paint (Game Length / Benchmarks / OP Score mode, Game Flow mode and
metric).

Each bar must make its selected tab the most salient one, by two measured
rules, plus AA:
  - CUE: the selected tab carries its own fill (its effective background
    differs from every unselected sibling's) or an inset underline the
    unselected tabs lack - a 1px border colour alone is not a cue.
  - SALIENCE: the selected tab's text is brighter than every unselected
    tab's text. An INVERTED pill (dark text on a fill brighter than that
    text, .bi-tab.is-active) is salient by its fill instead: the fill is
    brighter than every unselected tab's fill and clears the 3:1 non-text
    contrast floor (WCAG 1.4.11) against the bar's own surface.
  - AA: each tab's text clears 4.5:1 on its own effective fill (a named PAIR,
    text on that tab's fill, not a token on some other surface).

Colours are RESOLVED, not grepped: every computed colour (themes.css declares
several as oklch() over a hex sibling) is painted onto a 1x1 canvas over the
composited ancestor backgrounds and read back as sRGB. Transitions are off
for the read: .bi-tab, .home-mode-tab and the History .view-tab animate their
colour, so a computed value read right after the theme swap is still the
PREVIOUS theme's (measured: every theme read back arcane's --text-dim).
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

VIEWPORT = {"width": 1920, "height": 920}

# Every theme the picker offers (web/js/lib/theme.js THEMES). hextech is the
# ABSENCE of the attribute; the others stamp <html data-theme>.
_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]

# (bar id, view hash, the Build Insights tab to click first or None, CSS
# selector of the bar's tabs, expected tab count).
_BARS = [
    ("home-mode", "home", None, "#home-mode-tabs .home-mode-tab", 4),
    ("history-scope", "history", None, "#history-scope-tabs .view-tab", 4),
    ("bi-tabs", "build-insights", None, "#bi-tabs .bi-tab", 9),
    ("dw-mode", "build-insights", "duration", "#bi-duration-mount .dw-mode-btn", 3),
    ("cb-mode", "build-insights", "bench", "#bi-bench-mount .cb-mode-btn", 3),
    ("op-mode", "build-insights", "opscore", "#bi-opscore-mount .op-mode-btn", 3),
    ("pf-mode", "build-insights", "flow", "#bi-flow-mount .pf-mode-btn", 3),
    ("pf-metric", "build-insights", "flow", "#bi-flow-mount .pf-metric-btn", 2),
]

_MEASURE = """
([sel, themes]) => {
  const root = document.documentElement;
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
  // Background colours from <html> down to `el`, bottom first.
  const stack = (el) => {
    const out = [];
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      out.unshift(getComputedStyle(n).backgroundColor);
    }
    return out;
  };
  const isSel = (el) => el.getAttribute('aria-selected') === 'true' ||
    el.getAttribute('aria-pressed') === 'true' ||
    el.classList.contains('active') || el.classList.contains('is-active');
  if (document.activeElement) document.activeElement.blur();
  const out = {};
  for (const t of themes) {
    if (t === 'hextech') root.removeAttribute('data-theme');
    else root.dataset.theme = t;
    out[t] = Array.from(document.querySelectorAll(sel)).map((el) => {
      const cs = getComputedStyle(el);
      const fill = px(stack(el));
      const surround = px(stack(el.parentElement));
      const r = el.getBoundingClientRect();
      return {
        label: (el.textContent || '').trim(),
        selected: isSel(el),
        focused: el === document.activeElement,
        shadow: cs.boxShadow,
        fill,
        surround,
        text: px(['rgb(' + fill.join(',') + ')', cs.color]),
        width: r.width,
        height: r.height,
      };
    });
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


def _open(pw_browser, mock_server, view, bi_tab, sel):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(ignore_https_errors=True, viewport=VIEWPORT)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + "/?ui_mock=1#" + view,
        wait_until="domcontentloaded", timeout=15_000,
    )
    page.wait_for_function(
        f"document.body.dataset.view === {view!r}", timeout=10_000,
    )
    page.add_style_tag(
        content="*, *::before, *::after { transition: none !important; }"
    )
    if bi_tab:
        page.click(f"#bi-tabs .bi-tab[data-bi-tab={bi_tab!r}]")
    page.wait_for_function(
        f"document.querySelectorAll({sel!r}).length > 1 && "
        f"document.querySelector({sel!r}).getBoundingClientRect().width > 0",
        timeout=10_000,
    )
    return ctx, page, errors


@pytest.fixture(scope="module")
def measured(mock_server, pw_browser):
    out = {}
    for bar, view, bi_tab, sel, count in _BARS:
        ctx, page, errors = _open(pw_browser, mock_server, view, bi_tab, sel)
        try:
            out[bar] = (page.evaluate(_MEASURE, [sel, _THEMES]), errors, count)
        finally:
            page.close()
            ctx.close()
    return out


def _split(measured, bar, theme):
    by_theme, _errors, count = measured[bar]
    tabs = by_theme[theme]
    sel = [t for t in tabs if t["selected"]]
    other = [t for t in tabs if not t["selected"]]
    # Anchors: the expected tab count, every tab laid out, exactly one
    # selected and none focused (the blur ran), so a box-shadow below is the
    # tab's own rule, never the focus ring.
    assert len(tabs) == count, f"{bar}/{theme}: {len(tabs)} tabs"
    assert all(t["width"] > 0 and t["height"] > 0 for t in tabs), bar
    assert len(sel) == 1 and other, (
        f"{bar}/{theme}: selected {[t['label'] for t in sel]}"
    )
    assert not any(t["focused"] for t in tabs), f"{bar}/{theme}: focus held"
    return sel[0], other


_CASES = [(b[0], t) for b in _BARS for t in _THEMES]


def test_measured_every_bar_and_theme(measured):
    assert sorted(measured) == sorted(b[0] for b in _BARS), list(measured)
    for bar, (by_theme, errors, _count) in measured.items():
        assert sorted(by_theme) == sorted(_THEMES), bar
        assert not errors, (bar, errors[:3])
    # The canvas readback resolved distinct colours per theme (an all-black
    # readback would pass every comparison below by accident).
    fills = {tuple(t["fill"]) for tabs in measured["bi-tabs"][0].values()
             for t in tabs if not t["selected"]}
    assert len(fills) >= 3, f"tab fills did not vary by theme: {fills}"


@pytest.mark.parametrize("bar,theme", _CASES)
def test_selected_tab_carries_a_fill_or_an_underline(measured, bar, theme):
    sel, other = _split(measured, bar, theme)
    own_fill = all(sel["fill"] != o["fill"] for o in other)
    underline = "inset" in sel["shadow"] and all(
        "inset" not in o["shadow"] for o in other
    )
    assert own_fill or underline, (
        f"{bar}/{theme}: selected {sel['label']!r} fill {sel['fill']} "
        f"shadow {sel['shadow']!r} matches unselected "
        f"{[(o['label'], o['fill']) for o in other]}"
    )


@pytest.mark.parametrize("bar,theme", _CASES)
def test_selected_tab_is_the_brightest_of_its_bar(measured, bar, theme):
    sel, other = _split(measured, bar, theme)
    if _lum(sel["fill"]) > _lum(sel["text"]):
        # Inverted pill: salient by its fill.
        for o in other:
            assert _lum(sel["fill"]) > _lum(o["fill"]), (
                f"{bar}/{theme}: pill fill {sel['fill']} not brighter than "
                f"{o['label']!r} fill {o['fill']}"
            )
        r = _ratio(sel["fill"], sel["surround"])
        assert r >= 3.0, (
            f"{bar}/{theme}: pill fill {sel['fill']} on bar surface "
            f"{sel['surround']} is {r:.2f}:1"
        )
        return
    for o in other:
        assert _lum(sel["text"]) > _lum(o["text"]), (
            f"{bar}/{theme}: selected {sel['label']!r} text {sel['text']} "
            f"(L={_lum(sel['text']):.3f}) is not brighter than {o['label']!r} "
            f"text {o['text']} (L={_lum(o['text']):.3f})"
        )


@pytest.mark.parametrize("bar,theme", _CASES)
def test_tab_text_clears_aa_on_its_own_fill(measured, bar, theme):
    sel, other = _split(measured, bar, theme)
    for t in [sel, *other]:
        r = _ratio(t["text"], t["fill"])
        assert r >= 4.5, (
            f"{bar}/{theme}: {t['label']!r} text {t['text']} on its fill "
            f"{t['fill']} is {r:.2f}:1"
        )


# The five Build Insights selector bars gained the one system focus ring in
# RM-1083 (they had only the UA outline). A keyboard-focused button, the
# selected one included, draws --focus-ring as an OUTER box-shadow with no
# outline; on the selected button it replaces the inset underline while focus
# is held (the --signal-info border and --text stay the selection cue).
_BI_SELECTOR_BARS = [b for b in _BARS if b[2] is not None]


@pytest.mark.parametrize(
    "bar,view,bi_tab,sel,_count", _BI_SELECTOR_BARS, ids=[b[0] for b in _BI_SELECTOR_BARS],
)
def test_selector_buttons_draw_the_system_focus_ring(
    mock_server, pw_browser, bar, view, bi_tab, sel, _count,
):
    ctx, page, errors = _open(pw_browser, mock_server, view, bi_tab, sel)
    try:
        # A key press puts Chromium in keyboard modality, so a programmatic
        # focus() then matches :focus-visible as a Tab would.
        page.keyboard.press("Shift")
        rows = page.evaluate(
            """(sel) => {
              const probe = document.createElement('div');
              probe.style.boxShadow = 'var(--focus-ring)';
              document.body.appendChild(probe);
              const ring = getComputedStyle(probe).boxShadow;
              probe.remove();
              return Array.from(document.querySelectorAll(sel)).map((el) => {
                el.focus();
                const cs = getComputedStyle(el);
                return {
                  label: (el.textContent || '').trim(),
                  selected: el.classList.contains('is-active'),
                  visible: el.matches(':focus-visible'),
                  outline: cs.outlineStyle,
                  shadow: cs.boxShadow,
                  ring,
                };
              });
            }""",
            sel,
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert any(r["selected"] for r in rows) and any(not r["selected"] for r in rows)
    for r in rows:
        assert r["ring"] not in ("", "none"), f"{bar}: --focus-ring resolved {r['ring']!r}"
        assert r["visible"], f"{bar}: {r['label']!r} did not match :focus-visible"
        assert r["outline"] == "none", f"{bar}: {r['label']!r} outline {r['outline']!r}"
        assert r["shadow"] == r["ring"], (
            f"{bar}: {r['label']!r} focused shadow {r['shadow']!r} != ring {r['ring']!r}"
        )
