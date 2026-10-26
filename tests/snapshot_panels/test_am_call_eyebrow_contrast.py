"""
tests/snapshot_panels/test_am_call_eyebrow_contrast.py
The CALL pane eyebrow labels reach WCAG AA on their resolved surface in every
theme (session 134, lane uiux, RM-945).

active_match.js _line() paints every CALL pane eyebrow - the TFT no-feed
"TFT LIVE DATA" status head and the League RIGHT NOW / ACTION / OBJECTIVE /
NEXT labels - with an inline color. At var(--text-faint) on the .am-pane-call
surface the headless render measured (16px / 700, so the 4.5:1 normal-text
floor applies):
  arcane   oklch(0.63 0.055 305)             on rgb(44, 30, 63)  4.31:1
  hextech  rgb(116, 135, 159)                on rgb(22, 32, 46)  4.46:1
  ember    oklch(0.63 0.045 40)              on rgb(48, 31, 29)  4.39:1
  moonlit  oklch(0.63 0.04 240)              on rgb(21, 37, 54)  4.48:1
(terminal 5.03, bloodmoon 4.52 passed). base.css documents --text-faint as AA
"on --surface"; the call pane is not --surface (lane doc trap 4: state the
pair, never the token). var(--text-dim), the base.css "secondary text /
labels" token, measured 6.37 to 8.18:1 on the same pane.

Each label is measured by COMPUTED color against the first opaque ancestor
background, both resolved by the browser (oklch included, trap 3), and must
stay dimmer than its own value text so the prompt still leads (HIERARCHY).

Drive path: ?ui_mock=1&mode=<tft_round|sr>&theme=<t>#active-match, the
out-of-game fixtures under web/data/ui_mock/.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_THEMES = ("arcane", "hextech", "terminal", "ember", "bloodmoon", "moonlit")

# The labels each mock must render; an empty measurement must not pass.
_EXPECT_LINES = {
    "tft_round": ["tft-live-data"],
    "sr": ["right-now", "action", "objective", "next"],
}

# Resolve any CSS color (oklch included) to sRGB bytes through a canvas, then
# return [line, labelRGB, valueRGB, surfaceRGB] per CALL pane line.
_MEASURE_JS = """
async () => {
  await document.fonts.ready;
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgb = (c) => {
    cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c;
    cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3]];
  };
  const alpha = (c) => {
    const m = /rgba?\\(([^)]*)\\)/.exec(c);
    if (!m) return 1;
    const parts = m[1].split(/[ ,/]+/).filter(Boolean);
    return parts.length > 3 ? parseFloat(parts[3]) : 1;
  };
  const surface = (el) => {
    for (let n = el; n; n = n.parentElement) {
      const b = getComputedStyle(n).backgroundColor;
      if (b && b !== 'transparent' && alpha(b) >= 1) return rgb(b);
    }
    return null;
  };
  return Array.from(document.querySelectorAll(
    '#am-call-body > div[data-call-line]')).map((row) => {
    const lbl = row.querySelector(':scope > span:first-child');
    const val = row.querySelector(':scope > span:last-child');
    return [row.dataset.callLine,
            rgb(getComputedStyle(lbl).color),
            rgb(getComputedStyle(val).color),
            surface(lbl)];
  });
}
"""


def _lum(c) -> float:
    def ch(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def _ratio(a, b) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _measure(pw_browser, mock_server, mode: str, theme: str):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url
            + f"/?ui_mock=1&mode={mode}&theme={theme}#active-match",
            wait_until="domcontentloaded",
            timeout=15_000,
        )
        want = len(_EXPECT_LINES[mode])
        page.wait_for_function(
            "(n) => document.querySelectorAll("
            "'#am-call-body > div[data-call-line]').length >= n",
            arg=want,
            timeout=10_000,
        )
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme
        rows = page.evaluate(_MEASURE_JS)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{mode}/{theme}]: {errors[:3]}"
    return rows


@pytest.mark.parametrize("theme", _THEMES)
@pytest.mark.parametrize("mode", sorted(_EXPECT_LINES))
def test_call_eyebrow_reaches_aa_on_its_surface(mode, theme, mock_server, pw_browser):
    rows = _measure(pw_browser, mock_server, mode, theme)
    assert [r[0] for r in rows] == _EXPECT_LINES[mode], rows
    for line, label, value, surface in rows:
        assert surface is not None, f"{mode}/{theme}/{line}: no opaque surface"
        ratio = _ratio(label, surface)
        assert ratio >= 4.5, (
            f"{mode}/{theme}/{line}: eyebrow rgb{tuple(label[:3])} on "
            f"rgb{tuple(surface[:3])} = {ratio:.2f}:1, below AA 4.5:1"
        )
        # HIERARCHY: the prompt leads, the eyebrow stays the dimmer of the two.
        assert _ratio(value, surface) > ratio, (
            f"{mode}/{theme}/{line}: eyebrow is as bright as its value"
        )
