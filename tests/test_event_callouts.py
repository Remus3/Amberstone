# arch: tests for the deterministic event-milestone callout DB | section=tests | frozen=no
"""Property-style tests for core/event_callouts.py.

The callout DB is PURE (no network, no LLM, no engine) so every case is
a plain input -> output assertion. Tests cover: SR objective schedule,
dragon-active/respawn window, level-spike active vs next-spike, item-spike
firing, ARAM/Arena objective exclusion, max_n cap + sort order, line
length + ASCII hygiene, and fail-soft on bad input.
"""
from __future__ import annotations

import unittest

from core.event_callouts import (
    _inhib_lane,
    dragon_soul_callout,
    epic_buff_callouts,
    inhibitor_callouts,
    milestone_line,
    next_callouts,
)


def _by_tag(callouts: list[dict], tag: str) -> dict | None:
    """Find the first callout with the given tag, or None."""
    for c in callouts:
        if c.get("tag") == tag:
            return c
    return None


def _all_callouts_unbounded(mode, t, lvl, items):
    """Call next_callouts with a large cap so nothing is dropped by max_n."""
    return next_callouts(mode, t, lvl, items, max_n=99)


class SrObjectiveScheduleTests(unittest.TestCase):
    def test_t0_sr_includes_first_drake_eta_300(self):
        cs = _all_callouts_unbounded("sr", 0.0, 1, 0)
        drake = _by_tag(cs, "dragon")
        self.assertIsNotNone(drake, "first drake objective must be present at t=0")
        self.assertEqual(drake["kind"], "objective")
        self.assertAlmostEqual(drake["eta_s"], 300.0, delta=0.01)

    def test_drake_is_top_callout_at_t0(self):
        # Numeric-eta objective must outrank None-eta spikes (bucket sort).
        cs = next_callouts("sr", 0.0, 1, 0, max_n=3)
        self.assertEqual(cs[0]["tag"], "dragon")

    def test_baron_eta_1200_at_t0(self):
        cs = _all_callouts_unbounded("sr", 0.0, 1, 0)
        baron = _by_tag(cs, "baron")
        self.assertIsNotNone(baron)
        self.assertAlmostEqual(baron["eta_s"], 1200.0, delta=0.01)

    def test_herald_and_plates_eta_840_at_t0(self):
        cs = _all_callouts_unbounded("sr", 0.0, 1, 0)
        for tag in ("herald", "plates"):
            obj = _by_tag(cs, tag)
            self.assertIsNotNone(obj, f"{tag} must be present at t=0")
            self.assertAlmostEqual(obj["eta_s"], 840.0, delta=0.01)


class DragonActiveAndRespawnTests(unittest.TestCase):
    def test_drake_active_just_after_spawn(self):
        # At 305s (5s after 300s spawn) drake should read active (eta_s <= 0).
        cs = _all_callouts_unbounded("sr", 305.0, 6, 1)
        drake = _by_tag(cs, "dragon")
        self.assertIsNotNone(drake)
        self.assertLessEqual(drake["eta_s"], 0.0)

    def test_drake_next_after_active_window(self):
        # At 360s (60s past spawn, beyond the 30s active window) the next
        # drake on the 5min cadence is at 600s -> eta 240.
        cs = _all_callouts_unbounded("sr", 360.0, 6, 1)
        drake = _by_tag(cs, "dragon")
        self.assertIsNotNone(drake)
        self.assertGreater(drake["eta_s"], 0.0)
        self.assertAlmostEqual(drake["eta_s"], 240.0, delta=0.01)

    def test_drake_respawn_cadence_late_game(self):
        # At 905s: first 300, then 600, then 900 spawned. 905 is 5s past
        # the 900s spawn -> active.
        cs = _all_callouts_unbounded("sr", 905.0, 11, 2)
        drake = _by_tag(cs, "dragon")
        self.assertIsNotNone(drake)
        self.assertLessEqual(drake["eta_s"], 0.0)


