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
