"""Deletion guards for the champ-select cooldown-watch panel.

History: competitor lift #5 shipped the panel; the 2026-07-03 champ-select
QA (ruling B19 in docs/qa/CHAMP_SELECT_QA_2026-07-03.md) removed the card
from champ select, which orphaned the frontend module (champ select was
its sole consumer); the operator-approved follow-up cleanup (LEDGER 765)
then DELETED web/js/panels/cooldown_watch.js + its CSS. The backend
(dashboard/routes_cooldown_watch.py + agents/daemon_slayer/cooldown_watch.py)
STAYS - covered by its own route tests.

These grep guards pin the deleted state so a partial re-wire cannot drift
back in silently. A future consumer (e.g. an overlay widget) should add a
NEW module + its own guards, not resurrect the old file ad hoc.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX_HTML = WEB / "index.html"
PANEL_JS = WEB / "js" / "panels" / "cooldown_watch.js"
PANEL_CSS = WEB / "css" / "panels" / "cooldown_watch.css"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"
CHAMP_SELECT_JS = WEB / "js" / "panels" / "champ_select.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class ModuleDeletedTests(unittest.TestCase):
    def test_panel_js_deleted(self) -> None:
        self.assertFalse(PANEL_JS.exists(), f"{PANEL_JS} should be deleted")

    def test_panel_css_deleted(self) -> None:
        self.assertFalse(PANEL_CSS.exists(), f"{PANEL_CSS} should be deleted")

    def test_dashboard_css_import_removed(self) -> None:
        self.assertNotIn("panels/cooldown_watch.css", _read(DASHBOARD_CSS))


class ChipMountRemovedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_mount_removed(self) -> None:
        self.assertNotIn('id="csv-sugg-cooldown-watch"', self.text)


class JsConsumptionRemovedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cs_text = _read(CHAMP_SELECT_JS)

    # Champ select dropped the import + render + sig fold (B19).
    def test_champ_select_import_removed(self) -> None:
        self.assertNotIn("from './cooldown_watch.js'", self.cs_text)
        self.assertNotIn("fetchCooldownWatch", self.cs_text)
        self.assertNotIn("renderCooldownWatch", self.cs_text)

    def test_champ_select_renderer_removed(self) -> None:
        self.assertNotIn("function _csvRenderCooldownWatch", self.cs_text)
        self.assertNotIn("_csvRenderCooldownWatch(cs)", self.cs_text)

    def test_section_signature_fold_removed(self) -> None:
        self.assertNotIn("getCooldownWatchCacheCount", self.cs_text)
        self.assertNotIn("cdw:", self.cs_text)

    def test_no_other_js_consumer(self) -> None:
        # Whole-tree guard: no web JS imports the deleted module.
        for f in (WEB / "js").rglob("*.js"):
            self.assertNotIn(
                "from './cooldown_watch.js'", _read(f),
                f"{f} imports the deleted cooldown_watch.js",
            )


class BackendKeptTests(unittest.TestCase):
    def test_route_module_still_exists(self) -> None:
        self.assertTrue(
            (ROOT / "dashboard" / "routes_cooldown_watch.py").exists(),
            "backend route module must stay (operator kept all backends)",
        )


class AsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii(self) -> None:
        raw = Path(__file__).read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
