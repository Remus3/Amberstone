"""RM-1276: a JSON integer too large for a float in a float body key is a 400.

``json.loads`` parses an integer literal as an exact Python ``int`` (up to the
4300-digit limit, past which the body is already a 400 "invalid JSON body").
``float(10 ** 400)`` raises OverflowError, which none of the four float
coercions caught (they catch TypeError and ValueError), so the request
escaped to the handler's catch-all as a 500 "internal engine error".
Measured in-process at ENGINE 1.290.0, patch 16.21.1, a 401-digit integer:

- /dps ``target_armor`` (``_opt_float``)            -> unhandled OverflowError;
- /hybrid ``alpha`` (``_opt_weight``)               -> unhandled OverflowError;
- /stats ``augment_stacks`` (``_opt_augment_stacks``) -> unhandled OverflowError;
- /hps ``targets_per_proc_override`` (``_opt_targets_override``) -> same.

The float literal ``1e400`` overflows to ``inf`` while parsing and already
answered the clean 400 "must be a finite number", so the same magnitude got a
400 or a 500 depending on whether it was written with an exponent. Policy: an
integer too large for a float is a non-finite number, so it takes the
"must be a finite number" 400. The message does not echo the digits (a body
may carry up to 4300 of them); it says what was refused instead.

Sibling sweep: /summoner-fight-adj and /enemy-rune-threat ran
``float(_opt_int(body, "level", 1) or 1)`` and 500'd the same way on a
401-digit ``level`` (a 301-digit one answered 200, clamped downstream). They
now coerce through the same helper. The other int keys (``top``,
``form_index``, ...) never call ``float()`` and are not changed: a huge
``level`` elsewhere is the engine's range 422, a huge ``top`` slices.

Unchanged: every existing message for a string, a bool, ``inf`` and a finite
number. ASCII only.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer import server
from agents.daemon_slayer.server import _ApiError

_HUGE = 10 ** 400
_TOO_LARGE = "must be a finite number, got an integer too large for a float"


def _call(site: str, value):
    if site == "_opt_float":
        return server._opt_float({"target_armor": value}, "target_armor", 0.0)
    if site == "_opt_weight":
        return server._opt_weight({"alpha": value}, "alpha")
    if site == "_opt_targets_override":
        return server._opt_targets_override(
            {"targets_per_proc_override": value})
    if site == "_opt_augment_stacks":
        return server._opt_augment_stacks({"augment_stacks": {"X": value}})
    raise AssertionError(site)


_SITES = {
    "_opt_float": "target_armor",
    "_opt_weight": "alpha",
    "_opt_targets_override": "targets_per_proc_override",
    "_opt_augment_stacks": "augment_stacks.X",
}


@pytest.mark.parametrize("site", sorted(_SITES))
@pytest.mark.parametrize("value", [_HUGE, -_HUGE])
def test_huge_integer_is_a_400_not_an_overflow(site, value) -> None:
    with pytest.raises(_ApiError) as exc:
        _call(site, value)
    assert exc.value.status == 400
    assert exc.value.message == f"{_SITES[site]}: {_TOO_LARGE}"
    assert str(_HUGE)[:40] not in exc.value.message


@pytest.mark.parametrize("site", sorted(_SITES))
def test_existing_messages_are_unchanged(site) -> None:
    """Fence on the fix's shape: the other arms answer as before."""
    field = _SITES[site]
    for value, text in (
        (float("inf"), f"{field}: must be a finite number, got inf"),
        ("abc", f"{field}: expected number, got 'abc'"),
        (True, f"{field}: expected number, got True"),
    ):
        with pytest.raises(_ApiError) as exc:
            _call(site, value)
        assert exc.value.status == 400
        assert exc.value.message == text


@pytest.mark.parametrize("site", sorted(_SITES))
@pytest.mark.parametrize("value, expected", [
    (30, 30.0), ("30", 30.0), (2.5, 2.5), (2 ** 53, float(2 ** 53)),
    (10 ** 308, 1e308),
])
def test_large_but_representable_numbers_still_coerce(
        site, value, expected) -> None:
    """Positive control: only a non-representable integer is refused."""
    got = _call(site, value)
    if site == "_opt_augment_stacks":
        got = got["X"]
    assert got == expected


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
@pytest.mark.parametrize("route, extra, field", [
    ("_route_dps", {"target_armor": _HUGE}, "target_armor"),
    ("_route_hybrid", {"alpha": _HUGE}, "alpha"),
    ("_route_stats", {"augment_stacks": {"X": _HUGE}}, "augment_stacks.X"),
    ("_route_hps", {"targets_per_proc_override": _HUGE},
     "targets_per_proc_override"),
])
def test_routes_answer_400_for_a_huge_integer(route, extra, field) -> None:
    body = {"champion": "Lux", "level": 11, "items": ["6655"]}
    body.update(extra)
    with pytest.raises(_ApiError) as exc:
        getattr(server, route)(body)
    assert exc.value.status == 400
    assert exc.value.message == f"{field}: {_TOO_LARGE}"


@pytest.mark.parametrize("route", [
    "_route_summoner_fight_adj", "_route_enemy_rune_threat"])
def test_float_level_routes_answer_400_for_a_huge_level(route) -> None:
    with pytest.raises(_ApiError) as exc:
        getattr(server, route)({"level": _HUGE})
    assert exc.value.status == 400
    assert exc.value.message == f"level: {_TOO_LARGE}"


@pytest.mark.parametrize("route", [
    "_route_summoner_fight_adj", "_route_enemy_rune_threat"])
def test_float_level_routes_keep_their_level_reading(route) -> None:
    """Positive control: a real level, a large representable one and the
    ``or 1`` default answer exactly as the float spelling of the level."""
    fn = getattr(server, route)
    body = {"self_spell_ids": [7], "enemy_rune_ids": [8010]}
    assert fn({**body, "level": 11}) == fn({**body, "level": 11.0})
    assert fn({**body, "level": 0}) == fn({**body, "level": 1})
    assert fn({**body, "level": 10 ** 300}) == fn({**body, "level": 1e300})
