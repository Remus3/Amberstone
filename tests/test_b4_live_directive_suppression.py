"""B4-a (RM-189): the served envelope must carry NO coach imperative while a
game is live.

Riot's third-party rules ban "notifications that dictate player action based on
the current game state". The compliance decision
(``docs/OVERLAY_COMPLIANCE_PLAN.md`` section 6c, operator 2026-08-11) moves
live coaching to pre-game and post-game and keeps only SILENT capture of the
decision branch points in-game.

Design: ``docs/OVERLAY_B4_DESIGN.md``. The suppression happens at the PRODUCER,
not the renderer, following the B5 precedent ("obfuscate at the producer ... so
every consumer inherits it") and the B2 precedent (the key stays on
``/api/state`` as a permanent null so consumers degrade rather than crash).

These are INVERTED guards, the same shape B1-B3 left behind: reinstating a live
imperative turns them red.

The three load-bearing cases, in the order they matter:
  1. suppression fires in a live game;
  2. the NEGATIVE CONTROL - the same fields are populated when NOT in a game.
     Without this, an always-null builder passes case 1 trivially;
  3. the shadow capture still records the full branch set, i.e. compliance did
     not silently kill the Haiku-to-ZERO validation substrate.
"""
from __future__ import annotations

import unittest
from unittest import mock

from dashboard import _state_builder
from dashboard._state_builder import (
    LIVE_SUPPRESSED_ENVELOPE_FIELDS,
    LIVE_SUPPRESSED_FIELDS,
    is_live_game,
    suppress_live_directives,
    suppress_live_envelope,
)


def _directive_coach():
    """A coach payload carrying every imperative field plus descriptive state."""
    return {
        # Imperatives - all must go while live.
        "action": "ALL-IN NOW",
        "immediate": "Enemy flash is down, walk up and commit.",
        "fight_rule": "Fight only with your jungler topside.",
        "next": "Reset after the dive.",
        "risk": "You die if Leona lands E.",
        "target_priority": "Focus Caitlyn first.",
        "round_strategy": "Open on the backline.",
        "choices": [
            {"key": "A", "label": "Force a short trade", "confidence": "high"},
            {"key": "B", "label": "Back off", "confidence": "low"},
        ],
        # Descriptive state - all must survive.
        "champion": "Kai'Sa",
        "game_time": "14:54",
        "kda": "13/7/15",
        "hp_pct": 62.0,
        "gold": 1450,
        "level": 11,
        "cc_threat_cell": {"Leona": 2.5},
    }


_DESCRIPTIVE = ("champion", "game_time", "kda", "hp_pct", "gold", "level",
                "cc_threat_cell")


class IsLiveGameTests(unittest.TestCase):
    def test_each_live_flag_is_live(self):
        for flag in ("has_game", "aram_mode", "arena_mode", "tft_mode",
                     "brawl_mode"):
            with self.subTest(flag=flag):
                self.assertTrue(is_live_game({flag: True}, False))

    def test_client_idle_is_not_live(self):
        self.assertFalse(is_live_game({"mode": "client"}, False))
        self.assertFalse(is_live_game({}, False))

    def test_champ_select_preflip_is_not_live(self):
        """The s150 LCU pre-flip MIRRORS a per-mode flag onto health during
        champ select (apply_preflip_mirror). Champ select is pre-game, where
        coaching is explicitly still allowed, so the mirrored flag must not
        read as a live game."""
        self.assertFalse(is_live_game({"aram_mode": True}, True))
        self.assertFalse(is_live_game({"has_game": True}, True))

    def test_non_dict_safe(self):
        self.assertFalse(is_live_game(None, False))


