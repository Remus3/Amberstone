"""Regression guards for the Build Insights "Game Length" tab R71 slice -
the champion filter (F1) + the computed early/late tendency chip (F2) on the
duration_winrate panel.

F1: a champion picker (text input + datalist hydrated from CHAMPS.byId, with
an ALL clear affordance) next to the mode bar re-fetches the curve with
&champion=<riot int id>; the per-mode cache/inflight/sig keys extend to
mode|champ. F2: a pure-client n-weighted winrate delta (second half of
non-null buckets minus first half, weights = games) renders a descriptive
late-leaning / early-leaning / flat chip - never a win-probability claim.

Grep / file based smoke checks; mirrors test_perf_curve_panel_dom.py.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "duration_winrate.js"
PANEL_CSS = WEB / "css" / "panels" / "duration_winrate.css"

MOUNT_ID = "bi-duration-mount"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class FilesExistTests(unittest.TestCase):
    def test_panel_js_exists(self) -> None:
        self.assertTrue(PANEL_JS.is_file(), f"missing {PANEL_JS}")

    def test_panel_css_exists(self) -> None:
        self.assertTrue(PANEL_CSS.is_file(), f"missing {PANEL_CSS}")


class ChampionFilterJsTests(unittest.TestCase):
    """F1 - champion filter wiring in the panel JS."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_still_exports_render(self) -> None:
        self.assertIn("export function renderDurationWinrate", self.text)

    def test_references_mount(self) -> None:
        self.assertIn(MOUNT_ID, self.text)

    def test_builds_champion_query_param(self) -> None:
        self.assertIn("&champion=", self.text)

    def test_imports_champs_from_items_index(self) -> None:
        self.assertIn("CHAMPS", self.text)
        self.assertIn("../lib/items_index.js", self.text)

    def test_datalist_picker_present(self) -> None:
        self.assertIn("<datalist", self.text)
        self.assertIn("dw-champ-input", self.text)
        self.assertIn("CHAMPS.byId", self.text)

    def test_champs_ready_listener_rebuilds(self) -> None:
        # Late CHAMPS hydration must rebuild the datalist via a re-render.
        self.assertIn("rc:champs-ready", self.text)

    def test_clear_affordance_present(self) -> None:
        self.assertIn("data-dw-champ-clear", self.text)

    def test_cache_key_extends_mode_with_champion(self) -> None:
        # `${mode}|${champ || 'all'}` - the shared _CACHE/_TS/_INFLIGHT key.
        self.assertIn("${mode}|${champ || 'all'}", self.text)

    def test_sig_dedup_keyed_on_champion(self) -> None:
        self.assertIn("_key(_mode, _champId)", self.text)

    def test_empty_state_names_filtered_champion(self) -> None:
        self.assertIn("_champName", self.text)

    def test_mode_bar_preserved(self) -> None:
        self.assertIn("data-dw-mode", self.text)
        self.assertIn("dw-mode-btn", self.text)


