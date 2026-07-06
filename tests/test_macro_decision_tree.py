# Tests for core/macro_decision_tree.py (ZOI Wave-2 agent-macro, fog-only v0)
# and its wiring into dashboard/_deterministic_coaching.py.
#
# Grep-confirmed API surfaces:
#   - registry-of-pure-predicates doctrine: core/decision_detector.py:133-142
#     (DECISION_REGISTRY - list of pure fns, purely additive).
#   - callout schema {tag, line, eta_s, kind}: core/event_callouts.py:220-228.
#   - has_capability fail-CLOSED ward gate: core/mode_capabilities.py:80-95.
#   - advisory chain + 3-row clamp: dashboard/_deterministic_coaching.py
#     _compute_uncached (macro_response kind="macro_response"
#     core/macro_response.py:267 - the NEW decision-tree kind is "macro",
#     no collision).
#   - vision fog per-enemy shape: core/vision_tracker.py:376-388.
#   - load_vision_state test seam: core/laning_cv_overrides.py:62-72
#     (lazy-imported per call by _stamp_vision_summary, so patching the
#     module attribute works - same pattern as
#     tests/test_deterministic_coaching_wire.py:630-649).
from __future__ import annotations

import json
import unittest
from pathlib import Path

import core.laning_cv_overrides as cvo
import dashboard._deterministic_coaching as dc
from core.macro_context import build_macro_context
from core.macro_decision_tree import (
    GANK_MIN_MIA_S,
    MACRO_RULE_REGISTRY,
    MIN_MIA_S,
    OBJECTIVE_WINDOW_S,
    evaluate,
    rules_for,
)

_ROOT = Path(__file__).resolve().parent.parent


def _enemy(champ: str, *, visible: bool = False, is_dead: bool = False,
           missing_for_s=None, zone: str = "") -> dict:
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


# The operator acceptance fixture: bot + sup MIA ~20s last seen river-ward,
# jungler last seen bottom jungle, 2 enemies still visible; dragon taken at
# 600s so the next drake spawns at 900s (40s out at game_time 860s).
_SCENARIO_VISION = {
    "summary": {"visible_count": 2, "missing_count": 3, "dead_count": 0,
                "total": 5},
    "enemies": {
        "Jinx":   _enemy("Jinx", missing_for_s=20.0, zone="bot_river"),
        "Thresh": _enemy("Thresh", missing_for_s=21.0, zone="bot_river"),
        "LeeSin": _enemy("LeeSin", missing_for_s=25.0,
                         zone="red_bot_jungle"),
        "Ahri":   _enemy("Ahri", visible=True, zone="mid"),
        "Garen":  _enemy("Garen", visible=True, zone="top_lane"),
    },
}

_ALL_VISIBLE_VISION = {
    "summary": {"visible_count": 5, "missing_count": 0, "dead_count": 0,
                "total": 5},
    "enemies": {
        nm: _enemy(nm, visible=True, zone="mid")
        for nm in ("Jinx", "Thresh", "LeeSin", "Ahri", "Garen")
    },
}

_SCENARIO_COACH = {"champion": "Caitlyn", "level": 11}
_SCENARIO_LC = {
    "champion": "Caitlyn",
    "enemy_team": ["Jinx", "Thresh", "LeeSin", "Ahri", "Garen"],
    "game_time_s": 860.0,
    "objective_events": [{"name": "dragon", "killer_team": "CHAOS",
                          "down_at_s": 600.0, "dragon_type": "infernal"}],
}


