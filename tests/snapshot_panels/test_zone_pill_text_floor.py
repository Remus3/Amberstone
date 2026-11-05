"""
tests/snapshot_panels/test_zone_pill_text_floor.py
RM-1548 (s144 uiux) - the Active Match header zone pill reads at the
--fs-xs floor, on one line, whole inside its pill.

THE DEFECT. web/css/panels/header.css set the header pills to 21px
(the font-uniformity rule), but a later `.zone-pill` block set 12px with
0.14em letter-spacing, so the zone call ("DEEP ENEMY", "ENEMY ZONE",
"SAFE", "DMZ") was the smallest text in the header, 4px under the 16px
--fs-xs floor, at every width. MEASURED in headless Chromium under
/?ui_mock=1&mode=sr#active-match: computed font-size 12px at 1920x920,
1199x920, 721x346, 720x346, 480x230 and 320x256.

Raising the size alone was not enough: at 16px with the 0.14em spacing
the "DEEP ENEMY" label needs 135px and the desktop pill gives it 120px,
so the label wrapped inside the 43px pill.

THE FIX. The zone pill text is var(--fs-xs) with 0.04em spacing (the
.mode-pill / .title spacing), it never wraps, and above 720px the pill is
min-width 142px with width auto (the 142px slot is unchanged for every
usual label, and a wider face grows this pill instead of wrapping it).
At 720px and under its min-width is 132px, which holds "DEEP ENEMY" at
the new size, so the four labels give one slot map there too.

The snapshot font is the Lato stub (every glyph one 0.49em advance); the
real Lato Black capitals are wider, so the last check widens the label
by letter-spacing and asserts it still stays on one line inside its pill.
"""
import pytest

from tests.snapshot_panels.test_header_pills_short_window import _SETS, _open

_VPS = [(1920, 920), (1199, 920), (721, 346), (720, 346), (480, 230), (320, 256)]
# The four labels web/js/panels/map_state.js writes, with the class it sets.
_LABELS = {
    "deep": ("\u26d4 DEEP ENEMY", "zone-pill zone-enemy zone-deep"),
    "enemy": ("\u26a0 ENEMY ZONE", "zone-pill zone-enemy"),
    "safe": ("\u2713 SAFE", "zone-pill zone-safe"),
    "dmz": ("- DMZ", "zone-pill zone-dmz"),
}
# Measured slot widths after the fix (stub font): 142px above 720px, as at
# HEAD, and 132px at 720px and under (HEAD min-width 118px).
_SLOT_W = {True: 142, False: 132}

_ZONE = """
(v) => {
  const p = document.getElementById('zone-pill');
  const b = document.getElementById('zone-label');
  p.className = v.cls;
  b.textContent = v.text;
  if (v.extra) b.style.letterSpacing = v.extra;
  const cs = getComputedStyle(p);
  const floor = parseFloat(getComputedStyle(document.documentElement)
    .getPropertyValue('--fs-xs'));
  const pr = p.getBoundingClientRect();
  const br = b.getBoundingClientRect();
  const r = document.createRange();
  r.selectNodeContents(b);
  const tops = new Set([...r.getClientRects()].map(x => Math.round(x.top)));
  const tr = r.getBoundingClientRect();
  return {fs: parseFloat(cs.fontSize), floor, w: pr.width, h: pr.height,
          lines: tops.size, labelOver: b.scrollWidth - b.clientWidth,
          pillOver: p.scrollWidth - p.clientWidth,
          inL: tr.left >= pr.left - 0.5, inR: tr.right <= pr.right + 0.5,
          inT: tr.top >= pr.top - 0.5, inB: tr.bottom <= pr.bottom + 0.5,
          textW: tr.width, labelW: br.width};
}
"""


def _measure(page, key, extra=""):
    text, cls = _LABELS[key]
    return page.evaluate(_ZONE, {"text": text, "cls": cls, "extra": extra})


@pytest.mark.parametrize("vp", _VPS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_zone_pill_text_is_at_the_floor_on_one_line_inside_the_pill(
        vp, pw_browser, mock_server):
    ctx, page, errors = _open(pw_browser, mock_server, vp, "sr", _SETS["live"])
    try:
        rows = {k: _measure(page, k) for k in _LABELS}
    finally:
        ctx.close()
    label = f"{vp[0]}x{vp[1]}"
    want_w = _SLOT_W[vp[0] > 720]
    for key, m in rows.items():
        assert m["floor"] >= 16, f"{label}: --fs-xs reads {m['floor']}px"
        assert m["fs"] >= m["floor"], (
            f"{label} {key}: zone pill text {m['fs']}px, under the"
            f" {m['floor']}px --fs-xs floor")
        assert m["lines"] == 1, f"{label} {key}: the label wraps to {m['lines']} lines"
        assert m["labelOver"] <= 0 and m["pillOver"] <= 0, (
            f"{label} {key}: the label overflows (label {m['labelOver']},"
            f" pill {m['pillOver']})")
        assert m["inL"] and m["inR"] and m["inT"] and m["inB"], (
            f"{label} {key}: the label text runs outside its pill {m}")
        assert abs(m["w"] - want_w) <= 0.5, (
            f"{label} {key}: the zone pill is {m['w']}px wide, want {want_w}"
            " (one slot for every label)")
    assert not errors, errors


@pytest.mark.parametrize("vp", [(1920, 920), (720, 346), (320, 256)],
                         ids=lambda v: f"{v[0]}x{v[1]}")
def test_a_wider_face_grows_the_pill_instead_of_wrapping(vp, pw_browser, mock_server):
    # 0.2em extra spacing stands in for Lato Black capitals, which are
    # wider than the stub's single advance.
    ctx, page, errors = _open(pw_browser, mock_server, vp, "sr", _SETS["live"])
    try:
        m = _measure(page, "deep", extra="0.2em")
        de = page.evaluate(
            "() => document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth")
    finally:
        ctx.close()
    label = f"{vp[0]}x{vp[1]} wide face"
    assert m["lines"] == 1, f"{label}: the label wraps to {m['lines']} lines"
    assert m["inL"] and m["inR"] and m["inT"] and m["inB"], (
        f"{label}: the label text runs outside its pill {m}")
    assert m["w"] > _SLOT_W[vp[0] > 720], f"{label}: the pill did not grow ({m['w']}px)"
    assert de <= 0, f"{label}: the page scrolls sideways {de}px"
    assert not errors, errors
