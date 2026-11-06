"""
tests/snapshot_panels/test_am_map_overlay_canvas_fits.py
The Active Match MAP pane's overlay canvas (#am-map-overlay) covers the map
image box and nothing else, at every window width, whether or not
/api/vision-state answers (s144 lane uiux, RM-1769).

The canvas is created in web/js/panels/active_match.js _renderAmMap with no
width or height, so until something sizes it, it is a default 300 x 150 px
box pinned to the figure's top-left corner. The only thing that sized it was
_amDrawOverlay, which runs on a /api/vision-state answer, so (measured on the
sr / aram ui_mock fixtures, headless):
  - with no base image (no local DDragon map and no live minimap crop, the
    am-map-noimg branch) the 300 px box stayed for good: 35 / 121 px past a
    265 / 179 px figure at 640x900 / 480x800, 21 / 106 px past the MAP pane,
    and the pane body (overflow-y: auto, so overflow-x is auto too) gained a
    horizontal scroller;
  - with an image but no vision answer (the endpoint failing), the box sat
    off the image (top-left of the figure, not over the map), so a dot drawn
    on it would not land where its world coordinate says;
  - a window resize, or the figure re-laying out as the other panes fill
    (measured: the image moved 53 px down at 1920x920 after the last vision
    draw), only re-fitted it on the next 500 ms vision poll.

Contract pinned here:
  - with an image, at every size and after a resize, the canvas covers the
    image box to within 1 px, vision answer or not, with no wait for a poll;
  - with no image, the canvas is not displayed and the MAP pane body has no
    horizontal overflow, and the vision text still ticks;
  - a world-centre enemy (x = z = 7400 on the 14800 CLASSIC map) is drawn
    at the image's centre (the projection lands on the map).

Drive path: /?ui_mock=1&mode=<sr|aram>#active-match with /api/vision-state
and the map image routed (a generated 512 x 512 PNG, the DDragon map size;
synthetic champion names, no Riot ids).
"""
import json
import struct
import zlib

import pytest

from tests.snapshot_panels.conftest import _WS_STUB


