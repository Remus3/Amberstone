# Tests for core/macro_context.py - the fog-only MacroContext snapshot (ZOI
# Wave-2 agent-macro, decision-tree v0).
#
# Grep-confirmed API surfaces the fixtures mirror:
#   - per-enemy fog shape {champion, team, level, is_dead, respawn_in_s,
#     visible, missing_for_s, last_seen_pos, last_seen_t, last_seen_zone}:
#     core/vision_tracker.py:376-388
#   - objective_events shape {name, killer_team, down_at_s[, dragon_type]}:
#     core/event_callouts.py:196-217 (_last_kill_t) + :671-677
#     (_is_elemental_drake)
#   - SR schedule constants SR_DRAGON_FIRST_S=300 / SR_DRAGON_RESPAWN_S=300 /
#     SR_BARON_FIRST_S=1200 / SR_BARON_RESPAWN_S=360:
#     core/event_callouts.py:66-69
#   - lead shape {"state": "ahead"/"even"/"behind", ...}:
#     core/lead_projection.py:231-250
#   - phase_for boundaries (early < 600s): core/lead_projection.py:70-71,
#     :170-182
from __future__ import annotations

import dataclasses
import unittest

from core.macro_context import EnemyFog, MacroContext, build_macro_context


def _enemy(champ: str, *, visible: bool = False, is_dead: bool = False,
           missing_for_s=None, zone: str = "") -> dict:
    """A vision_tracker-shaped per-enemy entry (core/vision_tracker.py:376)."""
    return {
        "champion": champ,
        "summoner_name": champ,
        "team": "CHAOS",
        "level": 9,
        "is_dead": is_dead,
        "respawn_in_s": None,
        "visible": visible,
        "missing_for_s": missing_for_s,
        "last_seen_pos": {"x": 7000.0, "z": 7000.0},
        "last_seen_t": 500.0,
        "last_seen_zone": zone,
    }


