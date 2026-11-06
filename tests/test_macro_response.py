# Tests for core/macro_response.py - the RC2 P5.7 (WS4) deterministic
# lost-objective + stagnation macro response. Off Live Client objective-kill
# events + the macro lead read, NOT a Claude call.
#
# Covers: lost-objective detection (enemy kill within the loss window, the
# (name x lead-state) truth table + the baron/herald wildcard), the recency +
# killer-team + window gates, stagnation gating (game-time floor, state-stable
# window, recent-objective veto, inhib-down veto) and its 3 lead-keyed lines,
# lost-takes-precedence-over-stagnation, the callout shape, the <=12-word line
# budget, ASCII hygiene, and fail-soft on garbage.
from __future__ import annotations

import unittest
from pathlib import Path

import core.macro_response as mr

_ROOT = Path(__file__).resolve().parent.parent


def _oe(name: str, killer_team: str, down_at_s: float) -> dict:
    """Minimal objective-kill event as _liveclient surfaces it."""
    return {"name": name, "killer_team": killer_team, "down_at_s": down_at_s}


class LostObjectiveTests(unittest.TestCase):
    def test_enemy_dragon_recent_behind(self) -> None:
        # Enemy took drake 10s ago, we are behind -> the defend/scale line.
        line = mr.lost_objective_response(
            [_oe("dragon", "enemy", 600.0)], {"state": "behind"}, 610.0)
        self.assertIsNotNone(line)
        self.assertIn("drake", line.lower())

    def test_dragon_ahead_even_behind_differ(self) -> None:
        evs = [_oe("dragon", "enemy", 600.0)]
        ahead = mr.lost_objective_response(evs, {"state": "ahead"}, 610.0)
        even = mr.lost_objective_response(evs, {"state": "even"}, 610.0)
        behind = mr.lost_objective_response(evs, {"state": "behind"}, 610.0)
        self.assertEqual(len({ahead, even, behind}), 3)

    def test_baron_uses_wildcard_any_state(self) -> None:
        evs = [_oe("baron", "enemy", 1300.0)]
        a = mr.lost_objective_response(evs, {"state": "ahead"}, 1310.0)
        b = mr.lost_objective_response(evs, {"state": "behind"}, 1310.0)
        self.assertEqual(a, b)  # baron is "*" - same line regardless of lead
        self.assertIn("baron", a.lower())

    def test_herald_wildcard(self) -> None:
        line = mr.lost_objective_response(
            [_oe("herald", "enemy", 800.0)], {"state": "even"}, 820.0)
        self.assertIn("herald", line.lower())

    def test_ally_kill_is_not_a_loss(self) -> None:
        # We took the dragon ourselves -> no lost-objective response.
        self.assertIsNone(mr.lost_objective_response(
            [_oe("dragon", "ally", 600.0)], {"state": "even"}, 610.0))

    def test_outside_loss_window_ignored(self) -> None:
        # Enemy drake 90s ago is past the ~45s loss window.
        self.assertIsNone(mr.lost_objective_response(
            [_oe("dragon", "enemy", 500.0)], {"state": "behind"}, 590.0))

    def test_future_event_ignored(self) -> None:
        # down_at_s after game_time_s (clock skew) is not a past loss.
        self.assertIsNone(mr.lost_objective_response(
            [_oe("dragon", "enemy", 700.0)], {"state": "behind"}, 610.0))

    def test_most_recent_qualifying_event_wins(self) -> None:
        evs = [_oe("dragon", "enemy", 600.0), _oe("baron", "enemy", 615.0)]
        line = mr.lost_objective_response(evs, {"state": "behind"}, 620.0)
        self.assertIn("baron", line.lower())  # baron is the more recent loss

    def test_unknown_killer_team_ignored(self) -> None:
        self.assertIsNone(mr.lost_objective_response(
            [_oe("dragon", "unknown", 600.0)], {"state": "behind"}, 610.0))


