"""Auto-show Post Game Review on game-end must survive a phase-blind game.

BUG (reproduced 3x live, 2026-07-20): when a game ended the dashboard went
straight to Home instead of the Post Game Review. ``rc-view-manual`` was
unset and the view label read "AUTO . HOME", so the auto-PGR arm inside
``_viewAutoDerive`` (web/js/main.js) never executed.

ROOT CAUSE. The auto-PGR arm is gated on the in-memory sticky
``_VIEW.gameStarted === "in-progress"``, which pre-fix could ONLY be set by
observing an explicit LCU phase of ChampSelect / GameStart / InProgress in the
same page session. But the browser does not reliably see a phase during a
live game:

  * ``tools/lcu_agent.py`` ``capture_state`` docstring - in-game an LCU
    capture cycle finishes "8-11s" behind because LCU calls run slow under
    League CPU pressure (push cadence ``INTERVAL = 1.0``).
  * ``dashboard/_liveclient.lcu_summary`` hard-drops any relayed snapshot
    older than 5s and returns ``{}``.

5s TTL against an 8-11s in-game capture means ``/api/state.lcu`` is ``{}``
(no ``phase``) for much of a game. The page still renders the in-game surface
through the item-281 null-phase promotion (``not phase and mode in
IN_GAME_MODES and live``) - a path that asserts a real live game yet did NOT
arm the sticky. Any page session that starts after champ-select (the ADR-008
asset-hash auto-reload mid-game, or a tab opened mid-game) therefore reaches
game-end with the sticky still ``None``, the post-game arm is skipped, and
derivation falls through to "home".

FIX. The null-phase live-game promotion now arms the sticky too, in the JS
and in this Python mirror. ``is_postgame_pgr_edge`` is the mirror of the
auto-PGR arm itself - the original fix (commit a2fdf448) deliberately left
the mirror unchanged because "navigation is a side-effect, not a derived
view", which is exactly why the regression shipped untested.

Two halves, matching tests/test_overlay_a3_coach_tag_strip.py:
  1. BEHAVIOUR - real assertions against dashboard/view_router_state.py.
  2. GREP CONTRACT - the JS source is pinned to the same transition table
     (there is no jsdom/node harness for web/js page code).
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

MAIN_JS = REPO / "web" / "js" / "main.js"

from dashboard.view_router_state import (  # noqa: E402
    IN_GAME_MODES,
    derive_view,
    is_postgame_pgr_edge,
    update_game_started,
)


def _derive_js() -> str:
    """Source text of `_viewAutoDerive` from main.js.

    Sliced by marker (not line number) so the test does not rot when the
    file above it shifts: from the function head to the next sibling
    declaration at the same 2-space IIFE indent.
    """
    src = MAIN_JS.read_text(encoding="utf-8")
    i = src.find("function _viewAutoDerive(lcu, mode) {")
    assert i != -1, "_viewAutoDerive not found in main.js"
    j = src.find("\n  function _viewIsUrgent", i)
    assert j != -1, "_viewIsUrgent (next sibling) not found after _viewAutoDerive"
    return src[i:j]


class PhaseBlindGameArmsTheSticky(unittest.TestCase):
    """A live game seen only through the null-phase promotion must still arm
    the sticky, so the following post-game phase is a PGR edge.

    This is the exact live sequence: lcu == {} for the whole page session
    (5s TTL vs 8-11s in-game capture), then PreEndOfGame lands once the
    game closes and the client speeds back up.
    """

    def test_null_phase_live_in_game_arms_sticky(self):
        r = derive_view(None, "arena", None, live=True)
        self.assertEqual(r.view, "active-match")
        self.assertEqual(r.game_started, "in-progress")

    def test_phase_blind_game_then_preendofgame_is_a_pgr_edge(self):
        sticky = None
        for _ in range(3):  # in-game ticks, lcu == {} -> phase None
            sticky = derive_view(None, "arena", sticky, live=True).game_started
        self.assertEqual(sticky, "in-progress")
        self.assertTrue(is_postgame_pgr_edge("PreEndOfGame", sticky))
        # And the edge clears the sticky, so the arm fires exactly once.
        after = derive_view("PreEndOfGame", "client", sticky, live=False)
        self.assertIsNone(after.game_started)
        self.assertFalse(is_postgame_pgr_edge("PreEndOfGame", after.game_started))

    def test_phase_blind_game_covers_every_in_game_mode(self):
        for mode in sorted(IN_GAME_MODES):
            with self.subTest(mode=mode):
                sticky = derive_view(None, mode, None, live=True).game_started
                self.assertEqual(sticky, "in-progress")

    def test_update_game_started_arm_is_direct(self):
        self.assertEqual(
            update_game_started(None, None, live=True, mode="aram"),
            "in-progress",
        )
        self.assertEqual(
            update_game_started("", None, live=True, mode="sr"),
            "in-progress",
        )


class ArmStaysGated(unittest.TestCase):
    """The new arm must not widen past the item-281 gate."""

    def test_no_live_game_does_not_arm(self):
        # Stale in-game mode flag with no liveclient - the item-281 phantom.
        r = derive_view(None, "aram", None, live=False)
        self.assertEqual(r.view, "home")
        self.assertIsNone(r.game_started)

    def test_client_mode_does_not_arm(self):
        self.assertIsNone(update_game_started(None, None, live=True, mode="client"))
        self.assertIsNone(update_game_started(None, None, live=True, mode=None))

    def test_unknown_mode_does_not_arm(self):
        self.assertIsNone(
            update_game_started(None, None, live=True, mode="weirdmode"),
        )

    def test_champ_select_null_blip_still_gated_on_live(self):
        # Regression guard for the s209 CS null-blip fix: no live game +
        # champ-select sticky must stay champ-select even in an in-game mode.
        self.assertEqual(
            update_game_started(None, "champ-select", live=False, mode="aram"),
            "champ-select",
        )

    def test_explicit_phase_never_reaches_the_arm(self):
        # Every explicit phase keeps its own transition.
        self.assertEqual(
            update_game_started("ChampSelect", None, live=True, mode="aram"),
            "champ-select",
        )
        self.assertIsNone(
            update_game_started("EndOfGame", "in-progress", live=True, mode="aram"),
        )


class PostGamePgrEdgeMirror(unittest.TestCase):
    """`is_postgame_pgr_edge` mirrors the inner guard at main.js:622."""

    def test_every_postgame_phase_is_an_edge_from_in_progress(self):
        for phase in ("EndOfGame", "PreEndOfGame", "WaitingForStats",
                      "TerminatedInError", "Lobby"):
            with self.subTest(phase=phase):
                self.assertTrue(is_postgame_pgr_edge(phase, "in-progress"))

    def test_no_edge_without_the_in_progress_sticky(self):
        self.assertFalse(is_postgame_pgr_edge("PreEndOfGame", None))
        self.assertFalse(is_postgame_pgr_edge("PreEndOfGame", "champ-select"))

    def test_phases_outside_the_postgame_set_are_not_edges(self):
        # "None" / Matchmaking / ReadyCheck are deliberately excluded: a
        # mid-game blip to those must not flush the in-game view (s209).
        for phase in ("None", "Matchmaking", "ReadyCheck", "InProgress", None):
            with self.subTest(phase=phase):
                self.assertFalse(is_postgame_pgr_edge(phase, "in-progress"))


class MainJsContract(unittest.TestCase):
    """The JS transition table carries the same arm (no JS runtime in CI)."""

    def setUp(self):
        self.fn = _derive_js()

    def test_auto_pgr_arm_still_present(self):
        self.assertIn('_viewSaveManual("last-match")', self.fn)
        self.assertIn("fetchAndRenderLastMatch()", self.fn)

    def test_in_game_mode_list_matches_the_python_mirror(self):
        m = re.search(r"const inGame = \[([^\]]*)\]", self.fn)
        self.assertIsNotNone(m, "inGame mode list not found in _viewAutoDerive")
        js_modes = set(re.findall(r'"([a-z]+)"', m.group(1)))
        self.assertEqual(js_modes, set(IN_GAME_MODES))

    def test_in_game_hoisted_above_the_sticky_block(self):
        # The arm reads `inGame`, so the const must be declared before the
        # first sticky mutation or the JS throws a TDZ ReferenceError.
        i = self.fn.find("const inGame = [")
        j = self.fn.find("_VIEW.gameStarted =")
        self.assertNotEqual(i, -1)
        self.assertNotEqual(j, -1)
        self.assertLess(i, j, "const inGame must be hoisted above the sticky block")

    def test_in_game_declared_exactly_once(self):
        self.assertEqual(self.fn.count("const inGame = ["), 1)

    def test_null_phase_live_arm_present(self):
        self.assertIn("else if (!phase && live && inGame)", self.fn)
        arm = self.fn[self.fn.find("else if (!phase && live && inGame)"):]
        head = arm[:200]
        self.assertIn('_VIEW.gameStarted = "in-progress"', head)

    def test_mirror_pointer_comment_retained(self):
        self.assertIn("dashboard/view_router_state.py", self.fn)


if __name__ == "__main__":
    unittest.main()
