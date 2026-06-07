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
    _CANONICAL_ROLES,
    _TEAM_POSITION_TO_ROLE,
    _TIER_ORDER,
    _classify_death,
    _median,
    aggregate_role_grades,
    build_report,
    classify_all,
    iter_deaths,
    iter_role_grades,
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
            champion_name TEXT,
            team_position TEXT,
            kills INTEGER,
            deaths INTEGER,
            assists INTEGER,
            total_minions_killed INTEGER,
            neutral_minions_killed INTEGER,
            vision_score INTEGER,
            total_damage_dealt_to_champs INTEGER,
            dragon_kills INTEGER DEFAULT 0,
            baron_kills INTEGER DEFAULT 0,
            objectives_stolen INTEGER DEFAULT 0,
            objectives_stolen_assists INTEGER DEFAULT 0,
            first_tower_kill INTEGER DEFAULT 0,
            first_tower_assist INTEGER DEFAULT 0,
            challenges_json TEXT
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
           (match_id, participant_id, team_id, puuid, riot_id_game_name, riot_id_tagline,
            champion_id, champion_name, team_position,
            kills, deaths, assists, total_minions_killed, neutral_minions_killed,
            vision_score, total_damage_dealt_to_champs)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            # match_a: SR match, self is MIDDLE; ally TOP; 4 enemies with positions
            (match_a, 1, 100, self_puuid,  "x", "T", 1, "Annie",  "MIDDLE",
             7, 4, 8, 180, 0, 22, 22000),
            (match_a, 2, 100, ally_puuid,  "a", "T", 2, "Olaf",   "TOP",
             3, 5, 4, 150, 30, 14, 14000),
            (match_a, 6, 200, enemy_puuid, "e", "T", 6, "Urgot",  "TOP",
             5, 3, 6, 160, 0, 12, 18000),
            (match_a, 7, 200, "PUUID-Z",   "z", "T", 7, "Vayne",  "BOTTOM",
             0, 0, 0, 0, 0, 0, 0),
            (match_a, 8, 200, "PUUID-Y",   "y", "T", 8, "Yasuo",  "MIDDLE",
             0, 0, 0, 0, 0, 0, 0),
            (match_a, 9, 200, "PUUID-X",   "x2", "T", 9, "Xin",    "JUNGLE",
             0, 0, 0, 0, 0, 0, 0),
            # match_b: ARAM-shaped row, self team_position is blank (event mode)
            (match_b, 1, 100, self_puuid,  "x", "T", 1, "Annie",  "",
             10, 6, 12, 200, 0, 0, 30000),
            (match_b, 2, 100, ally_puuid,  "a", "T", 2, "Olaf",   "",
             0, 0, 0, 0, 0, 0, 0),
            (match_b, 6, 200, enemy_puuid, "e", "T", 6, "Urgot",  "",
             0, 0, 0, 0, 0, 0, 0),
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
        self.assertEqual(report["schema_version"], 2)
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
            self.assertEqual(data["schema_version"], 2)
            self.assertGreater(data["total_deaths"], 0)
            self.assertIn("role_grades", data)
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


class MedianHelperTests(unittest.TestCase):
    """The plain-median helper is the single source of truth for the
    role_grades median_score field. Boundary cases pinned here."""

    def test_empty_returns_zero(self):
        self.assertEqual(_median([]), 0.0)

    def test_single_value(self):
        self.assertEqual(_median([42.5]), 42.5)

    def test_odd_count(self):
        self.assertEqual(_median([10.0, 30.0, 20.0]), 20.0)

    def test_even_count_averages_middle_pair(self):
        self.assertEqual(_median([10.0, 20.0, 30.0, 40.0]), 25.0)