class SuppressLiveDirectivesTests(unittest.TestCase):
    def test_every_imperative_is_suppressed_while_live(self):
        out = suppress_live_directives(_directive_coach(), {"has_game": True},
                                       False)
        for field in LIVE_SUPPRESSED_FIELDS:
            with self.subTest(field=field):
                self.assertIn(field, out,
                              "B2 precedent: the key STAYS so consumers degrade")
                self.assertFalse(out[field], f"{field} must be falsy while live")

    def test_choices_suppresses_to_empty_list_not_none(self):
        """coach_choices.js does Array.isArray(coach.choices) - a None would
        make the renderer fall through to the prose branch instead of the
        empty branch."""
        out = suppress_live_directives(_directive_coach(), {"has_game": True},
                                       False)
        self.assertEqual(out["choices"], [])

    def test_descriptive_state_survives(self):
        """The ban is on imperatives. Stripping the descriptive read too would
        be an over-broad suppression, and this is the guard that catches it."""
        src = _directive_coach()
        out = suppress_live_directives(src, {"has_game": True}, False)
        for field in _DESCRIPTIVE:
            with self.subTest(field=field):
                self.assertEqual(out[field], src[field])

    def test_negative_control_not_live_leaves_everything(self):
        src = _directive_coach()
        out = suppress_live_directives(src, {"mode": "client"}, False)
        for field in LIVE_SUPPRESSED_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(out[field], src[field])

    def test_negative_control_champ_select_leaves_everything(self):
        src = _directive_coach()
        out = suppress_live_directives(src, {"aram_mode": True}, True)
        self.assertEqual(out["action"], src["action"])
        self.assertEqual(out["choices"], src["choices"])

    def test_does_not_mutate_caller_payload(self):
        """The same coach dict is the shadow writers' input earlier in the
        tick. Mutating it in place would retroactively blank what they logged
        if any writer holds a reference."""
        src = _directive_coach()
        suppress_live_directives(src, {"has_game": True}, False)
        self.assertEqual(src["action"], "ALL-IN NOW")
        self.assertEqual(len(src["choices"]), 2)

    def test_absent_fields_are_not_invented(self):
        out = suppress_live_directives({"champion": "Ashe"},
                                       {"has_game": True}, False)
        self.assertEqual(out, {"champion": "Ashe"})

    def test_non_dict_safe(self):
        self.assertIsNone(suppress_live_directives(None, {"has_game": True},
                                                   False))


def _directive_det():
    """A deterministic block whose callout + lead lines are verbatim from the
    producers, so these guards fail if the real vocabulary changes."""
    return {
        "choices": [{"key": "A", "label": "Force a short trade"}],
        # core/event_callouts.py:119,127,107 - imperatives, and the two spike
        # lines are ALSO the B3 power-spike notification.
        "callouts": [
            {"tag": "lvl6", "line": "Your lvl-6 spike - look for all-in",
             "eta_s": 0.0, "kind": "spike"},
            {"tag": "item2", "line": "2-item spike - force fights now",
             "eta_s": 0.0, "kind": "spike"},
            {"tag": "dragon", "line": "Drake spawns 5:00 - set up vision",
             "eta_s": 45.0, "kind": "objective"},
        ],
        # core/lead_projection.py:211 - the module calls _LINES_BY_MODE a
        # "per-mode directive table" in so many words.
        "lead_projection": {"state": "ahead", "magnitude": "large",
                            "line": "Big lead: dive or roam, snowball it now."},
    }


class SuppressLiveEnvelopeTests(unittest.TestCase):
    """B4-b: `callouts` and `lead_projection` are TOP-LEVEL siblings of
    `coach` on /api/state, so the B4-a coach-field sweep did not reach them -
    yet #rn-callouts and #rn-lead are two of the only three mounts the overlay
    shell keeps visible (web/css/overlay.css:127). Both carry imperatives."""

    def test_callouts_and_lead_are_blanked_while_live(self):
        out = suppress_live_envelope(_directive_det(), {"has_game": True}, False)
        self.assertEqual(out["callouts"], [])
        self.assertEqual(out["lead_projection"], {})

    def test_every_declared_envelope_field_is_covered(self):
        out = suppress_live_envelope(_directive_det(), {"has_game": True}, False)
        for field in LIVE_SUPPRESSED_ENVELOPE_FIELDS:
            with self.subTest(field=field):
                self.assertFalse(out.get(field))

    def test_negative_control_not_live_leaves_everything(self):
        src = _directive_det()
        out = suppress_live_envelope(src, {"mode": "client"}, False)
        self.assertEqual(len(out["callouts"]), 3)
        self.assertEqual(out["lead_projection"]["state"], "ahead")

    def test_champ_select_preflip_leaves_everything(self):
        src = _directive_det()
        out = suppress_live_envelope(src, {"aram_mode": True}, True)
        self.assertEqual(len(out["callouts"]), 3)

    def test_does_not_mutate_caller_payload(self):
        src = _directive_det()
        suppress_live_envelope(src, {"has_game": True}, False)
        self.assertEqual(len(src["callouts"]), 3)

    def test_non_dict_safe(self):
        self.assertIsNone(suppress_live_envelope(None, {"has_game": True}, False))


