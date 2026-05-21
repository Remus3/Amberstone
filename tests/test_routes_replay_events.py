"""Tests for the s220 PGR S5 Match-V5 timeline events route.

GET /api/replay/events?match_id=<id>[&include=items,skills,wards,all]

The route reads discrete events from
``data/rewind_history.db.timeline_events`` and returns the
chronological ribbon the Replay page renders under the per-frame
scrubber.

Synthetic DB only - the route opens the DB via the
``_REWIND_DB`` module global, so tests monkey-patch that path to a
seeded temp DB. No real rewind_history.db dependency.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from dashboard import routes_replay_events as routes


# ── fake handler mirroring the BaseHTTPRequestHandler surface the
#    route uses (only `path` + `_send`). ────────────────────────────────

class _FakeHandler:
    def __init__(self, path: str):
        self.path = path
        self.responses: list[tuple[int, bytes, str]] = []

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.responses.append((status, body, content_type))

    @property
    def last(self) -> tuple[int, dict, str]:
        assert self.responses, "no response sent"
        status, body, ct = self.responses[-1]
        return status, json.loads(body), ct


def _seed_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE matches (
                match_id TEXT PRIMARY KEY,
                queue_id INTEGER,
                duration_s INTEGER
            );
            CREATE TABLE participants (
                match_id TEXT,
                participant_id INTEGER,
                team_id INTEGER,
                summoner_name TEXT,
                champion_name TEXT
            );
            CREATE TABLE timeline_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL,
                timestamp_ms INTEGER,
                event_type TEXT,
                participant_id INTEGER,
                item_id INTEGER,
                killer_id INTEGER,
                victim_id INTEGER,
                assisting_ids_json TEXT,
                bounty INTEGER,
                shutdown_bounty INTEGER,
                kill_streak_len INTEGER,
                kill_pos_x INTEGER,
                kill_pos_y INTEGER,
                victim_damage_json TEXT,
                building_type TEXT,
                lane_type TEXT,
                tower_type TEXT,
                team_id INTEGER,
                monster_type TEXT,
                monster_subtype TEXT,
                ward_type TEXT,
                skill_slot INTEGER,
                level_up_type TEXT,
                level INTEGER,
                raw_json TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO matches(match_id, queue_id, duration_s) VALUES (?, ?, ?)",
            ("NA1_TEST_001", 420, 1800),
        )
        # 5 participants per side, mirror Riot's 1..10 ids.
        for pid in range(1, 6):
            conn.execute(
                "INSERT INTO participants(match_id, participant_id, team_id, summoner_name, champion_name) "
                "VALUES (?, ?, 100, ?, ?)",
                ("NA1_TEST_001", pid, f"Ally{pid}", f"Champ{pid}"),
            )
        for pid in range(6, 11):
            conn.execute(
                "INSERT INTO participants(match_id, participant_id, team_id, summoner_name, champion_name) "
                "VALUES (?, ?, 200, ?, ?)",
                ("NA1_TEST_001", pid, f"Enemy{pid - 5}", f"Champ{pid}"),
            )
        # Strong events.
        conn.execute(
            "INSERT INTO timeline_events(match_id, timestamp_ms, event_type, killer_id, "
            "victim_id, assisting_ids_json, kill_pos_x, kill_pos_y) "
            "VALUES (?, ?, 'CHAMPION_KILL', ?, ?, ?, ?, ?)",
            ("NA1_TEST_001", 60_000, 2, 8, "[3, 5]", 6126, 13581),
        )
        conn.execute(
            "INSERT INTO timeline_events(match_id, timestamp_ms, event_type, killer_id, "
            "team_id, building_type, lane_type, tower_type) "
            "VALUES (?, ?, 'BUILDING_KILL', ?, ?, 'TOWER_BUILDING', 'MID_LANE', 'OUTER_TURRET')",
            ("NA1_TEST_001", 360_000, 3, 200),
        )
        conn.execute(
            "INSERT INTO timeline_events(match_id, timestamp_ms, event_type, killer_id, "
            "monster_type, monster_subtype) "
            "VALUES (?, ?, 'ELITE_MONSTER_KILL', ?, 'DRAGON', 'INFERNAL_DRAGON')",
            ("NA1_TEST_001", 480_000, 4),
        )
        conn.execute(
            "INSERT INTO timeline_events(match_id, timestamp_ms, event_type, killer_id, "
            "team_id, building_type, lane_type, tower_type) "
            "VALUES (?, ?, 'TURRET_PLATE_DESTROYED', ?, ?, 'TOWER_BUILDING', 'TOP_LANE', NULL)",
            ("NA1_TEST_001", 480_000, 5, 200),
        )
        # Item event - NOT in strong set; opt-in via ?include=items.
        conn.execute(
            "INSERT INTO timeline_events(match_id, timestamp_ms, event_type, participant_id, item_id) "
            "VALUES (?, ?, 'ITEM_PURCHASED', 1, 3865)",
            ("NA1_TEST_001", 90_000),
        )
        # Skill event - opt-in via ?include=skills.
        conn.execute(
            "INSERT INTO timeline_events(match_id, timestamp_ms, event_type, participant_id, skill_slot, level_up_type, level) "
            "VALUES (?, ?, 'SKILL_LEVEL_UP', 1, 1, 'NORMAL', 2)",
            ("NA1_TEST_001", 120_000),
        )
        # Ward event - opt-in via ?include=wards.
        conn.execute(
            "INSERT INTO timeline_events(match_id, timestamp_ms, event_type, participant_id, ward_type) "
            "VALUES (?, ?, 'WARD_PLACED', 5, 'YELLOW_TRINKET')",
            ("NA1_TEST_001", 180_000),
        )
        conn.commit()
    finally:
        conn.close()


class _DbPatchedCase(unittest.TestCase):
    """Each test seeds a fresh temp DB and patches _REWIND_DB to point
    at it. The route's TTL cache is cleared per-test so cache-keyed
    assertions are isolated."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="rc-s5-events-")
        self._db_path = Path(self._tmp_dir) / "rewind_history.db"
        _seed_db(self._db_path)
        self._patcher = patch.object(routes, "_REWIND_DB", self._db_path)
        self._patcher.start()
        routes._CACHE.clear()

    def tearDown(self):
        self._patcher.stop()
        try:
            self._db_path.unlink(missing_ok=True)
            Path(self._tmp_dir).rmdir()
        except OSError:
            pass


