"""
tests/snapshot_panels/test_history_row_hover_marks_contrast.py
RM-1555 (s144 uiux) - the History / Session row marks stay at WCAG AA
(4.5:1) while their row is HOVERED, in every theme.

RM-1550 pinned the session row W / L counts (.hs-w / .hs-l) and RM-1551
the match row grade chip (.home-recent-grade X), both measured with the
pointer parked at (0, 0), so only the resting and the selected (.active) fill
were seen. A hovered row swaps its fill: a session row to --surface-2
(header.css .history-session-row:hover), a neutral match row to --info-soft
(home.css .history-match-row-clickable:hover:not(.result-*)). Win / loss
match rows keep their result tint on hover (RM-1315), so they are measured
too, as the control that the hover really landed.

WHAT IS MEASURED (headless Chromium at 1920x920, transitions off; each row is
hovered with the real mouse, never a forced class; colours resolved by the
browser, oklch and color-mix included, lane doc trap 3; a translucent fill
composited over the first opaque ancestor, so the PAIR is measured, never the
token, trap 4):
  - every session row of /?ui_mock=1#history, hovered: its .hs-w / .hs-l
    count (16px weight 700);
  - every match row of that view (first session chosen) and of
    /?ui_mock=1#session, hovered: its grade chip re-classed in place through
    all six letters S A B C D F (16px weight 900). The fixtures hold no F
    grade and one D, so the chip CSS is the subject and the fixture only
    supplies real row contexts.
Neither text is WCAG "large", so the 4.5:1 bar applies. Each mark must also
keep its hue (a loss / low grade reads red, a win / A / B reads green), so a
fix can only move the text, never drop the encoding.
"""
import re
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

ROOT = Path(__file__).resolve().parent.parent.parent
_GRADES = ("S", "A", "B", "C", "D", "F")


def _themes():
    # "hextech" is the DEFAULT palette at :root (web/css/themes.css header);
    # no [data-theme="hextech"] block exists, so stamping it selects :root.
    text = (ROOT / "web" / "css" / "themes.css").read_text(encoding="utf-8")
    found = set(re.findall(r':root\[data-theme="([a-z0-9_-]+)"\]', text))
    return ["hextech"] + sorted(found - {"hextech"})


_THEMES = _themes()

_HELPERS_JS = r"""
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => {
    cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c;
    cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  };
  const over = (top, base) => [0, 1, 2].map(
    (i) => top[i] * top[3] + base[i] * (1 - top[3]));
  const fill = (el) => {
    const layers = [];
    for (let n = el; n; n = n.parentElement) {
      const b = rgba(getComputedStyle(n).backgroundColor);
      if (b[3] > 0) layers.push(b);
      if (b[3] >= 1) break;
    }
    if (!layers.length || layers[layers.length - 1][3] < 1) return null;
    let acc = layers.pop().slice(0, 3);
    while (layers.length) acc = over(layers.pop(), acc);
    return acc;
  };
  const kind = (row) => row.classList.contains('result-win') ? 'win'
    : row.classList.contains('result-loss') ? 'loss' : 'neutral';
"""

# Measure the marks of ONE row (args: [rowSelector, index, grades]). The
# row's own :hover state is read back, so a missed hover is visible.
_MEASURE_ROW_JS = "async (args) => {\n" + _HELPERS_JS + r"""
  const [sel, idx, grades] = args;
  const row = document.querySelectorAll(sel)[idx];
  const out = {hovered: row.matches(':hover'), rowKind: kind(row),
               rowFill: rgba(getComputedStyle(row).backgroundColor),
               marks: []};
  for (const [cls, res] of [['.hs-w', 'win'], ['.hs-l', 'loss']]) {
    const el = row.querySelector(cls);
    if (!el || !el.getClientRects().length) continue;
    const cs = getComputedStyle(el);
    out.marks.push({mark: 'count', key: res, color: rgba(cs.color),
                    fill: fill(el), fontSize: parseFloat(cs.fontSize)});
  }
  const chip = row.querySelector(':scope > .home-recent-grade');
  if (chip && chip.getClientRects().length && grades.length) {
    const prev = chip.className;
    for (const g of grades) {
      chip.className = 'home-recent-grade ' + g;
      const cs = getComputedStyle(chip);
      out.marks.push({mark: 'grade', key: g, color: rgba(cs.color),
                      fill: fill(chip), fontSize: parseFloat(cs.fontSize)});
    }
    chip.className = prev;
  }
  return out;
}
"""


def _lum(c) -> float:
    def ch(v: float) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def _ratio(a, b) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _open(page, url, view, ready):
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(f"document.body.dataset.view === '{view}'",
                           timeout=10_000)
    page.wait_for_function(ready, timeout=10_000)


# Hover and theme flips below must not straddle a transition (RM-1132).
_CALM = ("*, *::before, *::after { transition: none !important;"
         " animation: none !important; }")
