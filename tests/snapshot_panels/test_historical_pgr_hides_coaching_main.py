"""
tests/snapshot_panels/test_historical_pgr_hides_coaching_main.py
RM-1552 (s144 uiux) - the detached historical Post Game Review (the view a
History or Session match row opens, #view-historical-pgr) gets the whole
area between the header and the footer. The top-level "Coaching panels"
<main> (web/index.html: MAP STATE, RIGHT NOW, NEXT, ITEM BUILD, ADAPTATION)
stays hidden there, as it is in every other view.

MEASURED BEFORE THE FIX (headless Chromium, 1920x920, /?ui_mock=1#history,
first session row, first match row): web/css/panels/header.css hid the
top-level <main> for 11 of the 12 VIEW_IDS (web/js/lib/state.js) but not
historical-pgr, so <main> painted as a 1920x578 grid at y=53 with all five
coaching panels and their live age badges, and the review was pushed into a
1884x245 band at y=633 (298px of content in a 243px box).

Two guards:
- the real flow: a History row click reaches historical-pgr (no class or
  attribute stamped by the test), the top-level <main> is not rendered and
  the review section starts right under the header and runs to the footer;
- every VIEW_ID: with body[data-view] set to it, the top-level <main> is
  display:none, so a view added later without a hide rule fails here. The
  list is read from state.js, so it cannot go stale; the nested Replay
  <main class="replay-main-pane"> must still render in the Replay view.
"""
import json
import re
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
# Synthetic HIST2 payload (no real ids); its champion proves a real review
# loaded, not the "-" placeholder.
from tests.snapshot_panels.test_historical_pgr_view import (
    _HIST_PAYLOAD,
    HIST_CHAMP,
)

ROOT = Path(__file__).resolve().parent.parent.parent


def _view_ids():
    text = (ROOT / "web" / "js" / "lib" / "state.js").read_text(encoding="utf-8")
    m = re.search(r"export const VIEW_IDS = \[(.*?)\];", text, re.S)
    assert m, "VIEW_IDS not found in web/js/lib/state.js"
    return re.findall(r'"([a-z0-9-]+)"', m.group(1))


_VIEW_IDS = _view_ids()

_READ = r"""() => {
  const R = (e) => { const b = e.getBoundingClientRect();
    return [b.x, b.y, b.width, b.height]; };
  const main = document.querySelector('body > main');
  const view = document.getElementById('view-historical-pgr');
  const head = document.querySelector('body > header');
  const foot = document.querySelector('body > footer');
  return {
    view: document.body.dataset.view,
    mainDisplay: getComputedStyle(main).display,
    mainRects: main.getClientRects().length,
    panels: [...main.querySelectorAll(':scope > .panel')]
      .filter((p) => p.getClientRects().length).map((p) => p.id),
    badges: [...document.querySelectorAll('.staleness')]
      .filter((b) => b.getClientRects().length).length,
    viewRect: R(view), headBottom: R(head)[1] + R(head)[3],
    footTop: R(foot)[1],
    champ: (document.getElementById('hpgr-champion-name') || {}).textContent,
  };
}"""


@pytest.fixture(scope="module")
def flow(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route("**/api/last-match*", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(_HIST_PAYLOAD)))
    try:
        page.goto(mock_server.url + "/?ui_mock=1#history",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_selector("#history-session-list .history-session-row",
                               timeout=10_000)
        page.click("#history-session-list .history-session-row")
        page.wait_for_selector("#history-match-list .history-match-row",
                               timeout=10_000)
        before = page.evaluate(_READ)
        page.click("#history-match-list .history-match-row")
        page.wait_for_function(
            "document.body.dataset.view === 'historical-pgr'", timeout=10_000)
        page.wait_for_selector("#view-historical-pgr", state="visible",
                               timeout=10_000)
        page.wait_for_function(
            "(c) => ((document.getElementById('hpgr-champion-name') || {})"
            ".textContent || '').trim() === c", arg=HIST_CHAMP,
            timeout=10_000)
        page.wait_for_timeout(600)   # two staleness sweeps (500 ms tick)
        after = page.evaluate(_READ)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
    return before, after


def test_history_view_anchor(flow):
    before, _ = flow
    # Anchor: the hide rule really applies on the view the flow starts from,
    # so an "after" with no <main> is the rule, not a missing element.
    assert before["view"] == "history", before
    assert before["mainDisplay"] == "none" and before["mainRects"] == 0, before


def test_historical_pgr_hides_the_coaching_main(flow):
    _, after = flow
    assert after["view"] == "historical-pgr", after
    assert (after["champ"] or "").strip() == HIST_CHAMP, after
    assert after["mainDisplay"] == "none", after
    assert after["mainRects"] == 0 and after["panels"] == [], after
    assert after["badges"] == 0, after


def test_historical_pgr_gets_the_area_under_the_header(flow):
    _, after = flow
    x, y, w, h = after["viewRect"]
    # The review starts within the view's own top margin of the header and
    # runs down to the footer (was y=633, h=245 at 920 tall).
    assert 0 <= y - after["headBottom"] <= 24, after
    assert after["footTop"] - (y + h) <= 24, after
    assert h >= 0.8 * (after["footTop"] - after["headBottom"]), after
    assert w >= 1800, after


@pytest.fixture(scope="module")
def per_view(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    out = {}
    try:
        page.goto(mock_server.url + "/?ui_mock=1#home",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function("document.body.dataset.view === 'home'",
                               timeout=10_000)
        for v in _VIEW_IDS:
            out[v] = page.evaluate(
                """(v) => { document.body.dataset.view = v;
                  const m = document.querySelector('body > main');
                  const r = document.querySelector('main.replay-main-pane');
                  return { main: getComputedStyle(m).display,
                           replay: r ? getComputedStyle(r).display : null }; }""",
                v)
    finally:
        page.close()
        ctx.close()
    return out


def test_view_list_anchor():
    # state.js really parsed, and the view this slice fixes is in it.
    assert len(_VIEW_IDS) >= 12, _VIEW_IDS
    assert "historical-pgr" in _VIEW_IDS and "active-match" in _VIEW_IDS


@pytest.mark.parametrize("view", _VIEW_IDS)
def test_every_view_hides_the_top_level_main(view, per_view):
    assert per_view[view]["main"] == "none", (view, per_view[view])


def test_replay_keeps_its_own_nested_main(per_view):
    assert per_view["replay"]["replay"] == "flex", per_view["replay"]
