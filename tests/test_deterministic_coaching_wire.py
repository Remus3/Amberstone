# Tests for the Haiku-elimination wave 3 deterministic coaching wire (item 265 W3A).
#
# Covers dashboard/_deterministic_coaching.py:
#   - _build_game_state field mapping (coach-wins-then-lc; enemy_comp from lc).
#   - compute_deterministic returns the 3 keys + is fail-soft (never raises).
#   - the TTL cache calls the underlying laning path ONCE within TTL, recomputes
#     after monotonic fast-forward.
#   - resolve_choices: deterministic-FIRST, else native, else synth, else [].
#   - ASCII hygiene on the 2 new/edited files (no non-ASCII in the added lines).
#
# All laning calls are monkeypatched so NO real DS-engine network call happens.
from __future__ import annotations

import os
import time
import unittest
from pathlib import Path

import dashboard._deterministic_coaching as dc

_ROOT = Path(__file__).resolve().parent.parent


def _reset_cache() -> None:
    dc._reset_caches_for_tests()


class BuildGameStateTests(unittest.TestCase):
    """_build_game_state maps coach + liveclient into the game_state shape."""

    def test_enemy_comp_comes_from_lc_enemy_team(self) -> None:
        coach = {"champion": "Aatrox"}
        lc = {"enemy_team": ["Garen", "Darius", "Teemo"]}
        gs = dc._build_game_state(coach, lc, "sr")
        self.assertEqual(gs["enemy_comp"], ["Garen", "Darius", "Teemo"])
        self.assertEqual(gs["my_champion"], "Aatrox")

    def test_inhib_events_come_from_lc(self) -> None:
        coach = {"champion": "Caitlyn"}
        lc = {"enemy_team": ["Ezreal"],
              "inhib_events": [{"down_at_s": 600.0, "name": "Barracks_T2_L1"}]}
        gs = dc._build_game_state(coach, lc, "sr")
        self.assertEqual(gs["inhib_events"],
                         [{"down_at_s": 600.0, "name": "Barracks_T2_L1"}])

    def test_coach_wins_over_lc_for_overlapping_fields(self) -> None:
        # Precedence is coach.get(...) or lc.get(...) for overlapping fields.
        coach = {"champion": "Aatrox", "level": 9, "kda": "5/2/3", "cs": 110}
        lc = {"champion": "Garen", "level": 6, "kda": "1/1/1", "cs": 40,
              "enemy_team": ["Teemo"]}
        gs = dc._build_game_state(coach, lc, "sr")
        self.assertEqual(gs["my_champion"], "Aatrox")  # coach wins
        self.assertEqual(gs["level"], 9)               # coach wins
        self.assertEqual(gs["kda"], "5/2/3")           # coach wins
        self.assertEqual(gs["cs"], 110)                # coach wins

    def test_lc_fills_when_coach_absent(self) -> None:
        coach = {}
        lc = {"champion": "Garen", "level": 6, "gold": 1500,
              "game_time_s": 360, "enemy_team": ["Teemo"]}
        gs = dc._build_game_state(coach, lc, "sr")
        self.assertEqual(gs["my_champion"], "Garen")
        self.assertEqual(gs["level"], 6)
        self.assertEqual(gs["gold"], 1500)
        self.assertEqual(gs["game_time_s"], 360)

    def test_present_zero_numeric_wins_over_later_none(self) -> None:
        # gold/cs of 0 are real values and must win over a later None per _first.
        coach = {"champion": "Aatrox", "gold": 0, "cs": 0}
        lc = {"gold": 999, "cs": 80, "enemy_team": ["Teemo"]}
        gs = dc._build_game_state(coach, lc, "sr")
        self.assertEqual(gs["gold"], 0)
        self.assertEqual(gs["cs"], 0)

    def test_empty_string_champion_falls_through_to_lc(self) -> None:
        # An empty-string coach champion is skipped (treated as absent).
        coach = {"champion": ""}
        lc = {"champion": "Garen", "enemy_team": ["Teemo"]}
        gs = dc._build_game_state(coach, lc, "sr")
        self.assertEqual(gs["my_champion"], "Garen")

    def test_game_time_seconds_fallback(self) -> None:
        coach = {"champion": "Aatrox", "game_seconds": 420}
        lc = {"enemy_team": ["Teemo"]}
        gs = dc._build_game_state(coach, lc, "sr")
        self.assertEqual(gs["game_time_s"], 420)

    def test_absent_fields_omitted(self) -> None:
        gs = dc._build_game_state({}, {}, "sr")
        # No enemy, no champ, no level -> empty / minimal dict, no raise.
        self.assertNotIn("enemy_comp", gs)
        self.assertNotIn("my_champion", gs)

    def test_none_lc_tolerated(self) -> None:
        gs = dc._build_game_state({"champion": "Aatrox"}, None, "sr")
        self.assertEqual(gs["my_champion"], "Aatrox")
        self.assertNotIn("enemy_comp", gs)

    def test_owned_items_and_ids_mapped(self) -> None:
        coach = {"champion": "Aatrox"}
        lc = {"owned_items": ["Eclipse", "Plated Steelcaps"],
              "owned_item_ids": ["6692", "3047"], "enemy_team": ["Teemo"]}
        gs = dc._build_game_state(coach, lc, "sr")
        self.assertEqual(gs["items"], ["Eclipse", "Plated Steelcaps"])
        self.assertEqual(gs["my_item_ids"], ["6692", "3047"])

    def test_hp_fraction_mapped(self) -> None:
        # RC2 P5.2: hp_fraction (lc-first) is stamped onto gs for the CV layer.
        coach = {"champion": "Aatrox", "hp": 600, "hp_max": 1000}
        gs = dc._build_game_state(coach, {"enemy_team": ["Teemo"]}, "sr")
        self.assertAlmostEqual(gs["hp_fraction"], 0.6)

    def test_hp_fraction_absent_omitted(self) -> None:
        gs = dc._build_game_state({"champion": "Aatrox"},
                                  {"enemy_team": ["Teemo"]}, "sr")
        self.assertNotIn("hp_fraction", gs)

    def test_team_item_pools_mapped_from_lc(self) -> None:
        # enemy_item_ids + ally_item_ids (for the heal-threat nudge) come only
        # from the liveclient scoreboard.
        coach = {"champion": "Aatrox"}
        lc = {"enemy_team": ["Soraka"],
              "enemy_item_ids": ["3072", "3074"], "ally_item_ids": ["3047"]}
        gs = dc._build_game_state(coach, lc, "sr")
        self.assertEqual(gs["enemy_item_ids"], ["3072", "3074"])
        self.assertEqual(gs["ally_item_ids"], ["3047"])

    def test_empty_team_item_pools_omitted(self) -> None:
        gs = dc._build_game_state({"champion": "Aatrox"},
                                  {"enemy_team": ["Teemo"], "enemy_item_ids": []},
                                  "sr")
        self.assertNotIn("enemy_item_ids", gs)
        self.assertNotIn("ally_item_ids", gs)