class LevelSpikeTests(unittest.TestCase):
    def test_level_6_is_active_spike(self):
        cs = _all_callouts_unbounded("sr", 400.0, 6, 1)
        spike = _by_tag(cs, "lvl6")
        self.assertIsNotNone(spike)
        self.assertEqual(spike["kind"], "level_spike")
        self.assertEqual(spike["eta_s"], 0.0)

    def test_level_5_next_spike_is_6(self):
        cs = _all_callouts_unbounded("sr", 300.0, 5, 1)
        spike = _by_tag(cs, "lvl6")
        self.assertIsNotNone(spike)
        self.assertIsNone(spike["eta_s"])
        self.assertIn("lvl-6", spike["line"])

    def test_level_11_active_and_16_pending(self):
        cs = _all_callouts_unbounded("sr", 900.0, 11, 3)
        s11 = _by_tag(cs, "lvl11")
        s16 = _by_tag(cs, "lvl16")
        self.assertIsNotNone(s11)
        self.assertEqual(s11["eta_s"], 0.0)
        self.assertIsNotNone(s16)
        self.assertIsNone(s16["eta_s"])

    def test_passed_level_spike_dropped(self):
        # At level 8, the lvl6 spike is passed and not current -> absent.
        cs = _all_callouts_unbounded("sr", 600.0, 8, 2)
        self.assertIsNone(_by_tag(cs, "lvl6"))


class ItemSpikeTests(unittest.TestCase):
    def test_item_count_1_fires_spike(self):
        cs = _all_callouts_unbounded("sr", 400.0, 6, 1)
        spike = _by_tag(cs, "item1")
        self.assertIsNotNone(spike)
        self.assertEqual(spike["kind"], "item_spike")
        self.assertEqual(spike["eta_s"], 0.0)

    def test_item_count_2_fires_spike(self):
        cs = _all_callouts_unbounded("sr", 700.0, 9, 2)
        spike = _by_tag(cs, "item2")
        self.assertIsNotNone(spike)
        self.assertEqual(spike["eta_s"], 0.0)

    def test_item_count_3_fires_spike(self):
        cs = _all_callouts_unbounded("sr", 1000.0, 12, 3)
        spike = _by_tag(cs, "item3")
        self.assertIsNotNone(spike)
        self.assertEqual(spike["eta_s"], 0.0)

    def test_item_count_0_next_is_1(self):
        cs = _all_callouts_unbounded("sr", 60.0, 2, 0)
        spike = _by_tag(cs, "item1")
        self.assertIsNotNone(spike)
        self.assertIsNone(spike["eta_s"])

    def test_passed_item_spike_dropped(self):
        # 4 items owned -> all of 1/2/3 are passed -> none present.
        cs = _all_callouts_unbounded("sr", 1200.0, 14, 4)
        for n in (1, 2, 3):
            self.assertIsNone(_by_tag(cs, f"item{n}"))


class ModeObjectiveExclusionTests(unittest.TestCase):
    def test_aram_has_no_neutral_objectives(self):
        cs = _all_callouts_unbounded("aram", 300.0, 6, 1)
        for tag in ("dragon", "herald", "baron", "plates", "elder"):
            self.assertIsNone(
                _by_tag(cs, tag),
                f"ARAM must not return neutral objective {tag}",
            )

    def test_aram_still_has_spikes(self):
        cs = _all_callouts_unbounded("aram", 300.0, 6, 1)
        self.assertIsNotNone(_by_tag(cs, "lvl6"))
        self.assertIsNotNone(_by_tag(cs, "item1"))

    def test_arena_has_no_map_objectives(self):
        cs = _all_callouts_unbounded("arena", 300.0, 6, 1)
        for tag in ("dragon", "herald", "baron", "plates", "elder"):
            self.assertIsNone(
                _by_tag(cs, tag),
                f"Arena must not return map objective {tag}",
            )

    def test_arena_still_has_spikes(self):
        cs = _all_callouts_unbounded("arena", 300.0, 6, 2)
        self.assertIsNotNone(_by_tag(cs, "lvl6"))
        self.assertIsNotNone(_by_tag(cs, "item2"))


