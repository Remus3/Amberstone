"""
tests/snapshot_panels/test_champ_select_build_row_mid_width.py
An ARAM / Arena / experimental Champ Select build row (checkbox | meta |
spells | items) never draws its variant badge or keystone strip over the
spells and items, at any width above 720 px (s144 lane uiux, RM-1781;
RM-1780 fixed 720 px and under).

Measured before the fix (ui_mock mode=aram, headless Chromium, spell icons
drawn): the row was a grid `14px 1fr auto auto`, so its meta column was what
the spells and items left over, while the badge inside it is a fixed 200 px
and the keystone strip a fixed 130 px. In the one-track 1200 px reflow the
meta was 51 px at 721, 90 at 760 and 130 at 800, and in the narrowest
three-track layout 177 px at 1201: the badge (and at 721-760 the keystone
strip) reached into the spells and items there (4 icons covered at 721, 3 at
760, 2 at 800, 1 at 1201).

The SR and Arena ui_mock fixtures carry no uncollapsed build row (Arena and
SR experimental rows share this markup and CSS), so the row is measured in
ARAM only.

Contract pinned here at 722 to 1920 wide, mode aram:
  - every displayed part of the meta (badge, keystone strip) lies inside the
    meta box, and no part of the row (checkbox, meta, spells, items) overlaps
    another, so nothing is drawn over the spells or items;
  - the parts lie inside the row's content box, items keep 42x42 and the two
    spells 20x20, the checkbox shares the meta's line, and the spells share
    the meta's or the items' line;
  - where one line holds all four parts (checkbox 14 + three 10 px gaps +
    a 200 px meta + spells + items), the row is that one line with the same
    geometry the grid gave it: checkbox at the content's left edge, meta at
    +24, items flush right, 10 px between meta, spells and items; otherwise
    the items go to a line of their own, 6 px under the meta's line, and
    the spells stay on the meta's line.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_champ_select_narrow_reflow import (
    _PNG,
    _SETTLE,
    _apart,
    _same_line,
)

_SIZES = ((722, 920), (760, 920), (800, 920), (880, 920), (960, 920),
          (1100, 920), (1200, 920), (1201, 920), (1240, 920), (1280, 920),
          (1440, 920), (1920, 920))
_IDS = [str(s[0]) for s in _SIZES]

_READ = """() => {
  const sec = document.getElementById("view-champ-select");
  if (!sec || getComputedStyle(sec).display === "none") return null;
  const shown = (e) => getComputedStyle(e).display !== "none"
    && getComputedStyle(e).visibility !== "hidden"
    && e.getBoundingClientRect().width > 0;
  const box = (e) => {
    const r = e.getBoundingClientRect();
    return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width,
            h: r.height};
  };
  return Array.from(sec.querySelectorAll(
      ".csv-build-row:not(.csv-build-row-collapsed)")).filter(shown)
    .map((row) => {
      const cs = getComputedStyle(row);
      const rb = row.getBoundingClientRect();
      const meta = row.querySelector(":scope > .csv-build-meta");
      return {
        display: cs.display,
        content: {
          l: rb.left + parseFloat(cs.borderLeftWidth)
            + parseFloat(cs.paddingLeft),
          r: rb.right - parseFloat(cs.borderRightWidth)
            - parseFloat(cs.paddingRight),
        },
        parts: Array.from(row.children).filter(shown).map((k) => ({
          cls: String(k.className).split(" ")[0], ...box(k)})),
        metaKids: meta ? Array.from(meta.querySelectorAll("*"))
          .filter(shown).map((k) => ({
            cls: String(k.className).slice(0, 40), ...box(k),
            sw: k.scrollWidth, cw: k.clientWidth})) : [],
        spells: Array.from(row.querySelectorAll(".csv-build-spell"))
          .filter(shown).map(box),
        items: Array.from(row.querySelectorAll(".csv-build-item"))
          .filter(shown).map(box),
      };
    });
}"""


def _read(pw_browser, url, size):
    ctx = pw_browser.new_context(
        ignore_https_errors=True,
        viewport={"width": size[0], "height": size[1]},
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    # The ui_mock server has no /icons/spells/ route; serve a real image so
    # the spells column is drawn, as on the live page.
    page.route("**/icons/spells/**", lambda route: route.fulfill(
        status=200, content_type="image/png", body=_PNG))
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(url + "/?ui_mock=1&mode=aram#champ-select",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "document.body.dataset.view === 'champ-select'"
            " && document.querySelector('#view-champ-select"
            " .csv-build-row:not(.csv-build-row-collapsed) .csv-build-item')",
            timeout=15_000,
        )
        page.wait_for_function(
            "Array.from(document.querySelectorAll('#view-champ-select"
            " img.csv-build-spell')).every((i) => i.complete"
            " && i.naturalWidth > 0)",
            timeout=10_000,
        )
        page.evaluate(_SETTLE)
        got = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors at {size}: {errors[:3]}"
    assert got, size
    return got


@pytest.fixture(scope="module")
def rows(mock_server, pw_browser):
    mock_server._store["data"] = {}
    return {s: _read(pw_browser, mock_server.url, s) for s in _SIZES}


def _by(row):
    return {p["cls"]: p for p in row["parts"]}


@pytest.mark.parametrize("size", _SIZES, ids=_IDS)
def test_meta_parts_stay_inside_the_meta(rows, size):
    for row in rows[size]:
        meta = _by(row)["csv-build-meta"]
        assert len(row["metaKids"]) >= 2, (size, row["metaKids"])
        for k in row["metaKids"]:
            assert k["l"] >= meta["l"] - 0.5, (size, k, meta)
            assert k["r"] <= meta["r"] + 0.5, (size, k, meta)
        badge = row["metaKids"][0]
        assert "csv-build-badge" in badge["cls"], (size, badge)
        # The whole label is shown, never elided.
        assert badge["cw"] + 0.5 >= badge["sw"], (size, badge)


@pytest.mark.parametrize("size", _SIZES, ids=_IDS)
def test_nothing_is_drawn_over_the_spells_or_items(rows, size):
    for row in rows[size]:
        parts = row["parts"]
        assert len(parts) == 4, (size, parts)
        for i, a in enumerate(parts):
            for b in parts[i + 1:]:
                assert _apart(a, b), (size, a, b)
        assert len(row["spells"]) == 2, (size, row)
        assert row["items"], (size, row)
        for k in row["metaKids"]:
            for it in row["spells"] + row["items"]:
                assert _apart(k, it), (size, k, it)


@pytest.mark.parametrize("size", _SIZES, ids=_IDS)
def test_parts_fit_the_row_and_keep_their_size(rows, size):
    for row in rows[size]:
        c = row["content"]
        for p in row["parts"]:
            assert p["l"] >= c["l"] - 0.5 and p["r"] <= c["r"] + 0.5, (
                size, p, c)
        for it in row["items"]:
            assert abs(it["w"] - 42) < 0.5 and abs(it["h"] - 42) < 0.5, (
                size, it)
        for sp in row["spells"]:
            assert abs(sp["w"] - 20) < 0.5 and abs(sp["h"] - 20) < 0.5, (
                size, sp)
        by = _by(row)
        cb, meta = by["csv-build-checkbox"], by["csv-build-meta"]
        sp, items = by["csv-build-spells"], by["csv-build-items"]
        assert _same_line(cb, meta), (size, row["parts"])
        assert _same_line(sp, meta) or _same_line(sp, items), (
            size, row["parts"])


@pytest.mark.parametrize("size", _SIZES, ids=_IDS)
def test_one_line_where_it_fits_with_the_grid_geometry(rows, size):
    for row in rows[size]:
        c = row["content"]
        by = _by(row)
        cb, meta = by["csv-build-checkbox"], by["csv-build-meta"]
        sp, items = by["csv-build-spells"], by["csv-build-items"]
        need = 14 + 30 + 200 + sp["w"] + items["w"]
        if c["r"] - c["l"] + 0.5 >= need:
            assert _same_line(meta, items) and _same_line(sp, items), (
                size, row["parts"])
            assert abs(cb["l"] - c["l"]) < 0.5, (size, cb, c)
            assert abs(meta["l"] - (c["l"] + 24)) < 0.5, (size, meta, c)
            assert abs(items["r"] - c["r"]) < 0.5, (size, items, c)
            assert abs(sp["l"] - (meta["r"] + 10)) < 0.5, (size, sp, meta)
            assert abs(items["l"] - (sp["r"] + 10)) < 0.5, (size, items, sp)
            # Vertically centred on one line, as the grid's align-items.
            mid = (items["t"] + items["b"]) / 2
            for p in (cb, meta, sp):
                assert abs((p["t"] + p["b"]) / 2 - mid) < 0.5, (size, p, mid)
        else:
            assert items["t"] >= meta["b"] - 0.5, (size, row["parts"])
            # Above 720 the spells stay on the meta's line and the items'
            # line starts 6 px under it (the row gap).
            assert _same_line(sp, meta), (size, row["parts"])
            top = max(cb["b"], meta["b"], sp["b"])
            assert abs(items["t"] - (top + 6)) < 0.5, (size, row["parts"])


def test_the_one_line_case_is_exercised(rows):
    # 1920 (the baseline) and 1100 (the 1200 px reflow) hold one line; 722
    # and 1201 do not. Without this the branch above could go untested.
    for size, one in (((1920, 920), True), ((1100, 920), True),
                      ((722, 920), False), ((1201, 920), False)):
        for row in rows[size]:
            by = _by(row)
            assert _same_line(by["csv-build-meta"], by["csv-build-items"]) \
                is one, (size, row["parts"])
