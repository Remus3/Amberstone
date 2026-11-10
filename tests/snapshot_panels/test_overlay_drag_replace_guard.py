"""
tests/snapshot_panels/test_overlay_drag_replace_guard.py
S144-U-285 (s144 uiux): in the overlay shell a widget being dragged stays
under the cursor when the page repaints or the window resizes mid-drag,
instead of the field's re-place pass snapping it back to its stored anchor.

THE DEFECT. Verifier NOTE (a) of S144-U-284, filed as a SHOULD-FIX in that
cycle's report. web/js/lib/overlay_layout.js re-places every widget through
_applyPos from three paths that had no drag guard: the body-wide
MutationObserver's debounced _placeAll (150 ms after ANY childList change on
the page - in a live game the panels repaint every tick), the game-family
observer's _placeAll, and the window resize handler. Only _watchTall's refit
(S144-U-284) skipped a widget carrying ovx-dragging. The drag tracks the
cursor by TOP with bottom cleared, and re-decides top vs bottom only on the
drop; _applyPos bottom-anchors a tall widget whose stored y is in the lower
half. So dragging the BUILD widget (w-build) down into the lower half and
holding it there while any panel repainted snapped it to the bottom corner,
away from the cursor, until the next pointer move dragged it back: the panel
flickered between two places for the whole drag. Measured headless before
the fix, sr 1920x1080: held at top 602 px, re-placed to top auto / bottom
16 px (rendered top 342, a 260 px jump) by a single body childList change,
by a resize event and by a mount swap; 3 of the 5 tests here failed.

The guard also follows the WIDGET, not the node, as defense in depth: the
drag already writes to a replacement mount (_installDrag _liveEl), but a
fresh node carries no ovx-dragging class, so a mount swapped mid-drag was
re-placed by _placeAll and by its new _watchTall ResizeObserver. No renderer
swaps a widget mount today (each registry mount is made once). The swap
here clones the node, inline style included, so it does not cover a fresh
node with no style yet (QA ledger FUTURE (l) of S144-U-285).

THE FIX (web/js/lib/overlay_layout.js). A module-level set of widget ids
being dragged (_dragIds, written by the drag's begin / end) and one
predicate, _midDrag(el, id), read by every re-place path: _placeAll and the
resize handler skip _applyPos for a dragged widget (the handle, hide menu,
hotkey hint and tall watcher still attach), and _watchTall's refit asks the
same predicate. The drop re-applies the position, as before.
"""
import pytest

from tests.snapshot_panels.test_overlay_build_refit_live import _run

_W = '.ovx-widget[data-ovx-id="w-build"]'
_MOUNT = "#view-active-match .am-pane-build"
_CALL = '.ovx-widget[data-ovx-id="w-call"]'

# Inline position + rendered box of the build mount, found by its registry
# selector (a replaced mount has no .ovx-widget class until the next place).
_STATE = """(sel) => {
  const w = document.querySelector(sel);
  if (!w) return null;
  const r = w.getBoundingClientRect();
  return {top: w.style.top, bottom: w.style.bottom, left: w.style.left,
          maxh: w.style.getPropertyValue('--ovx-maxh'),
          rtop: r.top, rleft: r.left,
          dragging: w.classList.contains('ovx-dragging')};
}"""

_FRAMES = """() => new Promise((r) => requestAnimationFrame(
  () => requestAnimationFrame(() => requestAnimationFrame(() => r()))))"""

# Positive control for the re-place paths: displace w-call (not dragged) by
# an inline top the layout never writes, so a re-place pass that ran is
# visible as w-call's top coming back.
_DISPLACE_CALL = """(sel) => {
  const c = document.querySelector(sel);
  c.style.top = '5px';
  return c.style.top;
}"""
_CALL_TOP = "(sel) => document.querySelector(sel).style.top"

# One childList change anywhere on the page: what every panel repaint is to
# the layout's body-wide observer.
_REPAINT = """() => {
  const d = document.createElement('div');
  d.className = 's144u285-repaint';
  document.body.appendChild(d);
  d.remove();
}"""

_RESIZE = "() => { window.dispatchEvent(new Event('resize')); }"

# A renderer swapping the build mount for a fresh node mid-drag: same markup,
# none of the layout's per-node marks (class, handle, wiring flags).
_SWAP = """(sel) => {
  const w = document.querySelector(sel);
  const n = w.cloneNode(true);
  n.classList.remove('ovx-dragging', 'ovx-widget');
  for (const h of n.querySelectorAll(':scope > .ovx-handle')) h.remove();
  delete n.dataset.ovxBodyDrag;
  delete n.dataset.ovxHideMenu;
  w.replaceWith(n);
  return document.querySelector(sel) === n;
}"""

_DY = 260  # sr w-build settles with its top near 340; +260 is lower half


def _px(v):
    assert v.endswith("px"), v
    return float(v[:-2])


def _grab_and_drag(page):
    """Press the w-build handle and drag it down into the lower half."""
    box = page.locator(_W + " > .ovx-handle").bounding_box()
    assert box, "w-build has no drag handle"
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    rest = page.evaluate(_STATE, _MOUNT)
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx + 20, cy + _DY, steps=8)
    page.evaluate(_FRAMES)
    return rest, (cx + 20, cy + _DY)