class CapAndSortTests(unittest.TestCase):
    def test_max_n_caps_length(self):
        cs = next_callouts("sr", 0.0, 1, 0, max_n=2)
        self.assertEqual(len(cs), 2)

    def test_max_n_default_is_3(self):
        cs = next_callouts("sr", 0.0, 1, 0)
        self.assertLessEqual(len(cs), 3)

    def test_active_sorts_before_upcoming(self):
        # At level 6 with 1 item just after drake spawn: actives (drake,
        # lvl6, item1) must precede any numeric-future objective.
        cs = _all_callouts_unbounded("sr", 305.0, 6, 1)
        # find first non-active index
        seen_future = False
        for c in cs:
            eta = c["eta_s"]
            is_active = eta is not None and eta <= 0
            if seen_future:
                self.assertFalse(
                    is_active,
                    "an active callout appeared after a non-active one",
                )
            if not is_active:
                seen_future = True

    def test_numeric_eta_sorts_before_none_eta(self):
        # baron (numeric eta) must precede any None-eta spike in the list.
        cs = _all_callouts_unbounded("sr", 0.0, 1, 0)
        idx_baron = next(i for i, c in enumerate(cs) if c["tag"] == "baron")
        none_idxs = [i for i, c in enumerate(cs) if c["eta_s"] is None]
        if none_idxs:
            self.assertLess(idx_baron, min(none_idxs))

    def test_ascending_eta_within_numeric_bucket(self):
        cs = _all_callouts_unbounded("sr", 0.0, 1, 0)
        numeric = [c["eta_s"] for c in cs if c["eta_s"] is not None and c["eta_s"] > 0]
        self.assertEqual(numeric, sorted(numeric))


# Per-kind word budget. The DEFAULT is 8; a kind may exceed it only with an
# entry here, and that entry is itself a bound, not a waiver - a new line in an
# exempt kind still fails if it goes past the kind's number. Both exemptions
# are measured, not guessed (lane 8 cycle 44).
_DEFAULT_WORD_BUDGET = 8
_KIND_WORD_BUDGET: dict[str, int] = {
    # structure_siege_callout ships two deliberately long instant-bridge
    # lines: 15 and 13 words. Whether the panel should carry a 15-word line
    # at all is a UI question filed for lane 4 (RM-304), not a test question.
    "siege": 15,
    # dragon_soul_callout: the enemy soul-point line is 10 words, which is
    # also the budget the module states for its own sided lines at :93.
    "dragon_soul": 10,
}
# Tags allowed to use an over-budget kind. Pinned EXACTLY so a NEW long line
# cannot hide behind an existing kind's exemption. Measured, not guessed.
_OVER_BUDGET_TAGS = {
    "siege_inhib", "siege_turret",
    "soul_secured_enemy", "soul_point_ally", "soul_point_enemy",
    "soul_race_enemy",
}


class LineLengthAndAsciiTests(unittest.TestCase):
    """DOMAIN NOTE (lane 8 cycle 44). This sweep used to call
    ``_all_callouts_unbounded`` with NO event kwargs, so it only ever saw the
    static objective + level-spike + item-spike lines - three of the eight
    kinds next_callouts emits. The guard was named "all lines" and graded a
    third of them, which is why two 13-to-15-word siege lines shipped past it.
    The sweep below drives every event list, so ``siege``, ``inhibitor``,
    ``epic_buff``, ``recall``, ``wave`` and ``dragon_soul`` are all in scope.
    """

    def _all_rows(self) -> list[dict]:
        """Every row the module can emit across a representative grid."""
        rows: list[dict] = []
        for mode in ("sr", "aram", "arena"):
            for t in (0.0, 150.0, 305.0, 360.0, 840.0, 905.0, 1200.0, 1800.0, 2200.0):
                for lvl in (1, 5, 6, 8, 11, 16, 18):
                    for items in (0, 1, 2, 3, 4):
                        rows.extend(next_callouts(
                            mode, t, lvl, items, max_n=99,
                            gold=99999, next_item_name="Rabadon's Deathcap",
                            next_item_cost=100,
                            objective_events=[
                                {"name": "baron", "killer_team": "ally",
                                 "down_at_s": max(t - 30.0, 0.0)},
                                {"name": "dragon", "killer_team": "enemy",
                                 "down_at_s": max(t - 40.0, 0.0),
                                 "dragon_type": "Fire"},
                                {"name": "dragon", "killer_team": "ally",
                                 "down_at_s": max(t - 50.0, 0.0),
                                 "dragon_type": "Ocean"}],
                            inhib_events=[{"name": "Barracks_T1L1",
                                           "down_at_s": max(t - 10.0, 0.0)}],
                            turret_events=[{"name": "Turret_T2_L_03_A",
                                            "down_at_s": max(t - 5.0, 0.0)}],
                            minion_events=[{"at_s": 65.0}],
                            enable_wave=True))
        # dragon_soul_callout is reached by dashboard/_deterministic_coaching
        # directly, never through next_callouts, so it needs its own probe or
        # it stays outside the guard exactly as the siege lines used to.
        # BOTH sides and all three soul states - an ally-only probe reaches
        # four of the six soul lines and misses the 10-word enemy one.
        for side in ("ally", "enemy"):
            for n in (2, 3, 4):
                soul = dragon_soul_callout([
                    {"name": "dragon", "killer_team": side,
                     "down_at_s": 100.0 + i, "dragon_type": "Fire"}
                    for i in range(n)])
                if soul is not None:
                    rows.append(soul)
        return rows

    def _all_lines(self) -> list[str]:
        return [r["line"] for r in self._all_rows()]

    def test_sweep_actually_reaches_every_kind(self):
        """Guard on the guard: if the sweep stops producing a kind, the
        budget test silently narrows again and nobody notices."""
        kinds = {r["kind"] for r in self._all_rows()}
        for expected in ("objective", "level_spike", "item_spike", "recall",
                         "epic_buff", "inhibitor", "siege", "wave",
                         "dragon_soul"):
            self.assertIn(expected, kinds,
                          f"sweep no longer emits {expected!r} - the line "
                          f"budget guard has narrowed. Kinds: {sorted(kinds)}")

    def test_all_lines_within_their_kind_word_budget(self):
        for row in self._all_rows():
            kind = row.get("kind", "")
            budget = _KIND_WORD_BUDGET.get(kind, _DEFAULT_WORD_BUDGET)
            words = len(row["line"].split())
            self.assertLessEqual(
                words, budget,
                f"{kind} line over its {budget}-word budget "
                f"({words} words): {row['line']!r}")
            if budget > _DEFAULT_WORD_BUDGET and words > _DEFAULT_WORD_BUDGET:
                self.assertIn(
                    row.get("tag"), _OVER_BUDGET_TAGS,
                    f"tag {row.get('tag')!r} is using the {kind!r} "
                    f"over-budget exemption but is not on the pinned list")

    def test_all_lines_ascii(self):
        for line in self._all_lines():
            self.assertEqual(
                line, line.encode("ascii", "ignore").decode("ascii"),
                f"non-ASCII byte in line: {line!r}",
            )

    def test_module_source_is_ascii(self):
        import core.event_callouts as mod

        with open(mod.__file__, "rb") as fh:
            raw = fh.read()
        non_ascii = [b for b in raw if b > 127]
        self.assertEqual(non_ascii, [], "module source has non-ASCII bytes")


