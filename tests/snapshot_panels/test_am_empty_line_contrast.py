"""
tests/snapshot_panels/test_am_empty_line_contrast.py
S144-U-243 (s144 uiux): the Active Match empty-state lines - the spike
curve's "power curve unavailable" (.spk-empty) and the ward heat strip's
"no wards yet" (.wh-empty) - reach the WCAG 1.4.3 AA text floor (4.5:1) on
their resolved surface in all six themes, with ancestor opacity folded in,
at the 1920x920 baseline and the 923x1280 companion window.

THE DEFECTS. MEASURED headless under /?ui_mock=1&mode=<sr|arena|aram>
#active-match before the fix. Both lines are sub-floor font sizes by
documented operator exception (item 184 v2.1 audit; S144-U-151 ruling):
.spk-empty is 10 px, .wh-empty is 9 px. Nothing ruled on their contrast.
Each painted --text-faint and then faded it again:
- .spk-empty at opacity 0.6 read 2.44 (arcane) to 2.61 (terminal);
- .wh-empty at opacity 0.5 read 2.09 (arcane) to 2.19 (terminal).
Dropping the fade alone is not enough: --text-faint at full strength reads
4.31 arcane, 4.39 ember, 4.46 hextech and 4.48 moonlit on the BUILD / MAP
pane surface (the same 4.31 - 4.48 S144-U-215 measured for the BUILD
pane's empty strip).

THE FIX (web/css/panels/spike_curve.css, web/css/panels/ward_heat.css).
Both lines drop the opacity and take --text-dim, the S144-U-215 empty-state
tier. The font-size exceptions stay: the 40 px sparkline slot and the 22 px
strip are unchanged. The empty line stays quieter than --text. After: 6.37
(hextech) to 8.18 (terminal), both lines, every mode and viewport.

Checked per theme: every rendered empty line reaches 4.5:1 (sr and arena
render both; aram hides the ward heat strip, so only the spike line); each
line is --text-dim at opacity 1 down its whole ancestor chain; its font
size and box height are the documented exception values; and it reads
dimmer than full --text on the same surface.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_MODES = ["sr", "arena", "aram"]
_VIEWPORTS = [(1920, 920), (923, 1280)]
_IDS = [f"{w}x{h}" for w, h in _VIEWPORTS]
_AA = 4.5
_SHEET = "*, *::before, *::after { transition: none !important; }"
# The empty lines each mode renders under ?ui_mock=1 (aram hides ward heat).
_EXPECT = {
    "sr": {".spk-empty", ".wh-empty"},
    "arena": {".spk-empty", ".wh-empty"},
    "aram": {".spk-empty"},
}
# The documented font-size exceptions and the box each line fills, as
# measured before and after the fix: the ward strip is 22 px tall with a
# 1 px bottom border inside it, so its empty line shrinks to 21 px.
_SIZE = {".spk-empty": (10.0, 40.0), ".wh-empty": (9.0, 21.0)}

_MEASURE = """async () => {
  await document.fonts.ready;
""" + _HELPERS + """
  const alpha = (el) => {
    let a = 1;
    for (let n = el; n; n = n.parentElement) {
      a *= parseFloat(getComputedStyle(n).opacity);
    }
    return a;
  };
  const root = getComputedStyle(document.documentElement);
  const tok = (name) => rgba(root.getPropertyValue(name).trim());
  const out = {};
  for (const sel of ['.spk-empty', '.wh-empty']) {
    const el = document.querySelector('#view-active-match ' + sel);
    if (!el || !el.checkVisibility()) continue;
    const cs = getComputedStyle(el);
    const fg = rgba(cs.color);
    const a = alpha(el);
    const s = surface(el);
    const faded = fg.slice(); faded[3] *= a;
    const text = tok('--text');
    out[sel] = {
      text: el.textContent.trim(), alpha: a, own: parseFloat(cs.opacity),
      color: fg, fg: s ? over(faded, s) : null, bg: s,
      full: s ? over(text, s) : null,
      size: parseFloat(cs.fontSize),
      height: el.getBoundingClientRect().height,
    };
  }
  return {theme: document.documentElement.dataset.theme || 'hextech',
          dim: tok('--text-dim'), lines: out};
}"""


@pytest.fixture(scope="module")
def measured():
    return {}


def _measure(mock_server, pw_browser, theme, mode, vp):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vp[0], "height": vp[1]}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    want = " && ".join(
        f"document.querySelector('#view-active-match {sel}')"
        for sel in sorted(_EXPECT[mode]))
    try:
        page.goto(
            mock_server.url
            + f"/?ui_mock=1&mode={mode}&theme={theme}#active-match",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "() => document.body.dataset.view === 'active-match'",
            timeout=10_000)
        page.wait_for_function(f"() => !!({want})", timeout=10_000)
        page.add_style_tag(content=_SHEET)
        got = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert got["theme"] == theme, f"booted on {got['theme']}, not {theme}"
    return got


def _get(measured, mock_server, pw_browser, theme, mode, vp):
    key = (theme, mode, vp)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, mode, vp)
    return measured[key]


def _lum(c) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("theme", _THEMES)
def test_every_empty_line_reaches_aa(theme, mode, vp, measured,
                                     mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, mode, vp)
    lines = got["lines"]
    # The mode's empty lines are on the page, so an empty read cannot pass.
    assert set(lines) == _EXPECT[mode], (theme, mode, vp, sorted(lines))
    bad = []
    for sel, ln in sorted(lines.items()):
        assert ln["bg"] is not None, (theme, mode, sel, ln)
        ratio = _ratio(ln["fg"], ln["bg"])
        if ratio < _AA:
            bad.append(f"{sel} {ln['text']!r} {ratio:.2f}:1 "
                       f"(alpha {ln['alpha']:.2f}) under {_AA}")
    assert not bad, f"{theme} {mode} {vp}: " + "; ".join(bad)


@pytest.mark.parametrize("theme", _THEMES)
def test_empty_lines_are_dim_text_unfaded_at_their_exception_size(
        theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, "sr", _VIEWPORTS[0])
    lines = got["lines"]
    assert set(lines) == _EXPECT["sr"], sorted(lines)
    for sel, ln in sorted(lines.items()):
        assert ln["own"] == 1, (theme, sel, ln["own"])
        assert ln["alpha"] == 1, (theme, sel, ln["alpha"])
        assert ln["color"] == got["dim"], (theme, sel, ln["color"], got["dim"])
        size, height = _SIZE[sel]
        assert ln["size"] == size, (theme, sel, ln["size"])
        assert abs(ln["height"] - height) < 0.5, (theme, sel, ln["height"])
        # Quieter than full --text on the same surface: an empty line is
        # a notice, never the loudest thing in its pane.
        assert _lum(ln["fg"]) < _lum(ln["full"]), (theme, sel, ln)
