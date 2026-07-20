"""Fidelity oracle for the .rofl stats sidecar -> rewind_history.db backfill.

Six of the twelve archived sidecars correspond to matches ALREADY in
rewind_history.db via the Match-V5 path. Those six are the oracle: a
sidecar-derived participant row must agree with the Match-V5-derived row
already on disk before any net-new row is inserted.

The sidecar uses Riot's internal engine stat names (CHAMPIONS_KILLED,
NUM_DEATHS, GOLD_EARNED) which are NOT the Match-V5 camelCase names, so the
mapping is real work rather than a rename.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from core.rofl_stats_backfill import (
    COLUMN_ALIASES,
    TEXT_COLUMNS,
    backfill_participants,
    map_rofl_player,
    read_rofl_game_version,
)

SIDECAR_DIR = Path.home() / "Documents" / "RC_ROFL_Archive" / "stats"
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "rewind_history.db"

# Match ids present in BOTH the sidecar archive and the Match-V5-derived DB.
ORACLE_MATCH_IDS = [
    "NA1_5585328637",
    "NA1_5585379389",
    "NA1_5585413839",
    "NA1_5592802194",
    "NA1_5595187452",
    "NA1_5597809601",
]

# Every mapped column must agree exactly. The mapping is deliberately the set
# that was MEASURED to agree - summoner_id, time_played and puuid were probed,
# found to disagree, and excluded in core.rofl_stats_backfill rather than
# papered over here. See that module's docstring for why each was dropped.
ORACLE_COLUMNS = [*COLUMN_ALIASES, *TEXT_COLUMNS, "win"]

pytestmark = pytest.mark.skipif(
    not SIDECAR_DIR.is_dir() or not DB_PATH.is_file(),
    reason="rofl sidecar archive or rewind_history.db not present on this host",
)


def _db_rows(match_id):
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        cols = ", ".join(["participant_id", "champion_name", *ORACLE_COLUMNS])
        cur = conn.execute(
            f"SELECT {cols} FROM participants WHERE match_id = ?", (match_id,)
        )
        return {r["participant_id"]: dict(r) for r in cur.fetchall()}
    finally:
        conn.close()


def test_sidecar_puuid_is_not_the_match_v5_puuid():
    """The sidecar carries a RAW uuid; the DB carries the key-encrypted puuid.

    These are different namespaces, so participant_id (sidecar player order) is
    the join key, not puuid. Pinning this stops a future reader from "fixing"
    the join back onto puuid and silently matching zero rows.
    """
    match_id = ORACLE_MATCH_IDS[0]
    sidecar = json.loads((SIDECAR_DIR / f"{match_id}.json").read_text())
    sidecar_ids = {map_rofl_player(p, i)["rofl_uuid"] for i, p in enumerate(sidecar["players"])}
    db_ids = {r["puuid"] for r in _db_rows(match_id).values() if r.get("puuid")}
    assert not (sidecar_ids & db_ids), "sidecar and Match-V5 puuid namespaces overlap"


@pytest.mark.parametrize("match_id", ORACLE_MATCH_IDS)
def test_sidecar_player_matches_match_v5_row(match_id):
    """A sidecar-derived row agrees with the Match-V5 row already in the DB."""
    sidecar = json.loads((SIDECAR_DIR / f"{match_id}.json").read_text())
    expected_by_pid = _db_rows(match_id)
    assert expected_by_pid, f"no participants rows in DB for {match_id}"

    compared = 0
    for index, player in enumerate(sidecar["players"]):
        mapped = map_rofl_player(player, index)
        expected = expected_by_pid.get(mapped["participant_id"])
        assert expected is not None, (
            f"{match_id}: no DB row for participant_id={mapped['participant_id']}"
        )
        # Champion agreement proves the positional join is sound, not luck.
        assert mapped["champion_name"] == expected["champion_name"], (
            f"{match_id} pid={mapped['participant_id']}: champion mismatch "
            f"sidecar={mapped['champion_name']!r} match_v5={expected['champion_name']!r}"
        )
        compared += 1
        for col in ORACLE_COLUMNS:
            assert mapped[col] == expected[col], (
                f"{match_id} pid={mapped['participant_id']} column={col}: "
                f"sidecar={mapped[col]!r} match_v5={expected[col]!r}"
            )

    assert compared == len(expected_by_pid), (
        f"{match_id}: matched {compared} of {len(expected_by_pid)} DB rows"
    )


# --- backfill: net-new inserts -------------------------------------------

ARCHIVE_DIR = SIDECAR_DIR.parent

# Sidecars whose matches are NOT in the DB. The three sub-300s entries are
# remakes and are excluded by the duration floor, not by name.
NEW_MATCH_IDS = ["NA1_5600233527", "NA1_5600354102", "NA1_5604806601"]
REMAKE_MATCH_IDS = ["NA1_5604206384", "NA1_5604206514", "NA1_5604715394"]


def _schema_sql():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name IN ('matches','participants') "
            "AND sql IS NOT NULL"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


@pytest.fixture
def champion_ids():
    """Champion name -> id, read from production read-only."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        return dict(
            conn.execute(
                "SELECT DISTINCT champion_name, champion_id FROM participants "
                "WHERE champion_name IS NOT NULL AND champion_id IS NOT NULL"
            ).fetchall()
        )
    finally:
        conn.close()


