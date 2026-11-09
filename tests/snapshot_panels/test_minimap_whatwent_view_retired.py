"""
tests/snapshot_panels/test_minimap_whatwent_view_retired.py
S144-U-260 (s144 uiux): the never-rendered WHAT WENT view (#mm-whatwent-view
with its #ww-good / #ww-bad lists) is retired from the #minimap panel, with
right_now.js renderWhatWent, its main.js call and the map_state.css
.what-went-* rules.

THE DEFECT. The #minimap panel sits in the top-level <main>, which
header.css hides for every VIEW_ID and overlay.css hides in the overlay
shell (measured: S144-U-227 / U-246, pinned by
test_home_minimap_polls_need_rendered_panel.py). The WHAT WENT view was the
panel's client-mode body (map_state.css swapped it in for the objective
rows under body[data-mode="client"]), so the aftergame bullets it carried
were never on screen. Still, main.js onState called renderWhatWent on every
state envelope, and it emptied and rebuilt both lists through innerHTML
each time. MEASURED headless before the fix (/?ui_mock=1#home, 1920x920,
client mode): #mm-whatwent-view present with no layout box, renderWhatWent
exported, two calls rewrote both lists twice (4 list rebuilds).

No other web surface reads what_went_good / what_went_bad (grep of web/js),
so the server-side aftergame bullets (core/aftergame_summary.py) now reach
no rendered surface; that payload is left as is and filed as a FUTURE row
for the Post Game Review reframe rather than relocated here by taste.

The objective rows (#mm-objectives-view) stay; their retirement is a
separate question (the CADENCE sweep reads MM.root). The positive controls
pin that the neighbouring Right Now renders are untouched.
"""
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

REPO = Path(__file__).resolve().parents[2]

_DRIVE = r"""async () => {
  const url = performance.getEntriesByType('resource')
    .map((e) => e.name).find((n) => n.includes('/panels/right_now.js'));
  if (!url) return {err: 'right_now.js not loaded'};
  const m = await import(url);
  const out = {threw: null};
  const view = document.getElementById('mm-whatwent-view');
  out.viewPresent = !!view;
  out.viewBoxes = view ? view.getClientRects().length : 0;
  out.exported = ('renderWhatWent' in m);
  out.gameSenseExported = (typeof m.renderGameSense === 'function');
  out.statsExported = (typeof m.renderStats === 'function');
  const p = {
    what_went_good: ['Synthetic positive A', 'Synthetic positive B'],
    what_went_bad: ['Synthetic negative A'],
  };
  let rebuilds = 0;
  const obs = new MutationObserver((recs) => {
    for (const r of recs) if (r.removedNodes.length) rebuilds += 1;
  });
  for (const id of ['ww-good', 'ww-bad']) {
    const ul = document.getElementById(id);
    if (ul) obs.observe(ul, {childList: true});
  }
  try {
    if (out.exported) { m.renderWhatWent(p); m.renderWhatWent(p); }
    m.renderGameSense(p);
    m.renderStats(p);
  } catch (e) {
    out.threw = String(e);
  }
  await new Promise((r) => setTimeout(r, 0));
  obs.disconnect();
  out.rebuilds = rebuilds;
  out.after = document.querySelectorAll(
    '#mm-whatwent-view, .what-went-view, .what-went-section, '
    + '.what-went-title, .what-went-list, #ww-good, #ww-bad, .ww-empty'
  ).length;
  out.objectives = !!document.getElementById('mm-objectives-view');
  out.dragonRow = !!document.getElementById('mm-dragon');
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
            mock_server.url + "/?ui_mock=1#home",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "() => document.body.dataset.view === 'home'", timeout=10_000)
        got = page.evaluate(_DRIVE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert "err" not in got, got
    return got


def test_the_whatwent_markup_is_gone(drive):
    assert drive["viewPresent"] is False, drive
    assert drive["after"] == 0, drive


def test_render_whatwent_is_no_longer_exported_and_rebuilds_nothing(drive):
    assert drive["threw"] is None, drive
    assert drive["rebuilds"] == 0, drive
    assert drive["exported"] is False, drive


def test_positive_control_the_neighbour_renders_are_untouched(drive):
    assert drive["gameSenseExported"] is True, drive
    assert drive["statsExported"] is True, drive


def test_positive_control_the_objective_rows_stay(drive):
    assert drive["objectives"] is True, drive
    assert drive["dragonRow"] is True, drive


_NAMES = (
    "renderWhatWent", "mm-whatwent-view", "what-went-view",
    "what-went-section", "what-went-title", "what-went-list",
    "what-went-good", "what-went-bad", '"ww-good"', '"ww-bad"', "ww-empty",
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
    assert 'id="mm-objectives-view"' in files["web/index.html"]
    assert "function renderGameSense(" in files["web/js/panels/right_now.js"]
    assert "renderGameSense(p);" in files["web/js/main.js"]
    assert "#mm-objectives-view" in files["web/css/panels/map_state.css"]
