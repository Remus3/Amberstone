"""Tests for core/post_game_score.py.

Exercises:
  - calculate_tif piecewise math vs LoLytics formula
  - calculate_death_timer BRW table + tif uplift
  - Pure-Python LR training converges on a trivial separable dataset
  - WpaModel persistence round-trip (save -> load -> identical)
  - Fallback estimator monotonic in gold_diff
  - predict_prob length-mismatch returns 0.5 (no raise)
  - Strong-event filter excludes LEVEL_UP and minion-killed monsters
  - Per-team participant resolver
  - State machine: CHAMPION_KILL / BUILDING_KILL / ELITE_MONSTER_KILL
  - compute_match_wpa on a synthetic SQLite timeline
"""
from __future__ import annotations

import json
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import post_game_score as pgs


class TestCalculateTif(unittest.TestCase):
    """LoLytics calculate_tif piecewise. Source: model/game.py."""

    def test_zero_under_15_minutes(self):
        for t in (0, 1, 5, 14.99):
            self.assertEqual(pgs.calculate_tif(t), 0.0)

    def test_band_15_to_30(self):
        # math.ceil(2 * (15 - 15)) * 0.425 = 0
        self.assertAlmostEqual(pgs.calculate_tif(15), 0.0)
        # math.ceil(2 * (20 - 15)) = 10; 10 * 0.425 = 4.25
        self.assertAlmostEqual(pgs.calculate_tif(20), 4.25)
        # math.ceil(2 * (29.9 - 15)) = ceil(29.8) = 30; 30*0.425 = 12.75
        self.assertAlmostEqual(pgs.calculate_tif(29.9), 12.75)

    def test_band_30_to_45(self):
        # base 12.75 + ceil(2*(30-30))*0.3 = 12.75
        self.assertAlmostEqual(pgs.calculate_tif(30), 12.75)
        # 12.75 + ceil(2*(35-30))*0.3 = 12.75 + 10*0.3 = 15.75
        self.assertAlmostEqual(pgs.calculate_tif(35), 15.75)
        # 12.75 + ceil(2*(44.9-30))*0.3 = 12.75 + 30*0.3 = 21.75
        self.assertAlmostEqual(pgs.calculate_tif(44.9), 21.75)

    def test_band_45_to_55(self):
        # base 21.75 + ceil(2*(45-45))*1.45 = 21.75
        self.assertAlmostEqual(pgs.calculate_tif(45), 21.75)
        # 21.75 + ceil(2*(50-45))*1.45 = 21.75 + 10*1.45 = 36.25
        self.assertAlmostEqual(pgs.calculate_tif(50), 36.25)

    def test_caps_at_50_after_55(self):
        for t in (55, 60, 99):
            self.assertEqual(pgs.calculate_tif(t), 50.0)

    def test_monotonic_non_decreasing(self):
        prev = -1.0
        # Step in 0.5 increments across the full curve.
        for i in range(0, 121):
            t = i * 0.5
            v = pgs.calculate_tif(t)
            self.assertGreaterEqual(v, prev,
                f"calculate_tif must be non-decreasing; failed at t={t}")
            prev = v


class TestDeathTimer(unittest.TestCase):
    """Death timer = BRW[level-1] + BRW[level-1] * (tif/100)."""

    def test_level_1_no_tif(self):
        # Level 1, 0 ms - BRW[0]=10, tif=0 -> 10s exactly.
        self.assertAlmostEqual(pgs.calculate_death_timer(1, 0), 10.0)

    def test_level_18_no_tif(self):
        # Level 18 cap, 0 ms - BRW[17]=52.5, tif=0 -> 52.5s.
        self.assertAlmostEqual(pgs.calculate_death_timer(18, 0), 52.5)

    def test_level_clamp_above_18(self):
        # Level 99 clamps to 18.
        self.assertAlmostEqual(pgs.calculate_death_timer(99, 0), 52.5)

    def test_level_clamp_below_1(self):
        self.assertAlmostEqual(pgs.calculate_death_timer(0, 0), 10.0)
        self.assertAlmostEqual(pgs.calculate_death_timer(-5, 0), 10.0)

    def test_brw_table_values(self):
        # Spot-check BRW table at level 7 (== 20s base).
        # 0 ms -> tif=0 -> 20s flat.
        self.assertAlmostEqual(pgs.calculate_death_timer(7, 0), 20.0)

    def test_tif_uplift_at_30_minutes(self):
        # 30 min = 30*60*1000 = 1_800_000 ms. tif(30)=12.75 -> uplift
        # 0.1275; BRW[17]=52.5 -> 52.5*(1+0.1275)=59.19375
        out = pgs.calculate_death_timer(18, 30 * 60 * 1000)
        self.assertAlmostEqual(out, 52.5 * (1 + 12.75 / 100.0))


