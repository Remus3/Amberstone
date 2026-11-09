"""S144-T-597: core.carry_share never raises on a wrong-typed roster and never
reports a share outside 0..100 or over the wrong set of players.

The caller (dashboard/builders_last_match.py) computes both shares inside the
last-match builder's try block, so a raise here does not just blank one stat -
it replaces the WHOLE Post Game Review payload with "internal error - see
logs". Measured before the fix:

  * a non-dict row (None, a string) raised AttributeError;
  * a non-numeric string, NaN, inf, a dict or a list in a gold / damage
    field raised ValueError / OverflowError / TypeError;
  * a roster that is a dict, a string or a generator was iterated as one
    (a generator lost every row before the operator's to next());
  * a negative value gave a negative share, or a share far above 100;
  * a bool value read as 1 (True) and a numeric string was coerced;
  * an operator row with no team_id summed every row that also lacked one
    (the whole lobby) and called it the team;
  * two is_me rows silently used the first; a truthy non-bool is_me
    ("false", 1) marked the operator.

Contract now: the roster must be a list or tuple of dict rows; the operator is
the ONE row whose is_me is the bool True; the team is the rows whose team_id
equals the operator's, which must be an int (not bool) or a non-blank str;
a value must be a non-bool int or a finite float, >= 0; a missing or None
value still reads 0 (the pinned contract in tests/test_carry_share.py).
Anything else returns None, which the caller renders as the "-" sentinel.
"""
from __future__ import annotations

import ast
import math
import random

import pytest

from core import carry_share
from core.carry_share import dmg_share_pct, gold_share_pct

_FNS = (("gold", gold_share_pct), ("damage_to_champs", dmg_share_pct))


def _team(field, me=1000, mates=(2000,), me_team=100):
    rows = [{"is_me": True, "team_id": me_team, field: me}]
    rows += [{"is_me": False, "team_id": me_team, field: v} for v in mates]
    rows.append({"is_me": False, "team_id": 200, field: 99999})
    return rows


# -- roster shape -------------------------------------------------------------

@pytest.mark.parametrize("field,fn", _FNS)
@pytest.mark.parametrize("roster", [
    {"is_me": True, "team_id": 100, "gold": 5},
    "is_me",
    42,
    3.5,
    True,
    object(),
])
def test_non_list_roster_reads_none(field, fn, roster):
    assert fn(roster) is None


@pytest.mark.parametrize("field,fn", _FNS)
def test_generator_roster_reads_none_not_a_partial_sum(field, fn):
    # Operator FIRST: the old body's next() consumed that row, so its sum saw
    # only the teammate and reported 1000 / 9000 = 11.1 instead of 10.0.
    rows = [{"is_me": True, "team_id": 100, field: 1000},
            {"is_me": False, "team_id": 100, field: 9000}]
    assert fn(r for r in rows) is None
    assert fn(rows) == 10.0


@pytest.mark.parametrize("field,fn", _FNS)
def test_tuple_roster_is_accepted(field, fn):
    assert fn(tuple(_team(field))) == 33.3


@pytest.mark.parametrize("field,fn", _FNS)
@pytest.mark.parametrize("junk_row", [None, "row", 7, ["is_me", True]])
def test_non_dict_row_reads_none(field, fn, junk_row):
    rows = _team(field)
    rows.insert(1, junk_row)
    assert fn(rows) is None


# -- operator row -------------------------------------------------------------

@pytest.mark.parametrize("field,fn", _FNS)
def test_two_operator_rows_read_none(field, fn):
    rows = _team(field)
    rows.append({"is_me": True, "team_id": 100, field: 5000})
    assert fn(rows) is None


@pytest.mark.parametrize("field,fn", _FNS)
@pytest.mark.parametrize("truthy", ["false", "yes", 1, [1], {"a": 1}])
def test_truthy_non_bool_is_me_is_not_the_operator(field, fn, truthy):
    rows = [{"is_me": truthy, "team_id": 100, field: 1000},
            {"is_me": False, "team_id": 100, field: 3000}]
    assert fn(rows) is None


@pytest.mark.parametrize("field,fn", _FNS)
def test_truthy_non_bool_is_me_does_not_shadow_the_real_operator(field, fn):
    rows = [{"is_me": 1, "team_id": 100, field: 3000},
            {"is_me": True, "team_id": 100, field: 1000}]
    assert fn(rows) == 25.0


# -- team id ------------------------------------------------------------------

@pytest.mark.parametrize("field,fn", _FNS)
def test_missing_operator_team_id_reads_none_not_the_whole_lobby(field, fn):
    rows = [{"is_me": True, field: 1000},
            {"is_me": False, field: 1000},
            {"is_me": False, field: 2000}]
    assert fn(rows) is None


@pytest.mark.parametrize("field,fn", _FNS)
@pytest.mark.parametrize("bad_team", [None, True, False, "", "   ", 1.5,
                                      float("nan"), [100], {"t": 100}])
def test_junk_operator_team_id_reads_none(field, fn, bad_team):
    rows = _team(field, me_team=bad_team)
    assert fn(rows) is None


