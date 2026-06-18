"""Regression guards for the Build Insights "Game Flow" tab - the per-minute
performance curve (core.perf_curve over the local rewind corpus).

An inline-SVG dual line (wins vs losses) of average cumulative gold / CS per
game minute, mounted as a tab on the Build Insights view next to "Game Length".
Consumes GET /api/perf-curve. Grep / file / json based smoke checks; mirrors
test_pgr_winprob_panel_dom.py + the duration_winrate wiring.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "perf_curve.js"
PANEL_CSS = WEB / "css" / "panels" / "perf_curve.css"
MOCK = WEB / "data" / "ui_mock" / "perf_curve.json"
BUILD_INSIGHTS_JS = WEB / "js" / "panels" / "build_insights.js"
INDEX_HTML = WEB / "index.html"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"

MOUNT_ID = "bi-flow-mount"


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
        self.assertIn('data-bi-tab="flow"', self.text)

    def test_pane_and_mount_present(self) -> None:
        self.assertIn('data-bi-pane="flow"', self.text)
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
        self.assertIn("renderPerfCurve", self.text)
        self.assertIn("./perf_curve.js", self.text)

    def test_dispatches_on_flow_tab(self) -> None:
        self.assertIn("'flow'", self.text)
        self.assertIn("renderPerfCurve()", self.text)


class DashboardCssImportTests(unittest.TestCase):
    def test_imports_panel_css(self) -> None:
        self.assertIn("panels/perf_curve.css", _read(DASHBOARD_CSS))

    def test_import_follows_duration_winrate(self) -> None:
        text = _read(DASHBOARD_CSS)
        dur = text.index("panels/duration_winrate.css")
        pf = text.index("panels/perf_curve.css")
        self.assertLess(dur, pf, "perf_curve import must follow duration_winrate")


class JsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_exports_render(self) -> None:
        self.assertIn("export function renderPerfCurve", self.text)

    def test_exports_test_hook(self) -> None:
        self.assertIn("export const __test", self.text)

    def test_fetches_perf_curve_endpoint(self) -> None:
        self.assertIn("/api/perf-curve", self.text)

    def test_references_mount(self) -> None:
        self.assertIn(MOUNT_ID, self.text)

    def test_builds_inline_svg_dual_line(self) -> None:
        self.assertIn("<svg", self.text)
        self.assertIn("polyline", self.text)
        self.assertIn("pf-line-win", self.text)
        self.assertIn("pf-line-loss", self.text)

    def test_metric_toggle_present(self) -> None:
        self.assertIn("data-pf-metric", self.text)

    def test_mock_short_circuit_present(self) -> None:
        self.assertIn("ui_mock", self.text)
        self.assertIn("/data/ui_mock/perf_curve.json", self.text)


class MockFixtureTests(unittest.TestCase):
    def test_fixture_is_valid_curve(self) -> None:
        data = json.loads(_read(MOCK))
        self.assertTrue(data.get("ok"))
        self.assertIn("minutes", data)
        self.assertGreaterEqual(len(data["minutes"]), 2)
        row = data["minutes"][0]
        for k in ("minute", "win_avg", "win_n", "loss_avg", "loss_n"):
            self.assertIn(k, row)


if __name__ == "__main__":
    unittest.main()