class FailSoftTests(unittest.TestCase):
    def test_unknown_mode_returns_empty(self):
        self.assertEqual(next_callouts("tft", 300.0, 6, 1), [])
        self.assertEqual(next_callouts("brawl", 300.0, 6, 1), [])
        self.assertEqual(next_callouts("nonsense", 0.0, 1, 0), [])

    def test_non_str_mode_returns_empty(self):
        self.assertEqual(next_callouts(None, 300.0, 6, 1), [])  # type: ignore[arg-type]
        self.assertEqual(next_callouts(123, 300.0, 6, 1), [])  # type: ignore[arg-type]

    def test_bad_numeric_inputs_do_not_raise(self):
        # None / garbage time, level, items -> coerced, no exception.
        out = next_callouts("sr", None, None, None)  # type: ignore[arg-type]
        self.assertIsInstance(out, list)
        out2 = next_callouts("sr", "x", "y", "z")  # type: ignore[arg-type]
        self.assertIsInstance(out2, list)

    def test_max_n_zero_returns_empty(self):
        self.assertEqual(next_callouts("sr", 0.0, 1, 0, max_n=0), [])

    def test_negative_max_n_returns_full_list(self):
        full = next_callouts("sr", 0.0, 1, 0, max_n=-1)
        self.assertGreater(len(full), 3)


class MilestoneLineTests(unittest.TestCase):
    def test_objective_tags_resolve(self):
        for tag in ("dragon", "herald", "baron", "plates", "elder"):
            self.assertTrue(milestone_line(tag), f"{tag} should resolve a line")

    def test_level_spike_tags_resolve(self):
        for tag in ("lvl6", "lvl11", "lvl16"):
            self.assertIn("spike", milestone_line(tag))

    def test_item_spike_tags_resolve(self):
        for tag in ("item1", "item2", "item3"):
            self.assertIn("spike", milestone_line(tag))

    def test_unknown_tag_returns_empty(self):
        self.assertEqual(milestone_line("lvl99"), "")
        self.assertEqual(milestone_line("item9"), "")
        self.assertEqual(milestone_line("garbage"), "")
        self.assertEqual(milestone_line(None), "")  # type: ignore[arg-type]
        self.assertEqual(milestone_line(42), "")  # type: ignore[arg-type]


