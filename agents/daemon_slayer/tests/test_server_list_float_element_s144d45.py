"""RM-1236: a FLOAT element in a DS list body key is an id only when integral.

``_coerce_str_list`` ran ``str(item)`` over a float element, so the JSON
number ``8005.0`` became the token ``"8005.0"``. Measured on the live server
(ENGINE 1.290.0, patch 16.21.1):

- ``/enemy-rune-threat`` ``enemy_rune_ids: [8005]`` answered
  ``incoming_amp_pct`` 0.08 (Press the Attack); ``[8005.0]`` answered 0.0 -
  ``_coerce_int_list`` dropped ``int("8005.0")`` as a junk token, so the
  threat silently vanished from a well-formed 200;
- ``/rank-mage`` (Lux L11, squishy targets) ``items: [6655]`` answered 200;
  ``[6655.0]`` answered 404 "unknown champion, item or augment".

Policy (lane adjudication, recorded in the commit): JSON has one number type,
so an integral finite float is the same id as the integer and is accepted as
``str(int(f))`` - the same reading ``_to_int`` already gives ``level: 11.0``.
A non-integral float (``6655.5``) or a non-finite one (``Infinity`` / ``NaN``
tokens, or ``1e400``) is never an id: a 400 naming the field and index, as
RM-1235 does for a bool / object / array element. Rejected alternative: a
400 for every float, which would refuse a value that equals a valid id.

Unchanged: int / string / None elements and the comma-string form; the
``_coerce_int_list`` fail-soft drop of a junk STRING token. ASCII only.
"""
from __future__ import annotations

import math

import pytest

from agents.daemon_slayer import server
from agents.daemon_slayer.server import (
    _ApiError,
    _coerce_int_list,
    _coerce_str_list,
)


@pytest.mark.parametrize(
    "value, expected",
    [([6655.0], ["6655"]), (["3089", 6655.0], ["3089", "6655"]),
     ([-0.0], ["0"]), ([1e3], ["1000"])],
)
def test_an_integral_float_element_is_the_integer_id(value, expected) -> None:
    assert _coerce_str_list(value, "items") == expected


def test_int_list_keeps_an_integral_float_rune_id() -> None:
    assert _coerce_int_list([8005.0, 8021], "enemy_rune_ids") == [8005, 8021]


@pytest.mark.parametrize("bad", [6655.5, 0.1, math.inf, -math.inf, math.nan])
@pytest.mark.parametrize("helper", [_coerce_str_list, _coerce_int_list])
def test_a_non_integral_or_non_finite_float_is_a_400(helper, bad) -> None:
    with pytest.raises(_ApiError) as exc:
        helper(["6655", bad], "items")
    assert exc.value.status == 400
    assert exc.value.message.startswith(
        "items[1]: expected string or integer, got float ")


def test_the_400_names_the_value_with_repr() -> None:
    with pytest.raises(_ApiError) as exc:
        _coerce_str_list([6655.5], "items")
    assert exc.value.message == (
        "items[0]: expected string or integer, got float 6655.5")


def test_other_accepted_forms_are_unchanged() -> None:
    assert _coerce_str_list([6655, " 3089 ", None, ""], "items") == [
        "6655", "3089"]
    assert _coerce_str_list("6655.0, 3089", "items") == ["6655.0", "3089"]
    assert _coerce_int_list(["8005", "abc", "8005.0"], "rune_ids") == [8005]


def test_enemy_rune_threat_credits_an_integral_float_rune_id() -> None:
    as_int = server._route_enemy_rune_threat(
        {"enemy_rune_ids": [8005], "level": 11})
    as_float = server._route_enemy_rune_threat(
        {"enemy_rune_ids": [8005.0], "level": 11})
    # Positive control: Press the Attack really carries an incoming amp, so
    # equality below is the id being read, not two empty answers agreeing.
    assert as_int["incoming_amp_pct"] > 0.0
    assert as_float == as_int


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
def test_rank_mage_reads_an_integral_float_item_like_the_integer() -> None:
    as_str = server._route_rank_mage(_lux_body(items=["6655"]))
    as_float = server._route_rank_mage(_lux_body(items=[6655.0]))
    assert as_float == as_str


@pytest.mark.usefixtures("_loaded_cache")
def test_rank_mage_answers_400_not_404_for_a_fractional_item() -> None:
    with pytest.raises(_ApiError) as exc:
        server._route_rank_mage(_lux_body(items=[6655.5]))
    assert exc.value.status == 400
    assert exc.value.message == (
        "items[0]: expected string or integer, got float 6655.5")