class StrongEventsTests(_DbPatchedCase):
    def test_returns_strong_events_in_clock_order(self):
        h = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001")
        routes._serve_replay_events(h)
        status, body, ct = h.last
        self.assertEqual(status, 200)
        self.assertEqual(ct, "application/json")
        self.assertTrue(body["ok"])
        self.assertEqual(body["match_id"], "NA1_TEST_001")
        # 4 strong events: CHAMPION_KILL, BUILDING_KILL,
        # ELITE_MONSTER_KILL, TURRET_PLATE_DESTROYED.
        self.assertEqual(body["count"], 4)
        types = [e["type"] for e in body["events"]]
        self.assertEqual(types, [
            "CHAMPION_KILL",
            "BUILDING_KILL",
            "ELITE_MONSTER_KILL",
            "TURRET_PLATE_DESTROYED",
        ])
        clocks = [e["clock_s"] for e in body["events"]]
        self.assertEqual(clocks, sorted(clocks), "events must be clock-asc")

    def test_strong_events_default_excludes_items_skills_wards(self):
        h = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001")
        routes._serve_replay_events(h)
        _, body, _ = h.last
        types = {e["type"] for e in body["events"]}
        for forbidden in ("ITEM_PURCHASED", "SKILL_LEVEL_UP",
                           "LEVEL_UP", "WARD_PLACED", "WARD_KILL"):
            self.assertNotIn(forbidden, types,
                             f"{forbidden} leaked into default ribbon")

    def test_champion_kill_carries_actor_victim_assists_pos(self):
        h = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001")
        routes._serve_replay_events(h)
        _, body, _ = h.last
        kill = body["events"][0]
        self.assertEqual(kill["type"], "CHAMPION_KILL")
        self.assertEqual(kill["clock_s"], 60)
        self.assertEqual(kill["actor"], 2)
        self.assertEqual(kill["victim"], 8)
        self.assertEqual(kill["assists"], [3, 5])
        self.assertEqual(kill["pos"], [6126, 13581])
        # actor 2 is on team 100 (allies) - ribbon paints by destroyer side.
        self.assertEqual(kill["team"], 100)

    def test_champion_kill_carries_participant_names_and_champs(self):
        """s220 carry-forward: events join participants table so the
        ribbon paints real summoner_name + champion_name instead of
        P<id> chips."""
        h = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001")
        routes._serve_replay_events(h)
        _, body, _ = h.last
        kill = body["events"][0]
        # actor pid=2 on team 100 -> Ally2 + Champ2 (per _seed_db).
        self.assertEqual(kill["actor_name"], "Ally2")
        self.assertEqual(kill["actor_champion"], "Champ2")
        # victim pid=8 on team 200 -> Enemy3 (8-5=3) + Champ8.
        self.assertEqual(kill["victim_name"], "Enemy3")
        self.assertEqual(kill["victim_champion"], "Champ8")
        # assists pid=[3, 5] -> Ally3 + Ally5 + Champ3 + Champ5.
        self.assertEqual(kill["assists_names"], ["Ally3", "Ally5"])
        self.assertEqual(kill["assists_champs"], ["Champ3", "Champ5"])

    def test_assist_names_use_null_parity_for_unknown_pid(self):
        """assists_names + assists_champs preserve list length parity
        with assists; missing meta rows surface as None (NOT ""), to
        match the actor_name/victim_name null convention."""
        h = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001")
        routes._serve_replay_events(h)
        _, body, _ = h.last
        # Synthesize an event with an unknown assist via direct DB poke,
        # bust the cache, then re-fetch.
        import sqlite3
        conn = sqlite3.connect(str(routes._REWIND_DB))
        try:
            conn.execute(
                "INSERT INTO timeline_events(match_id, timestamp_ms, event_type, "
                "killer_id, victim_id, assisting_ids_json) "
                "VALUES (?, 240000, 'CHAMPION_KILL', 1, 6, '[7, 99]')",
                ("NA1_TEST_001",),
            )
            conn.commit()
        finally:
            conn.close()
        routes._CACHE.clear()
        h2 = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001")
        routes._serve_replay_events(h2)
        _, body2, _ = h2.last
        kills = [e for e in body2["events"] if e["clock_s"] == 240]
        self.assertEqual(len(kills), 1)
        synth = kills[0]
        # assist 7 -> Enemy2; assist 99 -> unknown -> None (null parity)
        self.assertEqual(synth["assists"], [7, 99])
        self.assertEqual(synth["assists_names"], ["Enemy2", None])
        self.assertEqual(synth["assists_champs"], ["Champ7", None])

    def test_non_actor_event_has_null_names(self):
        """ELITE_MONSTER_KILL with no killer_id and no participant_id
        should surface actor_name/champion as null, not ''."""
        h = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001")
        routes._serve_replay_events(h)
        _, body, _ = h.last
        drake = next(e for e in body["events"] if e["type"] == "ELITE_MONSTER_KILL")
        # killer_id=4 on team 100 -> Ally4 + Champ4
        self.assertEqual(drake["actor_name"], "Ally4")
        self.assertEqual(drake["actor_champion"], "Champ4")
        # No victim on monster kills.
        self.assertIsNone(drake["victim"])
        self.assertIsNone(drake["victim_name"])
        self.assertIsNone(drake["victim_champion"])

    def test_building_kill_team_is_destroyer_not_owner(self):
        """BUILDING_KILL.team_id stores the team that LOST the
        building; the ribbon should paint by DESTROYER for correct
        ally/enemy coloring. The route flips the field."""
        h = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001")
        routes._serve_replay_events(h)
        _, body, _ = h.last
        building = next(e for e in body["events"] if e["type"] == "BUILDING_KILL")
        # team_id stored = 200 (owner that lost it) -> destroyer = 100.
        self.assertEqual(building["team"], 100)
        # tower_type wins over building_type when populated.
        self.assertEqual(building["subtype"], "OUTER_TURRET")
        self.assertEqual(building["lane"], "MID_LANE")

    def test_elite_monster_subtype_winner(self):
        h = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001")
        routes._serve_replay_events(h)
        _, body, _ = h.last
        drake = next(e for e in body["events"] if e["type"] == "ELITE_MONSTER_KILL")
        # monster_subtype takes precedence over monster_type.
        self.assertEqual(drake["subtype"], "INFERNAL_DRAGON")


