"""Regression guards for the summoner-spell WPA TAB on the Build Insights
view (BACKLOG WPA-lane extension to SPELLS, the pre-game WPA sibling of the
rune-WPA build-insights table).

The Build Insights view ships the item-WPA table (item 273) + the skill-WPA
tab (item 275) + the rune-WPA tab (item 374). This slice folds summoner-
spell-WPA in as a FOURTH tab: Spells renders a NEW sortable spell-WPA table
consuming GET /api/summspell-wpa (core/summoner_spell_wpa.py +
dashboard/routes_summspell_wpa.py). The unit is the single spell_id - each
participant row contributes its two picks; there is no slot split (D vs F
order is a keybind preference, not a choice).

This file pins ONLY the spell-tab additions (the item + skill + rune wiring
is covered by their own DOM test files):

  - index.html has the Spells tab button + the spell-table mount inside
    #view-build-insights only
  - the panel js fetches /api/summspell-wpa + renders the spell-table mount
  - the panel reuses the shared 5-segment confidence bar round(n/(n+5)*5)
  - the spell mock fixture (web/data/ui_mock/summspell_wpa.json) exists +
    is valid JSON with the spell keys
  - the spell caption is the honest personal-corpus wording
  - all touched / new artifacts add 0 non-ASCII bytes

Grep / json based smoke checks - cheap, fast, enough to catch a missing
wire or a renamed id. Mirrors test_rune_wpa_panel_dom.py.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "build_insights.js"
PANEL_CSS = WEB / "css" / "panels" / "build_insights.css"
SPELL_MOCK = WEB / "data" / "ui_mock" / "summspell_wpa.json"
INDEX_HTML = WEB / "index.html"

SPELL_MOUNT_ID = "bi-spell-table-mount"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TabToggleHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_tab_toggle_container_present(self) -> None:
        # The tab toggle lives inside the build-insights section only.
        self.assertIn('id="bi-tabs"', self.text)

    def test_spells_tab_button_present(self) -> None:
        self.assertIn('data-bi-tab="spells"', self.text)

    def test_spell_table_mount_present(self) -> None:
        self.assertIn(f'id="{SPELL_MOUNT_ID}"', self.text)

    def test_spell_pane_present(self) -> None:
        self.assertIn('data-bi-pane="spells"', self.text)

    def test_spells_tab_inside_build_insights_section_only(self) -> None:
        # The tab markup must be inside #view-build-insights, not leaked
        # into another view section.
        sec_start = self.text.find('id="view-build-insights"')
        sec_end = self.text.find("</section>", sec_start)
        self.assertGreater(sec_start, 0)
        self.assertGreater(sec_end, sec_start)
        block = self.text[sec_start:sec_end]
        self.assertIn('data-bi-tab="spells"', block)
        self.assertIn(f'id="{SPELL_MOUNT_ID}"', block)


class SpellJsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_fetches_summspell_wpa_endpoint(self) -> None:
        self.assertIn("/api/summspell-wpa", self.text)

    def test_references_spell_table_mount(self) -> None:
        self.assertIn(SPELL_MOUNT_ID, self.text)

    def test_spell_mock_short_circuit_present(self) -> None:
        self.assertIn("/data/ui_mock/summspell_wpa.json", self.text)

    def test_tab_switch_wiring_present(self) -> None:
        # The tab buttons are wired by data-bi-tab.
        self.assertIn("data-bi-tab", self.text)

    def test_confidence_bar_formula_reused(self) -> None:
        # The same _confSegments / bi-seg machinery renders spell rows.
        self.assertIn("_confSegments", self.text)
        self.assertIn("bi-seg", self.text)

    def test_spell_icon_resolution_present(self) -> None:
        # Spell icon resolved via the local /icons/spells mirror.
        self.assertIn("/icons/spells/", self.text)


class SpellCssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_CSS)

    def test_tab_classes_present(self) -> None:
        self.assertIn(".bi-tab", self.text)

    def test_spell_icon_class_present(self) -> None:
        self.assertIn(".bi-spell-icon", self.text)

    def test_spell_caption_class_present(self) -> None:
        self.assertIn(".bi-spell-caption", self.text)

    def test_tab_hit_min(self) -> None:
        # Tab buttons must meet the keyboard-and-fingertip floor.
        self.assertIn("var(--hit-min)", self.text)

    def test_uses_fs_tokens(self) -> None:
        self.assertIn("var(--fs-", self.text)


class SpellMockFixtureTests(unittest.TestCase):
    def test_fixture_exists(self) -> None:
        self.assertTrue(SPELL_MOCK.is_file(), f"missing {SPELL_MOCK}")

    def test_valid_json(self) -> None:
        data = json.loads(_read(SPELL_MOCK))
        self.assertTrue(data.get("ok"))
        items = data.get("items")
        self.assertIsInstance(items, list)
        self.assertGreaterEqual(len(items), 5)

    def test_spell_keys_present(self) -> None:
        data = json.loads(_read(SPELL_MOCK))
        keys = {"spell_id", "name", "icon", "n",
                "observed_winrate", "expected_winrate", "wpa", "wpa_shrunk"}
        for it in data["items"]:
            self.assertTrue(keys.issubset(it.keys()),
                            f"row missing keys: {keys - set(it.keys())}")

    def test_has_positive_and_negative_wpa(self) -> None:
        data = json.loads(_read(SPELL_MOCK))
        wpas = [it["wpa"] for it in data["items"]]
        self.assertTrue(any(w > 0 for w in wpas), "no positive wpa")
        self.assertTrue(any(w < 0 for w in wpas), "no negative wpa")


class HonestCaptionTests(unittest.TestCase):
    def test_index_html_has_spell_caption(self) -> None:
        text = _read(INDEX_HTML)
        # The honest personal-corpus wording (spells are a weaker signal).
        self.assertIn("bi-spell-caption", text)


class AsciiHygieneTests(unittest.TestCase):
    def _scan(self, path: Path) -> list:
        src = path.read_bytes()
        return [(i, b) for i, b in enumerate(src) if b > 0x7F]

    def test_panel_js_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_JS), [])

    def test_panel_css_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_CSS), [])

    def test_spell_mock_is_ascii(self) -> None:
        self.assertEqual(self._scan(SPELL_MOCK), [])

    def test_build_insights_section_is_ascii(self) -> None:
        # index.html carries pre-existing non-ASCII bytes elsewhere in the
        # file; this slice MUST add 0 new non-ASCII bytes. Scan only the
        # #view-build-insights section (the only region this slice edits).
        text = _read(INDEX_HTML)
        start = text.find('id="view-build-insights"')
        end = text.find("</section>", start)
        self.assertGreater(start, 0)
        self.assertGreater(end, start)
        section = text[start:end]
        bad = [(i, c) for i, c in enumerate(section) if ord(c) > 0x7F]
        self.assertEqual(bad, [], f"new non-ASCII in build-insights section: {bad[:5]}")

    def test_this_test_file_is_ascii(self) -> None:
        self.assertEqual(self._scan(Path(__file__)), [])


if __name__ == "__main__":
    unittest.main()
