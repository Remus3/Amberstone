"""Regression guards for the DS action-queue combo panel (competitor
lift #2, docs/COMPETITOR_LIFT_2026-05-30.md).

Backend dashboard/routes_ds_combo.py + its engine module
agents/daemon_slayer/combo.py ship with their own suites
(tests/test_routes_ds_combo.py +
agents/daemon_slayer/tests/test_combo_2026_05_30.py). This file pins the
TWO NEW frontend files this slice owns:

  - web/js/panels/ds_combo.js exports the API contract (fetchDsCombo,
    getCachedDsCombo, getDsComboCacheCount, renderDsCombo, parseSeqInput)
    and references the expected DOM ids/classes the host mounts into.
  - web/css/panels/ds_combo.css carries the .ds-combo card + timeline-row
    classes and uses semantic tokens.

The SHARED-FILE wiring (web/index.html mount block #csv-sugg-ds-combo,
the @import into web/css/dashboard.css, and the champ_select.js mount
call) is added by the orchestrator (this agent is forbidden from editing
those shared files). Those wires get their own guard once landed; here we
only assert the two NEW files are coherent + ASCII-clean so a refactor
that breaks an export / class name is caught.

Grep-based smoke checks - cheap, fast. Mirrors test_cooldown_watch_panel_dom.py.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "ds_combo.js"
PANEL_CSS = WEB / "css" / "panels" / "ds_combo.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class FilesExistTests(unittest.TestCase):
    def test_panel_js_exists(self) -> None:
        self.assertTrue(PANEL_JS.is_file(), f"missing {PANEL_JS}")

    def test_panel_css_exists(self) -> None:
        self.assertTrue(PANEL_CSS.is_file(), f"missing {PANEL_CSS}")


class JsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_exports_fetch(self) -> None:
        self.assertIn("export function fetchDsCombo", self.text)

    def test_exports_get_cached(self) -> None:
        self.assertIn("export function getCachedDsCombo", self.text)

    def test_exports_cache_count(self) -> None:
        self.assertIn("export function getDsComboCacheCount", self.text)

    def test_exports_render(self) -> None:
        self.assertIn("export function renderDsCombo", self.text)

    def test_exports_parse_seq(self) -> None:
        self.assertIn("export function parseSeqInput", self.text)

    def test_exports_reset_helper(self) -> None:
        self.assertIn("export function _resetDsCombo", self.text)

    def test_fetches_backend_route(self) -> None:
        self.assertIn("/api/ds-combo?", self.text)

    def test_references_expected_dom_ids(self) -> None:
        # The render fn builds a per-block input + timeline container keyed
        # off the block id; assert the id suffixes the host depends on.
        self.assertIn("-input", self.text)
        self.assertIn("-table", self.text)
        self.assertIn("dscombo-table", self.text)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _read(PANEL_CSS)

    def test_card_class_present(self) -> None:
        self.assertIn(".ds-combo", self.css)
        self.assertIn(".dscombo-row", self.css)
        self.assertIn(".dscombo-cum", self.css)

    def test_input_class_present(self) -> None:
        self.assertIn(".dscombo-input", self.css)

    def test_cooldown_row_styling(self) -> None:
        self.assertIn("data-dscombo-cd", self.css)

    def test_uses_signal_tokens(self) -> None:
        self.assertIn("var(--signal-info", self.css)

    def test_hidden_rule_present(self) -> None:
        self.assertIn("[hidden]", self.css)


class AsciiHygieneTests(unittest.TestCase):
    _BAD = (chr(0x2013), chr(0x2014), chr(0x2018), chr(0x2019),
            chr(0x201C), chr(0x201D), chr(0x2026))

    def _scan(self, path: Path) -> list[int]:
        text = path.read_text(encoding="utf-8")
        return [i for i, c in enumerate(text) if c in self._BAD]

    def test_panel_js_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_JS), [])

    def test_panel_css_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_CSS), [])

    def test_this_test_file_is_ascii(self) -> None:
        self.assertEqual(self._scan(Path(__file__)), [])


if __name__ == "__main__":
    unittest.main()
