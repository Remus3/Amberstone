"""Tests for s220 Item E phase 1 — `_enrich_match_timeline` in
dashboard/builders.py.

The parser turns a Riot Match-V5 timeline payload (which nests frames
under ``info``; a flat top-level ``frames`` list is also accepted) into
the per-minute gold/XP/CS differential series + objective ribbon the
Post Game Review "Timeline" tab renders. Diffs are ally_total −
enemy_total (positive = operator's team ahead).

Synthetic-only — no DB, no live Riot API. The numbers are hand-chosen
so the per-frame aggregation + event team-attribution assert exactly.
"""
from __future__ import annotations

import unittest

from dashboard.builders import _enrich_match_timeline


def _detail(my_team=100):
    """10 participants — pids 1-5 team 100, 6-10 team 200."""
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


if __name__ == "__main__":
    unittest.main()
