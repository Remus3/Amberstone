"""R56 (2026-07-01): 5-phase UI fixture-audit contract for the
coach_decisions + trigger_pill surfaces (docs/UI_SCALE_SPEC_V2.md v2.1).

Grep-contract style (pathlib read + regex asserts on source, the
tests/test_overlay_*.py pattern - overlay/panel JS has no node harness).

Locks the R56 MUST-FIXes so they cannot regress:
  TYPOGRAPHY - every font-size in coach_decisions.css and in the
    map_state.css .trigger-pill block is a var(--fs-*) token (no bare
    sub-floor px like the pre-audit 11/12/13/14/15px).
  HIT-TARGETS - .coach-decision-btn (the only clickable in scope)
    carries min-height: var(--hit-min).
  STRUCTURE - the Recent Coach Calls poll is gated on its DOM section
    existing: the #recent-coach-calls markup was dropped with the s162
    lobby v2 (832704a7), so an unguarded setInterval fetched
    /api/decisions/log every 30s into a null render forever.
  ASCII - no em/en dashes or smart quotes in the four audited files
    (the functional U+25CF pill dot in trigger_pill.js matches the
    sibling ds-pill/augments-pill glyph convention and is allowed).
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CD_CSS = ROOT / "web" / "css" / "panels" / "coach_decisions.css"
MS_CSS = ROOT / "web" / "css" / "panels" / "map_state.css"
CD_JS = ROOT / "web" / "js" / "panels" / "coach_decisions.js"
TP_JS = ROOT / "web" / "js" / "panels" / "trigger_pill.js"

# font-size: <bare px> - does NOT match font-size: var(--fs-sm, 18px)
_BARE_PX = re.compile(r"font-size:\s*\d+(?:\.\d+)?px")

# Banned glyphs by codepoint (chr() keeps this file itself ASCII-clean):
# en dash, em dash, single + double smart quotes.
BANNED = {
    chr(0x2013): "en dash", chr(0x2014): "em dash",
    chr(0x2018): "smart quote", chr(0x2019): "smart quote",
    chr(0x201C): "smart quote", chr(0x201D): "smart quote",
}


def _trigger_pill_blocks(css: str) -> str:
    """Concatenate every .trigger-pill rule body in map_state.css."""
    return "\n".join(
        m.group(0) for m in re.finditer(
            r"\.trigger-pill[^{]*\{[^}]*\}", css)
    )


class TestR56Typography(unittest.TestCase):
    def test_coach_decisions_css_has_no_bare_px_font_sizes(self):
        css = CD_CSS.read_text(encoding="utf-8")
        bare = _BARE_PX.findall(css)
        self.assertEqual(bare, [],
                         "coach_decisions.css font-sizes must be var(--fs-*) "
                         f"tokens (UI_SCALE_SPEC_V2), found bare: {bare}")

    def test_coach_decisions_css_consumes_fs_tokens(self):
        css = CD_CSS.read_text(encoding="utf-8")
        for tok in ("var(--fs-md", "var(--fs-sm", "var(--fs-xs"):
            self.assertIn(tok, css,
                          f"coach_decisions.css must consume {tok})")

    def test_trigger_pill_font_size_is_tokenized(self):
        blocks = _trigger_pill_blocks(MS_CSS.read_text(encoding="utf-8"))
        self.assertTrue(blocks, ".trigger-pill rules missing from map_state.css")
        self.assertEqual(_BARE_PX.findall(blocks), [],
                         ".trigger-pill font-size must be a var(--fs-*) token")
        self.assertIn("var(--fs-sm", blocks,
                      ".trigger-pill must consume var(--fs-sm)")


class TestR56HitTargets(unittest.TestCase):
    def test_coach_decision_btn_meets_hit_min(self):
        css = CD_CSS.read_text(encoding="utf-8")
        m = re.search(r"\.coach-decision-btn\s*\{[^}]*\}", css)
        self.assertIsNotNone(m, ".coach-decision-btn rule missing")
        self.assertIn("min-height: var(--hit-min", m.group(0),
                      ".coach-decision-btn must meet the --hit-min 42px floor")


class TestR56Structure(unittest.TestCase):
    def test_recent_calls_poll_gated_on_section_presence(self):
        src = CD_JS.read_text(encoding="utf-8")
        self.assertRegex(
            src,
            r"if\s*\(RECENT_CALLS\.section\)[\s\S]{0,200}"
            r"setInterval\(pollRecentCoachCalls",
            "recent-coach-calls poll must not start when its DOM section "
            "is absent (markup removed in s162 lobby v2)")


class TestR56Ascii(unittest.TestCase):
    def test_no_banned_glyphs_in_audited_files(self):
        for p in (CD_CSS, MS_CSS, CD_JS, TP_JS):
            text = p.read_text(encoding="utf-8")
            hits = sorted({BANNED[ch] for ch in text if ch in BANNED})
            self.assertEqual(hits, [], f"{p.name} contains banned glyphs: {hits}")


if __name__ == "__main__":
    unittest.main()
