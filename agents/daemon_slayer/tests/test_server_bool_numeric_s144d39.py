"""RM-1154: a JSON boolean in a scalar NUMERIC body key is a 400, not 1 / 0.

``json.loads`` hands ``true`` / ``false`` over as Python ``bool``, and
``bool`` is a subclass of ``int``, so ``int(True) == 1`` and
``float(True) == 1.0``. Every scalar numeric coercion in
``agents/daemon_slayer/server.py`` (``_to_int`` and so ``_opt_int``,
``_opt_float``, ``_opt_weight``, ``_opt_targets_override``) took the
boolean silently: ``{"target_armor": true}`` scored against 1 armor,
``{"top": true}`` truncated the ranking to one row, ``{"alpha": false}``
pinned a hybrid weight to 0.0 - each a well-formed 200 answering a
question the caller did not ask.

The same module already rejects a boolean wherever it states a policy:
``_opt_augment_stacks`` (RM-479, "a caller can never set it with no
effect") and ``_block_index_scalar_ok`` ("bool rejected"). This guard
extends that existing policy to the scalar helpers; it invents none.

Out of scope on purpose: list fields (``items`` / ``runes`` / ``only``)
keep junk TOKENS fail-soft per ``_coerce_int_list``'s documented policy (a
bool / object / array ELEMENT is a 400 since RM-1235), and
``_opt_bool`` already takes a boolean by design. ASCII only.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer import server
from agents.daemon_slayer.server import (
    _ApiError,
    _opt_float,
    _opt_int,
    _opt_targets_override,
    _opt_weight,
    _to_int,
)


def _call(helper: str, key: str, value):
    body = {key: value}
    if helper == "_to_int":
        return _to_int(value, key)
    if helper == "_opt_int":
        return _opt_int(body, key, 20)
    if helper == "_opt_float":
        return _opt_float(body, key, 0.0)
    if helper == "_opt_weight":
        return _opt_weight(body, key)
    if helper == "_opt_targets_override":
        return _opt_targets_override(body)
    raise AssertionError(helper)


_HELPERS = [
    ("_to_int", "level"),
    ("_opt_int", "top"),
    ("_opt_float", "target_armor"),
    ("_opt_weight", "alpha"),
    ("_opt_targets_override", "targets_per_proc_override"),
]


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize(("helper", "key"), _HELPERS)
def test_boolean_is_a_400_naming_the_key(helper, key, value):
    with pytest.raises(_ApiError) as ctx:
        _call(helper, key, value)
    assert ctx.value.status == 400
    assert key in ctx.value.message
    assert repr(value) in ctx.value.message


@pytest.mark.parametrize(("helper", "key"), _HELPERS)
@pytest.mark.parametrize("value", [3, 3.0, "3"])
def test_ordinary_numbers_still_coerce(helper, key, value):
    """Positive control: the bool arm must not swallow real numbers."""
    assert _call(helper, key, value) == 3


@pytest.mark.parametrize(("helper", "key"), [h for h in _HELPERS if h[0] != "_to_int"])
@pytest.mark.parametrize("value", [None, ""])
def test_absent_values_still_take_the_default(helper, key, value):
    expected = {"_opt_int": 20, "_opt_float": 0.0}.get(helper)
    assert _call(helper, key, value) == expected


def test_form_index_rank_inherits_the_rejection():
    """``_parse_form_index`` coerces each value through ``_to_int``."""
    with pytest.raises(_ApiError) as ctx:
        server._parse_form_index({"form_index": {"q": True}})
    assert ctx.value.status == 400
    assert "form_index[q]" in ctx.value.message


@pytest.fixture(scope="module")
def _loaded_cache():
    """Install the on-disk snapshot for the route handlers, then restore
    whatever the cache held so no other module sees this one's state."""
    from agents.daemon_slayer.data_loader import DataSnapshot

    prior = server._CACHE._snap
    server._CACHE.set(DataSnapshot.load())
    yield
    server._CACHE._snap = prior


@pytest.mark.usefixtures("_loaded_cache")
@pytest.mark.parametrize(
    ("route", "body", "key"),
    [
        ("_route_stats", {"champion": "Aatrox", "level": True}, "level"),
        ("_route_dps", {"champion": "Aatrox", "level": 11, "target_armor": True}, "target_armor"),
        ("_route_rank", {"champion": "Jinx", "level": 11, "top": True}, "top"),
    ],
)
def test_route_rejects_boolean_before_scoring(route, body, key):
    """End to end through the route handler, so a route that grew its own
    raw ``float()`` / ``int()`` instead of the helpers would fail here."""
    with pytest.raises(_ApiError) as ctx:
        getattr(server, route)(dict(body))
    assert ctx.value.status == 400
    assert key in ctx.value.message
