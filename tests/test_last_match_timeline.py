"""Tests for s220 Item E phase 1 - `_enrich_match_timeline` in
dashboard/builders.py.

The parser turns a Riot Match-V5 timeline payload (which nests frames
under ``info``; a flat top-level ``frames`` list is also accepted) into
the per-minute gold/XP/CS differential series + objective ribbon the
Post Game Review "Timeline" tab renders. Diffs are ally_total −
enemy_total (positive = operator's team ahead).

Synthetic-only - no DB, no live Riot API. The numbers are hand-chosen
so the per-frame aggregation + event team-attribution assert exactly.
"""
from __future__ import annotations

import unittest

from dashboard.builders import _enrich_match_timeline
from dashboard.builders_lcu_enrich import _fold_at_n_into_roster


def _detail(my_team=100):
    """10 participants - pids 1-5 team 100, 6-10 team 200."""
    parts = []
    for pid in range(1, 11):
        parts.append({"participantId": pid,
                       "teamId": 100 if pid <= 5 else 200})
    return {"participants": parts, "gameDuration": 1330}


def _pf(pid, gold, xp, minions, jungle=0):
    return {"participantId": pid, "totalGold": gold, "xp": xp,
            "minionsKilled": minions, "jungleMinionsKilled": jungle}


def _frame(ts, team100_gxp, team200_gxp, events=None):
    """team1xx_gxp = (gold, xp, minions) applied to every member."""
    pf = {}
    g1, x1, m1 = team100_gxp
    g2, x2, m2 = team200_gxp
    for pid in range(1, 6):
        pf[str(pid)] = _pf(pid, g1, x1, m1)
    for pid in range(6, 11):
        pf[str(pid)] = _pf(pid, g2, x2, m2)
    return {"timestamp": ts, "participantFrames": pf,
            "events": events or []}


class SeriesAggregationTests(unittest.TestCase):
    def test_gold_xp_cs_diffs_and_final(self):
        tl = {
            "frameInterval": 60000,
            "frames": [
                _frame(0,        (500, 0, 0),    (500, 0, 0)),
                _frame(60000,    (1000, 300, 12), (900, 250, 9)),
                _frame(120000,   (2000, 600, 20), (1500, 400, 15)),
            ],
        }
        out = _enrich_match_timeline(tl, _detail(), 100)
        # 5 members per team, diff = 5*(t100 - t200)
        self.assertEqual(out["series"]["gold"], [0, 500, 2500])
        self.assertEqual(out["series"]["xp"],   [0, 250, 1000])
        self.assertEqual(out["series"]["cs"],   [0, 15, 25])
        self.assertEqual(out["final"], {"gold": 2500, "xp": 1000, "cs": 25})
        self.assertEqual(out["minutes"], [0, 1, 2])
        self.assertEqual(out["frame_interval_ms"], 60000)
        self.assertEqual(out["duration_s"], 1330)

    def test_enemy_ahead_is_negative(self):
        tl = {"frames": [
            _frame(0,      (500, 0, 0), (500, 0, 0)),
            _frame(60000,  (800, 100, 5), (1200, 300, 11)),
        ]}
        out = _enrich_match_timeline(tl, _detail(), 100)
        self.assertEqual(out["series"]["gold"], [0, -2000])
        self.assertEqual(out["final"]["gold"], -2000)

    def test_my_team_200_flips_sign(self):
        tl = {"frames": [
            _frame(0,     (500, 0, 0), (500, 0, 0)),
            _frame(60000, (1000, 0, 0), (900, 0, 0)),
        ]}
        out = _enrich_match_timeline(tl, _detail(), 200)
        # ally is now team 200 → diff = 5*(900-1000) = -500
        self.assertEqual(out["series"]["gold"], [0, -500])

    def test_unknown_my_team_falls_back_to_first_seen(self):
        tl = {"frames": [_frame(0, (500, 0, 0), (500, 0, 0)),
                         _frame(60000, (1000, 0, 0), (900, 0, 0))]}
        out = _enrich_match_timeline(tl, _detail(), 999)
        # teams_seen sorted → [100, 200]; fallback ally=100
        self.assertEqual(out["series"]["gold"], [0, 500])