class _FakeChoice:
    """Minimal stand-in that to_jsonable can serialize via .to_dict()."""

    def __init__(self, key: str, label: str) -> None:
        self.key = key
        self.label = label

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "source_tag": "ds-matchup"}


class ComputeDeterministicTests(unittest.TestCase):
    """compute_deterministic shape + fail-soft + cache behavior."""

    def setUp(self) -> None:
        _reset_cache()

    def tearDown(self) -> None:
        _reset_cache()

    def test_returns_three_keys(self) -> None:
        # Monkeypatch laning_choices to return a stub so no network call.
        orig = dc.laning_choices
        try:
            dc.laning_choices = lambda gs, mode="SR": [_FakeChoice("A", "Trade now")]
            coach = {"champion": "Aatrox", "level": 9, "game_time_s": 330,
                     "kda": "3/1/2", "cs": 90, "gold": 1200}
            lc = {"enemy_team": ["Garen"], "owned_items": ["Eclipse"]}
            out = dc.compute_deterministic(coach, lc, "sr")
        finally:
            dc.laning_choices = orig
        self.assertIn("choices", out)
        self.assertIn("callouts", out)
        self.assertIn("lead_projection", out)
        self.assertIsInstance(out["choices"], list)
        self.assertIsInstance(out["callouts"], list)
        self.assertIsInstance(out["lead_projection"], dict)
        # The stub choice surfaced as jsonable dict.
        self.assertEqual(out["choices"][0]["label"], "Trade now")
        # lead_projection always carries the 4 keys from project_lead.
        self.assertIn("state", out["lead_projection"])
        self.assertIn("line", out["lead_projection"])
        self.assertEqual(out["lead_projection"]["source_tag"], "lead-proj")

    def test_heal_threat_callout_merged_into_callouts(self) -> None:
        # Enemy Soraka + no ally anti-heal -> a heal_threat callout rides in
        # state.callouts (appended after the timed objectives).
        orig = dc.laning_choices
        try:
            dc.laning_choices = lambda gs, mode="SR": []
            coach = {"champion": "Aatrox", "level": 9, "game_time_s": 330}
            lc = {"enemy_team": ["Soraka"], "enemy_item_ids": ["3072"],
                  "ally_item_ids": ["3047"]}
            out = dc.compute_deterministic(coach, lc, "sr")
        finally:
            dc.laning_choices = orig
        kinds = [c.get("kind") for c in out["callouts"]]
        self.assertIn("heal_threat", kinds)
        heal = next(c for c in out["callouts"] if c.get("kind") == "heal_threat")
        self.assertIn("Soraka", heal["line"])
        self.assertIsNone(heal["eta_s"])

    def test_heal_threat_suppressed_when_ally_has_antiheal(self) -> None:
        # Ally owns Morellonomicon (3165) -> no heal_threat callout.
        orig = dc.laning_choices
        try:
            dc.laning_choices = lambda gs, mode="SR": []
            coach = {"champion": "Aatrox", "level": 9, "game_time_s": 330}
            lc = {"enemy_team": ["Soraka", "Vladimir"], "ally_item_ids": ["3165"]}
            out = dc.compute_deterministic(coach, lc, "sr")
        finally:
            dc.laning_choices = orig
        kinds = [c.get("kind") for c in out["callouts"]]
        self.assertNotIn("heal_threat", kinds)

    def test_fail_soft_returns_all_empty(self) -> None:
        # A laning path that raises must degrade to the all-empty result.
        orig = dc.laning_choices

        def _boom(gs, mode="SR"):
            raise RuntimeError("engine exploded")

        try:
            dc.laning_choices = _boom
            out = dc.compute_deterministic({"champion": "Aatrox"},
                                           {"enemy_team": ["Garen"]}, "sr")
        finally:
            dc.laning_choices = orig
        self.assertEqual(out, {"choices": [], "callouts": [],
                               "lead_projection": {}})

    def test_does_not_raise_on_garbage_inputs(self) -> None:
        # None coach + None lc + weird mode -> no raise, empty-ish result.
        out = dc.compute_deterministic(None, None, None)
        self.assertIn("choices", out)
        self.assertIn("callouts", out)
        self.assertIn("lead_projection", out)

    def test_ttl_cache_calls_laning_once_within_ttl(self) -> None:
        calls = {"n": 0}
        orig = dc.laning_choices

        def _counting(gs, mode="SR"):
            calls["n"] += 1
            return [_FakeChoice("A", "Trade now")]

        coach = {"champion": "Aatrox", "level": 9, "game_time_s": 330}
        lc = {"enemy_team": ["Garen"]}
        try:
            dc.laning_choices = _counting
            dc.compute_deterministic(coach, lc, "sr")
            dc.compute_deterministic(coach, lc, "sr")  # same sig within TTL
        finally:
            dc.laning_choices = orig
        self.assertEqual(calls["n"], 1, "laning_choices must be called once within TTL")

    def test_ttl_cache_recomputes_after_expiry(self) -> None:
        calls = {"n": 0}
        orig_laning = dc.laning_choices
        orig_mono = time.monotonic
        clock = {"t": 1000.0}

        def _counting(gs, mode="SR"):
            calls["n"] += 1
            return [_FakeChoice("A", "Trade now")]

        coach = {"champion": "Aatrox", "level": 9, "game_time_s": 330}
        lc = {"enemy_team": ["Garen"]}
        try:
            dc.laning_choices = _counting
            time.monotonic = lambda: clock["t"]
            dc.compute_deterministic(coach, lc, "sr")           # miss -> compute
            dc.compute_deterministic(coach, lc, "sr")           # hit (same t)
            clock["t"] = 1000.0 + dc._CACHE_TTL_S + 0.5         # fast-forward past TTL
            dc.compute_deterministic(coach, lc, "sr")           # miss -> recompute
        finally:
            dc.laning_choices = orig_laning
            time.monotonic = orig_mono
        self.assertEqual(calls["n"], 2, "must recompute after TTL expiry")


