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
        `tools/lcu_agent.py:536` distils as 6x2 per live LCU shape.
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

    def test_tft_ascii_clean(self) -> None:
        self._check(_FIXTURE_DIR / "active_match_tft.json")
        self._check(_FIXTURE_DIR / "active_match_tft_live.json")


class TftFixtureTests(unittest.TestCase):
    """RM-895: the ?ui_mock=1&mode=tft / tft_live Active Match fixtures.

    Real TFT shape: the standalone TFT client has nothing on :2999, so the
    liveclient block is empty, and the no-feed fallback (active_match.js
    amLiveFallbackModel) reads stage / level / health / gold off the coach
    payload. The rendered page is pinned by
    tests/snapshot_panels/test_tft_ui_mock_active_match.py.
    """

    def test_main_js_routes_both_tft_modes(self) -> None:
        src = _read(_MAIN_JS)
        self.assertIn(
            'm === "tft") url = "/data/ui_mock/active_match_tft.json"', src
        )
        self.assertIn(
            'm === "tft_live") url = "/data/ui_mock/active_match_tft_live.json"',
            src,
        )

    def test_both_fixtures_are_a_live_tft_game_with_no_feed(self) -> None:
        for name in ("active_match_tft.json", "active_match_tft_live.json"):
            data = _load_fixture(name)
            self.assertEqual(data.get("mode"), "tft", name)
            self.assertEqual(data.get("phase"), "InProgress", name)
            self.assertEqual(data.get("liveclient"), {}, name)
            self.assertEqual((data.get("coach") or {}).get("mode"), "tft", name)

    def test_no_coach_imperative_in_either_fixture(self) -> None:
        # Real shape: the served TFT payload carried every advice field empty.
        # An invented imperative here would also be one the B4 live-directive
        # ban forbids any surface to show mid-game.
        for name in ("active_match_tft.json", "active_match_tft_live.json"):
            coach = _load_fixture(name).get("coach") or {}
            for key in ("action", "immediate", "board", "econ", "rolldown",
                        "items", "god_pick", "placement", "upgrade"):
                self.assertEqual(coach.get(key, ""), "", f"{name}: {key}")

    def test_unavailable_fixture_carries_no_tft_state(self) -> None:
        coach = _load_fixture("active_match_tft.json").get("coach") or {}
        for key in ("stage_round", "stage", "round", "level", "hp", "health",
                    "gold"):
            self.assertNotIn(key, coach, key)

    def test_live_fixture_uses_the_tft_coach_file_key_set(self) -> None:
        coach = _load_fixture("active_match_tft_live.json").get("coach") or {}
        # tft/tft_coach_engine.py writes health (not hp) and stage_round.
        self.assertEqual(coach.get("stage_round"), "4-2")
        self.assertEqual((coach.get("stage"), coach.get("round")), (4, 2))
        self.assertEqual(coach.get("level"), 8)
        self.assertEqual(coach.get("health"), 100)
        self.assertEqual(coach.get("gold"), 57)
        self.assertNotIn("hp", coach)


class TftRoundFixtureTests(unittest.TestCase):
    """RM-944: ?ui_mock=1&mode=tft_round, a verbatim recorded /api/state
    row of the S134 standalone-client shape (tft/tft_standalone.py), the one
    TFT fixture whose BOARD / LOBBY panes and overlay lobby carry data. The
    rendered page is pinned by tests/snapshot_panels/
    test_tft_ui_mock_active_match.py and test_tft_overlay_active_match.py.
    """

    _NAME = "active_match_tft_round.json"

    def test_main_js_routes_tft_round(self) -> None:
        self.assertIn(
            'm === "tft_round") url = "/data/ui_mock/active_match_tft_round.json"',
            _read(_MAIN_JS),
        )

    def test_ascii_clean(self) -> None:
        raw = (_FIXTURE_DIR / self._NAME).read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])
        self.assertNotIn(b"\r", raw)

    def test_is_the_standalone_round_feed_shape(self) -> None:
        data = _load_fixture(self._NAME)
        self.assertEqual(data.get("mode"), "tft")
        self.assertEqual(data.get("phase"), "InProgress")
        lc = data.get("liveclient") or {}
        self.assertEqual(lc.get("source"), "tft_standalone")
        self.assertIs(lc.get("live_api"), False)
        self.assertIs(lc.get("eliminated"), False)
        # The one field dropped from the recorded row: a match id no surface reads.
        self.assertNotIn("game_id", lc)
        coach = data.get("coach") or {}
        self.assertEqual(coach.get("mode"), "tft")
        for key in ("tft_board", "tft_players", "tft_as_of", "standing"):
            self.assertIn(key, coach, key)

    def test_coach_and_liveclient_agree_like_the_served_row(self) -> None:
        data = _load_fixture(self._NAME)
        lc, coach = data["liveclient"], data["coach"]
        self.assertEqual(lc["hp"], coach["hp"])
        self.assertEqual(lc["standing"], coach["standing"])
        self.assertEqual(lc["board"], coach["tft_board"])
        self.assertEqual(lc["players"], coach["tft_players"])
        self.assertEqual(lc["as_of"], coach["tft_as_of"])
        self.assertEqual(len(lc["board"]), lc["board_size"])

    def test_item_names_are_the_current_producer_form(self) -> None:
        # RM-946: the row was recorded before tft_standalone.clean_item_name
        # dropped the client's category token, so its one component item was
        # re-derived (DA_Component_BFSword -> "BF Sword"). A fixture carrying
        # the old served form would pin a string the backend no longer emits.
        data = _load_fixture(self._NAME)
        names = [i for u in data["coach"]["tft_board"] + data["liveclient"]["board"]
                 for i in u["items"]]
        self.assertIn("BF Sword", names)
        for n in names:
            self.assertFalse(n.startswith(("Component ", "Artifact ", "Emblem ")), n)

    def test_lobby_is_eight_anonymous_rows_with_one_you(self) -> None:
        rows = _load_fixture(self._NAME)["coach"]["tft_players"]
        self.assertEqual(len(rows), 8)
        self.assertEqual(sorted(r["standing"] for r in rows), list(range(1, 9)))
        self.assertEqual([r["standing"] for r in rows if r["you"]], [5])
        for r in rows:
            self.assertEqual(set(r), {"standing", "health", "you", "board_size"})


if __name__ == "__main__":
    unittest.main()
