"""
tests/snapshot_panels/test_ui_mock_active_match_map_text_floor.py
The SR MAP pane's two text marks read at the --fs-xs floor (session 144,
lane uiux, S144-U-229).

web/js/panels/active_match.js drew the red MIA badge on the overlay canvas
in `bold 10px sans-serif` and styled the gank band (#am-map-gank, "WARN
Nidalee missing 25s - ward / back off") at `font-size:12px`, both under
--fs-xs (web/css/tokens.css, 16 px) with no documented exception. The gank
band is the one warning on the map, and the badge is the only place the
canvas says how long an enemy has been gone.

The band now takes var(--fs-xs); the badge reads the resolved --fs-xs off
the canvas and sizes its red box to that font, still clamped inside the
canvas edges. Canvas text has no computed style, so the badge is pinned two
ways: the font every fillText on the overlay canvas used (recorded by an
init-script wrapper), and the badge-red pixel box it painted.

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

# Every fillText on the overlay canvas, as [text, ctx.font].
_RECORD_TEXT = """(() => {
  const orig = CanvasRenderingContext2D.prototype.fillText;
  window.__amCanvasText = [];
  CanvasRenderingContext2D.prototype.fillText = function (t) {
    if (this.canvas && this.canvas.id === 'am-map-overlay') {
      window.__amCanvasText.push([String(t), this.font]);
    }
    return orig.apply(this, arguments);
  };
})();"""

_FS_XS_JS = """() => parseFloat(getComputedStyle(document.documentElement)
  .getPropertyValue('--fs-xs'))"""

# The badge is the only rgba(185, 28, 28, 0.85) fill on the layer (S144-U-230;
# it was rgba(220, 38, 38, 0.85)); its white tag text is drawn inside that
# box. Pink dots carry a green channel of 126, so they never match.
_BADGE_BOX_JS = """() => {
  const cv = document.getElementById('am-map-overlay');
  if (!cv || getComputedStyle(cv).display === 'none'
      || cv.width < 4 || cv.height < 4) return null;
  const w = cv.width, h = cv.height;
  const d = cv.getContext('2d').getImageData(0, 0, w, h).data;
  let x0 = w, y0 = h, x1 = -1, y1 = -1, red = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      if (d[i] >= 170 && d[i + 1] <= 60 && d[i + 2] <= 60
          && d[i + 3] >= 180) {
        red++;
        if (x < x0) x0 = x;
        if (x > x1) x1 = x;
        if (y < y0) y0 = y;
        if (y > y1) y1 = y;
      }
    }
  }
  let white = 0;
  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      const i = (y * w + x) * 4;
      if (d[i] >= 230 && d[i + 1] >= 230 && d[i + 2] >= 230
          && d[i + 3] >= 230) white++;
    }
  }
  return {w, h, red, white, x0, y0, x1, y1};
}"""


def _vs_corner(t_now):
    """The S144-U-228 SR state plus Kindred 25 s gone at the top-right
    corner of the 14800 map, where the badge must clamp inside the canvas."""
    vs = _vs_sr(t_now)
    del vs["enemies"]["Nidalee"]
    vs["enemies"]["Kindred"] = {
        "champion": "Kindred", "team": "CHAOS", "level": 8,
        "is_dead": False, "respawn_in_s": None, "visible": False,
        "missing_for_s": 25.0, "last_seen_pos": {"x": 14700, "z": 14700},
        "last_seen_t": 562.0, "last_seen_zone": "RIVER",
    }
    return vs


def _open(pw_browser, mock_server, feed):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.add_init_script(_RECORD_TEXT)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route("**/api/vision-state*", feed)
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
    page.wait_for_function(
        f"(({_BADGE_BOX_JS})() || {{}}).red > 0", timeout=10_000)
    return ctx, page, errors


def _font_px(font):
    m = re.search(r"(\d+(?:\.\d+)?)px", font)
    assert m, font
    return float(m.group(1))


def test_sr_mia_badge_text_reads_at_the_fs_xs_floor(mock_server, pw_browser):
    """The badge tag is drawn at the resolved --fs-xs (16 px), and its red
    box is tall enough to hold that font, with the white tag inside it."""
    ctx, page, errors = _open(pw_browser, mock_server, _Feed("live", _vs_sr))
    try:
        fs_xs = page.evaluate(_FS_XS_JS)
        assert fs_xs == 16, fs_xs
        drawn = page.evaluate("window.__amCanvasText")
        tags = [f for t, f in drawn if t.endswith(" 25s")]
        assert tags, drawn[:5]
        for font in tags:
            assert _font_px(font) >= fs_xs, (font, fs_xs)
            assert "bold" in font or "700" in font, font
        box = page.evaluate(_BADGE_BOX_JS)
        assert box["y1"] - box["y0"] + 1 >= fs_xs, box
        assert box["white"] > 20, box
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


def test_sr_mia_badge_at_the_map_corner_stays_inside_the_canvas(
    mock_server, pw_browser
):
    """An enemy last seen at the top-right corner: the larger badge is still
    clamped clear of every canvas edge, not cut off by it."""
    ctx, page, errors = _open(pw_browser, mock_server,
                              _Feed("live", _vs_corner))
    try:
        box = page.evaluate(_BADGE_BOX_JS)
        assert box["y1"] - box["y0"] + 1 >= page.evaluate(_FS_XS_JS), box
        assert box["x0"] >= 1 and box["y0"] >= 1, box
        assert box["x1"] <= box["w"] - 2, box
        assert box["y1"] <= box["h"] - 2, box
        assert box["white"] > 20, box
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


def test_sr_gank_band_reads_at_the_fs_xs_floor(mock_server, pw_browser):
    """The gank band's computed font size is --fs-xs, and the larger text
    still fits the figure: no horizontal overflow, and the band covers no
    more than a quarter of the map it sits on."""
    ctx, page, errors = _open(pw_browser, mock_server, _Feed("live", _vs_sr))
    try:
        page.wait_for_function(
            f"({_GANK_JS})() === {json.dumps(_SR_GANK)}", timeout=10_000)
        band = page.evaluate("""() => {
          const g = document.getElementById('am-map-gank');
          const fig = g.parentElement;
          const cs = getComputedStyle(g);
          return {fs: parseFloat(cs.fontSize), weight: cs.fontWeight,
                  h: g.getBoundingClientRect().height,
                  figH: fig.getBoundingClientRect().height,
                  sw: g.scrollWidth, cw: g.clientWidth};
        }""")
        fs_xs = page.evaluate(_FS_XS_JS)
        assert band["fs"] == fs_xs, (band, fs_xs)
        assert band["weight"] == "700", band
        assert band["sw"] <= band["cw"], band
        assert band["h"] <= band["figH"] / 4, band
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
