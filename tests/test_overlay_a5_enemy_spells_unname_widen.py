"""A5 (OVERLAY_BUILD_MASTER_PLAN WP-A5): the enemy summoner-spell tap-tracker
loses its panel name and widens the champion-name column to the longest name.

Acceptance (plan WP-A5 row + the next-session handoff):
  1. NO panel name - the "ENEMY SPELLS" `.es-head` title is gone.
  2. FULL champion names - the `_shortChamp` 9-char slice is removed; the row
     renders the whole champion name (e.g. "Nunu & Willump").
  3. ALIGNED + un-clamped - the `.es-champ` column drops its `flex:0 0 58px`
     fixed basis + the ellipsis clamp; it sizes to a shared longest-name basis
     (a JS-computed `--es-champ-ch` width) so every row's chips line up.
  4. The panel max-width is lifted off 230px to fit the longest name + chips.

Grep-style contract test, mirroring tests/test_overlay_a4b_stats_vertical.py +
tests/test_overlay_a3_coach_tag_strip.py: pathlib reads + substring/regex asserts,
no DOM emulation (there is no jsdom/node harness for web/js page code).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PANEL_JS = REPO / "web" / "js" / "panels" / "enemy_spells.js"
OVERLAY_CSS = REPO / "web" / "css" / "overlay.css"


def _rule(css: str, selector: str) -> str:
    """Body text of the first CSS rule whose head is `selector` (up to the next
    closing brace), comments stripped."""
    i = css.find(selector)
    assert i != -1, f"selector {selector!r} not found"
    j = css.find("}", i)
    assert j != -1, f"no closing brace after {selector!r}"
    return re.sub(r"/\*.*?\*/", "", css[i:j], flags=re.S)


class NameHeaderRemoved(unittest.TestCase):
    """No "ENEMY SPELLS" title in the JS scaffold or the CSS."""

    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")
        self.css = OVERLAY_CSS.read_text(encoding="utf-8")

    def test_no_es_head_class_in_js(self):
        self.assertNotIn("es-head", self.js)

    def test_no_enemy_spells_title_literal(self):
        self.assertNotIn("ENEMY SPELLS", self.js)

    def test_no_es_head_rule_in_css(self):
        self.assertNotIn("es-head", self.css)


class FullChampionNames(unittest.TestCase):
    """The 9-char slice is gone; rows render the whole champion name."""

    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_shortchamp_helper_removed(self):
        self.assertNotIn("_shortChamp", self.js)

    def test_nine_char_slice_removed(self):
        self.assertNotIn("slice(0, 9)", self.js)
        # No champ-length truncation guard remains.
        self.assertNotIn("length > 9", self.js)

    def test_name_cell_renders_full_champion(self):
        # Direct assignment of the full name, no wrapper/slice.
        self.assertIn("name.textContent = e.champion", self.js)


class SharedWidthBasis(unittest.TestCase):
    """The name column sizes to a JS-computed longest-name basis so rows align."""

    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_shared_basis_var_set_from_js(self):
        self.assertIn("--es-champ-ch", self.js)

    def test_longest_name_computed(self):
        # The basis is the max champion-name length over the live roster.
        self.assertIn("Math.max", self.js)


class CssWidenedAndUnclamped(unittest.TestCase):
    """Panel widened off 230px; .es-champ drops the fixed basis + ellipsis."""

    def setUp(self):
        self.css = OVERLAY_CSS.read_text(encoding="utf-8")

    def test_panel_no_longer_230(self):
        body = _rule(self.css, ".ovx-enemyspells {")
        self.assertNotIn("230px", body)

    def test_panel_widened(self):
        body = _rule(self.css, ".ovx-enemyspells {")
        self.assertIn("max-width: 360px", body)

    def test_es_champ_no_fixed_58_basis(self):
        body = _rule(self.css, ".es-champ {")
        self.assertNotIn("58px", body)

    def test_es_champ_no_ellipsis_clamp(self):
        body = _rule(self.css, ".es-champ {")
        self.assertNotIn("text-overflow", body)
        self.assertNotIn("overflow: hidden", body)

    def test_es_champ_consumes_shared_basis(self):
        body = _rule(self.css, ".es-champ {")
        self.assertIn("--es-champ-ch", body)


class AsciiHygiene(unittest.TestCase):
    """enemy_spells.js stays pure 7-bit ASCII (hard rule)."""

    def test_panel_js_is_pure_ascii(self):
        data = PANEL_JS.read_bytes()
        bad = [(i, b) for i, b in enumerate(data) if b > 0x7F]
        self.assertEqual(bad[:5], [], "non-ASCII bytes in enemy_spells.js")

    BAD = {
        chr(0x2013): "en-dash", chr(0x2014): "em-dash",
        chr(0x2018): "left smart quote", chr(0x2019): "right smart quote",
        chr(0x201C): "left smart dq", chr(0x201D): "right smart dq",
    }

    def test_overlay_css_no_banned_chars(self):
        text = OVERLAY_CSS.read_text(encoding="utf-8")
        for ch, name in self.BAD.items():
            self.assertNotIn(ch, text, f"{name} in overlay.css")


if __name__ == "__main__":
    unittest.main()
