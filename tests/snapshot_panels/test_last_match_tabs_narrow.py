"""
tests/snapshot_panels/test_last_match_tabs_narrow.py
The Post Game Review tab strip (AI Analysis / Graph / Build / Review)
fits its nav in a narrow window: the strip wraps BETWEEN tabs and a tab
label never breaks inside itself (s144 lane uiux, RM-1782; the U-165
FUTURE row "the Post Game Review tab strip at 480"). 400% zoom of the
1920x920 baseline is 480 wide; WCAG 1.4.10 reflows at 320.

Measured before the fix (headless Chromium, ?ui_mock=1&mode=<sr|aram|
arena>#last-match, the same numbers in all three modes):
  - .lm-tabs-strip was a nowrap flex row of four tabs with a 96 px
    min-width each, so it could not get narrower than 409 px. At 480 it
    ran from x 72 to 481 in a nav whose content box ends at 408; at 320
    the nav ends at 248, so Build and Review lay wholly outside it;
  - from about 560 down the tabs shrank instead: AI Analysis 130 ->
    103 px and Review 108 -> 96 px, so both labels broke onto two lines
    (a 62 px tall tab, the Review arrow alone on the second line).
The hero identity row and the Quick Review columns run past the view at
the same widths; they are NOT this guard's subject (QA ledger FUTURE).

Contract pinned in all three modes at 1920x920, 722x900, 640x900,
560x900, 480x800, 400x800, 360x740 and 320x640:
  - every tab lies inside the nav's content box and the strip does not
    scroll sideways;
  - every tab label is one line: the tab is its 42 px min-height tall
    (the hit floor), never taller, and at least 42 px wide;
  - the tabs keep DOM order in reading order (each later tab is on the
    same line further right, or on a later line);
  - each tab's 2 px focus ring at 2 px offset lies inside the tabbed
    section's border box;
  - when the strip wraps, Review ends its last line at the nav's right
    content edge (it is the "leaves this view" control).
Above 640 nothing moves: at 1920, 722 and 640 the four tabs share one
line at 0 / 136 / 238 / 340 px from the nav's content left, 130 / 96 /
96 / 108 px wide (border box), as before.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_SIZES = ((1920, 920), (722, 900), (640, 900), (560, 900), (480, 800),
          (400, 800), (360, 740), (320, 640))
_MODES = ("sr", "aram", "arena")
_ONE_LINE_MIN = 640
_CASES = [(w, h, m) for (w, h) in _SIZES for m in _MODES]
_IDS = [f"{m}-{w}" for (w, h, m) in _CASES]
_WIDE_LEFTS = (0, 136, 238, 340)
_WIDE_WIDTHS = (130, 96, 96, 108)
_RING = 4  # 2 px outline + 2 px outline-offset (.lm-tab:focus-visible)

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)

_READ = """() => {
  const nav = document.querySelector("#lm-tabbed-section .lm-tabs-nav");
  const strip = nav.querySelector(".lm-tabs-strip");
  const sec = document.getElementById("lm-tabbed-section");
  const ncs = getComputedStyle(nav);
  const nr = nav.getBoundingClientRect();
  const left = nr.left + parseFloat(ncs.borderLeftWidth)
    + parseFloat(ncs.paddingLeft);
  const right = nr.right - parseFloat(ncs.borderRightWidth)
    - parseFloat(ncs.paddingRight);
  const sr = sec.getBoundingClientRect();
  const tabs = [...strip.querySelectorAll(".lm-tab")].map((b) => {
    const r = b.getBoundingClientRect();
    return {text: b.textContent.trim(), nav: b.classList.contains(
      "lm-tab-nav"), l: r.left, r: r.right, t: r.top, b: r.bottom,
      w: r.width, h: r.height,
      minH: parseFloat(getComputedStyle(b).minHeight)};
  });
  return {box: [left, right], sec: [sr.left, sr.right, sr.top, sr.bottom],
          strip: [strip.scrollWidth, strip.clientWidth], tabs};
}"""


@pytest.fixture(scope="module", params=_CASES, ids=_IDS)
def tabs_at(request, mock_server, pw_browser):
    w, h, mode = request.param
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": w, "height": h})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + f"/?ui_mock=1&mode={mode}#last-match",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "(() => { const t = document.getElementById('lm-mode-tag');"
            " return t && t.textContent.trim() !== '-'; })()",
            timeout=10_000)
        page.evaluate(_SETTLE)
        data = page.evaluate(_READ)
    finally:
        page.close()
        ctx.close()
    return w, mode, data, errors


def test_no_page_errors(tabs_at):
    w, mode, _d, errors = tabs_at
    assert errors == [], f"{mode} {w}: {errors}"


def test_four_tabs_review_last(tabs_at):
    w, mode, d, _e = tabs_at
    assert [t["nav"] for t in d["tabs"]] == [False, False, False, True], (
        f"{mode} {w}: {[t['text'] for t in d['tabs']]}")


def test_every_tab_inside_the_nav(tabs_at):
    w, mode, d, _e = tabs_at
    left, right = d["box"]
    out = [f"{t['text']} {t['l']:.0f}-{t['r']:.0f}" for t in d["tabs"]
           if t["l"] < left - 1 or t["r"] > right + 1]
    assert not out, f"{mode} {w}: nav box {left:.0f}-{right:.0f}: {out}"
    sw, cw = d["strip"]
    assert sw <= cw + 1, f"{mode} {w}: strip scrolls sideways {sw} > {cw}"


def test_every_label_is_one_line_at_the_hit_floor(tabs_at):
    w, mode, d, _e = tabs_at
    for t in d["tabs"]:
        assert t["minH"] >= 42, f"{mode} {w}: {t['text']} min {t['minH']}"
        assert t["minH"] - 0.5 <= t["h"] <= t["minH"] + 0.5, (
            f"{mode} {w}: {t['text']} is {t['h']:.1f} px tall"
            f" (label broke onto a second line)")
        assert t["w"] >= 42, f"{mode} {w}: {t['text']} {t['w']:.1f} wide"


def test_tabs_keep_reading_order(tabs_at):
    w, mode, d, _e = tabs_at
    tabs = d["tabs"]
    for a, b in zip(tabs, tabs[1:]):
        same_line = abs(a["t"] - b["t"]) < 1
        assert (same_line and b["l"] >= a["r"]) or b["t"] >= a["b"], (
            f"{mode} {w}: {b['text']} is not after {a['text']}")


def test_focus_ring_inside_the_tabbed_section(tabs_at):
    w, mode, d, _e = tabs_at
    sl, sr_, st, sb = d["sec"]
    for t in d["tabs"]:
        assert t["l"] - _RING >= sl and t["r"] + _RING <= sr_, (
            f"{mode} {w}: {t['text']} ring {t['l'] - _RING:.0f}-"
            f"{t['r'] + _RING:.0f} outside {sl:.0f}-{sr_:.0f}")
        assert t["t"] - _RING >= st and t["b"] + _RING <= sb, (
            f"{mode} {w}: {t['text']} ring outside the section vertically")


def test_wrapped_review_ends_at_the_nav_right_edge(tabs_at):
    w, mode, d, _e = tabs_at
    tabs = d["tabs"]
    if len({round(t["t"]) for t in tabs}) == 1:
        return
    review = tabs[-1]
    assert abs(review["r"] - d["box"][1]) <= 1, (
        f"{mode} {w}: Review ends at {review['r']:.0f},"
        f" nav content edge {d['box'][1]:.0f}")
    assert review["t"] >= max(t["t"] for t in tabs[:-1]), (
        f"{mode} {w}: Review is not on the last line")


def test_unchanged_at_640_and_wider(tabs_at):
    w, mode, d, _e = tabs_at
    if w < _ONE_LINE_MIN:
        pytest.skip("narrow: the strip may wrap")
    tabs = d["tabs"]
    left = d["box"][0]
    assert len({round(t["t"]) for t in tabs}) == 1, f"{mode} {w}: wrapped"
    for t, x, wd in zip(tabs, _WIDE_LEFTS, _WIDE_WIDTHS):
        assert abs((t["l"] - left) - x) <= 1, (
            f"{mode} {w}: {t['text']} at +{t['l'] - left:.1f}, want +{x}")
        assert abs(t["w"] - wd) <= 1, (
            f"{mode} {w}: {t['text']} {t['w']:.1f} wide, want {wd}")


def test_narrow_widths_wrap_rather_than_overflow(tabs_at):
    w, mode, d, _e = tabs_at
    if w > 480:
        pytest.skip("only 480 and under must wrap")
    lines = len({round(t["t"]) for t in d["tabs"]})
    assert lines >= 2, f"{mode} {w}: the four tabs stayed on one line"