class TestSigmoid(unittest.TestCase):
    def test_zero_is_half(self):
        self.assertAlmostEqual(pgs._sigmoid(0.0), 0.5)

    def test_large_positive_near_one(self):
        # sigmoid(50) rounds to exactly 1.0 in float64. Just require
        # >= 0.9999; the upper bound is enforced by sigmoid()
        # returning a float in [0, 1].
        self.assertGreaterEqual(pgs._sigmoid(50.0), 0.9999)
        self.assertLessEqual(pgs._sigmoid(50.0), 1.0)

    def test_large_negative_near_zero(self):
        self.assertLessEqual(pgs._sigmoid(-50.0), 0.0001)
        self.assertGreaterEqual(pgs._sigmoid(-50.0), 0.0)


class TestFeatureScaling(unittest.TestCase):
    def test_length_match(self):
        raw = [1000.0] * pgs.WPA_FEATURE_COUNT
        out = pgs.scale_features(raw)
        self.assertEqual(len(out), pgs.WPA_FEATURE_COUNT)

    def test_length_pad(self):
        out = pgs.scale_features([])
        self.assertEqual(len(out), pgs.WPA_FEATURE_COUNT)
        # Bias is divided by 1.0 so the scaled padded zero is still 0.0.
        self.assertEqual(out[-1], 0.0)

    def test_length_truncate(self):
        raw = [1.0] * (pgs.WPA_FEATURE_COUNT + 5)
        out = pgs.scale_features(raw)
        self.assertEqual(len(out), pgs.WPA_FEATURE_COUNT)


class TestFallbackProb(unittest.TestCase):
    def test_zero_features_half(self):
        feats = [0.0] * pgs.WPA_FEATURE_COUNT
        p = pgs._fallback_prob(feats)
        self.assertAlmostEqual(p, 0.5)

    def test_monotonic_in_gold_diff(self):
        feats = [0.0] * pgs.WPA_FEATURE_COUNT
        ps = []
        for gd in (-10000, -5000, 0, 5000, 10000):
            feats[0] = float(gd)
            ps.append(pgs._fallback_prob(feats))
        for a, b in zip(ps, ps[1:]):
            self.assertLess(a, b, f"fallback must be monotonic in gold_diff: {ps}")

    def test_baron_boosts_prob(self):
        feats = [0.0] * pgs.WPA_FEATURE_COUNT
        base = pgs._fallback_prob(feats)
        feats[8] = 1.0  # baron_diff
        with_baron = pgs._fallback_prob(feats)
        self.assertGreater(with_baron, base)

    def test_short_features_returns_half(self):
        self.assertAlmostEqual(pgs._fallback_prob([1.0, 2.0]), 0.5)


class TestWpaModelPersistence(unittest.TestCase):
    def test_roundtrip(self):
        m = pgs.WpaModel(
            weights=tuple(0.1 * i for i in range(pgs.WPA_FEATURE_COUNT)),
            feature_names=pgs.FEATURE_NAMES,
            n_samples=42,
        )
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "model.json"
            pgs.save_model(m, target)
            loaded = pgs.load_model(target)
            self.assertIsNotNone(loaded)
            assert loaded is not None  # for type checkers
            self.assertEqual(loaded.n_samples, 42)
            self.assertEqual(len(loaded.weights), pgs.WPA_FEATURE_COUNT)
            for a, b in zip(m.weights, loaded.weights):
                self.assertAlmostEqual(a, b)

    def test_load_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "absent.json"
            self.assertIsNone(pgs.load_model(p))

    def test_load_bad_json_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            p.write_text("not valid json{{", encoding="utf-8")
            self.assertIsNone(pgs.load_model(p))


