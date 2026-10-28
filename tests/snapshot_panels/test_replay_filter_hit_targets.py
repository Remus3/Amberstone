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

RM-1071: the click test flaked about 1 in 6 runs ("checked False->False,
0 change events"), mostly at 923x1280. Cause, measured: the rows can render
before Lato arrives (display=swap, web/css/dashboard.css), and the swap moves
the filter labels up 7px at 1920x920 and 10px at 923x1280 within about 25ms,
more than the 4px corner inset, so a point probed before the swap could land
under the label by the time it was clicked. The shared load helper now waits
for the fonts and the re-layout (_settle_layout); the last test below holds
the font responses until the rows exist to make the swap happen every run.

RM-1078: that last test skipped when Google Fonts was unreachable or the
held face failed to load, two skips tests/test_skip_condition_hygiene.py
cannot resolve to an environment capability. It now serves a local stub
Lato (_webfont_stub.py) for both requests, so the swap runs on every host
with no network, and both former skips are assertions.
"""
import pytest

from tests.snapshot_panels._webfont_stub import (
    STUB_APPLIED,
    fulfill_stub_font,
    route_stub_webfont,
)
from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page
from tests.snapshot_panels.test_replay_timeline_rows_and_grid_reach import (
    _load_first_match,
    _load_match_rows,
    _settle_layout,
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


def _click_each_label_corner(page):
    """Click 4px inside each filter label's far corner, clear of the box;
    return the failures (an empty list = every filter toggled once)."""
    failures = []
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
    return failures


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_click_on_filter_label_outside_the_box_toggles(mock_server, pw_browser, vp):
    """A real pointer click 4px inside each label's far corner, clear of the
    20px box, toggles the checkbox and fires its change handler. The point
    is checked to land inside the label and off the checkbox first."""
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    try:
        _load_first_match(page, mock_server)
        failures = _click_each_label_corner(page)
    finally:
        page.close()
        ctx.close()
    assert not failures, failures
    assert not errors, f"JS errors: {errors[:3]}"


_LABEL_RECTS = """(ids) => ids.map(id => {
  const r = document.getElementById(id).closest('label').getBoundingClientRect();
  return [r.left, r.top, r.right, r.bottom];
})"""

_STABLE_FRAMES = """async ([ids, n]) => {
  const rects = () => JSON.stringify(ids.map(id =>
    document.getElementById(id).closest('label').getBoundingClientRect()));
  const first = rects();
  for (let i = 0; i < n; i++) {
    await new Promise((ok) => requestAnimationFrame(ok));
    if (rects() !== first) return false;
  }
  return true;
}"""


_LATO_LOADED = """() => Array.from(document.fonts).some(
  (f) => f.family.replace(/["']/g, "") === "Lato" && f.status === "loaded")"""


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_a_late_webfont_swap_is_settled_before_the_label_click(
        mock_server, pw_browser, vp):
    """The flake made deterministic: every webfont response is held until the
    timeline rows exist, then released. _settle_layout must return only once
    the fonts are loaded and the labels have stopped moving, after which the
    corner click toggles every filter. RM-1072: the swap moved the labels
    7px (1920x920) / 10px (923x1280), past the 4px probe inset; the Replay
    body's fixed line-height (web/css/panels/primitives.css .replay-body)
    holds that move to 1px, under the inset, so a pre-swap point can no
    longer miss its label (test_replay_font_swap.py pins the cause).
    RM-1078: the face is the local stub (_webfont_stub.py), not the
    network Lato, so the swap is exercised on every host."""
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    held = []
    route_stub_webfont(page, lambda route: held.append(route))
    try:
        _load_match_rows(page, mock_server)
        assert held, (
            "premise: the page requested the webfont face (the dashboard.css "
            "Lato @import, answered by the stub CSS)"
        )
        assert page.evaluate("document.fonts.status") == "loading", (
            "premise: the webfont is still pending when the rows exist"
        )
        pre = page.evaluate(_LABEL_RECTS, list(_IDS))
        for route in held:
            fulfill_stub_font(route)
        status = _settle_layout(page)
        post = page.evaluate(_LABEL_RECTS, list(_IDS))
        # The reference settle is independent of the helper under test, so
        # a helper that returns early is measured, not skipped.
        page.wait_for_function("document.fonts.status === 'loaded'",
                               timeout=10_000)
        stable = page.evaluate(_STABLE_FRAMES, [list(_IDS), 10])
        final = page.evaluate(_LABEL_RECTS, list(_IDS))
        # A face that fails to load leaves the fallback in place: no swap,
        # so `moved` below would pass on any CSS. STUB_APPLIED also proves
        # the stub, not a fallback, draws 'Lato' text.
        loaded = page.evaluate(_LATO_LOADED)
        applied = page.evaluate(STUB_APPLIED)
        moved = max(abs(b[1] - a[1]) for a, b in zip(pre, final))
        failures = _click_each_label_corner(page)
    finally:
        page.close()
        ctx.close()
    assert loaded, "premise: the stub Lato face loaded once released"
    assert applied, "premise: the stub face, not a fallback, draws Lato text"
    assert status == "loaded", f"_settle_layout returned with fonts {status!r}"
    assert moved <= 1.0, (
        f"the webfont swap moved the filter labels {moved}px (RM-1072 "
        f"holds it to 1px): {pre} then {final}"
    )
    assert post == final, (
        f"_settle_layout returned before the swap re-laid the labels out: "
        f"{post} then {final}"
    )
    assert stable, "labels still moving after the fonts loaded"
    assert not failures, failures
    assert not errors, f"JS errors: {errors[:3]}"
