"""Regression guards for the DS relative-score bar panel (competitor lift
#3, docs/COMPETITOR_LIFT_2026-05-30.md "Lift 3").

Backend dashboard/routes_ds_relscore.py ships with its own HTTP-contract
suite (tests/test_routes_ds_relscore.py). This file pins the NEW frontend
artifacts this slice owns - it does NOT assert the cross-file wiring into
champ_select.js / index.html / dashboard.css (the orchestrator wires those
shared files). Here we only guard:

  - web/js/panels/ds_relscore.js exists, is ASCII-clean, exports the API
    contract (renderDsRelscore, getDsRelscoreCacheCount, _resetDsRelscore,
    __test), imports resolveChampNames, references the rows container +
    the bar fill, gates on cs.my_champion.
  - web/css/panels/ds_relscore.css exists, is ASCII-clean, declares the
    card class + the relative-score bar (the hero element) + rows classes
    + uses a semantic token.

Grep-based smoke checks - cheap, fast, enough to catch a missing export or
a renamed class. Mirrors test_ds_knobs_panel_dom.py.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "ds_relscore.js"
PANEL_CSS = WEB / "css" / "panels" / "ds_relscore.css"

# The champ-select mount block id the panel renders into.
BLOCK_ID = "csv-ds-relscore"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class FilesExistTests(unittest.TestCase):
    def test_panel_js_exists(self) -> None:
        self.assertTrue(PANEL_JS.is_file(), f"missing {PANEL_JS}")

    def test_panel_css_exists(self) -> None:
        self.assertTrue(PANEL_CSS.is_file(), f"missing {PANEL_CSS}")


class JsExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_exports_render(self) -> None:
        self.assertIn("export function renderDsRelscore", self.text)

    def test_exports_cache_count(self) -> None:
        self.assertIn("export function getDsRelscoreCacheCount", self.text)

    def test_exports_reset(self) -> None:
        self.assertIn("export function _resetDsRelscore", self.text)

    def test_exports_test_hook(self) -> None:
        self.assertIn("export const __test", self.text)

    def test_imports_resolve_champ_names(self) -> None:
        self.assertIn("resolveChampNames", self.text)
        self.assertIn("./cc_conditional_pressure.js", self.text)

    def test_fetches_ds_relscore_endpoint(self) -> None:
        self.assertIn("/api/ds-relscore", self.text)

    def test_references_rows_container(self) -> None:
        self.assertIn("dsr-rows", self.text)

    def test_references_bar_fill(self) -> None:
        # The bar is the hero element - the fill must be rendered.
        self.assertIn("dsr-bar-fill", self.text)

    def test_gates_on_my_champion(self) -> None:
        # The panel resolves the locked champion from cs.my_champion.
        self.assertIn("my_champion", self.text)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_CSS)

    def test_card_class_present(self) -> None:
        self.assertIn(".ds-relscore", self.text)

    def test_bar_classes_present(self) -> None:
        self.assertIn(".dsr-bar", self.text)
        self.assertIn(".dsr-bar-fill", self.text)

    def test_rows_class_present(self) -> None:
        self.assertIn(".dsr-row", self.text)
        self.assertIn(".dsr-pct", self.text)

    def test_uses_semantic_token(self) -> None:
        self.assertIn("var(--signal-", self.text)

    def test_hidden_rule_present(self) -> None:
        self.assertIn("[hidden]", self.text)


class BlockIdTests(unittest.TestCase):
    def test_block_id_is_documented_constant(self) -> None:
        # The mount block id the orchestrator wires into index.html /
        # champ_select.js. Pinned here so a rename is caught.
        self.assertEqual(BLOCK_ID, "csv-ds-relscore")


class AsciiHygieneTests(unittest.TestCase):
    _BAD = (chr(0x2013), chr(0x2014), chr(0x2018), chr(0x2019),
            chr(0x201C), chr(0x201D))

    def _scan(self, path: Path) -> list[int]:
        text = path.read_text(encoding="utf-8")
        return [i for i, c in enumerate(text) if c in self._BAD]

    def test_panel_js_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_JS), [])

    def test_panel_css_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_CSS), [])

    def test_this_test_file_is_ascii(self) -> None:
        src = Path(__file__).read_bytes()
        bad = [(i, b) for i, b in enumerate(src) if b > 0x7F]
        self.assertEqual(bad, [], f"non-ASCII in test file: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
