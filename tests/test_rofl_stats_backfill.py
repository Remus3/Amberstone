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
import os
import sqlite3
from pathlib import Path

import pytest

from core.rofl_stats_backfill import (
    COLUMN_ALIASES,
    TEXT_COLUMNS,
    backfill_participants,
    backfill_tracked_summary,
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

# Lane 8 cycle 45: this gate was a MODULE-level pytestmark, so it skipped all
# 25 tests this file then collected, wherever the live archive is absent -
# which is every worktree (the
# DB is gitignored and DB_PATH resolves under the tree root) and CI. Seven of
# the backfill tests build their own DB via _hermetic_db and need neither
# artifact, so they were being skipped for no reason and had never run in CI.
# The gate now names only the tests that genuinely read production.
requires_live_archive = pytest.mark.skipif(
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


@requires_live_archive
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


@requires_live_archive
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


@requires_live_archive
def test_read_rofl_game_version_reads_the_header():
    """Game version IS carried in the .rofl header, unlike queue and mode."""
    version = read_rofl_game_version(ARCHIVE_DIR / "NA1-5604806601.rofl")
    assert version == "16.14.794.5912"


@requires_live_archive
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


@requires_live_archive
def test_backfill_skips_remakes_below_the_duration_floor(empty_db, champion_ids):
    paths = [SIDECAR_DIR / f"{m}.json" for m in REMAKE_MATCH_IDS]
    report = backfill_participants(empty_db, paths, min_duration_s=300, champion_ids=champion_ids)

    assert report["inserted_matches"] == 0
    assert report["inserted_participants"] == 0
    assert sorted(report["skipped_short"]) == sorted(REMAKE_MATCH_IDS)


@requires_live_archive
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


@requires_live_archive
def test_backfill_is_idempotent(empty_db, champion_ids):
    paths = [SIDECAR_DIR / f"{m}.json" for m in NEW_MATCH_IDS]
    backfill_participants(empty_db, paths, min_duration_s=300, champion_ids=champion_ids)
    report = backfill_participants(empty_db, paths, min_duration_s=300, champion_ids=champion_ids)

    assert report["inserted_matches"] == 0
    assert report["inserted_participants"] == 0
    assert sorted(report["skipped_present"]) == sorted(NEW_MATCH_IDS)


@requires_live_archive
def test_backfill_dry_run_writes_nothing(empty_db, champion_ids):
    paths = [SIDECAR_DIR / f"{m}.json" for m in NEW_MATCH_IDS]
    report = backfill_participants(empty_db, paths, min_duration_s=300, dry_run=True, champion_ids=champion_ids)

    assert report["inserted_participants"] == 30
    conn = sqlite3.connect(empty_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM participants").fetchone()[0] == 0
    finally:
        conn.close()


# --- tracked-summary backfill (hermetic; no production DB or sidecar dir) ----
#
# The rows this recovers are NOT missing - they exist in matches with tracked_*
# NULL (queue_id/game_mode already correct from Match-V5). NULL champion renders
# "Unknown", NULL kda renders "0-0-0". The fix is an UPDATE of tracked_* on the
# existing row, joined file->row by match_id and player->operator by RIOT ID
# (never the sidecar's raw PUUID). These tests build their own schema + sidecars
# so they run with zero dependency on the archived data on disk.

OPERATOR = ("SamplePlayer", "Vayne")

# Champion name -> Riot id, passed explicitly so resolution is deterministic and
# never learned from a (possibly empty) participants table.
CHAMP_IDS = {
    "Vayne": 67, "Lux": 99, "Ashe": 22, "Thresh": 412, "Garen": 86,
    "Ahri": 103, "Jinx": 222, "Leona": 89, "Darius": 122, "Sona": 37,
}


def _oplayer(name, tag, champ, team, k, d, a, win, puuid="raw-uuid"):
    """One sidecar player entry in engine-key shape."""
    return {
        "RIOT_ID_GAME_NAME": name,
        "RIOT_ID_TAG_LINE": tag,
        "SKIN": champ,
        "TEAM": team,
        "CHAMPIONS_KILLED": k,
        "NUM_DEATHS": d,
        "ASSISTS": a,
        "WIN": "Win" if win else "Fail",
        "PUUID": puuid,
    }


def _lobby_with_operator():
    """Ten players; the operator sits at index 3, not index 0."""
    names = [
        ("decoyA", "NA1", "Lux"), ("decoyB", "NA1", "Ashe"),
        ("decoyC", "NA1", "Thresh"), (OPERATOR[0], OPERATOR[1], "Vayne"),
        ("decoyD", "NA1", "Garen"), ("decoyE", "NA1", "Ahri"),
        ("decoyF", "NA1", "Jinx"), ("decoyG", "NA1", "Leona"),
        ("decoyH", "NA1", "Darius"), ("decoyI", "NA1", "Sona"),
    ]
    players = []
    for i, (nm, tg, champ) in enumerate(names):
        team = 100 if i < 5 else 200
        if nm == OPERATOR[0] and tg == OPERATOR[1]:
            players.append(_oplayer(nm, tg, champ, team, 12, 3, 7, True))
        else:
            players.append(_oplayer(nm, tg, champ, team, i, i, i, i % 2 == 0))
    return players


def _lobby_without_operator():
    names = [f"stranger{i}" for i in range(10)]
    champs = list(CHAMP_IDS)
    return [
        _oplayer(names[i], "EUW", champs[i], 100 if i < 5 else 200, i, 1, i, i % 2 == 0)
        for i in range(10)
    ]


def _write_sidecar(stats_dir, match_id, players, game_length_ms=1250000):
    stats_dir.mkdir(parents=True, exist_ok=True)
    path = stats_dir / f"{match_id}.json"
    path.write_text(
        json.dumps(
            {"match_id": match_id, "game_length_ms": game_length_ms, "players": players}
        )
    )
    return path


_TEXT_PARTICIPANT_COLS = {
    "champion_name", "riot_id_game_name", "riot_id_tagline",
    "match_id", "puuid", "team_position", "individual_position",
    "champion_transform",
}


def _participant_columns():
    """Every column backfill_participants writes to participants."""
    cols = list(COLUMN_ALIASES) + list(TEXT_COLUMNS)
    cols += ["participant_id", "champion_name", "win", "champion_id", "match_id", "puuid"]
    return cols


def _hermetic_db(tmp_path):
    """A DB with matches (incl tracked_*) and a participants table wide enough
    for the full backfill_participants INSERT - no production schema needed."""
    path = tmp_path / "rewind_test.db"
    conn = sqlite3.connect(path)
    try:
        defs = [
            f"{c} {'TEXT' if c in _TEXT_PARTICIPANT_COLS else 'INTEGER'}"
            for c in _participant_columns()
        ]
        conn.execute("CREATE TABLE participants (" + ", ".join(defs) + ")")
        conn.execute(
            "CREATE TABLE matches ("
            "match_id TEXT PRIMARY KEY, queue_id INTEGER, game_mode TEXT, "
            "game_version TEXT, patch TEXT, game_duration_s INTEGER, "
            "has_stats INTEGER, has_timeline INTEGER, "
            "tracked_champion_id INTEGER, tracked_champion_name TEXT, "
            "tracked_team_id INTEGER, tracked_win INTEGER, "
            "tracked_kills INTEGER, tracked_deaths INTEGER, tracked_assists INTEGER)"
        )
        conn.commit()
    finally:
        conn.close()
    return path


def _seed_match(db, match_id, queue_id, game_mode, players=None):
    """Insert a matches row with tracked_* NULL, plus optional participants."""
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO matches (match_id, queue_id, game_mode, has_stats, has_timeline) "
            "VALUES (?, ?, ?, 1, 1)",
            (match_id, queue_id, game_mode),
        )
        for index, player in enumerate(players or []):
            row = map_rofl_player(player, index)
            row.pop("rofl_uuid", None)
            row["match_id"] = match_id
            row["champion_id"] = CHAMP_IDS.get(row["champion_name"])
            cols = ", ".join(row)
            marks = ", ".join("?" for _ in row)
            conn.execute(
                f"INSERT INTO participants ({cols}) VALUES ({marks})", list(row.values())
            )
        conn.commit()
    finally:
        conn.close()


def _match_row(db, match_id):
    conn = sqlite3.connect(db)
    try:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM matches WHERE match_id = ?", (match_id,)
        ).fetchone()
    finally:
        conn.close()


def test_backfill_recovers_null_tracked_summary(tmp_path):
    """The corrupted-row recovery: a q2400 row with tracked_* NULL is filled,
    and queue_id/game_mode are left exactly as Match-V5 wrote them."""
    db = _hermetic_db(tmp_path)
    players = _lobby_with_operator()
    _seed_match(db, "NA1_5604806601", 2400, "KIWI", players)
    sidecar = _write_sidecar(tmp_path / "stats", "NA1_5604806601", players)

    report = backfill_tracked_summary(
        db, [sidecar], operator_accounts=[OPERATOR], champion_ids=CHAMP_IDS
    )

    assert "NA1_5604806601" in report["updated"]
    row = _match_row(db, "NA1_5604806601")
    assert row["tracked_champion_name"] == "Vayne"
    assert row["tracked_champion_id"] == 67
    assert row["tracked_team_id"] == 100
    assert row["tracked_kills"] == 12
    assert row["tracked_deaths"] == 3
    assert row["tracked_assists"] == 7
    assert row["tracked_win"] == 1
    # Untouched: the queue the sidecar cannot prove.
    assert row["queue_id"] == 2400
    assert row["game_mode"] == "KIWI"


def test_tracked_player_selected_by_riot_id(tmp_path):
    """Selection is by Riot ID; scrambling every sidecar PUUID changes nothing.

    Pins the join so a future reader cannot "fix" it back onto puuid (raw here,
    key-encrypted in the DB) and silently pick the wrong - or zero - players.
    """
    db = _hermetic_db(tmp_path)
    players = _lobby_with_operator()
    for i, player in enumerate(players):
        player["PUUID"] = f"scrambled-{i}"
    _seed_match(db, "NA1_5600000001", 450, "ARAM", players)
    sidecar = _write_sidecar(tmp_path / "stats", "NA1_5600000001", players)

    report = backfill_tracked_summary(
        db, [sidecar], operator_accounts=[OPERATOR], champion_ids=CHAMP_IDS
    )

    assert "NA1_5600000001" in report["updated"]
    row = _match_row(db, "NA1_5600000001")
    # The operator (index 3, Vayne), never index 0 (Lux).
    assert row["tracked_champion_name"] == "Vayne"
    assert row["tracked_kills"] == 12


def test_backfill_skips_lobby_without_operator(tmp_path):
    """No operator in the lobby -> tracked_* stays NULL and is reported; the
    code never falls back to guessing index 0."""
    db = _hermetic_db(tmp_path)
    players = _lobby_without_operator()
    _seed_match(db, "NA1_5600000002", 420, "CLASSIC", players)
    sidecar = _write_sidecar(tmp_path / "stats", "NA1_5600000002", players)

    report = backfill_tracked_summary(
        db, [sidecar], operator_accounts=[OPERATOR], champion_ids=CHAMP_IDS
    )

    assert "NA1_5600000002" in report["skipped_no_operator"]
    assert report["updated"] == []
    row = _match_row(db, "NA1_5600000002")
    assert row["tracked_champion_name"] is None
    assert row["tracked_kills"] is None


def test_backfill_tracked_summary_is_idempotent(tmp_path):
    """A second pass over already-filled rows updates nothing."""
    db = _hermetic_db(tmp_path)
    players = _lobby_with_operator()
    _seed_match(db, "NA1_5600000003", 2400, "KIWI", players)
    sidecar = _write_sidecar(tmp_path / "stats", "NA1_5600000003", players)

    backfill_tracked_summary(
        db, [sidecar], operator_accounts=[OPERATOR], champion_ids=CHAMP_IDS
    )
    report = backfill_tracked_summary(
        db, [sidecar], operator_accounts=[OPERATOR], champion_ids=CHAMP_IDS
    )

    assert report["updated"] == []
    assert "NA1_5600000003" in report["skipped_already_filled"]


def test_net_new_insert_fills_tracked_summary(tmp_path):
    """The INSERT path also closes the hole: a net-new operator-present match
    gets tracked_* filled, while queue_id/game_mode stay NULL."""
    db = _hermetic_db(tmp_path)
    players = _lobby_with_operator()
    sidecar = _write_sidecar(tmp_path / "stats", "NA1_5600000004", players)

    report = backfill_participants(
        db, [sidecar], min_duration_s=300, champion_ids=CHAMP_IDS,
        operator_accounts=[OPERATOR],
    )

    assert report["inserted_matches"] == 1
    assert report["inserted_participants"] == 10
    row = _match_row(db, "NA1_5600000004")
    assert row["tracked_champion_name"] == "Vayne"
    assert row["tracked_champion_id"] == 67
    assert row["tracked_team_id"] == 100
    assert row["tracked_kills"] == 12
    assert row["tracked_deaths"] == 3
    assert row["tracked_assists"] == 7
    assert row["tracked_win"] == 1
    # No local artifact can prove a queue for a net-new row.
    assert row["queue_id"] is None
    assert row["game_mode"] is None


def test_backfill_tracked_summary_dry_run_writes_nothing(tmp_path):
    """dry_run reports the intended update but rolls the write back."""
    db = _hermetic_db(tmp_path)
    players = _lobby_with_operator()
    _seed_match(db, "NA1_5600000005", 2400, "KIWI", players)
    sidecar = _write_sidecar(tmp_path / "stats", "NA1_5600000005", players)

    report = backfill_tracked_summary(
        db, [sidecar], operator_accounts=[OPERATOR], champion_ids=CHAMP_IDS,
        dry_run=True,
    )

    assert "NA1_5600000005" in report["updated"]
    row = _match_row(db, "NA1_5600000005")
    assert row["tracked_champion_name"] is None


def test_backfill_sweeps_all_null_rows_regardless_of_queue(tmp_path):
    """The entry point recovers EVERY tracked-NULL row that has a sidecar with
    the operator, not just q2400 - the root cause spans 420/450/2400."""
    db = _hermetic_db(tmp_path)
    seeds = [
        ("NA1_5600000010", 420, "CLASSIC"),
        ("NA1_5600000011", 450, "ARAM"),
        ("NA1_5600000012", 2400, "KIWI"),
    ]
    sidecars = []
    for match_id, queue_id, game_mode in seeds:
        players = _lobby_with_operator()
        _seed_match(db, match_id, queue_id, game_mode, players)
        sidecars.append(_write_sidecar(tmp_path / "stats", match_id, players))

    report = backfill_tracked_summary(
        db, sidecars, operator_accounts=[OPERATOR], champion_ids=CHAMP_IDS
    )

    assert sorted(report["updated"]) == [m for m, _q, _g in seeds]
    for match_id, queue_id, _g in seeds:
        row = _match_row(db, match_id)
        assert row["tracked_champion_name"] == "Vayne"
        assert row["queue_id"] == queue_id


# ---------------------------------------------------------------------------
# Lane 8 cycle 45: malformed-input resilience.
#
# core/rofl_archive.py:655-665 already carries the fix for this exact class -
# one wrong-shape .rofl aborted the whole extract_archive loop (item-1176).
# The backfill half never got it, and is strictly worse: the loop body runs
# INSIDE an open transaction, so an abort at file N discards the N-1 updates
# that already succeeded. The live caller (tools/rofl_tracked_backfill.py:69)
# globs *.json, so one partially-written sidecar poisons every future run.
# ---------------------------------------------------------------------------


def _write_broken_sidecar(stats_dir, name, body):
    stats_dir.mkdir(parents=True, exist_ok=True)
    path = stats_dir / f"{name}.json"
    path.write_text(body, encoding="utf-8")
    return path


def test_one_malformed_sidecar_does_not_discard_the_whole_run(tmp_path):
    """A bad sidecar is skipped and reported; the good ones still commit.

    Regression: json.loads raised out of the per-file loop, past the pending
    UPDATE for NA1_1, and conn.close() in the finally block rolled it back.
    """
    db = _hermetic_db(tmp_path)
    players = _lobby_with_operator()
    _seed_match(db, "NA1_1", 2400, "KIWI", players)
    _seed_match(db, "NA1_2", 2400, "KIWI", players)
    good1 = _write_sidecar(tmp_path / "stats", "NA1_1", players)
    bad = _write_broken_sidecar(tmp_path / "stats", "NA1_bad", "{not valid json")
    good2 = _write_sidecar(tmp_path / "stats", "NA1_2", players)

    report = backfill_tracked_summary(
        db, [good1, bad, good2], operator_accounts=[OPERATOR], champion_ids=CHAMP_IDS
    )

    assert sorted(report["updated"]) == ["NA1_1", "NA1_2"]
    assert [Path(p).name for p, _ in report["failed"]] == ["NA1_bad.json"]
    # The commit actually landed - the pre-fix rollback left both of these None.
    for match_id in ("NA1_1", "NA1_2"):
        assert _match_row(db, match_id)["tracked_champion_name"] == "Vayne"


@pytest.mark.parametrize(
    "label, body",
    [
        ("not_json", "{not valid json"),
        ("missing_match_id", '{"players": [], "game_length_ms": 1250000}'),
        ("missing_players", '{"match_id": "NA1_9", "game_length_ms": 1250000}'),
        ("players_not_a_list", '{"match_id": "NA1_9", "players": 3, '
                               '"game_length_ms": 1250000}'),
    ],
)
def test_every_malformed_sidecar_shape_is_survived(tmp_path, label, body):
    """Wrong SHAPE is as common as wrong syntax and must not abort either."""
    db = _hermetic_db(tmp_path)
    players = _lobby_with_operator()
    _seed_match(db, "NA1_1", 2400, "KIWI", players)
    good = _write_sidecar(tmp_path / "stats", "NA1_1", players)
    bad = _write_broken_sidecar(tmp_path / "stats", f"bad_{label}", body)

    report = backfill_tracked_summary(
        db, [bad, good], operator_accounts=[OPERATOR], champion_ids=CHAMP_IDS
    )

    assert report["updated"] == ["NA1_1"]
    assert len(report["failed"]) == 1
    assert _match_row(db, "NA1_1")["tracked_champion_name"] == "Vayne"


def test_malformed_sidecar_does_not_abort_participant_inserts(tmp_path):
    """backfill_participants carries the same loop and needs the same guard."""
    db = _hermetic_db(tmp_path)
    players = _lobby_with_operator()
    bad = _write_broken_sidecar(tmp_path / "stats", "NA1_bad", "{not valid json")
    good = _write_sidecar(tmp_path / "stats", "NA1_7", players)

    report = backfill_participants(
        db, [bad, good], champion_ids=CHAMP_IDS, operator_accounts=[OPERATOR]
    )

    assert report["inserted_matches"] == 1
    assert report["inserted_participants"] == len(players)
    assert [Path(p).name for p, _ in report["failed"]] == ["NA1_bad.json"]


def test_sidecars_are_decoded_as_utf8_under_a_non_utf8_codepage(tmp_path):
    """A non-ASCII RIOT_ID_GAME_NAME must survive the read.

    read_text() with no encoding resolves to the locale codepage (cp1252 on
    this box) while the writer declares utf-8. This guard is DEFENCE IN
    DEPTH and the byte pattern below is one production cannot currently
    emit: core/rofl_archive.py:811 serializes at the default
    ensure_ascii=True, so real sidecars are pure ASCII (measured 0 non-ASCII
    bytes across all 17) and cp1252 decodes those identically. It bites the
    day that writer passes ensure_ascii=False, or a sidecar arrives from
    elsewhere. In-process the assertion is vacuous while this session
    carries PYTHONUTF8=1, so it runs in a subprocess with PYTHONUTF8=0.
    NOTE PYTHONUTF8 is NOT set machine-wide: it is absent from both the User
    and Machine registry and is only inherited by this process tree, so a
    process started outside it would not have it either.
    """
    import subprocess
    import sys

    repo = Path(__file__).resolve().parent.parent
    sidecar = tmp_path / "NA1_1.json"
    # Escaped, not literal: this repo is 7-bit ASCII in authored bytes.
    name = "\u30d7\u30ec\u30a4\u30e4\u30fc"  # katakana, 5 non-ASCII chars
    sidecar.write_bytes(
        json.dumps(
            {
                "match_id": "NA1_1",
                "game_length_ms": 1250000,
                "players": [{"RIOT_ID_GAME_NAME": name}],
            },
            ensure_ascii=False,
        ).encode("utf-8")
    )

    script = chr(10).join([
        "import sys",
        f"sys.path.insert(0, {str(repo)!r})",
        "from pathlib import Path",
        "from core.rofl_stats_backfill import _load_sidecar",
        f"d = _load_sidecar(Path({str(sidecar)!r}))",
        "print(d['players'][0]['RIOT_ID_GAME_NAME'])",
    ])

    env = dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="utf-8")
    done = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == name