class EventRibbonTests(unittest.TestCase):
    def _run(self):
        tl = {"frames": [
            _frame(60000, (1000, 0, 0), (900, 0, 0), events=[
                {"type": "CHAMPION_KILL", "timestamp": 45000,
                 "killerId": 1, "victimId": 6},
                # second kill must NOT produce a 2nd first_blood
                {"type": "CHAMPION_KILL", "timestamp": 50000,
                 "killerId": 7, "victimId": 2},
                {"type": "ELITE_MONSTER_KILL", "timestamp": 600000,
                 "monsterType": "DRAGON", "monsterSubType": "FIRE_DRAGON",
                 "killerId": 2},
                {"type": "WARD_PLACED", "timestamp": 61000, "creatorId": 3},
            ]),
            _frame(120000, (2000, 0, 0), (1500, 0, 0), events=[
                {"type": "ELITE_MONSTER_KILL", "timestamp": 1200000,
                 "monsterType": "BARON_NASHOR", "killerTeamId": 200},
                {"type": "BUILDING_KILL", "timestamp": 1100000,
                 "buildingType": "TOWER_BUILDING", "teamId": 200,
                 "killerId": 0},
                {"type": "BUILDING_KILL", "timestamp": 1300000,
                 "buildingType": "INHIBITOR_BUILDING", "teamId": 100,
                 "killerId": 8},
            ]),
        ]}
        return _enrich_match_timeline(tl, _detail(), 100)

    def test_event_kinds_order_and_clock(self):
        evs = self._run()["events"]
        kinds = [(e["kind"], e["clock"], e["team"]) for e in evs]
        self.assertEqual(kinds, [
            ("first_blood", "0:45",  "ally"),    # killerId 1 → team 100 (mine)
            ("dragon",      "10:00", "ally"),    # killerId 2 → team 100
            ("tower",       "18:20", "ally"),    # teamId 200 LOST it → ally took
            ("baron",       "20:00", "enemy"),   # killerTeamId 200 → enemy
            ("inhibitor",   "21:40", "enemy"),   # killerId 8 → team 200
        ])

    def test_dragon_subtype_label(self):
        evs = self._run()["events"]
        drag = next(e for e in evs if e["kind"] == "dragon")
        self.assertEqual(drag["label"], "Fire Dragon")

    def test_only_one_first_blood(self):
        evs = self._run()["events"]
        self.assertEqual(sum(1 for e in evs if e["kind"] == "first_blood"), 1)

    def test_ward_event_ignored(self):
        evs = self._run()["events"]
        self.assertFalse(any("ward" in e["kind"] for e in evs))

    def test_event_cap_at_60(self):
        many = [{"type": "BUILDING_KILL", "timestamp": 60000 + i * 1000,
                 "buildingType": "TOWER_BUILDING", "teamId": 200,
                 "killerId": 0} for i in range(70)]
        tl = {"frames": [_frame(60000, (1, 0, 0), (1, 0, 0), events=many)]}
        out = _enrich_match_timeline(tl, _detail(), 100)
        self.assertEqual(len(out["events"]), 60)


class GuardTests(unittest.TestCase):
    def test_none_timeline(self):
        self.assertEqual(_enrich_match_timeline(None, _detail(), 100), {})

    def test_empty_dict(self):
        self.assertEqual(_enrich_match_timeline({}, _detail(), 100), {})

    def test_no_frames(self):
        self.assertEqual(
            _enrich_match_timeline({"frames": []}, _detail(), 100), {})

    def test_no_participants_in_detail(self):
        tl = {"frames": [_frame(0, (1, 0, 0), (1, 0, 0))]}
        self.assertEqual(_enrich_match_timeline(tl, {}, 100), {})

    def test_garbage_frame_entries_do_not_raise(self):
        tl = {"frames": [
            {"timestamp": 0, "participantFrames": {
                "1": _pf(1, 500, 0, 0),
                "2": "not-a-dict",          # skipped, no raise
                "x": {"totalGold": "junk"},  # bad pid resolves, gold→0
            }, "events": ["not-a-dict", {"type": "CHAMPION_KILL",
                                          "timestamp": 1000, "killerId": 1}]},
            {"timestamp": 60000, "participantFrames": {
                "1": _pf(1, 1000, 0, 0)}, "events": []},
        ]}
        out = _enrich_match_timeline(tl, _detail(), 100)
        self.assertEqual(len(out["series"]["gold"]), 2)
        self.assertEqual(out["events"][0]["kind"], "first_blood")

    def test_duration_falls_back_to_last_frame_ts(self):
        tl = {"frames": [_frame(0, (1, 0, 0), (1, 0, 0)),
                         _frame(180000, (2, 0, 0), (2, 0, 0))]}
        out = _enrich_match_timeline(tl, {"participants": _detail()[
            "participants"]}, 100)
        self.assertEqual(out["duration_s"], 180)


class MatchV5NestingTests(unittest.TestCase):
    """Real Match-V5 timelines nest frames + frameInterval under
    ``info``. The parser must read there first and still accept a flat
    top-level shape (the other tests use the flat form)."""

    def test_info_nested_frames_are_parsed(self):
        tl = {
            "metadata": {"matchId": "NA1_5560797021"},
            "info": {
                "frameInterval": 60000,
                "frames": [
                    _frame(0,     (500, 0, 0),    (500, 0, 0)),
                    _frame(60000, (1000, 300, 12), (900, 250, 9), events=[
                        {"type": "CHAMPION_KILL", "timestamp": 30000,
                         "killerId": 1, "victimId": 6},
                    ]),
                ],
            },
        }
        out = _enrich_match_timeline(tl, _detail(), 100)
        self.assertEqual(out["series"]["gold"], [0, 500])
        self.assertEqual(out["frame_interval_ms"], 60000)
        self.assertEqual(out["events"][0]["kind"], "first_blood")
        self.assertEqual(out["events"][0]["team"], "ally")

    def test_info_without_frames_falls_back_to_top_level(self):
        tl = {
            "info": {"gameMode": "ARAM"},   # no frames here
            "frames": [_frame(0, (1, 0, 0), (1, 0, 0)),
                       _frame(60000, (1000, 0, 0), (900, 0, 0))],
        }
        out = _enrich_match_timeline(tl, _detail(), 100)
        self.assertEqual(out["series"]["gold"], [0, 500])