class RegistryShapeTests(unittest.TestCase):

    def test_sr_rules_ordered_and_nonempty(self) -> None:
        rules = MACRO_RULE_REGISTRY["sr"]
        self.assertGreaterEqual(len(rules), 2)
        self.assertEqual(rules[0].name, "objective_danger")
        self.assertEqual(rules[1].name, "gank_warning")

    def test_aram_and_arena_registered_empty_no_sr_fallback(self) -> None:
        # Shared vision / no fog: present-but-empty, and rules_for must NOT
        # fall back to the SR rules.
        self.assertIn("aram", MACRO_RULE_REGISTRY)
        self.assertIn("arena", MACRO_RULE_REGISTRY)
        self.assertEqual(MACRO_RULE_REGISTRY["aram"], ())
        self.assertEqual(MACRO_RULE_REGISTRY["arena"], ())
        self.assertEqual(rules_for("aram"), ())
        self.assertEqual(rules_for("ARENA"), ())
        self.assertEqual(rules_for("KIWI"), ())
        self.assertEqual(rules_for("CHERRY"), ())

    def test_unknown_mode_yields_no_rules(self) -> None:
        self.assertEqual(rules_for("tft"), ())
        self.assertEqual(rules_for(None), ())
        self.assertEqual(rules_for("garbage"), ())

    def test_sr_spellings_resolve(self) -> None:
        sr = MACRO_RULE_REGISTRY["sr"]
        for spelling in ("sr", "SR", "CLASSIC", "client", "game"):
            self.assertEqual(rules_for(spelling), sr, spelling)


class ObjectiveDangerRuleTests(unittest.TestCase):

    def _danger_ctx(self, mode: str = "sr", gt: float = 860.0):
        return build_macro_context(
            mode, gt,
            enemies=_SCENARIO_VISION["enemies"],
            objective_events=_SCENARIO_LC["objective_events"],
        )

    def test_fires_one_macro_callout_with_window_count_action(self) -> None:
        out = evaluate(self._danger_ctx())
        self.assertIsInstance(out, dict)
        self.assertEqual(out["kind"], "macro")
        self.assertEqual(out["tag"], "macro_objective_danger")
        self.assertIn("Drake", out["line"])
        self.assertIn("40", out["line"])           # the objective window
        self.assertIn("3 missing", out["line"])    # the missing count
        self.assertIn("ward", out["line"])         # SR has wards (W landed)
        self.assertAlmostEqual(out["eta_s"], 40.0)

    def test_ward_text_gated_on_has_capability(self) -> None:
        # Emit called directly with a no-ward mode: the action must say
        # group/back off and NEVER "ward" (has_capability fail-CLOSED).
        rule = MACRO_RULE_REGISTRY["sr"][0]
        line_aram = rule.emit(self._danger_ctx(mode="aram"))["line"]
        self.assertNotIn("ward", line_aram.lower())
        self.assertIn("group", line_aram.lower())
        line_sr = rule.emit(self._danger_ctx(mode="sr"))["line"]
        self.assertIn("ward", line_sr.lower())

    def test_baron_window_names_baron(self) -> None:
        events = [{"name": "baron", "killer_team": "ORDER",
                   "down_at_s": 1500.0}]
        ctx = build_macro_context(
            "sr", 1830.0, enemies=_SCENARIO_VISION["enemies"],
            objective_events=events)
        out = evaluate(ctx)
        self.assertIsNotNone(out)
        self.assertIn("Baron", out["line"])
        self.assertAlmostEqual(out["eta_s"], 30.0)

    def test_no_fire_below_two_missing(self) -> None:
        enemies = {"Jinx": _enemy("Jinx", missing_for_s=20.0,
                                  zone="bot_river"),
                   "Ahri": _enemy("Ahri", visible=True)}
        ctx = build_macro_context(
            "sr", 860.0, enemies=enemies,
            objective_events=_SCENARIO_LC["objective_events"])
        self.assertIsNone(evaluate(ctx))

    def test_no_fire_when_missing_below_min_mia(self) -> None:
        short = {nm: _enemy(nm, missing_for_s=MIN_MIA_S - 5.0,
                            zone="bot_river")
                 for nm in ("Jinx", "Thresh")}
        ctx = build_macro_context(
            "sr", 860.0, enemies=short,
            objective_events=_SCENARIO_LC["objective_events"])
        self.assertIsNone(evaluate(ctx))

    def test_no_fire_outside_objective_window(self) -> None:
        # Dragon taken at 600 -> next at 900; at 900 - OBJECTIVE_WINDOW_S - 40
        # the window has not opened yet.
        gt = 900.0 - OBJECTIVE_WINDOW_S - 40.0
        ctx = build_macro_context(
            "sr", gt, enemies=_SCENARIO_VISION["enemies"],
            objective_events=_SCENARIO_LC["objective_events"])
        out = evaluate(ctx)
        if out is not None:
            # If anything fired it must NOT be the objective-danger rule.
            self.assertNotEqual(out["tag"], "macro_objective_danger")


