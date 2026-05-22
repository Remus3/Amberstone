"""Compute operator objective-participation from rewind_history.db participants.

The post_game_rubric (core/post_game_rubric.py) weights an
``obj_participation_pct`` axis per role:

    ADC 0.50, SUP 0.10, JG 0.70, MID 0.30, TOP 0.25

Until this module shipped, both live consumers
(``dashboard/routes_post_game_rubric.py`` and
``scripts/postmortem_analyze.py``) passed 0.0 always, so the operator
under-scored that axis by ~5-10 points on participation-heavy roles.

Standard League definition of "objective participation":
    (operator's involvement in team objectives) / (team total objectives).

Closest approximation from rewind_history.db ``participants`` columns
(8-column model; item 134 carry (g) lifts from the prior 7-column
approximation by reading ``voidMonsterKill`` (Voidgrubs) from
``participants.challenges_json`` alongside the already-wired
``riftHeraldTakedowns``):

    numerator   = dragon_kills
                + baron_kills
                + objectives_stolen
                + objectives_stolen_assists
                + first_tower_kill
                + first_tower_assist
                + riftHeraldTakedowns       # from challenges_json
                + voidMonsterKill           # from challenges_json (Voidgrubs)
    denominator = sum of those same 8 columns across all 5 teammates
                  (matched by participants.team_id)

Edge case: if the team total is 0 (no objectives taken whole match),
return 0.0. The rubric correctly scores that as zero contribution to a
zero-base game; we do NOT pretend the operator got "100% of nothing".

Fail-soft contract: missing match_id, blank puuid, malformed schema,
malformed challenges_json (non-JSON / missing key / non-numeric), or
any sqlite error returns 0.0. Never raises.
"""
from __future__ import annotations

import json
import sqlite3

# Columns summed to form numerator + denominator. Order is load-bearing
# in the SQL templates below - keep in sync.
_OBJ_COLUMNS = (
    "dragon_kills",
    "baron_kills",
    "objectives_stolen",
    "objectives_stolen_assists",
    "first_tower_kill",
    "first_tower_assist",
)

# SQL fragment that sums all _OBJ_COLUMNS for a single row. Coalesces
# NULL columns to 0 so partially-populated rows (event modes, older
# schema) still produce a sane numeric.
_ROW_SUM_SQL = " + ".join(f"COALESCE({c}, 0)" for c in _OBJ_COLUMNS)

# The 7th + 8th objective contributions live inside the participants
# ``challenges_json`` blob (Match-V5 challenges). Older schemas may not
# carry this column; the SELECT widening below uses a try/except SQL
# error path so the fail-soft contract still holds.
_HERALD_KEY = "riftHeraldTakedowns"
_VOID_KEY = "voidMonsterKill"


