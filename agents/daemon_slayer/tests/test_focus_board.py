"""Focus board (RM-841) - per-enemy TTK both ways, kill order, danger list.

Asserts COMPUTED quantities against the live snapshot rather than pinning
patch-fragile numbers: every TTK is recomputed in the test from the same
primitives the module composes (``matchup._defensive_stats``,
``dps.compute_dps``, ``ability_dps.compute_ability_dps``,
``ehp._aram_damage_taken``), and every cross-row claim is a direction (more
armour -> slower kill, one more ally -> faster kill), never a cross-item
magnitude.

Champions and item ids are resolved against the snapshot once
(``SnapshotFixtureTests``) so a drifted id fails loudly instead of turning
every other test vacuous.
"""

from __future__ import annotations

import json
import math
import unittest

from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.ehp import _aram_damage_taken
from agents.daemon_slayer.focus_board import (
    FocusBoard,
    FocusRow,
    compute_focus_board,
)
from agents.daemon_slayer.matchup import _defensive_stats

_LEVEL = 11

# Real SR item ids (verified against the snapshot by SnapshotFixtureTests).
_JINX = ("Jinx", _LEVEL, ("6672", "3031", "3006"))          # Kraken / IE / Zerks
_LUX_ME = ("Lux", _LEVEL, ("6655", "3089", "3020"))          # Luden / Rabadon / Sorcs
_THORNMAIL = "3075"

_COMP = (
    ("Malphite", _LEVEL, ("3075", "3068", "3047")),  # Thornmail / Sunfire / Steelcaps
    ("Lux", _LEVEL, ("6655", "3089", "3020")),       # Luden / Rabadon / Sorcs
    ("Zed", _LEVEL, ("3142", "3814", "3158")),       # Youmuu / EoN / Lucidity
    ("Leona", _LEVEL, ("3143", "3111")),             # Randuin / Mercs
    ("Darius", _LEVEL, ("3071", "3047", "3742")),    # Cleaver / Steelcaps / DMP
)
_ALLY = ("Orianna", _LEVEL, ("6655", "3020"))


def _sustained(snap, fighter, target, mode="SR", apply_mode_modifiers=False):
    """Recompute AA + ability DPS of ``fighter`` into ``target``'s defences."""
    cid, lvl, items = fighter
    t_cid, t_lvl, t_items = target
    armor, mr, hp, bonus = _defensive_stats(
        snap, t_cid, t_lvl, list(t_items), mode,
        apply_mode_modifiers=apply_mode_modifiers,
    )
    kw = dict(
        mode=mode, target_armor=armor, target_mr=mr, target_max_hp=hp,
        target_bonus_hp=bonus, apply_mode_modifiers=apply_mode_modifiers,
    )
    aa = compute_dps(snap, cid, lvl, list(items), **kw).weighted_dps
    ab = compute_ability_dps(snap, cid, lvl, list(items), **kw).total_ability_dps
    return aa, ab, hp


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _board(self, me, enemies, **kw) -> FocusBoard:
        return compute_focus_board(self.snap, me, enemies, **kw)

    def _row(self, board: FocusBoard, champion_id: str) -> FocusRow:
        for r in board.rows:
            if r.champion_id == champion_id:
                return r
        self.fail(f"no row for {champion_id}: {[r.champion_id for r in board.rows]}")


class SnapshotFixtureTests(_Base):
    def test_fixture_champions_and_items_resolve(self) -> None:
        fighters = (_JINX, _LUX_ME, _ALLY) + _COMP
        for cid, _lvl, items in fighters:
            with self.subTest(champion=cid):
                self.assertIn(cid, self.snap.champions)
                for iid in items:
                    self.assertIn(iid, self.snap.items, f"{cid} item {iid}")
        self.assertIn(_THORNMAIL, self.snap.items)


class TtkArithmeticTests(_Base):
    def test_my_ttk_is_effective_hp_over_sustained_dps(self) -> None:
        board = self._board(_JINX, _COMP[:1])
        row = self._row(board, "Malphite")
        aa, ab, hp = _sustained(self.snap, _JINX, _COMP[0])
        self.assertGreater(aa + ab, 0.0)
        # SR: no damage-taken multiplier, so effective HP is the resolved max HP.
        self.assertAlmostEqual(row.target_max_hp, hp, places=6)
        self.assertAlmostEqual(row.target_effective_hp, hp, places=6)
        self.assertAlmostEqual(row.my_dps, aa + ab, places=6)
        self.assertAlmostEqual(row.my_ttk_s, hp / (aa + ab), places=6)

    def test_their_ttk_on_me_is_my_effective_hp_over_their_dps(self) -> None:
        board = self._board(_JINX, _COMP[:1])
        row = self._row(board, "Malphite")
        aa, ab, my_hp = _sustained(self.snap, _COMP[0], _JINX)
        self.assertAlmostEqual(board.my_max_hp, my_hp, places=6)
        self.assertAlmostEqual(board.my_effective_hp, my_hp, places=6)
        self.assertAlmostEqual(row.their_dps_on_me, aa + ab, places=6)
        self.assertAlmostEqual(row.their_ttk_on_me_s, my_hp / (aa + ab), places=6)

    def test_focus_value_is_their_dps_over_team_ttk(self) -> None:
        board = self._board(_JINX, _COMP)
        for row in board.rows:
            with self.subTest(enemy=row.champion_id):
                self.assertAlmostEqual(
                    row.focus_value, row.their_dps_on_me / row.team_ttk_s, places=9,
                )


