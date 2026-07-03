"""
tests/test_panel_visibility_permode.py

QA slice B (2026-07-03): per-mode panel-visibility settings.

Source-level contract guards for the pieces the node suite
(web/js/panels/panel_visibility.test.mjs, pure core) cannot reach:

  - every id in the JS PANELS registry exists as an id="..." in
    web/index.html (no phantom panels - applyPanelVisibility getElementById
    would silently no-op, and a settings row would toggle nothing);
  - the expanded registry actually includes the QA-named panels;
  - the tab bar (SR / ARAM / ARENA / TFT / OUT-OF-GAME) is rendered with
    sessionStorage-persisted selection;
  - the CSS gate covers non-<main> panels while still excluding the overlay
    shell, and the tab hit-target / font-token / focus-ring rules hold;
  - everything stays 7-bit ASCII (repo hard rule).

Pure-logic behavior (context mapping incl. brawl->sr, legacy-blob migration,
5-context matrix, fail-open) lives in the node suite.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANEL_JS = ROOT / "web" / "js" / "panels" / "panel_visibility.js"
PANEL_MJS = ROOT / "web" / "js" / "panels" / "panel_visibility.test.mjs"
PANEL_CSS = ROOT / "web" / "css" / "panels" / "panel_visibility.css"
INDEX_HTML = ROOT / "web" / "index.html"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _registry_ids(js: str) -> list[str]:
    """Parse the panel ids out of the PANELS registry block."""
    m = re.search(r"const PANELS = Object\.freeze\(\[(.*?)\]\);", js, re.S)
    assert m, "PANELS registry block not found"
    return re.findall(r'id:\s*"([^"]+)"', m.group(1))


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(PANEL_JS)
        cls.html = _read(INDEX_HTML)
        cls.ids = _registry_ids(cls.js)

    def test_every_registry_id_exists_in_index_html(self):
        missing = [i for i in self.ids if f'id="{i}"' not in self.html]
        self.assertEqual(missing, [], f"phantom panel ids (not in index.html): {missing}")

    def test_registry_expanded_beyond_legacy_five(self):
        self.assertGreaterEqual(len(self.ids), 17, self.ids)
        for pid in [
            "minimap", "right-now", "next", "item-build", "adaptation",
            "coach-decisions", "rn-lead", "rn-choices", "rn-callouts",
            "personal-context-section", "session-trend", "lm-tc-table",
            "hpgr-tc-table", "am-spike-curve", "am-spike-markers",
            "am-ward-heat", "aram-balance-panel",
        ]:
            self.assertIn(pid, self.ids, pid)

    def test_registry_ids_unique(self):
        self.assertEqual(len(set(self.ids)), len(self.ids))


class ContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(PANEL_JS)

    def test_five_contexts_declared(self):
        for ctx in ("in-game-sr", "in-game-aram", "in-game-arena",
                    "in-game-tft", "out-game"):
            self.assertIn(f'"{ctx}"', self.js, ctx)

    def test_brawl_inherits_sr_with_s214_citation(self):
        # The retired-mode routing must be commented WHY, citing s214.
        self.assertIn("s214", self.js)
        self.assertRegex(self.js, r'brawl:\s*"in-game-sr"')

    def test_legacy_migration_present(self):
        self.assertIn('LEGACY_IN_GAME_KEY = "in-game"', self.js)

    def test_storage_key_unchanged(self):
        self.assertIn('STORAGE_KEY = "rc-panel-visibility"', self.js)


class TabUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(PANEL_JS)
        cls.css = _read(PANEL_CSS)

    def test_tab_labels(self):
        for label in ("SR", "ARAM", "ARENA", "TFT", "OUT-OF-GAME"):
            self.assertIn(f'label: "{label}"', self.js, label)

    def test_selected_tab_persisted_in_session_storage(self):
        self.assertIn('TAB_STORAGE_KEY = "rc-pv-tab"', self.js)
        self.assertIn("sessionStorage", self.js)

    def test_tablist_semantics(self):
        self.assertIn('"tablist"', self.js)
        self.assertIn("aria-selected", self.js)

    def test_tab_hit_target_and_tokens(self):
        # Hit floor on the tab buttons (tokens.css:119 --hit-min 42px).
        self.assertRegex(self.css, r"\.pv-tab\s*\{[^}]*min-height:\s*var\(--hit-min", )
        # focus-visible ring on the semantic token.
        self.assertRegex(self.css, r"\.pv-tab:focus-visible\s*\{[^}]*var\(--focus-ring\)")

    def test_font_sizes_on_tokens_only(self):
        # Every font-size in the panel CSS must be a --fs-* token (16px floor
        # is guaranteed by tokens.css --fs-xs; no raw px sizes allowed here).
        raw = re.findall(r"font-size:\s*([^;]+);", self.css)
        offenders = [v for v in raw if "var(--fs-" not in v]
        self.assertEqual(offenders, [], offenders)


class GateCssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _read(PANEL_CSS)
        cls.js = _read(PANEL_JS)

    def test_gate_covers_non_main_panels(self):
        # The expanded registry includes blocks outside <main> (coach-decisions
        # banner, last-match team context, active-match spike/ward blocks), so
        # the gate must NOT be scoped to `main >`.
        self.assertNotIn('main > .panel[data-pv-hidden="1"]', self.css)
        self.assertIn('body:not([data-shell="overlay"]) [data-pv-hidden="1"]', self.css)

    def test_overlay_shell_still_excluded_in_js(self):
        self.assertIn('dataset.shell === "overlay"', self.js)

    def test_live_reapply_contract_strings_survive(self):
        # tests/test_rc_skel_removed.py depends on these exact strings.
        self.assertIn("function initPanelVisibility()", self.js)
        self.assertIn("buildPanelVisibilitySettings();", self.js)
        self.assertIn("applyPanelVisibility();", self.js)


class AsciiTests(unittest.TestCase):
    def test_all_slice_files_ascii(self):
        for p in (PANEL_JS, PANEL_MJS, PANEL_CSS):
            text = _read(p)
            bad = [
                (i + 1, ch)
                for i, line in enumerate(text.splitlines())
                for ch in line
                if ord(ch) > 126
            ]
            self.assertEqual(bad, [], f"non-ASCII in {p.name}: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
