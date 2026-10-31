"""RM-1157: a non-string JSON value in a string body key is a 400.

``_opt_str`` and ``_required_str`` in ``agents/daemon_slayer/server.py`` ran
``str(v)`` over whatever JSON value arrived. A list, an object, a boolean or a
number in a string key therefore became its Python repr and the route
answered a well-formed 200 for a question the caller never asked. Measured on
the live server (ENGINE 1.290.0, patch 16.21.1): ``/rank-mage`` for Lux at
level 11 with ``mode: ["ARAM"]`` echoed ``mode "['ARAM']"`` and scored 247
candidates against 121 for ``mode: "ARAM"`` - an unknown mode allows every
map's items, the Arena-only variants included - and ``champion: ["Lux"]``
resolved to Lux through the alnum-stripped name fallback.

Policy, chosen to invent nothing: it is the one RM-1154 states for a JSON
boolean in a numeric key and RM-479 states for ``augment_stacks`` - a value of
the wrong JSON type is a 400 naming the field, never a silent coercion. Absent
or null still takes the default, and the query-string transport is untouched
because it only ever carries strings. ASCII only.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer import server
from agents.daemon_slayer.server import _ApiError, _opt_str, _required_str

_WRONG_TYPES = (["ARAM"], {"m": "ARAM"}, True, False, 12, 1.5, [])


@pytest.mark.parametrize("value", _WRONG_TYPES)
def test_opt_str_rejects_a_non_string_value(value) -> None:
    with pytest.raises(_ApiError) as exc:
        _opt_str({"mode": value}, "mode", "SR")
    assert exc.value.status == 400
    assert exc.value.message.startswith("mode: expected string")


@pytest.mark.parametrize("value", _WRONG_TYPES)
def test_required_str_rejects_a_non_string_value(value) -> None:
    with pytest.raises(_ApiError) as exc:
        _required_str({"champion": value}, "champion")
    assert exc.value.status == 400
    assert exc.value.message.startswith("champion: expected string")


@pytest.mark.parametrize(
    "body, expected",
    [({}, "SR"), ({"mode": None}, "SR"), ({"mode": ""}, "SR"),
     ({"mode": "   "}, "SR"), ({"mode": " aram "}, "aram"),
     ({"mode": "ARENA"}, "ARENA")],
)
def test_opt_str_string_and_absent_forms_are_unchanged(body, expected) -> None:
    assert _opt_str(body, "mode", "SR") == expected


def test_required_str_string_forms_are_unchanged() -> None:
    assert _required_str({"champion": "  Lux "}, "champion") == "Lux"
    for body in ({}, {"champion": None}, {"champion": "  "}):
        with pytest.raises(_ApiError) as exc:
            _required_str(body, "champion")
        assert exc.value.status == 400
        assert exc.value.message == "missing required field: champion"


@pytest.fixture(scope="module")
def _loaded_cache():
    """Install the on-disk snapshot for the route handler, then restore
    whatever the cache held so no other module sees this one's state."""
    from agents.daemon_slayer.data_loader import DataSnapshot

    prior = server._CACHE._snap
    server._CACHE.set(DataSnapshot.load())
    yield
    server._CACHE._snap = prior


def _mage_body(**extra) -> dict:
    # Probe hygiene: a realistic build state and squishy sweep targets.
    body = {
        "champion": "Lux",
        "level": 11,
        "items": ["6655"],
        "mode": "ARAM",
        "top": 200,
        "target_armor": 30,
        "target_mr": 30,
        "target_max_hp": 1900,
        "target_bonus_hp": 800,
    }
    body.update(extra)
    return body


@pytest.mark.usefixtures("_loaded_cache")
def test_a_listed_mode_is_a_400_not_an_allow_all_pool() -> None:
    aram = server._route_rank_mage(_mage_body())
    unknown = server._route_rank_mage(_mage_body(mode="NOT_A_MODE"))
    # Positive control: an unknown mode really widens the pool, so the
    # repr path was scoring a different question, not the same one.
    assert unknown["candidates_evaluated"] > aram["candidates_evaluated"]
    with pytest.raises(_ApiError) as exc:
        server._route_rank_mage(_mage_body(mode=["ARAM"]))
    assert exc.value.status == 400


@pytest.mark.usefixtures("_loaded_cache")
def test_a_listed_champion_is_a_400_not_a_fuzzy_match() -> None:
    with pytest.raises(_ApiError) as exc:
        server._route_rank_mage(_mage_body(champion=["Lux"]))
    assert exc.value.status == 400