class TestPredictProb(unittest.TestCase):
    def test_no_model_uses_fallback(self):
        feats = [0.0] * pgs.WPA_FEATURE_COUNT
        self.assertAlmostEqual(pgs.predict_prob(feats, None), 0.5)

    def test_length_mismatch_returns_half(self):
        m = pgs.WpaModel(
            weights=(0.0,) * pgs.WPA_FEATURE_COUNT,
            feature_names=pgs.FEATURE_NAMES,
            n_samples=1,
        )
        # Pass too few features - WpaModel.predict_prob returns 0.5,
        # but predict_prob() routes through scale_features which pads.
        # We invoke predict_prob() so the pad path runs.
        self.assertAlmostEqual(pgs.predict_prob([1.0, 2.0], m), 0.5)

    def test_predict_with_zero_weights_is_half(self):
        m = pgs.WpaModel(
            weights=(0.0,) * pgs.WPA_FEATURE_COUNT,
            feature_names=pgs.FEATURE_NAMES,
            n_samples=1,
        )
        feats = [100.0] * pgs.WPA_FEATURE_COUNT
        self.assertAlmostEqual(pgs.predict_prob(feats, m), 0.5)


class TestTraining(unittest.TestCase):
    def test_converges_on_separable_data(self):
        # Build a perfectly separable dataset: positive gold_diff -> win,
        # negative -> loss. All other features zero except bias.
        X = []
        y = []
        for v in (-3.0, -2.0, -1.0, -0.5, 0.5, 1.0, 2.0, 3.0):
            feats = [0.0] * pgs.WPA_FEATURE_COUNT
            feats[0] = v
            feats[-1] = 1.0  # bias
            X.append(tuple(feats))
            y.append(1 if v > 0 else 0)
        model = pgs.train_logistic_regression(X, y, epochs=400, lr=0.8, l2=0.0)
        # gold_diff weight should be positive (more gold -> more wins).
        self.assertGreater(model.weights[0], 0.0)
        # And the model should classify the training samples correctly.
        correct = 0
        for feats, label in zip(X, y):
            p = model.predict_prob(feats)
            pred = 1 if p > 0.5 else 0
            if pred == label:
                correct += 1
        self.assertGreaterEqual(correct, 7)  # 7/8 minimum, ideally 8/8.

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            pgs.train_logistic_regression([], [])

    def test_mismatched_lengths_raises(self):
        feats = [(0.0,) * pgs.WPA_FEATURE_COUNT]
        with self.assertRaises(ValueError):
            pgs.train_logistic_regression(feats, [0, 1])

    def test_wrong_feature_count_raises(self):
        with self.assertRaises(ValueError):
            pgs.train_logistic_regression([(0.0, 0.0)], [0])


class TestStrongEventFilter(unittest.TestCase):
    def test_champion_kill_is_strong(self):
        self.assertTrue(pgs.is_strong_event("CHAMPION_KILL", 5, None))

    def test_building_kill_is_strong(self):
        self.assertTrue(pgs.is_strong_event("BUILDING_KILL", 5, None))

    def test_elite_monster_with_killer_is_strong(self):
        self.assertTrue(pgs.is_strong_event("ELITE_MONSTER_KILL", 5, "DRAGON"))

    def test_elite_monster_killed_by_minion_excluded(self):
        # LoLytics excludes ELITE_MONSTER_KILL with killer_id 0.
        self.assertFalse(pgs.is_strong_event("ELITE_MONSTER_KILL", 0, "DRAGON"))
        self.assertFalse(pgs.is_strong_event("ELITE_MONSTER_KILL", None, "DRAGON"))

    def test_level_up_excluded(self):
        self.assertFalse(pgs.is_strong_event("LEVEL_UP", 5, None))

    def test_item_purchased_excluded(self):
        self.assertFalse(pgs.is_strong_event("ITEM_PURCHASED", 5, None))

    def test_none_event_type_excluded(self):
        self.assertFalse(pgs.is_strong_event(None, 5, None))