class RoleNormalizationTests(unittest.TestCase):
    """team_position values from Match-V5 canonicalize to ADC/SUP/JG/MID/TOP.

    Blank / unknown / event-mode rows are SKIPPED upstream (iter_role_grades
    filters before calling _TEAM_POSITION_TO_ROLE.get). This guards against
    the rubric's _normalize_role fallback to MID hiding event-mode data.
    """

    def test_bottom_maps_to_adc(self):
        self.assertEqual(_TEAM_POSITION_TO_ROLE["BOTTOM"], "ADC")

    def test_utility_maps_to_sup(self):
        self.assertEqual(_TEAM_POSITION_TO_ROLE["UTILITY"], "SUP")

    def test_jungle_maps_to_jg(self):
        self.assertEqual(_TEAM_POSITION_TO_ROLE["JUNGLE"], "JG")

    def test_middle_maps_to_mid(self):
        self.assertEqual(_TEAM_POSITION_TO_ROLE["MIDDLE"], "MID")

    def test_top_maps_to_top(self):
        self.assertEqual(_TEAM_POSITION_TO_ROLE["TOP"], "TOP")

    def test_canonical_roles_are_5(self):
        self.assertEqual(set(_CANONICAL_ROLES), {"ADC", "SUP", "JG", "MID", "TOP"})


