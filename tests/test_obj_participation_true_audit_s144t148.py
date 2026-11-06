# tests/test_obj_participation_true_audit_s144t148.py
"""True-audit regressions for core.obj_participation (s144 cycle 148).

compute_obj_participation feeds obj_participation_pct into the post-game
rubric grade (dashboard/routes_post_game_rubric.py, scripts/
postmortem_analyze.py). Its docstring promises a float in [0.0, 1.0] and
"Never raises". Findings (provisional ids RM-1861..RM-1867):

- RM-1861: a non-finite contribution - a NaN / Infinity / 1e400 literal in
  challenges_json (json.loads accepts all three) or an inf REAL in an SQL
  objective column - made the team total non-finite, every clamp comparison
  False, and the function returned NaN.
- RM-1862: a negative (corrupt) count on a TEAMMATE row was summed into
  the denominator, shrinking the team total and inflating the operator's
  share (1 / (1 - 5 + 5) = 1.0 where the honest share is 1 / 6). The six SQL
  columns were summed inside SQL, so one bad column was invisible to Python.
- RM-1863: a JSON boolean (true) counted as one objective.
- RM-1864: an absurd finite count (1e308) overflowed the team sum to inf
  and erased the operator's real share to 0.0.
- RM-1865: a deeply nested challenges_json raised RecursionError out of
  _challenges_objectives (also imported by core.precomputed_replay_narrative).
- RM-1866: a match_id or puuid holding a lone surrogate raised
  UnicodeEncodeError out of sqlite3 parameter binding.
- RM-1867: a non-str match_id / puuid whose truthiness raises escaped,
  because the falsy check ran before the isinstance check.

Well-formed rows give byte-identical ratios (pinned below).
"""
from __future__ import annotations

import json
import math
import sqlite3

import pytest

from core.obj_participation import (
    _challenges_objectives,
    _coerce_float,
    compute_obj_participation,
)

_COLS = (
    "dragon_kills", "baron_kills", "objectives_stolen",
    "objectives_stolen_assists", "first_tower_kill", "first_tower_assist",
)


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.execute(
        "CREATE TABLE participants (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "match_id TEXT, team_id INTEGER, puuid TEXT, "
        + ", ".join(f"{col} INTEGER" for col in _COLS)
        + ", challenges_json TEXT)"
    )
    yield c
    c.close()


def _ins(c, puuid, *, match_id="M1", team_id=100, challenges=None, **cols):
    if isinstance(challenges, dict):
        challenges = json.dumps(challenges)
    vals = [cols.get(col, 0) for col in _COLS]
    c.execute(
        "INSERT INTO participants (match_id, team_id, puuid, "
        + ", ".join(_COLS)
        + ", challenges_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (match_id, team_id, puuid, *vals, challenges),
    )


def _ratio(c, match_id="M1", puuid="SELF"):
    out = compute_obj_participation(c, match_id, puuid)
    assert isinstance(out, float)
    assert math.isfinite(out), out
    assert 0.0 <= out <= 1.0, out
    return out


# --- RM-1861: non-finite contributions -------------------------------


@pytest.mark.parametrize(
    "blob",
    [
        '{"riftHeraldTakedowns": NaN}',
        '{"turretTakedowns": Infinity}',
        '{"voidMonsterKill": -Infinity}',
        '{"riftHeraldTakedowns": 1e400}',
    ],
)
def test_non_finite_challenges_value_is_dropped_not_nan(conn, blob):
    _ins(conn, "SELF", dragon_kills=1, challenges=blob)
    _ins(conn, "A1", dragon_kills=1)
    assert _ratio(conn) == 0.5


def test_non_finite_tuple_slots_are_zero():
    assert _challenges_objectives(
        '{"riftHeraldTakedowns": NaN, "voidMonsterKill": Infinity, '
        '"turretTakedowns": 4}'
    ) == (0.0, 0.0, 4.0)


@pytest.mark.parametrize("bad", [float("inf"), float("-inf")])
def test_non_finite_sql_column_is_dropped_not_nan(conn, bad):
    _ins(conn, "SELF", dragon_kills=1, baron_kills=bad)
    _ins(conn, "A1", dragon_kills=1)
    assert _ratio(conn) == 0.5


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", float("nan")])
def test_coerce_float_rejects_non_finite(bad):
    assert _coerce_float(bad) == 0.0


# --- RM-1862: negative counts -----------------------------------------


def test_negative_teammate_sql_count_does_not_inflate_operator_share(conn):
    _ins(conn, "SELF", dragon_kills=1)
    _ins(conn, "A1", dragon_kills=-5)
    _ins(conn, "A2", dragon_kills=5)
    assert _ratio(conn) == pytest.approx(1.0 / 6.0)


def test_negative_column_inside_one_row_does_not_cancel_a_real_one(conn):
    # SELF: 2 dragons, corrupt -2 barons -> the row is worth 2, not 0.
    _ins(conn, "SELF", dragon_kills=2, baron_kills=-2)
    _ins(conn, "A1", dragon_kills=2)
    assert _ratio(conn) == 0.5