class StagnationTests(unittest.TestCase):
    def _stagnant_inputs(self, state: str = "even") -> dict:
        return dict(objective_events=[], lead={"state": state},
                    game_time_s=1400.0, inhib_events=[], stable_for_s=200.0)

    def test_fires_when_all_gates_met(self) -> None:
        line = mr.stagnation_response(**self._stagnant_inputs())
        self.assertIsNotNone(line)
        self.assertIn("stalled", line.lower())

    def test_three_lead_lines_differ(self) -> None:
        lines = {
            mr.stagnation_response(**self._stagnant_inputs(s))
            for s in ("ahead", "even", "behind")
        }
        self.assertEqual(len(lines), 3)

    def test_blocked_before_game_time_floor(self) -> None:
        kw = self._stagnant_inputs()
        kw["game_time_s"] = 600.0  # < 20 min
        self.assertIsNone(mr.stagnation_response(**kw))

    def test_blocked_when_not_stable_long_enough(self) -> None:
        kw = self._stagnant_inputs()
        kw["stable_for_s"] = 30.0  # lead only just settled
        self.assertIsNone(mr.stagnation_response(**kw))

    def test_blocked_by_recent_objective(self) -> None:
        kw = self._stagnant_inputs()
        kw["objective_events"] = [_oe("dragon", "ally", 1380.0)]  # 20s ago
        self.assertIsNone(mr.stagnation_response(**kw))

    def test_old_objective_does_not_block(self) -> None:
        kw = self._stagnant_inputs()
        kw["objective_events"] = [_oe("dragon", "ally", 1000.0)]  # 400s ago
        self.assertIsNotNone(mr.stagnation_response(**kw))

    def test_blocked_by_inhib_down(self) -> None:
        kw = self._stagnant_inputs()
        kw["inhib_events"] = [{"down_at_s": 1300.0, "name": "Inhib"}]  # within 300s
        self.assertIsNone(mr.stagnation_response(**kw))

    def test_respawned_inhib_does_not_block(self) -> None:
        kw = self._stagnant_inputs()
        kw["inhib_events"] = [{"down_at_s": 1000.0, "name": "Inhib"}]  # 400s ago
        self.assertIsNotNone(mr.stagnation_response(**kw))

    def test_default_stable_for_s_does_not_fire(self) -> None:
        # No memory supplied (stable_for_s default 0) -> never a false stall.
        self.assertIsNone(mr.stagnation_response(
            [], {"state": "even"}, 1400.0, []))


class CalloutTests(unittest.TestCase):
    def test_lost_objective_callout_shape(self) -> None:
        out = mr.macro_response_callout(
            [_oe("baron", "enemy", 1300.0)], {"state": "behind"}, 1310.0, [])
        self.assertEqual(out["kind"], "macro_response")
        self.assertEqual(out["tag"], "macro_lost_objective")
        self.assertIsNone(out["eta_s"])
        self.assertIn("baron", out["line"].lower())

    def test_stagnation_callout_shape(self) -> None:
        out = mr.macro_response_callout(
            [], {"state": "even"}, 1400.0, [], stable_for_s=200.0)
        self.assertEqual(out["kind"], "macro_response")
        self.assertEqual(out["tag"], "macro_stagnation")
        self.assertIsNone(out["eta_s"])

    def test_lost_objective_takes_precedence(self) -> None:
        # Both could fire (a fresh loss AND a long stall); the concrete loss wins.
        out = mr.macro_response_callout(
            [_oe("baron", "enemy", 1390.0)], {"state": "even"}, 1400.0, [],
            stable_for_s=200.0)
        self.assertEqual(out["tag"], "macro_lost_objective")

    def test_none_when_nothing_fires(self) -> None:
        self.assertIsNone(mr.macro_response_callout(
            [], {"state": "even"}, 300.0, []))


