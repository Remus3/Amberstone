"""
tests/snapshot_panels/test_replay_font_swap.py
The Replay view body keeps its layout when the webfont swaps in, so the
match list, the meta line and the timeline filter labels do not jump on
first paint (session 144, lane uiux, RM-1072; the RM-1011 class, whose
fix covered only the view head).

The dashboard loads Lato from a Google Fonts @import with display=swap
(web/css/dashboard.css), so the Replay view can first paint in the
fallback face and re-lay out when Lato arrives. Its text used
`line-height: normal`, whose value is the FONT's own ascent + descent.
Measured in headless Chromium under /?ui_mock=1#replay with a match
loaded, Google Fonts blocked (the first-paint face) against Lato loaded:
match rows 68 -> 64px, #replay-meta 24 -> 22px per line, the timeline
rows' chips 21 -> 19px, and the three timeline filter labels moved up
7px at 1920x920 and 10px at 923x1280 - the move that made the RM-1071
label click flake.

The fix (web/css/panels/primitives.css .replay-body) gives the whole view
body a unitless `line-height: 1.2` (about Lato's own normal value); the row
buttons inherit it through `font: inherit`. Measured after the fix with
the fallback, `monospace` and `serif` faces forced onto the body: every
single-line text box is identical, and the filter labels move 1px at most.
That 1px is the meta row's baseline alignment (#replay-meta 18px beside
the 26px #replay-clock): the gap between two font sizes' baselines scales
with the face's ascent - descent, so it is face dependent by design of
`align-items: baseline`, not a line-height leak.

Rule pinned here, by layout value with the Google Fonts requests ABORTED
(no network dependence; the fallback face is the first-paint face), at
1920x920 and at the 923x1280 companion width:
- every Replay text element computes a resolved line-height, not
  `normal`, in every face, and each pure-text box is exactly a whole
  number of those lines;
- a single-line match row keeps its height whichever face renders it
  (a face wide enough to wrap the row's second line - `monospace` -
  is a width question, not a line-height one, and is excluded);
- the timeline filter labels and rows move at most 1px between faces,
  and the timeline rows keep their height.

Drive path and settle: _load_match_rows + _settle_layout of
test_replay_timeline_rows_and_grid_reach.py; the face swap and the
distinct-face premise are test_view_head_font_swap.py's.
"""
import sys

import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page
from tests.snapshot_panels.test_replay_timeline_rows_and_grid_reach import (
    _load_match_rows,
    _settle_layout,
)
from tests.snapshot_panels.test_view_head_font_swap import (
    _WINDOWS_FACES,
    _block_webfonts,
    _probe_faces,
    _require_distinct_faces,
)

_FACES = (None, "monospace", "serif")

_SWAP = """(face) => {
  let s = document.getElementById("s144u45-swap");
  if (!s) {
    s = document.createElement("style");
    s.id = "s144u45-swap";
    document.head.appendChild(s);
  }
  s.textContent = face
    ? "#replay-body, #replay-body * { font-family: "
      + face + " !important; }"
    : "";
}"""

# Text elements that must compute a resolved line-height.
_TEXT = (
    ".replay-list-head", ".replay-match-top", ".replay-match-bot",
    "#replay-meta", "#replay-clock", ".replay-events-title",
    ".replay-events-count", ".replay-events-filter", ".replay-events-label",
    ".replay-events-actor", ".replay-events-chip-text", ".replay-grid th",
)
# Of those, the ones whose border box is nothing but their line boxes (no
# padding, no min-height, no replaced child), so height = lines x lh.
_PURE = (
    ".replay-match-bot", "#replay-meta", "#replay-clock",
    ".replay-events-title", ".replay-events-label", ".replay-events-chip-text",
)

_READ = """([textSels, pureSels]) => {
  const pane = document.querySelector(".replay-main-pane");
  pane.scrollTop = 0;
  const top0 = pane.getBoundingClientRect().top;
  const shown = (sel) => Array.from(document.querySelectorAll(sel))
    .filter((el) => el.getBoundingClientRect().height > 0);
  const text = {};
  for (const sel of textSels) {
    text[sel] = shown(sel).map((el) => ({
      lineHeight: getComputedStyle(el).lineHeight,
      height: el.getBoundingClientRect().height,
      pure: pureSels.includes(sel),
    }));
  }
  // Lines counted from the text's own line fragments (distinct tops), so
  // the count does not depend on the line-height under test.
  const lines = (el) => {
    const range = document.createRange();
    range.selectNodeContents(el);
    return new Set(Array.from(range.getClientRects())
      .filter((r) => r.width > 0).map((r) => Math.round(r.top))).size;
  };
  const rows = shown("#replay-match-list .replay-match-row").map((row) => ({
    height: row.getBoundingClientRect().height,
    botLines: lines(row.querySelector(".replay-match-bot")),
  }));
  const tops = (sel) => shown(sel)
    .map((el) => el.getBoundingClientRect().top - top0);
  return {
    text,
    rows,
    filterTops: tops(".replay-events-filter"),
    eventTops: tops(".replay-events-row"),
    eventHeights: shown(".replay-events-row")
      .map((el) => el.getBoundingClientRect().height),
  };
}"""


