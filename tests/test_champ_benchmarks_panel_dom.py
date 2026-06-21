"""Regression guards for the Build Insights "Benchmarks" tab - the per-champion
stat distribution table (core.benchmarks over the local corpus).

A Aggregator-B-style per-champion stat breakdown (p25/p50/p75 for a fixed early-game
column set), mounted as a tab on the Build Insights view next to "OP Score".
Consumes GET /api/champ-benchmarks. Grep / file / json based smoke checks (the
sanctioned panel-DOM proof path for these ESM panels - mirrors
test_perf_curve_panel_dom.py + the duration_winrate wiring; there is no
Playwright harness for these panels).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "champ_benchmarks.js"
PANEL_CSS = WEB / "css" / "panels" / "champ_benchmarks.css"
MOCK = WEB / "data" / "ui_mock" / "champ_benchmarks.json"
BUILD_INSIGHTS_JS = WEB / "js" / "panels" / "build_insights.js"
INDEX_HTML = WEB / "index.html"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"

MOUNT_ID = "bi-bench-mount"

# Forbidden non-ASCII (project hard rule). chr() so this file stays ASCII-clean.
_BAD = {
    chr(0x2013): "EN DASH",
    chr(0x2014): "EM DASH",
    chr(0x2018): "LEFT SINGLE QUOTE",
    chr(0x2019): "RIGHT SINGLE QUOTE",
    chr(0x201C): "LEFT DOUBLE QUOTE",
    chr(0x201D): "RIGHT DOUBLE QUOTE",
}


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class FilesExistTests(unittest.TestCase):
    def test_panel_js_exists(self) -> None:
        self.assertTrue(PANEL_JS.is_file(), f"missing {PANEL_JS}")

    def test_panel_css_exists(self) -> None:
        self.assertTrue(PANEL_CSS.is_file(), f"missing {PANEL_CSS}")

    def test_mock_fixture_exists(self) -> None:
        self.assertTrue(MOCK.is_file(), f"missing {MOCK}")


class IndexHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_tab_button_present(self) -> None:
        self.assertIn('data-bi-tab="bench"', self.text)

    def test_tab_label_present(self) -> None:
        self.assertIn(">Benchmarks<", self.text)

    def test_pane_and_mount_present(self) -> None:
        self.assertIn('data-bi-pane="bench"', self.text)
        self.assertIn(f'id="{MOUNT_ID}"', self.text)

    def test_mount_inside_build_insights(self) -> None:
        tabs = self.text.index('id="bi-tabs"')
        mount = self.text.index(f'id="{MOUNT_ID}"')
        self.assertLess(tabs, mount, "mount must sit inside the Build Insights section")


class BuildInsightsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(BUILD_INSIGHTS_JS)

    def test_imports_panel(self) -> None:
        self.assertIn("renderChampBenchmarks", self.text)
        self.assertIn("./champ_benchmarks.js", self.text)

    def test_dispatches_on_bench_tab(self) -> None:
        self.assertIn("'bench'", self.text)
        self.assertIn("renderChampBenchmarks()", self.text)


class DashboardCssImportTests(unittest.TestCase):
    def test_imports_panel_css(self) -> None:
        self.assertIn("panels/champ_benchmarks.css", _read(DASHBOARD_CSS))


class JsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_exports_render(self) -> None:
        self.assertIn("export function renderChampBenchmarks", self.text)

    def test_fetches_champ_benchmarks_endpoint(self) -> None:
        self.assertIn("/api/champ-benchmarks", self.text)

    def test_references_mount(self) -> None:
        self.assertIn(MOUNT_ID, self.text)

    def test_builds_a_table(self) -> None:
        self.assertIn("<table", self.text)
        self.assertIn("<thead", self.text)
        self.assertIn("<tbody", self.text)

    def test_headline_p50_with_range_and_title(self) -> None:
        # The median is the headline; the p25-p75 spread shows as a sub + title.
        self.assertIn("cb-p50", self.text)
        self.assertIn("cb-range", self.text)
        self.assertIn("title=", self.text)

    def test_games_trust_column_present(self) -> None:
        self.assertIn("cb-games", self.text)

    def test_champ_icon_onerror_fallback(self) -> None:
        # local DDragon -> CDN -> hide chain (copied from build_insights.js).
        self.assertIn("onerror", self.text)
        self.assertIn("ddragon.leagueoflegends.com", self.text)

    def test_descriptive_personal_corpus_caption(self) -> None:
        low = self.text.lower()
        self.assertIn("personal-corpus", low)
        self.assertIn("not a meta", low)

    def test_empty_state_matches_duration(self) -> None:
        self.assertIn("Not enough", self.text)
        self.assertIn("games tracked yet", self.text)

    def test_mock_short_circuit_present(self) -> None:
        self.assertIn("ui_mock", self.text)
        self.assertIn("/data/ui_mock/champ_benchmarks.json", self.text)

    def test_mode_switcher_present(self) -> None:
        self.assertIn("data-cb-mode", self.text)


class MockFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(_read(MOCK))

    def test_fixture_matches_contract(self) -> None:
        d = self.data
        self.assertTrue(d.get("ok"))
        self.assertEqual(d.get("mode"), "aram")
        self.assertEqual(d.get("min_games"), 3)
        self.assertIsInstance(d.get("metrics"), list)
        self.assertEqual(len(d["metrics"]), 5)

    def test_fixture_has_full_table(self) -> None:
        rows = self.data["rows"]
        self.assertGreaterEqual(len(rows), 4)
        self.assertEqual(self.data["n"], len(rows))

    def test_each_row_has_champion_games_stats(self) -> None:
        for r in self.data["rows"]:
            self.assertIn("champion", r)
            self.assertIn("games", r)
            self.assertIn("stats", r)
            for k in r["stats"]:
                self.assertIn(k, self.data["metrics"])

    def test_stat_cell_has_p50(self) -> None:
        first = self.data["rows"][0]
        any_stat = next(iter(first["stats"].values()))
        self.assertIn("p50", any_stat)


class AsciiHygieneTests(unittest.TestCase):
    def _scan(self, path: Path) -> list[str]:
        text = path.read_text(encoding="utf-8")
        return [name for ch, name in _BAD.items() if ch in text]

    def test_panel_js_ascii_clean(self) -> None:
        self.assertEqual([], self._scan(PANEL_JS))

    def test_panel_css_ascii_clean(self) -> None:
        self.assertEqual([], self._scan(PANEL_CSS))

    def test_mock_ascii_clean(self) -> None:
        self.assertEqual([], self._scan(MOCK))


if __name__ == "__main__":
    unittest.main()