def test_cli_reports_and_exits_nonzero_when_a_sidecar_is_unusable(
        tmp_path, capsys, monkeypatch):
    """The CLI must SAY a sidecar was dropped, not silently skip it.

    Trading a loud crash for a silent skip would be a worse bug than the one
    the guard fixes, and a zero exit is exactly the "Last Result: 0 means
    nothing happened" trap. So the skip is reported and the exit is 2, while
    the good sidecar in the same run still lands.
    """
    from core import rofl_stats_backfill
    from tools import rofl_tracked_backfill

    # The CLI resolves `operator_accounts` from the per-install identity config
    # at CALL time, so pin the fixture account - otherwise this asserts against
    # whatever accounts the machine running the suite is configured for.
    monkeypatch.setattr(rofl_stats_backfill, "DEFAULT_ACCOUNTS", [OPERATOR])

    db = _hermetic_db(tmp_path)
    players = _lobby_with_operator()
    _seed_match(db, "NA1_1", 2400, "KIWI", players)
    archive = tmp_path / "arch"
    _write_sidecar(archive / "stats", "NA1_1", players)
    (archive / "stats" / "BAD.json").write_text("{truncated", encoding="utf-8")

    code = rofl_tracked_backfill.main(
        ["--archive", str(archive), "--db", str(db), "--no-extract", "--commit"]
    )

    assert code == 2
    out = capsys.readouterr().out
    assert "failed=1" in out
    assert "BAD.json" in out
    # The good sidecar in the same sweep still committed.
    assert _match_row(db, "NA1_1")["tracked_champion_name"] == "Vayne"


