"""Regression guards for the PGR S3 win-prob "phases that mattered" graph
(docs/PGR_REFRAME_S2.md staging S3).

An inline-SVG win-probability curve over game time, mounted in the AI
Analysis tab of the last-match (Post Game Review) view next to the
phases-that-mattered cards. Consumes GET /api/post-game-wpa (the
per-frame team win-prob the WPA model walks frame by frame) and plots
the top swing phases as annotated dots. The panel is NOT a new view -
it mounts inside the existing PGR view (like pgr_build_wpa) so this file
pins the in-view wiring + the panel contract, NOT a view-router rule.

Grep / file / json based smoke checks. Mirrors
test_pgr_build_wpa_panel_dom.py + test_build_insights_panel_dom.py.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "pgr_winprob.js"
PANEL_CSS = WEB / "css" / "panels" / "pgr_winprob.css"
MOCK = WEB / "data" / "ui_mock" / "pgr_winprob.json"
LAST_MATCH_JS = WEB / "js" / "panels" / "last_match.js"
INDEX_HTML = WEB / "index.html"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"

MOUNT_ID = "pgr-winprob-mount"


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

    def test_mount_present(self) -> None:
        self.assertIn(f'id="{MOUNT_ID}"', self.text)

    def test_mount_inside_ai_analysis_tab(self) -> None:
        # The graph mount must sit inside the last-match view, near the
        # phases-that-mattered list (the AI Analysis tab #lm-wpa-wrap).
        sec = self.text.index('id="view-last-match"')
        wpa = self.text.index('id="lm-wpa-wrap"')
        mount = self.text.index(f'id="{MOUNT_ID}"')
        self.assertLess(sec, mount, "mount before the last-match section")
        # Sits next to the phases list, after the section opens.
        self.assertGreater(mount, wpa - 4000, "mount near the AI Analysis tab")


class LastMatchWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(LAST_MATCH_JS)

    def test_imports_panel(self) -> None:
        self.assertIn("renderPgrWinprob", self.text)
        self.assertIn("./pgr_winprob.js", self.text)

    def test_dispatches_panel_in_set_phases(self) -> None:
        # _setPhases already derives the match id + operator team for the
        # phases fetch; the win-prob graph wires off the same trigger.
        self.assertIn("renderPgrWinprob(", self.text)


class DashboardCssImportTests(unittest.TestCase):
    def test_imports_panel_css(self) -> None:
        self.assertIn("panels/pgr_winprob.css", _read(DASHBOARD_CSS))

    def test_import_is_in_pgr_cluster(self) -> None:
        # Must sit immediately after pgr_build_wpa.css, not appended at EOF.
        text = _read(DASHBOARD_CSS)
        bw = text.index("panels/pgr_build_wpa.css")
        wp = text.index("panels/pgr_winprob.css")
        self.assertLess(bw, wp, "winprob import must follow build_wpa")
        # Nothing but whitespace / the import statement between them.
        between = text[bw:wp]
        self.assertNotIn("last_match.css", between)


class JsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_exports_render(self) -> None:
        self.assertIn("export function renderPgrWinprob", self.text)

    def test_exports_test_hook(self) -> None:
        self.assertIn("export const __test", self.text)

    def test_fetches_wpa_endpoint(self) -> None:
        self.assertIn("/api/post-game-wpa", self.text)

    def test_references_mount(self) -> None:
        self.assertIn(MOUNT_ID, self.text)

    def test_builds_inline_svg(self) -> None:
        # An inline SVG line, no external chart lib.
        self.assertIn("<svg", self.text)
        self.assertIn("polyline", self.text)

    def test_baseline_at_fifty_percent(self) -> None:
        # A 50% reference baseline must be drawn.
        self.assertIn("baseline", self.text.lower())

    def test_operator_team_mapping(self) -> None:
        # team100 prob_after must be mappable to ally/enemy via operator side.
        self.assertIn("operatorTeam", self.text)

    def test_mock_short_circuit_present(self) -> None:
        self.assertIn("dataset.uiMock", self.text)
        self.assertIn("/data/ui_mock/pgr_winprob.json", self.text)

    def test_swing_dot_annotations(self) -> None:
        self.assertIn("pwp-dot", self.text)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_CSS)

    def test_hidden_mount_rule(self) -> None:
        self.assertIn(f"#{MOUNT_ID}[hidden]", self.text)

    def test_card_class_present(self) -> None:
        self.assertIn(".pwp-card", self.text)

    def test_pos_neg_classes_present(self) -> None:
        self.assertIn(".pwp-ally", self.text)
        self.assertIn(".pwp-enemy", self.text)

    def test_uses_signal_token(self) -> None:
        self.assertIn("var(--signal-", self.text)

    def test_uses_fs_token(self) -> None:
        self.assertIn("var(--fs-", self.text)


class MockFixtureTests(unittest.TestCase):
    def test_valid_json(self) -> None:
        data = json.loads(_read(MOCK))
        self.assertTrue(data.get("ok"))
        ev = data.get("events")
        self.assertIsInstance(ev, list)
        self.assertGreaterEqual(len(ev), 5)

    def test_event_keys_present(self) -> None:
        data = json.loads(_read(MOCK))
        keys = {"game_time", "type", "wpa", "prob_before", "prob_after",
                "actor_team"}
        for ev in data["events"]:
            self.assertTrue(keys.issubset(ev.keys()),
                            f"event missing keys: {keys - set(ev.keys())}")

    def test_top_phases_present(self) -> None:
        data = json.loads(_read(MOCK))
        tp = data.get("top_phases")
        self.assertIsInstance(tp, list)
        self.assertGreaterEqual(len(tp), 1)


class AsciiHygieneTests(unittest.TestCase):
    def _scan(self, path: Path) -> list:
        return [(i, b) for i, b in enumerate(path.read_bytes()) if b > 0x7F]

    def test_panel_js_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_JS), [])

    def test_panel_css_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_CSS), [])

    def test_mock_fixture_is_ascii(self) -> None:
        self.assertEqual(self._scan(MOCK), [])

    def test_this_test_file_is_ascii(self) -> None:
        self.assertEqual(self._scan(Path(__file__)), [])


if __name__ == "__main__":
    unittest.main()
