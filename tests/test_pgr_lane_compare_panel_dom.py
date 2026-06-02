"""Regression guards for the PGR S4 lane / role comparison panel
(docs/PGR_REFRAME_S2.md staging S4).

Operator vs lane opponent (same role slot) - final gold / cs / damage /
kill-participation. The /api/last-match payload carries no team_position
field and no per-participant @N timeline (only a team-aggregate diff
series), so the comparison uses FINAL-game stats and pairs by Riot
participant-slot convention (participant_id i pairs to i +/- 5 on the
enemy team). @N (gold@10 / cs@10) is deferred honestly - see the panel
js comment. Mode-aware: hides for ARAM / Arena (no lane pairing).

The panel mounts inside the existing PGR view (Build tab), so this file
pins the in-view wiring + the panel contract, NOT a view-router rule.
Mirrors test_pgr_build_wpa_panel_dom.py.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "pgr_lane_compare.js"
PANEL_CSS = WEB / "css" / "panels" / "pgr_lane_compare.css"
MOCK = WEB / "data" / "ui_mock" / "pgr_lane_compare.json"
LAST_MATCH_JS = WEB / "js" / "panels" / "last_match.js"
INDEX_HTML = WEB / "index.html"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"

MOUNT_ID = "pgr-lane-compare-mount"


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

    def test_mount_inside_last_match_view(self) -> None:
        sec = self.text.index('id="view-last-match"')
        mount = self.text.index(f'id="{MOUNT_ID}"')
        self.assertLess(sec, mount, "mount before the last-match section")


class LastMatchWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(LAST_MATCH_JS)

    def test_imports_panel(self) -> None:
        self.assertIn("renderPgrLaneCompare", self.text)
        self.assertIn("./pgr_lane_compare.js", self.text)

    def test_dispatches_panel_in_render(self) -> None:
        self.assertIn("renderPgrLaneCompare(", self.text)


class DashboardCssImportTests(unittest.TestCase):
    def test_imports_panel_css(self) -> None:
        self.assertIn("panels/pgr_lane_compare.css", _read(DASHBOARD_CSS))

    def test_import_is_in_pgr_cluster(self) -> None:
        # Must sit in the PGR cluster after pgr_winprob.css.
        text = _read(DASHBOARD_CSS)
        wp = text.index("panels/pgr_winprob.css")
        lc = text.index("panels/pgr_lane_compare.css")
        self.assertLess(wp, lc, "lane_compare import must follow winprob")


class JsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_exports_render(self) -> None:
        self.assertIn("export function renderPgrLaneCompare", self.text)

    def test_exports_test_hook(self) -> None:
        self.assertIn("export const __test", self.text)

    def test_references_mount(self) -> None:
        self.assertIn(MOUNT_ID, self.text)

    def test_pairs_by_participant_slot(self) -> None:
        # Lane opponent paired by participant-id slot (i +/- 5).
        self.assertIn("participant_id", self.text)

    def test_compares_core_metrics(self) -> None:
        # gold / cs / damage / kill-participation.
        self.assertIn("gold", self.text)
        self.assertIn("cs", self.text)
        self.assertIn("damage", self.text.lower())

    def test_mode_aware_hide(self) -> None:
        # Fail-soft hide for ARAM / Arena (no lane opponent).
        self.assertIn("mode", self.text.lower())

    def test_n_deferred_comment(self) -> None:
        # The @N-frame deferral must be documented honestly in a comment.
        self.assertIn("@N", self.text)

    def test_mock_short_circuit_present(self) -> None:
        self.assertIn("dataset.uiMock", self.text)
        self.assertIn("/data/ui_mock/pgr_lane_compare.json", self.text)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_CSS)

    def test_hidden_mount_rule(self) -> None:
        self.assertIn(f"#{MOUNT_ID}[hidden]", self.text)

    def test_card_class_present(self) -> None:
        self.assertIn(".plc-card", self.text)

    def test_lead_classes_present(self) -> None:
        # The "ahead / behind" tint classes.
        self.assertIn(".plc-ahead", self.text)
        self.assertIn(".plc-behind", self.text)

    def test_uses_signal_token(self) -> None:
        self.assertIn("var(--signal-", self.text)

    def test_uses_fs_token(self) -> None:
        self.assertIn("var(--fs-", self.text)


class MockFixtureTests(unittest.TestCase):
    def test_valid_json(self) -> None:
        data = json.loads(_read(MOCK))
        self.assertTrue(data.get("found"))
        m = data.get("match")
        self.assertIsInstance(m, dict)

    def test_roster_pairing_resolvable(self) -> None:
        data = json.loads(_read(MOCK))
        en = data["match"]["enriched"]
        roster = en.get("roster")
        self.assertIsInstance(roster, list)
        self.assertEqual(len(roster), 10, "SR fixture needs 10 participants")
        me = [p for p in roster if p.get("is_me")]
        self.assertEqual(len(me), 1, "exactly one is_me participant")

    def test_mode_is_sr(self) -> None:
        data = json.loads(_read(MOCK))
        self.assertEqual(data["match"].get("mode"), "SR")


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
