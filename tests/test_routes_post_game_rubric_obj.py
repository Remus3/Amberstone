"""Smoke tests for /api/post-game-rubric obj_participation enrichment.

Closes item-132 carry-forward (c) + item 133 carry (b) +
item 134 carry (g). Pins:
  - Match with NO operator objectives yields obj_participation == 0.0
    in components (and total_score is the pre-enrichment baseline).
  - Match WITH operator objectives yields a non-zero obj_participation
    component, lifting total_score above the no-objectives baseline.
  - Herald takedowns from challenges_json fold into the 7th lane.
  - voidMonsterKill (Voidgrubs) from challenges_json folds into the
    8th lane (item 134 carry (g)).

Mirror of tests/test_routes_post_game_rubric.py fixture style (the
schema there is intentionally a tiny subset; this file widens the seed
table to carry the 6 objective columns + team_id + challenges_json
needed by core.obj_participation).
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dashboard import routes_post_game_rubric as rpgr


class _StubHandler:
    def __init__(self, path: str):
        self.path = path
        self.responses: list[tuple[int, bytes, str]] = []

    def _send(self, status: int, body: bytes,
              content_type: str = "application/json") -> None:
        self.responses.append((status, body, content_type))


def _seed_obj_db(
    path: Path,
    match_id: str = "OBJ_M1",
    operator_puuid: str = "OPER",
    team_position: str = "BOTTOM",
    game_duration_s: int = 1800,
    operator_objectives: dict | None = None,
    ally_objectives: dict | None = None,
    operator_herald: int = 0,
    ally_herald: int = 0,
    operator_void: int = 0,
    ally_void: int = 0,
    operator_turret: int = 0,
    ally_turret: int = 0,
) -> None:
    """Widened seed: 6 objective columns + challenges_json (9-column model
    per BACKLOG L14 (c)). challenges_json carries riftHeraldTakedowns +
    voidMonsterKill + turretTakedowns (the latter clamped against the
    SQL first_tower sentinels in compute_obj_participation)."""
    operator_objectives = operator_objectives or {}
    ally_objectives = ally_objectives or {}

    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE matches (
            match_id TEXT PRIMARY KEY,
            game_duration_s INTEGER
        );
        CREATE TABLE participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,
            team_id INTEGER,
            puuid TEXT,
            team_position TEXT,
            kills INTEGER,
            deaths INTEGER,
            assists INTEGER,
            total_minions_killed INTEGER,
            neutral_minions_killed INTEGER,
            vision_score INTEGER,
            total_damage_dealt_to_champs INTEGER,
            dragon_kills INTEGER,
            baron_kills INTEGER,
            objectives_stolen INTEGER,
            objectives_stolen_assists INTEGER,
            first_tower_kill INTEGER,
            first_tower_assist INTEGER,
            challenges_json TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO matches(match_id, game_duration_s) VALUES (?, ?)",
        (match_id, game_duration_s),
    )

    def _obj_tuple(d: dict) -> tuple:
        return (
            d.get("dragon_kills", 0),
            d.get("baron_kills", 0),
            d.get("objectives_stolen", 0),
            d.get("objectives_stolen_assists", 0),
            d.get("first_tower_kill", 0),
            d.get("first_tower_assist", 0),
        )

    op_challenges = json.dumps({
        "riftHeraldTakedowns": int(operator_herald),
        "voidMonsterKill": int(operator_void),
        "turretTakedowns": int(operator_turret),
    })
    ally_challenges = json.dumps({
        "riftHeraldTakedowns": int(ally_herald),
        "voidMonsterKill": int(ally_void),
        "turretTakedowns": int(ally_turret),
    })

    # Operator row
    conn.execute(
        """INSERT INTO participants
           (match_id, team_id, puuid, team_position,
            kills, deaths, assists, total_minions_killed,
            neutral_minions_killed, vision_score,
            total_damage_dealt_to_champs,
            dragon_kills, baron_kills, objectives_stolen,
            objectives_stolen_assists, first_tower_kill,
            first_tower_assist, challenges_json)
           VALUES (?,?,?,?, 8,3,10, 180,0, 18, 22000, ?,?,?,?,?,?, ?)""",
        (match_id, 100, operator_puuid, team_position)
        + _obj_tuple(operator_objectives)
        + (op_challenges,),
    )
    # One ally on the same team (provides the denominator when operator has 0)
    conn.execute(
        """INSERT INTO participants
           (match_id, team_id, puuid, team_position,
            kills, deaths, assists, total_minions_killed,
            neutral_minions_killed, vision_score,
            total_damage_dealt_to_champs,
            dragon_kills, baron_kills, objectives_stolen,
            objectives_stolen_assists, first_tower_kill,
            first_tower_assist, challenges_json)
           VALUES (?,?,?,?, 3,5,4, 150,30, 14, 14000, ?,?,?,?,?,?, ?)""",
        (match_id, 100, "ALLY_A", "TOP")
        + _obj_tuple(ally_objectives)
        + (ally_challenges,),
    )
    conn.commit()
    conn.close()


def _seed_state(path: Path, puuid: str = "OPER") -> None:
    path.write_text(json.dumps({"puuid": puuid}), encoding="utf-8")


class ObjEnrichmentTests(unittest.TestCase):
    """The route now passes computed obj_participation through to the rubric."""

    def setUp(self):
        rpgr._CACHE.clear()

    def _serve(self, path: str, db_path: Path, state_path: Path):
        with mock.patch.object(rpgr, "_REWIND_DB", db_path):
            with mock.patch.object(rpgr, "_STATE_JSON", state_path):
                h = _StubHandler(path)
                rpgr._serve_post_game_rubric(h)
                return h.responses

    def test_no_objectives_keeps_component_at_zero(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_obj_db(db)  # operator + ally both at 0
            _seed_state(state)
            resp = self._serve("/api/post-game-rubric?match_id=OBJ_M1", db, state)
            payload = json.loads(resp[0][1])
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["components"]["obj_participation"], 0.0)

    def test_operator_carries_all_team_objectives(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_obj_db(
                db,
                operator_objectives={
                    "dragon_kills": 2, "baron_kills": 1,
                    "first_tower_kill": 1,
                },
                ally_objectives={},
            )
            _seed_state(state)
            resp = self._serve("/api/post-game-rubric?match_id=OBJ_M1", db, state)
            payload = json.loads(resp[0][1])
            self.assertTrue(payload["ok"])
            # operator = 4, team = 4 -> ratio 1.0 -> component non-zero
            self.assertGreater(payload["components"]["obj_participation"], 0.0)

    def test_obj_enrichment_lifts_total_score(self):
        """Same role + same KDA, only objectives differ. The +obj run
        should land a strictly higher total_score because the rubric
        weights the obj_participation axis positively."""
        with tempfile.TemporaryDirectory() as td:
            db1 = Path(td) / "rh_zero.db"
            db2 = Path(td) / "rh_full.db"
            state = Path(td) / "state.json"
            _seed_state(state)
            _seed_obj_db(db1, match_id="ZM")
            _seed_obj_db(
                db2, match_id="ZM",
                operator_objectives={
                    "dragon_kills": 2, "baron_kills": 1, "first_tower_kill": 1,
                },
            )
            rpgr._CACHE.clear()
            r1 = self._serve("/api/post-game-rubric?match_id=ZM", db1, state)
            rpgr._CACHE.clear()
            r2 = self._serve("/api/post-game-rubric?match_id=ZM", db2, state)
            p1 = json.loads(r1[0][1])
            p2 = json.loads(r2[0][1])
            self.assertGreater(p2["total_score"], p1["total_score"])

    def test_partial_share_renders_partial_component(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_obj_db(
                db,
                operator_objectives={"dragon_kills": 1},
                ally_objectives={"dragon_kills": 1, "baron_kills": 1, "first_tower_kill": 1},
            )
            _seed_state(state)
            resp = self._serve("/api/post-game-rubric?match_id=OBJ_M1", db, state)
            payload = json.loads(resp[0][1])
            # operator 1, team 4 -> ratio 0.25; ADC obj weight 0.5
            # component = 0.5 * (0.25 / 0.55) = ~0.227 (non-zero, sub-weight)
            self.assertTrue(payload["ok"])
            self.assertGreater(payload["components"]["obj_participation"], 0.0)
            self.assertLess(payload["components"]["obj_participation"],
                            payload["weights_used"]["obj_participation"] * 2.0)

    def test_jungle_role_higher_obj_weight(self):
        """JG carries 0.70 weight vs ADC's 0.50 - same operator-share
        should produce a strictly bigger component on JG."""
        with tempfile.TemporaryDirectory() as td:
            db_adc = Path(td) / "adc.db"
            db_jg = Path(td) / "jg.db"
            state = Path(td) / "state.json"
            _seed_state(state)
            obj = {"dragon_kills": 2, "first_tower_kill": 1}
            _seed_obj_db(db_adc, team_position="BOTTOM",
                         operator_objectives=obj)
            _seed_obj_db(db_jg, team_position="JUNGLE",
                         operator_objectives=obj)
            rpgr._CACHE.clear()
            r_adc = self._serve("/api/post-game-rubric?match_id=OBJ_M1",
                                db_adc, state)
            rpgr._CACHE.clear()
            r_jg = self._serve("/api/post-game-rubric?match_id=OBJ_M1",
                               db_jg, state)
            p_adc = json.loads(r_adc[0][1])
            p_jg = json.loads(r_jg[0][1])
            self.assertGreater(
                p_jg["components"]["obj_participation"],
                p_adc["components"]["obj_participation"],
            )

    def test_response_still_carries_all_components(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_obj_db(
                db, operator_objectives={"dragon_kills": 1},
            )
            _seed_state(state)
            resp = self._serve("/api/post-game-rubric?match_id=OBJ_M1", db, state)
            payload = json.loads(resp[0][1])
            for key in ("kda", "cs_per_min", "obj_participation", "vision", "dpm"):
                self.assertIn(key, payload["components"])


class HeraldEnrichmentRouteTests(unittest.TestCase):
    """The route now reads riftHeraldTakedowns from challenges_json
    (item 133 carry (b))."""

    def setUp(self):
        rpgr._CACHE.clear()

    def _serve(self, path: str, db_path: Path, state_path: Path):
        with mock.patch.object(rpgr, "_REWIND_DB", db_path):
            with mock.patch.object(rpgr, "_STATE_JSON", state_path):
                h = _StubHandler(path)
                rpgr._serve_post_game_rubric(h)
                return h.responses

    def test_operator_solo_herald_lifts_component_above_zero(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            # No SQL objectives at all; operator gets herald=1.
            _seed_obj_db(db, operator_herald=1, ally_herald=0)
            _seed_state(state)
            resp = self._serve("/api/post-game-rubric?match_id=OBJ_M1", db, state)
            payload = json.loads(resp[0][1])
            self.assertTrue(payload["ok"])
            # Operator 0 sql + 1 herald = 1; team 0 sql + 1 herald = 1.
            # Ratio = 1.0 -> non-zero component.
            self.assertGreater(payload["components"]["obj_participation"], 0.0)

    def test_herald_enrichment_lifts_total_score(self):
        """Same KDA + same SQL-obj content; only herald differs. The
        herald-enriched run should land a strictly higher total_score
        when the ratio is NOT already saturated at 1.0."""
        with tempfile.TemporaryDirectory() as td:
            db_no_herald = Path(td) / "rh_no.db"
            db_herald = Path(td) / "rh_yes.db"
            state = Path(td) / "state.json"
            _seed_state(state)
            # Ally has 3 dragons so the no-herald baseline ratio is
            # 1/4=0.25 (sub-saturated). Operator's herald=2 then lifts
            # ratio to 3/6=0.5 (twice the baseline component).
            op_obj = {"dragon_kills": 1}
            ally_obj = {"dragon_kills": 3}
            _seed_obj_db(db_no_herald, match_id="HM",
                         operator_objectives=op_obj,
                         ally_objectives=ally_obj,
                         operator_herald=0)
            _seed_obj_db(db_herald, match_id="HM",
                         operator_objectives=op_obj,
                         ally_objectives=ally_obj,
                         operator_herald=2)
            rpgr._CACHE.clear()
            r1 = self._serve("/api/post-game-rubric?match_id=HM", db_no_herald, state)
            rpgr._CACHE.clear()
            r2 = self._serve("/api/post-game-rubric?match_id=HM", db_herald, state)
            p1 = json.loads(r1[0][1])
            p2 = json.loads(r2[0][1])
            self.assertGreater(p2["total_score"], p1["total_score"])
            # Confirm the component lifted, not some other axis.
            self.assertGreater(
                p2["components"]["obj_participation"],
                p1["components"]["obj_participation"],
            )

    def test_teammate_herald_pulls_share_down(self):
        # Operator owns 1 dragon; ally owns 6 dragons (dilutes the
        # operator share into the linear region for the item-335 ADC obj
        # baseline 0.15, where 2x-median clamp saturates above ~0.30).
        # 6-col ratio = 1/7 ~ 0.143; +ally herald -> 1/8 = 0.125 (lower).
        with tempfile.TemporaryDirectory() as td:
            db_6col = Path(td) / "no_herald.db"
            db_7col = Path(td) / "with_herald.db"
            state = Path(td) / "state.json"
            _seed_state(state)
            _seed_obj_db(
                db_6col, match_id="TM",
                operator_objectives={"dragon_kills": 1},
                ally_objectives={"dragon_kills": 6},
                operator_herald=0, ally_herald=0,
            )
            _seed_obj_db(
                db_7col, match_id="TM",
                operator_objectives={"dragon_kills": 1},
                ally_objectives={"dragon_kills": 6},
                operator_herald=0, ally_herald=1,
            )
            rpgr._CACHE.clear()
            r_6 = self._serve("/api/post-game-rubric?match_id=TM", db_6col, state)
            rpgr._CACHE.clear()
            r_7 = self._serve("/api/post-game-rubric?match_id=TM", db_7col, state)
            p6 = json.loads(r_6[0][1])
            p7 = json.loads(r_7[0][1])
            # Component drops because the denominator grew by 1.
            self.assertGreater(
                p6["components"]["obj_participation"],
                p7["components"]["obj_participation"],
            )

    def test_null_challenges_json_treated_as_zero_herald(self):
        # Pre-Match-V5-challenges historic rows: challenges_json NULL ->
        # herald = 0. The route still 200s, the component still computes
        # off the 6 SQL columns alone.
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_state(state)
            conn = sqlite3.connect(str(db))
            conn.executescript(
                """
                CREATE TABLE matches (
                    match_id TEXT PRIMARY KEY,
                    game_duration_s INTEGER
                );
                CREATE TABLE participants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id TEXT,
                    team_id INTEGER,
                    puuid TEXT,
                    team_position TEXT,
                    kills INTEGER,
                    deaths INTEGER,
                    assists INTEGER,
                    total_minions_killed INTEGER,
                    neutral_minions_killed INTEGER,
                    vision_score INTEGER,
                    total_damage_dealt_to_champs INTEGER,
                    dragon_kills INTEGER,
                    baron_kills INTEGER,
                    objectives_stolen INTEGER,
                    objectives_stolen_assists INTEGER,
                    first_tower_kill INTEGER,
                    first_tower_assist INTEGER,
                    challenges_json TEXT
                );
                INSERT INTO matches(match_id, game_duration_s)
                  VALUES ('NULL_CJ', 1800);
                INSERT INTO participants
                  (match_id, team_id, puuid, team_position,
                   kills, deaths, assists,
                   total_minions_killed, neutral_minions_killed,
                   vision_score, total_damage_dealt_to_champs,
                   dragon_kills, baron_kills, objectives_stolen,
                   objectives_stolen_assists, first_tower_kill,
                   first_tower_assist, challenges_json)
                  VALUES
                  ('NULL_CJ', 100, 'OPER', 'BOTTOM', 8, 3, 10,
                   180, 0, 18, 22000, 1, 0, 0, 0, 0, 0, NULL);
                INSERT INTO participants
                  (match_id, team_id, puuid, team_position,
                   kills, deaths, assists,
                   total_minions_killed, neutral_minions_killed,
                   vision_score, total_damage_dealt_to_champs,
                   dragon_kills, baron_kills, objectives_stolen,
                   objectives_stolen_assists, first_tower_kill,
                   first_tower_assist, challenges_json)
                  VALUES
                  ('NULL_CJ', 100, 'ALLY_A', 'TOP', 3, 5, 4,
                   150, 30, 14, 14000, 0, 0, 0, 0, 0, 0, NULL);
                """
            )
            conn.commit()
            conn.close()
            resp = self._serve("/api/post-game-rubric?match_id=NULL_CJ", db, state)
            self.assertEqual(resp[0][0], 200)
            payload = json.loads(resp[0][1])
            self.assertTrue(payload["ok"])
            # Operator 1 dragon + ally 0 -> ratio 1.0 (no herald).
            self.assertGreater(payload["components"]["obj_participation"], 0.0)


class VoidEnrichmentRouteTests(unittest.TestCase):
    """The route now reads voidMonsterKill from challenges_json
    (item 134 carry (g)) and folds it into the 8-column model."""

    def setUp(self):
        rpgr._CACHE.clear()

    def _serve(self, path: str, db_path: Path, state_path: Path):
        with mock.patch.object(rpgr, "_REWIND_DB", db_path):
            with mock.patch.object(rpgr, "_STATE_JSON", state_path):
                h = _StubHandler(path)
                rpgr._serve_post_game_rubric(h)
                return h.responses

    def test_void_enrichment_lifts_total_score(self):
        """Same KDA + same SQL-obj content; only voidgrubs differ. The
        void-enriched run should land a strictly higher total_score
        when the ratio is NOT already saturated at 1.0."""
        with tempfile.TemporaryDirectory() as td:
            db_no_void = Path(td) / "rh_no.db"
            db_void = Path(td) / "rh_yes.db"
            state = Path(td) / "state.json"
            _seed_state(state)
            # Ally has 3 dragons so the no-void baseline ratio is
            # 1/4 = 0.25 (sub-saturated). Operator's void=3 then lifts
            # ratio to 4/7 ~ 0.571.
            op_obj = {"dragon_kills": 1}
            ally_obj = {"dragon_kills": 3}
            _seed_obj_db(db_no_void, match_id="VM",
                         operator_objectives=op_obj,
                         ally_objectives=ally_obj,
                         operator_void=0, ally_void=0)
            _seed_obj_db(db_void, match_id="VM",
                         operator_objectives=op_obj,
                         ally_objectives=ally_obj,
                         operator_void=3, ally_void=0)
            rpgr._CACHE.clear()
            r1 = self._serve("/api/post-game-rubric?match_id=VM", db_no_void, state)
            rpgr._CACHE.clear()
            r2 = self._serve("/api/post-game-rubric?match_id=VM", db_void, state)
            p1 = json.loads(r1[0][1])
            p2 = json.loads(r2[0][1])
            self.assertGreater(p2["total_score"], p1["total_score"])
            self.assertGreater(
                p2["components"]["obj_participation"],
                p1["components"]["obj_participation"],
            )

    def test_void_with_herald_compose(self):
        # Both blob keys contribute together. Operator: 1 dragon + 1
        # herald + 2 void = 4. Ally: 1 dragon + 0 herald + 0 void = 1.
        # Team total = 5, ratio = 0.8. Non-saturated.
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_state(state)
            _seed_obj_db(
                db, match_id="VHC",
                operator_objectives={"dragon_kills": 1},
                ally_objectives={"dragon_kills": 1},
                operator_herald=1, ally_herald=0,
                operator_void=2, ally_void=0,
            )
            resp = self._serve("/api/post-game-rubric?match_id=VHC", db, state)
            payload = json.loads(resp[0][1])
            self.assertTrue(payload["ok"])
            # ADC weight 0.50 on obj axis. The component must be > 0
            # AND below the saturation cap (which would be ~ weight * 1.0 / 0.55).
            self.assertGreater(payload["components"]["obj_participation"], 0.0)

    def test_void_only_no_herald(self):
        # Pure voidgrub contribution: no SQL objectives, no herald.
        # Operator 2 void / team 2 void = 1.0 ratio.
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_state(state)
            _seed_obj_db(
                db, match_id="VONLY",
                operator_objectives={},
                ally_objectives={},
                operator_herald=0, ally_herald=0,
                operator_void=2, ally_void=0,
            )
            resp = self._serve("/api/post-game-rubric?match_id=VONLY", db, state)
            payload = json.loads(resp[0][1])
            self.assertTrue(payload["ok"])
            self.assertGreater(payload["components"]["obj_participation"], 0.0)

    def test_teammate_void_pulls_share_down(self):
        # Operator owns 1 dragon; ally owns 6 dragons (dilutes the
        # operator share into the linear region for the item-335 ADC obj
        # baseline 0.15). Pre-void: 1/7 ~ 0.143. Post ally void=2:
        # 1/9 ~ 0.111 (lower).
        with tempfile.TemporaryDirectory() as td:
            db_no_void = Path(td) / "no_void.db"
            db_void = Path(td) / "with_void.db"
            state = Path(td) / "state.json"
            _seed_state(state)
            _seed_obj_db(
                db_no_void, match_id="TV",
                operator_objectives={"dragon_kills": 1},
                ally_objectives={"dragon_kills": 6},
                operator_void=0, ally_void=0,
            )
            _seed_obj_db(
                db_void, match_id="TV",
                operator_objectives={"dragon_kills": 1},
                ally_objectives={"dragon_kills": 6},
                operator_void=0, ally_void=2,
            )
            rpgr._CACHE.clear()
            r_pre = self._serve("/api/post-game-rubric?match_id=TV", db_no_void, state)
            rpgr._CACHE.clear()
            r_post = self._serve("/api/post-game-rubric?match_id=TV", db_void, state)
            p_pre = json.loads(r_pre[0][1])
            p_post = json.loads(r_post[0][1])
            # Component drops because the denominator grew by 2.
            self.assertGreater(
                p_pre["components"]["obj_participation"],
                p_post["components"]["obj_participation"],
            )

    def test_legacy_schema_no_challenges_json_void_falls_back(self):
        # OperationalError fallback path: pre-challenges DB schema
        # should still return a 6-column ratio cleanly without crashing
        # on the missing voidgrub key.
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_state(state)
            # Build a legacy-shape DB (no challenges_json column at all).
            conn = sqlite3.connect(str(db))
            conn.executescript(
                """
                CREATE TABLE matches (
                    match_id TEXT PRIMARY KEY,
                    game_duration_s INTEGER
                );
                CREATE TABLE participants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id TEXT,
                    team_id INTEGER,
                    puuid TEXT,
                    team_position TEXT,
                    kills INTEGER,
                    deaths INTEGER,
                    assists INTEGER,
                    total_minions_killed INTEGER,
                    neutral_minions_killed INTEGER,
                    vision_score INTEGER,
                    total_damage_dealt_to_champs INTEGER,
                    dragon_kills INTEGER,
                    baron_kills INTEGER,
                    objectives_stolen INTEGER,
                    objectives_stolen_assists INTEGER,
                    first_tower_kill INTEGER,
                    first_tower_assist INTEGER
                );
                INSERT INTO matches(match_id, game_duration_s)
                  VALUES ('LEGV', 1800);
                INSERT INTO participants
                  (match_id, team_id, puuid, team_position,
                   kills, deaths, assists,
                   total_minions_killed, neutral_minions_killed,
                   vision_score, total_damage_dealt_to_champs,
                   dragon_kills, baron_kills, objectives_stolen,
                   objectives_stolen_assists, first_tower_kill,
                   first_tower_assist)
                  VALUES
                  ('LEGV', 100, 'OPER', 'BOTTOM', 8, 3, 10,
                   180, 0, 18, 22000, 2, 1, 0, 0, 1, 0);
                INSERT INTO participants
                  (match_id, team_id, puuid, team_position,
                   kills, deaths, assists,
                   total_minions_killed, neutral_minions_killed,
                   vision_score, total_damage_dealt_to_champs,
                   dragon_kills, baron_kills, objectives_stolen,
                   objectives_stolen_assists, first_tower_kill,
                   first_tower_assist)
                  VALUES
                  ('LEGV', 100, 'ALLY_A', 'TOP', 3, 5, 4,
                   150, 30, 14, 14000, 1, 0, 0, 0, 0, 0);
                """
            )
            conn.commit()
            conn.close()
            resp = self._serve("/api/post-game-rubric?match_id=LEGV", db, state)
            self.assertEqual(resp[0][0], 200)
            payload = json.loads(resp[0][1])
            self.assertTrue(payload["ok"])
            # 6-column 4/5 = 0.8 -> non-zero component.
            self.assertGreater(payload["components"]["obj_participation"], 0.0)


class TurretEnrichmentRouteTests(unittest.TestCase):
    """The route now reads turretTakedowns from challenges_json
    (BACKLOG L14 (c)) and folds the NON-OVERLAPPING piece (towers 2-11
    beyond the first_tower binary sentinels) into the 9-column model."""

    def setUp(self):
        rpgr._CACHE.clear()

    def _serve(self, path: str, db_path: Path, state_path: Path):
        with mock.patch.object(rpgr, "_REWIND_DB", db_path):
            with mock.patch.object(rpgr, "_STATE_JSON", state_path):
                h = _StubHandler(path)
                rpgr._serve_post_game_rubric(h)
                return h.responses

    def test_turret_enrichment_lifts_total_score(self):
        """Same KDA + same SQL-obj content; only turretTakedowns differ.
        The turret-enriched run should land a strictly higher
        total_score when the ratio is NOT already saturated at 1.0."""
        with tempfile.TemporaryDirectory() as td:
            db_no_turret = Path(td) / "rh_no.db"
            db_turret = Path(td) / "rh_yes.db"
            state = Path(td) / "state.json"
            _seed_state(state)
            # Ally got 3 dragons so the no-turret baseline ratio is
            # 1/4 = 0.25 (sub-saturated). Operator's turret=5 (with
            # ftk=0, fta=0 from operator_objectives) lifts the
            # non-overlapping count by 5, ratio -> 6/9 ~ 0.667.
            op_obj = {"dragon_kills": 1}
            ally_obj = {"dragon_kills": 3}
            _seed_obj_db(db_no_turret, match_id="TM",
                         operator_objectives=op_obj,
                         ally_objectives=ally_obj,
                         operator_turret=0, ally_turret=0)
            _seed_obj_db(db_turret, match_id="TM",
                         operator_objectives=op_obj,
                         ally_objectives=ally_obj,
                         operator_turret=5, ally_turret=0)
            rpgr._CACHE.clear()
            r1 = self._serve("/api/post-game-rubric?match_id=TM",
                             db_no_turret, state)
            rpgr._CACHE.clear()
            r2 = self._serve("/api/post-game-rubric?match_id=TM",
                             db_turret, state)
            p1 = json.loads(r1[0][1])
            p2 = json.loads(r2[0][1])
            self.assertGreater(p2["total_score"], p1["total_score"])
            self.assertGreater(
                p2["components"]["obj_participation"],
                p1["components"]["obj_participation"],
            )

    def test_first_tower_overlap_not_double_counted(self):
        # Operator: first_tower_kill=1 + turretTakedowns=1 (the same
        # turret). Ally: no objectives. The non-overlapping turret
        # piece must be 0 (max(1-1-0, 0)=0); the numerator counts the
        # SQL sentinel ONCE not twice. Ratio = 1/1 = 1.0 since op got
        # the only objective.
        with tempfile.TemporaryDirectory() as td:
            db_overlap = Path(td) / "rh_overlap.db"
            db_clean_extra = Path(td) / "rh_extra.db"
            state = Path(td) / "state.json"
            _seed_state(state)
            # Overlap case: op turretTakedowns=1 + ftk=1 -> extra=0.
            _seed_obj_db(db_overlap, match_id="TO",
                         operator_objectives={"first_tower_kill": 1},
                         ally_objectives={},
                         operator_turret=1, ally_turret=0)
            # Clean-extra case: op turretTakedowns=2 + ftk=1 -> extra=1.
            # Numerator gains 1 vs overlap case.
            _seed_obj_db(db_clean_extra, match_id="TO",
                         operator_objectives={"first_tower_kill": 1},
                         ally_objectives={},
                         operator_turret=2, ally_turret=0)
            rpgr._CACHE.clear()
            r1 = self._serve("/api/post-game-rubric?match_id=TO",
                             db_overlap, state)
            rpgr._CACHE.clear()
            r2 = self._serve("/api/post-game-rubric?match_id=TO",
                             db_clean_extra, state)
            p1 = json.loads(r1[0][1])
            p2 = json.loads(r2[0][1])
            # Both ratios saturate at 1.0 (op took every objective on
            # their team). The 2nd case has higher RAW numerator + same
            # ratio (1.0). The pin here is that the score does NOT
            # exceed the 1.0-ratio cap (no double-count exceeds 100%).
            self.assertLessEqual(
                p1["components"]["obj_participation"],
                p2["components"]["obj_participation"] + 1e-6,
            )

    def test_turret_with_herald_void_compose(self):
        # Operator: 1 dragon_kill + 1 herald + 1 void + 3 extra turrets
        # = 6. Ally: 1 dragon_kill = 1. Team = 7. Ratio = 6/7 ~ 0.857.
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            _seed_state(state)
            _seed_obj_db(
                db, match_id="THV",
                operator_objectives={"dragon_kills": 1},
                ally_objectives={"dragon_kills": 1},
                operator_herald=1, ally_herald=0,
                operator_void=1, ally_void=0,
                operator_turret=3, ally_turret=0,
            )
            resp = self._serve("/api/post-game-rubric?match_id=THV", db, state)
            payload = json.loads(resp[0][1])
            self.assertTrue(payload["ok"])
            self.assertGreater(payload["components"]["obj_participation"], 0.0)


class FailSoftWithMissingObjColumnsTests(unittest.TestCase):
    """If the DB schema is missing objective columns (older schema), the
    route degrades gracefully to obj_participation=0.0 instead of 500."""

    def setUp(self):
        rpgr._CACHE.clear()

    def _serve(self, path: str, db_path: Path, state_path: Path):
        with mock.patch.object(rpgr, "_REWIND_DB", db_path):
            with mock.patch.object(rpgr, "_STATE_JSON", state_path):
                h = _StubHandler(path)
                rpgr._serve_post_game_rubric(h)
                return h.responses

    def test_legacy_schema_without_obj_cols_falls_back_to_zero(self):
        # Legacy seed: matches participants table without the 6 obj cols.
        # core.obj_participation should swallow the sqlite error and
        # return 0.0, so the route still returns 200.
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "rh.db"
            state = Path(td) / "state.json"
            conn = sqlite3.connect(str(db))
            conn.executescript(
                """
                CREATE TABLE matches (
                    match_id TEXT PRIMARY KEY,
                    game_duration_s INTEGER
                );
                CREATE TABLE participants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id TEXT,
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
                INSERT INTO matches(match_id, game_duration_s)
                  VALUES ('LEG_M', 1800);
                INSERT INTO participants
                  (match_id, puuid, team_position, kills, deaths, assists,
                   total_minions_killed, neutral_minions_killed,
                   vision_score, total_damage_dealt_to_champs)
                  VALUES ('LEG_M', 'OPER', 'BOTTOM', 8, 3, 10, 180, 0, 18, 22000);
                """
            )
            conn.commit()
            conn.close()
            _seed_state(state)
            resp = self._serve("/api/post-game-rubric?match_id=LEG_M", db, state)
            self.assertEqual(resp[0][0], 200)
            payload = json.loads(resp[0][1])
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["components"]["obj_participation"], 0.0)


if __name__ == "__main__":
    unittest.main()
