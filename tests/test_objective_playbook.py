# Tests for core/objective_playbook.py - the RC2 P5.5 (WS3) deterministic
# objective playbook callout. Joins the objective schedule (event_callouts) with
# the macro lead read (lead_projection) into ONE kind="playbook" directive row.
#
# Covers: the (objective x lead-state) truth table, elder wildcard, soonest
# covered-objective selection (plates/spikes skipped), phase gating
# (baron mid/late, elder late), CV upgrades (enemy dead -> free; >=3 missing ->
# contest) and their near-window gate, eta passthrough, fail-soft on garbage,
# callout shape, the <=12-word line budget, and ASCII hygiene.
from __future__ import annotations

import unittest
from pathlib import Path

import core.objective_playbook as op

_ROOT = Path(__file__).resolve().parent.parent


def _co(tag: str, eta_s: float) -> dict:
    """Minimal objective callout row as next_callouts emits it."""
    return {"tag": tag, "line": f"{tag} line", "eta_s": eta_s, "kind": "objective"}


class TruthTableTests(unittest.TestCase):
    def test_dragon_ahead(self) -> None:
        out = op.playbook_callout([_co("dragon", 30.0)], {"state": "ahead"}, None, "mid")
        self.assertIsNotNone(out)
        self.assertEqual(out["kind"], "playbook")
        self.assertEqual(out["tag"], "playbook_dragon")
        self.assertEqual(out["eta_s"], 30.0)  # objective eta passthrough
        self.assertTrue(out["line"].startswith("Drake"))

    def test_dragon_even_and_behind_differ(self) -> None:
        even = op.playbook_callout([_co("dragon", 40.0)], {"state": "even"}, None, "mid")
        behind = op.playbook_callout([_co("dragon", 40.0)], {"state": "behind"}, None, "mid")
        self.assertNotEqual(even["line"], behind["line"])

    def test_herald_any_phase(self) -> None:
        out = op.playbook_callout([_co("herald", 20.0)], {"state": "ahead"}, None, "early")
        self.assertIsNotNone(out)
        self.assertEqual(out["tag"], "playbook_herald")
        self.assertTrue(out["line"].startswith("Herald"))

    def test_baron_gated_to_mid_late(self) -> None:
        early = op.playbook_callout([_co("baron", 60.0)], {"state": "even"}, None, "early")
        self.assertIsNone(early)  # baron not contestable early -> no row
        mid = op.playbook_callout([_co("baron", 60.0)], {"state": "even"}, None, "mid")
        self.assertIsNotNone(mid)
        self.assertEqual(mid["tag"], "playbook_baron")

    def test_elder_late_only_and_wildcard_state(self) -> None:
        not_late = op.playbook_callout([_co("elder", 50.0)], {"state": "behind"}, None, "mid")
        self.assertIsNone(not_late)
        late = op.playbook_callout([_co("elder", 50.0)], {"state": "behind"}, None, "late")
        self.assertIsNotNone(late)
        self.assertEqual(late["tag"], "playbook_elder")
        self.assertTrue(late["line"].startswith("Elder"))


class SelectionTests(unittest.TestCase):
    def test_soonest_covered_objective_wins_plates_skipped(self) -> None:
        callouts = [_co("plates", 10.0), _co("dragon", 50.0), _co("baron", 100.0)]
        out = op.playbook_callout(callouts, {"state": "even"}, None, "mid")
        self.assertEqual(out["tag"], "playbook_dragon")  # plates uncovered

    def test_skips_phase_gated_to_next_covered(self) -> None:
        # Elder first but phase mid (elder is late-only) -> fall through to dragon.
        callouts = [_co("elder", 20.0), _co("dragon", 80.0)]
        out = op.playbook_callout(callouts, {"state": "ahead"}, None, "mid")
        self.assertEqual(out["tag"], "playbook_dragon")

    def test_only_spikes_no_objective_returns_none(self) -> None:
        callouts = [
            {"tag": "lvl6", "line": "x", "eta_s": 0.0, "kind": "level_spike"},
            {"tag": "item1", "line": "x", "eta_s": None, "kind": "item_spike"},
        ]
        self.assertIsNone(op.playbook_callout(callouts, {"state": "ahead"}, None, "mid"))