@pytest.fixture(scope="module", params=VIEWPORTS,
                ids=lambda v: f"{v[0]}x{v[1]}")
def faces(request, mock_server, pw_browser):
    ctx, page, errors = _new_page(pw_browser, mock_server, request.param)
    _block_webfonts(page)
    try:
        _load_match_rows(page, mock_server)
        _settle_layout(page)
        per_face = {}
        for face in _FACES:
            page.evaluate(_SWAP, face)
            _settle_layout(page)
            per_face[face or "fallback"] = page.evaluate(
                _READ, [list(_TEXT), list(_PURE)]
            )
        page.evaluate(_SWAP, None)
        probe = _probe_faces(page)
        yield per_face, probe, errors
    finally:
        page.close()
        ctx.close()


def test_every_replay_text_element_is_measured(faces):
    # Anchor: an unloaded match or a hidden pane would pass every check.
    per_face, _, errors = faces
    for face, r in per_face.items():
        for sel in _TEXT:
            assert r["text"][sel], (face, sel, "not rendered")
        assert len(r["rows"]) >= 4, (face, r["rows"])
        assert len(r["filterTops"]) == 3, (face, r["filterTops"])
        assert len(r["eventTops"]) >= 10, (face, len(r["eventTops"]))
    assert errors == []


@pytest.mark.skipif(sys.platform != "win32", reason=_WINDOWS_FACES)
def test_the_swapped_faces_really_differ(faces):
    _, probe, _ = faces
    _require_distinct_faces(probe)


def test_replay_text_computes_a_resolved_line_height(faces):
    per_face, _, _ = faces
    for face, r in per_face.items():
        for sel, items in r["text"].items():
            for t in items:
                # `normal` is the pre-fix value: fail on it by name.
                assert t["lineHeight"] != "normal", (face, sel, t)
                if not t["pure"]:
                    continue
                lh = float(t["lineHeight"].removesuffix("px"))
                lines = round(t["height"] / lh)
                assert lines >= 1 and abs(t["height"] - lines * lh) <= 0.5, (
                    face, sel, t)


@pytest.mark.skipif(sys.platform != "win32", reason=_WINDOWS_FACES)
def test_single_line_match_rows_keep_their_height_across_faces(faces):
    per_face, probe, _ = faces
    _require_distinct_faces(probe)
    base = [r["height"] for r in per_face["fallback"]["rows"]
            if r["botLines"] == 1]
    # Anchor: the fixture's rows are one-line rows in the fallback face.
    assert len(base) >= 4, per_face["fallback"]["rows"]
    compared = 0
    for face, r in per_face.items():
        for row in r["rows"]:
            if row["botLines"] != 1:
                continue
            compared += 1
            assert abs(row["height"] - base[0]) <= 0.5, (face, row, base)
    # fallback + serif rows at least; monospace wraps (a width question).
    assert compared >= 8, compared


@pytest.mark.skipif(sys.platform != "win32", reason=_WINDOWS_FACES)
def test_timeline_labels_and_rows_hold_still_across_faces(faces):
    per_face, probe, _ = faces
    _require_distinct_faces(probe)
    ref = per_face["fallback"]
    for face, r in per_face.items():
        assert len(r["filterTops"]) == len(ref["filterTops"]) == 3, face
        assert len(r["eventTops"]) == len(ref["eventTops"]) >= 10, face
        # 1px: the meta row's baseline alignment (module docstring).
        for got, want in zip(r["filterTops"], ref["filterTops"]):
            assert abs(got - want) <= 1.0, (face, r["filterTops"],
                                            ref["filterTops"])
        for got, want in zip(r["eventTops"], ref["eventTops"]):
            assert abs(got - want) <= 1.0, (face, r["eventTops"][:3],
                                            ref["eventTops"][:3])
        assert r["eventHeights"] == ref["eventHeights"], face
