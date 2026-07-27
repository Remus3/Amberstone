"""Regression guards for the DS stat-sweep panel (competitor lift #3,
docs/COMPETITOR_LIFT_2026-05-30.md).

Backend dashboard/routes_ds_sweep.py + its engine module
agents/daemon_slayer/dps_sweep.py ship with their own suites
(tests/test_routes_ds_sweep.py + tests/test_ds_sweep_2026_05_30.py). This
file pins the frontend wiring that hooks the sparkline card into the
Active Match view so a future refactor that drops a wire reverts the surface
to invisible:

  - CS3 (2026-06-08): #csv-sugg-ds-sweep was MOVED from the champ-select
    Suggestions card to the Active Match BUILD pane (#view-active-match) so it
    reads the LIVE champion mid-game, not the locked champ-select pick.
  - web/index.html declares #csv-sugg-ds-sweep inside the active-match BUILD
    pane (a sibling of the spike-curve + spike-markers + the other relocated
    DS panels).
  - web/js/panels/ds_sweep.js exports the API contract (fetchDsSweep,
    getCachedDsSweep, getDsSweepCacheCount, renderDsSweep,
    renderDsSweepForChampSelect) and is ASCII-clean.
  - web/js/panels/active_match.js imports the panel + calls
    renderDsSweepForChampSelect against the live-champion synthetic cs.
  - web/css/panels/ds_sweep.css is @import'd into dashboard.css.

Grep-based smoke checks - cheap, fast, enough to catch a missing wire.
Mirrors test_cooldown_watch_panel_dom.py.

The orchestrator owns the shared-file wiring (index.html / dashboard.css /
champ_select.js). The OwnFilesTests below pin THIS agent's own deliverables
(ds_sweep.js + ds_sweep.css) and ALWAYS run. The WiringTests pin the
orchestrator's shared-file edits; they skip cleanly (rather than fail loudly)
when the wiring has not landed yet so this agent's suite is green standalone
on its worktree branch and the guard turns live once the orchestrator wires
the surface.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX_HTML = WEB / "index.html"
PANEL_JS = WEB / "js" / "panels" / "ds_sweep.js"
CHAMP_SELECT_JS = WEB / "js" / "panels" / "champ_select.js"
ACTIVE_MATCH_JS = WEB / "js" / "panels" / "active_match.js"
PANEL_CSS = WEB / "css" / "panels" / "ds_sweep.css"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"

_MOUNT_ID = 'id="csv-sugg-ds-sweep"'


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class OwnFilesTests(unittest.TestCase):
    """This agent's own deliverables - always run."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.panel_js = _read(PANEL_JS)
        cls.panel_css = _read(PANEL_CSS)

    def test_panel_exports_fetch(self) -> None:
        self.assertIn("export function fetchDsSweep", self.panel_js)

    def test_panel_exports_get_cached(self) -> None:
        self.assertIn("export function getCachedDsSweep", self.panel_js)

    def test_panel_exports_cache_count(self) -> None:
        self.assertIn("export function getDsSweepCacheCount", self.panel_js)

    def test_panel_exports_render(self) -> None:
        self.assertIn("export function renderDsSweep", self.panel_js)

    def test_panel_exports_champ_select_entry(self) -> None:
        self.assertIn(
            "export function renderDsSweepForChampSelect", self.panel_js
        )

    def test_panel_imports_resolve_champ_names(self) -> None:
        self.assertIn("resolveChampNames", self.panel_js)
        self.assertIn("from './cc_conditional_pressure.js'", self.panel_js)

    def test_panel_hits_ds_sweep_endpoint(self) -> None:
        self.assertIn("/api/ds-sweep?", self.panel_js)

    def test_panel_reads_my_champion(self) -> None:
        idx = self.panel_js.index("function renderDsSweepForChampSelect")
        body = self.panel_js[idx:idx + 1500]
        self.assertIn("cs.my_champion", body)

    def test_panel_default_mount_id(self) -> None:
        self.assertIn("csv-sugg-ds-sweep", self.panel_js)

    def test_css_card_class_present(self) -> None:
        self.assertIn(".ds-sweep", self.panel_css)
        self.assertIn(".dsw-line", self.panel_css)
        self.assertIn(".dsw-foot", self.panel_css)

    def test_css_uses_signal_tokens(self) -> None:
        self.assertIn("var(--signal-info", self.panel_css)

    def test_css_hidden_rule_present(self) -> None:
        self.assertIn("[hidden]", self.panel_css)


class WiringTests(unittest.TestCase):
    """Shared-file wiring guard. CS3 (2026-06-08) moved this surface from
    champ-select to the Active Match view; the assertions now pin the
    active-match home so a refactor that drops a wire is caught.

    MEASURED 2026-07-26 (skip audit): the guard the class carried defeated
    exactly that. `setUpClass` recorded `wired = _MOUNT_ID in index` and
    `setUp` skipped the class when it was false, while `test_mount_present`
    asserted the same mount id one method later - so the class could not fail,
    only assert-what-it-had-already-checked or skip. The mount is present in
    web/index.html, confirmed before removal, so the guard is gone.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.index = _read(INDEX_HTML)
        cls.cs = _read(CHAMP_SELECT_JS)
        cls.am = _read(ACTIVE_MATCH_JS)
        cls.dashboard_css = _read(DASHBOARD_CSS)

    def test_mount_present(self) -> None:
        self.assertIn(_MOUNT_ID, self.index)

    def test_hidden_by_default(self) -> None:
        idx = self.index.index(_MOUNT_ID)
        self.assertIn("hidden", self.index[idx:idx + 200])

    def test_inside_active_match_build_pane(self) -> None:
        # CS3: the mount now sits in the active-match BUILD pane, after the
        # view-active-match section opener and before the input bar.
        am_open = self.index.index('id="view-active-match"')
        mount_at = self.index.index(_MOUNT_ID)
        next_view = self.index.index('id="activity-strip"')
        self.assertLess(am_open, mount_at)
        self.assertLess(mount_at, next_view)

    def test_not_in_champ_select_anymore(self) -> None:
        # The mount must be GONE from the champ-select region.
        cs_open = self.index.index('id="view-champ-select"')
        cs_close = self.index.index('id="view-session"')
        cs_region = self.index[cs_open:cs_close]
        self.assertNotIn(_MOUNT_ID, cs_region)

    def test_active_match_imports_panel(self) -> None:
        self.assertIn("from './ds_sweep.js'", self.am)
        self.assertIn("renderDsSweepForChampSelect", self.am)

    def test_active_match_calls_renderer(self) -> None:
        self.assertIn("renderDsSweepForChampSelect(synthetic", self.am)

    def test_champ_select_no_longer_imports_sweep(self) -> None:
        # The sweep panel left champ-select entirely.
        self.assertNotIn("renderDsSweepForChampSelect", self.cs)
        self.assertNotIn("getDsSweepCacheCount", self.cs)

    def test_dashboard_imports_panel_css(self) -> None:
        self.assertIn("./panels/ds_sweep.css", self.dashboard_css)


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

    def test_this_test_file_is_ascii(self) -> None:
        self.assertEqual(self._scan(Path(__file__)), [])


if __name__ == "__main__":
    unittest.main()
