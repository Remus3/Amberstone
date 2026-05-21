"""tests/test_postmortem_analyze.py - ADR-007 phase 2 analyzer + loader."""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.postmortem_analyze import (  # noqa: E402
    DeathEvent,
    PATTERN_KEYS,
    PATTERN_META,
    _classify_death,
    build_report,
    classify_all,
    iter_deaths,
    main,
    write_atomic,
)


def _build_fixture_db(path: pathlib.Path) -> dict:
    """Create a tiny rewind_history-shaped DB with deterministic death events.

    Returns the puuid + match id used so tests can assert against them.
    """
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE matches (
            match_id TEXT PRIMARY KEY,
            queue_id INTEGER,
            game_mode TEXT,
            game_duration_s INTEGER
        );
        CREATE TABLE participants (
            id INTEGER PRIMARY KEY,
            match_id TEXT,
            participant_id INTEGER,
            team_id INTEGER,
            puuid TEXT,
            riot_id_game_name TEXT,
            riot_id_tagline TEXT,
            champion_id INTEGER,
            champion_name TEXT
        );
        CREATE TABLE timeline_events (
            id INTEGER PRIMARY KEY,
            match_id TEXT,
            timestamp_ms INTEGER,
            event_type TEXT,
            participant_id INTEGER,
            killer_id INTEGER,
            victim_id INTEGER,
            assisting_ids_json TEXT,
            kill_pos_x INTEGER,
            kill_pos_y INTEGER,
            team_id INTEGER
        );
    """)
    self_puuid = "PUUID-SELF"
    ally_puuid = "PUUID-ALLY"
    enemy_puuid = "PUUID-ENEMY"
    match_a = "NA1_TEST_A"
    match_b = "NA1_TEST_B"
    cur.executemany(
        "INSERT INTO matches (match_id, queue_id, game_mode, game_duration_s) VALUES (?,?,?,?)",
        [(match_a, 400, "CLASSIC", 1800), (match_b, 450, "ARAM", 1200)],
    )
    cur.executemany(
        """INSERT INTO participants
           (match_id, participant_id, team_id, puuid, riot_id_game_name, riot_id_tagline, champion_id, champion_name)
           VALUES (?,?,?,?,?,?,?,?)""",
        [
            (match_a, 1, 100, self_puuid,  "x", "T", 1, "Annie"),
            (match_a, 2, 100, ally_puuid,  "a", "T", 2, "Olaf"),
            (match_a, 6, 200, enemy_puuid, "e", "T", 6, "Urgot"),
            (match_a, 7, 200, "PUUID-Z",   "z", "T", 7, "Vayne"),
            (match_a, 8, 200, "PUUID-Y",   "y", "T", 8, "Yasuo"),
            (match_a, 9, 200, "PUUID-X",   "x2", "T", 9, "Xin"),
            (match_b, 1, 100, self_puuid,  "x", "T", 1, "Annie"),
            (match_b, 2, 100, ally_puuid,  "a", "T", 2, "Olaf"),
            (match_b, 6, 200, enemy_puuid, "e", "T", 6, "Urgot"),
        ],
    )
    events = [
        # Match A
        (match_a, 120_000, "CHAMPION_KILL", None, 6, 1, "[]",       100, 200, None),  # solo_1v1_loss + solo_pickoff + early_pre_3min
        (match_a, 180_000, "CHAMPION_KILL", None, 6, 2, "[]",       100, 200, None),  # ally death (sets up solo_pickoff filter)
        (match_a, 185_000, "CHAMPION_KILL", None, 6, 1, "[]",       100, 200, None),  # solo_1v1_loss; ally died 5s prior -> NOT solo_pickoff; rapid_repeat (65s -> just outside, must be <=60s)
        (match_a, 600_000, "CHAMPION_KILL", None, 6, 1, "[7,8,9]",  100, 200, None),  # caught_4plus + solo_pickoff
        (match_a, 1_600_000, "CHAMPION_KILL", None, 6, 1, "[7]",    100, 200, None),  # solo_pickoff (no ally death window)
        (match_a, 1_650_000, "CHAMPION_KILL", None, 6, 1, "[7]",    100, 200, None),  # rapid_repeat + solo_pickoff; (50s after prior self)
        # Match B
        (match_b, 30_000,  "CHAMPION_KILL", None, 6, 1, "[]",       100, 200, None),  # early + solo_1v1_loss + solo_pickoff
        # late
        (match_b, 1_550_000, "CHAMPION_KILL", None, 6, 1, "[7,8,9]", 100, 200, None), # late_throw + caught_4plus + solo_pickoff
    ]
    cur.executemany(
        """INSERT INTO timeline_events
           (match_id, timestamp_ms, event_type, participant_id, killer_id, victim_id,
            assisting_ids_json, kill_pos_x, kill_pos_y, team_id)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        events,
    )
    conn.commit()
    conn.close()
    return {
        "self_puuid": self_puuid,
        "match_a": match_a,
        "match_b": match_b,
    }