class AbilityDpsIncludedTests(_Base):
    def test_lux_my_dps_exceeds_auto_attack_dps(self) -> None:
        # compute_dps is auto-attack DPS only (dps.py docstring); a mage's
        # sustained damage must add ability DPS or mages rank wrong.
        board = self._board(_LUX_ME, _COMP[:1])
        row = self._row(board, "Malphite")
        aa, ab, _hp = _sustained(self.snap, _LUX_ME, _COMP[0])
        self.assertGreater(ab, 0.0)
        self.assertGreater(row.my_dps, aa)
        self.assertAlmostEqual(row.my_dps, aa + ab, places=6)


class ArmorRaisesTtkTests(_Base):
    def test_thornmail_raises_jinx_ttk_on_malphite(self) -> None:
        bare = self._board(_JINX, [("Malphite", _LEVEL, ())])
        armored = self._board(_JINX, [("Malphite", _LEVEL, (_THORNMAIL,))])
        t_bare = self._row(bare, "Malphite").my_ttk_s
        t_arm = self._row(armored, "Malphite").my_ttk_s
        self.assertTrue(math.isfinite(t_bare) and math.isfinite(t_arm))
        self.assertGreater(t_arm, t_bare)


class TeamTtkTests(_Base):
    def test_solo_team_ttk_equals_my_ttk(self) -> None:
        board = self._board(_JINX, _COMP)
        for row in board.rows:
            with self.subTest(enemy=row.champion_id):
                self.assertAlmostEqual(row.team_dps, row.my_dps, places=9)
                self.assertAlmostEqual(row.team_ttk_s, row.my_ttk_s, places=9)

    def test_adding_an_ally_lowers_team_ttk_below_my_ttk(self) -> None:
        board = self._board(_JINX, _COMP, allies=[_ALLY])
        self.assertEqual(board.allies, ("Orianna",))
        for row in board.rows:
            with self.subTest(enemy=row.champion_id):
                self.assertGreater(row.team_dps, row.my_dps)
                self.assertLess(row.team_ttk_s, row.my_ttk_s)
                aa, ab, _hp = _sustained(
                    self.snap, _ALLY, (row.champion_id, row.level, row.item_ids),
                )
                self.assertAlmostEqual(row.team_dps, row.my_dps + aa + ab, places=6)


class OrderingTests(_Base):
    def test_kill_order_sorted_by_focus_value_desc(self) -> None:
        board = self._board(_JINX, _COMP, allies=[_ALLY])
        self.assertEqual(len(board.rows), len(_COMP))
        by_id = {r.champion_id: r for r in board.rows}
        self.assertEqual(sorted(board.kill_order), sorted(by_id))
        values = [by_id[c].focus_value for c in board.kill_order]
        self.assertEqual(values, sorted(values, reverse=True))
        # Non-vacuous: the comp must actually spread on the axis.
        self.assertGreater(max(values), min(values))

    def test_danger_order_sorted_by_their_ttk_on_me_asc(self) -> None:
        board = self._board(_JINX, _COMP)
        by_id = {r.champion_id: r for r in board.rows}
        self.assertEqual(sorted(board.danger_order), sorted(by_id))
        ttks = [by_id[c].their_ttk_on_me_s for c in board.danger_order]
        self.assertEqual(ttks, sorted(ttks))
        self.assertGreater(max(ttks), min(ttks))


