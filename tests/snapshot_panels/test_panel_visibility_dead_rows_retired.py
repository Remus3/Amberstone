"""
tests/snapshot_panels/test_panel_visibility_dead_rows_retired.py
S144-U-263 (s144 uiux): the Settings view's PANEL VISIBILITY card
(web/js/panels/panel_visibility.js buildPanelVisibilitySettings) no longer
lists checkboxes for panels that render in no view.

THE DEFECT. The card built one checkbox row per PANELS registry entry, 17
per context tab. Nine of them named panels inside the top-level <main>
(Map State, Right Now, Next, Item Build, Adaptation and the Right Now
children Macro Lead, Coach Choices, Callouts, Personal Context). header.css
hides that <main> for every VIEW_ID, so those nine rows had no visible
effect in any view or context: unticking one stamped data-pv-hidden on a
node that already had no layout box, and the operator saw nothing change.
The overlay shell, where the Right Now strip mounts do render, is exempt
from the gate by design (applyPanelVisibility returns early there), so the
rows could not reach it either. The registry's own comment already refused
dead checkboxes for overlay-only widgets; these nine were the same case.

THE FIX. The nine entries leave the PANELS registry; the card lists the
eight panels a view can show. A stored pref for a retired id is dropped on
read like any unknown id (fail-open), so an old blob neither throws nor
hides anything.

Pinned here, in headless Chromium against the fixture-driven mock server:
- the premise: each of the nine ids sits inside the top-level <main> and
  has no layout box in any VIEW_ID under any mode tag;
- the card: every context tab lists exactly the eight kept panels, in
  registry order, and none of the nine;
- positive control: unticking a kept row still hides its panel and
  persists, and re-ticking shows it again;
- an old blob that hid a retired id loads without a page error and its
  retired key does not survive the next write.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

VIEWPORT = {"width": 1920, "height": 920}

RETIRED = [
    "minimap", "right-now", "next", "item-build", "adaptation",
    "rn-lead", "rn-choices", "rn-callouts", "personal-context-section",
]
KEPT = [
    "coach-decisions", "session-trend", "lm-tc-table", "hpgr-tc-table",
    "am-spike-curve", "am-spike-markers", "am-ward-heat",
    "aram-balance-panel",
]
# S144-U-264 retired the #minimap node itself
# (test_minimap_panel_shell_retired.py); the premise reads the rest, and
# pins that minimap is not served at all. RETIRED still drives the row and
# old-blob cases below.
# S144-U-265: the NEXT panel is no longer served either
# (test_next_panel_retired.py).
SERVED_RETIRED = [i for i in RETIRED if i not in ("minimap", "next")]
CONTEXTS = ["in-game-sr", "in-game-aram", "in-game-arena", "in-game-tft",
            "out-game"]

_READY = (
    "document.body.dataset.view === 'settings' && "
    "document.querySelector('#panel-visibility-card .pv-cell') !== null"
)


def _open(pw_browser, mock_server, blob=None):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(ignore_https_errors=True, viewport=VIEWPORT)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    if blob is not None:
        page.add_init_script(
            "try { localStorage.setItem('rc-panel-visibility', "
            + json.dumps(blob) + "); } catch (_e) {}"
        )
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + "/?ui_mock=1#settings",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(_READY, timeout=10_000)
    return ctx, page, errors


def _close(page, ctx, mock_server):
    page.close()
    ctx.close()
    mock_server._store["data"] = {}


@pytest.fixture
def settings_page(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server)
    try:
        yield page, errors
    finally:
        _close(page, ctx, mock_server)


def test_premise_the_retired_ids_render_in_no_view(settings_page):
    """Each retired id sits in the top-level <main> and has no layout box
    in any VIEW_ID under any mode tag. If a view starts showing <main>,
    its panels need their rows back; update this pin."""
    page, errors = settings_page
    got = page.evaluate("""async (ids) => {
      const { VIEW_IDS } = await import('/js/lib/state.js');
      const b = document.body;
      const keep = { view: b.dataset.view, mode: b.dataset.mode };
      const out = { views: VIEW_IDS.length, inMain: {}, boxes: {},
                    minimapNode: !!document.getElementById('minimap'),
                    nextNode: !!document.getElementById('next') };
      for (const id of ids) {
        const n = document.getElementById(id);
        out.inMain[id] = !!n && !!n.closest('body > main');
        out.boxes[id] = 0;
      }
      for (const mode of ['sr', 'aram', 'arena', 'tft', 'client']) {
        b.dataset.mode = mode;
        for (const v of VIEW_IDS) {
          b.dataset.view = v;
          for (const id of ids) {
            out.boxes[id] += document.getElementById(id)
              .getClientRects().length;
          }
        }
      }
      b.dataset.view = keep.view;
      if (keep.mode === undefined) delete b.dataset.mode;
      else b.dataset.mode = keep.mode;
      return out;
    }""", SERVED_RETIRED)
    assert not errors, errors[:3]
    assert got["views"] >= 12, got
    assert got["minimapNode"] is False, got
    assert got["nextNode"] is False, got
    assert got["inMain"] == {i: True for i in SERVED_RETIRED}, got["inMain"]
    assert got["boxes"] == {i: 0 for i in SERVED_RETIRED}, got["boxes"]


def test_every_tab_lists_only_the_panels_a_view_can_show(settings_page):
    page, errors = settings_page
    rows = page.evaluate("""(ctxs) => {
      const card = document.getElementById('panel-visibility-card');
      const out = {};
      for (const c of ctxs) {
        card.querySelector('.pv-tab[data-pv-tab="' + c + '"]').click();
        out[c] = Array.from(card.querySelectorAll(
          '.pv-table input[type=checkbox]'))
          .map((cb) => [cb.dataset.pvContext, cb.dataset.pvPanel]);
      }
      return out;
    }""", CONTEXTS)
    assert not errors, errors[:3]
    assert list(rows) == CONTEXTS
    for c, pairs in rows.items():
        assert [p for _ctx, p in pairs] == KEPT, (c, pairs)
        assert {ctx for ctx, _p in pairs} == {c}, (c, pairs)
        assert not set(RETIRED) & {p for _c, p in pairs}, (c, pairs)


def test_a_kept_row_still_hides_and_shows_its_panel(settings_page):
    """Positive control: the gate still works for the rows that remain."""
    page, errors = settings_page
    page.click('#panel-visibility-card .pv-tab[data-pv-tab="out-game"]')
    sel = ('#panel-visibility-card input[data-pv-context="out-game"]'
           '[data-pv-panel="session-trend"]')
    read = """() => {
      let blob = null;
      try { blob = JSON.parse(localStorage.getItem('rc-panel-visibility')); }
      catch (_e) { blob = null; }
      return {
        hidden: document.getElementById('session-trend').dataset.pvHidden
          || null,
        stored: blob && blob['out-game'] ? blob['out-game']['session-trend']
          : null,
        keys: blob && blob['out-game'] ? Object.keys(blob['out-game']) : [],
      };
    }"""
    page.click(sel)
    off = page.evaluate(read)
    page.click(sel)
    on = page.evaluate(read)
    assert not errors, errors[:3]
    assert off["hidden"] == "1" and off["stored"] is False, off
    assert on["hidden"] is None and on["stored"] is True, on
    assert sorted(on["keys"]) == sorted(KEPT), on["keys"]


def test_an_old_blob_hiding_a_retired_id_is_dropped(mock_server, pw_browser):
    old = json.dumps({
        "in-game-sr": {"minimap": False, "right-now": False,
                       "session-trend": True},
        "out-game": {"next": False, "item-build": False},
    })
    ctx, page, errors = _open(pw_browser, mock_server, blob=old)
    try:
        page.click('#panel-visibility-card .pv-tab[data-pv-tab="out-game"]')
        page.click('#panel-visibility-card input[data-pv-context="out-game"]'
                   '[data-pv-panel="am-ward-heat"]')
        got = page.evaluate("""() => ({
          blob: JSON.parse(localStorage.getItem('rc-panel-visibility')),
          stamped: Array.from(document.querySelectorAll('[data-pv-hidden]'))
            .map((n) => n.id),
        })""")
    finally:
        _close(page, ctx, mock_server)
    assert not errors, errors[:3]
    for c in CONTEXTS:
        assert not set(RETIRED) & set(got["blob"][c]), (c, got["blob"][c])
    assert got["blob"]["out-game"]["am-ward-heat"] is False, got["blob"]
    assert got["stamped"] == ["am-ward-heat"], got["stamped"]
