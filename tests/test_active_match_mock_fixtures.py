"""Item 188 (2026-05-25): Active Match SR/ARAM/Arena mock fixture pins.

Pages #11/12/13 v2.1 typography migration shipped item 184; live UI captures
STILL OWED per item 187 carry. This test fixes the fixture shapes + the
mock dispatcher wiring in web/js/main.js so the audit captures stand on
authored data when the operator is between games.

Pattern mirrors:
- tests/test_active_match_panel.py (if exists; was not present pre-item-188)
- tests/test_replay_events_panel_dom.py (replay fixture pins)
- tests/test_dashboard_css_panel_imports_parity.py (drift guards)

Drift guards lock:
1. The 3 mock fixture files exist with valid JSON.
2. Each fixture carries the canonical Active Match payload shape
   (coach.action/immediate/next/objective + liveclient block +
   summoner_cooldowns array + phase=InProgress + mode tag).
3. The mock dispatcher helpers (_amMockLoad / _amMockUrl / _amIsMock)
   are wired in web/js/main.js with the canonical patterns.
4. The ?mode=<sr|aram|arena> URL flag routing is grep-pinned.
5. The Arena fixture honors the 6x2 = 12-player shape per item 180
   (NOT 6x3 - that was a stale c3a1e23 premise corrected at item 183).
6. ASCII hygiene: 0 non-ASCII bytes in fixtures (matches operator no-em-dash
   policy + chr() drift guard precedent).
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_DIR = _REPO_ROOT / "web" / "data" / "ui_mock"
_MAIN_JS = _REPO_ROOT / "web" / "js" / "main.js"
_ACTIVE_MATCH_JS = _REPO_ROOT / "web" / "js" / "panels" / "active_match.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_fixture(name: str) -> dict:
    path = _FIXTURE_DIR / name
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


class FixtureFilesExistTests(unittest.TestCase):
    """Item 188: 3 NEW per-mode Active Match mock fixtures."""

    def test_sr_fixture_exists(self) -> None:
        path = _FIXTURE_DIR / "active_match_sr.json"
        self.assertTrue(path.exists(), f"missing fixture: {path}")
        self.assertGreater(path.stat().st_size, 500, "SR fixture too small")

    def test_aram_fixture_exists(self) -> None:
        path = _FIXTURE_DIR / "active_match_aram.json"
        self.assertTrue(path.exists(), f"missing fixture: {path}")
        self.assertGreater(path.stat().st_size, 500, "ARAM fixture too small")

    def test_arena_fixture_exists(self) -> None:
        path = _FIXTURE_DIR / "active_match_arena.json"
        self.assertTrue(path.exists(), f"missing fixture: {path}")
        self.assertGreater(path.stat().st_size, 500, "Arena fixture too small")


class FixtureJsonValidityTests(unittest.TestCase):
    def test_sr_loads(self) -> None:
        data = _load_fixture("active_match_sr.json")
        self.assertEqual(data["mode"], "sr")
        self.assertEqual(data["phase"], "InProgress")
        self.assertTrue(data.get("mock"), "mock flag missing")

    def test_aram_loads(self) -> None:
        data = _load_fixture("active_match_aram.json")
        self.assertEqual(data["mode"], "aram")
        self.assertEqual(data["phase"], "InProgress")
        self.assertTrue(data.get("mock"), "mock flag missing")

    def test_arena_loads(self) -> None:
        data = _load_fixture("active_match_arena.json")
        self.assertEqual(data["mode"], "arena")
        self.assertEqual(data["phase"], "InProgress")
        self.assertTrue(data.get("mock"), "mock flag missing")


class CoachPayloadShapeTests(unittest.TestCase):
    """active_match.js render consumes coach.{action,immediate,next,objective}.

    Each fixture's coach block must carry all 4 fields so the CALL pane
    renders 4 distinct lines instead of falling through to the "waiting
    for coach tick" empty state.
    """

    def _check(self, name: str) -> None:
        data = _load_fixture(name)
        coach = data.get("coach") or {}
        for field in ("action", "immediate", "next", "objective"):
            self.assertTrue(
                coach.get(field),
                f"{name}: coach.{field} empty - CALL pane will not render line",
            )
        self.assertTrue(coach.get("champion"), f"{name}: coach.champion empty")
        self.assertIsInstance(coach.get("level", 0), int)
        self.assertIsInstance(coach.get("items", []), list)
        picks = coach.get("daemon_slayer_picks") or []
        self.assertGreaterEqual(
            len(picks),
            5,
            f"{name}: need >=5 DS picks for BUILD pane strip (slice 0,5)",
        )

    def test_sr_coach_shape(self) -> None:
        self._check("active_match_sr.json")

    def test_aram_coach_shape(self) -> None:
        self._check("active_match_aram.json")

    def test_arena_coach_shape(self) -> None:
        self._check("active_match_arena.json")


class LiveClientShapeTests(unittest.TestCase):
    """liveclient block drives THREATS strip + spike_curve + draft_elo."""

    def test_sr_has_10_players(self) -> None:
        data = _load_fixture("active_match_sr.json")
        lc = data.get("liveclient") or {}
        all_players = lc.get("allPlayers") or []
        self.assertEqual(len(all_players), 10, "SR liveclient expects 10p (5v5)")

    def test_aram_has_10_players_shared_vision(self) -> None:
        data = _load_fixture("active_match_aram.json")
        lc = data.get("liveclient") or {}
        all_players = lc.get("allPlayers") or []
        self.assertEqual(len(all_players), 10, "ARAM liveclient expects 10p (5v5 shared)")

    def test_arena_has_12_players_6x2(self) -> None:
        """Item 180 + item 183 carry correction: Arena is 6x2 NOT 6x3.

        The c3a1e23 commit message implied 6x3 but `_arena_teams()` at
        `tools/gamepc_lcu_agent.py:536` distils as 6x2 per live LCU shape.
        Honor live shape; do NOT pitch a 6x3 schema lift without first
        verifying live LCU returns it.
        """
        data = _load_fixture("active_match_arena.json")
        lc = data.get("liveclient") or {}
        all_players = lc.get("allPlayers") or []
        self.assertEqual(
            len(all_players), 12, "Arena liveclient expects 6x2 = 12 players"
        )
        # 6 sub-teams confirmed: count distinct team strings.
        teams = {p.get("team") for p in all_players if p.get("team")}
        self.assertEqual(
            len(teams), 6, f"Arena expects 6 sub-teams, got {sorted(teams)}"
        )

    def test_active_player_present_each(self) -> None:
        for name in (
            "active_match_sr.json",
            "active_match_aram.json",
            "active_match_arena.json",
        ):
            data = _load_fixture(name)
            lc = data.get("liveclient") or {}
            ap = lc.get("activePlayer") or {}
            self.assertTrue(
                ap.get("summonerName"),
                f"{name}: liveclient.activePlayer.summonerName empty",
            )
            stats = ap.get("championStats") or {}
            self.assertIn("currentHealth", stats, f"{name}: HP missing")
            self.assertIn("maxHealth", stats, f"{name}: max HP missing")


class CooldownsShapeTests(unittest.TestCase):
    """summoner_cooldowns drives the right-rail CD ledger pane."""

    def _check(self, name: str) -> None:
        data = _load_fixture(name)
        cds = data.get("summoner_cooldowns") or []
        self.assertIsInstance(cds, list)
        self.assertGreater(
            len(cds), 0, f"{name}: empty summoner_cooldowns - CD ledger pane empty"
        )
        for cd in cds:
            self.assertIn("slot", cd)
            self.assertIn("name", cd)
            self.assertIn("remaining_s", cd)

    def test_sr_cooldowns(self) -> None:
        self._check("active_match_sr.json")

    def test_aram_cooldowns(self) -> None:
        self._check("active_match_aram.json")

    def test_arena_cooldowns(self) -> None:
        self._check("active_match_arena.json")


class MainJsMockDispatcherWiringTests(unittest.TestCase):
    """Pin the _amMockLoad + _amMockUrl + _amIsMock wiring in main.js.

    A future refactor that rips the wire or renames the helpers fails
    CI before the operator-facing audit-capture URL surface breaks.
    """

    def setUp(self) -> None:
        self.src = _read(_MAIN_JS)

    def test_am_is_mock_helper_present(self) -> None:
        self.assertIn("function _amIsMock()", self.src)

    def test_am_mock_url_helper_present(self) -> None:
        self.assertIn("function _amMockUrl()", self.src)

    def test_am_mock_load_helper_present(self) -> None:
        self.assertIn("function _amMockLoad()", self.src)

    def test_url_routes_sr_aram_arena(self) -> None:
        # All 3 mode branches present in _amMockUrl.
        self.assertIn('"/data/ui_mock/active_match_sr.json"', self.src)
        self.assertIn('"/data/ui_mock/active_match_aram.json"', self.src)
        self.assertIn('"/data/ui_mock/active_match_arena.json"', self.src)

    def test_render_active_match_call_site_uses_mock_branch(self) -> None:
        # The call-site at applyState wraps renderActiveMatch in the mock
        # short-circuit. _amIsMock() must appear in the same scope to gate
        # the branch.
        self.assertIn("_amIsMock()", self.src)
        self.assertIn("_amMockUrl()", self.src)
        # On view-change, the active-match view kick must call the
        # dispatcher so the first navigation renders without waiting for
        # the next state tick.
        self.assertIn('viewId === "active-match"', self.src)


class AsciiHygieneTests(unittest.TestCase):
    """No em-dashes / smart-quotes / non-ASCII in mock fixtures.

    Matches operator hard rule in CLAUDE.md + the chr() drift guard
    precedent in tests/test_smart_quote_hygiene.py.
    """

    def _check(self, path: Path) -> None:
        raw = path.read_bytes()
        non_ascii = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        self.assertEqual(
            len(non_ascii),
            0,
            f"{path.name}: {len(non_ascii)} non-ASCII bytes at offsets "
            f"{[off for off, _ in non_ascii[:5]]}",
        )

    def test_sr_ascii_clean(self) -> None:
        self._check(_FIXTURE_DIR / "active_match_sr.json")

    def test_aram_ascii_clean(self) -> None:
        self._check(_FIXTURE_DIR / "active_match_aram.json")

    def test_arena_ascii_clean(self) -> None:
        self._check(_FIXTURE_DIR / "active_match_arena.json")


if __name__ == "__main__":
    unittest.main()