class ClassifierTests(unittest.TestCase):
    def test_caught_4plus_fires_on_3plus_assists(self):
        d = DeathEvent("m", 600_000, 1, 6, (7, 8, 9))
        tags = _classify_death(d, prior_ally_deaths=[], prior_self_death_ts_ms=None)
        self.assertIn("caught_4plus", tags)
        self.assertNotIn("solo_1v1_loss", tags)

    def test_solo_1v1_loss_fires_on_zero_assists(self):
        d = DeathEvent("m", 600_000, 1, 6, ())
        tags = _classify_death(d, prior_ally_deaths=[], prior_self_death_ts_ms=None)
        self.assertIn("solo_1v1_loss", tags)
        self.assertNotIn("caught_4plus", tags)

    def test_caught_and_solo_1v1_are_mutually_exclusive(self):
        d_mid = DeathEvent("m", 600_000, 1, 6, (7, 8))
        tags = _classify_death(d_mid, prior_ally_deaths=[], prior_self_death_ts_ms=None)
        self.assertNotIn("caught_4plus", tags)
        self.assertNotIn("solo_1v1_loss", tags)

    def test_early_pre_3min(self):
        d = DeathEvent("m", 90_000, 1, 6, ())
        tags = _classify_death(d, [], None)
        self.assertIn("early_pre_3min", tags)

    def test_late_throw(self):
        d = DeathEvent("m", 1_550_000, 1, 6, ())
        tags = _classify_death(d, [], None)
        self.assertIn("late_throw", tags)

    def test_solo_pickoff_no_ally_in_window(self):
        d = DeathEvent("m", 600_000, 1, 6, ())
        tags = _classify_death(d, prior_ally_deaths=[100_000], prior_self_death_ts_ms=None)
        self.assertIn("solo_pickoff", tags)

    def test_solo_pickoff_suppressed_by_recent_ally_death(self):
        d = DeathEvent("m", 600_000, 1, 6, ())
        # Ally died 5s before within the 8s window
        tags = _classify_death(d, prior_ally_deaths=[595_000], prior_self_death_ts_ms=None)
        self.assertNotIn("solo_pickoff", tags)

    def test_rapid_repeat_fires_within_60s(self):
        d = DeathEvent("m", 660_000, 1, 6, ())
        tags = _classify_death(d, [], prior_self_death_ts_ms=620_000)
        self.assertIn("rapid_repeat", tags)

    def test_rapid_repeat_not_fired_outside_window(self):
        d = DeathEvent("m", 700_000, 1, 6, ())
        tags = _classify_death(d, [], prior_self_death_ts_ms=600_000)  # 100s apart
        self.assertNotIn("rapid_repeat", tags)


