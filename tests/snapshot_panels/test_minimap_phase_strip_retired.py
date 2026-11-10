"""
tests/snapshot_panels/test_minimap_phase_strip_retired.py
S144-U-254 (s144 uiux): the never-rendered match-phase strip
(#phase-strip, its three .phase-seg bars and #phase-marker) is retired
from the Map State panel; body[data-phase], the one live output of the
same code, keeps working.

THE DEFECT. MEASURED headless under /?ui_mock=1&mode=sr#<view>, 1920x920,
in all 12 VIEW_IDS and again with &overlay=1: after
map_state.js _applyGamePhase(1000) the strip had lost its .hidden class,
yet getClientRects().length was 0 in all 24 renders. The strip sits in the
#minimap panel inside the top-level <main>, which header.css hides for
every VIEW_ID and overlay.css hides in the overlay shell (the same cause
S144-U-227 / U-245 / U-246 measured for the rest of the panel). Every
game-clock anchor still un-hid it and moved its marker (a style write) and
restarted the marker's 1.8 s keyframe (a forced reflow via offsetWidth on
every phase change), and web/css/panels/grid.css carried 36 lines for
it (a comment, the rules and a @keyframes).

THE FIX. The markup, its CSS and the strip / marker half of
_applyGamePhase are removed. _applyGamePhase still stamps
body[data-phase] (early < 15:00, mid < 25:00, late), which two live
rule sets read: the header tint in web/css/panels/base.css and the
stage-gated STATS groups in web/css/panels/map_state.css.

The header-tint assertions are the positive control: they fail if the
phase stamp itself stops working, so the retirement cannot pass by
breaking the live half.
"""
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

REPO = Path(__file__).resolve().parents[2]

_DRIVE = """async () => {
  const url = performance.getEntriesByType('resource')
    .map((e) => e.name).find((n) => n.includes('/panels/map_state.js'));
  if (!url) return {err: 'map_state.js not loaded'};
  const m = await import(url);
  const strip = document.querySelectorAll(
    '#phase-strip, #phase-marker, .phase-seg').length;
  const header = document.querySelector('body > header');
  const out = {strip, rows: [], threw: null};
  try {
    for (const s of [300, 1000, 1600, 899, 1499]) {
      m._applyGamePhase(s);
      out.rows.push({
        s, phase: document.body.dataset.phase ?? null,
        bg: getComputedStyle(header).backgroundImage,
      });
    }
  } catch (e) {
    out.threw = String(e);
  }
  out.stripAfter = document.querySelectorAll(
    '#phase-strip, #phase-marker, .phase-seg').length;
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


def _by_s(drive):
    return {r["s"]: r for r in drive["rows"]}


def test_the_phase_strip_markup_is_gone(drive):
    assert drive["strip"] == 0, drive
    assert drive["stripAfter"] == 0, drive


def test_apply_game_phase_does_not_throw_without_the_strip(drive):
    assert drive["threw"] is None, drive


def test_body_data_phase_is_still_stamped_at_each_boundary(drive):
    rows = _by_s(drive)
    assert rows[300]["phase"] == "early", rows
    assert rows[899]["phase"] == "early", rows
    assert rows[1000]["phase"] == "mid", rows
    assert rows[1499]["phase"] == "mid", rows
    assert rows[1600]["phase"] == "late", rows


def test_positive_control_the_header_tint_follows_the_phase(drive):
    rows = _by_s(drive)
    assert rows[300]["bg"] == "none", rows
    assert "linear-gradient" in rows[1000]["bg"], rows
    assert "linear-gradient" in rows[1600]["bg"], rows
    # mid (gold) and late (red) are different tints.
    assert rows[1000]["bg"] != rows[1600]["bg"], rows


def test_no_stylesheet_or_script_still_names_the_strip():
    names = ("phase-strip", "phase-seg", "phase-marker", "phaseTransition",
             "phase-transition")
    hits = []
    for sub, pat in (("web/css", "*.css"), ("web/js", "*.js")):
        for p in sorted((REPO / sub).rglob(pat)):
            text = p.read_text(encoding="utf-8")
            hits += [(p.relative_to(REPO).as_posix(), n)
                     for n in names if n in text]
    html = (REPO / "web/index.html").read_text(encoding="utf-8")
    hits += [("web/index.html", n) for n in names if n in html]
    assert hits == [], hits


def test_anchor_the_name_scan_reads_real_files():
    # An empty scan would pass the test above; prove it reads the live
    # files by finding the phase stamp's live consumers.
    base = (REPO / "web/css/panels/base.css").read_text(encoding="utf-8")
    ms_css = (REPO / "web/css/panels/map_state.css").read_text(
        encoding="utf-8")
    ms_js = (REPO / "web/js/panels/map_state.js").read_text(encoding="utf-8")
    assert 'body[data-phase="mid"]' in base
    assert '[data-phase="early"] .stats-group' in ms_css
    assert "document.body.dataset.phase = phase" in ms_js