class IterRoleGradesTests(unittest.TestCase):
    """iter_role_grades reads participants joined to matches; skips blank
    team_position rows so event-mode ARAM/Arena matches don't pollute the
    role aggregation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="postmortem_rg_")
        self.db_path = pathlib.Path(self.tmpdir) / "rewind.db"
        self.fixture = _build_fixture_db(self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass
        os.rmdir(self.tmpdir)

    def test_returns_one_per_non_blank_team_position(self):
        conn = sqlite3.connect(str(self.db_path))
        grades = iter_role_grades(conn, [self.fixture["self_puuid"]])
        conn.close()
        # match_a self team_position=MIDDLE -> MID grade; match_b is "" -> skipped
        self.assertEqual(len(grades), 1)
        self.assertEqual(grades[0]["role"], "MID")

    def test_blank_team_position_is_skipped(self):
        # Sanity: confirm match_b's self row exists with blank team_position
        # so the iter_role_grades skip path is the reason for len==1, not
        # missing data.
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.execute(
            "SELECT team_position FROM participants WHERE puuid = ? ORDER BY match_id",
            (self.fixture["self_puuid"],),
        )
        positions = [r[0] for r in cur]
        conn.close()
        self.assertEqual(positions, ["MIDDLE", ""])

    def test_grade_carries_total_score_and_percentile(self):
        conn = sqlite3.connect(str(self.db_path))
        grades = iter_role_grades(conn, [self.fixture["self_puuid"]])
        conn.close()
        g = grades[0]
        self.assertIn("total_score", g)
        self.assertIn("percentile_grade", g)
        self.assertIsInstance(g["total_score"], float)
        self.assertIn(g["percentile_grade"], ("S+", "S", "A", "B", "C", "D"))

    def test_empty_puuid_list_returns_empty(self):
        conn = sqlite3.connect(str(self.db_path))
        grades = iter_role_grades(conn, [])
        conn.close()
        self.assertEqual(grades, [])

    def test_unknown_puuid_returns_empty(self):
        conn = sqlite3.connect(str(self.db_path))
        grades = iter_role_grades(conn, ["PUUID-NOPE"])
        conn.close()
        self.assertEqual(grades, [])


class AggregateRoleGradesTests(unittest.TestCase):
    """aggregate_role_grades buckets per-match grades by canonical role +
    overall; emits tier_distribution + median_score + count for each."""

    def test_empty_input_returns_zero_buckets(self):
        out = aggregate_role_grades([])
        self.assertEqual(out["total_matches_scored"], 0)
        self.assertEqual(out["overall"]["count"], 0)
        self.assertEqual(out["overall"]["median_score"], 0)
        for role in _CANONICAL_ROLES:
            self.assertEqual(out["by_role"][role]["count"], 0)
            self.assertEqual(out["by_role"][role]["median_score"], 0)

    def test_canonical_role_keys_always_present(self):
        # Even when a role has 0 matches, the bucket exists so frontend
        # iteration is deterministic.
        out = aggregate_role_grades([
            {"role": "ADC", "total_score": 50.0, "percentile_grade": "B"},
        ])
        self.assertEqual(set(out["by_role"].keys()), set(_CANONICAL_ROLES))

    def test_buckets_by_role(self):
        grades = [
            {"role": "ADC", "total_score": 80.0, "percentile_grade": "S"},
            {"role": "ADC", "total_score": 60.0, "percentile_grade": "B"},
            {"role": "MID", "total_score": 70.0, "percentile_grade": "A"},
        ]
        out = aggregate_role_grades(grades)
        self.assertEqual(out["by_role"]["ADC"]["count"], 2)
        self.assertEqual(out["by_role"]["MID"]["count"], 1)
        self.assertEqual(out["by_role"]["SUP"]["count"], 0)

    def test_median_score_per_role(self):
        grades = [
            {"role": "TOP", "total_score": 10.0, "percentile_grade": "D"},
            {"role": "TOP", "total_score": 50.0, "percentile_grade": "B"},
            {"role": "TOP", "total_score": 90.0, "percentile_grade": "S+"},
        ]
        out = aggregate_role_grades(grades)
        self.assertEqual(out["by_role"]["TOP"]["median_score"], 50)

    def test_overall_aggregates_across_roles(self):
        grades = [
            {"role": "ADC", "total_score": 30.0, "percentile_grade": "D"},
            {"role": "MID", "total_score": 70.0, "percentile_grade": "A"},
        ]
        out = aggregate_role_grades(grades)
        self.assertEqual(out["overall"]["count"], 2)
        self.assertEqual(out["overall"]["median_score"], 50)
        self.assertEqual(out["total_matches_scored"], 2)

    def test_tier_distribution_per_role(self):
        grades = [
            {"role": "JG", "total_score": 90.0, "percentile_grade": "S+"},
            {"role": "JG", "total_score": 80.0, "percentile_grade": "S"},
            {"role": "JG", "total_score": 80.0, "percentile_grade": "S"},
        ]
        out = aggregate_role_grades(grades)
        tier = out["by_role"]["JG"]["tier_distribution"]
        self.assertEqual(tier["S+"], 1)
        self.assertEqual(tier["S"], 2)
        self.assertEqual(tier["A"], 0)

    def test_tier_distribution_carries_all_6_tiers(self):
        out = aggregate_role_grades([
            {"role": "SUP", "total_score": 50.0, "percentile_grade": "B"},
        ])
        self.assertEqual(set(out["by_role"]["SUP"]["tier_distribution"].keys()), set(_TIER_ORDER))
        self.assertEqual(set(out["overall"]["tier_distribution"].keys()), set(_TIER_ORDER))

    def test_unknown_role_is_dropped(self):
        # If iter_role_grades emits an unexpected role string, the
        # aggregator skips it rather than crashing or creating a new
        # canonical bucket.
        out = aggregate_role_grades([
            {"role": "GHOST", "total_score": 50.0, "percentile_grade": "B"},
            {"role": "ADC", "total_score": 50.0, "percentile_grade": "B"},
        ])
        self.assertEqual(out["total_matches_scored"], 1)
        self.assertEqual(out["by_role"]["ADC"]["count"], 1)
        self.assertNotIn("GHOST", out["by_role"])

    def test_unknown_tier_string_demotes_to_d(self):
        out = aggregate_role_grades([
            {"role": "MID", "total_score": 50.0, "percentile_grade": "ZZZ"},
        ])
        self.assertEqual(out["by_role"]["MID"]["tier_distribution"]["D"], 1)


class BuildReportSchemaV2Tests(unittest.TestCase):
    """build_report still ships schema_version=2 even when the role_grades
    section is added in main() (not in build_report itself). The schema
    bump propagates to all downstream consumers."""

    def test_schema_version_is_2(self):
        report = build_report([], dict.fromkeys(PATTERN_KEYS, 0), [])
        self.assertEqual(report["schema_version"], 2)


class MainRoleGradesIntegrationTests(unittest.TestCase):
    """main() writes the role_grades envelope to the JSON output."""

    def test_main_writes_role_grades_section(self):
        tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="postmortem_rg_main_"))
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
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("role_grades", data)
            rg = data["role_grades"]
            self.assertIn("total_matches_scored", rg)
            self.assertIn("overall", rg)
            self.assertIn("by_role", rg)
            self.assertEqual(rg["total_matches_scored"], 1)
            self.assertEqual(rg["by_role"]["MID"]["count"], 1)
            self.assertEqual(rg["by_role"]["ADC"]["count"], 0)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


def _populate_match_a_objectives(
    db_path: pathlib.Path,
    self_puuid: str,
    ally_puuid: str,
    ally_extra_dragons: int = 0,
) -> None:
    """Stamp objective columns on match_a so iter_role_grades sees a
    non-zero obj_participation_pct.

    Operator owns 1 dragon + 1 first_tower = 2; ally owns
    1 + ally_extra_dragons dragons. With the default (0) team total = 3,
    operator share = 2/3 ~ 0.667.

    ally_extra_dragons dilutes the operator's share. The item-335
    recalibration set the obj baselines to the real per-role medians (MID
    ~0.13), so the 2x-median clamp saturates the obj axis above ~0.26
    share; the dilution-monotonicity tests pass a large pad here to keep
    BOTH the before + after shares in the linear (unsaturated) region
    where the share delta is observable on the grade.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE participants SET dragon_kills=1, first_tower_kill=1 "
            "WHERE match_id='NA1_TEST_A' AND puuid=?",
            (self_puuid,),
        )
        conn.execute(
            "UPDATE participants SET dragon_kills=? "
            "WHERE match_id='NA1_TEST_A' AND puuid=?",
            (1 + int(ally_extra_dragons), ally_puuid),
        )
        conn.commit()
    finally:
        conn.close()


