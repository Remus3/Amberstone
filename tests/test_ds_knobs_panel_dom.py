"""Regression guards for the DS engine-knobs control panel (competitor
lift #1, docs/COMPETITOR_LIFT_2026-05-30.md "Lift 1").

Backend dashboard/routes_ds_knobs.py ships with its own HTTP-contract suite
(tests/test_routes_ds_knobs.py). This file pins the NEW frontend artifacts
this slice owns - it does NOT assert the cross-file wiring into
champ_select.js / index.html / dashboard.css (the orchestrator wires those
shared files; their drift guard lives elsewhere). Here we only guard:

  - web/js/panels/ds_knobs.js exists, is ASCII-clean, exports the API
    contract (fetchDsKnobs, getCachedDsKnobs, getDsKnobsCacheCount,
    renderDsKnobs) + references the 3 knob input ids + the rows container.
  - web/css/panels/ds_knobs.css exists, is ASCII-clean, declares the card
    class + control-strip + rows classes + uses a semantic token.

Grep-based smoke checks - cheap, fast, enough to catch a missing export or
a renamed id. Mirrors test_cooldown_watch_panel_dom.py.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "ds_knobs.js"
PANEL_CSS = WEB / "css" / "panels" / "ds_knobs.css"

# The 3 v1 knob input ids (armor / MR / gold cap) the panel renders + reads.
KNOB_IDS = ("dsk-armor", "dsk-mr", "dsk-budget")


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

    def test_exports_fetch(self) -> None:
        self.assertIn("export function fetchDsKnobs", self.text)

    def test_exports_get_cached(self) -> None:
        self.assertIn("export function getCachedDsKnobs", self.text)

    def test_exports_cache_count(self) -> None:
        self.assertIn("export function getDsKnobsCacheCount", self.text)

    def test_exports_render(self) -> None:
        self.assertIn("export function renderDsKnobs", self.text)

    def test_fetches_ds_knobs_endpoint(self) -> None:
        self.assertIn("/api/ds-knobs", self.text)

    def test_references_three_knob_ids(self) -> None:
        for kid in KNOB_IDS:
            self.assertIn(kid, self.text, f"knob id {kid} missing from panel JS")

    def test_references_rows_container(self) -> None:
        self.assertIn("dsk-rows", self.text)

    def test_reads_my_champion_from_state(self) -> None:
        # The panel resolves the locked champion from cs.my_champion.
        self.assertIn("my_champion", self.text)

    def test_debounce_constant_present(self) -> None:
        # Knob-change re-fetches must be debounced.
        self.assertIn("_DSK_DEBOUNCE_MS", self.text)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_CSS)

    def test_card_class_present(self) -> None:
        self.assertIn(".ds-knobs", self.text)

    def test_strip_class_present(self) -> None:
        self.assertIn(".dsk-strip", self.text)
        self.assertIn(".dsk-knob", self.text)

    def test_rows_class_present(self) -> None:
        self.assertIn(".dsk-row", self.text)
        self.assertIn(".dsk-delta", self.text)

    def test_uses_semantic_token(self) -> None:
        self.assertIn("var(--signal-", self.text)

    def test_hidden_rule_present(self) -> None:
        self.assertIn("[hidden]", self.text)


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