class ResolveChoicesTests(unittest.TestCase):
    """resolve_choices: deterministic-FIRST, then native, then synth, then []."""

    def test_deterministic_choices_win(self) -> None:
        det = {"choices": [{"key": "A", "label": "Trade now", "source_tag": "ds-matchup"}]}
        coach = {"action": "Push the wave"}  # would yield a synth A/B if reached
        out = dc.resolve_choices(coach, det)
        self.assertEqual(out, det["choices"])
        self.assertEqual(out[0]["source_tag"], "ds-matchup")

    def test_falls_back_to_synth_when_det_empty(self) -> None:
        det = {"choices": []}
        # An action prose with a recognizable binary verb yields a synth A/B.
        coach = {"action": "Push the wave then recall", "immediate": "shove",
                 "fight_rule": "do not face-check"}
        out = dc.resolve_choices(coach, det)
        self.assertTrue(out, "synth should produce a non-empty A/B from 'push'")
        self.assertEqual(out[0]["source_tag"], "synth")
        self.assertEqual({c["key"] for c in out}, {"A", "B"})

    def test_empty_when_no_det_and_no_actionable_prose(self) -> None:
        det = {"choices": []}
        coach = {"action": "Scale into late game"}  # no binary verb -> synth []
        out = dc.resolve_choices(coach, det)
        self.assertEqual(out, [])

    def test_fail_soft_on_garbage(self) -> None:
        # A det missing the choices key + a non-dict coach -> [] not raise.
        self.assertEqual(dc.resolve_choices(None, None), [])
        self.assertEqual(dc.resolve_choices("nope", {"choices": []}), [])


