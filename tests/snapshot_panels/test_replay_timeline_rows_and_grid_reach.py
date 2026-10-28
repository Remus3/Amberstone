"""
tests/snapshot_panels/test_replay_timeline_rows_and_grid_reach.py
RM-1019 (s144 uiux): two Replay main-pane defects, measured in headless
Chromium under /?ui_mock=1#replay after a match is loaded.

1. The timeline rows (`.replay-events-row`, web/css/panels/replay_events.css)
   are click-to-seek controls but rendered 36px tall, under --hit-min (42px),
   at both 1920x920 and 923x1280.

2. Re-checking the item-185 height budget (list cap 320px, grid floor 360px)
   found it already blown at the 1920x920 baseline: the pane's children
   (meta row, scrubber, timeline section, participant grid) measure about
   210px taller than `.replay-main-pane`, and the pane was `overflow: hidden`
   (web/css/panels/primitives.css). The grid box ran from y=718 to 1078 under
   a clip edge at 888, so at the grid's own max scroll only 6 of the 10
   participant rows were ever visible - the last four could not be seen by
   any means. web/css/panels/review_player.css already let the pane scroll,
   but only while a recording is shown, on the stated belief that the
   children "already fill a ~920px viewport".

The fix keeps both item-185 values: rows take min-height: var(--hit-min),
and the pane scrolls on the y axis, so every participant row is reachable.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page

_EVENT_ROWS = ".replay-events-row"
_GRID_ROWS = ".replay-grid-wrap tbody tr"


def _load_first_match(page, mock_server):
    page.goto(mock_server.url + "/?ui_mock=1#replay",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_selector("#replay-match-list .replay-match-row", timeout=10_000)
    page.click("#replay-match-list .replay-match-row")
    page.wait_for_function(
        f"() => document.querySelectorAll('{_EVENT_ROWS}').length > 0"
        f" && document.querySelectorAll('{_GRID_ROWS}').length > 0",
        timeout=10_000,
    )


_ROW_HEIGHTS = """
() => {
  const hitMin = parseFloat(getComputedStyle(document.documentElement)
    .getPropertyValue('--hit-min'));
  const list = document.querySelector('.replay-events-list');
  return {
    hitMin,
    rows: [...document.querySelectorAll('.replay-events-row')].map(r => ({
      kind: r.dataset.kind || '',
      h: r.getBoundingClientRect().height,
    })),
    listMax: getComputedStyle(list).maxHeight,
    listCh: list.clientHeight,
    listSh: list.scrollHeight,
  };
}
"""


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_timeline_rows_reach_hit_min(mock_server, pw_browser, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    try:
        _load_first_match(page, mock_server)
        m = page.evaluate(_ROW_HEIGHTS)
        # Anchor: --hit-min resolves (42px in web/css/tokens.css) and the
        # fixture (web/data/ui_mock/replay.json) renders >= 10 rows.
        assert m["hitMin"] >= 40, m["hitMin"]
        assert len(m["rows"]) >= 10, len(m["rows"])
        short = [r for r in m["rows"] if r["h"] + 0.5 < m["hitMin"]]
        assert not short, (
            f"timeline seek rows under --hit-min {m['hitMin']}px: {short[:3]}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_timeline_list_keeps_the_item_185_cap(mock_server, pw_browser, vp):
    """The taller rows must not grow the ribbon: the list stays capped at
    320px and scrolls its tail (the fixture saturates it, so the cap is
    exercised, not vacuous)."""
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    try:
        _load_first_match(page, mock_server)
        m = page.evaluate(_ROW_HEIGHTS)
        assert m["listMax"] == "320px", m["listMax"]
        assert m["listCh"] <= 320, m
        assert m["listSh"] > m["listCh"], f"list not saturated, cap untested: {m}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


# Walk the clipping ancestors of the LAST participant row. Every one that
# overflows must be user-scrollable (overflow-y auto / scroll): a hidden
# overflow is reachable only by script. Then scroll each scrollable ancestor
# to its end, innermost first, and report where the row and the grid box sit
# against every clip edge and the window.
_REACH = """
() => {
  const rows = [...document.querySelectorAll('.replay-grid-wrap tbody tr')];
  const last = rows[rows.length - 1];
  const wrap = document.querySelector('.replay-grid-wrap');
  const clippers = [];
  for (let el = last.parentElement; el && el !== document.documentElement;
       el = el.parentElement) {
    const cs = getComputedStyle(el);
    if (cs.overflowY !== 'visible') clippers.push(el);
  }
  const trapped = clippers
    .filter(el => el.scrollHeight > el.clientHeight + 1)
    .filter(el => !['auto', 'scroll'].includes(getComputedStyle(el).overflowY))
    .map(el => (el.id || el.className || el.tagName) + ' overflowY='
         + getComputedStyle(el).overflowY + ' sh=' + el.scrollHeight
         + ' ch=' + el.clientHeight);
  for (const el of clippers) {
    if (['auto', 'scroll'].includes(getComputedStyle(el).overflowY)) {
      el.scrollTop = el.scrollHeight;
    }
  }
  const clipBottom = el => {
    const b = el.getBoundingClientRect();
    return b.top + el.clientTop + el.clientHeight;
  };
  const edge = Math.min(window.innerHeight, ...clippers.map(clipBottom));
  return {
    rows: rows.length,
    trapped,
    lastBottom: last.getBoundingClientRect().bottom,
    wrapBottom: wrap.getBoundingClientRect().bottom,
    wrapH: wrap.getBoundingClientRect().height,
    edge,
  };
}
"""


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_every_participant_row_is_reachable(mock_server, pw_browser, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    try:
        _load_first_match(page, mock_server)
        m = page.evaluate(_REACH)
        # Anchor: the fixture's frames carry all 10 participants.
        assert m["rows"] == 10, m
        assert not m["trapped"], (
            f"participant grid clipped by a box the user cannot scroll: "
            f"{m['trapped']}"
        )
        assert m["lastBottom"] <= m["edge"] + 0.5, (
            f"last participant row ends at {m['lastBottom']}, clip edge "
            f"{m['edge']}: {m}"
        )
        # The grid keeps its item-185 360px floor and its whole box shows.
        assert m["wrapH"] >= 359.5, m
        assert m["wrapBottom"] <= m["edge"] + 0.5, m
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