class TestTeamOfParticipant(unittest.TestCase):
    def test_team_100_blue(self):
        for pid in (1, 2, 3, 4, 5):
            self.assertEqual(pgs._team_of_participant(pid), 100)

    def test_team_200_red(self):
        for pid in (6, 7, 8, 9, 10):
            self.assertEqual(pgs._team_of_participant(pid), 200)

    def test_zero_and_none_return_none(self):
        self.assertIsNone(pgs._team_of_participant(0))
        self.assertIsNone(pgs._team_of_participant(None))

    def test_out_of_range_returns_none(self):
        self.assertIsNone(pgs._team_of_participant(11))
        self.assertIsNone(pgs._team_of_participant(-1))


class TestStateMachine(unittest.TestCase):
    def test_champion_kill_updates_state(self):
        s = pgs.MatchState()
        pgs._apply_champion_kill(s, 5, 7, "[1, 2]")
        self.assertEqual(s.kills_team100, 1)
        self.assertEqual(s.deaths_team200, 1)
        self.assertEqual(s.assists_team100, 2)
        self.assertEqual(s.assists_team200, 0)

    def test_champion_kill_assist_split_across_teams(self):
        s = pgs.MatchState()
        # Killer team 100 with one ally + one rogue assist that landed
        # on the wrong team field in raw data (defensive).
        pgs._apply_champion_kill(s, 5, 7, "[1, 6]")
        self.assertEqual(s.assists_team100, 1)
        self.assertEqual(s.assists_team200, 1)

    def test_champion_kill_bad_assists_json(self):
        s = pgs.MatchState()
        pgs._apply_champion_kill(s, 5, 7, "not json")
        self.assertEqual(s.kills_team100, 1)
        self.assertEqual(s.assists_team100, 0)

    def test_building_kill_tower(self):
        s = pgs.MatchState()
        pgs._apply_building_kill(s, 5, "TOWER_BUILDING", "OUTER_TURRET", 200)
        self.assertEqual(s.turrets_team100, 1)
        self.assertEqual(s.turrets_team200, 0)
        # team_id 200 means team 200 lost; team 100 destroyed it.

    def test_building_kill_inhib(self):
        s = pgs.MatchState()
        pgs._apply_building_kill(s, 6, "INHIBITOR_BUILDING", None, 100)
        self.assertEqual(s.inhibs_team200, 1)
        self.assertEqual(s.inhibs_team100, 0)

    def test_elite_monster_dragon(self):
        s = pgs.MatchState()
        pgs._apply_elite_monster_kill(s, 5, "DRAGON", "WATER_DRAGON")
        self.assertEqual(s.dragons_team100, 1)

    def test_elite_monster_baron(self):
        s = pgs.MatchState()
        pgs._apply_elite_monster_kill(s, 8, "BARON_NASHOR", None)
        self.assertEqual(s.barons_team200, 1)

    def test_elite_monster_horde(self):
        s = pgs.MatchState()
        pgs._apply_elite_monster_kill(s, 5, "HORDE", None)
        self.assertEqual(s.horde_team100, 1)

    def test_to_feature_vector_length(self):
        s = pgs.MatchState()
        feats = s.to_feature_vector(125.5)
        self.assertEqual(len(feats), pgs.WPA_FEATURE_COUNT)
        self.assertEqual(feats[-1], 1.0)  # bias
        self.assertEqual(feats[-2], 125.5)  # game_time_s


class TestUpdateStateFromFrame(unittest.TestCase):
    def test_aggregates_per_team(self):
        s = pgs.MatchState()
        rows = [
            (1, 1000, 500),
            (2, 1500, 600),
            (3, 2000, 700),
            (4, 2500, 800),
            (5, 3000, 900),
            (6, 1100, 510),
            (7, 1200, 620),
            (8, 1300, 730),
            (9, 1400, 840),
            (10, 1500, 950),
        ]
        pgs.update_state_from_frame(s, rows)
        # team 100 totals.
        self.assertEqual(s.gold_team100, 1000 + 1500 + 2000 + 2500 + 3000)
        self.assertEqual(s.xp_team100, 500 + 600 + 700 + 800 + 900)
        # team 200 totals.
        self.assertEqual(s.gold_team200, 1100 + 1200 + 1300 + 1400 + 1500)
        self.assertEqual(s.xp_team200, 510 + 620 + 730 + 840 + 950)


