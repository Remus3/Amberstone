"""RM-1237: a FRACTIONAL float in a scalar INT body key is a 400, not truncated.

``_to_int`` ran ``int(value)``, so the JSON number ``11.5`` became 11 and the
route answered a question the caller did not ask. Measured on the live server
(ENGINE 1.290.0, patch 16.21.1), POST /rank-mage, Lux, ``items: ["6655"]``,
squishy sweep targets:

- ``level: 11``   -> 200, echoed level 11;
- ``level: 11.5`` -> 200, echoed level 11 (silent truncation);
- ``level: "11.5"`` -> 400 "level: expected integer, got '11.5'".

So the STRING spelling of a fractional level was already refused while the
NUMBER spelling was quietly floored, and since RM-1236 a fractional id in a
list key is a 400 too. ``top: 2.9`` likewise answered 2 rows.

Policy (lane adjudication, recorded in the commit): JSON has one number type,
so an integral finite float (``11.0``) is the integer and stays accepted - the
reading RM-1236 gives a list element. A non-integral float is never an int
key's value: a 400 "<field>: expected integer, got <repr>", the message the
string arm already uses. Rejected alternatives: keep truncation (silent, and
inconsistent with the string arm), or round (still answers a different
question). Caller audit: every first-party sender casts with ``int(...)``
(``core/daemon_slayer_client.py``, ``coaches/sr_draft_profile.py``,
``coach_integration/archetype_dispatch.py``, ``tools/ds_matchdb_mcp_server.py``),
so no shipped caller changes behaviour. Reverses if: a DS int key is found
that a real caller fills with a non-integral number on purpose.

Unchanged: int and digit-string values, the bool and non-finite 400s, and the
``form_index`` values, which reach the same helper. ASCII only.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer import server
from agents.daemon_slayer.server import _ApiError, _opt_int, _to_int


@pytest.mark.parametrize("value", [11.5, 11.7, 0.1, -0.5, 1.000001])
def test_to_int_refuses_a_fractional_float(value) -> None:
    with pytest.raises(_ApiError) as exc:
        _to_int(value, "level")
    assert exc.value.status == 400
    assert exc.value.message == f"level: expected integer, got {value!r}"


def test_opt_int_refuses_a_fractional_float() -> None:
    with pytest.raises(_ApiError) as exc:
        _opt_int({"top": 2.9}, "top", 20)
    assert exc.value.status == 400
    assert exc.value.message == "top: expected integer, got 2.9"


@pytest.mark.parametrize(
    "value, expected",
    [(11, 11), ("11", 11), (11.0, 11), (-0.0, 0), (1e3, 1000)],
)
def test_integral_values_still_coerce(value, expected) -> None:
    """Positive control: the fractional arm must not swallow real integers."""
    assert _to_int(value, "level") == expected


def test_fractional_string_message_is_the_same_shape() -> None:
    """The number arm and the string arm answer alike (one policy)."""
    with pytest.raises(_ApiError) as exc:
        _to_int("11.5", "level")
    assert exc.value.message == "level: expected integer, got '11.5'"


def test_form_index_inherits_the_rejection() -> None:
    """``_parse_form_index`` coerces each value through ``_to_int``."""
    with pytest.raises(_ApiError) as exc:
        server._parse_form_index({"form_index": {"q": 1.5}})
    assert exc.value.status == 400
    assert exc.value.message == "form_index[q]: expected integer, got 1.5"
    assert server._parse_form_index({"form_index": {"q": 1.0}}) == {"Q": 1}


@pytest.fixture(scope="module")
def _loaded_cache():
    """Install the on-disk snapshot for the route handlers, then restore
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
def test_rank_mage_answers_400_for_a_fractional_level() -> None:
    with pytest.raises(_ApiError) as exc:
        server._route_rank_mage(_lux_body(level=11.5))
    assert exc.value.status == 400
    assert exc.value.message == "level: expected integer, got 11.5"


@pytest.mark.usefixtures("_loaded_cache")
def test_rank_mage_reads_an_integral_float_level_like_the_integer() -> None:
    assert server._route_rank_mage(_lux_body(level=11.0)) == (
        server._route_rank_mage(_lux_body(level=11)))
