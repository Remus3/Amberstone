"""
tests/snapshot_panels/test_replay_filter_hit_targets.py
RM-1065 (s144 uiux): the RM-1063 verifier measured the Replay timeline
filter controls #replay-evt-items / -skills / -wards (web/index.html, the
.replay-events-filters head of #replay-events-section) at 20px tall, under
the 42px --hit-min floor (web/css/tokens.css), and filed it for a check.

Measured in headless Chromium under /?ui_mock=1#replay after a match is
loaded, 1920x920 and 923x1280: the 20px boxes are the checkboxes
themselves (web/css/panels/replay_events.css sizes them 20x20). Each one is
wrapped in label.replay-events-filter, which already carries
`min-height: var(--hit-min)` plus horizontal padding and renders 42px tall
and about 79-90px wide, and a real pointer click at the label's far corner, clear
of the box, toggles its checkbox and fires the change handler that re-fetches
the timeline (web/js/panels/replay_events.js). Keyboard focus already draws
the system ring (RM-1017, pinned in test_focus_ring_token_sites.py). So no
defect: the label is the target, the same pattern RM-1016 pinned for the
Settings checkboxes (test_settings_checkbox_hit_targets.py).

Before this file nothing pinned it: the only guards on these controls check
the focus ring and Space handling, never the label box or a click outside
the checkbox. This one fails if a filter loses its label wrapper, a label
drops under --hit-min, or a click outside the box stops toggling the filter.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page
from tests.snapshot_panels.test_replay_timeline_rows_and_grid_reach import (
    _load_first_match,
)

_IDS = ("replay-evt-items", "replay-evt-skills", "replay-evt-wards")

_BOXES = """
(ids) => {
  const hitMin = parseFloat(getComputedStyle(document.documentElement)
    .getPropertyValue('--hit-min'));
  return {hitMin, boxes: ids.map(id => {
    const cb = document.getElementById(id);
    const lab = cb && cb.closest('label');
    const r = cb ? cb.getBoundingClientRect() : null;
    const lr = lab ? lab.getBoundingClientRect() : null;
    return {
      id, found: !!cb, kind: lab ? lab.className : '(no label)',
      cbH: r ? r.height : 0,
      labW: lr ? lr.width : 0, labH: lr ? lr.height : 0,
    };
  })};
}
"""


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_every_replay_filter_label_clears_hit_min(mock_server, pw_browser, vp):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    try:
        _load_first_match(page, mock_server)
        m = page.evaluate(_BOXES, list(_IDS))
    finally:
        page.close()
        ctx.close()
    hit = m["hitMin"]
    assert hit >= 42, f"--hit-min resolved to {hit}px"
    for b in m["boxes"]:
        assert b["found"], f"#{b['id']} missing from the Replay timeline head"
        assert b["kind"] == "replay-events-filter", (
            f"#{b['id']} is not wrapped in label.replay-events-filter: {b}"
        )
        # Anchor: the box is the small control the rule allows (and is
        # rendered, so a hidden section cannot pass with zero-size rects) ...
        assert 0 < b["cbH"] < hit, f"premise: box {b}"
        # ... and its label is the full fingertip target.
        assert b["labH"] >= hit - 0.5, (
            f"#{b['id']} label {b['labH']}px tall < --hit-min {hit}px"
        )
        assert b["labW"] >= hit - 0.5, (
            f"#{b['id']} label {b['labW']}px wide < --hit-min {hit}px"
        )
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_click_on_filter_label_outside_the_box_toggles(mock_server, pw_browser, vp):
    """A real pointer click 4px inside each label's far corner, clear of the
    20px box, toggles the checkbox and fires its change handler. The point
    is checked to land inside the label and off the checkbox first."""
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    failures = []
    try:
        _load_first_match(page, mock_server)
        for cb_id in _IDS:
            h = page.query_selector(f"#{cb_id}")
            pt = h.evaluate(
                """e => {
                  e.__changes = 0;
                  e.addEventListener('change', () => { e.__changes += 1; });
                  const lab = e.closest('label');
                  const lr = lab.getBoundingClientRect();
                  const x = lr.right - 4, y = lr.bottom - 4;
                  const at = document.elementFromPoint(x, y);
                  return {x, y, inLabel: !!at && lab.contains(at),
                          onBox: at === e};
                }"""
            )
            if not pt["inLabel"] or pt["onBox"]:
                failures.append(f"{cb_id}: probe point {pt}")
                continue
            before = h.is_checked()
            page.mouse.click(pt["x"], pt["y"])
            after = h.evaluate("e => e.checked")
            changes = h.evaluate("e => e.__changes")
            if after == before or changes != 1:
                failures.append(
                    f"{cb_id}: label click checked {before}->{after}, "
                    f"{changes} change events"
                )
    finally:
        page.close()
        ctx.close()
    assert not failures, failures
    assert not errors, f"JS errors: {errors[:3]}"