@pytest.mark.parametrize("field,fn", _FNS)
def test_bool_teammate_team_id_never_matches_int_team_one(field, fn):
    rows = [{"is_me": True, "team_id": 1, field: 1000},
            {"is_me": False, "team_id": True, field: 9000},
            {"is_me": False, "team_id": 1, field: 1000}]
    assert fn(rows) == 50.0


@pytest.mark.parametrize("field,fn", _FNS)
def test_str_team_id_is_accepted(field, fn):
    rows = [{"is_me": True, "team_id": "blue", field: 1000},
            {"is_me": False, "team_id": "blue", field: 3000},
            {"is_me": False, "team_id": "red", field: 9000}]
    assert fn(rows) == 25.0


# -- values -------------------------------------------------------------------

_JUNK_VALUES = ["abc", "5000", "", "1e3", float("nan"), float("inf"),
                float("-inf"), True, False, {"v": 1}, [1000], -1, -0.5]


@pytest.mark.parametrize("field,fn", _FNS)
@pytest.mark.parametrize("junk", _JUNK_VALUES, ids=repr)
def test_junk_operator_value_reads_none(field, fn, junk):
    assert fn(_team(field, me=junk)) is None


@pytest.mark.parametrize("field,fn", _FNS)
@pytest.mark.parametrize("junk", _JUNK_VALUES, ids=repr)
def test_junk_teammate_value_reads_none(field, fn, junk):
    assert fn(_team(field, mates=(2000, junk))) is None


@pytest.mark.parametrize("field,fn", _FNS)
def test_junk_enemy_value_is_ignored(field, fn):
    rows = _team(field)
    rows[-1][field] = "corrupt"
    assert fn(rows) == 33.3


@pytest.mark.parametrize("field,fn", _FNS)
def test_negative_teammate_can_no_longer_push_share_past_100(field, fn):
    assert fn(_team(field, me=5000, mates=(-4000,))) is None


@pytest.mark.parametrize("field,fn", _FNS)
def test_missing_or_none_operator_value_reads_zero_share(field, fn):
    rows = _team(field)
    rows[0][field] = None
    assert fn(rows) == 0.0
    del rows[0][field]
    assert fn(rows) == 0.0


@pytest.mark.parametrize("field,fn", _FNS)
def test_integral_float_value_is_accepted(field, fn):
    assert fn(_team(field, me=1000.0, mates=(2000.0,))) == 33.3


@pytest.mark.parametrize("field,fn", _FNS)
def test_huge_values_never_overflow(field, fn):
    big = 10 ** 400
    assert fn(_team(field, me=big, mates=(big,))) == 50.0
    assert fn(_team(field, me=1e308, mates=(1e308,))) == 50.0


@pytest.mark.parametrize("field,fn", _FNS)
def test_result_is_always_finite_and_in_range(field, fn):
    rng = random.Random(597)
    for _ in range(500):
        me = rng.choice([0, 1, rng.randint(0, 40000), 10 ** 30])
        mates = tuple(rng.choice([0, rng.randint(0, 40000), None])
                      for _ in range(rng.randint(0, 4)))
        out = fn(_team(field, me=me, mates=mates))
        if out is not None:
            assert isinstance(out, float)
            assert math.isfinite(out) and 0.0 <= out <= 100.0


# -- byte-identity on valid input --------------------------------------------

def _old_share(roster, field):
    """The pre-S144-T-597 body, verbatim, as the valid-input oracle."""
    rows = roster or []
    me = next((r for r in rows if r.get("is_me")), None)
    if me is None:
        return None
    my_team = me.get("team_id")
    team_total = sum(int(r.get(field) or 0)
                     for r in rows if r.get("team_id") == my_team)
    if team_total <= 0:
        return None
    return round(100.0 * int(me.get(field) or 0) / team_total, 1)


@pytest.mark.parametrize("field,fn", _FNS)
def test_valid_input_is_byte_identical_to_the_old_body(field, fn):
    rng = random.Random(5970)
    for _ in range(3000):
        my_team = rng.choice([100, 200, 0, "blue"])
        rows = []
        n_me_pos = rng.randint(0, 9)
        for i in range(10):
            team = my_team if i < 5 else (300 if my_team != 300 else 400)
            row = {"is_me": i == n_me_pos and i < 5, "team_id": team}
            pick = rng.random()
            if pick < 0.08:
                pass  # key absent
            elif pick < 0.12:
                row[field] = None
            elif pick < 0.2:
                row[field] = 0
            elif pick < 0.3:
                row[field] = float(rng.randint(0, 60000))
            else:
                row[field] = rng.randint(0, 60000)
            rows.append(row)
        rng.shuffle(rows)
        assert fn(rows) == _old_share(rows, field)
        assert fn(list(rows)) == _old_share(list(rows), field)


def test_module_has_no_exception_handler_that_could_hide_a_bug():
    # Junk is refused by explicit shape checks, never by a try/except that
    # would also swallow a programming error.
    with open(carry_share.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Try)]