def _coerce_float(value) -> float:
    """Best-effort float coercion. Returns 0.0 on any failure."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _challenges_objectives(blob) -> tuple[float, float]:
    """Extract (riftHeraldTakedowns, voidMonsterKill) from one challenges_json
    blob in a SINGLE parse trip.

    Returning a tuple from one parse avoids double-parsing the blob (a
    sibling _void_from_challenges helper would re-call json.loads per
    row). Fail-soft on every degenerate shape: None, empty string,
    non-string, malformed JSON, non-dict parse result, missing key,
    non-numeric value. Each missing/bad value contributes 0.0 to its
    slot independently.
    """
    if not blob:
        return (0.0, 0.0)
    if not isinstance(blob, (str, bytes, bytearray)):
        return (0.0, 0.0)
    try:
        parsed = json.loads(blob)
    except (ValueError, TypeError):
        return (0.0, 0.0)
    if not isinstance(parsed, dict):
        return (0.0, 0.0)
    return (
        _coerce_float(parsed.get(_HERALD_KEY)),
        _coerce_float(parsed.get(_VOID_KEY)),
    )


def _herald_from_challenges(blob) -> float:
    """Extract ``riftHeraldTakedowns`` from a challenges_json blob.

    Kept as a thin wrapper around ``_challenges_objectives`` for backward
    compatibility with any external caller; new code in this module
    should prefer the tuple-returning helper to avoid double-parsing.
    """
    herald, _void = _challenges_objectives(blob)
    return herald


def _void_from_challenges(blob) -> float:
    """Extract ``voidMonsterKill`` (Voidgrubs) from a challenges_json blob.

    Companion to ``_herald_from_challenges``. Same fail-soft contract.
    """
    _herald, void = _challenges_objectives(blob)
    return void


def compute_obj_participation(
    conn: sqlite3.Connection,
    match_id: str,
    puuid: str,
) -> float:
    """Compute objective participation for the operator's row in ``match_id``.

    8-column model (item 134 carry (g)): the original 6 SQL columns plus
    ``riftHeraldTakedowns`` AND ``voidMonsterKill`` (Voidgrubs) parsed
    from ``participants.challenges_json``. Both blob counters are added
    to BOTH numerator (operator's own row) and denominator (team-wide
    sum) so the ratio stays normalized.

    Args:
        conn: open sqlite3 connection (caller owns lifecycle; we never
            close it). May be read-only (URI ``mode=ro``).
        match_id: Match-V5 match id (e.g. ``NA1_1234567890``).
        puuid: operator's PUUID for the participant row.

    Returns:
        A float in ``[0.0, 1.0]``. Returns 0.0 on any of:
          - blank match_id or puuid
          - no matching participants row
          - team total is 0 (rubric correctly under-scores a no-objectives game)
          - any sqlite error or unexpected schema shape
          - malformed challenges_json (handled per-row; the SQL trip
            still succeeds and other rows contribute normally)
    """
    if not match_id or not puuid:
        return 0.0
    if not isinstance(match_id, str) or not isinstance(puuid, str):
        return 0.0

    try:
        # Fetch the operator row's team_id in one trip (separate from the
        # team-wide pull so we can short-circuit on unknown puuid before
        # paying for the WHERE team_id scan).
        cur = conn.execute(
            "SELECT team_id FROM participants "
            "WHERE match_id = ? AND puuid = ? LIMIT 1",
            (match_id, puuid),
        )
        op_row = cur.fetchone()
        if op_row is None:
            return 0.0
        team_id = op_row[0]
        if team_id is None:
            return 0.0

        # Pull every team row's 6-col sum AND the puuid + challenges_json
        # so we can tally herald + voidgrubs in Python and identify the
        # operator row without a second query. Try the widened SELECT
        # first (modern schema). On OperationalError (legacy schema
        # without challenges_json), fall back to the 6-column SELECT.
        try:
            team_sql = (
                f"SELECT puuid, ({_ROW_SUM_SQL}) AS row_sum, challenges_json "
                "FROM participants "
                "WHERE match_id = ? AND team_id = ?"
            )
            cur = conn.execute(team_sql, (match_id, team_id))
            rows = cur.fetchall()
            has_challenges = True
        except sqlite3.OperationalError:
            # Legacy schema (no challenges_json column). Degrade to the
            # 6-column model; the test
            # FailSoftWithMissingObjColumnsTests::test_legacy_schema_without_obj_cols_falls_back_to_zero
            # pins this contract through to the route layer.
            team_sql = (
                f"SELECT puuid, ({_ROW_SUM_SQL}) AS row_sum "
                "FROM participants "
                "WHERE match_id = ? AND team_id = ?"
            )
            cur = conn.execute(team_sql, (match_id, team_id))
            rows = cur.fetchall()
            has_challenges = False
    except sqlite3.Error:
        return 0.0

    numerator = 0.0
    denominator = 0.0
    for row in rows:
        row_puuid = row[0]
        row_sum6 = _coerce_float(row[1])
        # Parse challenges_json ONCE per row and extract both herald +
        # voidgrubs in one trip. Order is (herald, void) but the sum
        # below is symmetric.
        if has_challenges:
            herald, void = _challenges_objectives(row[2])
        else:
            herald, void = (0.0, 0.0)
        row_total = row_sum6 + herald + void
        denominator += row_total
        if row_puuid == puuid:
            numerator = row_total

    if denominator <= 0:
        return 0.0
    ratio = numerator / denominator
    if ratio < 0.0:
        return 0.0
    if ratio > 1.0:
        return 1.0
    return ratio
