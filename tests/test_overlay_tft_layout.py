"""TFT overlay default layout vs the TFT HUD (S134 N9, source-parsing).

The TFT widget defaults (web/js/lib/overlay_layout.js TFT_WIDGETS) must not
cover the parts of the TFT screen the player reads or clicks: the stage strip,
the FPS / settings block, the scoreboard, the trait panel, the board and bench,
the shop, and the augment / carousel choice UI. They must also stay on screen
and clear of the overlay's own controls (the menu launcher and the rc-shell
ON/OFF icon) and of the slot reserved for the TFT-14 planner picker
(web/js/lib/overlay_tft.js TFT_PLANNER_SLOT).

KEEP-OUT PROVENANCE. Measured 2026-10-25 off the real match-3 frames
(ops/runtime/tft_qa/20261025-085349/frames/vision_*.jpg: the 2560x1440 game,
saved at 1280x720 by the vision relay, so x1.5 maps a frame pixel onto the
1920x1080 design px the overlay field uses; the overlay body zoom maps design px
back onto the 2560x1440 screen). Frames read: vision_0041 (3-3 planning, shop
open), vision_0066 (4-5, full board), vision_0080 (5-2, a scoreboard hover card
open), vision_0019 (2-4 carousel), vision_0034 (3-2 augment choice). Each box is
the union over those frames, rounded outward. The frames carry player names
and stay gitignored; only these numbers are recorded.

HEIGHTS. Measured in a headless Chromium render of the overlay page at
1920x1080 with the sanitised real fixtures (tests/snapshot_panels/fixtures/
tft_overlay_*.json): the vitals and board boxes are identical across the
sentinel, live and feed payloads (fixed slots, no reflow). The live browser
check of the same boxes against the same table is
tests/snapshot_panels/test_overlay_tft_view.py.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LAYOUT_JS = REPO / "web" / "js" / "lib" / "overlay_layout.js"
TFT_JS = REPO / "web" / "js" / "lib" / "overlay_tft.js"
TOGGLE_JS = REPO / "rc-shell" / "src" / "overlay_toggle.js"
OVERLAY_CSS = REPO / "web" / "css" / "overlay.css"

DESIGN_W = 1920
DESIGN_H = 1080
BOTTOM_MARGIN = 16  # overlay_layout._applyPos: availH = H - y - 16

# (x0, y0, x1, y1) in design px. See the module docstring for provenance.
KEEP_OUT = {
    # stage label, round icons, phase timer + progress bar (top centre)
    "stage_strip": (715, 0, 1205, 64),
    # FPS / ping readout + the two top-right buttons
    "fps_block": (1420, 0, 1690, 52),
    # player list (portraits, names, HP), the hover card it opens to the left
    # (vision_0080), and the two small buttons above it at the right edge
    "scoreboard": (1600, 60, 1920, 852),
    # trait panel (left edge)
    "traits": (0, 240, 300, 826),
    # far half of the board + item orbs + carousel portals + the opponent banner
    "board_far": (380, 62, 1450, 400),
    # near half, bench row, tactician, the two bottom corner pillars
    "board_near": (300, 400, 1560, 862),
    # level / XP / odds row, gold, streak, the bottom-right counter box, shop
    "shop": (228, 862, 1466, DESIGN_H),
    # augment choice: the three cards, their reroll buttons, the confirm button
    "augment_cards": (370, 190, 1560, 805),
    "augment_reroll": (495, 830, 1425, 888),
    "augment_confirm": (850, 950, 1070, 1024),
    # TFT's own emote button (top-left corner)
    "emote_button": (0, 0, 56, 38),
}

# Natural heights (design px), measured - see HEIGHTS above. Re-measured
# S135 (after the UI-audit head backing, which keeps the same height): the
# s134 values sat 1-2 px under the rendered boxes.
NATURAL_H = {
    "w-tft-hud": 123,
    "w-tft-lobby": 60,
    "w-tft-board": 146,
}

# The launcher is shared by every game and its default (24,24) predates TFT:
# it overlaps the lower edge of TFT's emote button (24..56 x 24..38). Not a
# board / shop / scoreboard region, and the operator's saved launcher spot is
# elsewhere; recorded here so it is a decision, not an accident. Every TFT
# widget is still checked against the emote button.
LAUNCHER_EXEMPT = {"emote_button"}

_TFT_BLOCK = re.compile(r"const TFT_WIDGETS = \[(.*?)^\];", re.M | re.S)
_ENTRY = re.compile(
    r'\{\s*id:\s*"(?P<id>[^"]+)"\s*,\s*sel:\s*"(?P<sel>[^"]+)"[^{}]*?'
    r"\bx:\s*(?P<x>-?\d+)\s*,\s*y:\s*(?P<y>-?\d+)\s*,\s*w:\s*(?P<w>\d+)"
    r'[^{}]*?\bgame:\s*"(?P<game>[^"]+)"'
)
_LAUNCHER = re.compile(r"const LAUNCHER = \{[^{}]*?\bx:\s*(\d+)\s*,\s*y:\s*(\d+)")
_LAUNCHER_W = re.compile(r"\.ovx-launcher\s*\{[^{}]*?\bwidth:\s*(\d+)px", re.S)
_PLANNER = re.compile(r"export const TFT_PLANNER_SLOT = Object\.freeze\(\{(.*?)\}\);", re.S)


def _num(block: str, key: str) -> int:
    m = re.search(r"\b" + key + r":\s*(\d+)", block)
    assert m, f"{key} not found in {block!r}"
    return int(m.group(1))


def _tft_widgets():
    js = LAYOUT_JS.read_text(encoding="utf-8")
    block = _TFT_BLOCK.search(js)
    assert block, "TFT_WIDGETS array not found in overlay_layout.js"
    out = [m.groupdict() for m in _ENTRY.finditer(block.group(1))]
    for w in out:
        for k in ("x", "y", "w"):
            w[k] = int(w[k])
    return out


def _box(x, y, w, h):
    return (x, y, x + w, y + h)


def _overlap(a, b):
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    return (dx, dy) if dx > 0 and dy > 0 else None


def tft_default_boxes() -> dict:
    """Default design-px box per TFT widget id (shared with the browser test)."""
    out = {}
    for w in _tft_widgets():
        h = min(NATURAL_H[w["id"]], DESIGN_H - w["y"] - BOTTOM_MARGIN)
        out[w["id"]] = _box(w["x"], w["y"], w["w"], h)
    return out


def control_boxes() -> dict:
    js = LAYOUT_JS.read_text(encoding="utf-8")
    lm = _LAUNCHER.search(js)
    assert lm, "LAUNCHER default not found"
    lw = _LAUNCHER_W.search(OVERLAY_CSS.read_text(encoding="utf-8"))
    assert lw, ".ovx-launcher width not found in overlay.css"
    side = int(lw.group(1))
    tog = TOGGLE_JS.read_text(encoding="utf-8")
    tx, ty, ts = _num(tog, "designX"), _num(tog, "designY"), _num(tog, "baseSize")
    return {
        "w-launcher": _box(int(lm.group(1)), int(lm.group(2)), side, side),
        "rc-shell-toggle": _box(tx, ty, ts, ts),
    }


def planner_box():
    m = _PLANNER.search(TFT_JS.read_text(encoding="utf-8"))
    assert m, "TFT_PLANNER_SLOT not found in overlay_tft.js"
    b = m.group(1)
    x, y, w = _num(b, "x"), _num(b, "y"), _num(b, "w")
    return _box(x, y, w, DESIGN_H - y - BOTTOM_MARGIN)


class TftOverlayLayout(unittest.TestCase):
    def test_parser_reads_the_three_tft_widgets(self):
        ws = _tft_widgets()
        self.assertEqual(sorted(w["id"] for w in ws), ["w-tft-board", "w-tft-hud", "w-tft-lobby"])
        for w in ws:
            self.assertEqual(w["game"], "tft", w["id"])
            self.assertIn(w["id"], NATURAL_H, f"{w['id']} has no measured height budget")

    def test_keep_out_table_is_not_vacuous(self):
        # An empty or degenerate table would pass every check below.
        self.assertGreaterEqual(len(KEEP_OUT), 10)
        for name, (x0, y0, x1, y1) in KEEP_OUT.items():
            self.assertTrue(0 <= x0 < x1 <= DESIGN_W and 0 <= y0 < y1 <= DESIGN_H, name)
        # positive control: a box on the board centre must be caught
        self.assertTrue(any(_overlap((900, 500, 1000, 600), r) for r in KEEP_OUT.values()))

    def test_every_tft_default_stays_on_screen(self):
        for wid, b in tft_default_boxes().items():
            self.assertTrue(0 <= b[0] and b[2] <= DESIGN_W and 0 <= b[1] and b[3] <= DESIGN_H,
                            f"{wid} {b} leaves the 1920x1080 design field")

    def test_no_tft_default_covers_the_tft_hud(self):
        bad = []
        for wid, b in tft_default_boxes().items():
            for name, r in KEEP_OUT.items():
                ov = _overlap(b, r)
                if ov:
                    bad.append(f"{wid} {b} x {name} {r}: {ov[0]}x{ov[1]} px")
        self.assertEqual(bad, [], "TFT widget default covers the TFT HUD")

    def test_tft_defaults_clear_each_other_the_controls_and_the_planner_slot(self):
        boxes = dict(tft_default_boxes())
        boxes.update(control_boxes())
        boxes["planner-slot"] = planner_box()
        ids = sorted(boxes)
        bad = []
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if {a, b} == {"w-launcher", "rc-shell-toggle"}:
                    continue  # both pre-date TFT and are stacked by design
                ov = _overlap(boxes[a], boxes[b])
                if ov:
                    bad.append(f"{a} {boxes[a]} x {b} {boxes[b]}: {ov[0]}x{ov[1]} px")
        self.assertEqual(bad, [])

    def test_the_planner_slot_is_clear_of_the_tft_hud(self):
        p = planner_box()
        for name, r in KEEP_OUT.items():
            self.assertIsNone(_overlap(p, r), f"planner slot {p} x {name} {r}")

    def test_controls_are_clear_of_the_tft_hud_except_the_recorded_residual(self):
        for cid, b in control_boxes().items():
            for name, r in KEEP_OUT.items():
                if cid == "w-launcher" and name in LAUNCHER_EXEMPT:
                    continue
                self.assertIsNone(_overlap(b, r), f"{cid} {b} x {name} {r}")
        # the exemption is real (not a stale excuse): the overlap still exists
        self.assertIsNotNone(_overlap(control_boxes()["w-launcher"], KEEP_OUT["emote_button"]))


if __name__ == "__main__":
    unittest.main()
