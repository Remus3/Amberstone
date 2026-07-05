"""Regression guards for the Build Insights "Snowball" tab (ORUN2 slice 2) -
the snowball-elasticity panel: win % bucketed by TEAM gold lead at the 10 and
20 min checkpoints, rendered as horizontal bars over the operator's OWN rewind
corpus. SR-only (no mode bar, no champion picker), a pure frontend mirror of
the shipped core.snowball_elasticity backend.

Grep / file / json based smoke checks; mirrors test_duration_winrate_panel_dom.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "snowball_elasticity.js"
PANEL_CSS = WEB / "css" / "panels" / "snowball_elasticity.css"
MOCK = WEB / "data" / "ui_mock" / "snowball_elasticity.json"

MOUNT_ID = "bi-snowball-mount"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class FilesExistTests(unittest.TestCase):
    def test_panel_js_exists(self) -> None:
        self.assertTrue(PANEL_JS.is_file(), f"missing {PANEL_JS}")

    def test_panel_css_exists(self) -> None:
        self.assertTrue(PANEL_CSS.is_file(), f"missing {PANEL_CSS}")

    def test_mock_fixture_exists(self) -> None:
        self.assertTrue(MOCK.is_file(), f"missing {MOCK}")


class PanelJsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_exports_render(self) -> None:
        self.assertIn("export function renderSnowballElasticity", self.text)

    def test_references_mount(self) -> None:
        self.assertIn(MOUNT_ID, self.text)

    def test_hits_live_endpoint(self) -> None:
        self.assertIn("/api/snowball-elasticity", self.text)

    def test_mock_short_circuit_present(self) -> None:
        self.assertIn("/data/ui_mock/snowball_elasticity.json", self.text)

    def test_reads_checkpoints_and_smoothed(self) -> None:
        self.assertIn("checkpoints", self.text)
        self.assertIn("winrate_smoothed", self.text)

    def test_bucket_labels_present(self) -> None:
        self.assertIn("Behind 2.5k+", self.text)
        self.assertIn("Ahead 2.5k+", self.text)

    def test_elasticity_labels_present(self) -> None:
        self.assertIn("snowball-prone", self.text)
        self.assertIn("comeback-prone", self.text)
        self.assertIn("'elastic'", self.text)

    def test_caption_stays_descriptive(self) -> None:
        self.assertIn("not a win probability", self.text)

    def test_degraded_resets_sig(self) -> None:
        # Without a sig reset, a refetch after a transient failure whose
        # payload matches the pre-failure sig early-returns in _paint and
        # the degraded text stays stuck on screen.
        m = re.search(r"function _degraded\([\s\S]*?\n\}", self.text)
        self.assertIsNotNone(m, "no _degraded function body found")
        self.assertIn("_sig = ''", m.group(0))

    def test_no_champion_picker_leftovers(self) -> None:
        # SR-only: prove no copy-paste of the duration_winrate champ picker
        # / mode bar survived into this panel.
        self.assertNotIn("dw-champ", self.text)
        self.assertNotIn("data-dw-mode", self.text)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_CSS)

    def test_core_classes_present(self) -> None:
        for cls_name in (".se-cp", ".se-chip", ".se-fill", ".se-track"):
            self.assertIn(cls_name, self.text)

    def test_chip_color_variants_present(self) -> None:
        self.assertIn(".se-chip.se-good", self.text)
        self.assertIn(".se-chip.se-bad", self.text)
        self.assertIn(".se-chip.se-dim", self.text)

    def test_uses_defined_surface_token(self) -> None:
        # Bare --surface-3 (defined in base.css), not the undefined
        # --bg-elevated whose bare form computes invalid -> transparent.
        self.assertIn("var(--surface-3)", self.text)

    def test_uses_fs_tokens(self) -> None:
        self.assertIn("var(--fs-", self.text)

    def test_interactive_accent_not_gold(self) -> None:
        self.assertNotIn("gold", self.text.lower())

    def test_zero_dark_hex_literals(self) -> None:
        # This file has no OQ6 ratchet pin, so its ceiling is 0: it must
        # contain zero dark/saturated hex literals (#0xxxxx/#1xxxxx/#2xxxxx).
        self.assertEqual(re.findall(r"#[0-2][0-9a-fA-F]{5}", self.text), [])

    def test_no_subfloor_font_sizes_without_exception(self) -> None:
        # Hardcoded font-size below --fs-xs (16px) needs an inline
        # operator-exception rationale (same guard as duration_winrate.css).
        floor_px = 16
        lines = self.text.splitlines()
        pat = re.compile(r"font-size:\s*(\d+)px")
        for i, line in enumerate(lines):
            m = pat.search(line)
            if not m:
                continue
            px = int(m.group(1))
            if px >= floor_px:
                continue
            window = "\n".join(lines[max(0, i - 6):i + 1])
            self.assertIn(
                "operator-exception", window,
                f"snowball_elasticity.css:{i + 1} font-size:{px}px is below "
                f"--fs-xs ({floor_px}px) with no inline operator-exception")


class MockFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(_read(MOCK))

    def test_valid_json_shape(self) -> None:
        self.assertTrue(self.data.get("ok"))
        self.assertEqual(self.data.get("mode"), "sr")

    def test_two_checkpoints(self) -> None:
        cps = self.data.get("checkpoints")
        self.assertIsInstance(cps, list)
        self.assertEqual(len(cps), 2)
        self.assertEqual({cp["key"] for cp in cps}, {"10min", "20min"})

    def test_five_buckets_with_keys(self) -> None:
        keys = {"label", "lo", "hi", "wins", "games",
                "winrate", "winrate_smoothed"}
        for cp in self.data["checkpoints"]:
            buckets = cp["buckets"]
            self.assertEqual(len(buckets), 5)
            for b in buckets:
                self.assertTrue(
                    keys.issubset(b.keys()),
                    f"bucket missing keys: {keys - set(b.keys())}")


class AsciiCleanTests(unittest.TestCase):
    def test_touched_files_are_ascii(self) -> None:
        for p in (PANEL_JS, PANEL_CSS, MOCK, Path(__file__)):
            raw = p.read_bytes()
            try:
                raw.decode("ascii")
            except UnicodeDecodeError as exc:
                self.fail(f"{p} is not 7-bit ASCII: {exc}")


if __name__ == "__main__":
    unittest.main()