class InhibitorCalloutTests(unittest.TestCase):
    """Inhibitor respawn callouts - correct-by-construction 300s timing,
    no team-side claim so a callout can never be backwards."""

    def test_fresh_inhib_gives_respawn_eta_and_lane(self):
        # Fell at 600s, now 700s -> respawn 900s -> eta 200s; top lane.
        out = inhibitor_callouts(
            [{"down_at_s": 600.0, "name": "Barracks_T2_L1"}], 700.0)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["kind"], "inhibitor")
        self.assertAlmostEqual(out[0]["eta_s"], 200.0)
        self.assertIn("top", out[0]["line"])

    def test_respawned_inhib_is_dropped(self):
        # Fell at 600s, now 950s -> respawn was 900s, already back -> dropped.
        out = inhibitor_callouts(
            [{"down_at_s": 600.0, "name": "Barracks_T1_C1"}], 950.0)
        self.assertEqual(out, [])

    def test_lane_parse_variants(self):
        self.assertEqual(_inhib_lane("Barracks_T2_L1"), "top")
        self.assertEqual(_inhib_lane("Barracks_T1_C1"), "mid")
        self.assertEqual(_inhib_lane("Barracks_T2_R1"), "bot")
        self.assertEqual(_inhib_lane("weird_name"), "")
        self.assertEqual(_inhib_lane(None), "")

    def test_unknown_name_is_generic_never_wrong(self):
        out = inhibitor_callouts([{"down_at_s": 100.0, "name": "???"}], 200.0)
        self.assertEqual(len(out), 1)
        self.assertNotIn("(", out[0]["line"])  # no lane parenthetical

    def test_fail_soft_on_bad_input(self):
        self.assertEqual(inhibitor_callouts(None, 100.0), [])
        self.assertEqual(inhibitor_callouts("nope", 100.0), [])
        self.assertEqual(inhibitor_callouts([{"name": "x"}], 100.0), [])
        self.assertEqual(inhibitor_callouts([42], 100.0), [])

    def test_sr_only_via_next_callouts(self):
        ev = [{"down_at_s": 600.0, "name": "Barracks_T2_L1"}]
        sr = next_callouts("sr", 700.0, 6, 1, max_n=99, inhib_events=ev)
        aram = next_callouts("aram", 700.0, 6, 1, max_n=99, inhib_events=ev)
        self.assertTrue(any(c["kind"] == "inhibitor" for c in sr))
        self.assertFalse(any(c["kind"] == "inhibitor" for c in aram))


