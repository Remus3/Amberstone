"""
tests/snapshot_panels/test_ui_mock_active_match_map_alert_contrast.py
The SR MAP pane's two red alert marks hold AA for their white text over any
map backdrop (session 144, lane uiux, S144-U-230).

web/js/panels/active_match.js painted the gank band (#am-map-gank, "WARN
Nidalee missing 25s - ward / back off") and the canvas MIA badge ("Nidale
25s") in translucent rgba(220, 38, 38, 0.85) under white bold 16 px text.
The 15 percent of backdrop that shows through decides the contrast: over a
dark map it is 6.28:1, but over a near-white patch (a lit lane, a snowy
ARAM-style tile, the no-image box of a light theme) the composite lightens
to 4.05:1, under the 4.5:1 AA floor for 16 px text. Both marks now share one
deeper red, rgba(185, 28, 28, 0.85): 5.13:1 over white, 8.14:1 over black,
so no backdrop takes the warning under AA.

The worst backdrop for white text is white (contrast falls as the composite
lightens), so each mark is pinned by compositing its own computed / painted
colour over pure white and over pure black. The band is read from its
computed background-color; the badge from the canvas pixel it painted
(getImageData returns un-premultiplied RGBA, so the fill colour and alpha
come back as drawn).

Drive path: /?ui_mock=1&mode=sr#active-match with an empty /api/state and a
live /api/vision-state stand-in (the S144-U-228 harness).
"""
import json
import re

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ui_mock_active_match_map_stall import (
    _GANK_JS,
    _MAP_PNG,
    _SR_FRESH,
    _SR_GANK,
    _STATUS_JS,
    _Feed,
    _vs_sr,
)

_AA = 4.5

# The most common opaque-ish reddish pixel on the overlay canvas: the badge
# box. Dots are pink (green channel 126), so a green channel under 100 and
# red over 120 with alpha over 150 isolates the badge fill.
_BADGE_RGBA_JS = """() => {
  const cv = document.getElementById('am-map-overlay');
  if (!cv || getComputedStyle(cv).display === 'none'
      || cv.width < 4 || cv.height < 4) return null;
  const d = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data;
  const seen = new Map();
  for (let i = 0; i < d.length; i += 4) {
    if (d[i] > 120 && d[i + 1] < 100 && d[i + 2] < 100 && d[i + 3] > 150) {
      const k = d[i] + ',' + d[i + 1] + ',' + d[i + 2] + ',' + d[i + 3];
      seen.set(k, (seen.get(k) || 0) + 1);
    }
  }
  let best = null, n = 0;
  for (const [k, c] of seen) if (c > n) { best = k; n = c; }
  return best ? {rgba: best.split(',').map(Number), n} : null;
}"""

_BAND_JS = """() => {
  const g = document.getElementById('am-map-gank');
  const cs = getComputedStyle(g);
  return {bg: cs.backgroundColor, fg: cs.color};
}"""


def _parse_css_rgba(s):
    m = re.match(r"rgba?\(([^)]+)\)", s)
    assert m, s
    parts = [float(p) for p in m.group(1).replace("/", ",").split(",")]
    if len(parts) == 3:
        parts.append(1.0)
    return parts


def _lum(rgb):
    def ch(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _over(fg_rgb, alpha, bg_rgb):
    return tuple(alpha * f + (1 - alpha) * b for f, b in zip(fg_rgb, bg_rgb))


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


_WHITE = (255, 255, 255)
_BLACK = (0, 0, 0)


def test_contrast_helper_positive_control():
    """The helper reproduces the measured defect: white over the old
    rgba(220, 38, 38, 0.85) on a white backdrop is under AA (4.05:1)."""
    old = _over((220, 38, 38), 0.85, _WHITE)
    assert 4.0 < _contrast(_WHITE, old) < _AA
    assert round(_contrast(_WHITE, (0, 0, 0)), 1) == 21.0


def _open(pw_browser, mock_server):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route("**/api/vision-state*", _Feed("live", _vs_sr))
    page.route("**/img/map/*", lambda r: r.fulfill(
        status=200, content_type="image/png", body=_MAP_PNG))
    page.goto(
        mock_server.url + "/?ui_mock=1&mode=sr#active-match",
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    page.wait_for_function(
        f"({_STATUS_JS})() === {json.dumps(_SR_FRESH)}", timeout=10_000,
    )
    return ctx, page, errors


def test_sr_gank_band_white_text_holds_aa_over_any_backdrop(
    mock_server, pw_browser
):
    """The band's computed background, composited over white and over
    black, keeps its white bold text at 4.5:1 or better."""
    ctx, page, errors = _open(pw_browser, mock_server)
    try:
        page.wait_for_function(
            f"({_GANK_JS})() === {json.dumps(_SR_GANK)}", timeout=10_000)
        band = page.evaluate(_BAND_JS)
        r, g, b, a = _parse_css_rgba(band["bg"])
        fg = _parse_css_rgba(band["fg"])
        assert fg[:3] == [255, 255, 255] and fg[3] == 1.0, band
        assert a >= 0.5, band
        for backdrop in (_WHITE, _BLACK):
            c = _contrast(_WHITE, _over((r, g, b), a, backdrop))
            assert c >= _AA, (band, backdrop, round(c, 2))
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


def test_sr_mia_badge_white_text_holds_aa_over_any_backdrop(
    mock_server, pw_browser
):
    """The badge's painted fill, composited over white and over black,
    keeps its white bold tag at 4.5:1 or better, and the band and the badge
    are the same red."""
    ctx, page, errors = _open(pw_browser, mock_server)
    try:
        page.wait_for_function(
            f"(({_BADGE_RGBA_JS})() || {{}}).n > 50", timeout=10_000)
        got = page.evaluate(_BADGE_RGBA_JS)
        r, g, b, a8 = got["rgba"]
        a = a8 / 255.0
        for backdrop in (_WHITE, _BLACK):
            c = _contrast(_WHITE, _over((r, g, b), a, backdrop))
            assert c >= _AA, (got, backdrop, round(c, 2))
        page.wait_for_function(
            f"({_GANK_JS})() === {json.dumps(_SR_GANK)}", timeout=10_000)
        br, bg_, bb, ba = _parse_css_rgba(page.evaluate(_BAND_JS)["bg"])
        assert max(abs(br - r), abs(bg_ - g), abs(bb - b)) <= 2, (
            got, (br, bg_, bb))
        assert abs(ba - a) <= 0.01, (got, ba)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
