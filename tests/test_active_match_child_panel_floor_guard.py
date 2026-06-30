"""Typography-floor + hit-target regression guard for the Active Match
child panels Draft Elo (draft_elo) and Ward Coverage Heat Strip
(ward_heat).

R40 (LOOP cycle 11) 5-phase fixture audit deliverable. The C2 active_match
audit + R13/R16 swept the sibling child panels but these two never got a
DEDICATED machine guard - item 184 v2.1 PRESERVED their sub-floor density
fonts behind inline operator-exception comments, but nothing locked that
contract in. This file is that lock.

Three contracts, mirroring the cheap grep-smoke precedent in
``tests/test_design_tokens_css.py`` + ``tests/test_ui_polish_2026_05_20.py``:

1. SubfloorFontExceptionTests (TYPOGRAPHY) - every hardcoded
   ``font-size: <N>px`` below the --fs-xs 16px floor in either panel CSS
   carries an ``operator-exception`` annotation inside its own rule block.
   A future edit that adds a NEW un-exempted sub-floor size, or strips an
   existing exception rationale, goes red. The scan helper is exercised
   against synthetic BAD/GOOD fixtures so the guard provably has teeth
   (RED-first: a sub-floor with no exception IS detected).

2. DisplayOnlyHitTargetTests (HIT-TARGETS) - both panels are display-only
   (chip + hover overlay; 22px ward strip). No ``cursor: pointer`` rule may
   ship without ``min-height: var(--hit-min)`` in the same block, and
   neither panel JS introduces a click handler. The day someone wires a
   real clickable, it must meet the --hit-min 42px tap floor.

3. AsciiHygieneTests (ASCII) - no em/en-dash or smart quotes in any of the
   four panel files. BAD dict built via chr() so this file stays clean
   against its own scan.

STRUCTURE + HIERARCHY phases of the audit are render-shape concerns covered
by the existing DOM/snapshot suites (tests/test_draft_elo_panel_dom.py,
tests/snapshot_panels/test_draft_elo_panel.py + test_ward_heat.py); this
file guards the two phases that are pure static-text contracts.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAFT_ELO_CSS = ROOT / "web" / "css" / "panels" / "draft_elo.css"
DRAFT_ELO_JS  = ROOT / "web" / "js"  / "panels" / "draft_elo.js"
WARD_HEAT_CSS = ROOT / "web" / "css" / "panels" / "ward_heat.css"
WARD_HEAT_JS  = ROOT / "web" / "js"  / "panels" / "ward_heat.js"

# The global typography floor (docs/UI_SCALE_SPEC_V2.md): --fs-xs = 16px.
FS_XS_PX = 16

_FONT_SIZE_RE = re.compile(r"font-size:\s*(\d+)px")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _subfloor_font_lines(css: str) -> list[tuple[int, int]]:
    """Every ``font-size: <N>px`` declaration with N < the 16px floor.

    Returns (1-based line number, size) pairs."""
    out: list[tuple[int, int]] = []
    for idx, line in enumerate(css.split("\n")):
        m = _FONT_SIZE_RE.search(line)
        if not m:
            continue
        size = int(m.group(1))
        if size < FS_XS_PX:
            out.append((idx + 1, size))
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
    # Split into "selector { body }" chunks; cheap brace split is enough
    # for these flat panel stylesheets (no nested at-rules with pointers).
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
    """Every sub-floor font in either panel is exception-annotated."""

    def test_draft_elo_has_subfloor_fonts(self):
        # Sanity floor: the scan works and the file is the dense chip we
        # expect (guards against a wiped/renamed file passing vacuously).
        self.assertGreaterEqual(
            len(_subfloor_font_lines(_read(DRAFT_ELO_CSS))), 5,
            "draft_elo.css should carry several sub-floor density fonts")

    def test_ward_heat_has_subfloor_fonts(self):
        self.assertGreaterEqual(
            len(_subfloor_font_lines(_read(WARD_HEAT_CSS))), 3,
            "ward_heat.css should carry several sub-floor density fonts")

    def test_draft_elo_no_unexcepted_subfloor(self):
        offenders = _unexcepted_subfloor(_read(DRAFT_ELO_CSS))
        self.assertEqual(
            [], offenders,
            "draft_elo.css sub-floor font(s) missing an operator-exception "
            f"rationale (line, px): {offenders}")

    def test_ward_heat_no_unexcepted_subfloor(self):
        offenders = _unexcepted_subfloor(_read(WARD_HEAT_CSS))
        self.assertEqual(
            [], offenders,
            "ward_heat.css sub-floor font(s) missing an operator-exception "
            f"rationale (line, px): {offenders}")

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
    """Both panels are display-only; any future clickable must meet
    --hit-min. No click handler is wired in either panel JS."""

    def test_draft_elo_css_no_pointer_without_hitmin(self):
        self.assertEqual(
            [], _pointer_rules_without_hitmin(_read(DRAFT_ELO_CSS)),
            "draft_elo.css cursor:pointer rule(s) lack min-height: "
            "var(--hit-min)")

    def test_ward_heat_css_no_pointer_without_hitmin(self):
        self.assertEqual(
            [], _pointer_rules_without_hitmin(_read(WARD_HEAT_CSS)),
            "ward_heat.css cursor:pointer rule(s) lack min-height: "
            "var(--hit-min)")

    def test_pointer_scan_has_teeth(self):
        self.assertEqual(
            [".btn"],
            _pointer_rules_without_hitmin(".btn { cursor: pointer; }"))
        self.assertEqual(
            [],
            _pointer_rules_without_hitmin(
                ".btn { cursor: pointer; min-height: var(--hit-min); }"))

    def test_panels_wire_no_click_handler(self):
        for js_path in (DRAFT_ELO_JS, WARD_HEAT_JS):
            js = _read(js_path)
            self.assertNotIn('addEventListener("click"', js,
                             f"{js_path.name} must stay display-only")
            self.assertNotIn("addEventListener('click'", js,
                             f"{js_path.name} must stay display-only")
            self.assertNotIn(".onclick", js,
                             f"{js_path.name} must stay display-only")


class AsciiHygieneTests(unittest.TestCase):
    """No em/en-dashes or smart quotes in the four panel files (the
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
        for path in (DRAFT_ELO_CSS, DRAFT_ELO_JS, WARD_HEAT_CSS, WARD_HEAT_JS):
            self.assertEqual([], self._scan(path),
                             f"{path.name} contains forbidden non-ASCII glyphs")

    def test_test_file_is_ascii_clean(self):
        self.assertEqual(
            [], self._scan(Path(__file__)),
            "test_active_match_child_panel_floor_guard.py has forbidden glyphs")


if __name__ == "__main__":
    unittest.main()