class EpicBuffCalloutTests(unittest.TestCase):
    """Baron/Elder buff-expiry countdowns - correct-by-construction fixed-window
    timing keyed by killer side (the side IS the value, so an unsided buff drops)."""

    def test_ally_baron_buff_countdown(self):
        # Baron taken by ally at 1200s, now 1260s -> 180s window -> 120s left.
        out = epic_buff_callouts(
            [{"name": "baron", "killer_team": "ally", "down_at_s": 1200.0}], 1260.0)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["kind"], "epic_buff")
        self.assertAlmostEqual(out[0]["eta_s"], 120.0)
        self.assertIn("ally", out[0]["tag"])
        # ally directive is proactive (take towers / objectives), not defensive.
        self.assertNotIn("face-check", out[0]["line"].lower())

    def test_enemy_baron_buff_defend(self):
        # Enemy baron at 1200s, now 1300s -> 80s left; defensive directive.
        out = epic_buff_callouts(
            [{"name": "baron", "killer_team": "enemy", "down_at_s": 1200.0}], 1300.0)
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0]["eta_s"], 80.0)
        self.assertIn("enemy", out[0]["tag"])
        self.assertIn("face-check", out[0]["line"].lower())

    def test_expired_baron_dropped(self):
        # Baron at 1200s, now 1400s -> window ended at 1380s -> dropped.
        out = epic_buff_callouts(
            [{"name": "baron", "killer_team": "ally", "down_at_s": 1200.0}], 1400.0)
        self.assertEqual(out, [])

    def test_elder_buff_via_dragon_type(self):
        # Elder is a DragonKill (name=='dragon') with dragon_type 'Elder';
        # 150s window. Ally elder at 2000s, now 2050s -> 100s left.
        out = epic_buff_callouts(
            [{"name": "dragon", "dragon_type": "Elder", "killer_team": "ally",
              "down_at_s": 2000.0}], 2050.0)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["kind"], "epic_buff")
        self.assertAlmostEqual(out[0]["eta_s"], 100.0)
        self.assertIn("elder", out[0]["tag"])

    def test_elemental_dragon_not_epic_buff(self):
        # Elemental drakes grant no expiring TEAM buff -> not an epic-buff event.
        out = epic_buff_callouts(
            [{"name": "dragon", "dragon_type": "Fire", "killer_team": "enemy",
              "down_at_s": 1200.0}], 1260.0)
        self.assertEqual(out, [])
        # A dragon with no type at all is also not an epic buff.
        out2 = epic_buff_callouts(
            [{"name": "dragon", "killer_team": "enemy", "down_at_s": 1200.0}], 1260.0)
        self.assertEqual(out2, [])

    def test_unknown_side_dropped(self):
        # The side drives the directive (defend vs take); an unsided buff is
        # dropped rather than rendered ambiguously.
        out = epic_buff_callouts(
            [{"name": "baron", "killer_team": "unknown", "down_at_s": 1200.0}], 1260.0)
        self.assertEqual(out, [])

    def test_fail_soft_on_bad_input(self):
        self.assertEqual(epic_buff_callouts(None, 100.0), [])
        self.assertEqual(epic_buff_callouts("nope", 100.0), [])
        self.assertEqual(epic_buff_callouts([42], 100.0), [])
        # Missing down_at_s -> skipped, not raised.
        self.assertEqual(
            epic_buff_callouts([{"name": "baron", "killer_team": "ally"}], 100.0), [])

    def test_sr_only_via_next_callouts(self):
        ev = [{"name": "baron", "killer_team": "ally", "down_at_s": 1200.0}]
        sr = next_callouts("sr", 1260.0, 14, 3, max_n=99, objective_events=ev)
        aram = next_callouts("aram", 1260.0, 14, 3, max_n=99, objective_events=ev)
        self.assertTrue(any(c["kind"] == "epic_buff" for c in sr))
        self.assertFalse(any(c["kind"] == "epic_buff" for c in aram))