# ---------------------------------------------------------------------
# compute_match_wpa - integration with a synthetic SQLite timeline
# ---------------------------------------------------------------------

def _seed_synthetic_match(conn: sqlite3.Connection, match_id: str) -> None:
    """Build a minimal timeline with 2 frames, 2 champion kills and a
    tower kill so we can assert the WPA pipeline end-to-end."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id          TEXT PRIMARY KEY,
            has_timeline      INTEGER,
            map_id            INTEGER,
            queue_id          INTEGER,
            game_creation_ts  INTEGER
        );
        CREATE TABLE IF NOT EXISTS teams (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id        TEXT,
            team_id         INTEGER,
            win             INTEGER
        );
        CREATE TABLE IF NOT EXISTS timeline_frames (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id        TEXT,
            timestamp_ms    INTEGER,
            participant_id  INTEGER,
            total_gold      INTEGER,
            xp              INTEGER,
            current_gold    INTEGER,
            level           INTEGER,
            minions_killed  INTEGER
        );
        CREATE TABLE IF NOT EXISTS timeline_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id        TEXT,
            timestamp_ms    INTEGER,
            event_type      TEXT,
            killer_id       INTEGER,
            victim_id       INTEGER,
            assisting_ids_json TEXT,
            building_type   TEXT,
            tower_type      TEXT,
            team_id         INTEGER,
            monster_type    TEXT,
            monster_subtype TEXT,
            level_up_type   TEXT,
            level           INTEGER
        );
    """)
    conn.execute(
        "INSERT OR REPLACE INTO matches(match_id, has_timeline, map_id) "
        "VALUES (?, 1, 11)",
        (match_id,),
    )
    conn.execute(
        "INSERT INTO teams(match_id, team_id, win) VALUES (?, ?, ?)",
        (match_id, 0, 1),
    )
    conn.execute(
        "INSERT INTO teams(match_id, team_id, win) VALUES (?, ?, ?)",
        (match_id, 1, 0),
    )
    # Frame at 0 - everyone at baseline.
    for pid in range(1, 11):
        conn.execute(
            "INSERT INTO timeline_frames(match_id, timestamp_ms, participant_id, "
            "total_gold, xp) VALUES (?,?,?,?,?)",
            (match_id, 0, pid, 500, 0),
        )
    # Frame at 5 min - team 100 ahead 6k gold.
    for pid in range(1, 6):
        conn.execute(
            "INSERT INTO timeline_frames(match_id, timestamp_ms, participant_id, "
            "total_gold, xp) VALUES (?,?,?,?,?)",
            (match_id, 300_000, pid, 3000, 2000),
        )
    for pid in range(6, 11):
        conn.execute(
            "INSERT INTO timeline_frames(match_id, timestamp_ms, participant_id, "
            "total_gold, xp) VALUES (?,?,?,?,?)",
            (match_id, 300_000, pid, 1800, 1200),
        )
    # Events: t=60s team 100 kills team 200 (champ kill).
    conn.execute(
        "INSERT INTO timeline_events(match_id, timestamp_ms, event_type, "
        "killer_id, victim_id, assisting_ids_json) VALUES (?,?,?,?,?,?)",
        (match_id, 60_000, "CHAMPION_KILL", 5, 7, "[]"),
    )
    # t=240s team 100 kills a dragon.
    conn.execute(
        "INSERT INTO timeline_events(match_id, timestamp_ms, event_type, "
        "killer_id, monster_type, monster_subtype) VALUES (?,?,?,?,?,?)",
        (match_id, 240_000, "ELITE_MONSTER_KILL", 3, "DRAGON", "WATER_DRAGON"),
    )
    # t=300s team 100 destroys a team 200 tower.
    conn.execute(
        "INSERT INTO timeline_events(match_id, timestamp_ms, event_type, "
        "killer_id, building_type, tower_type, team_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (match_id, 300_000, "BUILDING_KILL", 4, "TOWER_BUILDING",
         "OUTER_TURRET", 200),
    )
    # Inject an ELITE_MONSTER_KILL with no killer (minion-killed) -
    # should be filtered out.
    conn.execute(
        "INSERT INTO timeline_events(match_id, timestamp_ms, event_type, "
        "killer_id, monster_type) VALUES (?,?,?,?,?)",
        (match_id, 270_000, "ELITE_MONSTER_KILL", None, "RIFTHERALD"),
    )
    conn.commit()


