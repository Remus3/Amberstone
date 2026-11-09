"""
tests/snapshot_panels/test_minimap_crop_image_retired.py
S144-U-257 (s144 uiux): the never-rendered live minimap crop image of the
#minimap panel (#mm-img-wrap with its #mm-img and #mm-img-caption) and the
main.js poll that fed it (/api/minimap-crop every 500 ms on the fast
stream, 2 s otherwise, during an SR / ARAM / Brawl game) are retired.

THE DEFECT. The #minimap panel sits in the top-level <main>, which
header.css hides for every VIEW_ID and overlay.css hides in the overlay
shell (pinned by test_home_minimap_polls_need_rendered_panel.py). Since
S144-U-227 the poll returned before sending while the panel had no layout
box, so in every real view it ran a 2 s / 500 ms timer that did nothing,
and its only output was an image no view shows. S144-U-256 retired the
heartbeat line and the dot overlay of the same panel; this retires the
image, its caption, its STALE caption suffix, the grid.css / map_state.css
rules that sized it and the whole poll (timeout, one-open-request guard,
cadence switch, blob URL handling).

KEPT, and pinned here as positive controls so the retirement cannot pass
by breaking a live neighbour:
- the Active Match MAP pane's own use of /api/minimap-crop as a base-image
  fallback (web/js/panels/active_match.js), which is an <img> src and not
  this poll;
- the header zone pill (map_state.js renderMinimapCanvases ->
  _updateZone; S144-U-258 later retired the canvas stack, so the panel
  shell and its objective rows are the served positive control);
- the overlay's /api/state minimap poller (main.js setupMinimapPoller),
  which feeds the overlay minimap rect and ZOI, not this image.
The backend route /api/minimap-crop is not touched.
"""
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

REPO = Path(__file__).resolve().parents[2]

_NAMES = (
    "mm-img", "minimap-img", "refreshMinimap", "_minimapPanelShown",
    "minimapInflight", "_dropMinimapInflight", "MINIMAP_INTERVAL",
    "MINIMAP_FETCH_TIMEOUT", "MINIMAP_MODES", "lastMinimapMode",
    "minimapTimer", "minimapInterval", "MM.img", "imgWrap", "imgCaption",
)


def _live_web_text():
    out = []
    for sub, pat in (("web/css", "*.css"), ("web/js", "*.js")):
        for p in sorted((REPO / sub).rglob(pat)):
            out.append((p.relative_to(REPO).as_posix(),
                        p.read_text(encoding="utf-8")))
    out.append(("web/index.html",
                (REPO / "web/index.html").read_text(encoding="utf-8")))
    return out


def test_no_stylesheet_script_or_page_still_names_the_retired_parts():
    hits = [(rel, n) for rel, text in _live_web_text()
            for n in _NAMES if n in text]
    assert hits == [], hits


def test_main_js_sends_no_minimap_crop_request():
    # The only /api/minimap-crop user left is the Active Match MAP pane's
    # <img> base-image fallback; main.js names the route nowhere.
    main = (REPO / "web/js/main.js").read_text(encoding="utf-8")
    assert "/api/minimap-crop" not in main


def test_anchor_the_scans_read_real_files():
    # An empty scan would pass both tests above; prove they read the live
    # files by finding the live neighbours of the retired parts.
    files = dict(_live_web_text())
    assert len(files) > 20, len(files)
    assert 'id="mm-objectives-view"' in files["web/index.html"]
    assert 'id="zone-pill"' in files["web/index.html"]
    assert "function renderMinimapCanvases(" in files[
        "web/js/panels/map_state.js"]
    assert "function _updateZone(" in files["web/js/panels/map_state.js"]
    assert "(function setupMinimapPoller()" in files["web/js/main.js"]
    assert '"/api/minimap-crop?mode=' in files[
        "web/js/panels/active_match.js"]
    assert ".mm-zoi-canvas {" in files["web/css/panels/grid.css"]


_DOM = r"""() => {
  const p = document.getElementById('minimap');
  return {
    panel: !!p,
    objectives: !!document.getElementById('mm-objectives-view'),
    retired: document.querySelectorAll(
      '#mm-img-wrap, #mm-img, #mm-img-caption, .minimap-img-wrap, '
      + '.minimap-img-caption, #minimap img').length,
  };
}"""


@pytest.mark.parametrize("mode", ["sr", "aram"])
def test_the_served_page_has_no_crop_image(mock_server, pw_browser, mode):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + f"/?ui_mock=1&mode={mode}#active-match",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "() => document.body.dataset.view === 'active-match'",
            timeout=10_000)
        got = page.evaluate(_DOM)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    # Positive control: the panel and its kept objective rows are served.
    assert got["panel"] and got["objectives"], got
    assert got["retired"] == 0, got
