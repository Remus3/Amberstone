"""RM-881 (h) closure guard: QA47 "labeled grid sections + tonal-elevation
surfaces + text-tier tokens" is SHIPPED, and these tests pin the shipped half.

Measured at s144 (queue lane cycle 5), against web/index.html and
web/css/panels/base.css:
  - Labeled sections: every routed view in the view menu is a
    `<section id="view-<name>" class="view-section">` whose first block is a
    `.view-section-head` carrying a non-empty `<h2>` label. Home is the one
    menu entry with no view-section (it renders the #home-overlay hero), and
    "auto" is the clear-manual action, not a view.
  - Tonal-elevation surfaces and text tiers: base.css `:root` declares the
    surface ramp (--surface, --surface-2, --surface-3) and the text tiers
    (--text, --dim, --faint), added by 0a02c0ff8.

What QA47 asked for and is deliberately NOT here (do not re-add it to make a
test pass):
  - Per-pane title heads on the Active Match grid: CALL and MAP lost theirs on
    purpose in fbaac20b4 (WP-A6, overlay data-ink doctrine), guarded by
    tests/test_overlay_a6_pane_headers_removed.py. The grid itself is a
    named-area grid, guarded by tests/test_am_grid_child_placement.py.
  - The Datadog-style Overview / Combat / Objectives / Status bands (research
    item nonleague B2): DECLINED by docs/research/RESEARCH_CONSOLIDATED_2026-07-28.md
    ("Recommend DECLINING"), because the standalone 1920 dashboard stopped being
    a primary visual surface (LEDGER 767).

These are closure guards, not regression tests: they were green on the base
they were written against. Their value is that a removed view head or a
dropped tier token now fails here instead of silently reopening QA47.
"""

from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO / "web" / "index.html"
BASE_CSS = REPO / "web" / "css" / "panels" / "base.css"

# Menu entries that have no view-section, with the reason (module docstring).
_MENU_WITHOUT_SECTION = {"home", "auto"}

# The surface ramp and the text tiers QA47 asked for.
_TIER_TOKENS = ("--surface", "--surface-2", "--surface-3", "--text", "--dim", "--faint")

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
         "link", "meta", "param", "source", "track", "wbr"}


class _ViewCensus(HTMLParser):
    """Menu entries and the leading labeled head of every view-section.

    A real parser, so comments, attribute order, extra classes and character
    references cannot fool it. A section's label is the text of a visible
    <h2> inside a visible `.view-section-head` that is the section's FIRST
    child element; anything else leaves the label "".
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[str] = []
        self.menu: list[str] = []
        self.heads: dict[str, str] = {}
        self._section: str | None = None
        self._section_depth = 0
        self._first_child_seen = False
        self._head_depth: int | None = None
        self._h2_depth: int | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if "view-menu-item" in classes and a.get("data-view"):
            self.menu.append(a["data-view"])
        if tag in _VOID:
            return
        depth = len(self._stack)
        ident = a.get("id") or ""
        if self._section is None and "view-section" in classes and ident.startswith("view-"):
            self._section = ident[len("view-"):]
            self._section_depth = depth
            self._first_child_seen = False
            self.heads[self._section] = ""
        elif self._section is not None and depth == self._section_depth + 1:
            if not self._first_child_seen:
                self._first_child_seen = True
                if tag == "div" and "view-section-head" in classes and "hidden" not in a:
                    self._head_depth = depth
        elif (self._head_depth is not None and tag == "h2"
              and self._h2_depth is None and "hidden" not in a):
            self._h2_depth = depth
        self._stack.append(tag)

    def handle_endtag(self, tag):
        if tag in _VOID or tag not in self._stack:
            return
        while self._stack:
            if self._stack.pop() == tag:
                break
        depth = len(self._stack)
        if self._h2_depth is not None and depth <= self._h2_depth:
            self._h2_depth = None
        if self._head_depth is not None and depth <= self._head_depth:
            self._head_depth = None
        if self._section is not None and depth <= self._section_depth:
            self._section = None

    def handle_data(self, data):
        if self._section is not None and self._h2_depth is not None:
            self.heads[self._section] += " " + data


def _census(html: str) -> _ViewCensus:
    parser = _ViewCensus()
    parser.feed(html)
    parser.close()
    parser.heads = {k: " ".join(v.split()) for k, v in parser.heads.items()}
    return parser


def _root_block(css: str) -> str:
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    m = re.search(r":root\s*\{(.*?)\}", css, flags=re.S)
    return m.group(1) if m else ""


class ViewSectionsCarryLabeledHeads(unittest.TestCase):
    def setUp(self):
        census = _census(INDEX_HTML.read_text(encoding="utf-8"))
        self.menu = census.menu
        self.heads = census.heads

    def test_the_enumerations_are_not_empty(self):
        # Anchor: an empty census would pass every check below.
        self.assertGreaterEqual(len(self.menu), 10)
        self.assertGreaterEqual(len(self.heads), 10)
        self.assertIn("active-match", self.heads)

    def test_every_menu_view_has_a_view_section(self):
        missing = [
            v for v in self.menu
            if v not in _MENU_WITHOUT_SECTION and v not in self.heads
        ]
        self.assertEqual(missing, [], "menu views with no view-section")

    def test_the_menu_exclusions_are_still_real(self):
        menu = set(self.menu)
        for name in _MENU_WITHOUT_SECTION:
            self.assertIn(name, menu, f"stale exclusion: {name} left the menu")
            self.assertNotIn(name, self.heads, f"stale exclusion: {name} now has a section")

    def test_every_view_section_opens_with_a_labeled_head(self):
        unlabeled = sorted(v for v, text in self.heads.items() if not text)
        self.assertEqual(unlabeled, [], "view-sections with no labeled .view-section-head h2")


class TierTokensDeclared(unittest.TestCase):
    def test_base_root_declares_the_surface_and_text_tiers(self):
        root = _root_block(BASE_CSS.read_text(encoding="utf-8"))
        self.assertTrue(root, "no :root block in base.css")
        missing = [
            t for t in _TIER_TOKENS
            if not re.search(r"(?m)^\s*" + re.escape(t) + r"\s*:", root)
        ]
        self.assertEqual(missing, [], "tier tokens missing from base.css :root")


if __name__ == "__main__":
    unittest.main()
