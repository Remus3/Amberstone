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
(9-column model; BACKLOG L14 option (c) adds the non-overlapping turret
count beyond the first_tower binary sentinels to the prior 8-column
model from item 135):

    numerator   = dragon_kills
                + baron_kills
                + objectives_stolen
                + objectives_stolen_assists
                + first_tower_kill
                + first_tower_assist
                + riftHeraldTakedowns          # from challenges_json
                + voidMonsterKill              # from challenges_json (Voidgrubs)
                + max(turretTakedowns          # from challenges_json
                      - first_tower_kill
                      - first_tower_assist, 0) # NON-OVERLAPPING towers 2-11 only
    denominator = sum of those same 9 columns across all 5 teammates
                  (matched by participants.team_id)

The ``turretTakedowns`` field counts all 11 turrets the operator
helped destroy on the enemy side (per Match-V5 "challenges" blob;
takedown = kill+assist within the proximity window). It OVERLAPS with
the SQL ``first_tower_kill`` and ``first_tower_assist`` sentinels for
the FIRST turret only (those columns are binary, not per-turret
counters). The ``max(..., 0)`` clamp subtracts the first-tower sentinels
to avoid double-counting it while still crediting towers 2-11.

The 3 other challenges_json fields (baronTakedowns, dragonTakedowns,
epicMonsterSteals) FULLY OVERLAP existing SQL columns (kills vs
takedowns is a semantic change to existing scores - deferred per
BACKLOG L14 option (a) until operator opts into a rebaseline).

Edge case: if the team total is 0 (no objectives taken whole match),
return 0.0. The rubric correctly scores that as zero contribution to a
zero-base game; we do NOT pretend the operator got "100% of nothing".

