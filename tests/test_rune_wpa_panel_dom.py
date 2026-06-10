"""Regression guards for the rune-WPA TAB on the Build Insights view
(item 273 extension to RUNES, the pre-game WPA analog of the item-WPA /
skill-WPA build-insights tables).

The Build Insights view ships the item-WPA table (item 273) + the skill-WPA
tab (item 275). This slice folds rune-WPA in as a THIRD tab rather than a
standalone panel: Items keeps the existing item-WPA table (default); Skills
renders the skill-WPA table; Runes renders a NEW sortable rune-WPA table
consuming GET /api/rune-wpa (core/rune_wpa.py + dashboard/routes_rune_wpa.py,
both LIVE). The unit is (rune_id, slot_kind=keystone|minor).

This file pins ONLY the rune-tab additions (the item + skill wiring is
covered by test_build_insights_panel_dom.py + test_build_insights_skill_tab
_dom.py):

  - index.html has the Runes tab button + the rune-table mount inside
    #view-build-insights only
  - the panel js fetches /api/rune-wpa + renders the rune-table mount
  - the panel reuses the shared 5-segment confidence bar round(n/(n+5)*5)
  - the rune mock fixture (web/data/ui_mock/rune_wpa.json) exists + is valid
    JSON with the rune keys + both slot kinds
  - the rune caption is the honest personal-corpus wording
  - all touched / new artifacts add 0 non-ASCII bytes

Grep / json based smoke checks - cheap, fast, enough to catch a missing
wire or a renamed id. Mirrors test_build_insights_skill_tab_dom.py.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "build_insights.js"
PANEL_CSS = WEB / "css" / "panels" / "build_insights.css"
RUNE_MOCK = WEB / "data" / "ui_mock" / "rune_wpa.json"
INDEX_HTML = WEB / "index.html"

RUNE_MOUNT_ID = "bi-rune-table-mount"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TabToggleHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_tab_toggle_container_present(self) -> None:
        # The tab toggle lives inside the build-insights section only.
        self.assertIn('id="bi-tabs"', self.text)

    def test_runes_tab_button_present(self) -> None:
        self.assertIn('data-bi-tab="runes"', self.text)

    def test_rune_table_mount_present(self) -> None:
        self.assertIn(f'id="{RUNE_MOUNT_ID}"', self.text)

    def test_rune_pane_present(self) -> None:
        self.assertIn('data-bi-pane="runes"', self.text)

    def test_runes_tab_inside_build_insights_section_only(self) -> None:
        # The tab markup must be inside #view-build-insights, not leaked
        # into another view section.
        sec_start = self.text.find('id="view-build-insights"')
        sec_end = self.text.find("</section>", sec_start)
        self.assertGreater(sec_start, 0)
        self.assertGreater(sec_end, sec_start)
        block = self.text[sec_start:sec_end]
        self.assertIn('data-bi-tab="runes"', block)
        self.assertIn(f'id="{RUNE_MOUNT_ID}"', block)


class RuneJsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_fetches_rune_wpa_endpoint(self) -> None:
        self.assertIn("/api/rune-wpa", self.text)

    def test_references_rune_table_mount(self) -> None:
        self.assertIn(RUNE_MOUNT_ID, self.text)

    def test_rune_mock_short_circuit_present(self) -> None:
        self.assertIn("/data/ui_mock/rune_wpa.json", self.text)

    def test_tab_switch_wiring_present(self) -> None:
        # The tab buttons are wired by data-bi-tab.
        self.assertIn("data-bi-tab", self.text)

    def test_confidence_bar_formula_reused(self) -> None:
        # The same _confSegments / bi-seg machinery renders rune rows.
        self.assertIn("_confSegments", self.text)
        self.assertIn("bi-seg", self.text)

    def test_slot_kind_badge_present(self) -> None:
        # keystone vs minor is shown as a badge keyed on slot_kind.
        self.assertIn("bi-slot-badge", self.text)
        self.assertIn("slot_kind", self.text)

    def test_rune_icon_resolution_present(self) -> None:
        # Rune icon resolved via the DDragon perk-images path.
        self.assertIn("perk-images", self.text)


class RuneCssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_CSS)

    def test_tab_classes_present(self) -> None:
        self.assertIn(".bi-tab", self.text)

    def test_slot_badge_class_present(self) -> None:
        self.assertIn(".bi-slot-badge", self.text)

    def test_rune_icon_class_present(self) -> None:
        self.assertIn(".bi-rune-icon", self.text)

    def test_tab_hit_min(self) -> None:
        # Tab buttons must meet the keyboard-and-fingertip floor.
        self.assertIn("var(--hit-min)", self.text)

    def test_uses_fs_tokens(self) -> None:
        self.assertIn("var(--fs-", self.text)


class RuneMockFixtureTests(unittest.TestCase):
    def test_fixture_exists(self) -> None:
        self.assertTrue(RUNE_MOCK.is_file(), f"missing {RUNE_MOCK}")

    def test_valid_json(self) -> None:
        data = json.loads(_read(RUNE_MOCK))
        self.assertTrue(data.get("ok"))
        items = data.get("items")
        self.assertIsInstance(items, list)
        self.assertGreaterEqual(len(items), 5)

    def test_rune_keys_present(self) -> None:
        data = json.loads(_read(RUNE_MOCK))
        keys = {"rune_id", "name", "icon", "slot_kind", "n",
                "observed_winrate", "expected_winrate", "wpa", "wpa_shrunk"}
        for it in data["items"]:
            self.assertTrue(keys.issubset(it.keys()),
                            f"row missing keys: {keys - set(it.keys())}")

    def test_slot_kinds_valid(self) -> None:
        data = json.loads(_read(RUNE_MOCK))
        kinds = {it["slot_kind"] for it in data["items"]}
        self.assertTrue(kinds.issubset({"keystone", "minor"}))
        # Both kinds should be represented for an honest fixture.
        self.assertIn("keystone", kinds)
        self.assertIn("minor", kinds)

    def test_has_positive_and_negative_wpa(self) -> None:
        data = json.loads(_read(RUNE_MOCK))
        wpas = [it["wpa"] for it in data["items"]]
        self.assertTrue(any(w > 0 for w in wpas), "no positive wpa")
        self.assertTrue(any(w < 0 for w in wpas), "no negative wpa")


class HonestCaptionTests(unittest.TestCase):
    def test_index_html_has_rune_caption(self) -> None:
        text = _read(INDEX_HTML)
        # The honest personal-corpus wording (runes are a weaker signal).
        self.assertIn("bi-rune-caption", text)


class AsciiHygieneTests(unittest.TestCase):
    def _scan(self, path: Path) -> list:
        src = path.read_bytes()
        return [(i, b) for i, b in enumerate(src) if b > 0x7F]

    def test_panel_js_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_JS), [])

    def test_panel_css_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_CSS), [])

    def test_rune_mock_is_ascii(self) -> None:
        self.assertEqual(self._scan(RUNE_MOCK), [])

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
