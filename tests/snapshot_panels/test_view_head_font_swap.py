"""
tests/snapshot_panels/test_view_head_font_swap.py
The page head of every dashboard view (.view-section-head) keeps its height
when the webfont swaps in, so the view does not jump on first paint
(session 144, lane uiux, RM-1011).

The dashboard loads Lato from a Google Fonts @import with display=swap
(web/css/dashboard.css), so every view first paints in the fallback face
and re-lays out when Lato arrives. The head's h2 and .view-section-sub
used `line-height: normal`, whose value is the FONT's own ascent + descent.
Measured in headless Chromium at 1920x920 under /?ui_mock=1: with the
Google Fonts requests blocked (the first-paint face) the h2 box was 39px,
the sub-line 24px and the head 44px (History 52px); with Lato loaded they
were 35 / 22 / 40px (History 50px). RM-1006 and RM-1008 both read that
4px jump as a transient scroll on the Lobby and User Builds views.

The fix (web/css/panels/header.css) gives the head a unitless
`line-height: 1.2` (Lato's own normal value, so the settled head reads
39.8px against 40), makes head buttons inherit it (the UA button `font`
resets line-height to `normal`), and centres .view-section-tabs like
.hpgr-back already was: baseline-aligning the 29px title with 16px tab
text depends on the face's ascent / descent, which still moved the History
head 1px. Measured after the fix with Lato blocked against Lato loaded:
all 11 heads identical at 1920 (History settles at 47px, was 50), and 8 of
11 at 923. The other 3 (User Builds, Build Insights, archive Post Game
Review) wrap their sub-line to two lines at 923 and still move 1px
(60.2 / 59.2px): a wrapped line's depth below the shared baseline is face
dependent. Filed as RM-1015.

Rule pinned here, by layout value with the Google Fonts requests ABORTED
(no network dependence; the fallback face is the first-paint face), at
1920x920 and at the 923x1280 companion width, on all 11 views:
- a single-line head keeps its height whichever face renders it: the
  cascade fallback, then `monospace`, then `serif` forced onto the head
  (the swap, simulated with local faces whose normal line-heights differ;
  the probe test proves they differ on this machine, and skips where they
  do not); all 11 heads are single-line at 1920, 8 at 923;
- the h2 and the sub-line compute a resolved line-height, not `normal`,
  and every line box is exactly that line-height in every face;
- at 1920 wide the first-paint head of a view without a 42px control is
  the 40px settled head (it was 44px).

Drive path: /?ui_mock=1#<view>, the recipe of the per-view snapshot tests,
landing on body[data-view], then the settle wait of
test_user_builds_fit.py.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_VIEWPORTS = {
    "baseline": {"width": 1920, "height": 920},
    "companion": {"width": 923, "height": 1280},
}

_VIEWS = (
    "lobby", "champ-select", "session", "history", "user-builds",
    "build-insights", "settings", "replay", "last-match", "historical-pgr",
    "active-match",
)

# Views whose head carries a 42px control (tabs / back button) that sets
# the head height instead of the text line.
_CONTROL_HEADS = {"history", "historical-pgr"}

_FACES = (None, "monospace", "serif")

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)

_SWAP = """(face) => {
  let s = document.getElementById("s144u22-swap");
  if (!s) {
    s = document.createElement("style");
    s.id = "s144u22-swap";
    document.head.appendChild(s);
  }
  s.textContent = face
    ? ".view-section-head, .view-section-head * { font-family: "
      + face + " !important; }"
    : "";
}"""

_READ = """() => {
  const sec = Array.from(document.querySelectorAll("section.view-section"))
    .find((s) => getComputedStyle(s).display !== "none");
  if (!sec) return null;
  const head = sec.querySelector(".view-section-head");
  const h = (el) => el.getBoundingClientRect().height;
  const text = Array.from(head.querySelectorAll("h2, .view-section-sub"))
    .filter((el) => getComputedStyle(el).display !== "none")
    .map((el) => ({
      tag: el.tagName + (el.className ? "." + el.className : ""),
      lineHeight: getComputedStyle(el).lineHeight,
      height: h(el),
    }));
  return {sec: sec.id, head: h(head), text};
}"""

_PROBE = """(face) => {
  const d = document.createElement("span");
  d.textContent = "Xg";
  d.style.cssText = "position:absolute;font-size:29px;line-height:normal;"
    + "font-family:" + face;
  document.body.appendChild(d);
  const px = d.getBoundingClientRect().height;
  d.remove();
  return px;
}"""


def _block_webfonts(page):
    page.route("**/fonts.googleapis.com/**", lambda route: route.abort())
    page.route("**/fonts.gstatic.com/**", lambda route: route.abort())


@pytest.fixture(scope="module", params=sorted(_VIEWPORTS))
def heads(request, mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport=_VIEWPORTS[request.param]
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    _block_webfonts(page)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    got: dict[str, dict] = {}
    probe: dict = {}
    try:
        for view in _VIEWS:
            page.goto(mock_server.url + "/?ui_mock=1#" + view,
                      wait_until="domcontentloaded", timeout=15_000)
            page.wait_for_function(
                f"document.body.dataset.view === '{view}'", timeout=10_000
            )
            page.evaluate(_SETTLE)
            per_face = {}
            for face in _FACES:
                page.evaluate(_SWAP, face)
                page.evaluate(_SETTLE)
                per_face[face or "fallback"] = page.evaluate(_READ)
            page.evaluate(_SWAP, None)
            got[view] = per_face
        probe = {face: page.evaluate(_PROBE, face)
                 for face in ("sans-serif", "monospace", "serif")}
        yield request.param, got, probe, errors
    finally:
        page.close()
        ctx.close()


def test_every_view_head_is_measured(heads):
    # Anchor: a hidden view or an empty head would pass every check below.
    _, got, _, errors = heads
    assert sorted(got) == sorted(_VIEWS)
    for view, per_face in got.items():
        r = per_face["fallback"]
        assert r is not None and r["sec"] == "view-" + view, (view, r)
        assert r["head"] > 0, (view, r)
        assert any(t["tag"] == "H2" for t in r["text"]), (view, r)
    assert errors == []


def test_the_swapped_faces_really_differ(heads):
    # Without two faces of different normal line-height the swap check
    # below compares a face with itself and passes on any CSS.
    _, _, probe, _ = heads
    if len(set(probe.values())) < 2:
        pytest.skip(f"local faces share one normal line-height: {probe}")


def _lines(t):
    # `normal` is the pre-fix value: fail on it by name, not on float().
    assert t["lineHeight"] != "normal", ("line-height is normal", t)
    return round(t["height"] / float(t["lineHeight"].removesuffix("px")))


def test_single_line_view_heads_do_not_change_height_with_the_face(heads):
    vp, got, probe, _ = heads
    if len(set(probe.values())) < 2:
        pytest.skip(f"local faces share one normal line-height: {probe}")
    compared = []
    for view, per_face in got.items():
        # A sub-line that wraps (the RM-975 companion-width wrap, or a wide
        # face) sits a face-dependent depth below the shared baseline: the
        # measured 1px residual filed as RM-1015. Single-line heads only.
        if any(_lines(t) != 1 for r in per_face.values() for t in r["text"]):
            continue
        compared.append(view)
        base = per_face["fallback"]["head"]
        for face, r in per_face.items():
            assert abs(r["head"] - base) <= 0.5, (view, face, per_face)
    # Anchor: every head is one line at 1920; at 923 the three long
    # sub-lines wrap (User Builds, Build Insights, archive Post Game Review).
    assert len(compared) == (len(_VIEWS) if vp == "baseline" else 8), compared


def test_view_head_text_lines_compute_a_resolved_line_height(heads):
    _, got, _, _ = heads
    for view, per_face in got.items():
        for face, r in per_face.items():
            for t in r["text"]:
                assert t["lineHeight"] != "normal", (view, face, t)
                # Each line box is exactly the line-height, whatever the face.
                lh = float(t["lineHeight"].removesuffix("px"))
                assert abs(t["height"] - _lines(t) * lh) <= 0.5, (view, face, t)


def test_first_paint_head_is_the_settled_40px_head(heads):
    vp, got, _, _ = heads
    if vp != "baseline":
        pytest.skip("the 40px figure is the 1920x920 baseline measurement")
    for view, per_face in got.items():
        if view in _CONTROL_HEADS:
            continue
        r = per_face["fallback"]
        assert abs(r["head"] - 40) <= 0.5, (view, r)
