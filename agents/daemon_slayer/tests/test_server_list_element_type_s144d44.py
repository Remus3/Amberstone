"""RM-1235: a bool / object / array ELEMENT in a DS list body key is a 400.

``_coerce_str_list`` ran ``str(item)`` over every list element, so a JSON
``true`` became the id ``"True"``, an object became ``"{'id': '3089'}"`` and a
nested array became ``"['6655']"``. Measured on the live server (ENGINE
1.290.0, patch 16.21.1), ``/rank-mage`` for Lux at level 11:

- ``items: ["6655", false]`` / ``[true]`` / ``[["6655"]]`` /
  ``["6655", {"id": "3089"}]`` answered 404 "unknown champion, item or
  augment", blaming a well-formed id for a JSON type error;
- ``only: [true]`` and ``only: [{"a": 1}]`` answered a well-formed 200 with
  ``candidates_evaluated`` 0, where ``only: ["3089"]`` evaluates 1.

Policy, chosen to invent nothing: RM-1154 / RM-1157 / RM-1234 - a value of
the wrong JSON type is a 400 naming the field, never a silent coercion. The
docstring already declares the element contract as ``list[str|int]``.

Unchanged on purpose: a ``None`` element is still skipped; ``int`` elements
still stringify (``3089`` -> ``"3089"``); a comma-separated query string still
splits; a junk numeric TOKEN (``"abc"``) in ``_coerce_int_list`` stays
fail-soft (dropped) per its documented policy - that is a bad value of the
right type, not a wrong type. A float element is left as it was (``"3031.0"``):
whether an integral float is an id needs its own policy call. ASCII only.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer import server
from agents.daemon_slayer.server import (
    _ApiError,
    _coerce_int_list,
    _coerce_str_list,
)

_WRONG_ELEMENTS = (True, False, {"id": "3089"}, {}, ["6655"], [])


@pytest.mark.parametrize("bad", _WRONG_ELEMENTS)
@pytest.mark.parametrize("helper", [_coerce_str_list, _coerce_int_list])
def test_a_wrong_type_element_is_a_400_naming_the_field(helper, bad) -> None:
    with pytest.raises(_ApiError) as exc:
        helper(["6655", bad], "items")
    assert exc.value.status == 400
    assert exc.value.message == (
        f"items[1]: expected string or integer, got {type(bad).__name__}")


@pytest.mark.parametrize(
    "value, expected",
    [(None, []), ([], []), ("6655, 3089,", ["6655", "3089"]),
     (["6655", None, " 3089 ", ""], ["6655", "3089"]),
     ([6655, "3089"], ["6655", "3089"]), (("6655",), ["6655"])],
)
def test_accepted_forms_are_unchanged(value, expected) -> None:
    assert _coerce_str_list(value, "items") == expected


def test_int_list_keeps_its_fail_soft_junk_token_policy() -> None:
    assert _coerce_int_list(["8005", "abc", 8021, None], "rune_ids") == [8005, 8021]


@pytest.mark.parametrize("value", [True, 7, {"a": 1}])
def test_a_non_list_value_keeps_its_existing_400(value) -> None:
    with pytest.raises(_ApiError) as exc:
        _coerce_str_list(value, "items")
    assert exc.value.status == 400
    assert exc.value.message.startswith("items: expected list or comma-separated")


@pytest.fixture(scope="module")
def _loaded_cache():
    """Install the on-disk snapshot for the route handler, then restore
    whatever the cache held so no other module sees this one's state."""
    from agents.daemon_slayer.data_loader import DataSnapshot

    prior = server._CACHE._snap
    server._CACHE.set(DataSnapshot.load())
    yield
    server._CACHE._snap = prior


def _lux_body(**extra) -> dict:
    # Probe hygiene: a realistic build state and squishy sweep targets.
    body = {
        "champion": "Lux",
        "level": 11,
        "items": ["6655"],
        "target_armor": 30,
        "target_mr": 30,
        "target_max_hp": 1900,
        "target_bonus_hp": 800,
        "top": 5,
    }
    body.update(extra)
    return body


@pytest.mark.usefixtures("_loaded_cache")
def test_a_bool_in_only_is_a_400_not_an_empty_200() -> None:
    good = server._route_rank_mage(_lux_body(only=["3089"]))
    # Positive control: a real id in ``only`` is evaluated, so the empty
    # answer for ``[true]`` was a different question, not a neutral one.
    assert good["candidates_evaluated"] == 1
    for bad in ([True], [{"a": 1}], ["3089", ["3089"]]):
        with pytest.raises(_ApiError) as exc:
            server._route_rank_mage(_lux_body(only=bad))
        assert exc.value.status == 400
        assert exc.value.message.startswith("only[")


@pytest.mark.usefixtures("_loaded_cache")
def test_a_bool_in_items_is_a_400_not_an_unknown_item_404() -> None:
    with pytest.raises(_ApiError) as exc:
        server._route_rank_mage(_lux_body(items=["6655", False]))
    assert exc.value.status == 400
    assert exc.value.message == "items[1]: expected string or integer, got bool"
