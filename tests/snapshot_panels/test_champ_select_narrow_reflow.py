"""
tests/snapshot_panels/test_champ_select_narrow_reflow.py
At 720 px and under (300% zoom of the 1920x920 baseline is 640 wide, 400% is
480; WCAG 1.4.10 reflows at 320) every Champ Select card fits the view and
nothing inside a card runs past it, in all three ui_mock modes (s144 lane
uiux, RM-1780; RM-1774 did the view heads).

Measured before the fix (ui_mock, headless Chromium): below 1200 px the grid
is one 1fr track, and a 1fr track cannot shrink below its widest card's
min-content, so every card was 640 px wide at every narrow width and the
view scrolled sideways (658 in 602 at 640, 658 in 282 at 320). With only the
track freed, the inner rows ran past their card: the ARAM bench (ten 58 px
cells) from 640 down, and at 320 the My Pick portrait row, the build path
rows, the ARAM build row and the Arena duo / augment / sub-team rows; the
200 px rune side rail beside the build list left that list 14 px at 320.
The ARAM build row grid let its meta column fall to 0 px at 640, so the
fixed 200 px variant badge drew over the spell and item icons (found by the
verifier at 560 / 640 once the spell icons were drawn; the ui_mock server has
no spell icon route, so this file serves a stub image for them).

Contract pinned here at 640x900, 560x860, 480x800, 360x740 and 320x640,
modes sr, aram and arena:
  - the view does not scroll sideways and every card lies inside the view's
    content box;
  - no displayed descendant of a card reaches past that card's frame;
  - a row of N equal cells (bench 5 at 58 px, duo 3 at 84, augments 3 at
    96, Arena sub-team 3 at 96) holds N columns while each keeps its floor,
    else as many as fit, and no cell drops under its floor;
  - the My Pick portrait keeps 88x88 at the card's centre, and at 480 and
    under the state, portrait and name stack;
  - the rune side rail drops under the build list when both do not fit,
    a build path's item icons keep 32x32;
  - an ARAM build row keeps its 42x42 items and its whole badge label inside
    its meta box, no two of its parts (checkbox, meta, spells, items)
    overlap, and neither the checkbox nor the spells sit alone on a line.
Above the line (722x900 and 1920x920) the layout is unchanged: the 1200 px
one-track grid at 722 and the three-track grid at 1920, ten bench columns,
the three-track portrait row, two-track path rows, the grid build row and
the rune rail beside the build list.
"""
import base64
import math

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_NARROW = ((640, 900), (560, 860), (480, 800), (360, 740), (320, 640))
# A 1x1 PNG for the stubbed spell icons.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
_WIDE = ((722, 900), (1920, 920))
_MODES = ("sr", "aram", "arena")
_IDS = [str(s[0]) for s in _NARROW]

# Row selector -> (cell selector, N columns wanted, cell floor px, gap px).
_ROWS = {
    "bench": (".csv-bench-row", ".csv-bench-cell", 5, 58, 6),
    "duo": (".csv-duo-row", ".csv-duo-cell", 3, 84, 8),
    "aug": (".csv-augment-slots", ".csv-augment-slot", 3, 96, 6),
    "team": (".csv-arena-team-row", ".csv-arena-cell", 3, 96, 6),
}
_ROWS_BY_MODE = {"sr": (), "aram": ("bench",), "arena": ("duo", "aug", "team")}

_READY = {
    "sr": ".csv-build-path-row .csv-build-path-item",
    "aram": ".csv-bench-cell",
    "arena": ".csv-augment-slot",
}

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)

