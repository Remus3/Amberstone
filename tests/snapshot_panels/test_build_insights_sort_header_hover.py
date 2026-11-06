"""
tests/snapshot_panels/test_build_insights_sort_header_hover.py
RM-1763 (s144 uiux): hovering a Build Insights sort header is a visible
step in EVERY theme, not only in the gold ones.

Measured in headless Chromium before the fix (`?ui_mock=1&theme=<t>
#build-insights`, 1920x920; colours resolved to sRGB through a canvas, so an
oklch() token is read as the browser paints it): `.bi-sort-btn:hover` set
`color: var(--accent)` over the header's resting `--dim`. In the operator
default theme "arcane" --accent is the lavender-silver frame metal, oklch
0.72 against --dim 0.74 at the same hue: the hover went from rgb(177,164,194)
to rgb(171,158,188), a 1.07:1 luminance ratio and DARKER than rest, so the
header gave no hover cue. In "terminal" the ratio was 1.00:1 (hue only).
The fix follows the sibling `.bi-tab:hover` in the same file: hover is
`color: var(--text)`, the brightest ink, which is 1.95:1 or more over --dim
in all six themes.

Positive control: the non-sortable "Expected WP" header has no button and
does not change on hover.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page

THEMES = ("hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane")

# The smallest rest -> hover luminance ratio that counts as a visible step.
# --text over --dim measures 1.95 (arcane) to 2.29 (hextech); the old
# --accent hover measured 1.00 to 1.30.
MIN_STEP = 1.5

_SEL = "#bi-table-mount th.bi-sortable[data-sort='n'] button"
_EXP = "#bi-table-mount th.bi-c-exp"

# Resolve the element's painted colour and the theme's --text / --dim to
# sRGB bytes through a 1x1 canvas (computed colours may be oklch()).
_COLORS = """
(sel) => {
  const el = document.querySelector(sel);
  const cv = document.createElement('canvas');
  cv.width = cv.height = 1;
  const g = cv.getContext('2d');
  const rgb = (c) => {
    g.clearRect(0, 0, 1, 1);
    g.fillStyle = '#000';
    g.fillStyle = c;
    g.fillRect(0, 0, 1, 1);
    return Array.from(g.getImageData(0, 0, 1, 1).data).slice(0, 3);
  };
  const root = getComputedStyle(document.documentElement);
  return {
    color: rgb(getComputedStyle(el).color),
    text: rgb(root.getPropertyValue('--text').trim()),
    dim: rgb(root.getPropertyValue('--dim').trim()),
    theme: document.documentElement.getAttribute('data-theme'),
  };
}
"""


def _lum(c):
    def ch(v):
        v = v / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (ch(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _open(pw_browser, mock_server, theme, vp=VIEWPORTS[0]):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    page.goto(mock_server.url + "/?ui_mock=1&theme=" + theme + "#build-insights",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        f"document.querySelector({_SEL!r}) !== null", timeout=10_000)
    page.mouse.move(2, 2)
    return ctx, page, errors


@pytest.mark.parametrize("theme", THEMES)
def test_sort_header_hover_is_a_visible_step(mock_server, pw_browser, theme):
    ctx, page, errors = _open(pw_browser, mock_server, theme)
    try:
        rest = page.evaluate(_COLORS, _SEL)
        # The theme really applied (hextech is the attribute-less default).
        assert rest["theme"] == (None if theme == "hextech" else theme), rest
        assert rest["color"] == rest["dim"], rest
        page.hover(_SEL)
        hov = page.evaluate(_COLORS, _SEL)
        step = _ratio(rest["color"], hov["color"])
        assert _lum(hov["color"]) > _lum(rest["color"]), (
            f"{theme}: the hover is not brighter than rest: "
            f"{rest['color']} -> {hov['color']}")
        assert step >= MIN_STEP, (
            f"{theme}: hover step {step:.2f}:1 < {MIN_STEP}: "
            f"{rest['color']} -> {hov['color']}")
        assert hov["color"] == hov["text"], hov
        assert not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_hover_step_at_both_viewports_in_the_default_theme(mock_server, pw_browser, vp):
    ctx, page, errors = _open(pw_browser, mock_server, "arcane", vp)
    try:
        rest = page.evaluate(_COLORS, _SEL)
        page.hover(_SEL)
        hov = page.evaluate(_COLORS, _SEL)
        assert _ratio(rest["color"], hov["color"]) >= MIN_STEP, (rest, hov)
        # Moving off restores the resting colour.
        page.mouse.move(2, 2)
        assert page.evaluate(_COLORS, _SEL)["color"] == rest["color"]
        assert not errors, errors
    finally:
        ctx.close()


def test_control_unsortable_header_does_not_react_to_hover(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, "arcane")
    try:
        assert page.locator(_EXP + " button").count() == 0
        rest = page.evaluate(_COLORS, _EXP)
        page.hover(_EXP)
        hov = page.evaluate(_COLORS, _EXP)
        assert hov["color"] == rest["color"] == rest["dim"], (rest, hov)
        assert not errors, errors
    finally:
        ctx.close()