class BuildStateIntegrationTests(unittest.TestCase):
    """build_state stamps coach['choices'] deterministic-FIRST + adds 2 keys."""

    def setUp(self) -> None:
        _reset_cache()

    def tearDown(self) -> None:
        _reset_cache()

    def _patched_build_state(self, det_result):
        """Import build_state with read_json + compute_deterministic stubbed."""
        import dashboard._state_builder as sb

        orig_read = sb.read_json
        orig_lcu = sb.lcu_summary
        orig_lc = sb.liveclient_summary
        orig_team = sb.get_team_context
        orig_compute = dc.compute_deterministic
        orig_resolve = dc.resolve_choices
        try:
            # Minimal health -> mode_key "client" -> coaching_data.json.
            sb.read_json = lambda p: {} if "health" in p else {"action": "Push the wave"}
            sb.lcu_summary = lambda: {}
            sb.liveclient_summary = lambda: {}
            sb.get_team_context = lambda: None
            dc.compute_deterministic = lambda coach, lc, mk: det_result
            # resolve_choices stays REAL so we test the deterministic-FIRST logic.
            dc.resolve_choices = orig_resolve
            return sb.build_state()
        finally:
            sb.read_json = orig_read
            sb.lcu_summary = orig_lcu
            sb.liveclient_summary = orig_lc
            sb.get_team_context = orig_team
            dc.compute_deterministic = orig_compute
            dc.resolve_choices = orig_resolve

    def test_deterministic_choices_stamped_on_coach(self) -> None:
        det = {"choices": [{"key": "A", "label": "Trade now", "source_tag": "ds-matchup"}],
               "callouts": [{"tag": "dragon", "line": "Drake 5:00", "eta_s": 30.0,
                             "kind": "objective"}],
               "lead_projection": {"state": "ahead", "magnitude": "slight",
                                   "line": "press", "source_tag": "lead-proj"}}
        state = self._patched_build_state(det)
        self.assertEqual(state["coach"]["choices"], det["choices"])
        self.assertEqual(state["callouts"], det["callouts"])
        self.assertEqual(state["lead_projection"], det["lead_projection"])

    def test_falls_back_to_synth_when_det_choices_empty(self) -> None:
        # det yields no choices -> coach action prose "Push the wave" -> synth A/B.
        det = {"choices": [], "callouts": [], "lead_projection": {}}
        state = self._patched_build_state(det)
        choices = state["coach"]["choices"]
        self.assertTrue(choices, "synth A/B expected from 'Push the wave'")
        self.assertEqual(choices[0]["source_tag"], "synth")
        # Additive keys still present (empty).
        self.assertEqual(state["callouts"], [])
        self.assertEqual(state["lead_projection"], {})

    def test_new_state_keys_always_present(self) -> None:
        det = {"choices": [], "callouts": [], "lead_projection": {}}
        state = self._patched_build_state(det)
        self.assertIn("callouts", state)
        self.assertIn("lead_projection", state)


