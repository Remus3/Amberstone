"""Regression guards for the DS-Profile champion panel.

A presentation-only champ-select card that renders the LOCKED champion's DS
"profile" as four labelled horizontal bars (Mobility / Sustain / Scaling /
Waveclear) over the new /api/ds-profile route. It mirrors the DS stat-sweep
panel (web/js/panels/ds_sweep.js + tests/test_ds_sweep_panel_dom.py) in
structure, discipline, and test shape.

The backend route + its engine ship with their own suites. This file pins the
frontend wiring that hooks the bar card into the Suggestions card of
champ-select so a future refactor that drops a wire reverts the surface to
invisible:

  - web/index.html declares #csv-sugg-ds-profile inside
    .csv-card-suggestions (a sibling of the cooldown-watch + cc-conditional
    + ds-sweep cards).
  - web/js/panels/ds_profile.js exports the API contract (fetchDsProfile,
    getCachedDsProfile, getDsProfileCacheCount, renderDsProfile,
    renderDsProfileForChampSelect, setDsProfileScheduler, _resetDsProfile)
    and is ASCII-clean.
  - web/js/panels/champ_select.js imports the panel + calls
    renderDsProfileForChampSelect + counts cache state in the section
    signature.
  - web/css/panels/ds_profile.css is @import'd into dashboard.css.

Grep-based smoke checks - cheap, fast, enough to catch a missing wire.
Mirrors test_ds_sweep_panel_dom.py.

The orchestrator owns the shared-file wiring (index.html / dashboard.css /
champ_select.js). The OwnFilesTests below pin THIS agent's own deliverables
(ds_profile.js + ds_profile.css + ds_profile.json) and ALWAYS run. The
WiringTests pin the orchestrator's shared-file edits; they skip cleanly
(rather than fail loudly) when the wiring has not landed yet so this agent's
suite is green standalone on its worktree branch and the guard turns live once
the orchestrator wires the surface.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX_HTML = WEB / "index.html"
PANEL_JS = WEB / "js" / "panels" / "ds_profile.js"
CHAMP_SELECT_JS = WEB / "js" / "panels" / "champ_select.js"
PANEL_CSS = WEB / "css" / "panels" / "ds_profile.css"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"
FIXTURE = WEB / "data" / "ui_mock" / "ds_profile.json"

_MOUNT_ID = 'id="csv-sugg-ds-profile"'
_AXIS_KEYS = (
    "mobility", "sustain", "scaling", "waveclear",
    "threatrange", "zonecontrol", "objdamage", "extendedduel",
)
_FLAG_WORDS = ("artillery", "terrain", "towers", "ramps")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class OwnFilesTests(unittest.TestCase):
    """This agent's own deliverables - always run."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.panel_js = _read(PANEL_JS)
        cls.panel_css = _read(PANEL_CSS)

    def test_panel_exports_fetch(self) -> None:
        self.assertIn("export function fetchDsProfile", self.panel_js)

    def test_panel_exports_get_cached(self) -> None:
        self.assertIn("export function getCachedDsProfile", self.panel_js)

    def test_panel_exports_cache_count(self) -> None:
        self.assertIn("export function getDsProfileCacheCount", self.panel_js)

    def test_panel_exports_render(self) -> None:
        self.assertIn("export function renderDsProfile", self.panel_js)

    def test_panel_exports_champ_select_entry(self) -> None:
        self.assertIn(
            "export function renderDsProfileForChampSelect", self.panel_js
        )

    def test_panel_exports_scheduler(self) -> None:
        self.assertIn("export function setDsProfileScheduler", self.panel_js)

    def test_panel_exports_reset(self) -> None:
        self.assertIn("export function _resetDsProfile", self.panel_js)

    def test_panel_imports_resolve_champ_names(self) -> None:
        self.assertIn("resolveChampNames", self.panel_js)
        self.assertIn("from './cc_conditional_pressure.js'", self.panel_js)

    def test_panel_hits_ds_profile_endpoint(self) -> None:
        self.assertIn("/api/ds-profile?", self.panel_js)

    def test_panel_reads_my_champion(self) -> None:
        idx = self.panel_js.index("function renderDsProfileForChampSelect")
        body = self.panel_js[idx:idx + 1500]
        self.assertIn("cs.my_champion", body)

    def test_panel_default_mount_id(self) -> None:
        self.assertIn("csv-sugg-ds-profile", self.panel_js)

    def test_css_card_class_present(self) -> None:
        self.assertIn(".ds-profile", self.panel_css)
        self.assertIn(".dsp-track", self.panel_css)
        self.assertIn(".dsp-fill", self.panel_css)

    def test_css_tier_class_present(self) -> None:
        self.assertIn(".dsp-tier-high", self.panel_css)
        self.assertIn(".dsp-tier-med", self.panel_css)
        self.assertIn(".dsp-tier-low", self.panel_css)

    def test_css_uses_signal_tokens(self) -> None:
        self.assertIn("var(--signal", self.panel_css)

    def test_css_hidden_rule_present(self) -> None:
        self.assertIn("[hidden]", self.panel_css)

    def test_fixture_is_ok_with_eight_axes(self) -> None:
        data = json.loads(_read(FIXTURE))
        self.assertTrue(data.get("ok"))
        axes = data.get("axes")
        self.assertIsInstance(axes, list)
        self.assertEqual(len(axes), 8)
        keys = [a.get("key") for a in axes]
        self.assertEqual(keys, list(_AXIS_KEYS))

    def test_css_flag_class_present(self) -> None:
        self.assertIn(".dsp-flag", self.panel_css)

    def test_panel_renders_new_axis_markers(self) -> None:
        self.assertIn("dsp-flag", self.panel_js)
        for word in _FLAG_WORDS:
            self.assertIn(word, self.panel_js)