class BuildStateSuppressesLiveDirectivesTests(unittest.TestCase):
    """End-to-end through build_state, mirroring the item-281 harness in
    tests/test_state_builder_cleared_at.py."""

    def _patch(self, *, health, coach_payload, lc_payload, shadow_spy=None):
        def _read_json(p):
            if "health" in str(p):
                return health
            return coach_payload

        patches = [
            mock.patch.object(_state_builder, "read_json", side_effect=_read_json),
            mock.patch.object(_state_builder, "lcu_summary", return_value={}),
            mock.patch.object(_state_builder, "liveclient_summary",
                              return_value=(lc_payload or {})),
            mock.patch.object(_state_builder, "get_team_context", return_value=None),
            mock.patch.object(_state_builder, "validate_coaching_payload",
                              lambda *_a, **_kw: None),
        ]
        if shadow_spy is not None:
            from dashboard import _deterministic_coaching as _dc
            patches.append(mock.patch.object(
                _dc, "shadow_log_precomputed_choices", side_effect=shadow_spy))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_live_game_serves_no_imperative(self):
        self._patch(
            health={"mode": "client", "aram_mode": True},
            coach_payload=_directive_coach(),
            lc_payload={"champion": "Kai'Sa", "game_time": "14:54"},
        )
        coach = _state_builder.build_state()["coach"]
        for field in LIVE_SUPPRESSED_FIELDS:
            with self.subTest(field=field):
                self.assertFalse(coach.get(field),
                                 f"{field} leaked into the live envelope")

    def test_live_game_still_serves_descriptive_state(self):
        self._patch(
            health={"mode": "client", "aram_mode": True},
            coach_payload=_directive_coach(),
            lc_payload={"champion": "Kai'Sa", "game_time": "14:54"},
        )
        coach = _state_builder.build_state()["coach"]
        self.assertEqual(coach.get("champion"), "Kai'Sa")
        self.assertEqual(coach.get("kda"), "13/7/15")
        self.assertEqual(coach.get("cc_threat_cell"), {"Leona": 2.5})

    def test_shadow_capture_still_sees_the_native_branch_set(self):
        """Guard 5 - the compliance gate must not starve the HZ-C1 substrate.

        The shadow writer runs BEFORE the suppression, so it must observe the
        UNSUPPRESSED choices even though the served envelope carries none.
        """
        seen = {}

        def _spy(coach, lc, mode_key, *a, **kw):
            seen["choices"] = list(coach.get("choices") or [])
            seen["action"] = coach.get("action")

        self._patch(
            health={"mode": "client", "aram_mode": True},
            coach_payload=_directive_coach(),
            lc_payload={"champion": "Kai'Sa", "game_time": "14:54"},
            shadow_spy=_spy,
        )
        coach = _state_builder.build_state()["coach"]
        self.assertEqual(len(seen.get("choices") or []), 2,
                         "shadow writer lost the native branch set")
        self.assertEqual(seen.get("action"), "ALL-IN NOW")
        self.assertFalse(coach.get("choices"))

    def _patch_det(self, det):
        from dashboard import _deterministic_coaching as _dc
        p = mock.patch.object(_dc, "compute_deterministic", return_value=det)
        p.start()
        self.addCleanup(p.stop)

    def test_live_game_serves_no_callouts_or_lead(self):
        self._patch(
            health={"mode": "client", "aram_mode": True},
            coach_payload=_directive_coach(),
            lc_payload={"champion": "Kai'Sa", "game_time": "14:54"},
        )
        self._patch_det(_directive_det())
        state = _state_builder.build_state()
        self.assertEqual(state["callouts"], [],
                         "#rn-callouts feed leaked into the live envelope")
        self.assertEqual(state["lead_projection"], {},
                         "#rn-lead feed leaked into the live envelope")

    def test_negative_control_client_idle_serves_callouts_and_lead(self):
        self._patch(
            health={"mode": "client"},
            coach_payload=_directive_coach(),
            lc_payload=None,
        )
        self._patch_det(_directive_det())
        state = _state_builder.build_state()
        self.assertEqual(len(state["callouts"]), 3)
        self.assertEqual(state["lead_projection"].get("state"), "ahead")

    def test_negative_control_client_idle_serves_imperatives(self):
        """Not in a game: coaching is allowed and MUST still flow, otherwise
        the live assertions above are vacuous."""
        self._patch(
            health={"mode": "client"},
            coach_payload=_directive_coach(),
            lc_payload=None,
        )
        coach = _state_builder.build_state()["coach"]
        self.assertEqual(coach.get("action"), "ALL-IN NOW")
        self.assertEqual(len(coach.get("choices") or []), 2)


if __name__ == "__main__":
    unittest.main()