def _same_place(a, b):
    return (a["top"] == b["top"] and a["bottom"] == b["bottom"]
            and a["left"] == b["left"] and abs(a["rtop"] - b["rtop"]) < 0.5
            and abs(a["rleft"] - b["rleft"]) < 0.5)


def _held_act(page):
    """sr 1920x1080: drag w-build down, repaint, resize, then drop."""
    out = {}
    out["rest"], _ = _grab_and_drag(page)
    out["held"] = page.evaluate(_STATE, _MOUNT)

    out["call_before"] = page.evaluate(_CALL_TOP, _CALL)
    page.evaluate(_DISPLACE_CALL, _CALL)
    page.evaluate(_REPAINT)
    page.wait_for_timeout(400)  # the 150 ms body observer has run
    page.evaluate(_FRAMES)
    out["after_repaint"] = page.evaluate(_STATE, _MOUNT)
    out["call_after_repaint"] = page.evaluate(_CALL_TOP, _CALL)

    page.evaluate(_DISPLACE_CALL, _CALL)
    page.evaluate(_RESIZE)
    page.evaluate(_FRAMES)
    out["after_resize"] = page.evaluate(_STATE, _MOUNT)
    out["call_after_resize"] = page.evaluate(_CALL_TOP, _CALL)

    page.mouse.up()
    page.evaluate(_FRAMES)
    out["dropped"] = page.evaluate(_STATE, _MOUNT)
    return out


@pytest.fixture(scope="module")
def held():
    return {}


def _held_run(cache, mock_server, pw_browser):
    if "got" not in cache:
        cache["got"] = _run(mock_server, pw_browser, "sr", (1920, 1080), "",
                            False, _held_act)
    return cache["got"]


def test_the_drag_reaches_the_lower_half_tracking_by_top(
        held, mock_server, pw_browser):
    got = _held_run(held, mock_server, pw_browser)
    r, h = got["rest"], got["held"]
    # Anchors: at rest w-build is bottom-anchored; held, the drag tracks it by
    # top in the lower half - the case where _applyPos would bottom-anchor it.
    assert r["top"] == "auto" and r["bottom"] == "16px", r
    assert h["dragging"], h
    assert h["bottom"] == "auto", h
    assert _px(h["top"]) > 1080 * 0.5, h


def test_a_repaint_mid_drag_never_moves_the_dragged_widget(
        held, mock_server, pw_browser):
    got = _held_run(held, mock_server, pw_browser)
    # Positive control: the re-place pass DID run (w-call came back).
    assert got["call_after_repaint"] == got["call_before"] != "5px", got
    a, h = got["after_repaint"], got["held"]
    assert _same_place(a, h), (
        f"a repaint mid-drag re-placed w-build: held {h}, after {a}")
    assert a["maxh"] == h["maxh"], (h["maxh"], a["maxh"])


def test_a_resize_mid_drag_never_moves_the_dragged_widget(
        held, mock_server, pw_browser):
    got = _held_run(held, mock_server, pw_browser)
    assert got["call_after_resize"] == got["call_before"] != "5px", got
    a, h = got["after_resize"], got["held"]
    assert _same_place(a, h), (
        f"a resize mid-drag re-placed w-build: held {h}, after {a}")


def test_the_drop_still_re_anchors_the_widget(held, mock_server, pw_browser):
    got = _held_run(held, mock_server, pw_browser)
    d = got["dropped"]
    assert not d["dragging"], d
    assert d["top"] == "auto" and d["bottom"] == "16px", d


def test_a_mount_swapped_mid_drag_is_not_re_placed_and_keeps_tracking(
        mock_server, pw_browser):
    def act(page):
        out = {}
        _, (x, y) = _grab_and_drag(page)
        out["held"] = page.evaluate(_STATE, _MOUNT)
        out["swapped"] = page.evaluate(_SWAP, _MOUNT)
        page.wait_for_timeout(400)  # body observer + the new tall watcher
        page.evaluate(_FRAMES)
        out["after_swap"] = page.evaluate(_STATE, _MOUNT)
        out["classed"] = page.evaluate(
            "(sel) => document.querySelector(sel).classList"
            ".contains('ovx-widget')", _MOUNT)
        page.mouse.move(x, y + 12, steps=2)
        page.evaluate(_FRAMES)
        out["moved"] = page.evaluate(_STATE, _MOUNT)
        page.mouse.up()
        page.evaluate(_FRAMES)
        out["dropped"] = page.evaluate(_STATE, _MOUNT)
        return out
    got = _run(mock_server, pw_browser, "sr", (1920, 1080), "", False, act)
    assert got["swapped"], "the mount was not replaced; the case is moot"
    # Positive control: the place pass ran on the fresh node.
    assert got["classed"], "no place pass ran after the swap"
    h, a = got["held"], got["after_swap"]
    assert a["top"] == h["top"] and a["bottom"] == h["bottom"] == "auto", (
        f"the swapped mount was re-placed mid-drag: held {h}, after {a}")
    m = got["moved"]
    assert m["bottom"] == "auto" and abs(_px(m["top"]) - _px(h["top"]) - 12) < 1.5, (
        f"the drag stopped tracking the swapped mount: {h} -> {m}")
    d = got["dropped"]
    assert d["top"] == "auto" and d["bottom"] == "16px", d