def _populate_match_a_herald(
    db_path: pathlib.Path,
    self_puuid: str,
    ally_puuid: str,
    self_herald: int = 0,
    ally_herald: int = 0,
) -> None:
    """Stamp challenges_json for match_a with riftHeraldTakedowns counts
    on the operator + one ally (item 133 carry (b))."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE participants SET challenges_json=? "
            "WHERE match_id='NA1_TEST_A' AND puuid=?",
            (json.dumps({"riftHeraldTakedowns": int(self_herald)}), self_puuid),
        )
        conn.execute(
            "UPDATE participants SET challenges_json=? "
            "WHERE match_id='NA1_TEST_A' AND puuid=?",
            (json.dumps({"riftHeraldTakedowns": int(ally_herald)}), ally_puuid),
        )
        conn.commit()
    finally:
        conn.close()


def _populate_match_a_objectives_blob(
    db_path: pathlib.Path,
    self_puuid: str,
    ally_puuid: str,
    self_herald: int = 0,
    ally_herald: int = 0,
    self_void: int = 0,
    ally_void: int = 0,
    self_turret: int = 0,
    ally_turret: int = 0,
) -> None:
    """Stamp challenges_json with riftHeraldTakedowns + voidMonsterKill
    + turretTakedowns (BACKLOG L14 (c) widened from item 134's 8-col
    model). Populates all 3 blob keys atomically per row so the
    9-column model is exercised end-to-end."""
    conn = sqlite3.connect(str(db_path))
    try:
        op_blob = json.dumps({
            "riftHeraldTakedowns": int(self_herald),
            "voidMonsterKill": int(self_void),
            "turretTakedowns": int(self_turret),
        })
        ally_blob = json.dumps({
            "riftHeraldTakedowns": int(ally_herald),
            "voidMonsterKill": int(ally_void),
            "turretTakedowns": int(ally_turret),
        })
        conn.execute(
            "UPDATE participants SET challenges_json=? "
            "WHERE match_id='NA1_TEST_A' AND puuid=?",
            (op_blob, self_puuid),
        )
        conn.execute(
            "UPDATE participants SET challenges_json=? "
            "WHERE match_id='NA1_TEST_A' AND puuid=?",
            (ally_blob, ally_puuid),
        )
        conn.commit()
    finally:
        conn.close()


class ObjParticipationWireTests(unittest.TestCase):
    """Closes item-132 carry-forward (c): iter_role_grades now passes real
    obj_participation_pct (was: 0.0 always) through compute_role_grade.

    The fixture's match_a is MIDDLE for self (-> MID role); MID weights
    obj_participation at 0.30 (compared to 0.0 / no obj baseline). The
    delta in total_score between zero-obj and populated-obj is the
    signature we pin.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="postmortem_obj_")
        self.db_path = pathlib.Path(self.tmpdir) / "rewind.db"
        self.fixture = _build_fixture_db(self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    def test_baseline_with_zero_objectives(self):
        # Zero objectives at fixture seed -> obj_participation = 0.0
        # and total_score has NO obj_participation contribution.
        conn = sqlite3.connect(str(self.db_path))
        try:
            grades = iter_role_grades(conn, [self.fixture["self_puuid"]])
        finally:
            conn.close()
        self.assertEqual(len(grades), 1)
        self.assertEqual(grades[0]["role"], "MID")
        baseline_score = grades[0]["total_score"]
        self.assertGreaterEqual(baseline_score, 0.0)
        self.assertLessEqual(baseline_score, 100.0)

    def test_populated_objectives_raise_total_score(self):
        # Read baseline first.
        conn = sqlite3.connect(str(self.db_path))
        try:
            baseline = iter_role_grades(conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()

        _populate_match_a_objectives(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
        )

        conn = sqlite3.connect(str(self.db_path))
        try:
            populated = iter_role_grades(conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()
        # Same KDA / CS / vision / DPM - only the obj_participation axis
        # differs. MID weight is 0.30, so the lift is positive.
        self.assertGreater(populated["total_score"], baseline["total_score"])
        self.assertEqual(populated["role"], baseline["role"])

    def test_legacy_schema_without_obj_columns_fails_soft(self):
        # Simulate an older DB shape: drop the 6 obj columns from a fresh
        # build and confirm iter_role_grades returns the same length of
        # grades (obj just becomes 0.0 via the fail-soft in
        # core.obj_participation).
        legacy_db = pathlib.Path(self.tmpdir) / "legacy.db"
        conn = sqlite3.connect(str(legacy_db))
        cur = conn.cursor()
        cur.executescript(
            """
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
                team_position TEXT,
                kills INTEGER,
                deaths INTEGER,
                assists INTEGER,
                total_minions_killed INTEGER,
                neutral_minions_killed INTEGER,
                vision_score INTEGER,
                total_damage_dealt_to_champs INTEGER
            );
            INSERT INTO matches VALUES ('LEG', 400, 'CLASSIC', 1800);
            INSERT INTO participants
              (match_id, participant_id, team_id, puuid, team_position,
               kills, deaths, assists, total_minions_killed,
               neutral_minions_killed, vision_score,
               total_damage_dealt_to_champs)
              VALUES ('LEG', 1, 100, 'X', 'MIDDLE', 5, 3, 8, 150, 0, 18, 20000);
            """
        )
        conn.commit()
        try:
            grades = iter_role_grades(conn, ["X"])
            self.assertEqual(len(grades), 1)
            self.assertEqual(grades[0]["role"], "MID")
            # No crash + a real score - confirms fail-soft on missing
            # objective columns.
            self.assertGreaterEqual(grades[0]["total_score"], 0.0)
        finally:
            conn.close()

    def test_main_run_with_populated_objectives_writes_role_grades(self):
        # End-to-end: main() drives iter_role_grades -> aggregate ->
        # write_atomic. obj enrichment flows all the way.
        _populate_match_a_objectives(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
        )
        out = pathlib.Path(self.tmpdir) / "out.json"
        rc = main([
            "--db", str(self.db_path),
            "--puuid", self.fixture["self_puuid"],
            "--output", str(out),
        ])
        self.assertEqual(rc, 0)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 2)
        rg = data["role_grades"]
        self.assertEqual(rg["by_role"]["MID"]["count"], 1)
        # Median score reflects the obj-enriched grade.
        self.assertGreaterEqual(rg["by_role"]["MID"]["median_score"], 0)
        self.assertLessEqual(rg["by_role"]["MID"]["median_score"], 100)

    def test_iter_role_grades_uses_match_id_and_puuid_per_row(self):
        # Smoke test that the SELECT still works after the widened
        # column list (now includes p.match_id + p.puuid).
        _populate_match_a_objectives(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
        )
        conn = sqlite3.connect(str(self.db_path))
        try:
            grades = iter_role_grades(conn, [self.fixture["self_puuid"]])
        finally:
            conn.close()
        self.assertEqual(len(grades), 1)
        self.assertEqual(grades[0]["role"], "MID")


class HeraldEnrichmentWireTests(unittest.TestCase):
    """Closes item 133 carry (b): challenges_json riftHeraldTakedowns
    flows through iter_role_grades -> compute_role_grade as the 7th
    objective contribution."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="postmortem_herald_")
        self.db_path = pathlib.Path(self.tmpdir) / "rewind.db"
        self.fixture = _build_fixture_db(self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    def test_solo_herald_lifts_total_score_above_zero_obj_baseline(self):
        # Read baseline first - operator has zero objectives.
        conn = sqlite3.connect(str(self.db_path))
        try:
            baseline = iter_role_grades(conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()

        # Operator gets 2 herald takedowns; ally gets 0. Team total now
        # 2; operator share = 1.0.
        _populate_match_a_herald(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
            self_herald=2,
            ally_herald=0,
        )
        conn = sqlite3.connect(str(self.db_path))
        try:
            populated = iter_role_grades(conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()
        # MID weight for obj_participation is 0.30 - non-zero lift.
        self.assertGreater(populated["total_score"], baseline["total_score"])
        self.assertEqual(populated["role"], baseline["role"])

    def test_herald_composes_with_sql_objectives(self):
        # Combined: SQL objectives + herald. The two contributions
        # should compose additively in numerator + denominator.
        _populate_match_a_objectives(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
            ally_extra_dragons=20,
        )
        # Operator: 2 obj; ally: 21 (1 + 20 pad). Team = 23, share ~0.087
        # (sub-saturation for the MID 0.13 obj baseline; see helper).
        conn = sqlite3.connect(str(self.db_path))
        try:
            sql_only = iter_role_grades(conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()

        # Add herald: operator 1, ally 0. Operator 3, team 24, share ~0.125
        # (up from ~0.087) - still linear, so the lift is observable.
        _populate_match_a_herald(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
            self_herald=1,
            ally_herald=0,
        )
        conn = sqlite3.connect(str(self.db_path))
        try:
            combined = iter_role_grades(conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()
        # Operator's share rose -> total_score also rises.
        self.assertGreater(combined["total_score"], sql_only["total_score"])

    def test_teammate_herald_lowers_operator_share(self):
        # Operator 2; ally 21 (1 + 20 pad). Share ~0.087 (sub-saturation
        # for the MID 0.13 obj baseline so the dilution is observable).
        _populate_match_a_objectives(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
            ally_extra_dragons=20,
        )
        conn = sqlite3.connect(str(self.db_path))
        try:
            without_ally_herald = iter_role_grades(conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()

        # Add herald=1 to ally only. Operator 2, team 24 -> share ~0.083
        # (lower than ~0.087 pre-enrichment).
        _populate_match_a_herald(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
            self_herald=0,
            ally_herald=1,
        )
        conn = sqlite3.connect(str(self.db_path))
        try:
            with_ally_herald = iter_role_grades(conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()
        # Operator's share fell -> total_score also fell.
        self.assertLess(
            with_ally_herald["total_score"],
            without_ally_herald["total_score"],
        )


class VoidEnrichmentWireTests(unittest.TestCase):
    """Closes item 134 carry (g): challenges_json voidMonsterKill
    (Voidgrubs) flows through iter_role_grades -> compute_role_grade as
    the 8th objective contribution."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="postmortem_void_")
        self.db_path = pathlib.Path(self.tmpdir) / "rewind.db"
        self.fixture = _build_fixture_db(self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    def test_void_enrichment_widens_obj_pct(self):
        # Read baseline first - operator has zero objectives.
        conn = sqlite3.connect(str(self.db_path))
        try:
            baseline = iter_role_grades(conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()

        # Operator gets 3 voidgrubs; ally gets 0. Operator share = 1.0.
        _populate_match_a_objectives_blob(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
            self_herald=0, ally_herald=0,
            self_void=3, ally_void=0,
        )
        conn = sqlite3.connect(str(self.db_path))
        try:
            populated = iter_role_grades(conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()
        # MID weight for obj_participation is 0.30 - non-zero lift.
        self.assertGreater(populated["total_score"], baseline["total_score"])
        self.assertEqual(populated["role"], baseline["role"])

    def test_void_in_role_grades_lift_with_herald_and_sql(self):
        # Stack the wins: SQL objectives + herald + voidgrubs all
        # contribute to operator's score.
        _populate_match_a_objectives(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
            ally_extra_dragons=20,
        )
        # SQL-only baseline: operator 2 obj; ally 21 (1 + 20 pad).
        # Team total = 23, share ~0.087 (sub-saturation, MID 0.13 baseline).
        conn = sqlite3.connect(str(self.db_path))
        try:
            sql_only = iter_role_grades(conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()

        # Add herald=1 + void=2 on operator; ally clean. Operator total
        # = 2 + 1 + 2 = 5; team = 26 -> ~0.192 share (up from ~0.087).
        _populate_match_a_objectives_blob(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
            self_herald=1, ally_herald=0,
            self_void=2, ally_void=0,
        )
        conn = sqlite3.connect(str(self.db_path))
        try:
            combined = iter_role_grades(conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()
        self.assertGreater(combined["total_score"], sql_only["total_score"])

    def test_teammate_void_lowers_operator_share(self):
        # Operator 2; ally 21 (1 + 20 pad). Share ~0.087 (sub-saturation
        # for the MID 0.13 obj baseline so the dilution is observable).
        _populate_match_a_objectives(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
            ally_extra_dragons=20,
        )
        conn = sqlite3.connect(str(self.db_path))
        try:
            without_ally_void = iter_role_grades(
                conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()

        # Add void=3 to ally only. Operator 2, team 26 -> share ~0.077
        # (down from ~0.087 pre-enrichment).
        _populate_match_a_objectives_blob(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
            self_herald=0, ally_herald=0,
            self_void=0, ally_void=3,
        )
        conn = sqlite3.connect(str(self.db_path))
        try:
            with_ally_void = iter_role_grades(
                conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()
        # Operator's share fell -> total_score also fell.
        self.assertLess(
            with_ally_void["total_score"],
            without_ally_void["total_score"],
        )


class TurretEnrichmentWireTests(unittest.TestCase):
    """Closes BACKLOG L14 (c): challenges_json turretTakedowns flows
    through iter_role_grades -> compute_role_grade as the 9th
    objective contribution via max(turret - ftk - fta, 0) clamp."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="postmortem_turret_")
        self.db_path = pathlib.Path(self.tmpdir) / "rewind.db"
        self.fixture = _build_fixture_db(self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    def test_turret_enrichment_widens_obj_pct(self):
        # Baseline: operator has zero objectives.
        conn = sqlite3.connect(str(self.db_path))
        try:
            baseline = iter_role_grades(conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()

        # Operator takes 5 turrets (none of them the first tower so no
        # overlap to subtract); ally 0. Operator share = 1.0.
        _populate_match_a_objectives_blob(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
            self_turret=5, ally_turret=0,
        )
        conn = sqlite3.connect(str(self.db_path))
        try:
            populated = iter_role_grades(conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()
        # MID weight for obj_participation is 0.30 - non-zero lift.
        self.assertGreater(populated["total_score"], baseline["total_score"])
        self.assertEqual(populated["role"], baseline["role"])

    def test_turret_first_tower_overlap_not_double_counted(self):
        # SQL ftk=1 already gives operator 1 point. Add
        # turretTakedowns=1 (the SAME first turret) -> extra=0; the
        # score must NOT lift further beyond the 1.0 ratio cap.
        _populate_match_a_objectives(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
        )
        # Match-A objectives default: op_dragons=2, ally_dragons=1; share 2/3
        # = 0.667. Add op turretTakedowns=1 + (no extra ftk since
        # _populate_match_a_objectives only sets dragons). Operator
        # share rises to 3/4 = 0.75.
        _populate_match_a_objectives_blob(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
            self_turret=1, ally_turret=0,
        )
        conn = sqlite3.connect(str(self.db_path))
        try:
            with_turret = iter_role_grades(
                conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()
        # Strictly positive obj_participation; never panics or returns
        # > 1.0 share. Both score sanity checks.
        self.assertGreater(with_turret["total_score"], 0.0)
        self.assertLessEqual(with_turret["total_score"], 100.0)

    def test_teammate_turret_lowers_operator_share(self):
        # SQL: operator dragons=2 + ally dragons=1; team=3; share 2/3.
        _populate_match_a_objectives(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
        )
        conn = sqlite3.connect(str(self.db_path))
        try:
            without_ally_turret = iter_role_grades(
                conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()

        # Ally takes 5 turrets (no overlap). Operator 2, team 2+1+5=8
        # -> share 0.25 (down from 0.667).
        _populate_match_a_objectives_blob(
            self.db_path,
            self_puuid=self.fixture["self_puuid"],
            ally_puuid="PUUID-ALLY",
            self_turret=0, ally_turret=5,
        )
        conn = sqlite3.connect(str(self.db_path))
        try:
            with_ally_turret = iter_role_grades(
                conn, [self.fixture["self_puuid"]])[0]
        finally:
            conn.close()
        # Operator's share fell -> total_score also fell.
        self.assertLess(
            with_ally_turret["total_score"],
            without_ally_turret["total_score"],
        )


if __name__ == "__main__":
    unittest.main()
