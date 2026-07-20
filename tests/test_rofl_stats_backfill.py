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

from core.rofl_stats_backfill import map_rofl_player

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

# Columns the sidecar and Match-V5 must agree on exactly. Deliberately the
# core combat/economy set - not the mission/battle-pass counters, which the
# Match-V5 path never carried.
ORACLE_COLUMNS = [
    "kills",
    "deaths",
    "assists",
    "champ_level",
    "gold_earned",
    "gold_spent",
    "total_minions_killed",
    "total_damage_dealt_to_champs",
    "total_damage_taken",
    "vision_score",
    "item0",
    "item1",
    "item2",
    "item3",
    "item4",
    "item5",
    "item6",
    "team_id",
    "win",
]

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
