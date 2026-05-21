"""Pass-3 design-tokens consumption sweep tests.

Five more panel CSS files swept to consume the semantic-color tokens
declared in ``web/css/tokens.css``. Mirrors the
``DraftEloConsumesTokensTests`` precedent in ``test_design_tokens_css.py``
(grep-based DOM-contract style; cheap text-search).

Per-panel scope summary:

* item_build.css: two ``#44ff88`` success-green literals (ds-chip em +
  ib-builds-status.ok) -> ``var(--signal-good)``. The 4 wave-state
  threshold colors (``#F5FF00`` your-lane pip, ``#5BC0F8`` icy-blue
  FREEZE, ``#4DD0A8`` potion-green TRADE, ``#FF4646`` vibrant-red
  DISENGAGE) are operator-tuned distinct cues intentionally outside
  the semantic palette and are PRESERVED.

* augment_reco.css: zero swaps. The 3 augment-rarity hex
  (``#6b7280`` silver, ``#b88410`` gold, ``#a855f7`` prismatic) are
  brand-specific Riot champ-select augment-tier colors per the file's
  own docstring; PRESERVED. Test pins existing ``var(--gold)`` /
  ``var(--info)`` / ``var(--good)`` / ``var(--bad)`` primitives the
  panel already consumes.

* team_context.css: two ``#F5B87C`` (tc-label + tc-slot-rank) ->
  ``var(--signal-gold)`` (exact case-insensitive match to the
  --signal-gold #f5b87c declaration in tokens.css).

* cd_ledger.css: zero swaps. Every hex is either an ally/enemy team
  tint (``#5b8dff`` blue / ``#f07e8b`` red / ``#9fbcff`` / ``#ffa5af``)
  or the panel-internal compact surface palette (dark backgrounds +
  borders + ready-chip greens + ult-chip purples). All intentionally
  outside the semantic palette; PRESERVED. Test pins existing
  ``var(--text)`` / ``var(--text-faint)`` / ``var(--surface-head)`` /
  ``var(--border-soft)`` / ``var(--radius)`` consumption.

* bridge_pending.css: ``#F5B87C`` (coach-decision-title) ->
  ``var(--signal-gold)``; three ``#8A8CF0`` lavender literals
  (data-choice="give" + rcc-choice-give + bp-btn-defer:hover) ->
  ``var(--signal-info)`` (exact case-insensitive match to
  --signal-info #8a8cf0); one ``#6FD080`` (bp-btn-accept:hover) ->
  ``var(--signal-good)``. PRESERVED outliers: ``#F07E8B`` salmon
  (coach contest + bp-btn-dismiss) panel-specific brand tint;
  ``#000`` text-on-gold menu-badge contrast.

ASCII hygiene scan on all 5 files; BAD dict via chr() so this test
file stays ASCII-clean against its own scan (mirrors
``test_design_tokens_css.py::AsciiHygieneTests`` pattern).
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ITEM_BUILD_CSS    = ROOT / "web" / "css" / "panels" / "item_build.css"
AUGMENT_RECO_CSS  = ROOT / "web" / "css" / "panels" / "augment_reco.css"
TEAM_CONTEXT_CSS  = ROOT / "web" / "css" / "panels" / "team_context.css"
CD_LEDGER_CSS     = ROOT / "web" / "css" / "panels" / "cd_ledger.css"
BRIDGE_PENDING_CSS = ROOT / "web" / "css" / "panels" / "bridge_pending.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class ItemBuildConsumesTokensTests(unittest.TestCase):
    """item_build.css: two #44ff88 success-green literals swapped to
    var(--signal-good). Wave-state threshold colors preserved."""

    def test_no_hardcoded_success_green_hex(self):
        """The two #44ff88 literals (ds-chip em + ib-builds-status.ok)
        must be gone; they were generic success-green that mapped
        cleanly onto --signal-good."""
        css = _read(ITEM_BUILD_CSS)
        self.assertNotIn("color: #44ff88", css,
                         "item_build.css still uses bare color: #44ff88;"
                         " repoint to var(--signal-good).")

    def test_consumes_signal_good(self):
        css = _read(ITEM_BUILD_CSS)
        self.assertIn("var(--signal-good)", css,
                      "item_build.css must consume var(--signal-good)"
                      " for the success-green chips")

    def test_wave_state_outliers_preserved(self):
        """Wave-state thresholds are operator-tuned distinct cues
        intentionally outside the semantic palette; do NOT auto-sweep."""
        css = _read(ITEM_BUILD_CSS)
        # Your-lane fluorescent yellow pip
        self.assertIn("#F5FF00", css,
                      "your-lane wave-marker yellow pip preserved")
        # Three wave-state threshold colors
        self.assertIn("#5BC0F8", css,
                      "wave-our (FREEZE, <=30%) icy-blue preserved")
        self.assertIn("#4DD0A8", css,
                      "wave-mid (TRADE, 30-65%) potion-green preserved")
        self.assertIn("#FF4646", css,
                      "wave-bad (DISENGAGE, >=80%) vibrant-red preserved")


class AugmentRecoConsumesTokensTests(unittest.TestCase):
    """augment_reco.css: zero hex swaps. Augment-rarity colors are
    brand-specific Riot champ-select tier colors per the file's own
    docstring. Existing var() consumption is pinned so a future
    contributor doesn't strip them."""

    def test_brand_augment_tier_colors_preserved(self):
        """The 3 augment-rarity hex are brand-specific Riot
        champ-select tier colors; do NOT swap to --signal-*."""
        css = _read(AUGMENT_RECO_CSS)
        self.assertIn("#6b7280", css,
                      "augment-tier silver brand color preserved")
        self.assertIn("#b88410", css,
                      "augment-tier gold brand color preserved")
        self.assertIn("#a855f7", css,
                      "augment-tier prismatic brand color preserved")

    def test_consumes_existing_primitives(self):
        """Existing primitives the panel consumes for the info-active
        accent + good/bad synergy arrows. Pinned so a future sweep
        doesn't strip them mistakenly."""
        css = _read(AUGMENT_RECO_CSS)
        self.assertIn("var(--info)", css,
                      "augment_reco.css must consume var(--info)"
                      " for the is-active accent")
        self.assertIn("var(--good)", css,
                      "augment_reco.css must consume var(--good)"
                      " for the ar-syn.pos arrow")
        self.assertIn("var(--bad)", css,
                      "augment_reco.css must consume var(--bad)"
                      " for the ar-syn.neg arrow")


