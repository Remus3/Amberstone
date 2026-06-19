"""Regression guards for the Build Insights "OP Score" tab - the per-interval
composite OP-Score curve (core.op_score_curve over the local rewind corpus).

An inline-SVG dual line (wins vs losses) of the per-minute 0-100 composite
performance score, mounted as a tab on the Build Insights view next to "Game
Flow". Consumes GET /api/op-score-curve. Grep / file / json based smoke checks;
mirrors test_perf_curve_panel_dom.py.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "op_score.js"
PANEL_CSS = WEB / "css" / "panels" / "op_score.css"
MOCK = WEB / "data" / "ui_mock" / "op_score.json"
BUILD_INSIGHTS_JS = WEB / "js" / "panels" / "build_insights.js"
INDEX_HTML = WEB / "index.html"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"

MOUNT_ID = "bi-opscore-mount"


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
        self.assertIn('data-bi-tab="opscore"', self.text)

    def test_pane_and_mount_present(self) -> None:
        self.assertIn('data-bi-pane="opscore"', self.text)
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
        self.assertIn("renderOpScore", self.text)
        self.assertIn("./op_score.js", self.text)

    def test_dispatches_on_opscore_tab(self) -> None:
        self.assertIn("'opscore'", self.text)
        self.assertIn("renderOpScore()", self.text)


class DashboardCssImportTests(unittest.TestCase):
    def test_imports_panel_css(self) -> None:
        self.assertIn("panels/op_score.css", _read(DASHBOARD_CSS))

    def test_import_follows_perf_curve(self) -> None:
        text = _read(DASHBOARD_CSS)
        pf = text.index("panels/perf_curve.css")
        op = text.index("panels/op_score.css")
        self.assertLess(pf, op, "op_score import must follow perf_curve")


class JsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_exports_render(self) -> None:
        self.assertIn("export function renderOpScore", self.text)

    def test_exports_test_hook(self) -> None:
        self.assertIn("export const __test", self.text)

    def test_fetches_op_score_endpoint(self) -> None:
        self.assertIn("/api/op-score-curve", self.text)

    def test_references_mount(self) -> None:
        self.assertIn(MOUNT_ID, self.text)

    def test_builds_inline_svg_dual_line(self) -> None:
        self.assertIn("<svg", self.text)
        self.assertIn("polyline", self.text)
        self.assertIn("op-line-win", self.text)
        self.assertIn("op-line-loss", self.text)

    def test_empty_state_dash_fallback(self) -> None:
        # the no-curve empty state renders a bare "-" sentinel cell.
        self.assertIn('op-empty">-<', self.text)

    def test_mock_short_circuit_present(self) -> None:
        self.assertIn("ui_mock", self.text)
        self.assertIn("/data/ui_mock/op_score.json", self.text)


class MockFixtureTests(unittest.TestCase):
    def test_fixture_is_valid_curve(self) -> None:
        data = json.loads(_read(MOCK))
        self.assertTrue(data.get("ok"))
        self.assertIn("minutes", data)
        self.assertGreaterEqual(len(data["minutes"]), 2)
        row = data["minutes"][0]
        for k in ("minute", "win_avg", "win_n", "loss_avg", "loss_n"):
            self.assertIn(k, row)

    def test_fixture_scores_in_range(self) -> None:
        data = json.loads(_read(MOCK))
        for row in data["minutes"]:
            for k in ("win_avg", "loss_avg"):
                v = row[k]
                if v is not None:
                    self.assertGreaterEqual(v, 0.0)
                    self.assertLessEqual(v, 100.0)


if __name__ == "__main__":
    unittest.main()