class IncludeFiltersTests(_DbPatchedCase):
    def test_include_items_widens_set(self):
        h = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001&include=items")
        routes._serve_replay_events(h)
        _, body, _ = h.last
        types = {e["type"] for e in body["events"]}
        self.assertIn("ITEM_PURCHASED", types)
        self.assertEqual(body["count"], 5)
        self.assertEqual(body["include"], ["items"])

    def test_include_skills_widens_set(self):
        h = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001&include=skills")
        routes._serve_replay_events(h)
        _, body, _ = h.last
        types = {e["type"] for e in body["events"]}
        self.assertIn("SKILL_LEVEL_UP", types)

    def test_include_wards_widens_set(self):
        h = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001&include=wards")
        routes._serve_replay_events(h)
        _, body, _ = h.last
        types = {e["type"] for e in body["events"]}
        self.assertIn("WARD_PLACED", types)

    def test_include_all_returns_every_type(self):
        h = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001&include=all")
        routes._serve_replay_events(h)
        _, body, _ = h.last
        types = {e["type"] for e in body["events"]}
        self.assertIn("ITEM_PURCHASED", types)
        self.assertIn("SKILL_LEVEL_UP", types)
        self.assertIn("WARD_PLACED", types)
        self.assertIn("CHAMPION_KILL", types)

    def test_invalid_include_token_ignored(self):
        h = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001&include=nope,items")
        routes._serve_replay_events(h)
        _, body, _ = h.last
        # 'nope' silently dropped; 'items' honored.
        self.assertEqual(body["include"], ["items"])