class ComboLethalTests(_Base):
    def test_combo_lethal_pct_in_unit_interval_for_every_row(self) -> None:
        cases = (
            (_JINX, _COMP),
            (_LUX_ME, _COMP),
            # A fed level-18 assassin into level-1 squishies saturates the cap.
            (("Zed", 18, ("3142", "3814", "6694", "3071")),
             [("Lux", 1, ()), ("Jinx", 1, ())]),
        )
        saw_cap = False
        for me, enemies in cases:
            board = self._board(me, enemies)
            self.assertEqual(len(board.rows), len(enemies))
            for row in board.rows:
                with self.subTest(me=me[0], enemy=row.champion_id):
                    self.assertGreaterEqual(row.combo_lethal_hp_pct, 0.0)
                    self.assertLessEqual(row.combo_lethal_hp_pct, 1.0)
                    expected = min(1.0, row.my_burst / row.target_effective_hp)
                    self.assertAlmostEqual(row.combo_lethal_hp_pct, expected, places=9)
                    if row.combo_lethal_hp_pct == 1.0:
                        saw_cap = True
        self.assertTrue(saw_cap, "no case reached the 1.0 cap - cap branch untested")


class RobustnessTests(_Base):
    def test_unknown_enemy_is_a_note_not_an_exception(self) -> None:
        board = self._board(_JINX, [("NotAChampion", _LEVEL, ()), _COMP[0]])
        self.assertEqual([r.champion_id for r in board.rows], ["Malphite"])
        self.assertTrue(any("NotAChampion" in n for n in board.notes), board.notes)
        self.assertNotIn("NotAChampion", board.kill_order)
        self.assertNotIn("NotAChampion", board.danger_order)

    def test_unknown_me_yields_empty_board_with_note(self) -> None:
        board = self._board(("NotAChampion", _LEVEL, ()), _COMP)
        self.assertEqual(board.rows, ())
        self.assertEqual(board.kill_order, ())
        self.assertEqual(board.danger_order, ())
        self.assertTrue(any("NotAChampion" in n for n in board.notes), board.notes)

    def test_unknown_ally_is_skipped_with_note(self) -> None:
        board = self._board(_JINX, _COMP[:1], allies=[("NotAChampion", _LEVEL, ())])
        self.assertEqual(board.allies, ())
        row = self._row(board, "Malphite")
        self.assertAlmostEqual(row.team_ttk_s, row.my_ttk_s, places=9)
        self.assertTrue(any("NotAChampion" in n for n in board.notes), board.notes)

    def test_unknown_item_is_dropped_with_note(self) -> None:
        clean = self._board(_JINX, [("Malphite", _LEVEL, (_THORNMAIL,))])
        noisy = self._board(_JINX, [("Malphite", _LEVEL, (_THORNMAIL, "999999"))])
        self.assertAlmostEqual(
            self._row(noisy, "Malphite").my_ttk_s,
            self._row(clean, "Malphite").my_ttk_s,
            places=9,
        )
        self.assertTrue(any("999999" in n for n in noisy.notes), noisy.notes)

    def test_malformed_fighter_is_a_note(self) -> None:
        board = self._board(_JINX, [("Malphite",), None, _COMP[1]])
        self.assertEqual([r.champion_id for r in board.rows], ["Lux"])
        malformed = [n for n in board.notes if "malformed" in n]
        self.assertEqual(len(malformed), 2, board.notes)

    def test_notes_state_full_hp_assumption(self) -> None:
        board = self._board(_JINX, _COMP[:1])
        self.assertTrue(any("full HP" in n for n in board.notes), board.notes)

    def test_to_dict_is_strict_json(self) -> None:
        board = self._board(_JINX, _COMP, allies=[_ALLY])
        doc = json.loads(json.dumps(board.to_dict(), allow_nan=False))
        self.assertEqual(len(doc["rows"]), len(_COMP))
        self.assertEqual(doc["kill_order"], list(board.kill_order))


