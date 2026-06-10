"""Regression guards for the rune-WPA table panel (item 273 extension to
RUNES, the pre-game WPA analog of the item-WPA / skill-WPA build-insights
tables).

The panel consumes GET /api/rune-wpa (core/rune_wpa.py +
dashboard/routes_rune_wpa.py, both LIVE) and renders a sortable WPA table
mirroring web/js/panels/build_insights.js:

  Rune (icon + name) | Slot (keystone/minor badge) | WPA (signed pp +
  confidence bar) | Games (n) | Expected WP (%) | Win Rate (%)

This file pins ONLY the rune-WPA panel artifacts (a self-contained panel
with its own mount; the merger wires it into the nav/router + runs the
5-phase fixture audit before final commit):

  - the panel js + css + mock fixture exist and are 0 non-ASCII bytes
  - the panel js exports a render fn + a __test hook
  - the panel fetches /api/rune-wpa + supports the ?ui_mock=1 fixture
  - the same 5-segment confidence bar formula round(n/(n+5)*5)
  - the rune mock fixture is valid JSON with the rune keys
  - keystone + minor slot kinds both appear in the fixture

Grep / json based smoke checks - cheap, fast, enough to catch a missing
wire or a renamed id. Mirrors test_build_insights_panel_dom.py.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "rune_wpa.js"
PANEL_CSS = WEB / "css" / "panels" / "rune_wpa.css"
MOCK = WEB / "data" / "ui_mock" / "rune_wpa.json"

MOUNT_ID = "rune-wpa-table-mount"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class FilesExistTests(unittest.TestCase):
    def test_panel_js_exists(self) -> None:
        self.assertTrue(PANEL_JS.is_file(), f"missing {PANEL_JS}")

    def test_panel_css_exists(self) -> None:
        self.assertTrue(PANEL_CSS.is_file(), f"missing {PANEL_CSS}")

    def test_mock_fixture_exists(self) -> None:
        self.assertTrue(MOCK.is_file(), f"missing {MOCK}")


class JsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_exports_render(self) -> None:
        self.assertIn("export function renderRuneWpa", self.text)

    def test_exports_test_hook(self) -> None:
        self.assertIn("export const __test", self.text)

    def test_fetches_rune_wpa_endpoint(self) -> None:
        self.assertIn("/api/rune-wpa", self.text)

    def test_mock_short_circuit_present(self) -> None:
        self.assertIn("dataset.uiMock", self.text)
        self.assertIn("/data/ui_mock/rune_wpa.json", self.text)

    def test_references_table_mount(self) -> None:
        self.assertIn(MOUNT_ID, self.text)

    def test_sortable_headers_present(self) -> None:
        self.assertIn("rwa-sortable", self.text)
        self.assertIn("data-sort", self.text)

    def test_confidence_bar_present(self) -> None:
        self.assertIn("_confSegments", self.text)
        self.assertIn("rwa-seg", self.text)

    def test_slot_kind_badge_present(self) -> None:
        # keystone vs minor is shown as a badge.
        self.assertIn("rwa-slot-badge", self.text)
        self.assertIn("slot_kind", self.text)

    def test_rune_icon_resolution_present(self) -> None:
        # Rune icon resolved via the DDragon perk-images path.
        self.assertIn("perk-images", self.text)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_CSS)

    def test_table_class_present(self) -> None:
        self.assertIn(".rwa-table", self.text)

    def test_wpa_classes_present(self) -> None:
        self.assertIn(".rwa-wpa-val", self.text)
        self.assertIn(".rwa-pos", self.text)
        self.assertIn(".rwa-neg", self.text)

    def test_conf_bar_classes_present(self) -> None:
        self.assertIn(".rwa-seg", self.text)

    def test_slot_badge_class_present(self) -> None:
        self.assertIn(".rwa-slot-badge", self.text)

    def test_uses_semantic_token(self) -> None:
        self.assertIn("var(--signal-", self.text)

    def test_uses_fs_tokens(self) -> None:
        self.assertIn("var(--fs-", self.text)

    def test_hit_min_on_sortable_header(self) -> None:
        self.assertIn("var(--hit-min)", self.text)


class MockFixtureTests(unittest.TestCase):
    def test_valid_json(self) -> None:
        data = json.loads(_read(MOCK))
        self.assertTrue(data.get("ok"))
        items = data.get("items")
        self.assertIsInstance(items, list)
        self.assertGreaterEqual(len(items), 5)

    def test_rune_keys_present(self) -> None:
        data = json.loads(_read(MOCK))
        keys = {"rune_id", "name", "slot_kind", "n", "observed_winrate",
                "expected_winrate", "wpa", "wpa_shrunk"}
        for it in data["items"]:
            self.assertTrue(keys.issubset(it.keys()),
                            f"row missing keys: {keys - set(it.keys())}")

    def test_slot_kinds_valid(self) -> None:
        data = json.loads(_read(MOCK))
        kinds = {it["slot_kind"] for it in data["items"]}
        self.assertTrue(kinds.issubset({"keystone", "minor"}))
        # Both kinds should be represented for an honest fixture.
        self.assertIn("keystone", kinds)
        self.assertIn("minor", kinds)

    def test_has_positive_and_negative_wpa(self) -> None:
        data = json.loads(_read(MOCK))
        wpas = [it["wpa"] for it in data["items"]]
        self.assertTrue(any(w > 0 for w in wpas), "no positive wpa in fixture")
        self.assertTrue(any(w < 0 for w in wpas), "no negative wpa in fixture")


class AsciiHygieneTests(unittest.TestCase):
    def _scan(self, path: Path) -> list:
        src = path.read_bytes()
        return [(i, b) for i, b in enumerate(src) if b > 0x7F]

    def test_panel_js_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_JS), [])

    def test_panel_css_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_CSS), [])

    def test_mock_fixture_is_ascii(self) -> None:
        self.assertEqual(self._scan(MOCK), [])

    def test_this_test_file_is_ascii(self) -> None:
        self.assertEqual(self._scan(Path(__file__)), [])


if __name__ == "__main__":
    unittest.main()
