"""
tests/snapshot_panels/test_ui_mock_active_match_build_eyebrows.py
The Active Match BUILD pane's row eyebrows (session 144, lane uiux,
S144-U-233).

web/css/panels/build_module.css paints each row's eyebrow (.bm-row-label:
"Daemon Slayer", "Meta Build", "Ultimate Build") at the --fs-xs floor, bold,
uppercase. The Daemon Slayer eyebrow is the headline (#6cf); Meta Build and
Ultimate Build read in var(--text-faint). Measured on the headless render
(?ui_mock=1&mode=sr and mode=complete, 1920x920) before this slice, against
the BUILD pane surface they sit on (.am-pane-build): 4.31:1 on arcane, 4.39
on ember, 4.46 on hextech, 4.48 on moonlit - under the 4.5:1 AA floor for
16 px text (bold 16 px is not WCAG large text, which starts at 18.66 px
bold). S144-U-215 moved the empty-row line in the same module off
--text-faint for the same reason and left the eyebrows behind.

Contract pinned here, in every theme, on the dashboard and the overlay:
  - every row eyebrow is at the --fs-xs floor and reaches 4.5:1 against the
    opaque surface it resolves to;
  - hierarchy: the Daemon Slayer eyebrow stays the brightest of the three
    (the headline row), so the fix lifts the other two without flattening
    the module.

Colours resolve through a canvas pixel (themes.css declares oklch()).
"""
import pytest

from tests.snapshot_panels.test_ui_mock_active_match_complete import (
    _SURFACES,
    _THEMES,
    _open,
)

_LABELS = ["Daemon Slayer", "Meta Build", "Ultimate Build"]

_EYEBROW_JS = """() => {
  const cv = document.createElement('canvas');
  cv.width = 1; cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => {
    cx.clearRect(0, 0, 1, 1);
    cx.fillStyle = '#000';
    cx.fillStyle = c;
    cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  };
  const lum = (c) => {
    const [r, g, b] = rgba(c).slice(0, 3).map(v => {
      v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  return Array.from(document.querySelectorAll(
    '#am-build-body .bm-row > .bm-row-label')).map(el => {
    let bgEl = el, bg = null;
    while (bgEl) {
      const c = getComputedStyle(bgEl).backgroundColor;
      if (rgba(c)[3] === 1) { bg = c; break; }
      bgEl = bgEl.parentElement;
    }
    const cs = getComputedStyle(el);
    const L1 = lum(cs.color), L2 = lum(bg || 'rgb(0, 0, 0)');
    return {
      text: el.textContent,
      visible: el.getClientRects().length > 0,
      fontPx: parseFloat(cs.fontSize),
      bgFound: !!bg,
      bgId: bgEl ? (bgEl.id || bgEl.className) : '',
      contrast: (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05),
    };
  });
}"""


def _eyebrows(mock_server, pw_browser, surface, theme):
    ctx, page, errors = _open(pw_browser, mock_server, "sr",
                              _SURFACES[surface] + f"&theme={theme}")
    try:
        booted = page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'")
        rows = page.evaluate(_EYEBROW_JS)
    finally:
        page.close()
        ctx.close()
    return booted, rows, errors


@pytest.mark.parametrize("theme", _THEMES)
@pytest.mark.parametrize("surface", sorted(_SURFACES))
def test_build_row_eyebrows_reach_aa_and_keep_the_headline(
        surface, theme, mock_server, pw_browser):
    booted, rows, errors = _eyebrows(mock_server, pw_browser, surface, theme)
    assert booted == theme, f"booted on the wrong theme, not {theme}"
    assert [r["text"] for r in rows] == _LABELS, rows
    for r in rows:
        assert r["visible"], (surface, theme, r)
        assert r["fontPx"] >= 16, (surface, theme, r)
        assert r["bgFound"], (surface, theme, r)
        assert r["contrast"] >= 4.5, (surface, theme, r)
    head, meta, ult = (r["contrast"] for r in rows)
    assert head > meta and head > ult, (surface, theme, rows)
    assert not errors, f"JS errors [{surface}/{theme}]: {errors[:3]}"
