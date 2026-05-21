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

Closest approximation from rewind_history.db ``participants`` columns:

    numerator   = dragon_kills
                + baron_kills
                + objectives_stolen
                + objectives_stolen_assists
                + first_tower_kill
                + first_tower_assist
    denominator = sum of those same columns across all 5 teammates
                  (matched by participants.team_id)

Edge case: if the team total is 0 (no objectives taken whole match),
return 0.0. The rubric correctly scores that as zero contribution to a
zero-base game; we do NOT pretend the operator got "100% of nothing".

Fail-soft contract: missing match_id, blank puuid, malformed schema, or
any sqlite error returns 0.0. Never raises.
"""
from __future__ import annotations

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


def _coerce_float(value) -> float:
    """Best-effort float coercion. Returns 0.0 on any failure."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def compute_obj_participation(
    conn: sqlite3.Connection,
    match_id: str,
    puuid: str,
) -> float:
    """Compute objective participation for the operator's row in ``match_id``.

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
    """
    if not match_id or not puuid:
        return 0.0
    if not isinstance(match_id, str) or not isinstance(puuid, str):
        return 0.0

    try:
        # Fetch operator row's team_id + per-row obj sum.
        operator_sql = (
            f"SELECT team_id, ({_ROW_SUM_SQL}) AS row_sum "
            "FROM participants "
            "WHERE match_id = ? AND puuid = ? LIMIT 1"
        )
        cur = conn.execute(operator_sql, (match_id, puuid))
        op_row = cur.fetchone()
        if op_row is None:
            return 0.0
        team_id = op_row[0]
        numerator = _coerce_float(op_row[1])
        if team_id is None:
            return 0.0

        # Team-wide total (all participants on the same team_id).
        team_sql = (
            f"SELECT COALESCE(SUM({_ROW_SUM_SQL}), 0) "
            "FROM participants "
            "WHERE match_id = ? AND team_id = ?"
        )
        cur = conn.execute(team_sql, (match_id, team_id))
        team_row = cur.fetchone()
        denominator = _coerce_float(team_row[0]) if team_row else 0.0
    except sqlite3.Error:
        return 0.0

    if denominator <= 0:
        return 0.0
    ratio = numerator / denominator
    if ratio < 0.0:
        return 0.0
    if ratio > 1.0:
        return 1.0
    return ratio
