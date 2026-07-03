"""Regression guards for the ally CC-pairing card (CS1) - updated for the
2026-07-03 champ-select QA (slice A, ruling B12 in
docs/qa/CHAMP_SELECT_QA_2026-07-03.md).

B12: the CC pairing card was REMOVED from champ select. The backend
(dashboard/routes_cc_pairing.py) and the frontend module
(web/js/panels/cc_pairing.js) STAY - only the champ-select mount + wiring
are gone. This file pins BOTH directions:

  - web/index.html no longer carries #csv-sugg-cc-pairing.
  - web/js/panels/champ_select.js no longer imports or renders the panel.
  - web/js/panels/cc_pairing.js still exports its full API contract.

Grep-based smoke checks - cheap, fast, enough to catch a re-wire drift.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX_HTML = WEB / "index.html"
PANEL_JS = WEB / "js" / "panels" / "cc_pairing.js"
CHAMP_SELECT_JS = WEB / "js" / "panels" / "champ_select.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class ChipMountRemovedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_mount_removed(self) -> None:
        self.assertNotIn('id="csv-sugg-cc-pairing"', self.text)


class JsConsumptionRemovedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.panel_text = _read(PANEL_JS)
        cls.cs_text = _read(CHAMP_SELECT_JS)

    # The module keeps its API contract (backend + module stay).
    def test_panel_exports_fetch(self) -> None:
        self.assertIn("export function fetchCcPairing", self.panel_text)

    def test_panel_exports_get_cached(self) -> None:
        self.assertIn("export function getCachedCcPairing", self.panel_text)

    def test_panel_exports_cache_count(self) -> None:
        self.assertIn("export function getCcPairingCacheCount",
                      self.panel_text)

    def test_panel_exports_render(self) -> None:
        self.assertIn("export function renderCcPairing", self.panel_text)

    # Champ select dropped the import + render + sig fold (B12).
    def test_champ_select_import_removed(self) -> None:
        self.assertNotIn("from './cc_pairing.js'", self.cs_text)
        self.assertNotIn("fetchCcPairing", self.cs_text)
        self.assertNotIn("renderCcPairing", self.cs_text)

    def test_champ_select_renderer_removed(self) -> None:
        self.assertNotIn("function _csvRenderCcPairing", self.cs_text)
        self.assertNotIn("_csvRenderCcPairing(cs)", self.cs_text)

    def test_section_signature_fold_removed(self) -> None:
        self.assertNotIn("getCcPairingCacheCount", self.cs_text)
        self.assertNotIn("ccpair:", self.cs_text)


class AsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii(self) -> None:
        raw = Path(__file__).read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
