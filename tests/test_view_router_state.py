"""View-router state machine integration tests (s171.8 backfill).

Exercises the Python mirror at `dashboard/view_router_state.py` which
mirrors the JS `_viewAutoDerive` function in `web/js/main.js` lines
482-568.  See that module's docstring for the test-mirror caveat.

Coverage targets (from `HEADLESS_BRIEF_2026-05-12_DOCS_TESTS.md` Task 1):
- ChampSelect → GameStart → InProgress → EndOfGame → Lobby (clean cycle)
- ChampSelect → Lobby (dodge — sticky should clear)
- ChampSelect → null → GameStart (transient null, sticky should hold)
- ChampSelect → null (extended, no GameStart observed) — sticky-guard
  inference advances to "game-start" per s171.8 fix
- InProgress → null/None/Lobby — gameStarted stays "in-progress"
- EndOfGame after in-progress → clears sticky
- Manual view sticky → auto-derive returns same view + urgent banner
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from dashboard.view_router_state import (  # noqa: E402
    DeriveResult,
    derive_view,
    is_urgent,
    update_game_started,
)


def _run(phases_modes, *, active=True):
    """Drive the state machine through a sequence of (phase, mode) ticks.

    Returns the list of DeriveResult instances, one per tick, with the
    sticky guard carried forward (matching how JS mutates _VIEW.gameStarted).
    """
    results = []
    sticky = None
    for phase, mode in phases_modes:
        r = derive_view(
            phase, mode, sticky,
            active_match_enabled=active,
        )
        results.append(r)
        sticky = r.game_started
    return results


class CleanCycleTests(unittest.TestCase):
    """Happy path: a full game from CS through post-game lobby."""

    def test_full_cycle_lands_on_each_view(self):
        # Phase sequence mimics what LCU emits across a real game.
        # Note: mode lingers as "sr" through EndOfGame because game_reader
        # doesn't flush mode_key until the next coaching tick — so the
        # post-game tick still resolves to "last-match", not "home".
        timeline = [
            ("Lobby",       "client"),  # pre-queue
            ("ChampSelect", "client"),  # CS opens
            ("ChampSelect", "client"),  # mid-CS tick
            ("GameStart",   "sr"),      # loading screen
            ("InProgress",  "sr"),      # in-game
            ("InProgress",  "sr"),      # in-game tick
            ("EndOfGame",   "sr"),      # post-game (sticky cleared)
            ("Lobby",       "client"),  # back to lobby
        ]
        results = _run(timeline)
        views = [r.view for r in results]
        self.assertEqual(views, [
            "lobby",
            "champ-select",
            "champ-select",
            "loading",
            "active-match",
            "active-match",
            "last-match",  # EndOfGame, sticky cleared, mode still "sr"
            "lobby",       # phase=Lobby → "lobby"
        ])
        # Sticky cleared after EndOfGame.
        self.assertIsNone(results[6].game_started)
        # Final sticky should remain cleared.
        self.assertIsNone(results[-1].game_started)


class DodgeClearTests(unittest.TestCase):
    """ChampSelect → Lobby/Matchmaking means the user dodged; clear sticky."""

    def test_cs_to_lobby_clears_sticky(self):
        results = _run([
            ("ChampSelect", "client"),
            ("Lobby",       "client"),
        ])
        self.assertEqual(results[0].game_started, "champ-select")
        self.assertEqual(results[0].view, "champ-select")
        # Dodge: sticky must clear, view falls back to lobby (per phase).
        self.assertIsNone(results[1].game_started)
        self.assertEqual(results[1].view, "lobby")

    def test_cs_to_matchmaking_clears_sticky(self):
        results = _run([
            ("ChampSelect",  "client"),
            ("Matchmaking",  "client"),
        ])
        self.assertIsNone(results[1].game_started)
        self.assertEqual(results[1].view, "lobby")

    def test_cs_to_ready_check_clears_sticky(self):
        results = _run([
            ("ChampSelect", "client"),
            ("ReadyCheck",  "client"),
        ])
        self.assertIsNone(results[1].game_started)
        self.assertEqual(results[1].view, "lobby")


class TransientNullTests(unittest.TestCase):
    """ChampSelect → null → GameStart: sticky must hold or infer game-start."""

    def test_brief_null_with_gamestart_arriving(self):
        # The 'easy' case — null lasts one tick, then GameStart fires.
        # Sticky inference advances to game-start during the null tick,
        # which is the desired behavior (s171.8 fix).
        results = _run([
            ("ChampSelect", "client"),
            (None,          "client"),  # transient blip
            ("GameStart",   "client"),
        ])
        self.assertEqual(results[0].game_started, "champ-select")
        # s171.8 inference: null after CS advances sticky → game-start.
        self.assertEqual(results[1].game_started, "game-start")
        self.assertEqual(results[1].view, "loading")
        # GameStart explicit → loading view, sticky = game-start.
        self.assertEqual(results[2].view, "loading")
        self.assertEqual(results[2].game_started, "game-start")

    def test_extended_null_after_cs_infers_game_start(self):
        # The s171.8 motivating case: GameStart never observed (missed
        # by the 2s poll), but ChampSelect is over. Sticky-guard inference
        # must advance to "game-start" so view stays on "loading".
        results = _run([
            ("ChampSelect", "client"),
            (None,          "client"),
            (None,          "client"),
            (None,          "client"),
            ("InProgress",  "sr"),  # finally lands on in-progress
        ])
        # All three null ticks should resolve to loading via sticky inference.
        self.assertEqual([r.view for r in results[1:4]], ["loading"] * 3)
        # Sticky on null ticks = game-start (carried forward).
        self.assertEqual(results[1].game_started, "game-start")
        self.assertEqual(results[2].game_started, "game-start")
        self.assertEqual(results[3].game_started, "game-start")
        # InProgress lands on active-match.
        self.assertEqual(results[4].view, "active-match")
        self.assertEqual(results[4].game_started, "in-progress")

    def test_empty_string_phase_treated_as_null(self):
        # JS `!phase` matches '' as well as null/undefined.
        results = _run([
            ("ChampSelect", "client"),
            ("",            "client"),
        ])
        self.assertEqual(results[1].game_started, "game-start")
        self.assertEqual(results[1].view, "loading")


class InProgressStickyTests(unittest.TestCase):
    """InProgress → null/Lobby blips must keep sticky on in-progress."""

    def test_in_progress_then_null_holds_sticky(self):
        results = _run([
            ("InProgress", "sr"),
            (None,         "sr"),
            (None,         "sr"),
            ("InProgress", "sr"),
        ])
        # Sticky should ride through the null blips.
        for r in results:
            self.assertEqual(r.game_started, "in-progress")
        # Views: explicit InProgress → active-match; null sticky → active-match.
        self.assertEqual([r.view for r in results], ["active-match"] * 4)

    def test_in_progress_then_lobby_with_postgame_clears(self):
        # Lobby IS in the post-game clear set when sticky=in-progress,
        # because LCU emits Lobby once the player returns to client.
        results = _run([
            ("InProgress", "sr"),
            ("Lobby",      "client"),
        ])
        self.assertEqual(results[0].game_started, "in-progress")
        self.assertIsNone(results[1].game_started)
        self.assertEqual(results[1].view, "lobby")

    def test_active_match_disabled_falls_through_to_last_match(self):
        # When operator opted out of active-match view, InProgress and the
        # in-progress sticky fallback both land on last-match.
        results = _run([("InProgress", "sr"), (None, "sr")], active=False)
        self.assertEqual(results[0].view, "last-match")
        self.assertEqual(results[1].view, "last-match")


class PostGameClearTests(unittest.TestCase):
    """EndOfGame / PreEndOfGame / WaitingForStats / TerminatedInError after
    in-progress must clear the sticky guard."""

    def test_each_postgame_phase_clears_sticky(self):
        for postgame in ("EndOfGame", "PreEndOfGame", "WaitingForStats",
                         "TerminatedInError", "Lobby"):
            with self.subTest(phase=postgame):
                results = _run([
                    ("InProgress", "sr"),
                    (postgame,     "client"),
                ])
                self.assertIsNone(results[1].game_started)

    def test_postgame_without_prior_in_progress_does_not_change_sticky(self):
        # If sticky was never set (no prior InProgress observed), the
        # post-game phase doesn't have anything to clear — sticky stays None.
        results = _run([("EndOfGame", "client")])
        self.assertIsNone(results[0].game_started)


class ChampSelectViewTests(unittest.TestCase):
    """ChampSelect always routes to the dedicated full-page view (s187+)."""

    def test_cs_phase_routes_to_champ_select(self):
        results = _run([("ChampSelect", "client")])
        self.assertEqual(results[0].view, "champ-select")
        self.assertEqual(results[0].game_started, "champ-select")


class HomeFallthroughTests(unittest.TestCase):
    """When nothing else matches, the default is home or last-match."""

    def test_no_phase_no_mode_returns_home(self):
        r = derive_view(None, None, None)
        self.assertEqual(r.view, "home")

    def test_client_mode_no_phase_returns_home(self):
        r = derive_view(None, "client", None)
        self.assertEqual(r.view, "home")

    def test_lobby_mode_no_phase_returns_home(self):
        r = derive_view(None, "lobby", None)
        self.assertEqual(r.view, "home")

    def test_unknown_mode_no_phase_returns_last_match(self):
        # Catch-all fallthrough — anything we didn't match.
        r = derive_view(None, "weirdmode", None)
        self.assertEqual(r.view, "last-match")


class UrgentViewTests(unittest.TestCase):
    """`is_urgent` decides whether to auto-promote past manual sticky."""

    def test_urgent_views_promote(self):
        for v in ("lobby", "champ-select", "loading", "last-match"):
            with self.subTest(view=v):
                self.assertTrue(is_urgent(v))

    def test_non_urgent_views_do_not_promote(self):
        for v in ("home", "active-match", "session", "history",
                  "replay", "user-builds", "settings", "dev"):
            with self.subTest(view=v):
                self.assertFalse(is_urgent(v))


class UpdateGameStartedTests(unittest.TestCase):
    """Direct tests of the pure sticky-guard transition table."""

    def test_explicit_phases_set_sticky(self):
        self.assertEqual(update_game_started("ChampSelect", None), "champ-select")
        self.assertEqual(update_game_started("GameStart", None), "game-start")
        self.assertEqual(update_game_started("InProgress", None), "in-progress")

    def test_overriding_phases_advance_or_preserve(self):
        # GameStart while sticky=champ-select advances.
        self.assertEqual(
            update_game_started("GameStart", "champ-select"), "game-start",
        )
        # InProgress while sticky=game-start advances.
        self.assertEqual(
            update_game_started("InProgress", "game-start"), "in-progress",
        )

    def test_clear_paths(self):
        self.assertIsNone(update_game_started("EndOfGame", "in-progress"))
        self.assertIsNone(update_game_started("Lobby", "in-progress"))
        self.assertIsNone(update_game_started("Lobby", "champ-select"))
        self.assertIsNone(update_game_started("Matchmaking", "champ-select"))

    def test_preserve_paths(self):
        # ChampSelect sticky should not clear on stable postgame phases
        # that aren't in the dodge set (EndOfGame applies to in-progress only).
        self.assertEqual(
            update_game_started("EndOfGame", "champ-select"), "champ-select",
        )
        # game-start sticky is preserved through non-clear phases.
        self.assertEqual(
            update_game_started("EndOfGame", "game-start"), "game-start",
        )

    def test_inference_only_fires_for_cs_sticky(self):
        # null with no prior sticky: stays None.
        self.assertIsNone(update_game_started(None, None))
        # null with in-progress sticky: stays in-progress (no inference).
        self.assertEqual(
            update_game_started(None, "in-progress"), "in-progress",
        )
        # null with game-start sticky: stays game-start (no inference).
        self.assertEqual(
            update_game_started(None, "game-start"), "game-start",
        )
        # null with champ-select sticky: INFERS game-start (s171.8 fix).
        self.assertEqual(
            update_game_started(None, "champ-select"), "game-start",
        )


class DeriveResultDataclassTests(unittest.TestCase):
    """Sanity check the return shape used everywhere."""

    def test_result_carries_both_fields(self):
        r = derive_view("ChampSelect", "client", None)
        self.assertIsInstance(r, DeriveResult)
        self.assertEqual(r.view, "champ-select")
        self.assertEqual(r.game_started, "champ-select")


if __name__ == "__main__":
    unittest.main()