class WiringTests(unittest.TestCase):
    """Orchestrator-owned shared-file wiring. Skips until the orchestrator
    lands the WIRING SPEC so this agent's branch is green standalone; turns
    into a live regression guard once the surface is wired."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.index = _read(INDEX_HTML)
        cls.cs = _read(CHAMP_SELECT_JS)
        cls.dashboard_css = _read(DASHBOARD_CSS)
        cls.wired = _MOUNT_ID in cls.index

    def setUp(self) -> None:
        if not self.wired:
            self.skipTest("ds-profile panel not yet wired into shared files")

    def test_mount_present(self) -> None:
        self.assertIn(_MOUNT_ID, self.index)

    def test_hidden_by_default(self) -> None:
        idx = self.index.index(_MOUNT_ID)
        self.assertIn("hidden", self.index[idx:idx + 200])

    def test_inside_suggestions_card(self) -> None:
        sugg_open = self.index.index("csv-card-suggestions")
        chip_at = self.index.index(_MOUNT_ID)
        self.assertLess(sugg_open, chip_at)

    def test_champ_select_imports_panel(self) -> None:
        self.assertIn("from './ds_profile.js'", self.cs)
        self.assertIn("renderDsProfileForChampSelect", self.cs)
        self.assertIn("getDsProfileCacheCount", self.cs)

    def test_champ_select_calls_renderer(self) -> None:
        self.assertIn("renderDsProfileForChampSelect(cs)", self.cs)

    def test_section_signature_includes_dsp_cache_count(self) -> None:
        self.assertIn("getDsProfileCacheCount", self.cs)
        self.assertIn("dsp:", self.cs)

    def test_dashboard_imports_panel_css(self) -> None:
        self.assertIn("./panels/ds_profile.css", self.dashboard_css)


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

    def test_fixture_is_ascii(self) -> None:
        self.assertEqual(self._scan(FIXTURE), [])

    def test_this_test_file_is_ascii(self) -> None:
        self.assertEqual(self._scan(Path(__file__)), [])


if __name__ == "__main__":
    unittest.main()
