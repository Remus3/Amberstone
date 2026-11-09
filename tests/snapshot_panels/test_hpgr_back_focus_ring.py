"""
tests/snapshot_panels/test_hpgr_back_focus_ring.py
S144-U-208 (s144 uiux): the archive Post Game Review's Back button
(#hpgr-back, the only focusable control in #view-historical-pgr) draws the
house focus ring, and keyboard focus no longer reads as a mouse hover.

THE DEFECT. web/css/panels/home.css gave `.hpgr-back:hover` and
`.hpgr-back:focus-visible` ONE rule: the --info-soft fill, a 1px --info
border and `outline: none`. MEASURED in headless Chromium under
/?ui_mock=1 (History, first session, first match), every theme, 1920x920:
the keyboard-focused button computed `outline-style: none` and
`box-shadow: none`, and painted exactly what a mouse hover paints (text
10.66 arcane to 13.24 terminal, border 7.45 to 8.49 on the view surface),
so a keyboard user could not tell focus from a pointer resting on it, and
the only focus cue was a 1px border. Every other swept control carries the
RM-1210 ring (`outline: 2px solid var(--accent)`).

THE FIX. A separate `.hpgr-back:focus-visible` rule draws that ring with a
2px offset (the head holds no other control). Hover keeps the fill and
border and draws no ring.

WHAT IS MEASURED (computed values, never a grep), every theme, at the
1920x920 baseline and the 923x1280 companion window:
  - the view holds exactly one focusable control, #hpgr-back (an empty
    sweep would pass);
  - keyboard-focused, it matches :focus-visible and computes a solid
    outline >= 2px in the resolved --accent, >= 3:1 (WCAG 1.4.11) against
    the opaque surface it is painted on, not clipped by an overflow box,
    and its reach does not cover the head's title or meta line;
  - mouse-hovered and unfocused, it draws no outline (focus and hover are
    told apart), and its label stays >= 4.5:1 on the hover fill.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_build_insights_chart_text_contrast import (
    _AA, _ROW,
)
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio
from tests.snapshot_panels.test_historical_pgr_text_contrast import (
    _open_archive,
)
from tests.snapshot_panels.test_home_history_nav_focus_ring import _RING_JS

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_VIEWPORTS = [(1920, 920), (923, 1280)]
_IDS = [f"{w}x{h}" for w, h in _VIEWPORTS]

_FOCUSABLE = (
    "#view-historical-pgr button, #view-historical-pgr a[href], "
    "#view-historical-pgr input, #view-historical-pgr select, "
    "#view-historical-pgr textarea, "
    "#view-historical-pgr [tabindex]:not([tabindex='-1'])"
)

# The ring box (border box grown by offset + width) against the head's
# other parts: a ring painted over the title or the meta line hides text.
_OVERLAP = """() => {
  const e = document.getElementById('hpgr-back');
  const cs = getComputedStyle(e);
  const reach = parseFloat(cs.outlineOffset) + parseFloat(cs.outlineWidth);
  const r = e.getBoundingClientRect();
  const out = [];
  for (const sel of ['#view-historical-pgr .view-section-head h2',
                     '#hpgr-meta']) {
    const q = document.querySelector(sel).getBoundingClientRect();
    const hit = r.left - reach < q.right && r.right + reach > q.left
      && r.top - reach < q.bottom && r.bottom + reach > q.top;
    if (hit) out.push(sel);
  }
  return out;
}"""

_HOVER = """() => {
""" + _ROW + """
  const e = document.getElementById('hpgr-back');
  const cs = getComputedStyle(e);
  return {hov: e.matches(':hover'), focused: document.activeElement === e,
          style: cs.outlineStyle, shadow: cs.boxShadow,
          text: row(e), info: tok('--info'),
          border: rgba(cs.borderTopColor)};
}"""


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("theme", _THEMES)
def test_back_draws_the_accent_ring_and_hover_does_not(
        theme, vp, mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vp[0], "height": vp[1]})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        _open_archive(page, mock_server.url, theme)
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        page.add_style_tag(
            content="*, *::before, *::after { transition: none !important; }")
        page.wait_for_timeout(200)
        # Hover first, with nothing focused: the pointer path.
        page.evaluate("document.activeElement && document.activeElement.blur()")
        page.hover("#hpgr-back")
        hover = page.evaluate(_HOVER)
        # Then keyboard modality, pointer parked off the button.
        page.mouse.move(2, vp[1] - 2)
        page.keyboard.press("Shift")
        rings = page.evaluate(_RING_JS, _FOCUSABLE)
        overlap = page.evaluate(_OVERLAP)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]

    assert [r["key"] for r in rings] == ["hpgr-back"], rings
    ring = rings[0]
    assert ring["focused"] and ring["fv"], ring
    assert ring["style"] == "solid" and ring["width"] >= 2, ring
    assert ring["ring"] == ring["accent"], f"ring is not --accent: {ring}"
    assert ring["contrast"] >= 3.0, (
        f"{theme} {vp}: ring {ring['contrast']}:1 on {ring['surfaceOf']}")
    assert not ring["clippedBy"], ring
    assert not overlap, f"{theme} {vp}: ring covers {overlap}"

    assert hover["hov"] and not hover["focused"], hover
    assert hover["style"] == "none" and hover["shadow"] == "none", (
        f"{theme} {vp}: hover draws a ring, so focus and hover look alike:"
        f" {hover['style']} / {hover['shadow']}")
    # Hover still reads as hover: the --info frame.
    assert hover["border"][:3] == hover["info"][:3], hover
    t = hover["text"]
    assert _ratio(t["fg"], t["bg"]) >= _AA, (
        f"{theme} {vp}: hover label {_ratio(t['fg'], t['bg']):.2f}:1")
