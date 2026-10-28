"""
tests/snapshot_panels/test_view_body_font_swap.py
Every dashboard view BODY (.view-section-body) keeps its layout when the
webfont swaps in, so the view content does not jump on first paint
(session 144, lane uiux, RM-1073; the RM-1011 class - that fix covered
the view heads, RM-1072 the Replay body alone).

The dashboard loads Lato from a Google Fonts @import with display=swap
(web/css/dashboard.css), so every view first paints in the fallback face
(web/css/panels/base.css font stack) and re-lays out when Lato arrives.
The body text of all 10 non-Replay views computed `line-height: normal`,
whose value is the FONT's own ascent + descent, and so did the body form
controls (the UA `font` on button / input resets it). Measured in headless
Chromium under /?ui_mock=1, Google Fonts blocked against Lato loaded, the
body content moved up to 23px (Lobby), 39px (Session), 35px (Settings)
and 32px (Build Insights) at 1920x920, and up to 48px at 923x1280.

The fix (web/css/panels/header.css) gives .view-section-body a unitless
`line-height: 1.2` (Lato's own normal value) and makes its form controls
inherit it at zero specificity. Measured after the fix against the real
Lato swap: no body box moves more than about 1px (1.1px, a Build
Insights segment chip) on any view, except the Active Match coach line's
inline span (2px, its own 31.9px line-height holds the line box) - and
the body heights are identical at both widths.

Rule pinned here, by layout value with the Google Fonts requests ABORTED
(no network dependence; the fallback face is the first-paint face), at
1920x920 and at the 923x1280 companion width, on all 11 views:
- no rendered text element or form control in a view body computes
  `line-height: normal`;
- each view body keeps its height when a face of a different normal
  line-height (`serif`) replaces the fallback (the swap, simulated with
  a local face; `monospace` is not used - its width wraps lines, a width
  question, not a line-height one).

Drive path: /?ui_mock=1#<view>, the recipe of test_view_head_font_swap.py,
plus a wait for the body height to stop changing (the ui_mock fixtures
render after their fetches resolve).
"""
import sys

import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page
from tests.snapshot_panels.test_view_head_font_swap import (
    _PROBE,
    _SETTLE,
    _VIEWS,
    _WINDOWS_FACES,
    _block_webfonts,
    _require_distinct_faces,
)

_FACES = (None, "serif")

_SWAP = """(face) => {
  let s = document.getElementById("s144u46-swap");
  if (!s) {
    s = document.createElement("style");
    s.id = "s144u46-swap";
    document.head.appendChild(s);
  }
  s.textContent = face
    ? ".view-section-body, .view-section-body * { font-family: "
      + face + " !important; }"
    : "";
}"""

# Resolves once the visible bodies' total height has held still for three
# 150ms samples (5s cap), so a late fixture render is not read as a swap.
_STABLE = """() => new Promise((ok) => {
  const height = () => Array.from(document.querySelectorAll(
    "section.view-section .view-section-body"))
    .reduce((n, b) => n + b.scrollHeight, 0);
  let last = -1, same = 0;
  const t0 = performance.now();
  const tick = () => {
    const h = height();
    same = h === last ? same + 1 : 0;
    last = h;
    if (same >= 3 || performance.now() - t0 > 5000) ok(h);
    else setTimeout(tick, 150);
  };
  tick();
})"""

_READ = """() => {
  const sec = Array.from(document.querySelectorAll("section.view-section"))
    .find((s) => getComputedStyle(s).display !== "none");
  if (!sec) return null;
  const bodies = Array.from(sec.querySelectorAll(".view-section-body"))
    .filter((b) => b.getBoundingClientRect().height > 0);
  const control = (el) => ["BUTTON", "INPUT", "SELECT", "TEXTAREA"]
    .includes(el.tagName);
  const text = [];
  for (const body of bodies) {
    for (const el of [body, ...body.querySelectorAll("*")]) {
      if (el.getBoundingClientRect().height === 0) continue;
      const own = Array.from(el.childNodes).some(
        (n) => n.nodeType === 3 && n.textContent.trim());
      if (!own && !control(el)) continue;
      text.push({
        el: el.tagName.toLowerCase() + (el.id ? "#" + el.id : "")
          + (typeof el.className === "string" && el.className.trim()
            ? "." + el.className.trim().split(/\\s+/).join(".") : ""),
        tag: el.tagName,
        lineHeight: getComputedStyle(el).lineHeight,
        height: el.getBoundingClientRect().height,
      });
    }
  }
  return {
    sec: sec.id,
    heights: bodies.map((b) => b.scrollHeight),
    text,
  };
}"""