class GankWarningRuleTests(unittest.TestCase):

    def test_fires_in_laning_phase_with_river_jungle_mia(self) -> None:
        enemies = {
            "LeeSin": _enemy("LeeSin", missing_for_s=15.0, zone="top_river"),
            "Ahri":   _enemy("Ahri", missing_for_s=14.0,
                             zone="blue_bot_jungle"),
            "Garen":  _enemy("Garen", visible=True, zone="top_lane"),
        }
        # gt 400 is laning phase; dragon first-spawn (300) is long past with
        # no kill anchor -> objective window closed, gank rule owns the read.
        ctx = build_macro_context("sr", 400.0, enemies=enemies)
        out = evaluate(ctx)
        self.assertIsNotNone(out)
        self.assertEqual(out["kind"], "macro")
        self.assertEqual(out["tag"], "macro_gank_warning")
        self.assertIn("2 missing", out["line"])
        self.assertIsNone(out["eta_s"])

    def test_no_fire_past_laning_phase(self) -> None:
        enemies = {
            "LeeSin": _enemy("LeeSin", missing_for_s=15.0, zone="top_river"),
            "Ahri":   _enemy("Ahri", missing_for_s=14.0,
                             zone="blue_bot_jungle"),
        }
        ctx = build_macro_context("sr", 1600.0, enemies=enemies)
        self.assertIsNone(evaluate(ctx))

    def test_no_fire_when_last_seen_in_lanes(self) -> None:
        enemies = {
            "LeeSin": _enemy("LeeSin", missing_for_s=15.0, zone="top_lane"),
            "Ahri":   _enemy("Ahri", missing_for_s=14.0, zone="bot_lane"),
        }
        ctx = build_macro_context("sr", 400.0, enemies=enemies)
        self.assertIsNone(evaluate(ctx))

    def test_gank_min_mia_threshold(self) -> None:
        enemies = {
            "LeeSin": _enemy("LeeSin", missing_for_s=GANK_MIN_MIA_S - 2.0,
                             zone="top_river"),
            "Ahri":   _enemy("Ahri", missing_for_s=GANK_MIN_MIA_S - 2.0,
                             zone="blue_bot_jungle"),
        }
        ctx = build_macro_context("sr", 400.0, enemies=enemies)
        self.assertIsNone(evaluate(ctx))


class EvaluateContractTests(unittest.TestCase):

    def test_first_match_wins_exactly_one_callout(self) -> None:
        # Both rules' predicates hold (drake window open at 560 after a 300s
        # take + 2 river-MIA in laning phase): the ordered registry returns
        # ONLY the first (objective danger).
        enemies = {
            "Jinx":   _enemy("Jinx", missing_for_s=20.0, zone="bot_river"),
            "Thresh": _enemy("Thresh", missing_for_s=21.0, zone="top_river"),
        }
        events = [{"name": "dragon", "killer_team": "CHAOS",
                   "down_at_s": 300.0, "dragon_type": "mountain"}]
        ctx = build_macro_context("sr", 560.0, enemies=enemies,
                                  objective_events=events)
        out = evaluate(ctx)
        self.assertIsNotNone(out)
        self.assertEqual(out["tag"], "macro_objective_danger")

    def test_empty_mode_registries_never_fire(self) -> None:
        for mode in ("aram", "arena", "KIWI", "CHERRY"):
            ctx = build_macro_context(
                mode, 860.0, enemies=_SCENARIO_VISION["enemies"],
                objective_events=_SCENARIO_LC["objective_events"])
            self.assertIsNone(evaluate(ctx), mode)

    def test_fail_soft_on_garbage(self) -> None:
        self.assertIsNone(evaluate(None))
        self.assertIsNone(evaluate("junk"))
        self.assertIsNone(evaluate(object()))

    def test_zoi_districts_seam_ignored_in_v0(self) -> None:
        ctx = build_macro_context(
            "sr", 860.0, enemies=_SCENARIO_VISION["enemies"],
            objective_events=_SCENARIO_LC["objective_events"])
        a = evaluate(ctx)
        b = evaluate(ctx, zoi={"bubbles": []}, districts={"map": 1.0})
        self.assertEqual(a, b)

    def test_no_llm_or_network_imports_in_modules(self) -> None:
        # ZERO LLM/network: the pure modules never import anthropic or any
        # HTTP client.
        for rel in ("core/macro_context.py", "core/macro_decision_tree.py"):
            src = (_ROOT / rel).read_text(encoding="utf-8")
            for banned in ("anthropic", "requests", "urllib", "socket",
                           "httpx"):
                self.assertNotIn(banned, src, f"{banned} in {rel}")


