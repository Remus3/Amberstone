"""Regression guards for the live power-spike markers panel (competitor
lift #4, docs/COMPETITOR_LIFT_2026-05-30.md).

Backend dashboard/routes_spike_markers.py + its engine module
agents/daemon_slayer/spike_markers.py ship with their own suites
(tests/test_routes_spike_markers.py +
agents/daemon_slayer/tests/test_spike_markers_2026_05_30.py). This file
pins the two FRONTEND files this task OWNS:

  - web/js/panels/spike_markers.js exports the API contract
    (fetchSpikeMarkers, getCachedSpikeMarkers, getSpikeMarkersCacheCount,
    renderSpikeMarkers) and references the expected DOM classes.
  - web/css/panels/spike_markers.css carries the strip classes + signal
    tokens + the [hidden] rule.

The shared-file wiring (web/index.html mount id, web/css/dashboard.css
@import, web/js/panels/active_match.js render call) is done by the
orchestrator, NOT this task - so those wires are checked opportunistically
(skip-if-absent) rather than asserted, to keep this slice green pre-wire.

Grep-based smoke checks - cheap, fast, enough to catch a missing wire.
Mirrors test_cooldown_watch_panel_dom.py.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PANEL_JS = WEB / "js" / "panels" / "spike_markers.js"
PANEL_CSS = WEB / "css" / "panels" / "spike_markers.css"
INDEX_HTML = WEB / "index.html"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"
ACTIVE_MATCH_JS = WEB / "js" / "panels" / "active_match.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class PanelFilesExistTests(unittest.TestCase):
    def test_panel_js_exists(self) -> None:
        self.assertTrue(PANEL_JS.is_file())

    def test_panel_css_exists(self) -> None:
        self.assertTrue(PANEL_CSS.is_file())


class JsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_panel_exports_fetch(self) -> None:
        self.assertIn("export function fetchSpikeMarkers", self.text)

    def test_panel_exports_get_cached(self) -> None:
        self.assertIn("export function getCachedSpikeMarkers", self.text)

    def test_panel_exports_cache_count(self) -> None:
        self.assertIn("export function getSpikeMarkersCacheCount", self.text)

    def test_panel_exports_render(self) -> None:
        self.assertIn("export function renderSpikeMarkers", self.text)

    def test_fetches_spike_markers_endpoint(self) -> None:
        self.assertIn("/api/spike-markers", self.text)

    def test_references_strip_classes(self) -> None:
        self.assertIn("spm-row", self.text)
        self.assertIn("spm-cell", self.text)
        self.assertIn("spm-next", self.text)

    def test_references_marker_states(self) -> None:
        self.assertIn("crossed", self.text)
        self.assertIn("next", self.text)
        self.assertIn("future", self.text)

    def test_documents_owed_live_clock_cursor(self) -> None:
        # The live-clock cursor is OWED (live-game-only) - it must be
        # called out in the source so a future maintainer knows the v1
        # intentionally omits it.
        self.assertIn("OWED", self.text)
        self.assertIn("cursor", self.text)


class CssContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_CSS)

    def test_card_class_present(self) -> None:
        self.assertIn(".spike-markers", self.text)
        self.assertIn(".spm-row", self.text)
        self.assertIn(".spm-cell", self.text)

    def test_state_selectors_present(self) -> None:
        self.assertIn('data-spm-state="crossed"', self.text)
        self.assertIn('data-spm-state="next"', self.text)
        self.assertIn('data-spm-state="future"', self.text)

    def test_uses_signal_tokens(self) -> None:
        self.assertIn("var(--signal-good", self.text)
        self.assertIn("var(--signal-warn", self.text)

    def test_hidden_rule_present(self) -> None:
        self.assertIn("[hidden]", self.text)


class SharedWiringTests(unittest.TestCase):
    """The shared-file wires are owned by the orchestrator. Checked
    opportunistically (skip when absent) so this slice stays green before
    the orchestrator lands the mount + @import + render call."""

    def test_dashboard_css_import_when_wired(self) -> None:
        text = _read(DASHBOARD_CSS)
        if "spike_markers.css" not in text:
            self.skipTest("dashboard.css @import not wired yet (orchestrator)")
        self.assertIn("./panels/spike_markers.css", text)

    def test_index_mount_when_wired(self) -> None:
        text = _read(INDEX_HTML)
        if "am-spike-markers" not in text:
            self.skipTest("index.html mount not wired yet (orchestrator)")
        self.assertIn('id="am-spike-markers"', text)

    def test_active_match_render_when_wired(self) -> None:
        text = _read(ACTIVE_MATCH_JS)
        if "spike_markers.js" not in text:
            self.skipTest("active_match.js render not wired yet (orchestrator)")
        self.assertIn("renderSpikeMarkers", text)


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


if __name__ == "__main__":
    unittest.main()
