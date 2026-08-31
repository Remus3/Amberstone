"""tests/test_routes_pickban_id_cap.py - lane 8 cycle 41.

dashboard/routes_pickban.py serves four GET routes on :8888, which binds
``::`` (all interfaces, measured 2026-08-31 via Get-NetTCPConnection), not
loopback. Every one of them takes comma-separated championId lists straight
off the query string, and NOTHING capped their length.

The sharp one is /api/champ-select/personal-record. It runs ONE
``_query_co_participant`` per element of ``allies`` and per element of
``enemies``:

    with_allies = [_query_with_ally(conn, puuid, a, queue_ids) for a in ally_ids]
    vs_enemies  = [_query_vs_enemy(conn, puuid, e, queue_ids) for e in enemy_ids]

Each of those is a correlated EXISTS subquery over ``participants`` in
data/rewind_history.db - 1.87 GB on this box. MEASURED 2026-08-31 against
the live file: 291 ms cold, 13.5 ms warm, per id. The HTTP request line caps
at 65536 bytes, so a single GET can carry roughly 32000 one-digit ids, which
is about 7 minutes of solid CPU on one handler thread holding a read
connection - from any host that can reach the port.

A real draft supplies at most 5 allies and 5 enemies. dashboard/_handler.py
already caps POST bodies (``_MAX_POST_BYTES``, lane 8 cycle 4, which fixed
the sibling "negative Content-Length pinned a handler thread from the
tailnet"). The GET side had no equivalent, and the work amplifier lives
there.

These tests pin the cap. They are written to FAIL against the pre-fix module.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dashboard import routes_pickban as RP


def _build_db(path: Path) -> None:
    """Minimal rewind_history.db shape - same columns the endpoint queries."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE matches (
            match_id TEXT PRIMARY KEY,
            queue_id INTEGER,
            game_creation_ts INTEGER
        );
        CREATE TABLE participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,
            puuid TEXT,
            team_id INTEGER,
            team_position TEXT,
            champion_id INTEGER,
            champion_name TEXT,
            win INTEGER
        );
    """)
    for i in range(6):
        mid = f"NA1_{i}"
        conn.execute(
            "INSERT INTO matches(match_id, queue_id, game_creation_ts) "
            "VALUES (?,?,?)", (mid, 420, 1_700_000_000_000 + i * 86400))
        conn.execute(
            "INSERT INTO participants(match_id, puuid, team_id, team_position, "
            "champion_id, champion_name, win) VALUES (?,?,?,?,?,?,?)",
            (mid, "OP-PUUID", 100, "BOTTOM", 22, "Ashe", i % 2))
        conn.execute(
            "INSERT INTO participants(match_id, puuid, team_id, team_position, "
            "champion_id, champion_name, win) VALUES (?,?,?,?,?,?,?)",
            (mid, "ALLY-PUUID", 100, "UTILITY", 12, "Alistar", i % 2))
    conn.commit()
    conn.close()


class _PickbanCapBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name) / "rewind_history.db"
        _build_db(self.db_path)
        p = mock.patch.object(RP, "_REWIND_DB", self.db_path)
        p.start()
        self.addCleanup(p.stop)
        RP._reset_caches()
        self.addCleanup(RP._reset_caches)

    @staticmethod
    def _call(handler, path):
        h = mock.MagicMock()
        h.path = path
        handler(h)
        h._send.assert_called_once()
        code, body, _ctype = h._send.call_args[0]
        return code, json.loads(body.decode("utf-8"))

    @staticmethod
    def _ids(n):
        return ",".join(str(1 + (i % 160)) for i in range(n))


class OversizedIdListsAreRejected(_PickbanCapBase):
    """Over-cap is a 400, never a silent truncation. 30000 ids is not a
    typo, and truncating would hide the attempt; a junk TOKEN stays
    dropped (documented _parse_csv_ints behaviour), a junk LENGTH does not."""

    def test_personal_record_rejects_oversized_allies(self):
        over = RP._MAX_ID_PARAMS + 1
        code, body = self._call(
            RP._serve_personal_record,
            "/api/champ-select/personal-record?allies=" + self._ids(over))
        self.assertEqual(code, 400)
        self.assertFalse(body["ok"])
        self.assertIn("allies", body["error"])

    def test_personal_record_rejects_oversized_enemies(self):
        over = RP._MAX_ID_PARAMS + 1
        code, body = self._call(
            RP._serve_personal_record,
            "/api/champ-select/personal-record?enemies=" + self._ids(over))
        self.assertEqual(code, 400)
        self.assertIn("enemies", body["error"])

    def test_pickban_recs_rejects_oversized_exclude(self):
        over = RP._MAX_ID_PARAMS + 1
        code, body = self._call(
            RP._serve_pickban_recs,
            "/api/champ-select/pickban-recs?role=BOT&exclude=" + self._ids(over))
        self.assertEqual(code, 400)
        self.assertIn("exclude", body["error"])

    def test_counter_picks_rejects_oversized_enemies(self):
        over = RP._MAX_ID_PARAMS + 1
        code, body = self._call(
            RP._serve_counter_picks,
            "/api/champ-select/counter-picks?enemies=" + self._ids(over))
        self.assertEqual(code, 400)
        self.assertIn("enemies", body["error"])

    def test_team_damage_mix_rejects_oversized_team_ids(self):
        over = RP._MAX_ID_PARAMS + 1
        code, body = self._call(
            RP._serve_team_damage_mix,
            "/api/champ-select/team-damage-mix?team_ids=" + self._ids(over))
        self.assertEqual(code, 400)
        self.assertIn("team_ids", body["error"])

    def test_queue_param_is_capped_too(self):
        """?queue= builds one ``?`` placeholder per id in EVERY query the
        route runs. Uncapped it walks into SQLite's variable ceiling and
        returns a 500 instead of naming the bad input."""
        over = RP._MAX_ID_PARAMS + 1
        code, body = self._call(
            RP._serve_pickban_recs,
            "/api/champ-select/pickban-recs?role=BOT&queue=" + self._ids(over))
        self.assertEqual(code, 400)
        self.assertIn("queue", body["error"])

    def test_rejection_leaks_no_internals(self):
        """CLAUDE.md error rule: the 400 names the param and the limit,
        and carries no path, no traceback, no SQL."""
        over = RP._MAX_ID_PARAMS + 1
        _code, body = self._call(
            RP._serve_personal_record,
            "/api/champ-select/personal-record?allies=" + self._ids(over))
        err = body["error"]
        self.assertIn(str(RP._MAX_ID_PARAMS), err)
        for leak in ("Traceback", "sqlite3", "SELECT", "rewind_history",
                     "C:\\", "/api/"):
            self.assertNotIn(leak, err)


class RealDraftSizedListsStillWork(_PickbanCapBase):
    """The cap must not break a legitimate draft. Guards over-tightening -
    the failure mode where a security fix silently disables the feature."""

    def test_full_5v5_draft_is_served(self):
        code, body = self._call(
            RP._serve_personal_record,
            "/api/champ-select/personal-record?champ=22&role=BOT"
            "&allies=12,64,103,84&enemies=1,2,3,4,5")
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["with_allies"]), 4)
        self.assertEqual(len(body["vs_enemies"]), 5)

    def test_exactly_at_the_cap_is_served(self):
        """Boundary: _MAX_ID_PARAMS itself is accepted, cap+1 is not."""
        code, body = self._call(
            RP._serve_personal_record,
            "/api/champ-select/personal-record?enemies="
            + self._ids(RP._MAX_ID_PARAMS))
        self.assertEqual(code, 200)
        self.assertEqual(len(body["vs_enemies"]), RP._MAX_ID_PARAMS)

    def test_cap_covers_the_largest_real_lobby(self):
        """10 picks + 10 bans (SR) and 16 players (Arena) must both fit."""
        self.assertGreaterEqual(RP._MAX_ID_PARAMS, 20)

    def test_cap_bounds_the_measured_worst_case(self):
        """The OTHER side of the bound, and the one the rest of this file
        cannot supply: every test above derives its oversized input from
        ``_MAX_ID_PARAMS`` itself, so they all stay green if the cap is
        raised back to a million. Mutation-tested 2026-08-31 - that mutant
        (M1) survived the other seven rejection tests, which is why this
        one exists.

        personal-record runs up to 2 queries per id, at a MEASURED 13.5 ms
        each against the live 1.87 GB rewind_history.db. Hold one request's
        worst case inside 2 s - past that the draft-time panel has missed
        its window anyway, so a larger cap buys nothing and re-opens the
        amplifier."""
        measured_ms_per_query = 13.5
        queries_per_id = 2
        budget_ms = 2000.0
        worst_ms = RP._MAX_ID_PARAMS * queries_per_id * measured_ms_per_query
        self.assertLessEqual(
            worst_ms, budget_ms,
            f"_MAX_ID_PARAMS={RP._MAX_ID_PARAMS} admits {worst_ms:.0f} ms of "
            f"query time per request; budget is {budget_ms:.0f} ms")


class FanOutIsBounded(_PickbanCapBase):
    """The MECHANISM test. The 400 above is the symptom; this pins the
    thing that actually costs the CPU - the per-id SQL fan-out."""

    def test_served_request_runs_at_most_two_queries_per_capped_id(self):
        calls = []
        real = RP._query_co_participant

        def counting(*a, **kw):
            calls.append(1)
            return real(*a, **kw)

        with mock.patch.object(RP, "_query_co_participant", counting):
            code, _body = self._call(
                RP._serve_personal_record,
                "/api/champ-select/personal-record"
                "?allies=" + self._ids(RP._MAX_ID_PARAMS)
                + "&enemies=" + self._ids(RP._MAX_ID_PARAMS))
        self.assertEqual(code, 200)
        self.assertLessEqual(len(calls), 2 * RP._MAX_ID_PARAMS)

    def test_rejected_request_runs_zero_queries(self):
        """A rejected request must not touch the DB at all - the guard
        has to fire BEFORE the connection is opened, or the cap buys
        nothing on the expensive path."""
        over = RP._MAX_ID_PARAMS + 1
        with mock.patch.object(RP, "_open_ro_with_puuid") as opener:
            code, _body = self._call(
                RP._serve_personal_record,
                "/api/champ-select/personal-record?allies=" + self._ids(over))
        self.assertEqual(code, 400)
        opener.assert_not_called()


class ConnectionIsClosedOnEveryPath(_PickbanCapBase):
    """Resource lifetime. `_open_ro_with_puuid` connects and THEN resolves
    the puuid; the caller's try/finally only begins once the function
    returns, so a raise from the resolve left the connection with no
    deterministic close - on exactly the path that means the db is sick
    (corrupt file -> DatabaseError, missing table -> OperationalError)."""

    def test_connection_closed_when_puuid_resolution_raises(self):
        fake_conn = mock.MagicMock()
        with mock.patch.object(RP.sqlite3, "connect", return_value=fake_conn), \
             mock.patch.object(RP, "_resolve_operator_puuid",
                               side_effect=sqlite3.DatabaseError("malformed")):
            with self.assertRaises(sqlite3.DatabaseError):
                RP._open_ro_with_puuid(mock.MagicMock())
        fake_conn.close.assert_called_once()

    def test_connection_closed_when_no_operator_puuid(self):
        """The pre-existing 503 path stays closed too - characterization,
        so a future edit cannot regress it while fixing the raise path."""
        fake_conn = mock.MagicMock()
        h = mock.MagicMock()
        with mock.patch.object(RP.sqlite3, "connect", return_value=fake_conn), \
             mock.patch.object(RP, "_resolve_operator_puuid", return_value=None):
            conn, puuid = RP._open_ro_with_puuid(h)
        self.assertIsNone(conn)
        self.assertIsNone(puuid)
        fake_conn.close.assert_called_once()
        self.assertEqual(h._send.call_args[0][0], 503)


if __name__ == "__main__":
    unittest.main()