_READ = """(rows) => {
  const sec = document.getElementById("view-champ-select");
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
  const all = (s) => Array.from(sec.querySelectorAll(s)).filter(shown);
  const tracks = (e) => getComputedStyle(e).gridTemplateColumns.split(" ")
    .filter(Boolean).length;
  const cards = all(".csv-card").map((c) => {
    const cr = c.getBoundingClientRect();
    const past = [];
    for (const d of c.querySelectorAll("*")) {
      if (!shown(d)) continue;
      const r = d.getBoundingClientRect();
      if (r.right > cr.right + 1 || r.left < cr.left - 1) {
        past.push([d.tagName + "." + String(d.className).slice(0, 48),
                   Math.round(r.left), Math.round(r.right),
                   Math.round(cr.left), Math.round(cr.right)]);
      }
    }
    return {cls: String(c.className).slice(0, 48), box: box(c),
            past: past.slice(0, 6), n: past.length};
  });
  const cellRows = {};
  for (const [key, [rowSel, cellSel]] of Object.entries(rows)) {
    cellRows[key] = all(rowSel).map((row) => {
      const rcs = getComputedStyle(row);
      return {
        w: row.getBoundingClientRect().width
          - parseFloat(rcs.paddingLeft) - parseFloat(rcs.paddingRight),
        cols: tracks(row),
        cells: Array.from(row.querySelectorAll(":scope > " + cellSel))
          .filter(shown).map((c) => c.getBoundingClientRect().width),
      };
    });
  }
  const port = all(".csv-mypick-portrait-row")[0];
  let portrait = null;
  if (port) {
    const card = port.closest(".csv-card").getBoundingClientRect();
    const ic = port.querySelector(".csv-mypick-icon").getBoundingClientRect();
    portrait = {
      cols: tracks(port),
      dc: (ic.left + ic.right) / 2 - (card.left + card.right) / 2,
      icon: [ic.width, ic.height],
      kids: Array.from(port.children).filter(shown).map(box),
    };
  }
  const brow = all(".csv-builds-row")[0];
  let builds = null;
  if (brow) {
    builds = {
      list: box(brow.querySelector(".csv-builds")),
      rail: shown(brow.querySelector(".csv-rune-side"))
        ? box(brow.querySelector(".csv-rune-side")) : null,
    };
  }
  const pathRows = all(".csv-build-path-row").map((p) => ({
    box: box(p),
    cols: tracks(p),
    items: Array.from(p.querySelectorAll(".csv-build-path-item"))
      .filter(shown).map(box),
  }));
  const buildRows = all(".csv-build-row:not(.csv-build-row-collapsed)")
    .map((r) => {
      const badge = r.querySelector(".csv-build-meta > :first-child");
      return {
        box: box(r),
        display: getComputedStyle(r).display,
        badge: badge ? {w: badge.getBoundingClientRect().width,
                        sw: badge.scrollWidth, box: box(badge)} : null,
        meta: box(r.querySelector(".csv-build-meta")),
        parts: Array.from(r.children).filter(shown).map((k) => ({
          cls: String(k.className).slice(0, 32), ...box(k)})),
        spells: Array.from(r.querySelectorAll(".csv-build-spell"))
          .filter(shown).map(box),
        items: Array.from(r.querySelectorAll(".csv-build-item"))
          .filter(shown).map(box),
      };
    });
  return {
    sw: sec.scrollWidth, cw: sec.clientWidth, content,
    grid: tracks(sec.querySelector(".csv-grid")),
    cards, cellRows, portrait, builds, pathRows, buildRows,
  };
}"""