class TestComputeMatchWpa(unittest.TestCase):
    def test_match_with_no_timeline(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            conn = sqlite3.connect(str(db))
            try:
                conn.executescript("""
                    CREATE TABLE matches (match_id TEXT, has_timeline INTEGER);
                    CREATE TABLE timeline_frames (match_id TEXT, timestamp_ms INTEGER,
                        participant_id INTEGER, total_gold INTEGER, xp INTEGER);
                    CREATE TABLE timeline_events (match_id TEXT, timestamp_ms INTEGER,
                        event_type TEXT, killer_id INTEGER, victim_id INTEGER,
                        assisting_ids_json TEXT, building_type TEXT, tower_type TEXT,
                        team_id INTEGER, monster_type TEXT, monster_subtype TEXT,
                        id INTEGER PRIMARY KEY AUTOINCREMENT);
                """)
                out = pgs.compute_match_wpa(conn, "ABSENT")
                self.assertFalse(out["ok"])
                self.assertEqual(out["error"], "no_timeline")
            finally:
                conn.close()

    def test_synthetic_match_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            conn = sqlite3.connect(str(db))
            try:
                _seed_synthetic_match(conn, "TEST_M1")
                out = pgs.compute_match_wpa(conn, "TEST_M1")
            finally:
                conn.close()
            self.assertTrue(out["ok"])
            self.assertEqual(out["match_id"], "TEST_M1")
            # Three strong events (kill, dragon, tower); minion-killed
            # rift herald is filtered out.
            self.assertEqual(out["event_count"], 3)
            # First event: champion kill by team 100 - prob_after should
            # be at least as high as prob_before (lethal trade).
            kill_ev = next(e for e in out["events"] if e["type"] == "CHAMPION_KILL")
            self.assertGreaterEqual(kill_ev["prob_after"], kill_ev["prob_before"])
            self.assertEqual(kill_ev["actor"], 5)
            self.assertEqual(kill_ev["actor_team"], 100)
            self.assertEqual(kill_ev["victim"], 7)
            # Top phases capped at 3.
            self.assertLessEqual(len(out["top_phases"]), 3)
            self.assertGreaterEqual(len(out["top_phases"]), 1)
            # Top phase has greatest |WPA|.
            for tp, ev in zip(out["top_phases"][:-1], out["top_phases"][1:]):
                self.assertGreaterEqual(abs(tp["wpa"]), abs(ev["wpa"]))

    def test_synthetic_match_with_trained_model(self):
        """Even a zero-weight model should yield WPA=0 per event."""
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            conn = sqlite3.connect(str(db))
            try:
                _seed_synthetic_match(conn, "TEST_M2")
                # Zero-weight model: every prob = 0.5 -> every WPA = 0.
                m = pgs.WpaModel(
                    weights=(0.0,) * pgs.WPA_FEATURE_COUNT,
                    feature_names=pgs.FEATURE_NAMES,
                    n_samples=1,
                )
                out = pgs.compute_match_wpa(conn, "TEST_M2", model=m)
            finally:
                conn.close()
            self.assertTrue(out["ok"])
            for ev in out["events"]:
                self.assertAlmostEqual(ev["wpa"], 0.0)
                self.assertAlmostEqual(ev["prob_before"], 0.5)
                self.assertAlmostEqual(ev["prob_after"], 0.5)


class TestBuildTrainingSamples(unittest.TestCase):
    def test_extracts_samples_from_synthetic(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            conn = sqlite3.connect(str(db))
            try:
                _seed_synthetic_match(conn, "TEST_M3")
                X, y = pgs.build_training_samples(
                    conn, match_ids=["TEST_M3"], frames_per_match=2
                )
            finally:
                conn.close()
            self.assertEqual(len(X), 2)
            self.assertEqual(len(y), 2)
            # team_id 0 won -> labels both 1.
            self.assertEqual(y, [1, 1])
            self.assertEqual(len(X[0]), pgs.WPA_FEATURE_COUNT)


if __name__ == "__main__":
    unittest.main()
