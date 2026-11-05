"""
tests/snapshot_panels/test_view_label_prefix_gives_way.py
RM-1436 (s144 uiux) - in a narrow window the header's current-view label
drops its "AUTO" prefix before it cuts the view name.

THE DEFECT. MEASURED in headless Chromium under /?ui_mock=1&mode=sr before
the fix. The label (#view-current-label, web/index.html) is pinned to 230 px
so the view trigger never changes size between views (s218); since
RM-1432 it may shrink below that when the header row is narrower. At
320x256 it is 115 px, and the auto-mode text "AUTO <dot> <VIEW>" (one text
node, web/js/main.js _viewUpdateTitleLabel) spent about half of that on the
prefix: PRE-GAME LOBBY ran 185 px in a 115 px box, POST GAME REVIEW 202 px,
ACTIVE MATCH 168 px, so the label read "AUTO <dot> PRE-G..." and the one
word that names the view was the part cut.

THE FIX.
- web/js/main.js writes the prefix and the name as two spans
  (.title-current-auto, .title-current-name); the label's textContent, and
  so the trigger's accessible name, is unchanged.
- web/css/panels/header.css, @media (max-width: 720px): the label is a
  one-line wrapping flex row whose first line holds the name; when the pair
  does not fit, the whole prefix wraps to the clipped second line (never a
  partial "AU"), and a name wider than the label alone ellipsizes inside the
  whole label.

What is checked, per character (Range rects, so the same probe reads the
one-text-node label at HEAD and the two-span label after the fix), on Home,
Pre-Game Lobby, Post Game Review and SR Active Match:
- at 320x256: the prefix is shown whole or not at all, a cut name never sits
  beside a visible prefix, and the name starts at the label's left edge;
- at 768 / 640 / 480 and at the 1920x920 / 923x1280 baselines, where the
  pair fits, both are shown whole, in order, on one line (nothing moved);
- the label stays one line and the trigger keeps its height everywhere;
- with a manual pick (no prefix) the name keeps the whole label.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import _new_page

_VIEWS = {
    "home": "HOME",
    "lobby": "PRE-GAME LOBBY",
    "last-match": "POST GAME REVIEW",
    "active-match": "ACTIVE MATCH",
}
_PREFIX = "AUTO " + chr(0xB7) + " "  # the middle dot, kept ASCII in source
_FITS = [(1920, 920), (923, 1280), (768, 368), (640, 307), (480, 230)]
_TIGHT = [(320, 256)]

_PROBE = """
(prefixLen) => {
  const l = document.getElementById('view-current-label');
  const L = l.getBoundingClientRect();
  const walker = document.createTreeWalker(l, NodeFilter.SHOW_TEXT);
  const chars = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    for (let i = 0; i < n.data.length; i++) {
      const r = document.createRange();
      r.setStart(n, i);
      r.setEnd(n, i + 1);
      const b = r.getBoundingClientRect();
      chars.push({c: n.data[i], l: b.left, r: b.right, t: b.top, b: b.bottom, w: b.width});
    }
  }
  // Horizontal: the whole glyph box. Vertical: its centre, because a glyph
  // from a fallback font (the middle dot) reports a taller box than the
  // line; a character wrapped to the clipped second line has its centre
  // a whole line below.
  const vis = (k) => k.w > 0 && k.l >= L.left - 0.5 && k.r <= L.right + 0.5
    && (k.t + k.b) / 2 >= L.top && (k.t + k.b) / 2 <= L.bottom;
  const solid = (arr) => arr.filter((k) => k.c.trim());
  const pre = solid(chars.slice(0, prefixLen));
  const name = solid(chars.slice(prefixLen));
  const nameEl = l.querySelector('.title-current-name');
  const nameCut = name.some((k) => !vis(k))
    || (nameEl ? nameEl.scrollWidth > nameEl.clientWidth + 1 : false);
  const tr = document.getElementById('view-trigger').getBoundingClientRect();
  const firstVis = chars.find((k) => k.c.trim() && vis(k));
  return {
    text: l.textContent,
    labelW: Math.round(L.width), labelH: Math.round(L.height),
    triggerH: Math.round(tr.height),
    preShown: pre.filter(vis).length, preLen: pre.length,
    nameShown: name.filter(vis).length, nameLen: name.length, nameCut,
    // From the label's CONTENT edge (it carries a 1 px rule + 10 px pad).
    firstLeft: firstVis ? Math.round(firstVis.l - L.left - l.clientLeft
      - parseFloat(getComputedStyle(l).paddingLeft)) : null,
    firstChar: firstVis ? firstVis.c : null,
    // Spread of the shown glyphs' centres: one line is a few px at most.
    spread: (() => { const c = chars.filter((k) => k.c.trim() && vis(k))
      .map((k) => (k.t + k.b) / 2);
      return c.length ? Math.round(Math.max(...c) - Math.min(...c)) : 0; })(),
  };
}
"""


def _open(pw_browser, mock_server, vp, view, manual=False):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    start = "home" if manual else view
    page.goto(f"{mock_server.url}/?ui_mock=1&mode=sr#{start}",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_selector("#view-trigger", state="visible", timeout=10_000)
    page.wait_for_function(
        "(want) => document.getElementById('view-current-label').textContent"
        ".trim().endsWith(want)", arg=_VIEWS[start], timeout=10_000)
    if manual:
        # A real menu pick from Home (the click handler saves the manual
        # view; the label is rewritten on the view change).
        page.click("#view-trigger")
        page.click(f".view-menu-item[data-view='{view}']")
        page.wait_for_function(
            "(want) => document.getElementById('view-current-label').textContent"
            " === want", arg=_VIEWS[view], timeout=10_000)
    page.wait_for_timeout(200)
    return ctx, page, errors


def _probe(pw_browser, mock_server, vp, view, manual=False):
    ctx, page, errors = _open(pw_browser, mock_server, vp, view, manual)
    try:
        st = page.evaluate(_PROBE, 0 if manual else len(_PREFIX))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
    return st


def _one_line(st, label):
    assert st["labelH"] <= 20 and st["spread"] <= 4, (
        f"{label}: the label is not one line: {st}")
    assert st["triggerH"] == 43, f"{label}: the trigger height moved: {st}"


@pytest.mark.parametrize("view", list(_VIEWS))
@pytest.mark.parametrize("vp", _TIGHT, ids=lambda v: f"{v[0]}x{v[1]}")
def test_prefix_gives_way_before_the_name(mock_server, pw_browser, vp, view):
    st = _probe(pw_browser, mock_server, vp, view)
    label = f"{view} {vp}"
    assert st["text"] == _PREFIX + _VIEWS[view], f"{label}: text changed: {st}"
    assert st["labelW"] < 200, f"anchor: {label}: the label is not cut down: {st}"
    assert st["preShown"] in (0, st["preLen"]), (
        f"{label}: the AUTO prefix is cut part way: {st}")
    if st["nameCut"]:
        assert st["preShown"] == 0, (
            f"{label}: the view name is cut while the AUTO prefix still shows: {st}")
    if st["preShown"] == 0:
        assert st["firstChar"] == _VIEWS[view][0] and st["firstLeft"] <= 1, (
            f"{label}: with the prefix gone the name does not start the label: {st}")
    assert st["nameShown"] >= min(st["nameLen"], 6), (
        f"{label}: under 6 letters of the view name show: {st}")
    _one_line(st, label)


@pytest.mark.parametrize("view", list(_VIEWS))
@pytest.mark.parametrize("vp", _FITS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_both_show_whole_where_they_fit(mock_server, pw_browser, vp, view):
    st = _probe(pw_browser, mock_server, vp, view)
    label = f"{view} {vp}"
    assert st["text"] == _PREFIX + _VIEWS[view], f"{label}: text changed: {st}"
    assert st["preShown"] == st["preLen"] and not st["nameCut"], (
        f"{label}: the prefix or the name is cut where both fit: {st}")
    assert st["firstChar"] == "A" and st["firstLeft"] <= 1, (
        f"{label}: the label does not read AUTO first: {st}")
    _one_line(st, label)


@pytest.mark.parametrize("view", ["lobby", "last-match"])
@pytest.mark.parametrize("vp", [(320, 256), (1920, 920)], ids=lambda v: f"{v[0]}x{v[1]}")
def test_a_manual_pick_gives_the_name_the_whole_label(mock_server, pw_browser, vp, view):
    st = _probe(pw_browser, mock_server, vp, view, manual=True)
    label = f"manual {view} {vp}"
    assert st["text"] == _VIEWS[view], f"anchor: {label}: not a manual label: {st}"
    assert st["firstChar"] == _VIEWS[view][0] and st["firstLeft"] <= 1, (
        f"{label}: the name does not start the label: {st}")
    if vp[0] == 1920:
        assert not st["nameCut"], f"{label}: the name is cut at the baseline: {st}"
    _one_line(st, label)
