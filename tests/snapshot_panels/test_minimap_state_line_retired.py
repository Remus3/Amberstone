"""
tests/snapshot_panels/test_minimap_state_line_retired.py
S144-U-256 (s144 uiux): the never-rendered MAP STATE heartbeat line
(#mm-state with its .mm-heart / .mm-counts / .mm-age spans) and the
vision-tracker dot overlay (#mm-vt-overlay, main.js refreshVisionOverlay)
are retired from the #minimap panel. The header zone pill, the one live
output of the same render, keeps working.

THE DEFECT. The #minimap panel sits in the top-level <main>, which
header.css hides for every VIEW_ID and overlay.css hides in the overlay
shell (measured: S144-U-227 / U-246, pinned by
test_home_minimap_polls_need_rendered_panel.py). Still, on every state
envelope of an SR game with positions, map_state.js renderMinimap rewrote
the line's counts, restarted its heartbeat animation through a forced
reflow (void heart.offsetWidth), and the first such render started a 1 s
setInterval that rewrote the "Ns ago" age and the heart's opacity for the
rest of the page's life. MEASURED headless before the fix
(/?ui_mock=1&mode=sr#active-match, 1920x920, two renders): #mm-state had
no layout box, 2 offsetWidth reads, 1 interval started. In ARAM / KIWI the
same line was the only visible-by-design output of refreshVisionOverlay
besides its enemy dots, which it draws only over the minimap image of the
same unrendered panel.

THE FIX. The markup, its CSS (grid.css .minimap-state family and the
mmHeartPulse keyframes, map_state.css .mm-vt-overlay), the status half of
renderMinimap, _renderMmStateLine and the whole refreshVisionOverlay poll
are removed. The Active Match MAP pane keeps its own /api/vision-state
poll (active_match.js), which this does not touch.

The zone-pill assertions are the positive control: they fail if
renderMinimap stops reaching _updateZone, so the retirement cannot pass by
breaking the live half.
"""
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

REPO = Path(__file__).resolve().parents[2]

_DRIVE = r"""async () => {
  const url = performance.getEntriesByType('resource')
    .map((e) => e.name).find((n) => n.includes('/panels/map_state.js'));
  const surl = performance.getEntriesByType('resource')
    .map((e) => e.name).find((n) => n.includes('/lib/state.js'));
  if (!url || !surl) return {err: 'map_state.js or state.js not loaded'};
  const m = await import(url);
  const s = await import(surl);
  s.state.lastTouch.minimap = 0;
  const desc = Object.getOwnPropertyDescriptor(
    HTMLElement.prototype, 'offsetWidth');
  let reads = 0;
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
    configurable: true,
    get() { reads += 1; return desc.get.call(this); },
  });
  const origSI = window.setInterval;
  let intervals = 0;
  window.setInterval = function () {
    intervals += 1;
    return origSI.apply(this, arguments);
  };
  const p = {
    game_time_s: 600, game_time: '10:00',
    dragon_state: 'Dragon spawns 12:00',
    champion: 'Ahri', my_team: 'blue',
    positions: {
      allies: {Ahri: {x: 0.2, y: 0.8}, Lux: {x: 0.25, y: 0.75}},
      enemies: {Zed: {x: 0.8, y: 0.2}},
    },
  };
  const out = {threw: null};
  out.before = document.querySelectorAll(
    '#mm-state, .minimap-state, #mm-vt-overlay').length;
  try {
    m.renderMinimap(p);
    m.renderMinimap(p);
  } catch (e) {
    out.threw = String(e);
  } finally {
    Object.defineProperty(HTMLElement.prototype, 'offsetWidth', desc);
    window.setInterval = origSI;
  }
  out.reads = reads;
  out.intervals = intervals;
  out.after = document.querySelectorAll(
    '#mm-state, .minimap-state, .mm-heart, .mm-counts, .mm-age, '
    + '#mm-vt-overlay').length;
  out.exported = ('_renderMmStateLine' in m);
  out.zone = document.body.dataset.zone ?? null;
  const pill = document.getElementById('zone-pill');
  out.pillClass = pill ? pill.className : null;
  out.pillText = (document.getElementById('zone-label') || {}).textContent;
  out.touched = s.state.lastTouch.minimap > 0;
  return out;
}"""


@pytest.fixture(scope="module")
def drive(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 920}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url + "/?ui_mock=1&mode=sr#active-match",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "() => document.body.dataset.view === 'active-match'",
            timeout=10_000)
        got = page.evaluate(_DRIVE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert "err" not in got, got
    return got


def test_the_state_line_and_vt_overlay_markup_is_gone(drive):
    assert drive["before"] == 0, drive
    assert drive["after"] == 0, drive


def test_render_minimap_forces_no_reflow_and_starts_no_timer(drive):
    assert drive["threw"] is None, drive
    assert drive["reads"] == 0, drive
    assert drive["intervals"] == 0, drive


def test_the_state_line_helper_is_no_longer_exported(drive):
    assert drive["exported"] is False, drive


def test_positive_control_the_zone_pill_still_reads_your_position(drive):
    # Two allies stacked deep on the blue side, the one enemy far away.
    assert drive["zone"] == "safe", drive
    assert drive["pillClass"] == "zone-pill zone-safe", drive
    assert drive["pillText"] == "\u2713 SAFE", drive


def test_positive_control_render_minimap_still_stamps_its_panel(drive):
    # S144-U-262 retired the objective rows this used to read; the
    # CADENCE sweep's freshness stamp is the kept per-render write.
    assert drive["touched"] is True, drive


_NAMES = (
    "minimap-state", "mm-heart", "mm-counts", "mm-age", "mmHeartPulse",
    "_renderMmStateLine", "mm-vt-overlay", "refreshVisionOverlay",
    "VT_OVERLAY", "VT_SHARED_VISION", "vtInflight", "MM.status",
    '"mm-state"', "#mm-state",
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


def test_anchor_the_name_scan_reads_real_files():
    # An empty scan would pass the test above; prove it reads the live
    # files by finding the live neighbours of the retired parts.
    files = dict(_live_web_text())
    assert len(files) > 20, len(files)
    assert 'id="zone-pill"' in files["web/index.html"]
    assert 'data-for="minimap"' in files["web/index.html"]
    assert "function _updateZone(" in files["web/js/panels/map_state.js"]
    assert "(function setupMinimapPoller()" in files["web/js/main.js"]
    assert "/api/vision-state" in files["web/js/panels/active_match.js"]
    assert ".mm-zoi-canvas {" in files["web/css/panels/grid.css"]
