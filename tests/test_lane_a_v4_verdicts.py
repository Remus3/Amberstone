"""Tests for the Lane A v4 verdict extension (item-state axis + cooldown-window
+ spike-timing blocks) in core.laning_scenario_precompute and its reader
core.precomputed_laning_coach.

Per the data-fragile rule (CLAUDE.md Testing Discipline) these assert ORDINAL /
INVARIANT properties, never exact damage numbers. The engine-backed cases load
a single shared DataSnapshot (mirrors tests/test_laning_scenario_precompute.py).
The characterization cases pin a cell field to the SAME live substrate call for
the same inputs (both deterministic). scenario_matrix.check_invariants is reused
where it applies (the no-NaN / no-negative / non-decreasing-in-level sweep).
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import core.laning_scenario_precompute as lsp  # noqa: E402
import core.precomputed_laning_coach as plc  # noqa: E402

# A small monotonic tolerance for the ordinal float invariants (the leaf
# scalars are 4-dp rounded; an item bonus can be a hair below the prior point
# due to rounding without being a real ordering break).
_MONO_EPS = 1e-3


class PureClassifierTests(unittest.TestCase):
    """The two NEW pure verdict classifiers + the item-state helpers - no
    engine, no snapshot (mirrors the existing laning_band pure-helper shape)."""

    def test_cc_threat_verdict_no_ult_is_wait_cd(self) -> None:
        # MY ult down (the no_ult axis) -> wait for the cooldown regardless of
        # the enemy numbers.
        self.assertEqual(lsp.cc_threat_verdict(12.0, 0.0, "no_ult"), "wait_cd")
        self.assertEqual(lsp.cc_threat_verdict(0.0, 130.0, "no_ult"), "wait_cd")

    def test_cc_threat_verdict_punish_when_ult_up_and_enemy_threat(self) -> None:
        # Ult up + enemy has a real threat spell on a finite cd -> punish.
        self.assertEqual(lsp.cc_threat_verdict(14.0, 130.0, "all_up"), "punish_now")

    def test_cc_threat_verdict_even_when_no_enemy_threat(self) -> None:
        # Ult up but enemy has no registered CC (enemy_cc_s 0) -> even.
        self.assertEqual(lsp.cc_threat_verdict(0.0, 130.0, "all_up"), "even")

    def test_cc_threat_verdict_failsoft_even_on_bad_input(self) -> None:
        self.assertEqual(lsp.cc_threat_verdict("x", "y", "all_up"), "even")

    def test_spike_verdict_spike_up_at_ult_band(self) -> None:
        # L6+ is the R-unlock band -> spike_up even itemless.
        self.assertEqual(lsp.spike_verdict("item", 1, "L6", "none"), "spike_up")
        self.assertEqual(lsp.spike_verdict("item", 2, "L11", "none"), "spike_up")

    def test_spike_verdict_spike_up_when_has_item(self) -> None:
        # An item-state past none is itself a power step.
        self.assertEqual(lsp.spike_verdict("level", 6, "L2", "one_item"), "spike_up")

    def test_spike_verdict_play_for_spike_pre_six_itemless(self) -> None:
        # L2 itemless with a next marker -> play_for_spike.
        self.assertEqual(lsp.spike_verdict("level", 6, "L2", "none"), "play_for_spike")

    def test_spike_verdict_even_when_no_next_marker(self) -> None:
        # No next marker (everything crossed) at a non-spike cell -> even.
        self.assertEqual(lsp.spike_verdict("", 0, "L2", "none"), "even")

    def test_item_states_for_band_prune(self) -> None:
        self.assertEqual(lsp.item_states_for_band("L2"), ("none",))
        self.assertEqual(lsp.item_states_for_band("L6"), ("none", "one_item"))
        self.assertEqual(
            lsp.item_states_for_band("L11"), ("none", "one_item", "two_item")
        )

    def test_item_states_for_band_unknown_full_ladder(self) -> None:
        self.assertEqual(lsp.item_states_for_band("L16"), lsp.ITEM_STATES)

    def test_item_state_for_count(self) -> None:
        self.assertEqual(plc.item_state_for(None), "none")
        self.assertEqual(plc.item_state_for(0), "none")
        self.assertEqual(plc.item_state_for(1), "one_item")
        self.assertEqual(plc.item_state_for(2), "two_item")
        self.assertEqual(plc.item_state_for(5), "two_item")
        self.assertEqual(plc.item_state_for("bad"), "none")

    def test_build_for_item_state_none_is_itemless(self) -> None:
        # none is always () without touching the build table.
        self.assertEqual(lsp.build_for_item_state("Annie", "none", "SR"), ())

    def test_build_for_item_state_unknown_champ_failsoft(self) -> None:
        self.assertEqual(
            lsp.build_for_item_state("NotARealChampion", "one_item", "SR"), ()
        )


class PersistRoundTripV4Tests(unittest.TestCase):
    """atomic_write round-trips the v4 blocks ASCII; the reader degrades a v3
    payload to trade+recall chips with NO new chip (no engine)."""

    def _v4_cell(self) -> dict:
        return {
            "verdict": "trade", "net_swing": 0.2, "pct_my_removed": 0.1,
            "pct_enemy_removed": 0.3, "kill_threshold_met": False,
            "economy": {"recall": "hold", "next_spike": "first_item",
                        "gold_at_band": 1000.0},
            "cc_threat": {"enemy_threat_spell": "Q", "enemy_cc_s": 1.5,
                          "my_ult_cd_s": 100.0,
                          "threat_verdict": "punish_now"},
            "spike_timing": {"next_kind": "level", "next_threshold": 6,
                             "next_label": "R unlock", "crossed_dps_at": 20.0,
                             "spike_verdict": "play_for_spike"},
        }

    def _v4_payload(self) -> dict:
        return {
            "version": "16.13.1", "generated_at": "2026-06-29T00:00:00Z",
            "mode": "sr", "schema": "laning_scenarios/v4",
            "dimensions": {"item_states": list(lsp.ITEM_STATES)},
            "scenarios": {"Annie": {"Ahri": {"L6": {"full": {"all_up": {
                "one_item": self._v4_cell(),
            }}}}}},
        }

    def test_atomic_write_roundtrip_v4_blocks_ascii(self) -> None:
        payload = self._v4_payload()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "laning_scenarios_sr.json"
            lsp.atomic_write(payload, out)
            raw = out.read_bytes()
            raw.decode("ascii")  # raises if any non-ASCII byte slipped in
            back = json.loads(raw.decode("utf-8"))
        self.assertEqual(back, payload)
        cell = lsp.lookup(back, "Annie", "Ahri", "L6", "full", "all_up", "one_item")
        self.assertEqual(cell["cc_threat"]["threat_verdict"], "punish_now")
        self.assertEqual(cell["spike_timing"]["spike_verdict"], "play_for_spike")
        self.assertIn("kill_threshold_met", cell)

    def test_reader_v4_emits_additive_chip(self) -> None:
        # A covered v4 cell with an actionable threat_verdict yields the
        # additive C chip on top of the A/B trade chips.
        payload = self._v4_payload()
        choices = plc.precomputed_choices(
            "Annie", "Ahri", 6, mana_fraction=1.0, ult_up=True,
            mode="sr", payload=payload, item_count=1,
        )
        keys = [c.key for c in choices]
        self.assertEqual(keys[:2], ["A", "B"])
        self.assertIn("C", keys)

    def test_reader_v3_payload_no_new_chip_no_raise(self) -> None:
        # A v3 payload (no cc_threat / spike_timing; cd node IS the leaf)
        # read by the v4 reader yields the trade+recall chips and NO new chip,
        # and does NOT raise (spec 6.1 / 7.3 back-compat).
        v3cell = {
            "verdict": "trade", "net_swing": 0.2, "pct_my_removed": 0.1,
            "pct_enemy_removed": 0.3,
            "economy": {"recall": "recall_now", "next_spike": "first_item",
                        "gold_at_band": 1200.0},
        }
        v3pay = {
            "version": "16.13.1", "mode": "sr", "schema": "laning_scenarios/v3",
            "scenarios": {"Annie": {"Ahri": {"L6": {"full": {"all_up": v3cell}}}}},
        }
        choices = plc.precomputed_choices(
            "Annie", "Ahri", 6, mana_fraction=1.0, ult_up=True,
            mode="sr", payload=v3pay, item_count=1,
            next_item=("Some Item", 1300),
        )
        keys = [c.key for c in choices]
        self.assertEqual(keys, ["A", "B"])
        # The recall economy drove the B chip (recall_now), proving the recall
        # path still fires from a v3 cell.
        self.assertEqual(choices[1].label, "Recall now")

    def test_reader_6key_descends_to_none_when_item_state_absent(self) -> None:
        # The 6-key lookup descends to the item_state-none cell when the
        # requested item_state is absent (spec 7.3), so the reader still emits
        # chips rather than [].
        none_cell = {
            "verdict": "even", "net_swing": 0.0, "pct_my_removed": 0.1,
            "pct_enemy_removed": 0.1, "kill_threshold_met": False,
            "economy": {"recall": "hold", "next_spike": "first_item",
                        "gold_at_band": 800.0},
        }
        pay = {
            "version": "16.13.1", "mode": "sr", "schema": "laning_scenarios/v4",
            "scenarios": {"Annie": {"Ahri": {"L11": {"full": {"all_up": {
                "none": none_cell,
            }}}}}},
        }
        # item_count=2 -> two_item requested, only none present.
        choices = plc.precomputed_choices(
            "Annie", "Ahri", 11, mana_fraction=1.0, ult_up=True,
            mode="sr", payload=pay, item_count=2,
        )
        self.assertTrue(choices)  # not [] - descended to the none cell
        self.assertEqual(choices[0].key, "A")


class EngineV4CharacterizationTests(unittest.TestCase):
    """Cell fields equal the live substrate call (characterization) + ordinal
    invariants over real engine output."""

    @classmethod
    def setUpClass(cls) -> None:
        from agents.daemon_slayer.data_loader import DataSnapshot
        cls.snap = DataSnapshot.load()

    # --- 7.1 characterization (cell == live substrate call) ------------------
    def test_cc_threat_cell_matches_substrate(self) -> None:
        # Riot compliance 2026-08-11: the substrate is the per-spell CC registry,
        # not the deleted cooldown_watch join. There is no enemy cooldown to
        # characterize any more - only the threat spell + its CC duration.
        cell = lsp.compute_cell(
            self.snap, "Annie", "Ahri", "L6", "full", "all_up",
            mode="SR", item_state="one_item",
        )
        ref = lsp._enemy_cc_threat_card("Ahri")
        self.assertNotIn("enemy_cd_s", cell["cc_threat"])
        if ref:
            self.assertEqual(cell["cc_threat"]["enemy_cc_s"], ref.cc_duration_s)
            self.assertEqual(cell["cc_threat"]["enemy_threat_spell"], ref.spell_key)
        else:  # no enemy CC -> the block degrades to even / empty spell
            self.assertEqual(cell["cc_threat"]["enemy_threat_spell"], "")

    def test_spike_timing_next_threshold_matches_substrate(self) -> None:
        from agents.daemon_slayer.spike_markers import compute_spike_markers
        ids = lsp.build_for_item_state("Annie", "one_item", "SR")
        cell = lsp.compute_cell(
            self.snap, "Annie", "Ahri", "L6", "full", "all_up",
            mode="SR", item_state="one_item",
        )
        ref = compute_spike_markers(
            "Annie", lsp.level_for_band("L6"), list(ids), mode="SR",
            item_count_done=1,
        )
        if ref.next_marker is not None:
            self.assertEqual(
                cell["spike_timing"]["next_threshold"], ref.next_marker.threshold
            )
            self.assertEqual(
                cell["spike_timing"]["next_kind"], ref.next_marker.kind
            )

    def test_trade_fields_unperturbed_by_v4(self) -> None:
        # Regression guard: the v3 trade characterization still holds (v4 did
        # not perturb the trade numbers) - the itemless none cell equals a
        # full-rotation compute_matchup, exactly as the v3 test asserts.
        from agents.daemon_slayer.matchup import compute_matchup
        cell = lsp.compute_cell(
            self.snap, "Garen", "Darius", "L6", "full", "all_up",
            mode="SR", item_state="none",
        )
        ref = compute_matchup(
            self.snap, "Garen", "Darius", 6, 6, mode="SR",
            sequence_a=["Q", "W", "E", "R"], sequence_b=["Q", "W", "E", "R"],
        )
        self.assertEqual(cell["verdict"], ref.verdict)
        self.assertEqual(cell["net_swing"], lsp._round(ref.net_swing))

    # --- 7.2 ordinal / monotonic invariants ----------------------------------
    def test_all_in_gate_invariant_holds_over_sweep(self) -> None:
        # Two structural properties over every cell of a real sweep (data-safe,
        # no exact numbers, and non-vacuous via the constructed-result check
        # below regardless of whether an all_in materializes in these 1v1
        # laning inputs):
        #   1. verdict == "all_in" => kill_threshold_met AND
        #      pct_enemy_removed >= 1.0 AND pct_my_removed < 1.0 (the brief
        #      named invariant; pins matchup._classify's all-in gate).
        #   2. kill_threshold_met => pct_enemy_removed >= 1.0 (the explicit
        #      flag is never set without the kill threshold being met).
        payload = lsp.generate_table(
            self.snap, ["Annie", "Syndra", "Caitlyn"], ["Ahri", "Garen", "Malphite"],
            mode="SR", bands=["L6", "L11"],
        )
        for per_enemy in payload["scenarios"].values():
            for per_band in per_enemy.values():
                for per_mana in per_band.values():
                    for per_cd in per_mana.values():
                        for cell in per_cd.values():
                            for leaf in cell.values():
                                if leaf.get("verdict") == "all_in":
                                    self.assertTrue(leaf["kill_threshold_met"])
                                    self.assertGreaterEqual(
                                        leaf["pct_enemy_removed"], 1.0
                                    )
                                    self.assertLess(leaf["pct_my_removed"], 1.0)
                                if leaf.get("kill_threshold_met"):
                                    self.assertGreaterEqual(
                                        leaf["pct_enemy_removed"], 1.0
                                    )

    def test_kill_threshold_gate_logic_explicit(self) -> None:
        # Non-vacuous unit check of the exact _cell_from_result gate:
        # kill_threshold_met == (pct_b_removed >= 1.0 AND a_can_full_combo).
        # Constructed MatchupResults (deterministic, not data-dependent) so the
        # gate is asserted even though live laning cells never reach a 1-combo
        # kill at these inputs.
        from agents.daemon_slayer.matchup import MatchupResult

        def _mk(pct_b: float, a_full: bool) -> MatchupResult:
            return MatchupResult(
                champ_a="A", champ_b="B", level_a=6, level_b=6,
                dmg_a_to_b=0.0, dmg_b_to_a=0.0, a_hp_eff=1.0, b_hp_eff=1.0,
                pct_a_removed=0.2, pct_b_removed=pct_b, net_swing=0.0,
                verdict="trade", a_can_full_combo=a_full, b_can_full_combo=True,
                a_casts_allowed=4, b_casts_allowed=4,
            )

        self.assertTrue(lsp._cell_from_result(_mk(1.0, True))["kill_threshold_met"])
        self.assertFalse(lsp._cell_from_result(_mk(0.9, True))["kill_threshold_met"])
        self.assertFalse(lsp._cell_from_result(_mk(1.0, False))["kill_threshold_met"])

    def test_spike_crossed_dps_non_decreasing_in_item_state(self) -> None:
        # For fixed (my, enemy, band, mana, cd), spike_timing.crossed_dps_at is
        # non-decreasing as item-state goes none -> one_item -> two_item (more
        # items, more DPS). SKIP None points (a missing dps_at cannot prove an
        # ordering break - the scenario_matrix NaN-skip discipline, spec risk 7).
        payload = lsp.generate_table(
            self.snap, ["Caitlyn"], ["Garen"], mode="SR", bands=["L11"],
        )
        per_cd = payload["scenarios"]["Caitlyn"]["Garen"]["L11"]["full"]["all_up"]
        seq = [
            per_cd.get(s, {}).get("spike_timing", {}).get("crossed_dps_at")
            for s in ("none", "one_item", "two_item")
        ]
        seq = [v for v in seq if v is not None]
        for a, b in zip(seq, seq[1:]):
            self.assertGreaterEqual(b, a - _MONO_EPS)

    def test_net_swing_non_decreasing_in_my_item_state(self) -> None:
        # More of MY items -> net_swing does not drop (I out-trade harder).
        payload = lsp.generate_table(
            self.snap, ["Caitlyn"], ["Garen"], mode="SR", bands=["L11"],
        )
        per_cd = payload["scenarios"]["Caitlyn"]["Garen"]["L11"]["full"]["all_up"]
        seq = [
            per_cd[s]["net_swing"]
            for s in ("none", "one_item", "two_item") if s in per_cd
        ]
        for a, b in zip(seq, seq[1:]):
            self.assertGreaterEqual(b, a - _MONO_EPS)

    def test_mirror_symmetry_even_per_item_state(self) -> None:
        # A same-champ same-level same-cd same-item-state mirror at full mana ->
        # net_swing 0.0 + verdict "even" (the item-575 invariant must still hold
        # with item-state added on BOTH sides).
        for istate in ("none", "one_item"):
            cell = lsp.compute_cell(
                self.snap, "Annie", "Annie", "L6", "full", "all_up",
                mode="SR", item_state=istate,
            )
            self.assertEqual(cell["net_swing"], 0.0, f"{istate} mirror not 0")
            self.assertEqual(cell["verdict"], "even")

    def test_cc_threat_sanity(self) -> None:
        # enemy_cc_s >= 0 always; a no_ult cell reports a
        # wait_cd threat verdict (my ult is down by the axis definition). The
        # my_ult_cd_s>0 honesty: a champ with a resolvable R cd in the full
        # rotation reports a positive cooldown.
        cell = lsp.compute_cell(
            self.snap, "Annie", "Ahri", "L6", "full", "no_ult",
            mode="SR", item_state="none",
        )
        cw = cell["cc_threat"]
        self.assertNotIn("enemy_cd_s", cw)
        self.assertGreaterEqual(cw["enemy_cc_s"], 0.0)
        self.assertEqual(cw["threat_verdict"], "wait_cd")
        # Annie's R has a real cooldown -> my_ult_cd_s is positive.
        self.assertGreater(cw["my_ult_cd_s"], 0.0)

    # --- 7.2 substrate invariant sweep (reuse check_invariants) --------------
    def test_scenario_matrix_invariants_over_seed_sweep(self) -> None:
        # Validate the underlying substrate the new blocks read from: run
        # scenario_matrix.check_invariants over a burst sweep of the seed
        # champions at the generated bands/item-states and assert zero
        # no_nan / no_negative / value_non_decreasing_in_level violations.
        from agents.daemon_slayer.scenario_matrix import (
            check_invariants,
            sweep_scenarios,
        )
        levels = (lsp.level_for_band("L6"), lsp.level_for_band("L11"))
        # item_sets per the item-state ladder (itemless + 1 + 2 of the curated
        # build). Use Annie (AP) so the magic-MR invariant is also clean.
        item_sets = [
            list(lsp.build_for_item_state("Annie", s, "SR"))
            for s in ("none", "one_item", "two_item")
        ]
        cells = sweep_scenarios(
            "Annie", levels=levels, item_sets=item_sets,
            target_profiles=[(0.0, 0.0)], modes=("SR",), metric="burst",
            snapshot=self.snap,
        )
        violations = check_invariants(cells, ap_champions=["Annie"])
        named = {v.invariant for v in violations}
        self.assertNotIn("no_nan", named)
        self.assertNotIn("no_negative", named)
        self.assertNotIn("value_non_decreasing_in_level", named)


if __name__ == "__main__":
    unittest.main()