class FailSoftTests(unittest.TestCase):
    def test_non_list_events(self) -> None:
        self.assertIsNone(mr.lost_objective_response(None, {"state": "behind"}, 610.0))
        self.assertIsNone(mr.lost_objective_response("nope", {"state": "behind"}, 610.0))

    def test_garbage_event_entries_skipped(self) -> None:
        evs = ["bad", 7, None, {"no_name": 1}, _oe("dragon", "enemy", 600.0)]
        line = mr.lost_objective_response(evs, {"state": "behind"}, 610.0)
        self.assertIn("drake", line.lower())

    def test_non_dict_lead_defaults_even(self) -> None:
        out = mr.macro_response_callout([], None, 1400.0, [], stable_for_s=200.0)
        even = mr.macro_response_callout([], {"state": "even"}, 1400.0, [],
                                         stable_for_s=200.0)
        self.assertEqual(out["line"], even["line"])

    def test_bad_game_time_no_raise(self) -> None:
        self.assertIsNone(mr.lost_objective_response(
            [_oe("dragon", "enemy", 600.0)], {"state": "behind"}, "soon"))

    def test_never_raises_on_total_garbage(self) -> None:
        try:
            mr.macro_response_callout(object(), object(), object(), object())
        except Exception as exc:  # noqa: BLE001
            self.fail(f"macro_response_callout raised: {exc!r}")