class BuildMacroContextTests(unittest.TestCase):

    def test_builds_from_vision_state_enemies_dict(self) -> None:
        enemies = {
            "Jinx": _enemy("Jinx", missing_for_s=20.0, zone="bot_river"),
            "Ahri": _enemy("Ahri", visible=True, zone="mid"),
        }
        ctx = build_macro_context("sr", 400.0, enemies=enemies)
        self.assertIsInstance(ctx, MacroContext)
        self.assertEqual(ctx.mode, "sr")
        self.assertEqual(ctx.game_time_s, 400.0)
        champs = sorted(e.champion for e in ctx.enemies)
        self.assertEqual(champs, ["Ahri", "Jinx"])
        jinx = next(e for e in ctx.enemies if e.champion == "Jinx")
        self.assertFalse(jinx.visible)
        self.assertEqual(jinx.missing_for_s, 20.0)
        self.assertEqual(jinx.last_seen_zone, "bot_river")

    def test_builds_from_enemy_list_too(self) -> None:
        enemies = [_enemy("Jinx", missing_for_s=15.0, zone="top_river")]
        ctx = build_macro_context("sr", 400.0, enemies=enemies)
        self.assertEqual(len(ctx.enemies), 1)
        self.assertEqual(ctx.enemies[0].champion, "Jinx")

    def test_missing_enemies_filters_dead_visible_and_threshold(self) -> None:
        enemies = {
            "Jinx":   _enemy("Jinx", missing_for_s=20.0, zone="bot_river"),
            "Thresh": _enemy("Thresh", missing_for_s=3.0, zone="bot_river"),
            "LeeSin": _enemy("LeeSin", is_dead=True, missing_for_s=50.0),
            "Ahri":   _enemy("Ahri", visible=True),
        }
        ctx = build_macro_context("sr", 400.0, enemies=enemies)
        mia = ctx.missing_enemies(min_missing_s=8.0)
        self.assertEqual([e.champion for e in mia], ["Jinx"])
        # Threshold 0 keeps every not-dead not-visible entry with a number.
        mia0 = ctx.missing_enemies()
        self.assertEqual(sorted(e.champion for e in mia0),
                         ["Jinx", "Thresh"])

    def test_next_dragon_eta_static_first_spawn(self) -> None:
        # No kill events: the first-spawn anchor (300s) is the next spawn.
        ctx = build_macro_context("sr", 200.0)
        self.assertAlmostEqual(ctx.next_dragon_eta_s, 100.0)
        # Baron first spawn 1200s.
        self.assertAlmostEqual(ctx.next_baron_eta_s, 1000.0)

    def test_next_dragon_eta_tracks_last_elemental_take(self) -> None:
        events = [{"name": "dragon", "killer_team": "CHAOS",
                   "down_at_s": 600.0, "dragon_type": "infernal"}]
        ctx = build_macro_context("sr", 860.0, objective_events=events)
        self.assertAlmostEqual(ctx.next_dragon_eta_s, 40.0)

    def test_elder_take_does_not_anchor_dragon_respawn(self) -> None:
        # An Elder kill is not an elemental respawn anchor (event_callouts
        # _last_kill_t elemental_only contract).
        events = [{"name": "dragon", "killer_team": "CHAOS",
                   "down_at_s": 2000.0, "dragon_type": "elder"}]
        ctx = build_macro_context("sr", 2100.0, objective_events=events)
        # Falls back to the static first-spawn anchor (long past).
        self.assertAlmostEqual(ctx.next_dragon_eta_s, 300.0 - 2100.0)

    def test_baron_eta_tracks_last_take(self) -> None:
        events = [{"name": "baron", "killer_team": "ORDER",
                   "down_at_s": 1500.0}]
        ctx = build_macro_context("sr", 1700.0, objective_events=events)
        self.assertAlmostEqual(ctx.next_baron_eta_s, 160.0)

    def test_lead_state_and_phase(self) -> None:
        ctx = build_macro_context("sr", 400.0, lead={"state": "ahead"})
        self.assertEqual(ctx.lead_state, "ahead")
        self.assertEqual(ctx.phase, "early")
        ctx_late = build_macro_context("sr", 1600.0)
        self.assertEqual(ctx_late.phase, "late")
        self.assertEqual(ctx_late.lead_state, "even")

    def test_zoi_kwarg_is_an_ignored_v1_seam(self) -> None:
        # v0 is fog-only: zoi content must not change the built context.
        a = build_macro_context("sr", 400.0,
                                enemies=[_enemy("Jinx", missing_for_s=20.0)])
        b = build_macro_context("sr", 400.0,
                                enemies=[_enemy("Jinx", missing_for_s=20.0)],
                                zoi={"bubbles": [{"team": "enemy"}],
                                     "demarcation": None, "map_control": {}})
        self.assertEqual(a, b)

    def test_fail_soft_on_garbage_never_raises(self) -> None:
        for args in (
            (None, None),
            (12345, "not-a-number"),
            ("sr", float("nan")),
        ):
            ctx = build_macro_context(*args)  # must not raise
            self.assertIsInstance(ctx, MacroContext)
        junk = build_macro_context(
            "sr", 400.0, enemies="junk", objective_events="junk",
            lead="junk", zoi="junk")
        self.assertIsInstance(junk, MacroContext)
        self.assertEqual(junk.enemies, ())
        self.assertEqual(junk.lead_state, "even")

    def test_malformed_enemy_entries_skipped(self) -> None:
        enemies = {"Jinx": _enemy("Jinx", missing_for_s=20.0),
                   "bad1": "junk", "bad2": None}
        ctx = build_macro_context("sr", 400.0, enemies=enemies)
        self.assertEqual([e.champion for e in ctx.enemies], ["Jinx"])

    def test_context_is_frozen(self) -> None:
        ctx = build_macro_context("sr", 400.0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ctx.mode = "aram"  # type: ignore[misc]

    def test_missing_for_s_bool_rejected(self) -> None:
        # bool is an int subclass; a True missing_for_s is garbage, not 1.0s.
        enemies = [_enemy("Jinx", missing_for_s=True)]
        ctx = build_macro_context("sr", 400.0, enemies=enemies)
        self.assertIsNone(ctx.enemies[0].missing_for_s)

    def test_enemyfog_defaults(self) -> None:
        e = EnemyFog()
        self.assertEqual(e.champion, "")
        self.assertFalse(e.visible)
        self.assertFalse(e.is_dead)
        self.assertIsNone(e.missing_for_s)
        self.assertEqual(e.last_seen_zone, "")


if __name__ == "__main__":
    unittest.main()
