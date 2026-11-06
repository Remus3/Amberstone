"""
tests/snapshot_panels/test_last_match_review_nav_hover.py
RM-1764 (s144 uiux): hovering the Last Match "Review" nav tab
(`#lm-go-to-review`, `.lm-tab.lm-tab-nav`) brightens its text in EVERY
theme and keeps the hovered text at WCAG AA on the hovered background.

Measured in headless Chromium before the fix (`?ui_mock=1&mode=sr&theme=<t>
#last-match`, 1920x920; text resolved to sRGB through a 1x1 canvas, the
background sampled from an element screenshot because the hover background
is the translucent --hextech-border composited over the panel):
`.lm-tab-nav:hover` set `color: var(--accent)`, the SAME colour as rest, so
the text step was 1.00:1 in all six themes and the only cue was the
--hextech-border tint. In the operator default theme "arcane" that tint is
lavender at alpha .30, and --accent (lavender-silver, rgb(171,158,188)) on
it measured 4.00:1 - below AA 4.5 for the 18px bold tab label (WCAG large
text starts at 18.66px bold). Terminal measured 4.73, the gold themes 5.5
to 6.1.

The fix follows the sibling `.lm-tab:hover` and the RM-1763 ruling (a
hover is a measured brighter step in every theme): hover is
`color: var(--text)`, keeping the --hextech-border tint, so the Review tab
still hovers differently from a panel tab.

Positive control: a plain panel tab ("Graph") already hovers to --text over
--surface-2 and is unchanged.
"""
import io

import pytest
from PIL import Image

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page

THEMES = ("hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane")

# The smallest rest -> hover text luminance ratio that counts as a visible
# step (the RM-1763 floor). --text over --accent measures 1.5 or more in
# every theme; the old hover measured 1.00.
MIN_STEP = 1.5
# WCAG AA for normal text: the label is --fs-sm (18px) bold, under the
# 18.66px bold large-text threshold.
AA = 4.5

_NAV = "#lm-go-to-review"
_TAB = "#lm-tabbed-section .lm-tab[data-tab='graph']"

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
    accent: rgb(root.getPropertyValue('--accent').trim()),
    theme: document.documentElement.getAttribute('data-theme'),
  };
}
"""


def _lum(c):
    def ch(v):
        v = v / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (ch(v) for v in c[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _bg(page, sel):
    """Painted background inside the button's top-left padding (no glyphs:
    the label is centred under 8px of vertical padding)."""
    png = page.locator(sel).screenshot(animations="disabled")
    return list(Image.open(io.BytesIO(png)).convert("RGB").getpixel((4, 4)))


def _open(pw_browser, mock_server, theme, vp=VIEWPORTS[0]):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    page.goto(mock_server.url + "/?ui_mock=1&mode=sr&theme=" + theme + "#last-match",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_selector(_NAV, state="visible", timeout=10_000)
    page.mouse.move(2, 2)
    return ctx, page, errors


# .lm-tab transitions background + colour over 0.12s on hover and on
# un-hover, so a colour read right after the mouse moves lands mid-
# transition. Wait out every transition on the element itself (the
# test_champ_select_lock_button_focus pattern), never a fixed sleep:
# test_theme_swap_reads_settled pins this.
# An infinite or paused animation never finishes, so it is not awaited
# (the pin's sweep after _SETTLE still sees it), and a bounded loop fails
# loudly instead of hanging until the pytest timeout.
_SETTLE = """async (sel) => {
  for (let i = 0; i < 20; i++) {
    const el = document.querySelector(sel);
    void getComputedStyle(el).color;
    const as = el.getAnimations().filter((a) => a.playState === 'running' &&
      a.effect.getComputedTiming().endTime !== Infinity);
    if (!as.length) return;
    await Promise.allSettled(as.map((a) => a.finished));
  }
  throw new Error('still animating after 20 waits: ' + sel);
}"""


def _hover(page, sel):
    page.hover(sel)
    page.evaluate(_SETTLE, sel)


def _unhover(page, sel):
    page.mouse.move(2, 2)
    page.evaluate(_SETTLE, sel)


@pytest.mark.parametrize("theme", THEMES)
def test_review_nav_hover_brightens_and_stays_aa(mock_server, pw_browser, theme):
    ctx, page, errors = _open(pw_browser, mock_server, theme)
    try:
        rest = page.evaluate(_COLORS, _NAV)
        assert rest["theme"] == (None if theme == "hextech" else theme), rest
        # At rest the Review tab is accent-tinted ("leaves this view").
        assert rest["color"] == rest["accent"], rest
        rest_bg = _bg(page, _NAV)
        _hover(page, _NAV)
        hov = page.evaluate(_COLORS, _NAV)
        hov_bg = _bg(page, _NAV)
        assert _lum(hov["color"]) > _lum(rest["color"]), (
            f"{theme}: hover text not brighter: {rest['color']} -> {hov['color']}")
        step = _ratio(rest["color"], hov["color"])
        assert step >= MIN_STEP, (
            f"{theme}: hover text step {step:.2f}:1 < {MIN_STEP}")
        contrast = _ratio(hov["color"], hov_bg)
        assert contrast >= AA, (
            f"{theme}: hovered text {hov['color']} on {hov_bg} is "
            f"{contrast:.2f}:1 < {AA}")
        assert hov["color"] == hov["text"], hov
        # The --hextech-border tint is kept: the hover background differs
        # from rest.
        assert hov_bg != rest_bg, (rest_bg, hov_bg)
        assert not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_review_nav_hover_at_both_viewports_in_the_default_theme(
        mock_server, pw_browser, vp):
    ctx, page, errors = _open(pw_browser, mock_server, "arcane", vp)
    try:
        rest = page.evaluate(_COLORS, _NAV)
        _hover(page, _NAV)
        hov = page.evaluate(_COLORS, _NAV)
        assert _ratio(rest["color"], hov["color"]) >= MIN_STEP, (rest, hov)
        assert _ratio(hov["color"], _bg(page, _NAV)) >= AA, hov
        # Moving off restores the resting colour.
        _unhover(page, _NAV)
        assert page.evaluate(_COLORS, _NAV)["color"] == rest["color"]
        assert not errors, errors
    finally:
        ctx.close()


def test_control_plain_tab_hover_is_unchanged(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, "arcane")
    try:
        rest = page.evaluate(_COLORS, _TAB)
        _hover(page, _TAB)
        hov = page.evaluate(_COLORS, _TAB)
        assert hov["color"] == hov["text"], hov
        assert _ratio(rest["color"], hov["color"]) >= MIN_STEP, (rest, hov)
        assert _ratio(hov["color"], _bg(page, _TAB)) >= AA, hov
        assert not errors, errors
    finally:
        ctx.close()