class JunkInputHardeningTests(unittest.TestCase):
    """s144 true-audit (RM-1953..RM-1957): junk input never fires a row it
    should not, and one junk entry never hides a real one."""

    _NAN = float("nan")
    _INF = float("inf")

    def _stall(self, **over: object) -> dict:
        kw: dict = dict(objective_events=[], lead={"state": "even"},
                        game_time_s=1400.0, inhib_events=[], stable_for_s=200.0)
        kw.update(over)
        return kw

    # RM-1953: a non-finite game time is not a time.
    def test_nan_game_time_fires_no_lost_objective(self) -> None:
        # The event is 900 s old at any real time; NaN made every window
        # compare False, so it read as a FRESH loss.
        self.assertIsNone(mr.lost_objective_response(
            [_oe("dragon", "enemy", 500.0)], {"state": "behind"}, self._NAN))

    def test_non_finite_game_time_fires_no_stall(self) -> None:
        for gt in (self._NAN, self._INF, "nan", "inf"):
            with self.subTest(gt=gt):
                self.assertIsNone(mr.stagnation_response(
                    **self._stall(game_time_s=gt)))
                self.assertIsNone(mr.macro_response_callout(
                    **self._stall(game_time_s=gt)))

    # RM-1954: a non-finite or junk stall duration is not a duration.
    def test_non_finite_stable_for_s_fires_no_stall(self) -> None:
        for st in (self._NAN, self._INF, "nan"):
            with self.subTest(st=st):
                self.assertIsNone(mr.stagnation_response(
                    **self._stall(stable_for_s=st)))

    def test_numeric_string_stable_for_s_reads_like_game_time(self) -> None:
        # game_time_s already accepts a numeric string; stable_for_s parsed
        # it, then compared the RAW str and raised (masked to None).
        self.assertEqual(
            mr.stagnation_response(**self._stall(stable_for_s="200")),
            mr.stagnation_response(**self._stall()))
        self.assertIsNone(mr.stagnation_response(**self._stall(stable_for_s="30")))

    # RM-1955: one unhashable event name must not hide a real loss.
    def test_unhashable_name_entry_does_not_hide_real_loss(self) -> None:
        for junk in ([], {}, ["dragon"]):
            with self.subTest(junk=junk):
                evs = [{"name": junk, "killer_team": "enemy", "down_at_s": 605.0},
                       _oe("baron", "enemy", 600.0)]
                line = mr.lost_objective_response(evs, {"state": "even"}, 610.0)
                self.assertIsNotNone(line)
                self.assertIn("baron", line.lower())

    # RM-1956: one over-long int time must not hide a real loss or stall.
    def test_overflowing_int_time_entry_is_skipped(self) -> None:
        huge = 10 ** 400
        evs = [_oe("dragon", "enemy", huge), _oe("baron", "enemy", 600.0)]
        line = mr.lost_objective_response(evs, {"state": "even"}, 610.0)
        self.assertIsNotNone(line)
        self.assertIn("baron", line.lower())
        self.assertIsNotNone(mr.stagnation_response(**self._stall(
            objective_events=[_oe("dragon", "ally", huge)],
            inhib_events=[{"down_at_s": huge}])))

    def test_overflowing_int_game_time_is_no_row(self) -> None:
        self.assertIsNone(mr.macro_response_callout(
            [_oe("baron", "enemy", 600.0)], {"state": "even"}, 10 ** 400, [],
            stable_for_s=200.0))

    def test_non_finite_event_time_is_skipped(self) -> None:
        evs = [_oe("baron", "enemy", self._NAN), _oe("dragon", "enemy", 600.0)]
        line = mr.lost_objective_response(evs, {"state": "behind"}, 610.0)
        self.assertIn("drake", line.lower())
        # An event with a NaN time is not evidence of a recent objective.
        self.assertIsNotNone(mr.stagnation_response(**self._stall(
            objective_events=[_oe("dragon", "ally", self._NAN)])))

    # RM-1957: "no event data" (None, RM-308(b)) is not "nothing taken".
    def test_missing_event_data_is_not_a_stall(self) -> None:
        for oe in (None, "x", {"name": "dragon"}):
            with self.subTest(objective_events=oe):
                self.assertIsNone(mr.stagnation_response(
                    **self._stall(objective_events=oe)))

    def test_missing_inhib_list_is_no_inhib_down(self) -> None:
        # The resolver drops an EMPTY inhib list (_build_game_state), so a
        # missing inhib_events is the normal "nothing has fallen" game and
        # must still allow the stall nudge (verifier catch, s144t165).
        for ie in (None, "x"):
            with self.subTest(inhib_events=ie):
                self.assertIsNotNone(mr.stagnation_response(
                    **self._stall(inhib_events=ie)))

    def test_stall_fires_through_the_live_resolver_shape(self) -> None:
        import dashboard._deterministic_coaching as dc
        lc = {"champion": "Aatrox", "inhib_events": [], "objective_events": []}
        gs = dc._build_game_state({"champion": "Aatrox"}, lc, "sr")
        out = mr.macro_response_callout(
            gs.get("objective_events"), {"state": "even"}, 1400.0,
            gs.get("inhib_events"), stable_for_s=200.0)
        self.assertIsNotNone(out)
        self.assertEqual(out["tag"], "macro_stagnation")
        # No event data at all (key absent) -> no stall claim.
        gs2 = dc._build_game_state({"champion": "Aatrox"},
                                   {"champion": "Aatrox"}, "sr")
        self.assertIsNone(mr.macro_response_callout(
            gs2.get("objective_events"), {"state": "even"}, 1400.0,
            gs2.get("inhib_events"), stable_for_s=200.0))

    def test_missing_inhib_data_still_coaches_a_fresh_loss(self) -> None:
        # The lost-objective half never read inhib_events; keep it that way.
        out = mr.macro_response_callout(
            [_oe("baron", "enemy", 1390.0)], {"state": "even"}, 1400.0, None,
            stable_for_s=200.0)
        self.assertEqual(out["tag"], "macro_lost_objective")


class LineBudgetAndAsciiTests(unittest.TestCase):
    def test_all_table_lines_within_word_budget(self) -> None:
        for line in mr.LOST_OBJECTIVE_RESPONSE.values():
            self.assertLessEqual(len(line.split()), 12, line)
        for line in mr.STAGNATION_RESPONSE.values():
            self.assertLessEqual(len(line.split()), 12, line)

    def test_all_lines_ascii(self) -> None:
        for line in (*mr.LOST_OBJECTIVE_RESPONSE.values(),
                     *mr.STAGNATION_RESPONSE.values()):
            self.assertTrue(line.isascii(), line)

    def test_source_file_ascii_no_banned_glyphs(self) -> None:
        src = (_ROOT / "core" / "macro_response.py").read_text(encoding="utf-8")
        for cp in (0x2014, 0x2013, 0x2018, 0x2019, 0x201C, 0x201D):
            self.assertNotIn(chr(cp), src)


if __name__ == "__main__":
    unittest.main()
