"""RM-1238: an integral float in the DS ``block_index`` body key is its integer.

``_parse_block_index`` accepted only Python ``int`` values, so the JSON number
``0.0`` (what ``json.dumps`` writes for a Python float) was silently skipped and
the engine fell back to the per-champion registry. Measured on the live server
(ENGINE 1.290.0, patch 16.21.1), ``/ability-dps`` Cassiopeia L11, items
``["6655"]``, squishy targets, E ``raw_damage_per_cast``:

- ``{"E": 0}`` 155.0, ``{"E": 0.0}`` 233.0 (the registry default, block 1);
- ``{"E": [0, 1]}`` 388.0, ``{"E": [0.0, 1.0]}`` 233.0;
- ``{"E": {"default": 0}}`` 155.0, ``{"E": {"default": 0.0}}`` 233.0.

Every answer was a well-formed 200, so the override vanished unseen.

Policy (lane adjudication, recorded in the commit): JSON has one number type,
so an integral finite float is the same block index as the integer - the
reading RM-1236 gives a list id and RM-1237 gives an int key. The parser
hands the engine a real ``int`` (the engine's trusted-registry validator
``_normalize_block_index_value`` still refuses any float). A fractional or
non-finite float stays MALFORMED and keeps the field's documented
skip-on-malformed / fall-back-to-registry contract (no 400, no 500), as a
bool or a string already does. Rejected alternative: a 400 for a malformed
``block_index`` value, which would break that pinned contract.
ASCII only.
"""
from __future__ import annotations

import math

import pytest

from agents.daemon_slayer import server
from agents.daemon_slayer.server import _parse_block_index


def _parse(value):
    return _parse_block_index({"block_index": {"E": value}})


@pytest.mark.parametrize(
    "value, expected",
    [
        (0.0, 0),
        (1.0, 1),
        (-0.0, 0),
        ([0.0, 1.0], [0, 1]),
        ([0, 1.0], [0, 1]),
        ({"default": 0.0}, {"default": 0}),
        ({"default": [1.0, 3], "target_full_hp": 0.0},
         {"default": [1, 3], "target_full_hp": 0}),
    ],
)
def test_an_integral_float_is_the_integer_block_index(value, expected) -> None:
    out = _parse(value)
    assert out == {"E": expected}


@pytest.mark.parametrize(
    "value",
    [0.0, [0.0, 1.0], {"default": 0.0, "target_no_setup": 1.0}],
)
def test_the_engine_receives_a_real_int_not_a_float(value) -> None:
    def _leaves(v):
        if isinstance(v, dict):
            for x in v.values():
                yield from _leaves(x)
        elif isinstance(v, list):
            yield from v
        else:
            yield v

    out = _parse(value)
    leaves = list(_leaves(out["E"]))
    assert leaves
    assert all(type(x) is int for x in leaves)


@pytest.mark.parametrize(
    "value",
    [
        1.5,
        math.inf,
        -math.inf,
        math.nan,
        [0, 1.5],
        [0.0, math.nan],
        {"default": 0.5},
        {"default": 0, "target_no_setup": math.inf},
        True,
        [0, False],
        "1",
    ],
)
def test_a_malformed_value_keeps_the_skip_contract(value) -> None:
    assert _parse(value) == {}


def test_ints_lists_and_conditionals_are_unchanged() -> None:
    body = {"block_index": {
        "e": 1, "W": [0, 1], "R": {"default": 2, "target_no_setup": 0},
        "Q": []}}
    assert _parse_block_index(body) == {
        "E": 1, "W": [0, 1], "R": {"default": 2, "target_no_setup": 0},
        "Q": []}


@pytest.fixture(scope="module")
def _loaded_cache():
    """Install the on-disk snapshot for the route handler, then restore
    whatever the cache held so no other module sees this one's state."""
    from agents.daemon_slayer.data_loader import DataSnapshot

    prior = server._CACHE._snap
    server._CACHE.set(DataSnapshot.load())
    yield
    server._CACHE._snap = prior


def _cass_e_raw(block_index) -> float:
    # Probe hygiene: a realistic build state and squishy sweep targets.
    out = server._route_ability_dps({
        "champion": "Cassiopeia",
        "level": 11,
        "items": ["6655"],
        "target_armor": 30,
        "target_mr": 30,
        "target_max_hp": 1900,
        "target_bonus_hp": 800,
        "block_index": block_index,
    })
    (row,) = [r for r in out["per_spell"] if r["key"] == "E"]
    return row["raw_damage_per_cast"]


@pytest.mark.usefixtures("_loaded_cache")
@pytest.mark.parametrize(
    "as_int, as_float",
    [
        ({"E": 0}, {"E": 0.0}),
        ({"E": [0, 1]}, {"E": [0.0, 1.0]}),
        ({"E": {"default": 0}}, {"E": {"default": 0.0}}),
    ],
)
def test_ability_dps_reads_an_integral_float_like_the_integer(
        as_int, as_float) -> None:
    # Positive control: the int override really moves E off the registry
    # default, so equality below is the float being read, not two
    # fallbacks agreeing.
    assert _cass_e_raw(as_int) != _cass_e_raw({})
    assert _cass_e_raw(as_float) == _cass_e_raw(as_int)