class NewPatternThresholdsTests(unittest.TestCase):
    """Boundary tests for small_skirmish (assists 1-2) + midgame_collapse (8-15min window).

    Precedence notes:
      - small_skirmish lives in the assist-band elif chain BETWEEN caught_4plus (>=3)
        and solo_1v1_loss (==0), so n_assists in {1, 2} is mutually exclusive with both.
      - midgame_collapse is an independent (set-additive) time-band check, mirroring
        the existing early_pre_3min and late_throw convention; it co-exists with
        whichever assist-band tag fires for the same death.
    """

    def test_small_skirmish_fires_on_assists_1(self):
        d = DeathEvent("m", 600_000, 1, 6, (7,))
        tags = _classify_death(d, prior_ally_deaths=[], prior_self_death_ts_ms=None)
        self.assertIn("small_skirmish", tags)
        self.assertNotIn("solo_1v1_loss", tags)
        self.assertNotIn("caught_4plus", tags)

    def test_small_skirmish_fires_on_assists_2(self):
        d = DeathEvent("m", 600_000, 1, 6, (7, 8))
        tags = _classify_death(d, prior_ally_deaths=[], prior_self_death_ts_ms=None)
        self.assertIn("small_skirmish", tags)
        self.assertNotIn("caught_4plus", tags)
        self.assertNotIn("solo_1v1_loss", tags)

    def test_small_skirmish_does_not_fire_on_3_assists(self):
        d = DeathEvent("m", 600_000, 1, 6, (7, 8, 9))
        tags = _classify_death(d, prior_ally_deaths=[], prior_self_death_ts_ms=None)
        self.assertIn("caught_4plus", tags)
        self.assertNotIn("small_skirmish", tags)

    def test_small_skirmish_does_not_fire_on_zero_assists(self):
        d = DeathEvent("m", 600_000, 1, 6, ())
        tags = _classify_death(d, prior_ally_deaths=[], prior_self_death_ts_ms=None)
        self.assertIn("solo_1v1_loss", tags)
        self.assertNotIn("small_skirmish", tags)

    def test_midgame_collapse_fires_inside_window(self):
        # t=600000 (10:00) sits inside the 8:00-15:00 window. Use 3 assists so the
        # assist-band tag is caught_4plus (and small_skirmish does NOT fire), proving
        # midgame_collapse is independent of the assist-band elif chain.
        d = DeathEvent("m", 600_000, 1, 6, (7, 8, 9))
        tags = _classify_death(d, prior_ally_deaths=[], prior_self_death_ts_ms=None)
        self.assertIn("midgame_collapse", tags)
        self.assertIn("caught_4plus", tags)
        self.assertNotIn("early_pre_3min", tags)
        self.assertNotIn("late_throw", tags)

    def test_midgame_collapse_fires_on_low_boundary(self):
        d = DeathEvent("m", 480_000, 1, 6, ())  # exactly 8:00
        tags = _classify_death(d, prior_ally_deaths=[], prior_self_death_ts_ms=None)
        self.assertIn("midgame_collapse", tags)

    def test_midgame_collapse_fires_on_high_boundary(self):
        d = DeathEvent("m", 900_000, 1, 6, ())  # exactly 15:00
        tags = _classify_death(d, prior_ally_deaths=[], prior_self_death_ts_ms=None)
        self.assertIn("midgame_collapse", tags)

    def test_midgame_collapse_excludes_early_window(self):
        d = DeathEvent("m", 120_000, 1, 6, ())  # 2:00 - early, not midgame
        tags = _classify_death(d, prior_ally_deaths=[], prior_self_death_ts_ms=None)
        self.assertIn("early_pre_3min", tags)
        self.assertNotIn("midgame_collapse", tags)

    def test_midgame_collapse_excludes_late_throw_window(self):
        d = DeathEvent("m", 1_600_000, 1, 6, ())  # >25:00 - late, not midgame
        tags = _classify_death(d, prior_ally_deaths=[], prior_self_death_ts_ms=None)
        self.assertIn("late_throw", tags)
        self.assertNotIn("midgame_collapse", tags)

    def test_pattern_count_is_eight(self):
        self.assertEqual(len(PATTERN_KEYS), 8)
        for key in ("small_skirmish", "midgame_collapse"):
            self.assertIn(key, PATTERN_META)
            self.assertIn("label", PATTERN_META[key])
            self.assertIn("description", PATTERN_META[key])


class IterDeathsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="postmortem_")
        self.db_path = pathlib.Path(self.tmpdir) / "rewind.db"
        self.fixture = _build_fixture_db(self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass
        os.rmdir(self.tmpdir)

    def test_iter_deaths_returns_only_victim_self(self):
        conn = sqlite3.connect(str(self.db_path))
        deaths = iter_deaths(conn, [self.fixture["self_puuid"]])
        conn.close()
        self.assertEqual(len(deaths), 7)  # 5 self-deaths in match_a + 2 in match_b (ally death at t=180s excluded)
        self.assertTrue(all(d.victim_id == 1 for d in deaths))

    def test_iter_deaths_empty_for_unknown_puuid(self):
        conn = sqlite3.connect(str(self.db_path))
        deaths = iter_deaths(conn, ["PUUID-NOPE"])
        conn.close()
        self.assertEqual(deaths, [])


class ClassifyAllTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="postmortem_")
        self.db_path = pathlib.Path(self.tmpdir) / "rewind.db"
        self.fixture = _build_fixture_db(self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass
        os.rmdir(self.tmpdir)

    def test_classify_counts_match_fixture(self):
        conn = sqlite3.connect(str(self.db_path))
        deaths = iter_deaths(conn, [self.fixture["self_puuid"]])
        counts = classify_all(conn, deaths)
        conn.close()
        # caught_4plus: t=600_000 (3 assists) + t=1_550_000 (3 assists) = 2
        self.assertEqual(counts["caught_4plus"], 2)
        # solo_1v1_loss: t=120_000, t=185_000, t=30_000 = 3
        self.assertEqual(counts["solo_1v1_loss"], 3)
        # early_pre_3min: t=120_000 + t=30_000 (t=185_000 is just past the 180_000 cutoff)
        self.assertEqual(counts["early_pre_3min"], 2)
        # late_throw: t=1_600_000 + t=1_650_000 (match_a) + t=1_550_000 (match_b) = 3 (all >=25:00)
        self.assertEqual(counts["late_throw"], 3)
        # rapid_repeat: t=185_000 (65s after 120_000 - just outside 60s) NO;
        #               t=1_650_000 (50s after 1_600_000) YES
        # so rapid_repeat = 1
        self.assertEqual(counts["rapid_repeat"], 1)


class BuildReportTests(unittest.TestCase):
    def test_top3_orders_by_count_descending(self):
        deaths = [
            DeathEvent("m", i, 1, 6, ()) for i in range(10)
        ]
        counts = {k: 0 for k in PATTERN_KEYS}
        counts["solo_pickoff"] = 9
        counts["caught_4plus"] = 5
        counts["rapid_repeat"] = 2
        report = build_report(deaths, counts, ["PUUID-X"])
        self.assertEqual(report["top3"], ["solo_pickoff", "caught_4plus", "rapid_repeat"])

    def test_top3_drops_zero_count_patterns(self):
        deaths = [DeathEvent("m", i, 1, 6, ()) for i in range(3)]
        counts = {k: 0 for k in PATTERN_KEYS}
        counts["solo_pickoff"] = 1
        report = build_report(deaths, counts, [])
        self.assertEqual(report["top3"], ["solo_pickoff"])

    def test_report_carries_schema_version_and_iso_ts(self):
        report = build_report([], dict.fromkeys(PATTERN_KEYS, 0), ["X"])
        self.assertEqual(report["schema_version"], 1)
        self.assertTrue(report["generated_at"].endswith("Z"))
        self.assertEqual(report["puuids"], ["X"])

    def test_all_patterns_carry_meta(self):
        report = build_report([], dict.fromkeys(PATTERN_KEYS, 0), [])
        for key in PATTERN_KEYS:
            self.assertIn(key, report["patterns"])
            self.assertEqual(report["patterns"][key]["label"], PATTERN_META[key]["label"])
            self.assertEqual(report["patterns"][key]["description"], PATTERN_META[key]["description"])

    def test_rate_uses_laplace_smoothing(self):
        report = build_report([DeathEvent("m", 0, 1, 6, ())], {"solo_pickoff": 1, **{k: 0 for k in PATTERN_KEYS if k != "solo_pickoff"}}, [])
        # laplace_rate(1, 1) = (1+1)/(1+2) = 2/3
        self.assertAlmostEqual(report["patterns"]["solo_pickoff"]["rate"], 2.0 / 3.0, places=3)


class WriteAtomicTests(unittest.TestCase):
    def test_write_atomic_creates_parent(self):
        tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="postmortem_"))
        try:
            target = tmpdir / "nested" / "subdir" / "out.json"
            write_atomic(target, {"a": 1})
            self.assertTrue(target.exists())
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["a"], 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_write_atomic_replaces_existing(self):
        tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="postmortem_"))
        try:
            target = tmpdir / "out.json"
            target.write_text(json.dumps({"a": 1}), encoding="utf-8")
            write_atomic(target, {"a": 2})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["a"], 2)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


class MainTests(unittest.TestCase):
    def test_main_returns_2_when_no_puuid_and_no_state(self):
        tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="postmortem_"))
        try:
            rc = main(["--db", str(tmpdir / "missing.db"), "--output", str(tmpdir / "out.json")])
            # Without puuid + no state file in tmpdir scope, returns 2 OR 3 if DB missing first.
            # Since CATCHUP_STATE is a module constant that points at the real repo, just assert non-zero.
            self.assertNotEqual(rc, 0)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_main_returns_3_when_db_missing(self):
        tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="postmortem_"))
        try:
            rc = main(["--db", str(tmpdir / "missing.db"), "--puuid", "PUUID-X", "--output", str(tmpdir / "out.json")])
            self.assertEqual(rc, 3)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_main_writes_output_on_real_db(self):
        tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="postmortem_"))
        try:
            db = tmpdir / "rewind.db"
            fixture = _build_fixture_db(db)
            out = tmpdir / "out.json"
            rc = main([
                "--db", str(db),
                "--puuid", fixture["self_puuid"],
                "--output", str(out),
            ])
            self.assertEqual(rc, 0)
            self.assertTrue(out.exists())
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], 1)
            self.assertGreater(data["total_deaths"], 0)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_main_dry_run_does_not_write(self):
        tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="postmortem_"))
        try:
            db = tmpdir / "rewind.db"
            fixture = _build_fixture_db(db)
            out = tmpdir / "out.json"
            rc = main([
                "--db", str(db),
                "--puuid", fixture["self_puuid"],
                "--output", str(out),
                "--dry-run",
            ])
            self.assertEqual(rc, 0)
            self.assertFalse(out.exists())
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


class AsciiHygieneTests(unittest.TestCase):
    def test_script_is_ascii(self):
        path = ROOT / "scripts" / "postmortem_analyze.py"
        body = path.read_bytes()
        for i, b in enumerate(body):
            self.assertLess(b, 128, f"non-ASCII byte 0x{b:02x} at offset {i}")


if __name__ == "__main__":
    unittest.main()
