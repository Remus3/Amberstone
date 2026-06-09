"""CS3 (2026-06-08): DS analysis panel relocation regression guard.

Four DS analysis panels - combo timeline (csv-sugg-ds-combo), DPS scaling
(csv-sugg-ds-sweep), the 1v1 fight model (csv-sugg-ds-matchup), and relative
item power (csv-ds-relscore) - were moved OFF the champ-select view and onto
the Active Match view (#view-active-match), where they read the LIVE champion
the operator is playing instead of the locked champ-select pick. This is a
RELOCATION, not a teardown: every route / fetch / render fn is unchanged; only
the mount div + the render INVOCATION moved.

This file pins that relocation so a later edit can't silently drag a panel
back onto champ-select (where the operator explicitly did not want it) or drop
one entirely:

  - the 4 mount ids are GONE from the #view-champ-select region of index.html
    and PRESENT in the #view-active-match region.
  - the 3 panels that STAY on champ-select (ds-profile, ds-knobs, ds-statcheck)
    plus the CS1 cc-pairing card are still mounted in #view-champ-select.
  - the render invocations moved from champ_select.js to active_match.js.

Grep + region-slice smoke checks - cheap, fast. Mirrors the sibling
test_ds_*_panel_dom.py style.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX_HTML = WEB / "index.html"
CHAMP_SELECT_JS = WEB / "js" / "panels" / "champ_select.js"
ACTIVE_MATCH_JS = WEB / "js" / "panels" / "active_match.js"

# The four panels the operator moved off champ-select.
MOVED_MOUNT_IDS = (
    'id="csv-sugg-ds-combo"',
    'id="csv-sugg-ds-sweep"',
    'id="csv-sugg-ds-matchup"',
    'id="csv-ds-relscore"',
)

# Panels that STAY on champ-select (must NOT be dragged along).
STAY_MOUNT_IDS = (
    'id="csv-sugg-ds-profile"',
    'id="csv-ds-knobs"',
    'id="csv-ds-statcheck"',
    'id="csv-sugg-cc-pairing"',
)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _region(html: str, start_id: str, end_id: str) -> str:
    """Slice the html between the section that carries start_id and the next
    section that carries end_id. Both markers are id="..." attributes."""
    start = html.index(start_id)
    end = html.index(end_id)
    assert start < end, f"{start_id!r} not before {end_id!r}"
    return html[start:end]


class RegionSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _read(INDEX_HTML)
        # Champ-select region: from view-champ-select section to the next
        # sibling (view-session).
        cls.cs_region = _region(
            cls.html, 'id="view-champ-select"', 'id="view-session"'
        )
        # Active-match region: from view-active-match section to the input
        # bar that follows the last view-section.
        cls.am_region = _region(
            cls.html, 'id="view-active-match"', 'id="activity-strip"'
        )

    def test_moved_panels_gone_from_champ_select(self) -> None:
        for mid in MOVED_MOUNT_IDS:
            self.assertNotIn(
                mid, self.cs_region,
                f"{mid} should NOT be in the champ-select region anymore",
            )

    def test_moved_panels_present_in_active_match(self) -> None:
        for mid in MOVED_MOUNT_IDS:
            self.assertIn(
                mid, self.am_region,
                f"{mid} should be mounted in the active-match region",
            )

    def test_stay_panels_remain_on_champ_select(self) -> None:
        for mid in STAY_MOUNT_IDS:
            self.assertIn(
                mid, self.cs_region,
                f"{mid} must stay mounted in the champ-select region",
            )

    def test_stay_panels_not_duplicated_into_active_match(self) -> None:
        for mid in STAY_MOUNT_IDS:
            self.assertNotIn(
                mid, self.am_region,
                f"{mid} must NOT be duplicated into active-match",
            )


class ChampSelectInvocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cs = _read(CHAMP_SELECT_JS)

    def test_sweep_invocation_removed(self) -> None:
        self.assertNotIn("renderDsSweepForChampSelect", self.cs)

    def test_matchup_invocation_removed(self) -> None:
        self.assertNotIn("renderDsMatchupForChampSelect", self.cs)
        self.assertNotIn("setDsMatchupScheduler", self.cs)

    def test_combo_invocation_removed(self) -> None:
        # The combo host wrapper + its fetch/render imports leave champ-select.
        self.assertNotIn("_csvRenderDsCombo", self.cs)
        self.assertNotIn("renderDsCombo", self.cs)

    def test_relscore_invocation_removed(self) -> None:
        self.assertNotIn("renderDsRelscore", self.cs)

    def test_profile_invocation_stays(self) -> None:
        # ds-profile stays on champ-select - guard against an over-eager cut.
        self.assertIn("renderDsProfileForChampSelect", self.cs)

    def test_knobs_and_statcheck_stay(self) -> None:
        self.assertIn("renderDsKnobs", self.cs)
        self.assertIn("renderDsStatcheck", self.cs)

    def test_cc_pairing_stays(self) -> None:
        self.assertIn("renderCcPairing", self.cs)


class ActiveMatchInvocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.am = _read(ACTIVE_MATCH_JS)

    def test_sweep_invocation_added(self) -> None:
        self.assertIn("renderDsSweepForChampSelect", self.am)

    def test_matchup_invocation_added(self) -> None:
        self.assertIn("renderDsMatchupForChampSelect", self.am)

    def test_combo_invocation_added(self) -> None:
        self.assertIn("renderDsCombo", self.am)

    def test_relscore_invocation_added(self) -> None:
        self.assertIn("renderDsRelscore", self.am)

    def test_feeds_live_champion(self) -> None:
        # The moved panels must read the LIVE champion (p.champion), not the
        # locked champ-select pick. Assert the live-champion resolve helper
        # exists in the active-match module.
        self.assertIn("_amDsSyntheticCs", self.am)


class AsciiHygieneTests(unittest.TestCase):
    _BAD = (chr(0x2013), chr(0x2014), chr(0x2018), chr(0x2019),
            chr(0x201C), chr(0x201D), chr(0x2026))

    def _scan(self, path: Path) -> list[int]:
        text = path.read_text(encoding="utf-8")
        return [i for i, c in enumerate(text) if c in self._BAD]

    def test_index_html_is_ascii(self) -> None:
        self.assertEqual(self._scan(INDEX_HTML), [])

    def test_champ_select_js_is_ascii(self) -> None:
        self.assertEqual(self._scan(CHAMP_SELECT_JS), [])

    def test_active_match_js_is_ascii(self) -> None:
        self.assertEqual(self._scan(ACTIVE_MATCH_JS), [])

    def test_this_test_file_is_ascii(self) -> None:
        self.assertEqual(self._scan(Path(__file__)), [])


if __name__ == "__main__":
    unittest.main()