def _read(pw_browser, url, mode, size):
    ctx = pw_browser.new_context(
        ignore_https_errors=True,
        viewport={"width": size[0], "height": size[1]},
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    # The ui_mock server has no /icons/spells/ route, so a spell <img>
    # errors and hides itself (onerror) at an unknown time; serve a real
    # image so the spells column is drawn, as on the live page.
    page.route("**/icons/spells/**", lambda route: route.fulfill(
        status=200, content_type="image/png", body=_PNG))
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    rows = {k: _ROWS[k][:2] for k in _ROWS_BY_MODE[mode]}
    try:
        page.goto(url + f"/?ui_mock=1&mode={mode}#champ-select",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "(sel) => document.body.dataset.view === 'champ-select'"
            " && document.querySelector('#view-champ-select ' + sel)"
            " && document.querySelector('#view-champ-select .csv-rune-side')",
            arg=_READY[mode],
            timeout=15_000,
        )
        page.wait_for_function(
            "Array.from(document.querySelectorAll('#view-champ-select"
            " img.csv-build-spell')).every((i) => i.complete"
            " && i.naturalWidth > 0)",
            timeout=10_000,
        )
        page.evaluate(_SETTLE)
        got = page.evaluate(_READ, rows)
    finally:
        ctx.close()
    assert not errors, f"page errors at {mode} {size}: {errors[:3]}"
    assert got is not None, (mode, size)
    return got


@pytest.fixture(scope="module")
def narrow(mock_server, pw_browser):
    mock_server._store["data"] = {}
    return {(m, s): _read(pw_browser, mock_server.url, m, s)
            for m in _MODES for s in _NARROW}


@pytest.fixture(scope="module")
def wide(mock_server, pw_browser):
    mock_server._store["data"] = {}
    return {(m, s): _read(pw_browser, mock_server.url, m, s)
            for m in _MODES for s in _WIDE}


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
@pytest.mark.parametrize("mode", _MODES)
def test_view_does_not_scroll_sideways_and_cards_fit(narrow, mode, size):
    r = narrow[(mode, size)]
    assert r["sw"] <= r["cw"] + 1, (mode, size, r["sw"], r["cw"])
    assert len(r["cards"]) >= 3, (mode, size, r["cards"])
    for c in r["cards"]:
        b = c["box"]
        assert b["l"] >= r["content"]["l"] - 1, (mode, size, c, r["content"])
        assert b["r"] <= r["content"]["r"] + 1, (mode, size, c, r["content"])


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
@pytest.mark.parametrize("mode", _MODES)
def test_no_card_content_reaches_past_its_frame(narrow, mode, size):
    assert len(narrow[(mode, size)]["cards"]) >= 3, (mode, size)
    for c in narrow[(mode, size)]["cards"]:
        assert c["n"] == 0, (mode, size, c["cls"], c["past"])


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
@pytest.mark.parametrize("mode", ("aram", "arena"))
def test_cell_rows_keep_n_columns_or_as_many_as_fit(narrow, mode, size):
    r = narrow[(mode, size)]
    seen = 0
    for key in _ROWS_BY_MODE[mode]:
        _, _, n, floor, gap = _ROWS[key]
        assert r["cellRows"][key], (mode, size, key)
        for row in r["cellRows"][key]:
            seen += 1
            fit = math.floor((row["w"] + gap + 0.5) / (floor + gap))
            assert row["cols"] == max(1, min(n, fit)), (mode, size, key, row)
            assert row["cells"], (mode, size, key, row)
            for w in row["cells"]:
                assert w + 0.5 >= floor, (mode, size, key, row)
    assert seen >= len(_ROWS_BY_MODE[mode]), (mode, size)


def test_bench_is_two_rows_of_five_at_640(narrow):
    rows = narrow[("aram", (640, 900))]["cellRows"]["bench"]
    assert rows and rows[0]["cols"] == 5 and len(rows[0]["cells"]) == 10, rows


def test_arena_rows_hold_three_across_at_480(narrow):
    r = narrow[("arena", (480, 800))]["cellRows"]
    for key in ("duo", "aug", "team"):
        for row in r[key]:
            assert row["cols"] == 3, (key, row)


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
@pytest.mark.parametrize("mode", ("sr", "aram"))
def test_portrait_keeps_its_box_at_the_card_centre(narrow, mode, size):
    p = narrow[(mode, size)]["portrait"]
    assert p is not None, (mode, size)
    assert p["icon"] == [88, 88], (mode, size, p)
    assert abs(p["dc"]) < 1, (mode, size, p)
    tops = [k["t"] for k in p["kids"]]
    if size[0] <= 480:
        assert p["cols"] == 1, (mode, size, p)
        assert len(tops) == 3, (mode, size, p)
        for a, b in zip(p["kids"], p["kids"][1:]):
            assert b["t"] >= a["b"] - 0.5, (mode, size, p)
    else:
        assert p["cols"] == 3, (mode, size, p)


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
@pytest.mark.parametrize("mode", _MODES)
def test_rune_rail_drops_under_the_build_list(narrow, mode, size):
    b = narrow[(mode, size)]["builds"]
    assert b is not None and b["rail"] is not None, (mode, size, b)
    assert b["rail"]["t"] >= b["list"]["b"] - 0.5, (mode, size, b)
    assert abs(b["rail"]["w"] - b["list"]["w"]) < 1, (mode, size, b)


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
@pytest.mark.parametrize("mode", ("sr", "arena"))
def test_build_path_items_keep_their_box_inside_the_row(narrow, mode, size):
    rows = narrow[(mode, size)]["pathRows"]
    assert rows, (mode, size)
    for row in rows:
        assert row["cols"] == (1 if size[0] <= 480 else 2), (mode, size, row)
        assert len(row["items"]) >= 1, (mode, size, row)
        for it in row["items"]:
            assert abs(it["w"] - 32) < 0.5 and abs(it["h"] - 32) < 0.5, (
                mode, size, row)
            assert it["r"] <= row["box"]["r"] + 0.5, (mode, size, row)


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_aram_build_row_keeps_items_and_whole_badge(narrow, size):
    rows = narrow[("aram", size)]["buildRows"]
    assert rows, size
    for row in rows:
        assert row["badge"] is not None, (size, row)
        assert row["badge"]["w"] + 0.5 >= row["badge"]["sw"], (size, row)
        # The badge lies inside its own meta column, so it is never drawn
        # over the item icons (a 0 px column lets it spill onto them).
        bb, mb = row["badge"]["box"], row["meta"]
        assert bb["r"] <= mb["r"] + 0.5, (size, row)
        assert len(row["items"]) >= 1, (size, row)
        # The stubbed spell icons are drawn, so the spells column is real.
        assert len(row["spells"]) == 2, (size, row)
        for it in row["items"] + row["spells"]:
            assert it["r"] <= row["box"]["r"] + 0.5, (size, row)
            assert _apart(it, bb), (size, bb, it)
        for it in row["items"]:
            assert abs(it["w"] - 42) < 0.5 and abs(it["h"] - 42) < 0.5, (
                size, row)
        # No two parts of the row (checkbox, meta, spells, items) overlap.
        parts = row["parts"]
        assert len(parts) == 4, (size, parts)
        for i, a in enumerate(parts):
            for b in parts[i + 1:]:
                assert _apart(a, b), (size, a, b)
        # Neither the checkbox nor the spells sit alone on a line: the
        # checkbox shares the meta's line, the spells the meta's or the
        # items' line.
        by = {p["cls"].split()[0]: p for p in parts}
        cb, meta = by["csv-build-checkbox"], by["csv-build-meta"]
        sp, items = by["csv-build-spells"], by["csv-build-items"]
        assert _same_line(cb, meta), (size, parts)
        assert _same_line(sp, meta) or _same_line(sp, items), (size, parts)


def _same_line(a, b):
    return a["t"] < b["b"] - 0.5 and b["t"] < a["b"] - 0.5


def _apart(a, b):
    return (a["l"] >= b["r"] - 0.5 or a["r"] <= b["l"] + 0.5
            or a["t"] >= b["b"] - 0.5 or a["b"] <= b["t"] + 0.5)


@pytest.mark.parametrize("size", _WIDE, ids=[str(s[0]) for s in _WIDE])
@pytest.mark.parametrize("mode", _MODES)
def test_layout_is_unchanged_above_the_line(wide, mode, size):
    r = wide[(mode, size)]
    assert r["grid"] == (3 if size[0] > 1200 else 1), (mode, size, r["grid"])
    b = r["builds"]
    assert b is not None and b["rail"] is not None, (mode, size, b)
    assert abs(b["rail"]["w"] - 200) < 0.5, (mode, size, b)
    assert b["rail"]["l"] >= b["list"]["r"] - 0.5, (mode, size, b)
    assert r["pathRows"] or mode == "aram", (mode, size)
    for row in r["pathRows"]:
        assert row["cols"] == 2, (mode, size, row)
    if mode in ("sr", "aram"):
        assert r["portrait"]["cols"] == 3, (mode, size, r["portrait"])
    if mode == "aram":
        assert [row["cols"] for row in r["cellRows"]["bench"]] == [10], r
        assert r["buildRows"], size
        for row in r["buildRows"]:
            assert row["display"] == "grid", (size, row)
    if mode == "arena":
        for key in ("duo", "aug", "team"):
            assert r["cellRows"][key], (size, key)
            for row in r["cellRows"][key]:
                assert row["cols"] == 3, (size, key, row)