def test_find_rofl_cannot_escape_the_archive_directory(tmp_path):
    """SECURITY: match_id comes from the sidecar and builds a filesystem path.

    Before containment, a match_id of "../ESCAPED" resolved OUTSIDE the
    archive and returned a container from anywhere on disk, whose header then
    became that match's game_version. Found by the cycle-45 adversarial pass,
    which refuted this dimension being marked N/A.
    """
    from core.rofl_stats_backfill import _find_rofl

    archive = tmp_path / "archive"
    (archive / "stats").mkdir(parents=True)
    outside = tmp_path / "ESCAPED.rofl"
    outside.write_bytes(b"RIOT" + bytes([0, 1]) + bytes(8) + bytes([4]) + b"1.2.")

    assert _find_rofl(archive, "../ESCAPED") is None
    # An absolute path must not be honoured either.
    assert _find_rofl(archive, str(tmp_path / "ESCAPED")) is None
    # The legitimate in-archive lookup still works, both separators.
    good = archive / "NA1_9.rofl"
    good.write_bytes(b"RIOT")
    assert _find_rofl(archive, "NA1_9") == good.resolve()
    dashed = archive / "NA1-8.rofl"
    dashed.write_bytes(b"RIOT")
    assert _find_rofl(archive, "NA1_8") == dashed.resolve()


