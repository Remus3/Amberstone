"""T2-F3 frontend guard (docs/COMPETITOR_LIFT_2026-06-08.md lines 114-121)
- the headline time-to-kill line on web/js/panels/ds_combo.js.

The combo panel renders the per-hit timeline + a totals foot; this slice
adds an ADDITIVE TTK headline rendered alongside the totals from the new
``payload.ttk`` block the route returns. Grep-based smoke checks (cheap,
fast, mirrors test_ds_combo_panel_dom.py): assert the render path reads
``ttk`` and emits the headline class, that the signature folds ttk in so a
TTK change repaints, and that the file stays ASCII-clean.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANEL_JS = ROOT / "web" / "js" / "panels" / "ds_combo.js"


def _read() -> str:
    return PANEL_JS.read_text(encoding="utf-8")


class TtkRenderContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read()

    def test_reads_ttk_field(self) -> None:
        # The render path must consume payload.ttk.
        self.assertIn("ttk", self.text)
        self.assertIn(".ttk", self.text)

    def test_emits_ttk_headline_class(self) -> None:
        # A dedicated class for the headline so the CSS + DOM test can pin it.
        self.assertIn("dscombo-ttk", self.text)

    def test_has_ttk_html_builder(self) -> None:
        # A helper that turns the ttk block into the headline markup.
        self.assertIn("_ttkHtml", self.text)

    def test_signature_includes_ttk(self) -> None:
        # The sig-dedup gate must fold a ttk marker so a TTK-only change
        # (same hits) still repaints; assert the signature fn references ttk.
        sig_start = self.text.index("function _signature")
        sig_end = self.text.index("function _statusBadge")
        sig_body = self.text[sig_start:sig_end]
        self.assertIn("ttk", sig_body)

    def test_lethal_and_ttk_seconds_surfaced(self) -> None:
        # The headline distinguishes a lethal one-combo from a multi-rotation
        # TTK; assert both the lethal branch and a seconds/rotation readout.
        self.assertIn("lethal", self.text)
        self.assertIn("ttk_s", self.text)
        self.assertIn("rotations_to_kill", self.text)


class AsciiHygieneTests(unittest.TestCase):
    _BAD = (chr(0x2013), chr(0x2014), chr(0x2018), chr(0x2019),
            chr(0x201C), chr(0x201D), chr(0x2026))

    def test_panel_js_is_ascii(self) -> None:
        text = _read()
        bad = [i for i, c in enumerate(text) if c in self._BAD]
        self.assertEqual(bad, [])

    def test_this_test_file_is_ascii(self) -> None:
        src = Path(__file__).read_bytes()
        bad = [(i, b) for i, b in enumerate(src) if b > 0x7F]
        self.assertEqual(bad, [], f"non-ASCII: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
