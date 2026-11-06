"""
tests/snapshot_panels/test_build_insights_narrow_table_scroll.py
In a narrow window a Build Insights WPA table (Items, Skills, Runes, Spells)
scrolls sideways inside its own mount, so the view never scrolls sideways
and the TAKEAWAY rail, caption and tabs stay put (s144 lane uiux,
RM-1777). 300% zoom of the 1920x920 baseline is 640 wide, 400% is 480,
WCAG 1.4.10 reflows at 320; a data table is the 1.4.10 two-dimensional
exception, so it may scroll, but inside itself, not the page.

Measured before the fix (headless Chromium, the ui_mock build_insights,
build_insights_skill, rune_wpa and summspell_wpa fixtures): under the
1200 px line .bi-pane-cols stacks as a column with align-items:flex-start,
so the table mount shrink-wrapped to the table's nowrap width (Items 689,
Skills 686, Runes 709, Spells 570 px) however narrow its pane was. A
table broke out of its pane below about 825 px (Runes; Items 805), and
the view scrolled sideways below about 786 px (Runes; Items 766, Spells
647): at 722 the section was 728 / 725 / 748 / 609 px wide in a 684 px
box, at 320 the Items table ran about 445 px past the view. The Benchmarks tab already scrolls its
table inside .cb-table-wrap; this brings the four WPA mounts in line.

Contract pinned for each WPA tab at 800x900, 722x900, 640x900, 480x800,
360x740 and 320x640:
  - the view does not scroll sideways (the section and the document);
  - the table mount lies inside its pane's content box and is the thing
    that scrolls sideways (overflow-x auto) when the table is wider, with
    no vertical scrollbar of its own;
  - every column is reachable: scrolled to its end, the Win Rate column's
    right edge is inside the mount;
  - keyboard: focusing the Win Rate sort button scrolls the mount so the
    button is wholly visible, and so does a re-sort from it (Enter); from
    the far end, focusing the WPA sort button scrolls back to show it.
    Chrome's own focus scroll leaves a partly visible button where it is
    (5 to 56 px past the edge measured), so build_insights.js reveals it.
Above the narrow range nothing moves: at 1920x920 and 1280x900 the rail
sits right of the table and no mount scrolls; at 1000x900 the table keeps
its own width (the mount is not stretched past the table).
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_NARROW = ((800, 900), (722, 900), (640, 900), (480, 800), (360, 740),
           (320, 640))
_TABS = ("items", "skills", "runes", "spells")
_MOUNT = {"items": "#bi-table-mount", "skills": "#bi-skill-table-mount",
          "runes": "#bi-rune-table-mount", "spells": "#bi-spell-table-mount"}
_CASES = [(w, h, t) for (w, h) in _NARROW for t in _TABS]
_IDS = [f"{w}-{t}" for (w, h, t) in _CASES]

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)

_READ = """(sel) => {
  const sec = document.getElementById("view-build-insights");
  const mount = document.querySelector(sel);
  const pane = mount.closest(".bi-tab-pane");
  const table = mount.querySelector("table.bi-table");
  const wr = table.querySelector("th.bi-c-wr");
  const rail = pane.querySelector(".bi-summary");
  const pcs = getComputedStyle(pane);
  const pr = pane.getBoundingClientRect();
  const mr = mount.getBoundingClientRect();
  const se = document.scrollingElement;
  return {
    sec: [sec.scrollWidth, sec.clientWidth],
    doc: [se.scrollWidth, se.clientWidth],
    paneIn: [pr.left + parseFloat(pcs.borderLeftWidth)
               + parseFloat(pcs.paddingLeft),
             pr.right - parseFloat(pcs.borderRightWidth)
               - parseFloat(pcs.paddingRight)],
    mount: {l: mr.left, r: mr.right, sw: mount.scrollWidth,
            cw: mount.clientWidth, sh: mount.scrollHeight,
            ch: mount.clientHeight,
            ox: getComputedStyle(mount).overflowX},
    tableW: table.getBoundingClientRect().width,
    wrR: wr.getBoundingClientRect().right,
    rail: rail ? rail.getBoundingClientRect().left : null,
  };
}"""

_END = """(sel) => {
  const mount = document.querySelector(sel);
  mount.scrollLeft = mount.scrollWidth;
  const wr = mount.querySelector("th.bi-c-wr").getBoundingClientRect();
  const mr = mount.getBoundingClientRect();
  return {wrR: wr.right, wrL: wr.left, mL: mr.left,
          mR: mr.left + mount.clientLeft + mount.clientWidth};
}"""

_FOCUSED = """(sel) => {
  const mount = document.querySelector(sel);
  const el = document.activeElement;
  const mr = mount.getBoundingClientRect();
  const r = el.getBoundingClientRect();
  return {inMount: mount.contains(el),
          col: (el.closest("th") || {}).className || "",
          l: r.left, r: r.right, mL: mr.left + mount.clientLeft,
          mR: mr.left + mount.clientLeft + mount.clientWidth,
          sl: mount.scrollLeft};
}"""


def _open(pw_browser, mock_server, w, h, tab):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": w, "height": h})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + "/?ui_mock=1#build-insights",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "document.querySelector('#bi-table-mount table.bi-table') !== null",
        timeout=10_000)
    if tab != "items":
        page.click(f'#bi-tabs [data-bi-tab="{tab}"]')
    page.wait_for_function(
        f"document.querySelector('{_MOUNT[tab]} table.bi-table "
        "th.bi-c-wr') !== null", timeout=10_000)
    page.evaluate(_SETTLE)
    return ctx, page, errors


@pytest.fixture(scope="module", params=_CASES, ids=_IDS)
def narrow(request, mock_server, pw_browser):
    w, h, tab = request.param
    ctx, page, errors = _open(pw_browser, mock_server, w, h, tab)
    try:
        data = page.evaluate(_READ, _MOUNT[tab])
        end = page.evaluate(_END, _MOUNT[tab])
        page.evaluate(f"document.querySelector('{_MOUNT[tab]}')"
                      ".scrollLeft = 0")
        page.focus(f"{_MOUNT[tab]} th.bi-c-wr .bi-sort-btn")
        page.evaluate(_SETTLE)
        focus = page.evaluate(_FOCUSED, _MOUNT[tab])
        page.keyboard.press("Enter")
        page.evaluate(_SETTLE)
        resort = page.evaluate(_FOCUSED, _MOUNT[tab])
        # Back to the first sortable column from the far end (Shift+Tab
        # from Buys lands on WPA, here focused directly).
        page.evaluate(f"document.querySelector('{_MOUNT[tab]}')"
                      ".scrollLeft = 1e6")
        page.focus(f"{_MOUNT[tab]} th.bi-c-wpa .bi-sort-btn")
        page.evaluate(_SETTLE)
        back = page.evaluate(_FOCUSED, _MOUNT[tab])
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors at {w} {tab}: {errors[:3]}"
    return {"w": w, "tab": tab, "d": data, "end": end, "focus": focus,
            "resort": resort, "back": back}


def test_view_does_not_scroll_sideways(narrow):
    d = narrow["d"]
    assert d["sec"][0] <= d["sec"][1] + 1, (
        f"{narrow['w']} {narrow['tab']}: #view-build-insights scrolls "
        f"sideways, scrollWidth {d['sec'][0]} > clientWidth {d['sec'][1]}")
    assert d["doc"][0] <= d["doc"][1] + 1, (
        f"{narrow['w']} {narrow['tab']}: the page scrolls sideways "
        f"({d['doc'][0]} > {d['doc'][1]})")


def test_table_mount_inside_its_pane(narrow):
    d = narrow["d"]
    left, right = d["paneIn"]
    m = d["mount"]
    assert m["l"] >= left - 1 and m["r"] <= right + 1, (
        f"{narrow['w']} {narrow['tab']}: mount {m['l']:.0f}-{m['r']:.0f} "
        f"outside the pane content box {left:.0f}-{right:.0f}")


def test_table_scrolls_inside_its_mount(narrow):
    d = narrow["d"]
    m = d["mount"]
    assert m["ox"] in ("auto", "scroll"), (
        f"{narrow['w']} {narrow['tab']}: mount overflow-x {m['ox']!r}")
    # The whole table is in the mount's scroll range, never clipped away.
    assert m["sw"] + 1 >= d["tableW"], (
        f"{narrow['w']} {narrow['tab']}: mount scrollWidth {m['sw']} < "
        f"table width {d['tableW']:.0f}")
    assert m["sh"] <= m["ch"] + 1, (
        f"{narrow['w']} {narrow['tab']}: the mount scrolls vertically "
        f"({m['sh']} > {m['ch']})")


def test_last_column_reachable(narrow):
    e = narrow["end"]
    assert e["wrR"] <= e["mR"] + 1 and e["wrL"] >= e["mL"] - 1, (
        f"{narrow['w']} {narrow['tab']}: scrolled to the end, Win Rate "
        f"{e['wrL']:.0f}-{e['wrR']:.0f} is not inside the mount "
        f"{e['mL']:.0f}-{e['mR']:.0f}")


@pytest.mark.parametrize("key,col", [("focus", "bi-c-wr"),
                                     ("resort", "bi-c-wr"),
                                     ("back", "bi-c-wpa")])
def test_keyboard_brings_sort_button_into_view(narrow, key, col):
    f = narrow[key]
    assert f["inMount"] and col in f["col"].split(), (
        f"{narrow['w']} {narrow['tab']} {key}: focus is not on the {col} "
        f"sort button ({f['col']!r})")
    assert f["l"] >= f["mL"] - 1 and f["r"] <= f["mR"] + 1, (
        f"{narrow['w']} {narrow['tab']} {key}: the focused {col} button "
        f"{f['l']:.0f}-{f['r']:.0f} is not wholly inside the mount "
        f"{f['mL']:.0f}-{f['mR']:.0f} (scrollLeft {f['sl']})")


@pytest.mark.parametrize("w,h", [(1920, 920), (1280, 900)])
def test_desktop_rail_beside_table_and_no_scroll(mock_server, pw_browser,
                                                 w, h):
    ctx, page, errors = _open(pw_browser, mock_server, w, h, "items")
    try:
        d = page.evaluate(_READ, _MOUNT["items"])
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors at {w}: {errors[:3]}"
    m = d["mount"]
    assert m["sw"] <= m["cw"] + 1, f"{w}: the Items mount scrolls ({m})"
    assert d["rail"] is not None and d["rail"] >= m["r"], (
        f"{w}: the TAKEAWAY rail ({d['rail']}) is not right of the table "
        f"mount (right {m['r']:.0f})")
    assert d["sec"][0] <= d["sec"][1] + 1


def test_mid_width_table_keeps_its_own_width(mock_server, pw_browser):
    # 1000 px: stacked (under the 1200 line) and the table fits, so the
    # mount still shrink-wraps the table instead of stretching it.
    ctx, page, errors = _open(pw_browser, mock_server, 1000, 900, "items")
    try:
        d = page.evaluate(_READ, _MOUNT["items"])
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors at 1000: {errors[:3]}"
    m = d["mount"]
    room = d["paneIn"][1] - d["paneIn"][0]
    assert m["sw"] <= m["cw"] + 1, f"1000: the Items mount scrolls ({m})"
    assert abs(m["cw"] - d["tableW"]) <= 1 and d["tableW"] < room - 40, (
        f"1000: the table ({d['tableW']:.0f}) is stretched to the mount "
        f"({m['cw']}) / pane ({room:.0f})")
