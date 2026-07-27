"""Overlay default-layout collision guard (source-parsing).

WHY a Python guard and not a .test.mjs: the box a widget occupies is the JS
registry (x,y) crossed with the CSS width map, and only a Python test can read
BOTH web/js/lib/overlay_layout.js and web/css/overlay.css (plus web/index.html
to resolve a class-selector width override back to its widget id).

WHY it exists: the registry comment claims every default was checked against
every other default (LEDGER 873 (C): w-stats once shipped on top of w-call).
That check was only ever run for w-arambalance against the others - the
left-side cluster was never checked against itself, and w-build (x 70, width
412 -> right edge 482) shipped 52px underneath w-ovds (x 430, width 210).
Measured live at 1920x1080 in a populated overlay render: w-build box
x 70..482 / y 470..1064, w-ovds box x 430..640 / y 80..1007, so the overlap is
52 x 537 px and it truncates build text. This guard is the machine version of
the comment's promise.

HEIGHT MODEL. overlay_layout._applyPos gives every widget
--ovx-maxh = max(140, H - y - 16) with overflow-y:auto, so the painted height
is min(natural content height, that cap). Each natural height below is either a
LIVE MEASUREMENT from a headless overlay probe (cited per entry) or, for a
data-gated panel that no repo fixture populates, a conservative row-count
estimate. Conservative here means "at least as tall as the panel can get" -
under-estimating a height is what would let a real collision through.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LAYOUT_JS = REPO / "web" / "js" / "lib" / "overlay_layout.js"
OVERLAY_CSS = REPO / "web" / "css" / "overlay.css"
INDEX_HTML = REPO / "web" / "index.html"

# The authored design box (CLAUDE.md: the overlay field is design-px in
# 1920x1080; the body zoom scales it to the real window).
DESIGN_W = 1920
DESIGN_H = 1080

# overlay_layout._applyPos: availH = H - c.y - 16, floored at 140.
BOTTOM_MARGIN = 16
MAXH_FLOOR = 140

# Natural (uncapped) content height per widget id. Provenance per entry.
NATURAL_H = {
    # MEASURED, headless Chromium overlay probe at 1920x1080 (?ui_mock=1&mode=sr
    # &overlay=1, the drive path tests/snapshot_panels/test_overlay_view.py
    # _open_overlay uses): scrollHeight 670, painted 594 against the y=470 cap.
    "w-build": 670,
    # MEASURED, same probe: scrollHeight 925 / painted 927 (settings strip +
    # fight-model knobs). The leaner live-SSE envelope renders it at 713, so 927
    # is the tall end and therefore the conservative one.
    "w-ovds": 927,
    # MEASURED, same probe: 175 with the populated CALL fixture (104 on the
    # leaner live-SSE envelope). Rounded up.
    "w-call": 180,
    # MEASURED, live-SSE SR envelope probe (the tests/snapshot_panels/
    # test_next_buy_view.py _SR_STATE drive path): 102. Rounded up.
    "w-objgauges": 110,
    # MEASURED, same live-SSE SR probe: 82 for the 3 rule rows. Rounded up.
    "w-nextbuy": 90,
    # MEASURED: 34, and pinned by overlay.css .ovx-launcher height:34px.
    "w-launcher": 34,
    # ESTIMATE - no repo fixture populates the ARAM grid headlessly. The
    # registry comment in overlay_layout.js budgets 480 for a full 11-row lobby
    # off a measured 436 at 10 rows; reuse that number so both agree.
    "w-arambalance": 480,
    # ESTIMATE - one 16px --fs-xs line plus the 6px/8px .ovx-widget padding and
    # the frame, tripled for safety. The macro-lead pill is a single row.
    "w-lead": 48,
    # ESTIMATE - the A/B/C chip stack is at most 3 chip rows; a chip is a
    # ~40px hit target (overlay chip tokens), plus frame.
    "w-choices": 150,
    "w-callouts": 150,
    # ESTIMATE - a single floating glyph chip (overlay.css:603-608 strips the
    # frame + padding entirely), so one oversized line.
    "w-spike": 60,
    # ESTIMATE - overlay.css:469-474 documents 5 enemy rows that must each fit
    # on ONE line; 5 rows plus a head at the overlay row metric.
    "w-enemyspells": 210,
    # ESTIMATE - selection row + source badge + bracket + column head + 5 metric
    # rows (overlay.css:943-1014 enumerates exactly these parts).
    "w-stats": 240,
}

# The ONLY pair excluded from the no-overlap rule, because the two can never
# paint in the same game: renderAramBalance hides its mount outside the ARAM
# mode set (web/js/panels/aram_balance.js:210-217) and computeGauges returns
# null - widget hidden - whenever mode != "sr" (web/js/panels/
# objective_gauges.js:201). Every other widget is treated as always-present.
MODE_EXCLUSIVE = {frozenset({"w-arambalance", "w-objgauges"})}

_WIDGETS_BLOCK = re.compile(r"const WIDGETS = \[(.*?)^\];", re.M | re.S)
_LAUNCHER_LINE = re.compile(r"const LAUNCHER = (\{.*?\});", re.S)
_ENTRY = re.compile(
    r'\{\s*id:\s*"(?P<id>[^"]+)"\s*,\s*sel:\s*"(?P<sel>[^"]+)"'
    r"[^{}]*?\bx:\s*(?P<x>-?\d+)\s*,\s*y:\s*(?P<y>-?\d+)"
)
_CSS_RULE = re.compile(r"(?P<sel>[^{}]+)\{(?P<body>[^{}]*)\}", re.S)
_OVX_W = re.compile(r"--ovx-w:\s*(\d+)px")
_DEFAULT_W = re.compile(r"width:\s*var\(--ovx-w,\s*(\d+)px\)")
_LAUNCHER_W = re.compile(r"\.ovx-launcher\s*\{[^{}]*?\bwidth:\s*(\d+)px", re.S)


def _parse_widgets(js: str):
    block = _WIDGETS_BLOCK.search(js)
    assert block, "WIDGETS array not found in overlay_layout.js"
    out = [m.groupdict() for m in _ENTRY.finditer(block.group(1))]
    launcher = _LAUNCHER_LINE.search(js)
    assert launcher, "LAUNCHER entry not found in overlay_layout.js"
    lm = _ENTRY.search(launcher.group(1))
    assert lm, "LAUNCHER entry did not parse"
    out.append(lm.groupdict())
    for w in out:
        w["x"] = int(w["x"])
        w["y"] = int(w["y"])
    return out


def _id_for_class(html: str, cls: str):
    """Resolve a CSS class used as a width override back to the element id it
    is authored on, so a class-selector rule can be attributed to a widget."""
    pat = re.compile(r'class="[^"]*\b' + re.escape(cls) + r'\b[^"]*"')
    for tag in re.finditer(r"<[^>]+>", html):
        text = tag.group(0)
        if pat.search(text):
            idm = re.search(r'id="([^"]+)"', text)
            if idm:
                return idm.group(1)
    return None


def _parse_widths(css: str, html: str, widgets):
    dflt = _DEFAULT_W.search(css)
    assert dflt, "the .ovx-widget width: var(--ovx-w, Npx) default is missing"
    widths = {w["id"]: int(dflt.group(1)) for w in widgets}

    lw = _LAUNCHER_W.search(css)
    assert lw, ".ovx-launcher fixed width not found in overlay.css"
    widths["w-launcher"] = int(lw.group(1))

    unresolved = []
    for rule in _CSS_RULE.finditer(css):
        px = _OVX_W.search(rule.group("body"))
        if not px:
            continue
        sel = rule.group("sel")
        direct = re.search(r'data-ovx-id="([^"]+)"', sel)
        if direct:
            widths[direct.group(1)] = int(px.group(1))
            continue
        # Class-selector override (w-stats ships its width on .ovx-statspanel).
        wid = None
        for cls in re.findall(r"\.([A-Za-z0-9_-]+)", sel):
            if cls in ("ovx-widget",):
                continue
            eid = _id_for_class(html, cls)
            if not eid:
                continue
            for w in widgets:
                if "#" + eid in w["sel"]:
                    wid = w["id"]
                    break
            if wid:
                break
        if wid:
            widths[wid] = int(px.group(1))
        else:
            unresolved.append(sel.strip().splitlines()[-1].strip())
    # An unattributed width override would silently under-size a box and hide a
    # real collision, so it is a failure, not a skip.
    assert not unresolved, f"--ovx-w overrides not attributable to a widget: {unresolved}"
    return widths


def _boxes():
    js = LAYOUT_JS.read_text(encoding="utf-8")
    css = OVERLAY_CSS.read_text(encoding="utf-8")
    html = INDEX_HTML.read_text(encoding="utf-8")
    widgets = _parse_widgets(js)
    widths = _parse_widths(css, html, widgets)
    out = {}
    for w in widgets:
        wid = w["id"]
        assert wid in NATURAL_H, (
            f"{wid} has no documented height budget - add one to NATURAL_H "
            "(with its provenance) before shipping a new widget default")
        cap = max(MAXH_FLOOR, DESIGN_H - w["y"] - BOTTOM_MARGIN)
        h = min(NATURAL_H[wid], cap)
        out[wid] = (w["x"], w["y"], w["x"] + widths[wid], w["y"] + h)
    return out


def _overlap(a, b):
    x = min(a[2], b[2]) - max(a[0], b[0])
    y = min(a[3], b[3]) - max(a[1], b[1])
    return (x, y) if x > 0 and y > 0 else None


class DefaultLayoutCollision(unittest.TestCase):
    def setUp(self):
        self.boxes = _boxes()

    def test_registry_parsed(self):
        # Cheap canary: a registry edit that breaks the regex must not silently
        # turn this whole guard into a no-op.
        self.assertGreaterEqual(len(self.boxes), 12)
        self.assertIn("w-build", self.boxes)
        self.assertIn("w-ovds", self.boxes)
        self.assertIn("w-launcher", self.boxes)

    def test_widths_resolved_from_css(self):
        # The two widths the reported defect turns on, read from overlay.css.
        self.assertEqual(self.boxes["w-build"][2] - self.boxes["w-build"][0], 412)
        self.assertEqual(self.boxes["w-ovds"][2] - self.boxes["w-ovds"][0], 210)

    def test_every_default_box_fits_on_screen(self):
        bad = []
        for wid, (x1, y1, x2, y2) in sorted(self.boxes.items()):
            if x1 < 0 or y1 < 0 or x2 > DESIGN_W or y2 > DESIGN_H:
                bad.append(f"{wid} box ({x1},{y1})-({x2},{y2})")
        self.assertFalse(bad, "widget defaults outside the 1920x1080 design box: "
                              + "; ".join(bad))

    def test_no_two_default_boxes_overlap(self):
        ids = sorted(self.boxes)
        hits = []
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if frozenset({a, b}) in MODE_EXCLUSIVE:
                    continue
                ov = _overlap(self.boxes[a], self.boxes[b])
                if ov:
                    hits.append(
                        f"{a} {self.boxes[a]} vs {b} {self.boxes[b]} "
                        f"-> overlap {ov[0]}x{ov[1]}px")
        self.assertFalse(hits, "overlapping default widget boxes:\n  "
                               + "\n  ".join(hits))


if __name__ == "__main__":
    unittest.main()
