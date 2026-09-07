"""Source guards for the descriptive rune HOVER tooltips (operator 2026-07-04).

Hovering a rune in the RC "user builds" area (and on the build-insights
rune-WPA tab) showed NO effect text - only the rune name, or nothing. Two
surfaces render runes and both now compose a descriptive title:

  Surface 1 - web/js/panels/build_insights.js (rune-WPA tab):
    the /api/rune-wpa row has no description, so the tab lazy-loads
    /api/dictionary/runes and folds shortDesc into {rune_id -> stripped
    text}; rowCells emits an _esc()'d title="Name - effect" on .bi-rune.

  Surface 2 - web/js/main.js (rune-page builder _ubRpBuildRow):
    the rune object already carries shortDesc (from /api/dictionary/runes),
    so c.title = name + " - " + _stripHtml(shortDesc).

The pure helper behaviour (_stripHtml / _runeTitle: tag-strip, entity-decode,
whitespace-collapse, null-safe, name-only fallback) is pinned behaviourally by
web/js/panels/build_insights_rune_tooltip.test.mjs (node --test). These are
source pins so a partial revert (dropping the title wiring or the helper) trips
CI in the Python suite too. Mirrors the 4e5b2575 / test_archetype_nudge_chip_dom
source-guard precedent.
"""
from __future__ import annotations

import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
BUILD_INSIGHTS_JS = WEB / "js" / "panels" / "build_insights.js"
MAIN_JS = WEB / "js" / "main.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class BuildInsightsRuneTooltipTests(unittest.TestCase):
    """Surface 1: the rune-WPA tab composes a descriptive, escaped title."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(BUILD_INSIGHTS_JS)

    def test_strip_html_helper_present(self) -> None:
        self.assertIn("function _stripHtml(", self.src)

    def test_rune_title_helper_present(self) -> None:
        self.assertIn("function _runeTitle(", self.src)

    def test_rune_desc_catalog_loader_present(self) -> None:
        # Lazy-load of the DDragon rune catalog keyed by rune_id.
        self.assertIn("function _loadRuneDescs(", self.src)
        self.assertIn("/api/dictionary/runes", self.src)

    def test_rune_row_emits_escaped_descriptive_title(self) -> None:
        # The title value is _esc()'d (template-string attribute) and applied to
        # the .bi-rune span.
        self.assertIn("_esc(_runeTitle(name, desc))", self.src)
        self.assertIn('<span class="bi-rune" title="${title}">', self.src)

    def test_helpers_exported_for_unit_test(self) -> None:
        self.assertIn("_stripHtml,", self.src)
        self.assertIn("_runeTitle,", self.src)


class MainJsRuneBuilderTooltipTests(unittest.TestCase):
    """Surface 2: the rune-page builder composes name + stripped shortDesc."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(MAIN_JS)

    def test_strip_html_helper_present(self) -> None:
        self.assertIn("function _stripHtml(", self.src)

    def test_rune_builder_title_is_descriptive(self) -> None:
        # _ubRpBuildRow no longer sets a bare name; it appends the stripped
        # shortDesc when present.
        self.assertIn(
            'c.title = rune.name + (rune.shortDesc ? " - " + _stripHtml(rune.shortDesc) : "");',
            self.src,
        )

    def test_bare_name_only_title_removed(self) -> None:
        # Guard against a revert to the plain `c.title = rune.name;` line.
        self.assertNotIn("c.title = rune.name;", self.src)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
