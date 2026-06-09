"""Regression: rewind_history.db ingestion went stale after an account switch.

REPLAY1 (2026-06-08). Operator report: "match ingestion is not up to date
after each game" - the Replay / rewind surface stopped updating (newest row
2026-05-23) even though the operator kept playing.

Root cause: ``resolve_current_puuid`` derived the operator's account from the
DB's MAJORITY puuid (``operator_riot_id_from_db`` -> the most-frequent puuid's
Riot ID -> Account-V1). When the operator switched Riot IDs, the DB stayed
dominated by the OLD account's ~2900 rows, so resolution kept re-locking onto
the old account and never discovered the new one (chicken-and-egg: the new
account has zero rows yet). The live writer reads the resulting stale puuid
from the state sentinel and only ever sees the old account's already-ingested
matches -> every live write is a no-op.

Fix: a persisted ``riot_id`` in the state sentinel (set by a ``--riot-id`` run)
is an authoritative, sticky override that beats the DB-majority fallback, so a
freshly-switched account is resolved correctly going forward.

Offline - Account-V1 + the DB are stubbed; no live Riot calls.
"""

from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import patch

from scripts import rewind_catchup as rc

# Account-V1 fixture: old account (Vayne) vs current account (Trist).
_ACCT = {
    ("SamplePlayer", "Vayne"): {"puuid": "PUUID_VAYNE_OLD"},
    ("SamplePlayer", "Trist"): {"puuid": "PUUID_TRIST_CURRENT"},
}


def _fake_account(name, tag, region="americas"):
    return _ACCT.get((name, tag))


def _db_dominated_by(name="SamplePlayer", tag="Vayne",
                     puuid="PUUID_VAYNE_OLD") -> sqlite3.Connection:
    """In-memory participants table whose MAJORITY rows are the old account -
    exactly the shape that made resolution self-reinforce on the old Riot ID."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE participants (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "puuid TEXT, riot_id_game_name TEXT, riot_id_tagline TEXT)"
    )
    for _ in range(5):
        conn.execute(
            "INSERT INTO participants (puuid, riot_id_game_name, riot_id_tagline) "
            "VALUES (?, ?, ?)", (puuid, name, tag))
    conn.commit()
    return conn


class ResolveCurrentPuuidPriorityTests(unittest.TestCase):
    def test_persisted_state_riot_id_beats_db_majority(self):
        """The core fix: a persisted current Riot ID resolves the NEW account
        even when the DB is still dominated by the old one."""
        conn = _db_dominated_by()
        with patch.object(rc.riot_api, "get_account_by_riot_id",
                          side_effect=_fake_account):
            puuid = rc.resolve_current_puuid(
                conn, state_riot_id="SamplePlayer#Trist")
        self.assertEqual(puuid, "PUUID_TRIST_CURRENT")

    def test_db_majority_used_when_no_persisted_riot_id(self):
        """Pre-fix behavior preserved when there is no persisted override:
        falls back to the DB-derived (old) account."""
        conn = _db_dominated_by()
        with patch.object(rc.riot_api, "get_account_by_riot_id",
                          side_effect=_fake_account):
            puuid = rc.resolve_current_puuid(conn)
        self.assertEqual(puuid, "PUUID_VAYNE_OLD")

    def test_explicit_riot_id_flag_beats_persisted_state(self):
        conn = _db_dominated_by()
        with patch.object(rc.riot_api, "get_account_by_riot_id",
                          side_effect=_fake_account):
            puuid = rc.resolve_current_puuid(
                conn, explicit_riot_id="SamplePlayer#Vayne",
                state_riot_id="SamplePlayer#Trist")
        self.assertEqual(puuid, "PUUID_VAYNE_OLD")

    def test_explicit_puuid_flag_beats_everything(self):
        conn = _db_dominated_by()
        puuid = rc.resolve_current_puuid(
            conn, explicit_puuid="PUUID_DIRECT",
            state_riot_id="SamplePlayer#Trist")
        self.assertEqual(puuid, "PUUID_DIRECT")

    def test_persisted_riot_id_falls_back_to_db_on_account_v1_miss(self):
        """If the persisted Riot ID can't be resolved (Account-V1 down /
        renamed again), degrade to the DB-derived account, never crash."""
        conn = _db_dominated_by()

        def _miss(name, tag, region="americas"):
            if (name, tag) == ("SamplePlayer", "Trist"):
                return None
            return _ACCT.get((name, tag))

        with patch.object(rc.riot_api, "get_account_by_riot_id",
                          side_effect=_miss):
            puuid = rc.resolve_current_puuid(
                conn, state_riot_id="SamplePlayer#Trist")
        self.assertEqual(puuid, "PUUID_VAYNE_OLD")

    def test_malformed_persisted_riot_id_is_ignored(self):
        conn = _db_dominated_by()
        with patch.object(rc.riot_api, "get_account_by_riot_id",
                          side_effect=_fake_account):
            puuid = rc.resolve_current_puuid(
                conn, state_riot_id="no-hash-here")
        self.assertEqual(puuid, "PUUID_VAYNE_OLD")


class AsciiHygieneTests(unittest.TestCase):
    def test_this_file_is_ascii_clean(self):
        from pathlib import Path
        data = Path(__file__).resolve().read_bytes()
        bad = [i for i, b in enumerate(data) if b > 127]
        self.assertEqual(bad, [], f"non-ASCII bytes at offsets {bad[:8]}")


if __name__ == "__main__":
    unittest.main()