def test_sidecar_keys_can_never_become_sql_column_names():
    """SECURITY: both INSERT/UPDATE statements are built with an f-string.

    They are safe only because every column name is derived from a
    module-level dict literal and never from sidecar data. That is a claim
    about provenance, so it is pinned rather than asserted: a player entry
    carrying a SQL fragment as a KEY must not contribute a column, and its
    strings must survive only as bound parameter VALUES.
    """
    evil_key = "x); DROP TABLE participants;--"
    row = map_rofl_player(
        {
            "RIOT_ID_GAME_NAME": evil_key,
            "SKIN": "a'--",
            evil_key: 1,
            "CHAMPIONS_KILLED": 5,
        },
        0,
    )
    allowed = set(COLUMN_ALIASES) | set(TEXT_COLUMNS) | {
        "participant_id", "champion_name", "rofl_uuid", "win",
    }
    assert [k for k in row if k not in allowed] == []
    # The fragment is still present - as data, which is the point.
    assert row["riot_id_game_name"] == evil_key


# --- .rofl container header, on bytes RC did not author ---------------------


def _write_header(tmp_path, name, payload):
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def test_truncated_rofl_header_raises_value_error(tmp_path):
    """A file ending mid-header raised a bare IndexError, not the documented
    ValueError, so callers guarding ValueError lost the whole run."""
    path = _write_header(tmp_path, "trunc.rofl", b"RIOT\x00\x01")
    with pytest.raises(ValueError):
        read_rofl_game_version(path)