class TendencyChipJsTests(unittest.TestCase):
    """F2 - computed early/late tendency chip."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_threshold_constant_is_five(self) -> None:
        self.assertIn("_CHIP_DELTA = 5", self.text)

    def test_tendency_function_present(self) -> None:
        self.assertIn("function _tendency(", self.text)

    def test_chip_labels_present(self) -> None:
        self.assertIn("late-leaning", self.text)
        self.assertIn("early-leaning", self.text)
        self.assertIn("'flat'", self.text)

    def test_chip_class_marker(self) -> None:
        self.assertIn("dw-chip", self.text)

    def test_weighting_uses_games(self) -> None:
        m = re.search(r"function _tendency\([\s\S]*?\n\}", self.text)
        self.assertIsNotNone(m, "no _tendency function body found")
        self.assertIn("games", m.group(0), "tendency must weight by games")

    def test_min_half_guard(self) -> None:
        # Fewer than 2 non-null buckets in either half -> no chip.
        m = re.search(r"function _tendency\([\s\S]*?\n\}", self.text)
        self.assertIsNotNone(m)
        self.assertIn("< 2", m.group(0))

    def test_caption_references_chip_and_stays_descriptive(self) -> None:
        self.assertIn("tendency chip", self.text)
        self.assertIn("not a win probability", self.text)

    def test_degraded_resets_sig(self) -> None:
        # Audit fix: without a sig reset, a refetch after a transient failure
        # whose payload matches the pre-failure sig early-returns in _paint
        # and the degraded text stays stuck on screen.
        m = re.search(r"function _degraded\([\s\S]*?\n\}", self.text)
        self.assertIsNotNone(m, "no _degraded function body found")
        self.assertIn("_sig = ''", m.group(0))


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_CSS)

    def test_picker_styles_present(self) -> None:
        self.assertIn(".dw-champ-input", self.text)
        self.assertIn(".dw-champ-clear", self.text)

    def test_controls_meet_hit_target(self) -> None:
        # Every new interactive control >= --hit-min (42px) tall.
        for cls_name in ("dw-champ-input", "dw-champ-clear"):
            block = re.search(
                r"\." + cls_name + r"\s*\{[^}]*\}", self.text)
            self.assertIsNotNone(block, f"no rule block for .{cls_name}")
            self.assertIn("var(--hit-min", block.group(0),
                          f".{cls_name} must pin min-height to --hit-min")

    def test_chip_styles_present(self) -> None:
        self.assertIn(".dw-chip", self.text)
        self.assertIn(".dw-chip.dw-good", self.text)
        self.assertIn(".dw-chip.dw-bad", self.text)
        self.assertIn(".dw-chip.dw-dim", self.text)

    def test_new_controls_use_defined_surface_token(self) -> None:
        # Audit MUST-FIX: --bg-elevated is never defined under web/, so its
        # BARE form (no fallback) computes invalid -> transparent background.
        # New controls must sit on the defined --surface-3 (base.css). The
        # fallback-carrying var(--bg-elevated, #hex) uses on pre-existing
        # rules render via fallback and stay RESKIN-CANDIDATE (operator-gated
        # FUTURE in docs/DARK_VALUES_AUDIT_2026-07-01.md) - only the bare,
        # invalid-computing form is banned here.
        self.assertIn("var(--surface-3)", self.text)
        self.assertNotIn("var(--bg-elevated)", self.text)

    def test_focus_visible_uses_shared_ring(self) -> None:
        # Sibling convention (build_insights.css): keyboard focus renders the
        # shared --focus-ring token on both new interactive controls.
        self.assertIn(".dw-champ-input:focus-visible", self.text)
        self.assertIn(".dw-champ-clear:focus-visible", self.text)
        self.assertGreaterEqual(self.text.count("var(--focus-ring)"), 2)

    def test_interactive_accent_is_cyan_not_gold(self) -> None:
        self.assertIn("#6cf", self.text)
        self.assertNotIn("gold", self.text.lower())

    def test_no_subfloor_font_sizes_without_exception(self) -> None:
        # Same audit guard as perf_curve.css: hardcoded font-size below
        # --fs-xs (16px) needs an inline operator-exception rationale.
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
                f"duration_winrate.css:{i + 1} font-size:{px}px is below "
                f"--fs-xs ({floor_px}px) with no inline operator-exception")

    def test_dark_literal_ratchet_pin_holds(self) -> None:
        # Self-check against the OQ6 ratchet pin (4) so this slice never
        # trips test_dark_values_ratchet_oq6 - new rules must use bare
        # token vars, not dark hex fallbacks.
        dark = re.compile(r"#[0-2][0-9a-fA-F]{5}\b|#[0-2][0-9a-fA-F]{2}\b")
        self.assertLessEqual(len(dark.findall(self.text)), 4)


class AsciiCleanTests(unittest.TestCase):
    def test_touched_files_are_ascii(self) -> None:
        for p in (PANEL_JS, PANEL_CSS, Path(__file__)):
            raw = p.read_bytes()
            try:
                raw.decode("ascii")
            except UnicodeDecodeError as exc:
                self.fail(f"{p} is not 7-bit ASCII: {exc}")


if __name__ == "__main__":
    unittest.main()
