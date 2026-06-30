"""Typography-floor + hit-target + ASCII regression guard for the four
Post-Game-Review (PGR) child panels: Build-WPA (pgr_build_wpa), Lane
Compare (pgr_lane_compare), Loadout (pgr_loadout) and Win-Prob
(pgr_winprob).

R47 (LOOP cycle 13) 5-phase fixture audit deliverable. C3 (item 332)
audited the parent last_match.js/css but left these PGR child panels
without a dedicated machine guard. This file is that lock, mirroring the
R40 active-match child-panel guard
(tests/test_active_match_child_panel_floor_guard.py).

Three static-text contracts:

1. SubfloorFontExceptionTests (TYPOGRAPHY) - every hardcoded
   ``font-size: <N>px`` below the --fs-xs 16px floor in any PGR panel CSS
   carries an ``operator-exception`` annotation inside its own rule block.
   Today only pgr_winprob.css carries one (the inline-SVG chart-axis tick
   labels, a genuine chart-density exception); the other three panels are
   fully tokenized. The scan helper is exercised against synthetic BAD/GOOD
   fixtures so the guard provably has teeth.

2. DisplayOnlyHitTargetTests (HIT-TARGETS) - all four panels are
   display-only. No ``cursor: pointer`` rule may ship without
   ``min-height: var(--hit-min)`` in the same block, and no panel JS wires
   a click handler. The day someone wires a real clickable, it must meet
   the --hit-min 42px tap floor.

3. AsciiHygieneTests (ASCII) - no em/en-dash or smart quotes in any of the
   eight panel files. BAD dict built via chr() so this file stays clean.

STRUCTURE + HIERARCHY phases are render-shape concerns covered by the
existing DOM/snapshot suites (tests/test_pgr_*_panel_dom.py,
tests/snapshot_panels/test_historical_pgr_view.py); this file guards the
two phases that are pure static-text contracts plus ASCII.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS_DIR = ROOT / "web" / "css" / "panels"
JS_DIR = ROOT / "web" / "js" / "panels"

PANELS = ("pgr_build_wpa", "pgr_lane_compare", "pgr_loadout", "pgr_winprob")
CSS_FILES = {p: CSS_DIR / f"{p}.css" for p in PANELS}
JS_FILES = {p: JS_DIR / f"{p}.js" for p in PANELS}

# The global typography floor (docs/UI_SCALE_SPEC_V2.md): --fs-xs = 16px.
FS_XS_PX = 16

_FONT_SIZE_RE = re.compile(r"font-size:\s*(\d+)px")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _subfloor_font_lines(css: str) -> list[tuple[int, int]]:
    """Every literal ``font-size: <N>px`` declaration with N < the 16px
    floor. Token references (``var(--fs-xs, 16px)``) never match the regex
    anchor, so they are correctly ignored. Returns (1-based line, size)."""
    out: list[tuple[int, int]] = []
    for idx, line in enumerate(css.split("\n")):
        m = _FONT_SIZE_RE.search(line)
        if m and int(m.group(1)) < FS_XS_PX:
            out.append((idx + 1, int(m.group(1))))
    return out


def _unexcepted_subfloor(css: str) -> list[tuple[int, int]]:
    """Sub-floor font-sizes whose own rule block carries NO
    ``operator-exception`` annotation.

    The search walks backward from the font-size declaration to the rule
    opener ``{`` (the exception comment lives inside the block, above the
    declaration), so a stray exception comment in a DIFFERENT rule cannot
    falsely satisfy an un-annotated sub-floor size."""
    lines = css.split("\n")
    out: list[tuple[int, int]] = []
    for idx, line in enumerate(lines):
        m = _FONT_SIZE_RE.search(line)
        if not m or int(m.group(1)) >= FS_XS_PX:
            continue
        found = False
        j = idx - 1
        while j >= 0:
            cur = lines[j]
            if "operator-exception" in cur:
                found = True
                break
            if "{" in cur:  # reached this rule's opener - stop the walk
                break
            j -= 1
        if not found:
            out.append((idx + 1, int(m.group(1))))
    return out


def _pointer_rules_without_hitmin(css: str) -> list[str]:
    """Selectors that set ``cursor: pointer`` without also reserving
    ``min-height: var(--hit-min)`` in the same rule block."""
    bad: list[str] = []
    for chunk in css.split("}"):
        if "{" not in chunk:
            continue
        sel, body = chunk.split("{", 1)
        if "cursor: pointer" not in body and "cursor:pointer" not in body:
            continue
        if "var(--hit-min)" not in body:
            bad.append(sel.strip())
    return bad


class SubfloorFontExceptionTests(unittest.TestCase):
    """Every sub-floor font in any PGR panel is exception-annotated."""

    def test_no_unexcepted_subfloor_in_any_pgr_panel(self):
        for css_path in CSS_FILES.values():
            offenders = _unexcepted_subfloor(_read(css_path))
            self.assertEqual(
                [], offenders,
                f"{css_path.name} sub-floor font(s) missing an "
                f"operator-exception rationale (line, px): {offenders}")

    def test_winprob_axis_label_exception_present(self):
        # The lone sanctioned sub-floor: the inline-SVG chart-axis tick
        # labels. Guards against a silent re-introduction of an
        # un-annotated sub-floor OR the loss of the documented exception.
        css = _read(CSS_FILES["pgr_winprob"])
        self.assertTrue(
            _subfloor_font_lines(css),
            "pgr_winprob.css should still carry its annotated chart-axis "
            "sub-floor label size")
        self.assertEqual([], _unexcepted_subfloor(css))

    def test_scan_has_teeth(self):
        """RED-first proof: an un-annotated sub-floor IS flagged, and the
        same size WITH an in-block exception comment is NOT."""
        bad = ".x {\n  color: #fff;\n  font-size: 9px;\n}\n"
        good = (".x {\n  color: #fff;\n"
                "  /* operator-exception: density - PRESERVED. */\n"
                "  font-size: 9px;\n}\n")
        self.assertEqual([(3, 9)], _unexcepted_subfloor(bad))
        self.assertEqual([], _unexcepted_subfloor(good))
        # A >=16px size is never a sub-floor offender.
        self.assertEqual([], _unexcepted_subfloor(".y { font-size: 16px; }"))


class DisplayOnlyHitTargetTests(unittest.TestCase):
    """All four panels are display-only; any future clickable must meet
    --hit-min. No click handler is wired in any panel JS."""

    def test_no_pointer_without_hitmin(self):
        for css_path in CSS_FILES.values():
            self.assertEqual(
                [], _pointer_rules_without_hitmin(_read(css_path)),
                f"{css_path.name} cursor:pointer rule(s) lack "
                "min-height: var(--hit-min)")

    def test_pointer_scan_has_teeth(self):
        self.assertEqual(
            [".btn"],
            _pointer_rules_without_hitmin(".btn { cursor: pointer; }"))
        self.assertEqual(
            [],
            _pointer_rules_without_hitmin(
                ".btn { cursor: pointer; min-height: var(--hit-min); }"))

    def test_panels_wire_no_click_handler(self):
        for js_path in JS_FILES.values():
            js = _read(js_path)
            self.assertNotIn('addEventListener("click"', js,
                             f"{js_path.name} must stay display-only")
            self.assertNotIn("addEventListener('click'", js,
                             f"{js_path.name} must stay display-only")
            self.assertNotIn(".onclick", js,
                             f"{js_path.name} must stay display-only")


class AsciiHygieneTests(unittest.TestCase):
    """No em/en-dashes or smart quotes in the eight panel files (the
    CLAUDE.md hard rule). BAD dict via chr() so this file stays clean."""

    BAD = {
        chr(0x2013): "EN DASH",
        chr(0x2014): "EM DASH",
        chr(0x2018): "LEFT SINGLE QUOTE",
        chr(0x2019): "RIGHT SINGLE QUOTE",
        chr(0x201C): "LEFT DOUBLE QUOTE",
        chr(0x201D): "RIGHT DOUBLE QUOTE",
    }

    def _scan(self, path: Path) -> list[str]:
        text = path.read_text(encoding="utf-8")
        return [name for ch, name in self.BAD.items() if ch in text]

    def test_panel_files_are_ascii_clean(self):
        for panel in PANELS:
            for path in (CSS_FILES[panel], JS_FILES[panel]):
                self.assertEqual(
                    [], self._scan(path),
                    f"{path.name} contains forbidden non-ASCII glyphs")

    def test_test_file_is_ascii_clean(self):
        self.assertEqual(
            [], self._scan(Path(__file__)),
            "test_pgr_child_panel_floor_guard.py has forbidden glyphs")


if __name__ == "__main__":
    unittest.main()
