"""A3 (OVERLAY_BUILD_MASTER_PLAN WP-A3): strip the coach inline bracket-timer
tags at the render sink and remove the hard truncation on the coach
headline/sub-headline rows.

Two acceptance halves:
  1. TAG STRIP - coach prose carries an internal authoring convention of
     single-lowercase-letter bracket tags (timer tags like [t]14s[/t] and
     siblings [x]...[/x]). They must never reach the rendered text or the
     clipboard. The strip lives in helpers.stripCoachTags and is folded into
     helpers.safe() so right_now.js + next.js inherit it (both route every
     coach field through safe()); coach_choices.js applies it explicitly
     because it slices raw fields without safe().
  2. TRUNCATION - the .action / .immediate (Right Now) and .action-mid /
     kv-body (Next) rows no longer hard-clamp + ellipsize coach prose
     mid-sentence. The Arena .immediate.is-pregame dense card KEEPS its
     deliberate "clipped not scrolled" box (round-44 design) - a regression
     guard, since it used to inherit the now-removed base .immediate clamp.

Grep-style contract test, mirroring tests/test_overlay_a1_slider_apply.py +
tests/test_overlay_a2_no_enemy_summs.py: pathlib reads + substring/rule-block
asserts, no DOM emulation (there is no jsdom/node harness for web/js page
code). The regex BEHAVIOR is pinned by re-implementing the exact JS pattern in
Python and asserting the documented examples; the JS source is pinned to that
same pattern by a literal-presence assert, so the two together verify the live
strip without a JS runtime.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HELPERS_JS = REPO / "web" / "js" / "lib" / "helpers.js"
COACH_CHOICES_JS = REPO / "web" / "js" / "panels" / "coach_choices.js"
RIGHT_NOW_CSS = REPO / "web" / "css" / "panels" / "right_now.css"
NEXT_CSS = REPO / "web" / "css" / "panels" / "next.css"

# The exact JS regexes A3 installs (paired single-letter tag incl. inner
# content, then any stray/unclosed single-letter tag). Mirrored here so the
# Python behavioral check is the same algorithm the source is asserted to use.
_PAIRED = re.compile(r"\[[a-z]\].*?\[/[a-z]\]", re.I)
_STRAY = re.compile(r"\[/?[a-z]\]", re.I)


def _py_strip(s: str) -> str:
    """Reference re-impl of stripCoachTags (same two regexes as the JS)."""
    out = _STRAY.sub(" ", _PAIRED.sub(" ", s))
    return re.sub(r"\s+", " ", out).strip() if out != s else s


def _rule(css: str, selector: str) -> str:
    """Body text of the first CSS rule whose head is `selector` (up to the
    next closing brace), with `/* ... */` comments stripped so an assertion
    keys off the actual declarations, not comment prose that may name a
    property (e.g. a comment explaining a removed -webkit-line-clamp)."""
    i = css.find(selector)
    assert i != -1, f"selector {selector!r} not found"
    j = css.find("}", i)
    assert j != -1, f"no closing brace after {selector!r}"
    return re.sub(r"/\*.*?\*/", "", css[i:j], flags=re.S)


class StripCoachTagsBehavior(unittest.TestCase):
    """The strip algorithm (re-impl of the JS regex) behaves per the brief."""

    def test_paired_timer_tag_removed_with_content(self):
        self.assertEqual(_py_strip("Back [t]14s[/t] now"), "Back now")

    def test_lone_timer_tag_collapses_to_empty(self):
        self.assertEqual(_py_strip("[t]5s[/t]"), "")

    def test_unclosed_tag_removed(self):
        self.assertEqual(_py_strip("Go [t] now"), "Go now")

    def test_sibling_letter_tag_removed(self):
        self.assertEqual(_py_strip("Ward [x]now[/x] please"), "Ward please")

    def test_multichar_item_ref_preserved(self):
        # Item refs are multi-char inside the brackets -> never matched.
        self.assertEqual(_py_strip("Buy [Kraken Slayer] now"),
                         "Buy [Kraken Slayer] now")

    def test_digit_ref_preserved(self):
        self.assertEqual(_py_strip("[3153] component"), "[3153] component")

    def test_no_tag_string_is_byte_identical(self):
        # Folding into safe() must not alter non-coach values (internal
        # whitespace preserved when there is no tag to strip).
        self.assertEqual(_py_strip("Mid - 45g  to  next"),
                         "Mid - 45g  to  next")


class HelpersWiring(unittest.TestCase):
    """helpers.js defines stripCoachTags with the exact regex and safe()
    delegates to it."""

    def setUp(self):
        self.src = HELPERS_JS.read_text(encoding="utf-8")

    def test_strip_coach_tags_exported(self):
        self.assertIn("export function stripCoachTags", self.src)

    def test_paired_regex_literal_present(self):
        self.assertIn(r"\[[a-z]\].*?\[\/[a-z]\]", self.src)

    def test_stray_regex_literal_present(self):
        self.assertIn(r"\[\/?[a-z]\]", self.src)

    def test_safe_delegates_to_strip(self):
        body = _rule(self.src, "export function safe(")
        self.assertIn("stripCoachTags", body)


class CoachChoicesStrips(unittest.TestCase):
    """coach_choices.js imports + applies the strip (it slices raw fields and
    bypasses safe())."""

    def setUp(self):
        self.src = COACH_CHOICES_JS.read_text(encoding="utf-8")

    def test_imports_strip_from_helpers(self):
        self.assertIn("stripCoachTags", self.src)
        self.assertIn("../lib/helpers.js", self.src)


class RightNowTruncationRemoved(unittest.TestCase):
    """Base .action + .immediate no longer hard-clamp; Arena is-pregame keeps
    its clip."""

    def setUp(self):
        self.css = RIGHT_NOW_CSS.read_text(encoding="utf-8")

    def test_action_no_line_clamp(self):
        body = _rule(self.css, ".action {")
        self.assertNotIn("-webkit-line-clamp", body)
        self.assertNotIn("overflow: hidden", body)

    def test_immediate_no_fixed_height_or_clamp(self):
        body = _rule(self.css, ".immediate {")
        # Intent: no FIXED height (a `min-height` reserve is allowed). The
        # 2-space-indented form distinguishes `height:` from `min-height:`.
        self.assertNotIn("\n  height: 54px", body)
        self.assertNotIn("-webkit-line-clamp", body)

    def test_arena_pregame_keeps_its_clip(self):
        # Regression guard: the dense Arena pregame card stays clipped-not-
        # scrolled (it used to inherit the now-removed base .immediate clamp).
        body = _rule(self.css, ".immediate.is-pregame {")
        self.assertIn("overflow: hidden", body)
        self.assertIn("-webkit-line-clamp", body)


class NextTruncationRemoved(unittest.TestCase):
    """Next headline + body rows no longer hard-clamp coach prose."""

    def setUp(self):
        self.css = NEXT_CSS.read_text(encoding="utf-8")

    def test_action_mid_no_line_clamp(self):
        body = _rule(self.css, ".action-mid {")
        self.assertNotIn("-webkit-line-clamp", body)

    def test_next_kv_body_no_line_clamp(self):
        body = _rule(self.css, ".panel-next .kv > span:last-child {")
        self.assertNotIn("-webkit-line-clamp", body)

    def test_right_now_kv_body_no_line_clamp(self):
        body = _rule(self.css, ".panel-right-now .kv > span:last-child {")
        self.assertNotIn("-webkit-line-clamp", body)


if __name__ == "__main__":
    unittest.main()
