"""RM-1156: a garbage string in a boolean body key falls back to the default.

``_opt_bool`` in ``agents/daemon_slayer/server.py`` mapped every string that
was not one of the four truthy words to False. For a DEFAULT-OFF seam that is
the default, so nothing showed. For the DEFAULT-ON keys (``filter_shared_uniques``
on six rank routes, ``apply_passive_damage`` on ``/rank-onhit``,
``enchanter_only`` on ``/rank-enchanter``, ``boots_unique`` on ``/beam``,
``assume_item_crit_dr`` / ``assume_item_aa_dr`` / ``assume_item_enemy_as_slow``) a
typo such as ``"ture"`` or an empty string silently DISARMED the filter and the
route answered a well-formed 200 for a question the caller never asked.

Policy, chosen to invent nothing: ``_opt_bool``'s own pinned contract
(``test_per_item_shield_route_seams_rm118.py``,
``test_the_string_and_int_forms_follow_the_shared_opt_bool_contract``) is
"garbage falls back to the default", and RM-1155 applied it to non-finite
numbers. This applies it to strings: the truthy words stay True, the
explicit falsy words ``0`` / ``false`` / ``no`` / ``off`` (any case, padded)
are False, and every other string, the empty one included, is the default.
For a default-False key every answer is unchanged. ASCII only.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer import server
from agents.daemon_slayer.server import _opt_bool

_GARBAGE = ("nope", "", "   ", "ture", "maybe", "2", "nan")


@pytest.mark.parametrize("value", _GARBAGE)
@pytest.mark.parametrize("default", [False, True])
def test_a_garbage_string_takes_the_default(value, default) -> None:
    assert _opt_bool({"k": value}, "k", default) is default


@pytest.mark.parametrize("value", ["0", "false", "FALSE", " no ", "Off"])
@pytest.mark.parametrize("default", [False, True])
def test_an_explicit_falsy_word_is_false_whatever_the_default(
    value, default
) -> None:
    assert _opt_bool({"k": value}, "k", default) is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "On"])
@pytest.mark.parametrize("default", [False, True])
def test_a_truthy_word_is_true_whatever_the_default(value, default) -> None:
    assert _opt_bool({"k": value}, "k", default) is True


@pytest.mark.parametrize(
    "value, expected",
    [(True, True), (False, False), (1, True), (0, False), (2.5, True),
     (None, True), ([], True), ({}, True)],
)
def test_non_string_forms_are_unchanged_under_a_true_default(
    value, expected
) -> None:
    assert _opt_bool({"k": value}, "k", True) is expected


@pytest.fixture(scope="module")
def _loaded_cache():
    """Install the on-disk snapshot for the route handler, then restore
    whatever the cache held so no other module sees this one's state."""
    from agents.daemon_slayer.data_loader import DataSnapshot

    prior = server._CACHE._snap
    server._CACHE.set(DataSnapshot.load())
    yield
    server._CACHE._snap = prior


def _enchanter_body(**extra) -> dict:
    # Probe hygiene: a realistic enchanter build state, never an empty build.
    body = {
        "champion": "Soraka",
        "level": 11,
        "items": ["3504", "3158"],
        "mode": "SR",
        "top": 200,
    }
    body.update(extra)
    return body


@pytest.mark.usefixtures("_loaded_cache")
@pytest.mark.parametrize("garbage", ["ture", ""])
def test_a_garbage_string_does_not_disarm_a_default_on_route_key(
    garbage,
) -> None:
    key = "enchanter_only"
    on = server._route_rank_enchanter(_enchanter_body())
    off = server._route_rank_enchanter(_enchanter_body(**{key: False}))
    # Positive control: the key really moves the route, so ON == the
    # garbage result is a real assertion and not a key that never fires.
    assert on != off
    assert server._route_rank_enchanter(_enchanter_body(**{key: "false"})) == off
    assert server._route_rank_enchanter(_enchanter_body(**{key: garbage})) == on