@pytest.fixture(scope="module", params=VIEWPORTS,
                ids=lambda v: f"{v[0]}x{v[1]}")
def bodies(request, mock_server, pw_browser):
    ctx, page, errors = _new_page(pw_browser, mock_server, request.param)
    _block_webfonts(page)
    got: dict[str, dict] = {}
    try:
        for view in _VIEWS:
            page.goto(mock_server.url + "/?ui_mock=1#" + view,
                      wait_until="domcontentloaded", timeout=15_000)
            page.wait_for_function(
                f"document.body.dataset.view === '{view}'", timeout=10_000
            )
            page.evaluate(_SETTLE)
            page.evaluate(_STABLE)
            per_face = {}
            for face in _FACES:
                page.evaluate(_SWAP, face)
                page.evaluate(_SETTLE)
                per_face[face or "fallback"] = page.evaluate(_READ)
            page.evaluate(_SWAP, None)
            got[view] = per_face
        probe = {face: page.evaluate(_PROBE, face)
                 for face in ("sans-serif", "monospace", "serif")}
        yield got, probe, errors
    finally:
        page.close()
        ctx.close()


def test_every_view_body_is_measured(bodies):
    # Anchor: a hidden view or an empty body would pass every check below.
    got, _, errors = bodies
    assert sorted(got) == sorted(_VIEWS)
    for view, per_face in got.items():
        for face, r in per_face.items():
            assert r is not None and r["sec"] == "view-" + view, (view, r)
            assert r["heights"] and all(h > 0 for h in r["heights"]), (
                view, face, r["heights"])
            assert r["text"], (view, face, "no body text rendered")
    # The views with real fixture content carry many text lines.
    assert sum(len(p["fallback"]["text"]) for p in got.values()) >= 400
    assert errors == []


def test_no_view_body_text_computes_line_height_normal(bodies):
    got, _, _ = bodies
    # A drop-down <select> is exempt: Chromium computes `normal` for it
    # whatever the author rule says (measured, even an inline style). Its
    # height is pinned across faces in the swap test below instead.
    bad = [(view, face, t["el"])
           for view, per_face in got.items()
           for face, r in per_face.items()
           for t in r["text"]
           if t["lineHeight"] == "normal" and t["tag"] != "SELECT"]
    # `normal` is the pre-fix value: name every element still on it.
    assert not bad, (len(bad), bad[:12])


@pytest.mark.skipif(sys.platform != "win32", reason=_WINDOWS_FACES)
def test_the_swapped_faces_really_differ(bodies):
    _, probe, _ = bodies
    _require_distinct_faces(probe)


@pytest.mark.skipif(sys.platform != "win32", reason=_WINDOWS_FACES)
def test_view_bodies_keep_their_height_when_the_face_swaps(bodies):
    got, probe, _ = bodies
    _require_distinct_faces(probe)
    moved = {}
    for view, per_face in got.items():
        base = per_face["fallback"]["heights"]
        other = per_face["serif"]["heights"]
        assert len(base) == len(other), (view, base, other)
        if any(abs(a - b) > 1 for a, b in zip(base, other)):
            moved[view] = (base, other)
    assert not moved, moved


@pytest.mark.skipif(sys.platform != "win32", reason=_WINDOWS_FACES)
def test_view_body_selects_keep_their_height_when_the_face_swaps(bodies):
    got, probe, _ = bodies
    _require_distinct_faces(probe)
    seen = 0
    for view, per_face in got.items():
        sel = {f: [(t["el"], t["height"]) for t in r["text"]
                   if t["tag"] == "SELECT"]
               for f, r in per_face.items()}
        assert sel["fallback"] == sel["serif"], (view, sel)
        seen += len(sel["fallback"])
    # Anchor: History's 2 filters and Settings' selects render.
    assert seen >= 4, seen