class TeamContextConsumesTokensTests(unittest.TestCase):
    """team_context.css: two #F5B87C (tc-label + tc-slot-rank) ->
    var(--signal-gold) (exact case-insensitive match to the
    --signal-gold #f5b87c declaration)."""

    def test_no_hardcoded_gold_hex(self):
        css = _read(TEAM_CONTEXT_CSS)
        # Both uppercase and lowercase forms must be gone from color:
        # property values.
        self.assertNotIn("color: #F5B87C", css,
                         "team_context.css still uses bare color: #F5B87C;"
                         " repoint to var(--signal-gold).")
        self.assertNotIn("color: #f5b87c", css,
                         "team_context.css still uses bare color: #f5b87c;"
                         " repoint to var(--signal-gold).")

    def test_consumes_signal_gold(self):
        css = _read(TEAM_CONTEXT_CSS)
        self.assertIn("var(--signal-gold)", css,
                      "team_context.css must consume var(--signal-gold)"
                      " for tc-label + tc-slot-rank")


class CdLedgerConsumesTokensTests(unittest.TestCase):
    """cd_ledger.css: zero hex swaps. Every hex is either an
    ally/enemy team tint or the panel-internal compact surface
    palette (dark backgrounds, ready-chip greens, ult-chip purples).
    All intentionally outside the semantic palette; PRESERVED.

    Test pins existing primitives the panel consumes so a future
    sweep doesn't strip them mistakenly."""

    def test_consumes_existing_primitives(self):
        css = _read(CD_LEDGER_CSS)
        self.assertIn("var(--surface-head)", css,
                      "cd_ledger.css must consume var(--surface-head)"
                      " for the right-rail pane background")
        self.assertIn("var(--border-soft)", css,
                      "cd_ledger.css must consume var(--border-soft)"
                      " for the pane border")
        self.assertIn("var(--radius)", css,
                      "cd_ledger.css must consume var(--radius)"
                      " for the pane corner radius")
        self.assertIn("var(--text-faint", css,
                      "cd_ledger.css must consume var(--text-faint)"
                      " for the chev + chip text fallback")

    def test_team_tint_outliers_preserved(self):
        """Ally-blue / enemy-red team tints are panel-specific brand
        colors intentionally distinct from --signal-good/--signal-bad
        so the operator scans ally-vs-enemy by hue, not by traffic-
        light semantics. PRESERVED."""
        css = _read(CD_LEDGER_CSS)
        self.assertIn("#5b8dff", css,
                      "ally-team blue border-left preserved")
        self.assertIn("#f07e8b", css,
                      "enemy-team red border-left preserved")
        self.assertIn("#9fbcff", css,
                      "ally-team name tint preserved")
        self.assertIn("#ffa5af", css,
                      "enemy-team name tint preserved")

    def test_ult_chip_purple_preserved(self):
        """Ult chip is intentionally visually distinct from summoner
        chips so the operator scans D/F/R left-to-right; the lavender
        is not on the semantic palette. PRESERVED."""
        css = _read(CD_LEDGER_CSS)
        self.assertIn("#d3bfff", css,
                      "ult-chip lavender text preserved")
        self.assertIn("#3a3a52", css,
                      "ult-chip dark purple sigil bg preserved")


