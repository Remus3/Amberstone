"""
tests/snapshot_panels/test_replay_narrow_reflow.py
At 720 px and under (300% zoom of the 1920x920 baseline is 640 wide, 400% is
480; WCAG 1.4.10 reflows at 320) the Replay panes stack and fit the view
(s144 lane uiux, RM-1785; RM-1774 measured the Replay body at 426 px
of content in a 282 px view at 320).

Measured before the fix (ui_mock replay, headless Chromium): .replay-body is
a fixed `320px 1fr` grid at every width, so the match list held 320 px and
the main pane got what was left: 274 px at 720, 194 at 640 and 50 px at 480
and under, where the meta, clock, Timeline section and scoreboard all ran
past it. At 360 / 320 the list pane alone was wider than the view, so the
whole view scrolled sideways (section scrollWidth 426 in 322 / 282). Inside
the main pane the Timeline rows are a `64px 1fr 140px 160px` grid (364 px
plus gaps), so they scrolled sideways inside the 320 px event list, and the
filter row (three 42 px labels and the count) ran past the section head.

Contract pinned here, ui_mock replay at rest and with the first match
loaded, at 640x900, 480x800, 360x740 and 320x640:
  - the view does not scroll sideways, and every shown descendant lies
    inside the view's content box, except the scoreboard table, which
    scrolls sideways inside its own .replay-grid-wrap (that wrap lies
    inside the view and is not a vertical scroller);
  - the list pane sits above the main pane and both take the body's full
    width; the main pane is no nested vertical scroller (the view scrolls
    the panes as one page);
  - with 12 matches the list pane stops at 20rem and its match list
    scrolls inside it, so the main pane is never pushed a screen down;
  - every Timeline row keeps the --hit-min floor and its clock, label,
    actor and victim inside the row: clock and label on the first line,
    actor and victim under them as equal halves of one line, or (a
    Timeline under 20rem, 320 px windows) a line each, and the event list
    never scrolls sideways;
  - the Timeline filters and count lie inside the section head, and each
    filter keeps the --hit-min height;
  - the minimap figure, when shown, lies inside the main pane, and its
    canvas stays square (300 x 300 where it fits, as before).
The Timeline row reflow keys off the Timeline section's own width (under
34rem), not the window's, so it also holds from 721 px up to about 900,
where the panes are still side by side and the section is about 230 px
wide, and beside a shown minimap: there the event list never scrolls
sideways either.
Above the 720 line (722x900, 860x900 and the 1920x920 baseline) the panes
keep the desktop layout: the 320 px list column beside the main pane,
which scrolls on y. At the baseline the Timeline keeps its four tracks.

Under the 320 floor (s144 lane uiux, S144-U-179; S144-U-175 filed it): at
300 and 280 px the meta line under the scrubber (#replay-meta, the match id,
queue, length and patch) held its 191 px match id unbroken in a 196 / 176 px
pane, so it ran 9 / 29 px past the pane and the view and the pane's
overflow-x clip cut the id off; from 280 down each match row's queue label
ran past its row (and the view) beside the champion name. Contract pinned at
300x640 and 280x640, at rest, with the first match and with the long-id
match loaded: nothing lies past the view, the meta and clock lie inside the
main pane, and every match row's top line lies inside its row. The same
meta fault hit the long-id ui_mock match (a 473 px id) at 860, 722, 480,
360 and 320, so that match is loaded there too (and at 640, which it fit). At the baseline the meta
stays one line with the clock beside it.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_NARROW = ((640, 900), (480, 800), (360, 740), (320, 640))
_WIDE = ((722, 900), (860, 900), (1920, 920))
_IDS = [str(s[0]) for s in _NARROW]
_WIDE_IDS = [str(s[0]) for s in _WIDE]

_MOCK = Path(__file__).resolve().parents[2] / "web" / "data" / "ui_mock" / "replay.json"

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)


def _padded_mock():
    """The ui_mock replay fixture with 8 more matches (copies of the real
    four under synthetic MOCK_PAD ids, older timestamps), so the list is
    longer than the 20rem cap."""
    doc = json.loads(_MOCK.read_text(encoding="utf-8"))
    base = doc["matches"]
    extra = []
    for i in range(8):
        m = copy.deepcopy(base[i % len(base)])
        m["match_id"] = f"MOCK_PAD_{i + 1:02d}"
        m["game_creation_ts"] = int(m["game_creation_ts"]) - (i + 1) * 86_400_000
        extra.append(m)
    doc["matches"] = base + extra
    return doc


_READ = """() => {
  const sec = document.getElementById("view-replay");
  if (!sec || getComputedStyle(sec).display === "none") return null;
  const scs = getComputedStyle(sec);
  const sr = sec.getBoundingClientRect();
  const content = {
    l: sr.left + parseFloat(scs.borderLeftWidth) + parseFloat(scs.paddingLeft),
    r: sr.right - parseFloat(scs.borderRightWidth)
      - parseFloat(scs.paddingRight),
  };
  const shown = (e) => getComputedStyle(e).display !== "none"
    && getComputedStyle(e).visibility !== "hidden"
    && e.getBoundingClientRect().width > 0;
  const box = (e) => {
    const r = e.getBoundingClientRect();
    return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width,
            h: r.height};
  };
  const tag = (d) => d.tagName + "#" + d.id + "."
    + String(d.className).slice(0, 40);
  const wrap = sec.querySelector(".replay-grid-wrap");
  const viewPast = [];
  for (const d of sec.querySelectorAll("*")) {
    if (!shown(d)) continue;
    if (wrap && wrap !== d && wrap.contains(d)) continue;
    const r = d.getBoundingClientRect();
    if (r.right > content.r + 1 || r.left < content.l - 1) {
      viewPast.push([tag(d), Math.round(r.left), Math.round(r.right)]);
    }
  }
  const list = sec.querySelector(".replay-list-pane");
  const main = sec.querySelector(".replay-main-pane");
  const ml = document.getElementById("replay-match-list");
  const body = document.getElementById("replay-body");
  const mainCs = getComputedStyle(main);
  const mainIn = {
    l: main.getBoundingClientRect().left + parseFloat(mainCs.borderLeftWidth),
    r: main.getBoundingClientRect().right
      - parseFloat(mainCs.borderRightWidth),
  };
  const evRows = Array.from(sec.querySelectorAll(
    "#replay-events-list .replay-events-row")).filter(shown).map((row) => {
      const part = (c) => box(row.querySelector(c));
      const rcs = getComputedStyle(row);
      const rr = row.getBoundingClientRect();
      return {row: box(row), clock: part(".replay-events-clock"),
              label: part(".replay-events-label"),
              actor: part(".replay-events-actor"),
              victim: part(".replay-events-victim"),
              tracks: rcs.gridTemplateColumns,
              disp: rcs.display,
              inner: {l: rr.left + parseFloat(rcs.borderLeftWidth)
                        + parseFloat(rcs.paddingLeft),
                      r: rr.right - parseFloat(rcs.borderRightWidth)
                        - parseFloat(rcs.paddingRight)},
              colGap: parseFloat(rcs.columnGap) || 0};
    });
  const evSec = document.getElementById("replay-events-section");
  const evHead = evSec ? evSec.querySelector(".replay-events-head") : null;
  const filters = evHead && shown(evSec)
    ? Array.from(evHead.querySelectorAll(
      ".replay-events-filter, .replay-events-count")).map((f) => ({
        cls: f.className, ...box(f)}))
    : [];
  const fig = document.getElementById("replay-map-figure");
  const canvas = document.getElementById("replay-map-canvas");
  const meta = document.getElementById("replay-meta");
  const metaRange = document.createRange();
  metaRange.selectNodeContents(meta);
  const matchRows = Array.from(sec.querySelectorAll(
    "#replay-match-list .replay-match-row")).filter(shown).map((row) => {
      const rcs = getComputedStyle(row);
      const rb = box(row);
      return {
        row: rb,
        // The content box: the parts sit inside the row's own padding.
        inL: rb.l + parseFloat(rcs.borderLeftWidth)
          + parseFloat(rcs.paddingLeft),
        inR: rb.r - parseFloat(rcs.borderRightWidth)
          - parseFloat(rcs.paddingRight),
        top: Array.from(row.querySelectorAll(".replay-match-top > *"))
          .filter(shown).map((c) => ({cls: c.className, ...box(c)})),
      };
    });
  return {
    meta: box(meta), metaText: meta.textContent,
    metaLines: metaRange.getClientRects().length,
    clock: box(document.getElementById("replay-clock")),
    matchRows,
    sw: sec.scrollWidth, cw: sec.clientWidth, content,
    docSw: document.documentElement.scrollWidth, vw: innerWidth,
    viewPast: viewPast.slice(0, 8), nViewPast: viewPast.length,
    cols: getComputedStyle(body).gridTemplateColumns,
    body: box(body), list: box(list), main: box(main), mainIn,
    mainSh: main.scrollHeight, mainCh: main.clientHeight,
    mainOy: mainCs.overflowY,
    mlSh: ml.scrollHeight, mlCh: ml.clientHeight,
    nMatches: ml.querySelectorAll(".replay-match-row").length,
    rem: parseFloat(getComputedStyle(document.documentElement).fontSize),
    wrap: wrap && shown(wrap) ? {...box(wrap), sh: wrap.scrollHeight,
                                 ch: wrap.clientHeight} : null,
    evRows, evHead: evHead && shown(evSec) ? box(evHead) : null, filters,
    elSw: document.getElementById("replay-events-list").scrollWidth,
    elCw: document.getElementById("replay-events-list").clientWidth,
    // The container query reads the content box.
    evW: evSec && shown(evSec) ? evSec.clientWidth
      - parseFloat(getComputedStyle(evSec).paddingLeft)
      - parseFloat(getComputedStyle(evSec).paddingRight) : null,
    fig: fig && shown(fig) ? box(fig) : null,
    canvas: fig && shown(fig) ? box(canvas) : null,
  };
}"""


def _read(pw_browser, url, size, load, pad=False, show_map=False, row=0):
    ctx = pw_browser.new_context(
        ignore_https_errors=True,
        viewport={"width": size[0], "height": size[1]},
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    if pad:
        body = json.dumps(_padded_mock())
        page.route("**/data/ui_mock/replay.json", lambda route: route.fulfill(
            status=200, content_type="application/json", body=body))
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(url + "/?ui_mock=1#replay", wait_until="domcontentloaded",
                  timeout=15_000)
        page.wait_for_selector("#replay-match-list .replay-match-row",
                               timeout=10_000)
        if load:
            page.locator("#replay-match-list .replay-match-row").nth(
                row).click()
            page.wait_for_function(
                "() => document.querySelectorAll("
                "'.replay-grid-wrap tbody tr').length > 0"
                " && document.querySelectorAll("
                "'#replay-events-list .replay-events-row').length > 0",
                timeout=10_000,
            )
        if show_map:
            # The ui_mock snapshots carry no positions, so the minimap stays
            # hidden; unhide it to measure the figure's own box.
            page.evaluate(
                "document.getElementById('replay-map-figure').hidden = false")
        page.evaluate(_SETTLE)
        got = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors at {size}: {errors[:3]}"
    return got


@pytest.fixture(scope="module")
def narrow(mock_server, pw_browser):
    mock_server._store["data"] = {}
    return {(s, load): _read(pw_browser, mock_server.url, s, load)
            for s in _NARROW for load in (False, True)}


@pytest.fixture(scope="module")
def wide(mock_server, pw_browser):
    mock_server._store["data"] = {}
    return {s: _read(pw_browser, mock_server.url, s, True) for s in _WIDE}


_CASES = [(s, load) for s in _NARROW for load in (False, True)]
_CASE_IDS = [f"{s[0]}-{'loaded' if load else 'rest'}" for s, load in _CASES]


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_the_view_does_not_scroll_sideways(narrow, case):
    r = narrow[case]
    assert r is not None, case
    assert r["sw"] <= r["cw"], (case, r["sw"], r["cw"])
    assert r["docSw"] <= r["vw"], (case, r["docSw"], r["vw"])
    assert r["nViewPast"] == 0, (case, r["viewPast"])


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_the_panes_stack_full_width_and_the_view_scrolls_them(narrow, case):
    r = narrow[case]
    body, lst, main = r["body"], r["list"], r["main"]
    for pane in (lst, main):
        assert abs(pane["l"] - body["l"]) < 1, (case, pane, body)
        assert abs(pane["r"] - body["r"]) < 1, (case, pane, body)
    assert main["t"] >= lst["b"], (case, lst, main)
    assert r["mainSh"] <= r["mainCh"] + 1, (case, r["mainSh"], r["mainCh"])
    # Not a scroll container at all (overflow-y auto with no overflow
    # still binds sticky descendants and takes the wheel first).
    assert r["mainOy"] == "visible", (case, r["mainOy"])


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_the_scoreboard_scrolls_only_inside_its_own_wrap(narrow, case):
    r = narrow[case]
    w = r["wrap"]
    assert w is not None, case
    assert w["l"] >= r["mainIn"]["l"] - 1 and w["r"] <= r["mainIn"]["r"] + 1, (
        case, w, r["mainIn"])
    assert w["sh"] <= w["ch"] + 1, (case, w)


def _mid(b):
    return (b["t"] + b["b"]) / 2


def _check_wrapped_row(where, row, ev_w, rem):
    """A row of a Timeline narrower than 34rem: every part inside the row,
    clock and label on the first line, actor and victim under them - equal
    halves of one line from 20rem up, a line each below."""
    rb = row["row"]
    assert row["disp"] == "flex", (where, row)
    assert rb["h"] >= 42 - 0.5, (where, row)
    for key in ("clock", "label", "actor", "victim"):
        p = row[key]
        assert p["l"] >= rb["l"] - 0.5 and p["r"] <= rb["r"] + 0.5, (
            where, key, row)
        assert p["t"] >= rb["t"] - 0.5 and p["b"] <= rb["b"] + 0.5, (
            where, key, row)
    assert row["label"]["l"] >= row["clock"]["r"] - 0.5, (where, row)
    assert abs(row["label"]["t"] - row["clock"]["t"]) < 12, (where, row)
    for key in ("actor", "victim"):
        assert row[key]["t"] >= row["clock"]["b"] - 1, (where, key, row)
    actor, victim = row["actor"], row["victim"]
    if ev_w >= 20 * rem:
        # One line (centred, so compare middles: a portrait is taller).
        assert abs(_mid(actor) - _mid(victim)) < 1, (where, row)
        assert victim["l"] >= actor["r"] - 0.5, (where, row)
        assert abs(actor["w"] - victim["w"]) < 1, (where, row)
    else:
        assert victim["t"] >= actor["b"] - 1, (where, row)
        assert abs(actor["w"] - victim["w"]) < 1, (where, row)
        assert actor["w"] >= rb["w"] * 0.8, (where, row)


# RM-2041 (s154): the label's width is the row's first line minus the clock,
# and the clock is set in --font-mono, which the RM-1078 stub does not cover:
# Consolas on Windows, DejaVu Sans Mono on the hosted Linux runner, 0.05em a
# glyph wider. At 320 a five-character mm:ss clock reads 50.8 px on
# Windows and leaves the label 73.2; CI runs 42427610342 and 42427673121 both
# read the clock 94-149.546875 (55.5 px) and the label 68.453125. The row's
# content box is the same on both (134 px at 320: Windows 40.7 + 10 + 83.3,
# Linux 55.5 + 10 + 68.5), so the compact padding is checked on every host as
# that content width (measured on Windows) with the label taking the whole
# rest of the clock's line; the 72 px label floor, a text-width fact of the
# clock's face, is pinned on Windows, where it was measured.
_ROW_INNER_W = {(640, 900): 454, (480, 800): 294, (360, 740): 174,
                (320, 640): 134}


def _label_floor_is_pinned():
    return sys.platform == "win32"


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_timeline_rows_hold_their_parts_on_two_lines(narrow, size):
    r = narrow[(size, True)]
    rows = r["evRows"]
    assert len(rows) >= 5, rows
    assert r["evW"] < 34 * r["rem"], (size, r["evW"])
    for row in rows:
        _check_wrapped_row(size, row, r["evW"], r["rem"])
        inner, clock, label = row["inner"], row["clock"], row["label"]
        # The compact main-pane padding gives the row its content width (with
        # the desktop 20 / 24 px padding the label was 63 px at 320) ...
        assert abs((inner["r"] - inner["l"]) - _ROW_INNER_W[size]) < 0.5, (
            size, inner)
        # ... and the label takes all of it that the clock leaves.
        assert abs(label["l"] - (clock["r"] + row["colGap"])) < 0.5, (
            size, row)
        assert abs(label["r"] - inner["r"]) < 0.5, (size, row)
        # So the label keeps at least 72 px (83 beside a four-character clock
        # at 320) - in the clock face Windows draws.
        if _label_floor_is_pinned():
            assert row["label"]["w"] >= 72, (size, row)
    assert r["elSw"] <= r["elCw"] + 1, (size, r["elSw"], r["elCw"])


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_timeline_filters_stay_inside_the_section_head(narrow, size):
    r = narrow[(size, True)]
    head, filters = r["evHead"], r["filters"]
    assert head is not None, size
    assert len(filters) == 4, filters
    for f in filters:
        assert f["l"] >= head["l"] - 0.5 and f["r"] <= head["r"] + 0.5, (
            size, f, head)
        assert f["t"] >= head["t"] - 0.5 and f["b"] <= head["b"] + 0.5, (
            size, f, head)
        if "filter" in f["cls"]:
            assert f["h"] >= 42 - 0.5, (size, f)


@pytest.mark.parametrize("size", ((640, 900), (320, 640)), ids=["640", "320"])
def test_a_long_match_list_stops_at_its_cap(mock_server, pw_browser, size):
    mock_server._store["data"] = {}
    r = _read(pw_browser, mock_server.url, size, False, pad=True)
    assert r["nMatches"] == 12, r["nMatches"]
    assert r["list"]["h"] <= 20 * r["rem"] + 1, (size, r["list"])
    assert r["mlSh"] > r["mlCh"], (size, r["mlSh"], r["mlCh"])
    assert r["main"]["t"] >= r["list"]["b"], (size, r["list"], r["main"])
    assert r["sw"] <= r["cw"], (size, r["sw"], r["cw"])


@pytest.mark.parametrize("size", ((760, 900), (480, 800), (320, 640)),
                         ids=["760", "480", "320"])
def test_the_minimap_figure_fits_the_main_pane(mock_server, pw_browser, size):
    mock_server._store["data"] = {}
    r = _read(pw_browser, mock_server.url, size, True, show_map=True)
    fig = r["fig"]
    assert fig is not None, size
    assert fig["l"] >= r["mainIn"]["l"] - 1 and fig["r"] <= r["mainIn"]["r"] + 1, (
        size, fig, r["mainIn"])
    # The 480x480 map stays square as the figure shrinks, and fills it.
    cv = r["canvas"]
    assert abs(cv["w"] - cv["h"]) < 1, (size, cv)
    assert cv["l"] >= fig["l"] - 0.5 and cv["r"] <= fig["r"] + 0.5, (
        size, cv, fig)
    assert r["nViewPast"] == 0, (size, r["viewPast"])


@pytest.mark.parametrize("size", _WIDE, ids=_WIDE_IDS)
def test_desktop_panes_are_unchanged_above_the_line(wide, size):
    r = wide[size]
    assert r["sw"] <= r["cw"], (size, r["sw"], r["cw"])
    cols = [float(t[:-2]) for t in r["cols"].split()]
    assert len(cols) == 2 and abs(cols[0] - 320) < 0.5, (size, r["cols"])
    assert r["mainOy"] == "auto", (size, r["mainOy"])
    assert abs(r["list"]["t"] - r["main"]["t"]) < 1, (size, r["list"], r["main"])


@pytest.mark.parametrize("size", _WIDE, ids=_WIDE_IDS)
def test_the_event_list_never_scrolls_sideways_above_the_line(wide, size):
    r = wide[size]
    assert r["evRows"], size
    assert r["elSw"] <= r["elCw"] + 1, (size, r["elSw"], r["elCw"])
    assert len(r["filters"]) == 4, (size, r["filters"])
    for f in r["filters"]:
        h = r["evHead"]
        assert f["l"] >= h["l"] - 0.5 and f["r"] <= h["r"] + 0.5, (size, f, h)


@pytest.mark.parametrize("size", ((722, 900), (860, 900)), ids=["722", "860"])
def test_a_narrow_timeline_beside_the_list_is_two_lines(wide, size):
    r = wide[size]
    assert r["evW"] < 34 * r["rem"], (size, r["evW"])
    assert r["evRows"], size
    for row in r["evRows"]:
        _check_wrapped_row(size, row, r["evW"], r["rem"])


def test_the_baseline_timeline_keeps_its_four_tracks(wide):
    r = wide[(1920, 920)]
    assert r["evW"] >= 34 * r["rem"], r["evW"]
    assert len(r["evRows"]) >= 5, r["evRows"]
    for row in r["evRows"]:
        assert row["disp"] == "grid", row
        tracks = [float(t[:-2]) for t in row["tracks"].split()]
        assert len(tracks) == 4, row["tracks"]
        assert abs(tracks[0] - 64) < 0.5, row["tracks"]
        assert abs(tracks[2] - 140) < 0.5 and abs(tracks[3] - 160) < 0.5, (
            row["tracks"])
        # One line: actor and victim share the clock's line.
        assert abs(row["actor"]["t"] - row["clock"]["t"]) < 12, row


def test_beside_a_shown_minimap_the_timeline_reflows_on_its_own_width(
        mock_server, pw_browser):
    mock_server._store["data"] = {}
    r = _read(pw_browser, mock_server.url, (1200, 900), True, show_map=True)
    assert r["fig"] is not None
    # Beside a wide enough pane the map keeps its full 300 px square.
    assert abs(r["canvas"]["w"] - 300) < 1 and abs(r["canvas"]["h"] - 300) < 1, (
        r["canvas"])
    assert r["evW"] is not None
    # 362 px of Timeline content beside the 300 px minimap at 1200.
    assert r["evW"] < 34 * r["rem"], r["evW"]
    assert len(r["evRows"]) >= 5, r["evRows"]
    for row in r["evRows"]:
        _check_wrapped_row("1200-map", row, r["evW"], r["rem"])
    assert r["elSw"] <= r["elCw"] + 1, (r["elSw"], r["elCw"])
    assert r["sw"] <= r["cw"], (r["sw"], r["cw"])


# Under the 320 floor: rest, the first match, and the long-id ui_mock match
# (row 1, MOCK_ARENA_LOSS_OVERFLOW_LONG_NAME_FOR_ELLIPSIS_TEST).
_TINY = ((300, 640), (280, 640))
_TINY_CASES = [(s, load, row) for s in _TINY
               for load, row in ((False, 0), (True, 0), (True, 1))]
_TINY_IDS = [f"{s[0]}-{'rest' if not load else f'row{row}'}"
             for s, load, row in _TINY_CASES]


@pytest.fixture(scope="module")
def tiny(mock_server, pw_browser):
    mock_server._store["data"] = {}
    return {c: _read(pw_browser, mock_server.url, c[0], c[1], row=c[2])
            for c in _TINY_CASES}


@pytest.mark.parametrize("case", _TINY_CASES, ids=_TINY_IDS)
def test_under_the_floor_nothing_runs_past_the_view(tiny, case):
    r = tiny[case]
    assert r is not None, case
    assert r["sw"] <= r["cw"], (case, r["sw"], r["cw"])
    assert r["docSw"] <= r["vw"], (case, r["docSw"], r["vw"])
    assert r["nViewPast"] == 0, (case, r["viewPast"])


@pytest.mark.parametrize("case", _TINY_CASES, ids=_TINY_IDS)
def test_under_the_floor_the_meta_and_clock_stay_in_the_pane(tiny, case):
    r = tiny[case]
    m_in = r["mainIn"]
    for key in ("meta", "clock"):
        b = r[key]
        assert b["l"] >= m_in["l"] - 0.5 and b["r"] <= m_in["r"] + 0.5, (
            case, key, b, m_in)
    if case[1]:
        # The loaded meta names the picked match (a real line, not the
        # resting prompt), whole.
        ids = ("MOCK_NORMAL_DRAFT_WIN",
               "MOCK_ARENA_LOSS_OVERFLOW_LONG_NAME_FOR_ELLIPSIS_TEST")
        assert r["metaText"].startswith(ids[case[2]] + " - "), (
            case, r["metaText"])


@pytest.mark.parametrize("case", _TINY_CASES, ids=_TINY_IDS)
def test_under_the_floor_each_match_row_holds_its_top_line(tiny, case):
    r = tiny[case]
    assert len(r["matchRows"]) == 4, (case, r["matchRows"])
    for mr in r["matchRows"]:
        rb = mr["row"]
        assert rb["h"] >= 42 - 0.5, (case, rb)
        assert len(mr["top"]) == 3, (case, mr)
        for part in mr["top"]:
            assert part["l"] >= mr["inL"] - 0.5, (case, part, mr)
            assert part["r"] <= mr["inR"] + 0.5, (case, part, mr)
            # A label drops to its own line whole; it is never broken
            # inside itself (one 19 px line, not a 38 px two-line box).
            assert part["h"] < 30, (case, part)


# The long-id ui_mock match at the stacked widths and beside the list:
# its 473 px id ran past the pane (and the view) at all of these but 640
# before S144-U-179 (the cases above load row 0 only).
_LONG = ((860, 900), (722, 900)) + _NARROW


@pytest.mark.parametrize("size", _LONG, ids=[str(s[0]) for s in _LONG])
def test_the_long_match_id_breaks_inside_the_pane(mock_server, pw_browser,
                                                  size):
    mock_server._store["data"] = {}
    r = _read(pw_browser, mock_server.url, size, True, row=1)
    assert r["metaText"].startswith(
        "MOCK_ARENA_LOSS_OVERFLOW_LONG_NAME_FOR_ELLIPSIS_TEST - "), (
        r["metaText"])
    m_in = r["mainIn"]
    for key in ("meta", "clock"):
        b = r[key]
        assert b["l"] >= m_in["l"] - 0.5 and b["r"] <= m_in["r"] + 0.5, (
            size, key, b, m_in)
    assert r["sw"] <= r["cw"], (size, r["sw"], r["cw"])
    assert r["nViewPast"] == 0, (size, r["viewPast"])


def test_the_baseline_meta_is_one_line_beside_the_clock(wide):
    r = wide[(1920, 920)]
    assert r["metaText"].startswith("MOCK_NORMAL_DRAFT_WIN - "), r["metaText"]
    assert r["metaLines"] == 1, (r["metaLines"], r["meta"])
    # The clock shares the meta's line, to its right.
    assert r["clock"]["l"] >= r["meta"]["r"] - 0.5, (r["meta"], r["clock"])
    assert r["clock"]["t"] < r["meta"]["b"], (r["meta"], r["clock"])
