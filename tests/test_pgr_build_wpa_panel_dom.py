"""Regression guards for the PGR S2 "your build, graded by your career"
WPA strip (item 275, docs/PGR_REFRAME_S2.md).

Career item-WPA + skill-WPA chips on the reviewed match's actual loadout,
mounted under the hero in the last-match view. Grep / file / json based
smoke checks pin the cross-file wiring + the panel contract. Mirrors
test_build_insights_panel_dom.py.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "pgr_build_wpa.js"
PANEL_CSS = WEB / "css" / "panels" / "pgr_build_wpa.css"
LAST_MATCH_JS = WEB / "js" / "panels" / "last_match.js"
INDEX_HTML = WEB / "index.html"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"

MOUNT_ID = "pgr-build-wpa-mount"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class FilesExistTests(unittest.TestCase):
    def test_panel_js_exists(self) -> None:
        self.assertTrue(PANEL_JS.is_file(), f"missing {PANEL_JS}")

    def test_panel_css_exists(self) -> None:
        self.assertTrue(PANEL_CSS.is_file(), f"missing {PANEL_CSS}")


class IndexHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_mount_present(self) -> None:
        self.assertIn(f'id="{MOUNT_ID}"', self.text)

    def test_mount_inside_last_match_view(self) -> None:
        # The mount must sit between the last-match section open and the
        # tabbed section, i.e. under the hero.
        sec = self.text.index('id="view-last-match"')
        mount = self.text.index(f'id="{MOUNT_ID}"')
        tabbed = self.text.index('id="lm-tabbed-section"')
        self.assertLess(sec, mount, "mount before the last-match section")
        self.assertLess(mount, tabbed, "mount must be above the tabbed section")


class LastMatchWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(LAST_MATCH_JS)

    def test_imports_panel(self) -> None:
        self.assertIn("renderPgrBuildWpa", self.text)
        self.assertIn("./pgr_build_wpa.js", self.text)

    def test_dispatches_panel_in_render(self) -> None:
        # renderLastMatch must call renderPgrBuildWpa(data).
        self.assertIn("renderPgrBuildWpa(data)", self.text)


class DashboardCssImportTests(unittest.TestCase):
    def test_imports_panel_css(self) -> None:
        self.assertIn("panels/pgr_build_wpa.css", _read(DASHBOARD_CSS))


class JsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_exports_render(self) -> None:
        self.assertIn("export function renderPgrBuildWpa", self.text)

    def test_exports_test_hook(self) -> None:
        self.assertIn("export const __test", self.text)

    def test_fetches_both_career_endpoints(self) -> None:
        self.assertIn("/api/item-wpa", self.text)
        self.assertIn("/api/skill-wpa", self.text)

    def test_references_mount(self) -> None:
        self.assertIn(MOUNT_ID, self.text)

    def test_skips_trinkets(self) -> None:
        # Trinket/empty-slot ids must be filtered so they carry no chip.
        self.assertIn("_SKIP_ITEM_IDS", self.text)
        self.assertIn("3340", self.text)  # warding trinket

    def test_skill_max_order_best_highlight(self) -> None:
        self.assertIn("is-best", self.text)

    def test_chip_helpers_present(self) -> None:
        self.assertIn("_confSegments", self.text)
        self.assertIn("_signedPP", self.text)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_CSS)

    def test_card_class_present(self) -> None:
        self.assertIn(".pbw-card", self.text)

    def test_pos_neg_classes_present(self) -> None:
        self.assertIn(".pbw-pos", self.text)
        self.assertIn(".pbw-neg", self.text)

    def test_hidden_mount_rule(self) -> None:
        self.assertIn(f"#{MOUNT_ID}[hidden]", self.text)

    def test_uses_signal_token(self) -> None:
        self.assertIn("var(--signal-", self.text)

    def test_uses_fs_token(self) -> None:
        self.assertIn("var(--fs-", self.text)

    def test_hit_min_on_row(self) -> None:
        self.assertIn("var(--hit-min", self.text)


class AsciiHygieneTests(unittest.TestCase):
    def _scan(self, path: Path) -> list:
        return [(i, b) for i, b in enumerate(path.read_bytes()) if b > 0x7F]

    def test_panel_js_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_JS), [])

    def test_panel_css_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_CSS), [])

    def test_this_test_file_is_ascii(self) -> None:
        self.assertEqual(self._scan(Path(__file__)), [])


if __name__ == "__main__":
    unittest.main()
