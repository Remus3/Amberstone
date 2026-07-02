"""Grep-based DOM-contract tests for OQ13 slice B - the home THIS WEEK
mode-factored weekly digest card.

The /api/home/summary payload (backend slice A) gains
``data.weekly_digest`` = {window_days, total_games, modes: [...]} where
each mode row carries mode/games/avg_kda plus good/bad/ugly strings
("" = backend-suppressed row -> skip it). Slice B renders one block per
mode inside a new #home-weekly-digest card that sits between Tonight's
Pick (#home-combo) and Last Build (#home-coach-build).

Old/missing-DB payloads may LACK weekly_digest entirely and an idle week
ships modes: [] - the card must degrade silently (stay hidden).

Mirrors the cheap text-search precedent set by
``tests/test_last_match_carry_bench_dom.py``.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN_JS    = ROOT / "web" / "js" / "main.js"
HOME_CSS   = ROOT / "web" / "css" / "panels" / "home.css"
INDEX_HTML = ROOT / "web" / "index.html"

# First line of the CSS block this slice appended to home.css; the block
# runs from here to EOF (appended last).
CSS_MARKER = "OQ13 slice B"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _card_block(html: str) -> str:
    """The digest card's slice of index.html: from the card open tag to
    the Last Build card that follows it (sibling adjacency contract)."""
    tail = html.split('id="home-weekly-digest"', 1)[1]
    return tail.split('id="home-coach-build"', 1)[0]


def _fn_body(js: str) -> str:
    """_homeRenderWeeklyDigest body, up to its closing brace at col 2
    (module functions in main.js are indented 2 spaces; inner blocks
    close deeper, so the first "\\n  }" is the function's own end)."""
    tail = js.split("function _homeRenderWeeklyDigest(", 1)[1]
    return tail.split("\n  }", 1)[0]


class HtmlCardTests(unittest.TestCase):
    """#home-weekly-digest exists, starts hidden, carries the head text
    and the empty JS-filled body container."""

    def test_card_exists_and_starts_hidden(self):
        html = _read(INDEX_HTML)
        self.assertIn('id="home-weekly-digest"', html)
        open_tag = html.split('id="home-weekly-digest"', 1)[1].split(">", 1)[0]
        self.assertIn("hidden", open_tag, "card must default hidden")

    def test_card_carries_namespace_class(self):
        html = _read(INDEX_HTML)
        before = html.split('id="home-weekly-digest"', 1)[0]
        open_tag = before.rsplit("<div", 1)[1]
        self.assertIn("home-weekly-digest", open_tag)

    def test_head_text_this_week_inside_card(self):
        block = _card_block(_read(INDEX_HTML))
        self.assertIn("home-weekly-digest-head", block)
        self.assertIn("THIS WEEK", block)

    def test_body_container_inside_card(self):
        block = _card_block(_read(INDEX_HTML))
        self.assertIn('id="home-weekly-digest-body"', block)

    def test_card_sits_between_combo_and_last_build(self):
        html = _read(INDEX_HTML)
        combo = html.index('id="home-combo"')
        digest = html.index('id="home-weekly-digest"')
        build = html.index('id="home-coach-build"')
        self.assertLess(combo, digest, "digest must follow Tonight's Pick")
        self.assertLess(digest, build, "digest must precede Last Build")


class MainJsTests(unittest.TestCase):
    """main.js defines _homeRenderWeeklyDigest, wires data.weekly_digest
    after _homeRenderCoach, hides on empty, renders idempotently, and
    never feeds payload strings to innerHTML."""

    def test_defines_renderer(self):
        js = _read(MAIN_JS)
        self.assertIn("function _homeRenderWeeklyDigest(", js)

    def test_wired_with_weekly_digest_after_coach(self):
        js = _read(MAIN_JS)
        call = "_homeRenderWeeklyDigest(data.weekly_digest)"
        self.assertIn(call, js)
        coach = js.index("_homeRenderCoach(data.tonight_pick, data.last_build)")
        self.assertLess(coach, js.index(call),
                        "digest render must follow the coach render")

    def test_absent_or_empty_modes_hides_card(self):
        body = _fn_body(_read(MAIN_JS))
        self.assertIn("!dg", body)
        self.assertIn("Array.isArray(dg.modes)", body)
        self.assertIn("dg.modes.length === 0", body)
        self.assertIn("hidden = true", body)

    def test_idempotent_signature_stash(self):
        body = _fn_body(_read(MAIN_JS))
        self.assertIn("JSON.stringify(dg)", body)
        self.assertIn("dataset.sig", body)

    def test_payload_lands_via_text_content_never_innerhtml(self):
        body = _fn_body(_read(MAIN_JS))
        self.assertNotIn("innerHTML", body,
                         "payload strings must not hit innerHTML")
        self.assertIn("createElement", body)
        self.assertIn("textContent", body)

    def test_good_bad_ugly_rows_reuse_pick_tip_classes(self):
        body = _fn_body(_read(MAIN_JS))
        for label in ("The Good", "The Bad", "The Ugly"):
            self.assertIn(label, body)
        for cls in ("home-pick-tip-row", "home-pick-tip-label",
                    "home-pick-tip-value"):
            self.assertIn(cls, body)

    def test_empty_row_string_skipped(self):
        body = _fn_body(_read(MAIN_JS))
        self.assertIn("continue", body)

    def test_mode_header_line_format(self):
        body = _fn_body(_read(MAIN_JS))
        self.assertIn("games", body)
        self.assertIn(".toFixed(1)", body)
        self.assertIn("KDA", body)


class HomeCssTests(unittest.TestCase):
    """home.css carries the namespaced .home-weekly-digest rules; the new
    block introduces no raw px font-size (tokens only, >= var(--fs-xs))."""

    def _block(self) -> str:
        css = _read(HOME_CSS)
        self.assertIn(CSS_MARKER, css, "OQ13 CSS block missing")
        return css.split(CSS_MARKER, 1)[1]

    def test_card_shell_and_hidden_rules_exist(self):
        block = self._block()
        self.assertIn(".home-weekly-digest {", block)
        self.assertIn(".home-weekly-digest[hidden] { display: none; }",
                      block)

    def test_head_and_mode_header_use_tokens(self):
        block = self._block()
        head = block.split(".home-weekly-digest-head", 1)[1].split("}", 1)[0]
        self.assertIn("var(--fs-xs)", head)
        mode = block.split(".home-weekly-digest-mode-head", 1)[1]
        mode = mode.split("}", 1)[0]
        self.assertIn("var(--fs-sm)", mode)

    def test_no_raw_px_font_size_in_new_block(self):
        block = self._block()
        raw = re.findall(r"font-size:\s*[\d.]+px", block)
        self.assertEqual([], raw,
                         "OQ13 block must use font tokens, not raw px")


class AsciiHygieneTests(unittest.TestCase):
    """No em/en-dashes or smart quotes in the touched files (all three
    were verified glyph-clean before this slice landed, so a whole-file
    scan is safe). BAD dict built via chr() so this file stays clean
    against its own scan."""

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

    def test_touched_files_are_ascii_clean(self):
        for p in (MAIN_JS, HOME_CSS, INDEX_HTML, Path(__file__)):
            self.assertEqual([], self._scan(p), f"non-ASCII glyphs in {p}")
