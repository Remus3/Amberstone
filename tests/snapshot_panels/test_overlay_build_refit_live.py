"""
tests/snapshot_panels/test_overlay_build_refit_live.py
S144-U-284 (s144 uiux): in the overlay shell the bottom-anchored BUILD
widget (w-build) re-runs its fit in the SAME frame its content changes, and
whenever a row grows or the Coach Call widget (w-call) above it resizes,
instead of only through the layout observer's 150 ms re-place.

THE DEFECT. QA ledger FUTURE (k) of S144-U-283. S144-U-283 caps the grown
w-build under w-call (TALL_FLOOR_GAP) and drops trailing sections whole
(_fitDropGroups), but both ran only inside _applyPos, and _applyPos ran
only on load, resize, drag-drop and the body-wide MutationObserver's
debounced _placeAll, 150 ms after a childList change. So:
  - a REBUILT build body (active_match.js clears it with innerHTML = ""
    and appends fresh nodes that carry data-ovx-drop but not the
    data-ovx-dropped mark) painted every section, the trailing one sliced
    by the clip, for up to 150 ms before the drop landed;
  - a row that GROWS with no childList change (a late image without fixed
    dimensions, a font swap, a class toggle) ran no fit at all: the clip
    sliced the trailing section until the next unrelated re-render;
  - a w-call that grows (its own renderer, or a style change) moved no
    floor: w-build kept its old cap and ran into the call widget.

THE FIX (web/js/lib/overlay_layout.js _watchTall). Each tall widget gets a
MutationObserver on its own subtree (childList), whose microtask refit runs
before the next frame paints, and a ResizeObserver on the widget, its rows
and the primary widgets, whose refit runs on the next animation frame
(never inside the observer callback, so the fit's own size changes cannot
raise a ResizeObserver loop error). A refit is skipped while the widget is
being dragged; the drop re-applies it.

The DEFENSE / COUNTER payloads are the S144-U-283 ones (real producer
output), injected with page.route on the build pane's two POSTs.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_overlay_build_grown_fit import (
    _BUILD_PLAN,
    _DS_PREVIEW,
    _READ,
)

_W = '.ovx-widget[data-ovx-id="w-build"]'
_SHEET = "*, *::before, *::after { transition: none !important; }"
_GROUPS = ("DEFENSE", "COUNTER", "THREATS")

# Waits into the third animation frame: a ResizeObserver notices a size
# change after layout in frame 1 (which paints unfitted), the refit runs in a
# frame-2 rAF queued from that callback, so frame 2 paints fitted. A frame-2
# rAF queued by the test itself runs BEFORE the refit's, so the read waits
# for a frame-3 rAF.
_TWO_FRAMES = """() => new Promise((r) => requestAnimationFrame(
  () => requestAnimationFrame(() => requestAnimationFrame(() => r()))))"""

# A rebuilt build body: the same markup, written back through innerHTML
# without the data-ovx-dropped marks, then read in the NEXT frame's rAF -
# the last script point before that frame paints. The 150 ms layout
# observer cannot have run yet.
_REBUILD = """(wsel) => new Promise((resolve) => {
  const b = document.querySelector(wsel + ' #am-build-body');
  const before = b.querySelectorAll('[data-ovx-dropped]').length;
  b.innerHTML = b.innerHTML.replace(/ data-ovx-dropped=""/g, '');
  requestAnimationFrame(() => resolve(before));
})"""


def _fulfil_with(body):
    def handler(route, _request):
        route.fulfill(status=200, content_type="application/json", body=body)
    return handler


def _run(mock_server, pw_browser, mode, vp, query, grown, act):
    """Load the overlay, let it settle, run act(page) and return its read."""
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vp[0], "height": vp[1]})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    if grown:
        # String-glob matchers, one call each (RM-1506: a name the guard
        # cannot prove is a string reads as a callable matcher).
        page.route("**/api/ds-preview", _fulfil_with(json.dumps(_DS_PREVIEW)))
        page.route("**/api/build-plan", _fulfil_with(json.dumps(_BUILD_PLAN)))
    want = list(_GROUPS) if grown else ["THREATS"]
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&mode={mode}&overlay=1{query}",
            wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "() => document.body.dataset.shell === 'overlay'"
            " && document.body.classList.contains('ovx-ready')",
            timeout=10_000)
        page.wait_for_function(
            """([wsel, want]) => {
              const b = document.querySelector(wsel + ' #am-build-body');
              if (!b) return false;
              const t = [...b.children].map(
                (k) => (k.textContent || '').trim());
              return want.every((g) => t.some((s) => s.startsWith(g)));
            }""", arg=[_W, want], timeout=20_000)
        page.add_style_tag(content=_SHEET)
        # Settled: the 150 ms layout observer has re-placed the field.
        page.wait_for_timeout(500)
        got = act(page)
        # A ResizeObserver loop error surfaces on window.onerror, not as an
        # exception; collect it too.
        loop_err = page.evaluate("() => window.__roErr || null")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert not loop_err, loop_err
    assert got, "w-build is not on the page"
    return got


def _arm_error_trap(page):
    page.evaluate("""() => { window.__roErr = null;
      window.addEventListener('error', (e) => {
        window.__roErr = String(e.message || e); }); }""")


def _inside(clip, b):
    return (b["left"] >= clip["left"] - 0.5
            and b["right"] <= clip["right"] + 0.5
            and b["top"] >= clip["top"] - 0.5
            and b["bottom"] <= clip["bottom"] + 0.5)


def _cut(got):
    return [f"{k['cls'] or k['text']!r} {k['box']['top']:.0f}-"
            f"{k['box']['bottom']:.0f}"
            for k in got["shown"] if not _inside(got["clip"], k["box"])]


def _whole(got):
    split = []
    for g, s in got["groups"].items():
        if s["eyebrow"] != s["strip"]:
            split.append(f"{g} {s}")
    return split


# ---- 1. a rebuilt body is refitted before the next frame paints ----------

_REBUILD_CASES = [
    ("sr", (1920, 1080), ""),
    ("aram", (1920, 1080), ""),
    ("mayhem", (1920, 1080), ""),
    ("arena", (1920, 1080), ""),
    ("sr", (2560, 1440), "&ovscale=1.333"),
]


@pytest.fixture(scope="module")
def rebuilt():
    return {}


def _get_rebuilt(rebuilt, mock_server, pw_browser, case):
    if case not in rebuilt:
        mode, vp, query = case

        def act(page):
            _arm_error_trap(page)
            before = page.evaluate(_REBUILD, _W)
            got = page.evaluate(_READ, _W)
            got["before"] = before
            return got
        rebuilt[case] = _run(mock_server, pw_browser, mode, vp, query,
                             True, act)
    return rebuilt[case]


@pytest.mark.parametrize("case", _REBUILD_CASES,
                         ids=[f"{m}-{v[0]}x{v[1]}" for m, v, _ in
                              _REBUILD_CASES])
def test_a_rebuilt_body_paints_its_first_frame_already_fitted(
        case, rebuilt, mock_server, pw_browser):
    got = _get_rebuilt(rebuilt, mock_server, pw_browser, case)
    # Anchor: the settled fit had dropped something, so the rebuild really
    # brought back an overflowing section for the observer to drop again.
    assert got["before"] >= 1, f"{case[0]}: nothing was dropped to begin with"
    cut = _cut(got)
    assert not cut, (f"{case[0]} {case[1]}: first frame after a rebuild, cut"
                     f" at clip bottom {got['clip']['bottom']:.0f}: "
                     + "; ".join(cut))
    assert not _whole(got), _whole(got)
    assert got["module"] and _inside(got["clip"], got["module"]), got["module"]


# ---- 2. a row that grows with no DOM change is refitted ------------------

# The rerank module grows through a style change alone (no childList
# mutation), then shrinks back: THREATS is dropped whole, then comes back.
# Plain fixtures: THREATS shows when settled (S144-U-282). The grow is
# sized past each mode's free room under w-call (sr about 10 px, arena about
# 89 px, measured at 1920x1080) and below what dropping THREATS frees.
_GROW_PX = {"sr": 60, "arena": 140}
_GROW_CASES = list(_GROW_PX)

_GROW = """async ([wsel, px]) => {
  const w = document.querySelector(wsel);
  const mod = w.querySelector('.bm-module');
  mod.style.paddingBottom = px + 'px';
  await (__FRAMES__)();
  return true;
}""".replace("__FRAMES__", _TWO_FRAMES)


@pytest.fixture(scope="module")
def grew():
    return {}


def _get_grew(grew, mock_server, pw_browser, mode):
    if mode not in grew:
        def act(page):
            _arm_error_trap(page)
            settled = page.evaluate(_READ, _W)
            page.evaluate(_GROW, [_W, _GROW_PX[mode]])
            grown = page.evaluate(_READ, _W)
            page.evaluate(_GROW, [_W, 0])
            back = page.evaluate(_READ, _W)
            return {"settled": settled, "grown": grown, "back": back}
        grew[mode] = _run(mock_server, pw_browser, mode, (1920, 1080), "",
                          False, act)
    return grew[mode]


@pytest.mark.parametrize("mode", _GROW_CASES)
def test_a_grown_row_drops_the_trailing_section_whole(
        mode, grew, mock_server, pw_browser):
    got = _get_grew(grew, mock_server, pw_browser, mode)
    assert got["settled"]["groups"]["THREATS"]["eyebrow"], (
        f"{mode}: THREATS was not shown before the grow; the case is moot")
    g = got["grown"]
    cut = _cut(g)
    assert not cut, (f"{mode}: after a {_GROW_PX[mode]} px row grow, cut at clip bottom"
                     f" {g['clip']['bottom']:.0f}: " + "; ".join(cut))
    assert not _whole(g), _whole(g)
    assert not g["groups"]["THREATS"]["eyebrow"], (
        f"{mode}: the grow did not overflow, so nothing was refitted")


@pytest.mark.parametrize("mode", _GROW_CASES)
def test_a_shrunk_row_brings_the_section_back(
        mode, grew, mock_server, pw_browser):
    got = _get_grew(grew, mock_server, pw_browser, mode)
    b = got["back"]
    assert b["groups"]["THREATS"]["eyebrow"], (
        f"{mode}: THREATS did not come back once the row shrank")
    assert not _cut(b), _cut(b)


# ---- 3. a w-call that grows moves the floor ------------------------------

_CALL_GROW = """async ([px]) => {
  const c = document.querySelector('.ovx-widget[data-ovx-id="w-call"]');
  const pad = parseFloat(getComputedStyle(c).paddingBottom) || 0;
  c.style.paddingBottom = (pad + px) + 'px';
  await (__FRAMES__)();
  return true;
}""".replace("__FRAMES__", _TWO_FRAMES)


# Each grow takes w-call's bottom past w-build's settled top minus the gap
# (sr: call bottom 320 vs build top 342; aram: 305 vs 463).
_CALL_GROW_PX = {"sr": 60, "aram": 160}


@pytest.mark.parametrize("mode", list(_CALL_GROW_PX))
def test_a_grown_call_widget_moves_the_build_floor(
        mode, mock_server, pw_browser):
    def act(page):
        _arm_error_trap(page)
        settled = page.evaluate(_READ, _W)
        page.evaluate(_CALL_GROW, [_CALL_GROW_PX[mode]])
        return {"settled": settled, "after": page.evaluate(_READ, _W)}
    got = _run(mock_server, pw_browser, mode, (1920, 1080), "", False, act)
    s, a = got["settled"], got["after"]
    assert a["call"] and s["call"], "w-call is not visible"
    assert (a["call"]["bottom"] - s["call"]["bottom"]
            >= _CALL_GROW_PX[mode] - 1), (
        "w-call did not grow; the case is moot", s["call"], a["call"])
    # Anchor: the grown call really reaches into the settled build box.
    assert a["call"]["bottom"] + 12 * a["z"] > s["wbox"]["top"], (
        "the grown w-call does not reach w-build; the case is moot")
    gap = a["wbox"]["top"] - a["call"]["bottom"]
    assert gap >= 12 * a["z"] - 1.0, (
        f"{mode}: w-build top {a['wbox']['top']:.0f} vs grown w-call bottom"
        f" {a['call']['bottom']:.0f} (gap {gap:.0f})")
    assert not _cut(a), _cut(a)
    assert not _whole(a), _whole(a)


# ---- 4. a drag in progress is never snapped back --------------------------

_DRAG_REBUILD = """(wsel) => new Promise((resolve) => {
  const w = document.querySelector(wsel);
  w.classList.add('ovx-dragging');
  w.style.bottom = 'auto';
  w.style.top = '300px';
  const b = w.querySelector('#am-build-body');
  b.innerHTML = b.innerHTML.replace(/ data-ovx-dropped=""/g, '');
  b.firstElementChild.style.paddingBottom = '30px';
  requestAnimationFrame(() => requestAnimationFrame(() => resolve(
    {top: w.style.top, bottom: w.style.bottom})));
})"""


def test_a_refit_never_moves_a_widget_mid_drag(mock_server, pw_browser):
    def act(page):
        _arm_error_trap(page)
        return page.evaluate(_DRAG_REBUILD, _W)
    got = _run(mock_server, pw_browser, "sr", (1920, 1080), "", True, act)
    assert got == {"top": "300px", "bottom": "auto"}, got