class AtNSnapshotTests(unittest.TestCase):
    """PGR S5: per-participant gold@10 / cs@10 snapshot for the lane-
    comparison panel. The reducer keeps the team-aggregate series AND now
    surfaces an `at_n` block keyed by participantId, picked from the frame
    nearest the 10-minute mark (or the last frame in a short game)."""

    def _laning_frames(self):
        frames = []
        for minute in range(13):  # 0..12 min
            pf = {}
            for pid in range(1, 11):
                pf[str(pid)] = _pf(pid, gold=pid * 1000 + minute, xp=0,
                                   minions=minute, jungle=(5 if pid == 3 else 0))
            frames.append({"timestamp": minute * 60000,
                           "participantFrames": pf, "events": []})
        return {"frameInterval": 60000, "frames": frames}

    def test_at_n_picks_ten_minute_frame_per_participant(self):
        out = _enrich_match_timeline(self._laning_frames(), _detail(), 100)
        at_n = out["at_n"]
        self.assertEqual(at_n["target_minute"], 10)
        self.assertEqual(at_n["minute"], 10)
        # pid1 @10: gold 1*1000+10=1010, cs=minions(10)
        self.assertEqual(at_n["by_pid"]["1"], {"gold": 1010, "cs": 10})
        # pid3 cs folds jungle (5) -> 15
        self.assertEqual(at_n["by_pid"]["3"], {"gold": 3010, "cs": 15})
        self.assertEqual(len(at_n["by_pid"]), 10)

    def test_at_n_short_game_uses_last_frame(self):
        tl = {"frames": [_frame(0, (500, 0, 0), (500, 0, 0)),
                         _frame(60000, (1000, 0, 5), (900, 0, 4)),
                         _frame(120000, (1500, 0, 9), (1400, 0, 8))]}
        out = _enrich_match_timeline(tl, _detail(), 100)
        at_n = out["at_n"]
        self.assertEqual(at_n["minute"], 2)            # last frame, game < 10min
        self.assertEqual(at_n["by_pid"]["1"]["gold"], 1500)
        self.assertEqual(at_n["by_pid"]["1"]["cs"], 9)
        self.assertEqual(at_n["by_pid"]["6"]["gold"], 1400)

    def test_at_n_missing_keys_default_zero(self):
        tl = {"frames": [{"timestamp": 600000, "participantFrames": {
            "1": {"participantId": 1}}, "events": []}]}
        out = _enrich_match_timeline(
            tl, {"participants": [{"participantId": 1, "teamId": 100}]}, 100)
        self.assertEqual(out["at_n"]["by_pid"]["1"], {"gold": 0, "cs": 0})


class FoldAtNIntoRosterTests(unittest.TestCase):
    """The fold copies the timeline `at_n` snapshot onto each roster entry
    (gold_at_n / cs_at_n / at_n_minute) so the panel reads it straight off
    the participant row. No-op when no timeline / at_n is present."""

    def test_fold_sets_at_n_fields_by_participant(self):
        enriched = {
            "roster": [{"participant_id": 1}, {"participant_id": 6}],
            "timeline": {"at_n": {"minute": 10, "target_minute": 10,
                                  "by_pid": {"1": {"gold": 3500, "cs": 80},
                                             "6": {"gold": 3000, "cs": 70}}}},
        }
        _fold_at_n_into_roster(enriched)
        by = {p["participant_id"]: p for p in enriched["roster"]}
        self.assertEqual(by[1]["gold_at_n"], 3500)
        self.assertEqual(by[1]["cs_at_n"], 80)
        self.assertEqual(by[1]["at_n_minute"], 10)
        self.assertEqual(by[6]["gold_at_n"], 3000)

    def test_fold_noop_without_timeline(self):
        enriched = {"roster": [{"participant_id": 1}]}
        _fold_at_n_into_roster(enriched)  # must not raise
        self.assertNotIn("gold_at_n", enriched["roster"][0])

    def test_fold_noop_without_at_n(self):
        enriched = {"roster": [{"participant_id": 1}], "timeline": {}}
        _fold_at_n_into_roster(enriched)
        self.assertNotIn("gold_at_n", enriched["roster"][0])


if __name__ == "__main__":
    unittest.main()
