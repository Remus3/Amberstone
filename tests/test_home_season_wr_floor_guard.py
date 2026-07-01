"""Typography-floor + hit-target + ASCII + wiring guard for the home hero
"true season WR" readout (QA15 part b).

The home last-20 pip strip already shipped (LIFT 3); this slice adds a
ranked season-WR readout beside it (`.home-season-wr`, painted by
`_homeRenderSeasonWr` from the home payload's `season_wr` dict). This lock
is SCOPED to that new selector on purpose: `web/css/panels/home.css` is
the whole home view (1300+ lines) and carries pre-existing sub-floor
hardcodes in the unrelated champ-select `.cs-*` block, so a whole-file
font guard is out of scope here. The scoped block guard mirrors the
teeth-first pattern of tests/test_pgr_child_panel_floor_guard.py.

Contracts:
1. TYPOGRAPHY - the `.home-season-wr` rule uses a `var(--fs-*)` token, never
   a literal sub-16px `font-size` (the --fs-xs floor, docs/UI_SCALE_SPEC_V2.md).
2. HIT-TARGETS - the readout is display-only: no `cursor: pointer` (so no
   --hit-min obligation). If it ever becomes clickable it must reserve the
   tap floor, and this guard flips RED first.
3. WIRING - the DOM node, the render fn and the CSS class all exist, so the
   three ends of the feature cannot silently drift apart.
4. ASCII - the authored CSS block + the render fn window are 7-bit ASCII
   (CLAUDE.md hard rule).

ASCII-only authored content.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME_CSS = ROOT / "web" / "css" / "panels" / "home.css"
INDEX_HTML = ROOT / "web" / "index.html"
MAIN_JS = ROOT / "web" / "js" / "main.js"

SELECTOR = ".home-season-wr"
DOM_ID = "home-hero-season-wr"
RENDER_FN = "_homeRenderSeasonWr"

FS_XS_PX = 16
_FONT_SIZE_RE = re.compile(r"font-size:\s*(\d+)px")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _css_block(css: str, selector: str) -> str:
    """Body of the first flat rule whose selector line contains
    ``selector`` (RC panel CSS has no nested braces). Empty when absent."""
    anchor = re.search(re.escape(selector) + r"\s*\{", css)
    if not anchor:
        return ""
    brace = css.index("{", anchor.start())
    end = css.index("}", brace)
    return css[brace + 1:end]


def _literal_subfloor_px(block: str) -> list[int]:
    """Literal ``font-size: <N>px`` sizes below the 16px floor in a block.
    Token refs (``var(--fs-xs)``) never match the px anchor -> ignored."""
    return [int(m.group(1)) for m in _FONT_SIZE_RE.finditer(block)
            if int(m.group(1)) < FS_XS_PX]


def _non_ascii(text: str) -> list[str]:
    return sorted({c for c in text if ord(c) > 0x7F})


class SeasonWrTypographyTests(unittest.TestCase):
    def test_block_uses_font_token_not_literal_subfloor(self):
        block = _css_block(_read(HOME_CSS), SELECTOR)
        self.assertTrue(block, f"{SELECTOR} rule missing from home.css")
        self.assertIn("var(--fs-", block,
                      f"{SELECTOR} must size type via a --fs-* token")
        self.assertEqual(
            [], _literal_subfloor_px(block),
            f"{SELECTOR} carries a literal sub-16px font-size")

    def test_scan_has_teeth(self):
        # A hardcoded sub-floor IS flagged; a token ref is NOT.
        self.assertEqual([11], _literal_subfloor_px("font-size: 11px;"))
        self.assertEqual([], _literal_subfloor_px("font-size: var(--fs-xs);"))
        self.assertEqual([], _literal_subfloor_px("font-size: 16px;"))


class SeasonWrHitTargetTests(unittest.TestCase):
    def test_readout_is_display_only(self):
        block = _css_block(_read(HOME_CSS), SELECTOR)
        self.assertNotIn("cursor: pointer", block,
                         f"{SELECTOR} is display-only (no click target)")
        self.assertNotIn("cursor:pointer", block)


class SeasonWrWiringTests(unittest.TestCase):
    def test_dom_node_present(self):
        self.assertIn(DOM_ID, _read(INDEX_HTML),
                      f"index.html missing #{DOM_ID}")

    def test_render_fn_present_and_called(self):
        js = _read(MAIN_JS)
        self.assertIn(f"function {RENDER_FN}", js,
                      f"main.js missing {RENDER_FN} definition")
        self.assertIn(f"{RENDER_FN}(", js,
                      f"main.js never calls {RENDER_FN}")

    def test_css_class_present(self):
        self.assertIn(SELECTOR, _read(HOME_CSS),
                      f"home.css missing {SELECTOR}")


class SeasonWrAsciiTests(unittest.TestCase):
    def test_css_block_is_ascii(self):
        block = _css_block(_read(HOME_CSS), SELECTOR)
        self.assertEqual([], _non_ascii(block),
                         "season-wr CSS block has non-ASCII glyphs")

    def test_render_fn_window_is_ascii(self):
        js = _read(MAIN_JS)
        i = js.find(f"function {RENDER_FN}")
        self.assertGreaterEqual(i, 0)
        window = js[i:i + 800]
        self.assertEqual([], _non_ascii(window),
                         "season-wr render fn has non-ASCII glyphs")

    def test_test_file_is_ascii(self):
        self.assertEqual([], _non_ascii(_read(Path(__file__))),
                         "this guard file has non-ASCII glyphs")


if __name__ == "__main__":
    unittest.main()