def test_negative_teammate_challenges_count_does_not_inflate_share(conn):
    _ins(conn, "SELF", challenges={"riftHeraldTakedowns": 1})
    _ins(conn, "A1", challenges={"voidMonsterKill": -3})
    _ins(conn, "A2", challenges={"voidMonsterKill": 3})
    assert _ratio(conn) == 0.25


@pytest.mark.parametrize("bad", [-1, -0.5, "-3"])
def test_coerce_float_rejects_negative(bad):
    assert _coerce_float(bad) == 0.0


# --- RM-1863: JSON booleans -------------------------------------------


def test_json_boolean_is_not_an_objective(conn):
    _ins(conn, "SELF", dragon_kills=1, challenges='{"turretTakedowns": true}')
    _ins(conn, "A1", dragon_kills=1)
    assert _ratio(conn) == 0.5


@pytest.mark.parametrize("bad", [True, False])
def test_coerce_float_rejects_bool(bad):
    assert _coerce_float(bad) == 0.0


# --- RM-1864: absurd finite counts -------------------------------------


def test_absurd_teammate_counts_do_not_erase_operator_share(conn):
    _ins(conn, "SELF", dragon_kills=1)
    _ins(conn, "A1", dragon_kills=1, challenges={"turretTakedowns": 1e308})
    _ins(conn, "A2", dragon_kills=1, challenges={"turretTakedowns": 1e308})
    assert _ratio(conn) == pytest.approx(1.0 / 3.0)


def test_coerce_float_rejects_absurd_count():
    assert _coerce_float(1e308) == 0.0
    assert _coerce_float(10_000_000) == 0.0


# --- RM-1865: deep nesting --------------------------------------------


def test_deeply_nested_challenges_blob_never_raises():
    assert _challenges_objectives("[" * 200_000) == (0.0, 0.0, 0.0)


def test_deeply_nested_challenges_row_falls_soft(conn):
    _ins(conn, "SELF", dragon_kills=1, challenges="[" * 200_000)
    _ins(conn, "A1", dragon_kills=1)
    assert _ratio(conn) == 0.5


# --- RM-1866 / 397: identifier shapes ---------------------------------


@pytest.mark.parametrize(
    "match_id, puuid", [("M\ud800", "SELF"), ("M1", "S\udfff")]
)
def test_lone_surrogate_identifier_returns_zero(conn, match_id, puuid):
    _ins(conn, "SELF", dragon_kills=1)
    assert compute_obj_participation(conn, match_id, puuid) == 0.0


class _BoolRaises:
    def __bool__(self):
        raise ValueError("ambiguous truth value")


@pytest.mark.parametrize("which", ["match_id", "puuid"])
def test_identifier_whose_truthiness_raises_returns_zero(conn, which):
    args = {"match_id": "M1", "puuid": "SELF"}
    args[which] = _BoolRaises()
    assert compute_obj_participation(conn, **args) == 0.0


# --- characterization: well-formed rows unchanged ------------------------


def test_well_formed_nine_column_ratio_is_unchanged(conn):
    _ins(
        conn, "SELF", dragon_kills=2, baron_kills=1, first_tower_kill=1,
        challenges={"riftHeraldTakedowns": 1, "voidMonsterKill": 3,
                    "turretTakedowns": 4},
    )
    _ins(conn, "A1", dragon_kills=1, objectives_stolen=1,
         challenges={"turretTakedowns": 2})
    _ins(conn, "A2", objectives_stolen_assists=1, first_tower_assist=1)
    _ins(conn, "E1", team_id=200, dragon_kills=9)
    # SELF = 2+1+1 + 1 + 3 + (4-1) = 11; A1 = 1+1+2 = 4; A2 = 1+1 = 2.
    assert compute_obj_participation(conn, "M1", "SELF") == 11.0 / 17.0


def test_null_and_text_count_columns_still_read_as_zero(conn):
    _ins(conn, "SELF", dragon_kills=None, baron_kills=1)
    _ins(conn, "A1", dragon_kills="abc", baron_kills=1)
    assert compute_obj_participation(conn, "M1", "SELF") == 0.5


def test_legacy_schema_without_challenges_still_uses_six_columns():
    c = sqlite3.connect(":memory:")
    try:
        c.execute(
            "CREATE TABLE participants (match_id TEXT, team_id INTEGER, "
            "puuid TEXT, " + ", ".join(f"{col} INTEGER" for col in _COLS) + ")"
        )
        c.execute(
            "INSERT INTO participants VALUES "
            "('M1', 100, 'SELF', 1, 0, 0, 0, 0, 0), "
            "('M1', 100, 'A1', 1, 0, -4, 0, 0, 0)"
        )
        assert compute_obj_participation(c, "M1", "SELF") == 0.5
    finally:
        c.close()