class FailureContractTests(_DbPatchedCase):
    def test_400_when_match_id_missing(self):
        h = _FakeHandler("/api/replay/events")
        routes._serve_replay_events(h)
        status, body, _ = h.last
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertIn("match_id", body["error"])

    def test_400_when_match_id_blank(self):
        h = _FakeHandler("/api/replay/events?match_id=")
        routes._serve_replay_events(h)
        status, _, _ = h.last
        self.assertEqual(status, 400)

    def test_404_when_match_unknown(self):
        h = _FakeHandler("/api/replay/events?match_id=NOPE_X")
        routes._serve_replay_events(h)
        status, body, _ = h.last
        self.assertEqual(status, 404)
        self.assertFalse(body["ok"])
        self.assertEqual(body["match_id"], "NOPE_X")

    def test_503_when_db_missing(self):
        # Point the global at a non-existent path for this test only.
        with patch.object(routes, "_REWIND_DB", self._db_path.with_suffix(".gone")):
            h = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001")
            routes._serve_replay_events(h)
            status, body, _ = h.last
            self.assertEqual(status, 503)
            self.assertFalse(body["ok"])


class CacheTests(_DbPatchedCase):
    def test_cache_hit_on_second_call(self):
        h1 = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001")
        routes._serve_replay_events(h1)
        _, body1, _ = h1.last
        self.assertFalse(body1["cached"])

        h2 = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001")
        routes._serve_replay_events(h2)
        _, body2, _ = h2.last
        self.assertTrue(body2["cached"])
        # Cached payload preserves event count + match id.
        self.assertEqual(body2["count"], body1["count"])
        self.assertEqual(body2["match_id"], body1["match_id"])

    def test_cache_key_includes_include_set(self):
        # First call - strong only. Second call - +items.
        h1 = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001")
        routes._serve_replay_events(h1)

        h2 = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001&include=items")
        routes._serve_replay_events(h2)
        _, body2, _ = h2.last
        # Different cache key -> first hit miss, not the strong-only payload.
        self.assertFalse(body2["cached"])
        self.assertEqual(body2["count"], 5)  # 4 strong + 1 item

    def test_cache_key_carries_schema_sentinel(self):
        """The cache key includes _CACHE_SCHEMA so a shape change
        (e.g. participant-name join) evicts stale pre-shape entries on
        first hit, not on TTL expiry."""
        self.assertTrue(routes._CACHE_SCHEMA)
        # Stage a stale entry under an OLD-shape key (sans schema).
        old_key = ("NA1_TEST_001", frozenset())
        import time as _t
        routes._CACHE[old_key] = (_t.time(), {"ok": True, "stale": True})
        h = _FakeHandler("/api/replay/events?match_id=NA1_TEST_001")
        routes._serve_replay_events(h)
        _, body, _ = h.last
        # The new-shape key MISSES the stale old-shape entry -> fresh.
        self.assertFalse(body["cached"])
        self.assertNotIn("stale", body)


class CleanroomDocPresenceTests(unittest.TestCase):
    """The ADR pointer keeps the route honest about the league_record
    cleanroom boundary - if the comment is dropped, this test fails."""

    def test_module_docstring_references_adr(self):
        from dashboard import routes_replay_events as r
        doc = r.__doc__ or ""
        self.assertIn("ADR-009-replay-events-cleanroom.md", doc)
        self.assertIn("league_record", doc)
        self.assertIn("GPL", doc)
        # Either the explicit "do NOT vendor" phrasing OR the
        # "forbids vendoring its source" phrasing keeps the cleanroom
        # boundary visible at the module level.
        d = doc.lower()
        self.assertTrue(
            "do not vendor" in d or "forbids vendoring" in d,
            "module docstring must call out the no-vendor cleanroom boundary",
        )
