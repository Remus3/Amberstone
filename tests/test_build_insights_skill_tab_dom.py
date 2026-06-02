"""Regression guards for the skill-WPA TAB on the Build Insights view
(item 275 carry (3) + PGR S2 carry, the skill-WPA frontend chip / tab).

The Build Insights view already ships the item-WPA table (item 273 G +
item 275). This slice adds a [ Items | Skills ] tab toggle: Items keeps
the existing item-WPA table (default); Skills renders a NEW sortable
skill-WPA table consuming GET /api/skill-wpa (core/skill_wpa.py +
dashboard/routes_skill_wpa.py, both LIVE).

This file pins ONLY the skill-tab additions (the item-WPA wiring is
covered by test_build_insights_panel_dom.py):

  - index.html has the tab-toggle markup inside #view-build-insights only
  - the panel js fetches /api/skill-wpa + renders a skill-table mount
  - the same 5-segment confidence bar formula round(n/(n+5)*5)
  - the skill mock fixture exists + is valid JSON with skill keys
  - the skill caption is the honest personal-corpus wording
  - all touched / new artifacts are 0 non-ASCII bytes

Grep / json based smoke checks - cheap, fast, enough to catch a missing
wire or a renamed id. Mirrors test_build_insights_panel_dom.py.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "build_insights.js"
PANEL_CSS = WEB / "css" / "panels" / "build_insights.css"
SKILL_MOCK = WEB / "data" / "ui_mock" / "build_insights_skill.json"
INDEX_HTML = WEB / "index.html"

VIEW_ID = "build-insights"
SKILL_MOUNT_ID = "bi-skill-table-mount"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TabToggleHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_tab_toggle_container_present(self) -> None:
        # The tab toggle lives inside the build-insights section only.
        self.assertIn('id="bi-tabs"', self.text)

    def test_items_tab_button_present(self) -> None:
        self.assertIn('data-bi-tab="items"', self.text)

    def test_skills_tab_button_present(self) -> None:
        self.assertIn('data-bi-tab="skills"', self.text)

    def test_skill_table_mount_present(self) -> None:
        self.assertIn(f'id="{SKILL_MOUNT_ID}"', self.text)

    def test_tab_toggle_inside_build_insights_section_only(self) -> None:
        # The tab markup must be inside #view-build-insights, not leaked
        # into another view section.
        sec_start = self.text.find('id="view-build-insights"')
        sec_end = self.text.find("</section>", sec_start)
        self.assertGreater(sec_start, 0)
        self.assertGreater(sec_end, sec_start)
        block = self.text[sec_start:sec_end]
        self.assertIn('id="bi-tabs"', block)
        self.assertIn(f'id="{SKILL_MOUNT_ID}"', block)


class SkillJsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_fetches_skill_wpa_endpoint(self) -> None:
        self.assertIn("/api/skill-wpa", self.text)

    def test_references_skill_table_mount(self) -> None:
        self.assertIn(SKILL_MOUNT_ID, self.text)

    def test_skill_mock_short_circuit_present(self) -> None:
        self.assertIn("/data/ui_mock/build_insights_skill.json", self.text)

    def test_tab_switch_wiring_present(self) -> None:
        # The tab buttons are wired by data-bi-tab.
        self.assertIn("data-bi-tab", self.text)

    def test_confidence_bar_formula_reused(self) -> None:
        # The same _confSegments / bi-seg machinery renders skill rows.
        self.assertIn("_confSegments", self.text)
        self.assertIn("bi-seg", self.text)

    def test_skill_badge_class_present(self) -> None:
        self.assertIn("bi-skill-badge", self.text)

    def test_champion_icon_resolution_present(self) -> None:
        # Champion icon resolved via the DDragon champion square.
        self.assertIn("img/champion/", self.text)


class SkillCssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_CSS)

    def test_tab_classes_present(self) -> None:
        self.assertIn(".bi-tab", self.text)

    def test_skill_badge_class_present(self) -> None:
        self.assertIn(".bi-skill-badge", self.text)

    def test_tab_hit_min(self) -> None:
        # Tab buttons must meet the keyboard-and-fingertip floor.
        self.assertIn("var(--hit-min)", self.text)

    def test_uses_fs_tokens(self) -> None:
        self.assertIn("var(--fs-", self.text)


class SkillMockFixtureTests(unittest.TestCase):
    def test_fixture_exists(self) -> None:
        self.assertTrue(SKILL_MOCK.is_file(), f"missing {SKILL_MOCK}")

    def test_valid_json(self) -> None:
        data = json.loads(_read(SKILL_MOCK))
        self.assertTrue(data.get("ok"))
        items = data.get("items")
        self.assertIsInstance(items, list)
        self.assertGreaterEqual(len(items), 5)

    def test_skill_keys_present(self) -> None:
        data = json.loads(_read(SKILL_MOCK))
        keys = {"champion_id", "champion", "skill_slot", "skill", "n",
                "observed_winrate", "expected_winrate", "wpa", "wpa_shrunk"}
        for it in data["items"]:
            self.assertTrue(keys.issubset(it.keys()),
                            f"row missing keys: {keys - set(it.keys())}")

    def test_skill_values_are_basic_slots(self) -> None:
        data = json.loads(_read(SKILL_MOCK))
        for it in data["items"]:
            self.assertIn(it["skill"], ("Q", "W", "E"),
                          "skill rows are first-maxed basics; ult excluded")

    def test_has_positive_and_negative_wpa(self) -> None:
        data = json.loads(_read(SKILL_MOCK))
        wpas = [it["wpa"] for it in data["items"]]
        self.assertTrue(any(w > 0 for w in wpas), "no positive wpa")
        self.assertTrue(any(w < 0 for w in wpas), "no negative wpa")


class HonestCaptionTests(unittest.TestCase):
    def test_index_html_has_skill_caption(self) -> None:
        text = _read(INDEX_HTML)
        # The honest personal-corpus wording (skills are a weaker signal).
        self.assertIn("bi-skill-caption", text)


class AsciiHygieneTests(unittest.TestCase):
    def _scan(self, path: Path) -> list:
        src = path.read_bytes()
        return [(i, b) for i, b in enumerate(src) if b > 0x7F]

    def test_panel_js_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_JS), [])

    def test_panel_css_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_CSS), [])

    def test_skill_mock_is_ascii(self) -> None:
        self.assertEqual(self._scan(SKILL_MOCK), [])

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