class BridgePendingConsumesTokensTests(unittest.TestCase):
    """bridge_pending.css: #F5B87C (coach-decision-title) ->
    var(--signal-gold); three #8A8CF0 (give buttons + defer hover) ->
    var(--signal-info); #6FD080 (accept hover) ->
    var(--signal-good)."""

    def test_no_hardcoded_gold_hex(self):
        css = _read(BRIDGE_PENDING_CSS)
        self.assertNotIn("color: #F5B87C", css,
                         "bridge_pending.css still uses bare color: #F5B87C;"
                         " repoint to var(--signal-gold).")

    def test_no_hardcoded_lavender_hex(self):
        """All three #8A8CF0 give-button / defer-hover literals must be
        gone; they map cleanly onto --signal-info (exact case-insensitive
        match to the tokens.css declaration #8a8cf0)."""
        css = _read(BRIDGE_PENDING_CSS)
        self.assertNotIn("color: #8A8CF0", css,
                         "bridge_pending.css still uses bare color: #8A8CF0;"
                         " repoint to var(--signal-info).")
        self.assertNotIn("border-color: #8A8CF0", css,
                         "bridge_pending.css still uses bare border-color:"
                         " #8A8CF0; repoint to var(--signal-info).")

    def test_no_hardcoded_accept_green_hex(self):
        """The #6FD080 accept-hover green must be gone; close enough
        to --signal-good (#6ec977) for semantic consolidation."""
        css = _read(BRIDGE_PENDING_CSS)
        self.assertNotIn("color: #6FD080", css,
                         "bridge_pending.css still uses bare color: #6FD080;"
                         " repoint to var(--signal-good).")
        self.assertNotIn("border-color: #6FD080", css,
                         "bridge_pending.css still uses bare border-color:"
                         " #6FD080; repoint to var(--signal-good).")

    def test_consumes_signal_vars(self):
        css = _read(BRIDGE_PENDING_CSS)
        self.assertIn("var(--signal-gold)", css,
                      "bridge_pending.css must consume var(--signal-gold)"
                      " for the coach-decision-title")
        self.assertIn("var(--signal-info)", css,
                      "bridge_pending.css must consume var(--signal-info)"
                      " for the give-action + defer-hover")
        self.assertIn("var(--signal-good)", css,
                      "bridge_pending.css must consume var(--signal-good)"
                      " for the accept-hover")

    def test_brand_salmon_preserved(self):
        """#F07E8B coral/salmon (coach contest button + bp-btn-dismiss
        hover + rcc-choice-contest + bp-btn-err) is a panel-specific
        brand color tuned to the bridge-pending escalation queue's
        visual language; not on the semantic --signal-bad red.
        PRESERVED. Mirrors the cd_ledger enemy-team #f07e8b tint."""
        css = _read(BRIDGE_PENDING_CSS)
        self.assertIn("#F07E8B", css,
                      "coach contest + dismiss salmon brand color preserved")

    def test_menu_badge_black_text_preserved(self):
        """#000 is the text-on-gold contrast for the menu-badge pill;
        not a semantic color, do NOT sweep."""
        css = _read(BRIDGE_PENDING_CSS)
        self.assertIn("color: #000", css,
                      "menu-badge text-on-gold black preserved")


class AsciiHygieneTests(unittest.TestCase):
    """No em/en-dashes or smart quotes in any of the 5 panel files
    per the project hard rule. BAD dict via chr() so this test file
    stays ASCII-clean against its own scan (mirrors
    test_design_tokens_css.py::AsciiHygieneTests)."""

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

    def test_item_build_css_is_ascii_clean(self):
        self.assertEqual([], self._scan(ITEM_BUILD_CSS),
                         "item_build.css contains forbidden non-ASCII")

    def test_augment_reco_css_is_ascii_clean(self):
        self.assertEqual([], self._scan(AUGMENT_RECO_CSS),
                         "augment_reco.css contains forbidden non-ASCII")

    def test_team_context_css_is_ascii_clean(self):
        self.assertEqual([], self._scan(TEAM_CONTEXT_CSS),
                         "team_context.css contains forbidden non-ASCII")

    def test_cd_ledger_css_is_ascii_clean(self):
        self.assertEqual([], self._scan(CD_LEDGER_CSS),
                         "cd_ledger.css contains forbidden non-ASCII")

    def test_bridge_pending_css_is_ascii_clean(self):
        self.assertEqual([], self._scan(BRIDGE_PENDING_CSS),
                         "bridge_pending.css contains forbidden non-ASCII")


if __name__ == "__main__":
    unittest.main()