# view: (row selector the scan hovers, grade letters it re-classes through).
_SCANS = {
    "session-rows": ("#history-session-list .history-session-row", ()),
    "history": ("#history-match-list > li.history-match-row", _GRADES),
    "session": ("#session-matches > li.history-match-row", _GRADES),
}


def _open_view(page, mock_server, page_view):
    """Open #history (session rows + the first session's match rows) or
    #session, transitions off, as the measured fixture does."""
    if page_view == "history":
        _open(page, mock_server.url + "/?ui_mock=1#history", "history",
              "document.querySelector('#history-session-list"
              " .history-session-row')")
        page.click("#history-session-list .history-session-row")
        page.wait_for_function(
            "document.querySelectorAll('#history-match-list"
            " .history-match-row .home-recent-grade').length >= 2",
            timeout=10_000)
    else:
        _open(page, mock_server.url + "/?ui_mock=1#session", "session",
              "document.querySelector('#session-matches .home-recent-grade')")
    page.add_style_tag(content=_CALM)


def _hover_scan(page, out, view, sel, grades):
    n = page.evaluate("(s) => document.querySelectorAll(s).length", sel)
    for t in _THEMES:
        page.evaluate(
            "(t) => document.documentElement.setAttribute('data-theme', t)", t)
        rows = []
        for i in range(n):
            page.locator(sel).nth(i).hover()
            rows.append(page.evaluate(_MEASURE_ROW_JS, [sel, i, grades]))
        page.mouse.move(0, 0)
        out[(view, t)] = rows


@pytest.fixture(scope="module")
def measured(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    out = {}
    try:
        _open_view(page, mock_server, "history")
        for view in ("session-rows", "history"):
            sel, grades = _SCANS[view]
            _hover_scan(page, out, view, sel, list(grades))
        _open_view(page, mock_server, "session")
        sel, grades = _SCANS["session"]
        _hover_scan(page, out, "session", sel, list(grades))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
    return out


def test_hover_scan_anchor(measured):
    assert len(_THEMES) >= 6, _THEMES
    for t in _THEMES:
        srows = measured[("session-rows", t)]
        # Every row really hovered, and at least one session row carries
        # both counts (an empty scan would pass every ratio test vacuously).
        assert srows and all(r["hovered"] for r in srows), t
        keys = {m["key"] for r in srows for m in r["marks"]}
        assert {"win", "loss"} <= keys, (t, keys)
        hist = measured[("history", t)]
        assert hist and all(r["hovered"] for r in hist), t
        sess = measured[("session", t)]
        assert sess and all(r["hovered"] for r in sess), t
        # The History fixture rows are all win / loss, the Session rows all
        # neutral, so between them every hover fill is measured.
        kinds = {r["rowKind"] for r in hist + sess}
        assert {"neutral", "win", "loss"} <= kinds, (t, kinds)
        # The hover really swapped the fill: a hovered neutral match row
        # paints --info-soft, never the resting --surface.
        assert all(r["rowFill"][3] < 1 for r in sess), t
    # The theme flip must really repaint, or every theme measures one palette.
    fills = {tuple(measured[("session-rows", t)][-1]["rowFill"])
             for t in _THEMES}
    assert len(fills) >= 3, f"theme flip inert: {fills}"


@pytest.mark.parametrize("view", ("session-rows", "history", "session"))
@pytest.mark.parametrize("theme", _THEMES)
def test_every_mark_on_a_hovered_row_reaches_aa(view, theme, measured):
    bad = []
    for r in measured[(view, theme)]:
        for m in r["marks"]:
            assert m["fill"] is not None, (view, theme, m)
            assert m["fontSize"] < 24, m  # not "large": 4.5:1 applies
            ratio = _ratio(m["color"], m["fill"])
            if ratio < 4.5:
                bad.append(
                    f"{m['mark']} {m['key']} on hovered {r['rowKind']} row:"
                    f" rgb{tuple(m['color'][:3])} on"
                    f" rgb{tuple(round(v) for v in m['fill'])}"
                    f" = {ratio:.2f}:1")
    assert not bad, f"{view}/{theme}: below AA 4.5:1: {sorted(set(bad))}"


@pytest.mark.parametrize("theme", _THEMES)
def test_hovered_marks_keep_their_hue(theme, measured):
    bad = []
    for view in ("session-rows", "history", "session"):
        for r in measured[(view, theme)]:
            for m in r["marks"]:
                cr, cg, cb = m["color"][:3]
                red = m["key"] in ("loss", "D", "F")
                green = m["key"] in ("win", "A", "B")
                if red and not cr - max(cg, cb) >= 60:
                    bad.append((view, m["key"], "no longer reads red"))
                if green and not cg - max(cr, cb) >= 30:
                    bad.append((view, m["key"], "no longer reads green"))
    assert not bad, f"{theme}: {sorted(set(bad))}"