# ---------------------------------------------------------------------------
# Wiring into dashboard/_deterministic_coaching.py
# ---------------------------------------------------------------------------

# Characterization pin captured from _compute_uncached BEFORE the decision-
# tree edit (laning_choices stubbed to [], no fog stamped). The post-edit
# output with no macro rule firing must stay byte-identical.
_PINNED_NO_RULE = {
    "callouts": [
        {"eta_s": 40.0, "kind": "objective",
         "line": "Drake spawns 5:00 - set up vision", "tag": "dragon"},
        {"eta_s": 40.0, "kind": "playbook",
         "line": "Drake: trade it for a lane - do not contest down",
         "tag": "playbook_dragon"},
        {"eta_s": 280.0, "kind": "objective",
         "line": "Rift Herald 14:00 - ward river", "tag": "herald"},
    ],
    "choices": [],
    "lead_projection": {
        "line": "Behind: freeze or farm safe, avoid trades.",
        "magnitude": "clear",
        "source_tag": "lead-proj",
        "state": "behind",
    },
}


class WiringTests(unittest.TestCase):

    def setUp(self) -> None:
        dc._reset_caches_for_tests()
        self._orig_laning = dc.laning_choices
        self._orig_vision = cvo.load_vision_state
        dc.laning_choices = lambda gs, mode="SR", **kw: []

    def tearDown(self) -> None:
        dc.laning_choices = self._orig_laning
        cvo.load_vision_state = self._orig_vision
        dc._reset_caches_for_tests()

    def test_characterization_no_rule_fires_byte_identical(self) -> None:
        gs = {"my_champion": "Jinx", "enemy_comp": ["Ahri"], "level": 9,
              "game_time_s": 560.0}
        out = dc._compute_uncached(dict(gs), "sr")
        self.assertEqual(json.dumps(out, sort_keys=True),
                         json.dumps(_PINNED_NO_RULE, sort_keys=True))

    def test_operator_acceptance_scenario(self) -> None:
        # bot+sup MIA ~20s river-ward + jungler last seen bottom + dragon in
        # 40s -> exactly ONE kind="macro" callout naming the drake window,
        # the missing count, and the ward/group action - zero LLM calls
        # (laning stubbed; every other generator is pure).
        cvo.load_vision_state = lambda path=None: _SCENARIO_VISION
        out = dc.compute_deterministic(_SCENARIO_COACH, _SCENARIO_LC, "sr")
        callouts = out["callouts"]
        macros = [c for c in callouts if c.get("kind") == "macro"]
        self.assertEqual(len(macros), 1)
        line = macros[0]["line"]
        self.assertIn("Drake", line)
        self.assertIn("40", line)          # the drake window
        self.assertIn("3 missing", line)   # the missing count
        self.assertIn("ward", line)        # SR ward action
        self.assertLessEqual(len(callouts), 3)  # density clamp preserved

    def test_zoi_none_byte_identical_when_no_rule_fires(self) -> None:
        cvo.load_vision_state = lambda path=None: _ALL_VISIBLE_VISION
        out_none = dc.compute_deterministic(
            dict(_SCENARIO_COACH), dict(_SCENARIO_LC), "sr")
        blob_none = json.dumps(out_none, sort_keys=True)
        dc._reset_caches_for_tests()
        out_zoi = dc.compute_deterministic(
            dict(_SCENARIO_COACH), dict(_SCENARIO_LC), "sr",
            zoi={"bubbles": [], "demarcation": None, "map_control": {}})
        self.assertEqual(blob_none, json.dumps(out_zoi, sort_keys=True))
        self.assertNotIn(
            "macro", [c.get("kind") for c in out_none["callouts"]])

    def test_decision_tree_outranks_ws4_macro_response(self) -> None:
        # Priority chain: decision_tree > ws4_macro > soul > heal.
        orig_ws4 = dc.macro_response_callout
        dc.macro_response_callout = lambda *a, **k: {
            "tag": "macro_stub", "line": "ws4 stub", "eta_s": None,
            "kind": "macro_response"}
        try:
            cvo.load_vision_state = lambda path=None: _SCENARIO_VISION
            out = dc.compute_deterministic(
                dict(_SCENARIO_COACH), dict(_SCENARIO_LC), "sr")
            kinds = [c.get("kind") for c in out["callouts"]]
            self.assertIn("macro", kinds)
            self.assertNotIn("macro_response", kinds)

            # With no macro rule firing, WS4 takes the advisory slot back.
            dc._reset_caches_for_tests()
            cvo.load_vision_state = lambda path=None: _ALL_VISIBLE_VISION
            out2 = dc.compute_deterministic(
                dict(_SCENARIO_COACH), dict(_SCENARIO_LC), "sr")
            kinds2 = [c.get("kind") for c in out2["callouts"]]
            self.assertIn("macro_response", kinds2)
            self.assertNotIn("macro", kinds2)
        finally:
            dc.macro_response_callout = orig_ws4

    def test_sr_only_no_macro_row_in_aram(self) -> None:
        cvo.load_vision_state = lambda path=None: _SCENARIO_VISION
        lc = dict(_SCENARIO_LC)
        out = dc.compute_deterministic(dict(_SCENARIO_COACH), lc, "aram")
        self.assertNotIn("macro", [c.get("kind") for c in out["callouts"]])

    def test_stamp_fog_enemies_and_failsoft(self) -> None:
        cvo.load_vision_state = lambda path=None: _SCENARIO_VISION
        gs: dict = {}
        dc._stamp_vision_summary(gs)
        self.assertEqual(gs["vision_summary"]["missing_count"], 3)
        fog = gs["fog_enemies"]
        self.assertEqual(len(fog), 5)
        jinx = next(e for e in fog if e["champion"] == "Jinx")
        self.assertEqual(jinx["last_seen_zone"], "bot_river")
        self.assertEqual(jinx["missing_for_s"], 20.0)
        self.assertFalse(jinx["visible"])

        cvo.load_vision_state = lambda path=None: {"enemies": "junk"}
        gs2: dict = {}
        dc._stamp_vision_summary(gs2)  # must not raise
        self.assertNotIn("fog_enemies", gs2)

    def test_fog_change_invalidates_cache_sig(self) -> None:
        base = {"my_champion": "Caitlyn", "enemy_comp": ["Jinx"], "level": 11,
                "game_time_s": 860.0}
        s0 = dc._cache_sig(dict(base), "sr")
        with_fog = {**base, "fog_enemies": [
            {"champion": "Jinx", "visible": False, "is_dead": False,
             "missing_for_s": 20.0, "last_seen_zone": "bot_river"}]}
        s1 = dc._cache_sig(with_fog, "sr")
        self.assertNotEqual(s0, s1)
        # A zone flip inside the same counts must ALSO re-key (completeness).
        zone_flip = {**base, "fog_enemies": [
            {"champion": "Jinx", "visible": False, "is_dead": False,
             "missing_for_s": 20.0, "last_seen_zone": "top_river"}]}
        self.assertNotEqual(s1, dc._cache_sig(zone_flip, "sr"))
        # Malformed fog is fail-soft, not a raise.
        self.assertEqual(
            dc._fog_sig({"fog_enemies": "junk"}), ())


if __name__ == "__main__":
    unittest.main()
