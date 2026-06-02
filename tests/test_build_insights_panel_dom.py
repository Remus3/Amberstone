"""Regression guards for the Build Insights view (item 273, the competitor site
lift, docs/COMPETITOR_LIFT_2026-06-02.md section 7b).

The view consumes the shipped GET /api/item-wpa as a sortable WPA table.
This file pins the frontend artifacts + the cross-file view wiring:

  - state.js registers the "build-insights" view id (+ label)
  - index.html has the nav button + the view section + the table mount
  - main.js imports + dispatches renderBuildInsights
  - dashboard.css imports the panel css
  - the panel js + css + mock fixture exist and are 0 non-ASCII bytes
  - the mock fixture is valid JSON with the expected item keys

Grep / AST / json based smoke checks - cheap, fast, enough to catch a
missing wire or a renamed id. Mirrors test_ds_relscore_panel_dom.py +
test_callouts_panel_dom.py.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "build_insights.js"
PANEL_CSS = WEB / "css" / "panels" / "build_insights.css"
MOCK = WEB / "data" / "ui_mock" / "build_insights.json"
STATE_JS = WEB / "js" / "lib" / "state.js"
MAIN_JS = WEB / "js" / "main.js"
INDEX_HTML = WEB / "index.html"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"

VIEW_ID = "build-insights"
MOUNT_ID = "bi-table-mount"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class FilesExistTests(unittest.TestCase):
    def test_panel_js_exists(self) -> None:
        self.assertTrue(PANEL_JS.is_file(), f"missing {PANEL_JS}")

    def test_panel_css_exists(self) -> None:
        self.assertTrue(PANEL_CSS.is_file(), f"missing {PANEL_CSS}")

    def test_mock_fixture_exists(self) -> None:
        self.assertTrue(MOCK.is_file(), f"missing {MOCK}")


class StateRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(STATE_JS)

    def test_view_id_in_view_ids(self) -> None:
        # The view id must appear in the VIEW_IDS array.
        self.assertIn(f'"{VIEW_ID}"', self.text)

    def test_view_label_present(self) -> None:
        self.assertIn(f'"{VIEW_ID}": "Build Insights"', self.text)


class IndexHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_nav_button_present(self) -> None:
        self.assertIn(f'data-view="{VIEW_ID}"', self.text)

    def test_section_present(self) -> None:
        self.assertIn(f'id="view-{VIEW_ID}"', self.text)

    def test_table_mount_present(self) -> None:
        self.assertIn(f'id="{MOUNT_ID}"', self.text)

    def test_min_n_input_present(self) -> None:
        self.assertIn('id="bi-min-n"', self.text)


class MainJsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(MAIN_JS)

    def test_imports_panel(self) -> None:
        self.assertIn("renderBuildInsights", self.text)
        self.assertIn("./panels/build_insights.js", self.text)

    def test_dispatches_panel(self) -> None:
        # applyView must call renderBuildInsights on the view branch.
        self.assertIn(f'viewId === "{VIEW_ID}"', self.text)
        self.assertIn("renderBuildInsights()", self.text)


class DashboardCssImportTests(unittest.TestCase):
    def test_imports_panel_css(self) -> None:
        text = _read(DASHBOARD_CSS)
        self.assertIn("panels/build_insights.css", text)


class JsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_exports_render(self) -> None:
        self.assertIn("export function renderBuildInsights", self.text)

    def test_exports_test_hook(self) -> None:
        self.assertIn("export const __test", self.text)

    def test_fetches_item_wpa_endpoint(self) -> None:
        self.assertIn("/api/item-wpa", self.text)

    def test_mock_short_circuit_present(self) -> None:
        # ?ui_mock=1 short-circuits to the fixture.
        self.assertIn("dataset.uiMock", self.text)
        self.assertIn("/data/ui_mock/build_insights.json", self.text)

    def test_references_table_mount(self) -> None:
        self.assertIn(MOUNT_ID, self.text)

    def test_sortable_headers_present(self) -> None:
        self.assertIn("bi-sortable", self.text)
        self.assertIn('data-sort', self.text)

    def test_confidence_bar_present(self) -> None:
        self.assertIn("_confSegments", self.text)
        self.assertIn("bi-seg", self.text)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_CSS)

    def test_table_class_present(self) -> None:
        self.assertIn(".bi-table", self.text)

    def test_wpa_classes_present(self) -> None:
        self.assertIn(".bi-wpa-val", self.text)
        self.assertIn(".bi-pos", self.text)
        self.assertIn(".bi-neg", self.text)

    def test_conf_bar_classes_present(self) -> None:
        self.assertIn(".bi-seg", self.text)

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

    def test_item_keys_present(self) -> None:
        data = json.loads(_read(MOCK))
        keys = {"item_id", "name", "n", "observed_winrate",
                "expected_winrate", "wpa", "wpa_shrunk"}
        for it in data["items"]:
            self.assertTrue(keys.issubset(it.keys()),
                            f"row missing keys: {keys - set(it.keys())}")

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