class ModeReachesBothSidesTests(_Base):
    def test_aram_mode_moves_both_directions(self) -> None:
        # Jinx aramDamageDealt 0.9 / aramDamageTaken 1.05; Lux 0.9 / 1.1.
        jinx = self.snap.champions["Jinx"]["lolmath"]["aram_modifiers"]
        lux = self.snap.champions["Lux"]["lolmath"]["aram_modifiers"]
        self.assertNotEqual(float(jinx["aramDamageDealt"]), 1.0)
        self.assertNotEqual(float(lux["aramDamageTaken"]), 1.0)
        enemy = [_COMP[1]]
        sr = self._row(self._board(_JINX, enemy, mode="SR"), "Lux")
        aram_board = self._board(_JINX, enemy, mode="ARAM")
        aram = self._row(aram_board, "Lux")
        # My side: Jinx's dealt multiplier reaches my DPS.
        self.assertNotAlmostEqual(aram.my_dps, sr.my_dps, places=6)
        # Their side: Lux's dealt multiplier reaches their DPS on me.
        self.assertNotAlmostEqual(aram.their_dps_on_me, sr.their_dps_on_me, places=6)
        # Damage-taken lands on both effective HP pools.
        taken_lux = _aram_damage_taken(self.snap, "Lux", "ARAM")
        taken_jinx = _aram_damage_taken(self.snap, "Jinx", "ARAM")
        self.assertAlmostEqual(
            aram.target_effective_hp, aram.target_max_hp / taken_lux, places=6,
        )
        self.assertAlmostEqual(
            aram_board.my_effective_hp, aram_board.my_max_hp / taken_jinx, places=6,
        )
        aa, ab, _hp = _sustained(self.snap, _JINX, _COMP[1], mode="ARAM")
        self.assertAlmostEqual(
            aram.my_ttk_s, (aram.target_max_hp / taken_lux) / (aa + ab), places=6,
        )
        # Lowercase mode folds to the same board.
        lower = self._row(self._board(_JINX, enemy, mode="aram"), "Lux")
        self.assertAlmostEqual(lower.my_ttk_s, aram.my_ttk_s, places=9)

    def test_arena_flag_reaches_my_side(self) -> None:
        # Jinx carries a wiki ARENA addend axis (dam_lvl / hp_lvl); Malphite
        # carries none, so only MY side can move.
        self.assertTrue(self.snap.mode_modifier("Jinx", "ARENA"))
        self.assertFalse(self.snap.mode_modifier("Malphite", "ARENA"))
        enemy = [("Malphite", _LEVEL, ())]
        off_b = self._board(_JINX, enemy, mode="ARENA")
        on_b = self._board(_JINX, enemy, mode="ARENA", apply_mode_modifiers=True)
        off, on = self._row(off_b, "Malphite"), self._row(on_b, "Malphite")
        self.assertNotAlmostEqual(on.my_dps, off.my_dps, places=6)
        self.assertNotAlmostEqual(on_b.my_max_hp, off_b.my_max_hp, places=6)
        self.assertAlmostEqual(on.target_max_hp, off.target_max_hp, places=9)
        self.assertTrue(on_b.apply_mode_modifiers)
        self.assertFalse(off_b.apply_mode_modifiers)

    def test_arena_flag_reaches_enemy_side(self) -> None:
        enemy = [("Jinx", _LEVEL, ("6672", "3031"))]
        me = ("Malphite", _LEVEL, ("3075",))
        off = self._row(self._board(me, enemy, mode="ARENA"), "Jinx")
        on = self._row(
            self._board(me, enemy, mode="ARENA", apply_mode_modifiers=True), "Jinx",
        )
        # Jinx's hp_lvl addend reaches her HP pool; dam_lvl reaches her DPS on me.
        self.assertNotAlmostEqual(on.target_max_hp, off.target_max_hp, places=6)
        self.assertNotAlmostEqual(on.their_dps_on_me, off.their_dps_on_me, places=6)
        self.assertNotAlmostEqual(on.my_ttk_s, off.my_ttk_s, places=6)

    def test_flag_is_inert_without_an_axis(self) -> None:
        # Neither champion carries an ARENA axis: on == off, so the moves above
        # are the flag's doing, not noise.
        enemy = [("Leona", _LEVEL, ("3143",))]
        me = ("Malphite", _LEVEL, ("3075",))
        self.assertFalse(self.snap.mode_modifier("Leona", "ARENA"))
        off = self._row(self._board(me, enemy, mode="ARENA"), "Leona")
        on = self._row(
            self._board(me, enemy, mode="ARENA", apply_mode_modifiers=True), "Leona",
        )
        for attr in ("my_dps", "their_dps_on_me", "target_max_hp", "my_burst"):
            with self.subTest(attr=attr):
                self.assertAlmostEqual(getattr(on, attr), getattr(off, attr), places=9)

    def test_flag_reaches_wiki_damage_taken_in_urf(self) -> None:
        # Darius URF dmg_taken 0.85 (wiki sidecar, flag-gated like ehp.py).
        mm = self.snap.mode_modifier("Darius", "URF")
        self.assertIsInstance(mm, dict)
        self.assertIn("dmg_taken", mm)
        me = ("Darius", _LEVEL, ("3071",))
        enemy = [("Zed", _LEVEL, ("3142",))]
        off_b = self._board(me, enemy, mode="URF")
        on_b = self._board(me, enemy, mode="URF", apply_mode_modifiers=True)
        self.assertAlmostEqual(off_b.my_effective_hp, off_b.my_max_hp, places=9)
        self.assertAlmostEqual(
            on_b.my_effective_hp, on_b.my_max_hp / float(mm["dmg_taken"]), places=6,
        )
        self.assertNotAlmostEqual(
            self._row(on_b, "Zed").their_ttk_on_me_s,
            self._row(off_b, "Zed").their_ttk_on_me_s,
            places=6,
        )


if __name__ == "__main__":
    unittest.main()
