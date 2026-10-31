"""RM-1234: a non-object JSON value in a dict body key is a 400.

``_parse_form_index`` (``/ability-dps``, ``/rank-mage``, ``/burst``,
``/rank-assassin``) and the ``granter_resists`` read in
``_route_ally_protected_ehp`` both turned any non-dict value into ``None``, so
the override was dropped and the route answered a well-formed 200 for a
question the caller never asked. Measured on the live server (ENGINE 1.290.0,
patch 16.21.1): ``/ability-dps`` for Hwei at level 11 answered
``total_ability_dps`` 15.67 with ``form_index_source "override"`` for
``form_index: {"Q": 2}``, and 23.06 with ``form_index_source "champion"`` for
``[["Q", 2]]`` and for ``"Q:2"``; ``/ally-protected-ehp`` for Jinx with Taric
answered ``physical_ehp`` 2677.7 for ``granter_resists: {"Taric": [...]}`` and
the no-grant 2493.9 for the same rows as a list.

Policy, chosen to invent nothing: RM-1154 / RM-1157 - a value of the wrong
JSON type is a 400 naming the field, never a silent coercion. Absent or null
still means "no override", and an empty object is still an empty override.
``_parse_block_index`` keeps its documented skip-on-malformed contract and is
not touched here. ASCII only.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer import server
from agents.daemon_slayer.server import _ApiError, _parse_form_index

_WRONG_TYPES = ([["Q", 2]], [], "Q:2", "", True, False, 2, 1.5)


@pytest.mark.parametrize("value", _WRONG_TYPES)
def test_form_index_rejects_a_non_object_value(value) -> None:
    with pytest.raises(_ApiError) as exc:
        _parse_form_index({"form_index": value})
    assert exc.value.status == 400
    assert exc.value.message.startswith("form_index: expected object")


@pytest.mark.parametrize(
    "body, expected",
    [({}, None), ({"form_index": None}, None), ({"form_index": {}}, {}),
     ({"form_index": {"q": 2}}, {"Q": 2}),
     ({"form_index": {"Q": "1", "e": 0}}, {"Q": 1, "E": 0})],
)
def test_form_index_absent_and_object_forms_are_unchanged(body, expected) -> None:
    assert _parse_form_index(body) == expected


@pytest.fixture(scope="module")
def _loaded_cache():
    """Install the on-disk snapshot for the route handler, then restore
    whatever the cache held so no other module sees this one's state."""
    from agents.daemon_slayer.data_loader import DataSnapshot

    prior = server._CACHE._snap
    server._CACHE.set(DataSnapshot.load())
    yield
    server._CACHE._snap = prior


def _hwei_body(**extra) -> dict:
    # Probe hygiene: a realistic build state and squishy sweep targets.
    body = {
        "champion": "Hwei",
        "level": 11,
        "item_ids": ["3089", "6655"],
        "target_armor": 30,
        "target_mr": 30,
        "target_max_hp": 1900,
        "target_bonus_hp": 800,
    }
    body.update(extra)
    return body


@pytest.mark.usefixtures("_loaded_cache")
def test_a_listed_form_index_is_a_400_not_the_registry_default() -> None:
    default = server._route_ability_dps(_hwei_body())
    override = server._route_ability_dps(_hwei_body(form_index={"Q": 2}))
    # Positive control: the object form really is an override that moves
    # the number, so dropping a listed one answered a different question.
    assert override["form_index_source"] == "override"
    assert default["form_index_source"] != "override"
    assert override["total_ability_dps"] != default["total_ability_dps"]
    for bad in ([["Q", 2]], "Q:2"):
        with pytest.raises(_ApiError) as exc:
            server._route_ability_dps(_hwei_body(form_index=bad))
        assert exc.value.status == 400


def _jinx_body(**extra) -> dict:
    body = {"champion": "Jinx", "level": 11, "ally_grant_champions": ["Taric"]}
    body.update(extra)
    return body


@pytest.mark.usefixtures("_loaded_cache")
def test_a_listed_granter_resists_is_a_400_not_the_default_grant() -> None:
    base = server._route_ally_protected_ehp(_jinx_body())
    given = server._route_ally_protected_ehp(
        _jinx_body(granter_resists={"Taric": [150, 120, 40, 32]}))
    # Positive control: the object form moves Taric's percent-of-resist grant.
    assert given["physical_ehp"] != base["physical_ehp"]
    assert server._route_ally_protected_ehp(
        _jinx_body(granter_resists=None))["physical_ehp"] == base["physical_ehp"]
    for bad in ([["Taric", 150, 120, 40, 32]], "Taric", 7, True):
        with pytest.raises(_ApiError) as exc:
            server._route_ally_protected_ehp(_jinx_body(granter_resists=bad))
        assert exc.value.status == 400
        assert exc.value.message.startswith("granter_resists: expected object")
