"""View-router state machine integration tests (s171.8 backfill, s209 update).

Exercises the Python mirror at `dashboard/view_router_state.py` which
mirrors the JS `_viewAutoDerive` function in `web/js/main.js`.

s209 changes:
- Loading view retired. GameStart now lands on active-match directly.
- Sticky-guard "game-start" tier dropped. GameStart sets sticky to
  "in-progress"; CS->null inference advances to "in-progress" as well.

Coverage targets:
- ChampSelect -> GameStart -> InProgress -> EndOfGame -> Lobby (clean cycle)
- ChampSelect -> Lobby (dodge - sticky should clear)
- ChampSelect -> null -> GameStart (transient null, sticky should hold)
- ChampSelect -> null (extended, no GameStart observed) - sticky-guard
  inference advances to "in-progress" per s209
- InProgress -> null/None/Lobby - gameStarted stays "in-progress"
- EndOfGame after in-progress -> clears sticky
- Manual view sticky -> auto-derive returns same view + urgent banner
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
        # doesn't flush mode_key until the next coaching tick - so the
        # post-game tick still resolves to "last-match", not "home".
        timeline = [
            ("Lobby",       "client"),  # pre-queue
            ("ChampSelect", "client"),  # CS opens
            ("ChampSelect", "client"),  # mid-CS tick
            ("GameStart",   "sr"),      # s209: -> active-match (was loading)
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
            "active-match",   # s209: GameStart -> active-match
            "active-match",
            "active-match",
            "last-match",  # EndOfGame, sticky cleared, mode still "sr"
            "lobby",       # phase=Lobby -> "lobby"
        ])
        # Sticky cleared after EndOfGame.
        self.assertIsNone(results[6].game_started)
        # Final sticky should remain cleared.
        self.assertIsNone(results[-1].game_started)


class DodgeClearTests(unittest.TestCase):
    """ChampSelect -> Lobby/Matchmaking means the user dodged; clear sticky."""

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
    """ChampSelect -> null -> GameStart: sticky must hold or infer in-progress."""

    def test_brief_null_with_gamestart_arriving(self):
        # The 'easy' case - null lasts one tick, then GameStart fires.
        # s209: null after CS infers "in-progress" -> active-match.
        results = _run([
            ("ChampSelect", "client"),
            (None,          "client"),  # transient blip
            ("GameStart",   "client"),
        ])
        self.assertEqual(results[0].game_started, "champ-select")
        # s209 inference: null after CS advances sticky -> in-progress.
        self.assertEqual(results[1].game_started, "in-progress")
        self.assertEqual(results[1].view, "active-match")
        # GameStart -> active-match, sticky = in-progress.
        self.assertEqual(results[2].view, "active-match")
        self.assertEqual(results[2].game_started, "in-progress")

    def test_extended_null_after_cs_infers_in_progress(self):
        # The s209 motivating case: GameStart never observed (missed by
        # the 2s poll), but ChampSelect is over. Sticky-guard inference
        # advances to "in-progress" so view lands on active-match.
        results = _run([
            ("ChampSelect", "client"),
            (None,          "client"),
            (None,          "client"),
            (None,          "client"),
            ("InProgress",  "sr"),  # finally lands on in-progress
        ])
        # All three null ticks should resolve to active-match via sticky.
        self.assertEqual([r.view for r in results[1:4]], ["active-match"] * 3)
        # Sticky on null ticks = in-progress (carried forward).
        self.assertEqual(results[1].game_started, "in-progress")
        self.assertEqual(results[2].game_started, "in-progress")
        self.assertEqual(results[3].game_started, "in-progress")
        # InProgress lands on active-match.
        self.assertEqual(results[4].view, "active-match")
        self.assertEqual(results[4].game_started, "in-progress")

    def test_empty_string_phase_treated_as_null(self):
        # JS `!phase` matches '' as well as null/undefined.
        results = _run([
            ("ChampSelect", "client"),
            ("",            "client"),
        ])
        self.assertEqual(results[1].game_started, "in-progress")
        self.assertEqual(results[1].view, "active-match")


class InProgressStickyTests(unittest.TestCase):
    """InProgress -> null/Lobby blips must keep sticky on in-progress."""

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
        # Views: explicit InProgress -> active-match; null sticky -> active-match.
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

    def test_game_start_active_disabled_falls_through_to_last_match(self):
        # s209: GameStart with active_match_enabled=False also falls
        # through to last-match (same as InProgress disabled).
        results = _run([("GameStart", "sr")], active=False)
        self.assertEqual(results[0].view, "last-match")
        self.assertEqual(results[0].game_started, "in-progress")


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
        # post-game phase doesn't have anything to clear - sticky stays None.
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
        # Catch-all fallthrough - anything we didn't match.
        r = derive_view(None, "weirdmode", None)
        self.assertEqual(r.view, "last-match")


class UrgentViewTests(unittest.TestCase):
    """`is_urgent` decides whether to auto-promote past manual sticky.

    s209: "loading" removed from urgent set; "active-match" added.
    """

    def test_urgent_views_promote(self):
        for v in ("lobby", "champ-select", "active-match", "last-match"):
            with self.subTest(view=v):
                self.assertTrue(is_urgent(v))

    def test_non_urgent_views_do_not_promote(self):
        # "dev" removed 2026-09-04 (RM-340): it was never in this module's
        # VIEW_IDS and is now gone from the JS registry too, so asserting it is
        # non-urgent asserted nothing - is_urgent returns False for any unknown
        # id. Same shape as the "loading" case documented below.
        for v in ("home", "session", "history",
                  "replay", "user-builds", "settings"):
            with self.subTest(view=v):
                self.assertFalse(is_urgent(v))

    def test_loading_view_id_no_longer_recognised(self):
        # s209: loading was urgent pre-s209 but the view itself is gone.
        # is_urgent of an unknown id returns False (not in the set).
        self.assertFalse(is_urgent("loading"))


class UpdateGameStartedTests(unittest.TestCase):
    """Direct tests of the pure sticky-guard transition table."""

    def test_explicit_phases_set_sticky(self):
        self.assertEqual(update_game_started("ChampSelect", None), "champ-select")
        # s209: GameStart now sets sticky to "in-progress" (was "game-start").
        self.assertEqual(update_game_started("GameStart", None), "in-progress")
        self.assertEqual(update_game_started("InProgress", None), "in-progress")

    def test_overriding_phases_advance_or_preserve(self):
        # GameStart while sticky=champ-select advances to in-progress.
        self.assertEqual(
            update_game_started("GameStart", "champ-select"), "in-progress",
        )
        # InProgress while sticky=in-progress stays in-progress.
        self.assertEqual(
            update_game_started("InProgress", "in-progress"), "in-progress",
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

    def test_inference_only_fires_for_cs_sticky(self):
        # null with no prior sticky: stays None.
        self.assertIsNone(update_game_started(None, None))
        # null with in-progress sticky: stays in-progress (no inference).
        self.assertEqual(
            update_game_started(None, "in-progress"), "in-progress",
        )


class LiveGateTests(unittest.TestCase):
    """item 281: a stale in-game mode flag must NOT promote an in-game view
    when there is no live game.

    The phantom-active-match bug: an ARAM lobby resolved mode_key='aram'
    from a stale ``health.aram_mode``; the LCU snapshot blipped to null
    between agent pushes; ``derive_view`` then promoted 'active-match' and
    the grid rendered an 11-day-old coach payload as a live 14:54 match.

    ``live`` (liveclient non-empty) is the cross-mode "a real game is
    running" signal. It defaults True so existing callers / s209 loading
    inference are unchanged; the live runtime passes the real value.
    """

    def test_null_phase_in_game_mode_no_live_goes_home(self):
        # Stale aram mode + LCU phase blip to null + NO live game -> home,
        # never the phantom active-match.
        r = derive_view(None, "aram", None, live=False)
        self.assertEqual(r.view, "home")

    def test_null_phase_in_game_mode_with_live_is_active_match(self):
        # Genuine loading / mid-game null blip WITH a live game -> active.
        r = derive_view(None, "aram", None, live=True)
        self.assertEqual(r.view, "active-match")

    def test_in_game_mode_no_live_no_phase_is_home_not_last_match(self):
        # Mode lingers in-game post-clear but no live game + no phase ->
        # home, not the in-game last-match grid.
        r = derive_view(None, "sr", None, live=False)
        self.assertEqual(r.view, "home")

    def test_lobby_phase_in_game_mode_no_live_is_lobby(self):
        # The common idle case: LCU reports Lobby -> lobby regardless.
        r = derive_view("Lobby", "aram", None, live=False)
        self.assertEqual(r.view, "lobby")

    def test_explicit_in_progress_is_active_even_without_live(self):
        # An explicit in-game phase is itself a live signal (game loading
        # before liveclient :2999 answers); active-match is correct.
        r = derive_view("InProgress", "aram", None, live=False)
        self.assertEqual(r.view, "active-match")

    def test_default_live_true_preserves_s209_inference(self):
        # Existing callers omit live; default True keeps null-after-CS
        # sticky inference landing on active-match.
        r = derive_view(None, "aram", "in-progress")
        self.assertEqual(r.view, "active-match")
        # s209: null with champ-select sticky infers "in-progress" (was
        # "game-start" pre-s209).
        self.assertEqual(
            update_game_started(None, "champ-select"), "in-progress",
        )


class ChampSelectNullBlipLiveGateTests(unittest.TestCase):
    """A transient null/empty LCU phase tick during champ select must NOT
    promote the sticky guard to in-progress (active-match) when no game is
    live. ``lcu.phase`` is a polled, relay-forwarded value that reads null on
    any agent/relay/poll blip; pre-fix, a single such blip flipped the view to
    the in-game page ~half the time and could stick there. Only a real game
    signal (live=liveclient non-empty, or an explicit GameStart/InProgress
    phase) advances past champ-select."""

    def test_cs_then_null_blip_no_live_holds_champ_select(self):
        # In CS, phase blips to null on one tick, no live game -> stay on CS.
        r = derive_view(None, "client", "champ-select", live=False)
        self.assertEqual(r.game_started, "champ-select")
        self.assertEqual(r.view, "champ-select")

    def test_cs_then_null_blip_with_live_promotes(self):
        # Genuine CS->game flip: liveclient up -> promote to in-progress.
        r = derive_view(None, "client", "champ-select", live=True)
        self.assertEqual(r.game_started, "in-progress")
        self.assertEqual(r.view, "active-match")

    def test_cs_null_blip_then_champ_select_recovers_no_live(self):
        # Sequence CS -> null(no live) -> CS must stay champ-select throughout,
        # never flicker to active-match.
        r1 = derive_view(None, "client", "champ-select", live=False)
        self.assertEqual(r1.view, "champ-select")
        r2 = derive_view("ChampSelect", "client", r1.game_started, live=False)
        self.assertEqual(r2.view, "champ-select")

    def test_update_game_started_live_gate(self):
        # Direct: null + champ-select sticky + no live -> stays champ-select.
        self.assertEqual(
            update_game_started(None, "champ-select", live=False),
            "champ-select",
        )
        # With live -> in-progress (s209 inference preserved).
        self.assertEqual(
            update_game_started(None, "champ-select", live=True),
            "in-progress",
        )

    def test_explicit_gamestart_promotes_even_without_live(self):
        # The genuine flip is still caught by the ungated GameStart path,
        # so gating the null-inference on live loses no real promotion.
        r = derive_view("GameStart", "client", "champ-select", live=False)
        self.assertEqual(r.view, "active-match")
        self.assertEqual(r.game_started, "in-progress")


class DeriveResultDataclassTests(unittest.TestCase):
    """Sanity check the return shape used everywhere."""

    def test_result_carries_both_fields(self):
        r = derive_view("ChampSelect", "client", None)
        self.assertIsInstance(r, DeriveResult)
        self.assertEqual(r.view, "champ-select")
        self.assertEqual(r.game_started, "champ-select")


if __name__ == "__main__":
    unittest.main()