class CvUpgradeTests(unittest.TestCase):
    def test_enemy_dead_ahead_near_free_objective(self) -> None:
        vs = {"visible_count": 4, "missing_count": 0, "dead_count": 1, "total": 5}
        out = op.playbook_callout([_co("dragon", 25.0)], {"state": "ahead"}, vs, "mid")
        self.assertIn("free", out["line"].lower())
        self.assertIn("take it now", out["line"].lower())

    def test_dead_upgrade_requires_ahead(self) -> None:
        vs = {"dead_count": 1, "missing_count": 0}
        out = op.playbook_callout([_co("dragon", 25.0)], {"state": "even"}, vs, "mid")
        self.assertNotIn("free", out["line"].lower())  # even -> base line, no free upgrade

    def test_dead_upgrade_requires_near(self) -> None:
        vs = {"dead_count": 1, "missing_count": 0}
        out = op.playbook_callout([_co("dragon", 400.0)], {"state": "ahead"}, vs, "mid")
        self.assertNotIn("free", out["line"].lower())  # far objective -> no CV upgrade

    def test_missing_three_near_contest(self) -> None:
        vs = {"visible_count": 1, "missing_count": 3, "dead_count": 0, "total": 5}
        out = op.playbook_callout([_co("dragon", 30.0)], {"state": "even"}, vs, "mid")
        self.assertIn("contest", out["line"].lower())

    def test_missing_below_threshold_keeps_base(self) -> None:
        vs = {"missing_count": 2, "dead_count": 0}
        out = op.playbook_callout([_co("dragon", 30.0)], {"state": "even"}, vs, "mid")
        self.assertNotIn("missing", out["line"].lower())

    def test_dead_takes_precedence_over_missing(self) -> None:
        vs = {"dead_count": 1, "missing_count": 3}
        out = op.playbook_callout([_co("dragon", 20.0)], {"state": "ahead"}, vs, "mid")
        self.assertIn("free", out["line"].lower())


class FailSoftTests(unittest.TestCase):
    def test_empty_callouts(self) -> None:
        self.assertIsNone(op.playbook_callout([], {"state": "ahead"}, None, "mid"))

    def test_non_list_callouts(self) -> None:
        self.assertIsNone(op.playbook_callout(None, {"state": "ahead"}, None, "mid"))
        self.assertIsNone(op.playbook_callout("nope", {"state": "ahead"}, None, "mid"))

    def test_non_dict_lead_defaults_even(self) -> None:
        out = op.playbook_callout([_co("dragon", 30.0)], None, None, "mid")
        even = op.playbook_callout([_co("dragon", 30.0)], {"state": "even"}, None, "mid")
        self.assertEqual(out["line"], even["line"])

    def test_unknown_state_defaults_even(self) -> None:
        out = op.playbook_callout([_co("dragon", 30.0)], {"state": "winning"}, None, "mid")
        even = op.playbook_callout([_co("dragon", 30.0)], {"state": "even"}, None, "mid")
        self.assertEqual(out["line"], even["line"])

    def test_garbage_callout_entries_skipped(self) -> None:
        callouts = ["bad", 7, None, {"no_tag": 1}, _co("dragon", 30.0)]
        out = op.playbook_callout(callouts, {"state": "ahead"}, None, "mid")
        self.assertEqual(out["tag"], "playbook_dragon")

    def test_bad_vision_summary_ignored(self) -> None:
        out = op.playbook_callout([_co("dragon", 20.0)], {"state": "ahead"}, "garbage", "mid")
        self.assertIsNotNone(out)  # bad vision -> base line, never raises
        self.assertNotIn("free", out["line"].lower())

    def test_never_raises_on_total_garbage(self) -> None:
        try:
            op.playbook_callout(object(), object(), object(), object())
        except Exception as exc:  # noqa: BLE001
            self.fail(f"playbook_callout raised: {exc!r}")


class LineBudgetAndAsciiTests(unittest.TestCase):
    def test_all_table_lines_within_word_budget(self) -> None:
        for key, line in op.OBJECTIVE_PLAYBOOK.items():
            self.assertLessEqual(len(line.split()), 12, f"{key}: {line!r}")

    def test_all_lines_ascii(self) -> None:
        for key, line in op.OBJECTIVE_PLAYBOOK.items():
            self.assertTrue(line.isascii(), f"{key}: {line!r}")

    def test_source_file_ascii_no_banned_glyphs(self) -> None:
        src = (_ROOT / "core" / "objective_playbook.py").read_text(encoding="utf-8")
        # Code-point ints so THIS test file stays ASCII-clean: em-dash,
        # en-dash, smart quotes (the 6 repo-banned glyphs).
        for cp in (0x2014, 0x2013, 0x2018, 0x2019, 0x201C, 0x201D):
            self.assertNotIn(chr(cp), src)


if __name__ == "__main__":
    unittest.main()