class CacheSigItemIdsTests(unittest.TestCase):
    """item 283: the coarse cache signature must include my_item_ids.

    laning_verdicts.laning_choices passes my_item_ids to matchup() as
    item_ids_a, so the verdict depends on WHICH items are owned - not just
    how many. Two states with the same item COUNT but different item IDS
    must therefore produce DISTINCT signatures, or the 3s TTL cache serves
    the first state's verdict for the second (wrong coaching on an item swap).
    """

    def test_distinct_item_ids_same_count_distinct_sig(self) -> None:
        base = {"my_champion": "Caitlyn", "enemy_comp": ["Ezreal"],
                "level": 6, "items": ["a", "b"], "game_time_s": 330}
        gs1 = {**base, "my_item_ids": ["3031", "3047"]}
        gs2 = {**base, "my_item_ids": ["3504", "3047"]}
        self.assertNotEqual(dc._cache_sig(gs1, "sr"), dc._cache_sig(gs2, "sr"))

    def test_identical_state_collapses_to_one_sig(self) -> None:
        # The cache must still HIT for a truly identical state (hit rate kept).
        base = {"my_champion": "Caitlyn", "enemy_comp": ["Ezreal"],
                "level": 6, "items": ["a", "b"], "my_item_ids": ["3031", "3047"],
                "game_time_s": 330}
        self.assertEqual(dc._cache_sig(dict(base), "sr"),
                         dc._cache_sig(dict(base), "sr"))

    def test_missing_item_ids_is_fail_soft(self) -> None:
        # No my_item_ids key -> empty id component, still a stable hashable sig.
        gs = {"my_champion": "Caitlyn", "enemy_comp": ["Ezreal"], "level": 6}
        sig = dc._cache_sig(gs, "sr")
        self.assertIsInstance(sig, tuple)
        self.assertEqual(dc._cache_sig(dict(gs), "sr"), sig)

    def test_each_output_field_changes_sig(self) -> None:
        # Sig-completeness invariant: changing ANY field that affects the
        # deterministic output MUST change the signature, or the TTL cache
        # serves a stale result for a genuinely-new state. This guards the
        # whole class of "incomplete cache key" bugs (the item-ids miss was
        # one instance).
        base = {"my_champion": "Caitlyn", "enemy_comp": ["Ezreal"], "level": 6,
                "items": ["a", "b"], "my_item_ids": ["3031", "3047"],
                "game_time_s": 330}
        base_sig = dc._cache_sig(base, "sr")
        mutations = [
            ("my_champion", "Jinx"),
            ("enemy_comp", ["Lux"]),
            ("level", 11),
            ("items", ["a", "b", "c"]),         # item_count change
            ("my_item_ids", ["3504", "3047"]),  # same count, different ids
            ("game_time_s", 330 + 6),           # crosses a 5s time bucket
        ]
        for field, val in mutations:
            gs = {**base, field: val}
            self.assertNotEqual(
                dc._cache_sig(gs, "sr"), base_sig,
                f"sig did not change when {field} changed")
        # mode is the 2nd arg, not a gs field - it must matter too.
        self.assertNotEqual(dc._cache_sig(base, "aram"), base_sig)

    def test_inhib_events_change_sig(self) -> None:
        base = {"my_champion": "Caitlyn", "enemy_comp": ["Ezreal"],
                "level": 11, "game_time_s": 700}
        with_inhib = {**base,
                      "inhib_events": [{"down_at_s": 600.0, "name": "x"}]}
        self.assertNotEqual(dc._cache_sig(with_inhib, "sr"),
                            dc._cache_sig(base, "sr"))

    def test_team_item_pools_change_sig(self) -> None:
        # The heal-threat nudge depends on the enemy + ally item pools, so a
        # change in either must change the sig (else a stale nudge is served
        # after an enemy completes a sustain item / an ally buys anti-heal).
        base = {"my_champion": "Aatrox", "enemy_comp": ["Soraka"],
                "level": 11, "game_time_s": 700}
        base_sig = dc._cache_sig(base, "sr")
        enemy_added = {**base, "enemy_item_ids": ["3072", "3074"]}
        ally_added = {**base, "ally_item_ids": ["3165"]}
        self.assertNotEqual(dc._cache_sig(enemy_added, "sr"), base_sig)
        self.assertNotEqual(dc._cache_sig(ally_added, "sr"), base_sig)
        # Order-independent (sorted) but value-sensitive.
        self.assertEqual(
            dc._cache_sig({**base, "ally_item_ids": ["3165", "3047"]}, "sr"),
            dc._cache_sig({**base, "ally_item_ids": ["3047", "3165"]}, "sr"))