def test_rofl_length_byte_cannot_smuggle_body_bytes_into_the_version(tmp_path):
    """The declared length is trusted blindly and the slice silently clips.

    A length byte of 40 against a 14-char version appended 26 bytes of the
    compressed body to the returned string, which is then stored verbatim in
    matches.game_version.
    """
    payload = b"RIOT\x00\x01" + b"\x00" * 8 + bytes([40]) + b"16.14.794.5912" + b"A" * 200
    path = _write_header(tmp_path, "liar.rofl", payload)
    with pytest.raises(ValueError):
        read_rofl_game_version(path)


def test_non_ascii_rofl_version_raises_a_plain_value_error(tmp_path):
    """Corrupt bytes in the version field raised UnicodeDecodeError.

    Asserting only pytest.raises(ValueError) here is VACUOUS -
    UnicodeDecodeError is itself a ValueError subclass, so that assertion
    passed against the UNFIXED code. The contract the fix establishes is a
    plain ValueError carrying the path, so pin the concrete type.
    """
    payload = b"RIOT\x00\x01" + b"\x00" * 8 + bytes([4]) + b"\xff\xfe\xfd\xfc"
    path = _write_header(tmp_path, "nonascii.rofl", payload)
    with pytest.raises(ValueError) as caught:
        read_rofl_game_version(path)
    assert type(caught.value) is ValueError
    assert not isinstance(caught.value, UnicodeDecodeError)
    assert "nonascii.rofl" in str(caught.value)


def test_rofl_version_truncated_mid_field_is_rejected_not_silently_short(tmp_path):
    """A file cut mid-version must fail, not return a shorter version.

    Found by mutation testing: deleting the len(raw) != length check left the
    whole suite green, because the alphabet check only catches a length byte
    that overruns into NON-version bytes. Here the file ends mid-field and
    every surviving byte is a legal version character, so the alphabet check
    passes and the slice silently returns "16.14.79" for a declared 14.
    """
    payload = b"RIOT" + bytes([0, 1]) + bytes(8) + bytes([14]) + b"16.14.79"
    path = _write_header(tmp_path, "cutshort.rofl", payload)
    with pytest.raises(ValueError) as caught:
        read_rofl_game_version(path)
    assert "only 8 bytes follow" in str(caught.value)


def test_well_formed_rofl_header_still_reads(tmp_path):
    """Characterization: the happy path is unchanged by the hardening."""
    payload = b"RIOT\x00\x01" + b"\x00" * 8 + bytes([14]) + b"16.14.794.5912" + b"A" * 60
    path = _write_header(tmp_path, "good.rofl", payload)
    assert read_rofl_game_version(path) == "16.14.794.5912"