Fail-soft contract: missing match_id, blank puuid, malformed schema,
malformed challenges_json (non-JSON / missing key / non-numeric /
nested past the parser's recursion limit), an identifier sqlite cannot
bind (a lone surrogate), or any sqlite error returns 0.0. Never raises
for a sqlite3 connection.

Every single count is validated on its own before it is summed
(``_coerce_float``): a value that is non-finite (NaN / Infinity, which
``json.loads`` accepts, or an inf REAL in an SQL column), negative, a
boolean, or above ``_MAX_COUNT`` is corrupt data and counts as 0.0.
Summing first would let one bad column cancel a real one, a negative
teammate count shrink the team total and inflate the operator's share,
or a NaN return NaN (s144 true-audit, RM-1861..RM-1867). The result is
always a finite float in [0.0, 1.0].
"""
from __future__ import annotations

import json
import math
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
# schema) still produce a sane numeric. It documents the column model
# (core.precomputed_replay_narrative cites it); the query itself selects
# the columns ONE BY ONE (_ROW_COLS_SQL) so Python validates each count
# before summing - an in-SQL sum lets a corrupt -5 cancel a real 5.
_ROW_SUM_SQL = " + ".join(f"COALESCE({c}, 0)" for c in _OBJ_COLUMNS)
_ROW_COLS_SQL = ", ".join(f"COALESCE({c}, 0)" for c in _OBJ_COLUMNS)

# Index of the first_tower_kill / first_tower_assist sentinels inside
# _OBJ_COLUMNS (the turret-overlap clamp needs them separately).
_FTK_IDX = _OBJ_COLUMNS.index("first_tower_kill")
_FTA_IDX = _OBJ_COLUMNS.index("first_tower_assist")

# No per-participant objective count is anywhere near this (11 turrets,
# a handful of dragons / grubs / barons). A value above it is a corrupt
# row, and summing it would overflow the team total to inf and erase
# every real share.
_MAX_COUNT = 1_000_000.0

# The 7th + 8th + 9th objective contributions live inside the
# participants ``challenges_json`` blob (Match-V5 challenges). Older
# schemas may not carry this column; the SELECT widening below uses a
# try/except SQL error path so the fail-soft contract still holds.
_HERALD_KEY = "riftHeraldTakedowns"
_VOID_KEY = "voidMonsterKill"
_TURRET_KEY = "turretTakedowns"


def _coerce_float(value) -> float:
    """Coerce one objective COUNT to a float. Returns 0.0 on any failure.

    None, a bool (a JSON ``true`` is not one objective), an unparseable
    value, a non-finite value (NaN / +-inf), a negative value and a value
    above ``_MAX_COUNT`` are all corrupt counts and give 0.0.
    """
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(out) or out < 0.0 or out > _MAX_COUNT:
        return 0.0
    return out


def _challenges_objectives(blob) -> tuple[float, float, float]:
    """Extract (riftHeraldTakedowns, voidMonsterKill, turretTakedowns)
    from one challenges_json blob in a SINGLE parse trip.

    Returning a tuple from one parse avoids triple-parsing the blob
    (sibling per-key helpers would re-call json.loads per row).
    Fail-soft on every degenerate shape: None, empty string, non-string,
    malformed JSON, nesting past the parser's recursion limit, non-dict
    parse result, missing key, non-numeric / non-finite / negative /
    boolean value. Each missing/bad value contributes 0.0 to its slot
    independently.
    """
    if not isinstance(blob, (str, bytes, bytearray)) or not blob:
        return (0.0, 0.0, 0.0)
    try:
        parsed = json.loads(blob)
    except (ValueError, TypeError, RecursionError):
        return (0.0, 0.0, 0.0)
    if not isinstance(parsed, dict):
        return (0.0, 0.0, 0.0)
    return (
        _coerce_float(parsed.get(_HERALD_KEY)),
        _coerce_float(parsed.get(_VOID_KEY)),
        _coerce_float(parsed.get(_TURRET_KEY)),
    )


def _herald_from_challenges(blob) -> float:
    """Extract ``riftHeraldTakedowns`` from a challenges_json blob.

    Kept as a thin wrapper around ``_challenges_objectives`` for backward
    compatibility with any external caller; new code in this module
    should prefer the tuple-returning helper to avoid double-parsing.
    """
    herald, _void, _turret = _challenges_objectives(blob)
    return herald


def _void_from_challenges(blob) -> float:
    """Extract ``voidMonsterKill`` (Voidgrubs) from a challenges_json blob.

    Companion to ``_herald_from_challenges``. Same fail-soft contract.
    """
    _herald, void, _turret = _challenges_objectives(blob)
    return void


def _turret_from_challenges(blob) -> float:
    """Extract ``turretTakedowns`` from a challenges_json blob.

    Companion to ``_herald_from_challenges``. Same fail-soft contract.
    Note: the consumer pairs this with ``first_tower_kill`` +
    ``first_tower_assist`` SQL columns via ``max(turret - ft_k - ft_a,
    0)`` to avoid double-counting the first turret (the only one those
    two binary sentinels cover).
    """
    _herald, _void, turret = _challenges_objectives(blob)
    return turret


def compute_obj_participation(
    conn: sqlite3.Connection,
    match_id: str,
    puuid: str,
) -> float:
    """Compute objective participation for the operator's row in ``match_id``.

    9-column model (BACKLOG L14 option (c)): the original 6 SQL columns
    plus ``riftHeraldTakedowns`` AND ``voidMonsterKill`` (Voidgrubs)
    parsed from ``participants.challenges_json`` (item 135), PLUS the
    non-overlapping turret count beyond the first-tower sentinels
    (``max(turretTakedowns - first_tower_kill - first_tower_assist,
    0)``). The clamp avoids double-counting the first turret (the only
    one the SQL sentinels cover) while crediting towers 2-11.

    Args:
        conn: open sqlite3 connection (caller owns lifecycle; we never
            close it). May be read-only (URI ``mode=ro``).
        match_id: Match-V5 match id (e.g. ``NA1_1234567890``).
        puuid: operator's PUUID for the participant row.

    Returns:
        A finite float in ``[0.0, 1.0]``. Returns 0.0 on any of:
          - non-str or blank match_id or puuid, or one sqlite cannot
            bind (a lone surrogate)
          - no matching participants row
          - team total is 0 (rubric correctly under-scores a no-objectives game)
          - any sqlite error or unexpected schema shape
          - malformed challenges_json (handled per-row; the SQL trip
            still succeeds and other rows contribute normally)
        A single corrupt count (non-finite, negative, boolean, above
        ``_MAX_COUNT``) contributes 0.0 and the rest of the row and
        team still count.

    """
    # isinstance BEFORE truthiness: a non-str whose __bool__ raises (an
    # array-like) must fall soft too, not escape.
    if not isinstance(match_id, str) or not isinstance(puuid, str):
        return 0.0
    if not match_id or not puuid:
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

        # Pull every team row's 6 SQL columns ONE BY ONE (so each count is
        # validated before it is summed) + the puuid + challenges_json so
        # we can tally herald + voidgrubs + non-overlapping turrets in
        # Python and identify the operator row without a second query.
        # Try the widened SELECT first (modern schema). On
        # OperationalError (legacy schema without challenges_json), fall
        # back to the 6-column SELECT.
        try:
            team_sql = (
                f"SELECT puuid, {_ROW_COLS_SQL}, challenges_json "
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
                f"SELECT puuid, {_ROW_COLS_SQL} "
                "FROM participants "
                "WHERE match_id = ? AND team_id = ?"
            )
            cur = conn.execute(team_sql, (match_id, team_id))
            rows = cur.fetchall()
            has_challenges = False
    except sqlite3.Error:
        return 0.0
    except UnicodeEncodeError:
        # A str identifier holding a lone surrogate cannot be bound as
        # UTF-8; no row can match it.
        return 0.0

    ncols = len(_OBJ_COLUMNS)
    numerator = 0.0
    denominator = 0.0
    for row in rows:
        row_puuid = row[0]
        counts = [_coerce_float(v) for v in row[1:1 + ncols]]
        row_sum6 = sum(counts)
        # Parse challenges_json ONCE per row and extract herald +
        # voidgrubs + raw turret count in one trip. The non-overlapping
        # turret contribution is the raw count MINUS the binary
        # first-tower sentinels (clamped at 0 so a 0-turret row with a
        # first-tower assist does NOT go negative).
        if has_challenges:
            ftk = counts[_FTK_IDX]
            fta = counts[_FTA_IDX]
            herald, void, turret_raw = _challenges_objectives(row[1 + ncols])
            turret_extra = max(turret_raw - ftk - fta, 0.0)
        else:
            herald, void, turret_extra = (0.0, 0.0, 0.0)
        row_total = row_sum6 + herald + void + turret_extra
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