class CvServedFlagTests(unittest.TestCase):
    """RC2 P5.2: the CV served override is DEFAULT-OFF. _cv_served_enabled gates
    it on RC_LANING_CV_SERVED; the off path must not pass apply_cv (byte-
    identical call), the on path passes apply_cv=True + hp_fraction."""

    def setUp(self) -> None:
        _reset_cache()
        self._prior = os.environ.get("RC_LANING_CV_SERVED")
        os.environ.pop("RC_LANING_CV_SERVED", None)

    def tearDown(self) -> None:
        _reset_cache()
        if self._prior is None:
            os.environ.pop("RC_LANING_CV_SERVED", None)
        else:
            os.environ["RC_LANING_CV_SERVED"] = self._prior

    def test_flag_default_off(self) -> None:
        self.assertFalse(dc._cv_served_enabled())

    def test_flag_truthy_values_on(self) -> None:
        for v in ("1", "true", "TRUE", "yes", "on"):
            os.environ["RC_LANING_CV_SERVED"] = v
            self.assertTrue(dc._cv_served_enabled(), v)

    def test_flag_falsey_values_off(self) -> None:
        for v in ("0", "false", "no", "off", ""):
            os.environ["RC_LANING_CV_SERVED"] = v
            self.assertFalse(dc._cv_served_enabled(), v)

    def test_off_path_does_not_pass_apply_cv(self) -> None:
        captured: dict = {}
        orig = dc.laning_choices

        def _stub(gs, mode="SR", **kw):  # noqa: ANN001, ANN003
            captured.update(kw)
            return []

        try:
            dc.laning_choices = _stub
            dc.compute_deterministic({"champion": "Aatrox"},
                                     {"enemy_team": ["Garen"]}, "sr")
        finally:
            dc.laning_choices = orig
        self.assertNotIn("apply_cv", captured)
        self.assertNotIn("hp_fraction", captured)

    def test_on_path_passes_apply_cv_true_and_hp(self) -> None:
        os.environ["RC_LANING_CV_SERVED"] = "1"
        captured: dict = {}
        orig = dc.laning_choices

        def _stub(gs, mode="SR", **kw):  # noqa: ANN001, ANN003
            captured.update(kw)
            return []

        try:
            dc.laning_choices = _stub
            coach = {"champion": "Aatrox", "hp": 50, "hp_max": 1000}
            dc.compute_deterministic(coach, {"enemy_team": ["Garen"]}, "sr")
        finally:
            dc.laning_choices = orig
        self.assertTrue(captured.get("apply_cv"))
        self.assertAlmostEqual(captured.get("hp_fraction"), 0.05)


class AsciiHygieneTests(unittest.TestCase):
    """The 2 new/edited files must be ASCII-clean in their content."""

    def _assert_ascii(self, rel: str) -> None:
        raw = (_ROOT / rel).read_bytes()
        nonascii = [b for b in raw if b > 0x7F]
        self.assertEqual(
            nonascii, [],
            f"{rel} has {len(nonascii)} non-ASCII bytes (no em-dash / smart quotes)",
        )

    def test_deterministic_coaching_module_ascii(self) -> None:
        self._assert_ascii("dashboard/_deterministic_coaching.py")

    def test_wire_test_file_ascii(self) -> None:
        self._assert_ascii("tests/test_deterministic_coaching_wire.py")


if __name__ == "__main__":
    unittest.main()