def _png(w: int, h: int) -> bytes:
    raw = b"".join(b"\x00" + b"\x40\x80\x40" * w for _ in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


_MAP_PNG = _png(512, 512)


def _vs(game_mode: str) -> dict:
    return {
        "t_now": 0, "game_time": 600.0, "game_mode": game_mode,
        "active_team": "ORDER",
        "enemies": {
            "Ahri": {"champion": "Ahri", "team": "CHAOS", "level": 9,
                     "is_dead": False, "respawn_in_s": None, "visible": True,
                     "missing_for_s": None,
                     "last_seen_pos": ({"x": 7400, "z": 7400}
                                       if game_mode == "CLASSIC" else None),
                     "last_seen_t": 600.0, "last_seen_zone": "MID"},
        },
        "summary": {"visible_count": 1, "missing_count": 0, "dead_count": 0,
                    "total": 1},
    }


_MEASURE = """() => {
  const box = (e) => { if (!e) return null; const r = e.getBoundingClientRect();
    return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width,
            h: r.height}; };
  const cv = document.getElementById('am-map-overlay');
  const img = document.getElementById('am-map-img');
  const fig = document.querySelector('#view-active-match .am-map-figure');
  const body = document.getElementById('am-map-body');
  let centre = null;
  if (cv && cv.width > 4 && cv.height > 4) {
    centre = cv.getContext('2d').getImageData(
      Math.floor(cv.width / 2), Math.floor(cv.height / 2), 1, 1).data[3];
  }
  return {cv: box(cv), img: box(img), fig: box(fig),
          cvShown: !!cv && getComputedStyle(cv).display !== 'none'
                   && cv.getBoundingClientRect().width > 0,
          cvW: cv && cv.width, cvH: cv && cv.height,
          imgLoaded: !!img && img.complete && img.naturalWidth > 0
                     && getComputedStyle(img).display !== 'none',
          noimg: !!fig && fig.classList.contains('am-map-noimg'),
          bodyScrollX: body ? body.scrollWidth - body.clientWidth : null,
          status: (document.getElementById('am-map-status') || {})
                    .textContent || '',
          centre};
}"""

_SIZES = [(1920, 920), (1024, 768), (768, 1024), (640, 900), (480, 800)]


def _open(pw_browser, mock_server, w, h, mode, *, image, vision):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": w, "height": h})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    vs = _vs("CLASSIC" if mode == "sr" else "ARAM")
    if vision:
        page.route("**/api/vision-state*", lambda r: r.fulfill(
            status=200, content_type="application/json", body=json.dumps(vs)))
    else:
        page.route("**/api/vision-state*", lambda r: r.fulfill(
            status=503, content_type="application/json", body="{}"))
    if image:
        page.route("**/img/map/*", lambda r: r.fulfill(
            status=200, content_type="image/png", body=_MAP_PNG))
    else:
        page.route("**/img/map/*", lambda r: r.fulfill(status=404, body=""))
        page.route("**/api/minimap-crop*", lambda r: r.fulfill(
            status=404, body=""))
    page.goto(mock_server.url + f"/?ui_mock=1&mode={mode}#active-match",
              wait_until="domcontentloaded", timeout=15_000)
    if image:
        page.wait_for_function(
            "(() => { const i = document.getElementById('am-map-img');"
            " return !!i && i.complete && i.naturalWidth > 0; })()",
            timeout=10_000)
    else:
        page.wait_for_function(
            "(() => { const f = document.querySelector("
            "'#view-active-match .am-map-figure');"
            " return !!f && f.classList.contains('am-map-noimg'); })()",
            timeout=10_000)
    if vision:
        page.wait_for_function(
            "/visible|bridge/.test((document.getElementById('am-map-status')"
            " || {}).textContent || '')", timeout=10_000)
    # Two animation frames: layout + any ResizeObserver delivery settle.
    page.evaluate("() => new Promise((r) => requestAnimationFrame("
                  "() => requestAnimationFrame(() => r())))")
    return ctx, page, errors


_COVER_JS = """() => {
  const cv = document.getElementById('am-map-overlay');
  const img = document.getElementById('am-map-img');
  if (!cv || !img || getComputedStyle(cv).display === 'none') return false;
  const a = cv.getBoundingClientRect(), b = img.getBoundingClientRect();
  return ['left', 'right', 'top', 'bottom'].every(
    (k) => Math.abs(a[k] - b[k]) <= 1.0);
}"""


def _settle(page, ms: int) -> None:
    """Wait up to `ms` for the canvas to cover the image box. A DOM change
    landing between frames is read by a measurement before the same
    frame's ResizeObserver turn, so one fixed frame is a race; `ms` stays
    under the 500 ms vision poll, and with no vision answer the observer
    is the only thing that can re-fit at all. On timeout the caller's
    assertion reports the measured boxes."""
    try:
        page.wait_for_function(_COVER_JS, timeout=ms, polling="raf")
    except Exception:  # noqa: BLE001 - the assertion below reports it
        pass


def _covers(m) -> bool:
    cv, img = m["cv"], m["img"]
    return (m["cvShown"]
            and all(abs(cv[k] - img[k]) <= 1.0 for k in ("l", "r", "t", "b")))


@pytest.mark.parametrize("vision", [True, False], ids=["vision", "novision"])
@pytest.mark.parametrize("mode", ["sr", "aram"])
@pytest.mark.parametrize("w,h", _SIZES)
def test_canvas_covers_the_image_box(w, h, mode, vision, mock_server,
                                     pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, w, h, mode,
                              image=True, vision=vision)
    try:
        _settle(page, 300)
        m = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert m["imgLoaded"], m
    assert _covers(m), (w, mode, vision, m["cv"], m["img"])
    assert m["cv"]["r"] <= m["fig"]["r"] + 1.0, (w, m)
    assert m["bodyScrollX"] <= 0, (w, m["bodyScrollX"])


@pytest.mark.parametrize("vision", [True, False], ids=["vision", "novision"])
@pytest.mark.parametrize("start", [(1920, 920), (1024, 768)])
def test_canvas_follows_a_resize(start, vision, mock_server, pw_browser):
    """A resize re-fits the canvas at once, not on the next vision poll
    (and never, with no vision answer)."""
    ctx, page, errors = _open(pw_browser, mock_server, *start, "sr",
                              image=True, vision=vision)
    seen = []
    try:
        for w, h in [(640, 900), (480, 800), (start[0], start[1])]:
            page.set_viewport_size({"width": w, "height": h})
            _settle(page, 300)
            seen.append(((w, h), page.evaluate(_MEASURE)))
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    for size, m in seen:
        assert _covers(m), (start, vision, size, m["cv"], m["img"])


@pytest.mark.parametrize("vision", [True, False], ids=["vision", "novision"])
@pytest.mark.parametrize("mode", ["sr", "aram"])
@pytest.mark.parametrize("w,h", _SIZES)
def test_no_image_means_no_canvas_box(w, h, mode, vision, mock_server,
                                      pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, w, h, mode,
                              image=False, vision=vision)
    try:
        m = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert m["noimg"], m
    assert not m["cvShown"], (w, mode, vision, m["cv"])
    assert m["bodyScrollX"] <= 0, (w, mode, vision, m["bodyScrollX"])
    if vision:
        assert ("visible" in m["status"]) or ("bridge" in m["status"]), m


@pytest.mark.parametrize("w,h", [(1920, 920), (640, 900), (480, 800)])
def test_world_centre_dot_lands_on_the_image_centre(w, h, mock_server,
                                                    pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, w, h, "sr",
                              image=True, vision=True)
    try:
        _settle(page, 300)
        m = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert _covers(m), (w, m["cv"], m["img"])
    assert m["centre"] and m["centre"] > 0, (w, m["centre"])
