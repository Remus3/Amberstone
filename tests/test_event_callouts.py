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


class LineLengthAndAsciiTests(unittest.TestCase):
    def _all_lines(self) -> list[str]:
        lines: list[str] = []
        # Sweep a representative grid of states across all modes.
        for mode in ("sr", "aram", "arena"):
            for t in (0.0, 150.0, 305.0, 360.0, 840.0, 905.0, 1200.0, 1800.0, 2200.0):
                for lvl in (1, 5, 6, 8, 11, 16, 18):
                    for items in (0, 1, 2, 3, 4):
                        for c in _all_callouts_unbounded(mode, t, lvl, items):
                            lines.append(c["line"])
        return lines

    def test_all_lines_at_most_8_words(self):
        for line in self._all_lines():
            self.assertLessEqual(
                len(line.split()), 8,
                f"line over 8 words: {line!r}",
            )

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


if __name__ == "__main__":
    unittest.main()