class DragonSoulCalloutTests(unittest.TestCase):
    """Per-side elemental-drake count -> the single 3-stack 'soul point' row.
    Soul locks on the 4th drake, so EXACTLY 3 means the next drake is SOUL."""

    @staticmethod
    def _drake(side: str, dtype: str = "Fire", t: float = 600.0) -> dict:
        return {"name": "dragon", "killer_team": side, "dragon_type": dtype,
                "down_at_s": t}

    def test_ally_at_soul_point(self):
        evs = [self._drake("ally", "Fire"), self._drake("ally", "Earth"),
               self._drake("ally", "Cloud")]
        out = dragon_soul_callout(evs)
        self.assertIsNotNone(out)
        self.assertEqual(out["kind"], "dragon_soul")
        self.assertIn("ally", out["tag"])
        self.assertIsNone(out["eta_s"])
        self.assertIn("force", out["line"].lower())

    def test_enemy_at_soul_point(self):
        evs = [self._drake("enemy"), self._drake("enemy", "Earth"),
               self._drake("enemy", "Cloud")]
        out = dragon_soul_callout(evs)
        self.assertIsNotNone(out)
        self.assertIn("enemy", out["tag"])
        self.assertIn("deny", out["line"].lower())

    def test_enemy_outranks_ally_when_both_at_point(self):
        # Degenerate (both at 3); the defensive deny takes the single slot.
        evs = [self._drake("ally"), self._drake("ally", "Earth"),
               self._drake("ally", "Cloud"),
               self._drake("enemy"), self._drake("enemy", "Earth"),
               self._drake("enemy", "Cloud")]
        out = dragon_soul_callout(evs)
        self.assertIn("enemy", out["tag"])

    def test_two_zero_is_soul_race_lead(self):
        # Follow-on: a >=2-drake lead with no one at the point surfaces the race.
        evs = [self._drake("ally"), self._drake("ally", "Earth")]
        out = dragon_soul_callout(evs)
        self.assertIsNotNone(out)
        self.assertEqual(out["kind"], "dragon_soul")
        self.assertIn("soul_race", out["tag"])
        self.assertIn("ally", out["tag"])
        self.assertIn("2-0", out["line"])

    def test_behind_on_race_from_operator_pov(self):
        evs = [self._drake("enemy"), self._drake("enemy", "Earth")]
        out = dragon_soul_callout(evs)
        self.assertIn("soul_race_enemy", out["tag"])
        self.assertIn("0-2", out["line"])          # always ally-enemy ordering
        self.assertIn("behind", out["line"].lower())

    def test_even_or_one_drake_no_row(self):
        self.assertIsNone(dragon_soul_callout([]))                       # 0-0
        self.assertIsNone(dragon_soul_callout([self._drake("ally")]))    # 1-0 early
        self.assertIsNone(dragon_soul_callout(                            # 2-2 tie
            [self._drake("ally"), self._drake("ally", "Earth"),
             self._drake("enemy"), self._drake("enemy", "Earth")]))

    def test_four_drakes_is_soul_secured_not_point(self):
        # Follow-on: 4 elemental = soul SECURED -> a locked-element row (not the
        # "next drake is SOUL" point row).
        evs = [self._drake("ally", "Fire", 400.0),
               self._drake("ally", "Earth", 800.0),
               self._drake("ally", "Cloud", 1200.0),
               self._drake("ally", "Mountain", 1600.0)]
        out = dragon_soul_callout(evs)
        self.assertIsNotNone(out)
        self.assertIn("soul_secured_ally", out["tag"])
        self.assertIn("SOUL", out["line"])
        self.assertIn("Mountain", out["line"])     # latest drake = locked element

    def test_enemy_soul_secured_outranks_ally_point(self):
        # enemy has soul (4) while ally is at the point (3) -> the live enemy
        # soul is the headline.
        evs = [self._drake("enemy", "Fire"), self._drake("enemy", "Earth"),
               self._drake("enemy", "Cloud"), self._drake("enemy", "Ocean"),
               self._drake("ally", "Fire"), self._drake("ally", "Earth"),
               self._drake("ally", "Cloud")]
        out = dragon_soul_callout(evs)
        self.assertIn("soul_secured_enemy", out["tag"])

    def test_elder_does_not_count_toward_soul(self):
        # 3 elemental + an Elder for the same side is still 3 elemental.
        evs = [self._drake("ally"), self._drake("ally", "Earth"),
               self._drake("ally", "Cloud"), self._drake("ally", "Elder")]
        out = dragon_soul_callout(evs)
        self.assertIsNotNone(out)
        self.assertIn("soul_point_ally", out["tag"])
        # And an Elder-only side never reads as a soul point or race.
        self.assertIsNone(dragon_soul_callout([self._drake("enemy", "Elder")]))

    def test_unknown_killer_not_attributed(self):
        # 3 ally + 1 unknown -> ally counts 3 (soul point), NOT 4 (secured):
        # the unresolved drake is not attributed.
        evs = [self._drake("ally"), self._drake("ally", "Earth"),
               self._drake("ally", "Cloud"), self._drake("unknown", "Ocean")]
        out = dragon_soul_callout(evs)
        self.assertIn("soul_point_ally", out["tag"])

    def test_baron_events_ignored(self):
        evs = [{"name": "baron", "killer_team": "ally", "down_at_s": 1200.0},
               self._drake("ally"), self._drake("ally", "Earth"),
               self._drake("ally", "Cloud")]
        out = dragon_soul_callout(evs)
        self.assertIn("ally", out["tag"])  # baron does not perturb the count

    def test_fail_soft_on_bad_input(self):
        self.assertIsNone(dragon_soul_callout(None))
        self.assertIsNone(dragon_soul_callout("nope"))
        self.assertIsNone(dragon_soul_callout([42, None, "x"]))
        self.assertIsNone(dragon_soul_callout([]))