@pytest.fixture
def empty_db(tmp_path):
    """A hermetic DB carrying the production schema and no rows."""
    path = tmp_path / "rewind_test.db"
    conn = sqlite3.connect(path)
    try:
        for stmt in _schema_sql():
            conn.execute(stmt)
        conn.commit()
    finally:
        conn.close()
    return path


def test_read_rofl_game_version_reads_the_header():
    """Game version IS carried in the .rofl header, unlike queue and mode."""
    version = read_rofl_game_version(ARCHIVE_DIR / "NA1-5604806601.rofl")
    assert version == "16.14.794.5912"


@pytest.mark.parametrize("match_id", ORACLE_MATCH_IDS)
def test_rofl_header_version_matches_match_v5(match_id):
    """The header parse is oracle-checked, same as the stat mapping.

    Replay Tool Z16 shows a patch per replay and this is where it comes from. Note
    what is NOT here: queue_id and game_mode. Replay Tool Z16's map label is an
    INFERENCE over player stats (GameDetailsInferrer.InferMap: no jungle creeps
    means Howling Abyss), not a field the file carries - and a map cannot
    distinguish ARAM from ARAM Mayhem anyway.
    """
    candidates = [
        ARCHIVE_DIR / f"{match_id}.rofl",
        ARCHIVE_DIR / f"{match_id.replace('_', '-')}.rofl",
    ]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        pytest.skip(f"no .rofl archived for {match_id}")

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        expected = conn.execute(
            "SELECT game_version FROM matches WHERE match_id = ?", (match_id,)
        ).fetchone()[0]
    finally:
        conn.close()

    assert read_rofl_game_version(path) == expected


def test_backfill_skips_remakes_below_the_duration_floor(empty_db, champion_ids):
    paths = [SIDECAR_DIR / f"{m}.json" for m in REMAKE_MATCH_IDS]
    report = backfill_participants(empty_db, paths, min_duration_s=300, champion_ids=champion_ids)

    assert report["inserted_matches"] == 0
    assert report["inserted_participants"] == 0
    assert sorted(report["skipped_short"]) == sorted(REMAKE_MATCH_IDS)


def test_backfill_inserts_net_new_participants(empty_db, champion_ids):
    paths = [SIDECAR_DIR / f"{m}.json" for m in NEW_MATCH_IDS]
    report = backfill_participants(empty_db, paths, min_duration_s=300, champion_ids=champion_ids)

    assert report["inserted_matches"] == 3
    assert report["inserted_participants"] == 30

    conn = sqlite3.connect(empty_db)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM participants WHERE match_id = ? ORDER BY participant_id",
            ("NA1_5604806601",),
        ).fetchall()
        assert len(rows) == 10
        assert [r["participant_id"] for r in rows] == list(range(1, 11))
        # Champion ids resolve from the DB's own name mapping, never invented.
        assert all(r["champion_id"] for r in rows)
        # No orphans: every participant has its matches row.
        orphans = conn.execute(
            "SELECT COUNT(*) FROM participants p "
            "LEFT JOIN matches m ON m.match_id = p.match_id WHERE m.match_id IS NULL"
        ).fetchone()[0]
        assert orphans == 0
        # Mode columns stay NULL - the sidecar cannot prove a queue.
        match = conn.execute(
            "SELECT queue_id, game_mode, game_version, patch, game_duration_s "
            "FROM matches WHERE match_id = ?",
            ("NA1_5600233527",),
        ).fetchone()
        assert match["queue_id"] is None
        assert match["game_mode"] is None
        assert match["game_version"] == "16.13.791.5903"
        assert match["patch"] == "16.13"
        # Replay-derived length. Match-V5's gameDuration can differ by ~1s, so
        # this is the sidecar's own measurement and is NOT oracle-matched.
        assert match["game_duration_s"] == 1250
    finally:
        conn.close()


def test_backfill_is_idempotent(empty_db, champion_ids):
    paths = [SIDECAR_DIR / f"{m}.json" for m in NEW_MATCH_IDS]
    backfill_participants(empty_db, paths, min_duration_s=300, champion_ids=champion_ids)
    report = backfill_participants(empty_db, paths, min_duration_s=300, champion_ids=champion_ids)

    assert report["inserted_matches"] == 0
    assert report["inserted_participants"] == 0
    assert sorted(report["skipped_present"]) == sorted(NEW_MATCH_IDS)


def test_backfill_dry_run_writes_nothing(empty_db, champion_ids):
    paths = [SIDECAR_DIR / f"{m}.json" for m in NEW_MATCH_IDS]
    report = backfill_participants(empty_db, paths, min_duration_s=300, dry_run=True, champion_ids=champion_ids)

    assert report["inserted_participants"] == 30
    conn = sqlite3.connect(empty_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM participants").fetchone()[0] == 0
    finally:
        conn.close()
