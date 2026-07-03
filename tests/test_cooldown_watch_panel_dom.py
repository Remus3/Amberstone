"""Regression guards for the matchup cooldown-watch panel (competitor
lift #5) - updated for the 2026-07-03 champ-select QA (slice A, ruling
B19 in docs/qa/CHAMP_SELECT_QA_2026-07-03.md).

B19: the cooldown-watch card was REMOVED from champ select (the overlay
surfaces the same signal in-game when it matters). The backend
(dashboard/routes_cooldown_watch.py + agents/daemon_slayer/cooldown_watch.py)
and the frontend module (web/js/panels/cooldown_watch.js) STAY - only the
champ-select mount + wiring are gone. This file now pins BOTH directions:

  - web/index.html no longer carries #csv-sugg-cooldown-watch.
  - web/js/panels/champ_select.js no longer imports or renders the panel.
  - web/js/panels/cooldown_watch.js still exports its full API contract
    (the module is currently orphaned - champ select was its sole
    consumer - kept for the in-game overlay follow-up).

Grep-based smoke checks - cheap, fast, enough to catch a re-wire drift.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX_HTML = WEB / "index.html"
PANEL_JS = WEB / "js" / "panels" / "cooldown_watch.js"
CHAMP_SELECT_JS = WEB / "js" / "panels" / "champ_select.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class ChipMountRemovedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_mount_removed(self) -> None:
        self.assertNotIn('id="csv-sugg-cooldown-watch"', self.text)


class JsConsumptionRemovedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.panel_text = _read(PANEL_JS)
        cls.cs_text = _read(CHAMP_SELECT_JS)

    # The module keeps its API contract (overlay follow-up consumer).
    def test_panel_exports_fetch(self) -> None:
        self.assertIn("export function fetchCooldownWatch", self.panel_text)

    def test_panel_exports_get_cached(self) -> None:
        self.assertIn("export function getCachedCooldownWatch",
                      self.panel_text)

    def test_panel_exports_cache_count(self) -> None:
        self.assertIn("export function getCooldownWatchCacheCount",
                      self.panel_text)

    def test_panel_exports_render(self) -> None:
        self.assertIn("export function renderCooldownWatch", self.panel_text)

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


class AsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii(self) -> None:
        raw = Path(__file__).read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