class DynamicObjectiveRespawnTests(unittest.TestCase):
    """L3: drake/baron ETA tracks the REAL last-take (last_kill + respawn) once
    a kill event exists, replacing the static game-start cadence. The no-events
    path stays byte-identical (characterization guard)."""

    @staticmethod
    def _drake(side="ally", dtype="Fire", t=450.0):
        return {"name": "dragon", "killer_team": side, "dragon_type": dtype,
                "down_at_s": t}

    # -- characterization: the static path is preserved without real events ----
    def test_characterization_static_when_no_events(self):
        cs = next_callouts("sr", 700.0, 6, 1, max_n=99)
        drake = _by_tag(cs, "dragon")
        self.assertAlmostEqual(drake["eta_s"], 200.0, delta=0.01)  # 900-grid - 700

    def test_empty_events_identical_to_no_events(self):
        no_ev = _by_tag(next_callouts("sr", 700.0, 6, 1, max_n=99), "dragon")
        empty = _by_tag(
            next_callouts("sr", 700.0, 6, 1, max_n=99, objective_events=[]), "dragon")
        self.assertAlmostEqual(no_ev["eta_s"], empty["eta_s"], delta=0.01)

    # -- dynamic: real take drives the ETA -------------------------------------
    def test_dragon_respawn_tracks_real_take(self):
        # Drake taken at 450, now 700 -> next = 450+300 = 750 -> eta 50,
        # NOT the static 5min-grid eta of 200.
        cs = next_callouts("sr", 700.0, 6, 1, max_n=99,
                           objective_events=[self._drake(t=450.0)])
        drake = _by_tag(cs, "dragon")
        self.assertAlmostEqual(drake["eta_s"], 50.0, delta=0.01)

    def test_dragon_up_when_respawn_passed(self):
        # Taken at 450, now 800 -> next 750 already passed -> drake UP (eta<=0).
        cs = next_callouts("sr", 800.0, 6, 1, max_n=99,
                           objective_events=[self._drake(t=450.0)])
        drake = _by_tag(cs, "dragon")
        self.assertLessEqual(drake["eta_s"], 0.0)

    def test_baron_respawn_eta_after_take(self):
        # Baron taken at 1300, now 1400 -> next = 1300+360 = 1660 -> eta 260.
        # (Static path treats baron as a one-shot at 1200 and drops it here.)
        cs = next_callouts("sr", 1400.0, 14, 3, max_n=99, objective_events=[
            {"name": "baron", "killer_team": "enemy", "down_at_s": 1300.0}])
        baron = _by_tag(cs, "baron")
        self.assertIsNotNone(baron)
        self.assertAlmostEqual(baron["eta_s"], 260.0, delta=0.01)

    def test_baron_up_when_respawn_passed(self):
        cs = next_callouts("sr", 1700.0, 16, 4, max_n=99, objective_events=[
            {"name": "baron", "killer_team": "ally", "down_at_s": 1300.0}])
        baron = _by_tag(cs, "baron")
        self.assertIsNotNone(baron)
        self.assertLessEqual(baron["eta_s"], 0.0)

    def test_soul_secured_suppresses_drake_row(self):
        # 4 elemental drakes -> soul taken, the pit spawns Elder, so there is no
        # elemental-drake row to time.
        evs = [self._drake(dtype="Fire", t=400.0),
               self._drake(dtype="Earth", t=800.0),
               self._drake(dtype="Cloud", t=1200.0),
               self._drake(dtype="Mountain", t=1600.0)]
        cs = next_callouts("sr", 1700.0, 16, 4, max_n=99, objective_events=evs)
        self.assertIsNone(_by_tag(cs, "dragon"))

    def test_elder_kill_does_not_anchor_drake_timer(self):
        # An Elder kill is NOT an elemental take; the drake row must NOT key off
        # it (would give eta 200 = 2000+300-2100). With no elemental kill it
        # falls back to the static cadence (active at 2100).
        cs = next_callouts("sr", 2100.0, 16, 4, max_n=99, objective_events=[
            self._drake(dtype="Elder", t=2000.0)])
        drake = _by_tag(cs, "dragon")
        self.assertIsNotNone(drake)
        self.assertLessEqual(drake["eta_s"], 0.0)  # static-active, not eta 200


class CadenceConstantReconciliationTests(unittest.TestCase):
    """L3: the drake/baron spawn constants live in ONE place (event_callouts)
    and core.decision_detector imports them - the two paths cannot drift."""

    def test_decision_detector_imports_canonical_constants(self):
        from core import decision_detector, event_callouts
        self.assertEqual(decision_detector._DRAGON_FIRST_S,
                         event_callouts.SR_DRAGON_FIRST_S)
        self.assertEqual(decision_detector._DRAGON_RESPAWN_S,
                         event_callouts.SR_DRAGON_RESPAWN_S)
        self.assertEqual(decision_detector._BARON_FIRST_S,
                         event_callouts.SR_BARON_FIRST_S)
        self.assertEqual(decision_detector._BARON_RESPAWN_S,
                         event_callouts.SR_BARON_RESPAWN_S)


if __name__ == "__main__":
    unittest.main()
