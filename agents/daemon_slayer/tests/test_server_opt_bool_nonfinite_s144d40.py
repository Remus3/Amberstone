"""RM-1155: a non-finite number in a boolean body key falls back to the default.

``json.loads`` accepts the bare ``NaN`` / ``Infinity`` / ``-Infinity`` tokens
by default, and an ordinary literal such as ``1e400`` overflows to ``inf``
while being parsed. ``_opt_bool`` in ``agents/daemon_slayer/server.py`` coerced
every number with ``bool(v)``, and ``bool(float("nan"))`` is True, so
``{"assume_kaenic_shield": NaN}`` ARMED a DEFAULT-OFF seam and the route
answered a well-formed 200 for a question the caller never asked.

Policy, chosen to invent nothing: ``_opt_bool``'s own pinned contract
(``test_per_item_shield_route_seams_rm118.py``,
``test_the_string_and_int_forms_follow_the_shared_opt_bool_contract``) is
"garbage falls back OFF" - a malformed value collapses to the caller's
default so the body stays byte-identical rather than silently armed. A
non-finite number is garbage under that contract. A 400 was the alternative
(the numeric helpers' non-finite policy); it was not taken because it would
give ``_opt_bool`` a second, stricter garbage rule that every other garbage
value does not follow.

Finite numbers keep their existing meaning (``0`` OFF, any other finite
number ON). ASCII only.
"""
from __future__ import annotations

import json
import math

import pytest

from agents.daemon_slayer import server
from agents.daemon_slayer.server import _opt_bool

_NONFINITE = (float("nan"), float("inf"), float("-inf"))


@pytest.mark.parametrize("value", _NONFINITE, ids=["nan", "inf", "-inf"])
@pytest.mark.parametrize("default", [False, True])
def test_non_finite_number_takes_the_default(value, default) -> None:
    assert _opt_bool({"k": value}, "k", default) is default


@pytest.mark.parametrize(
    "raw", ['{"k": NaN}', '{"k": Infinity}', '{"k": -Infinity}', '{"k": 1e400}']
)
def test_the_json_token_paths_reach_the_default(raw) -> None:
    """The values above, produced the way the HTTP handler produces them."""
    body = json.loads(raw)
    assert not math.isfinite(body["k"])
    assert _opt_bool(body, "k", False) is False
    assert _opt_bool(body, "k", True) is True


@pytest.mark.parametrize(
    "value, expected",
    [(True, True), (False, False), (1, True), (0, False), (0.0, False),
     (2.5, True), (-1, True), ("true", True), ("on", True), ("nope", False),
     ("", False), (None, False), ([], False)],
)
def test_finite_and_existing_forms_are_unchanged(value, expected) -> None:
    assert _opt_bool({"k": value}, "k", False) is expected


def test_absent_key_takes_the_default() -> None:
    assert _opt_bool({}, "k", False) is False
    assert _opt_bool({}, "k", True) is True


@pytest.fixture(scope="module")
def _loaded_cache():
    """Install the on-disk snapshot for the route handler, then restore
    whatever the cache held so no other module sees this one's state."""
    from agents.daemon_slayer.data_loader import DataSnapshot

    prior = server._CACHE._snap
    server._CACHE.set(DataSnapshot.load())
    yield
    server._CACHE._snap = prior


def _ehp_body(**extra) -> dict:
    # Probe hygiene: a realistic build carrying the seam's item (Kaenic
    # Rookern 2504) plus two unrelated completed items, never an empty build.
    body = {
        "champion": "Malphite",
        "level": 13,
        "items": ["2504", "3068", "3047"],
        "mode": "SR",
        "enemy_ad_share": 0.5,
        "enemy_ap_share": 0.5,
    }
    body.update(extra)
    return body


@pytest.mark.usefixtures("_loaded_cache")
@pytest.mark.parametrize("raw_token", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_token_does_not_arm_an_ehp_seam(raw_token) -> None:
    seam = "assume_kaenic_shield"
    off = server._route_ehp(_ehp_body())
    armed = server._route_ehp(_ehp_body(**{seam: True}))
    # Positive control: the seam really moves the route, so OFF == the
    # garbage result is a real assertion and not a seam that never fires.
    assert armed != off
    body = _ehp_body(**json.loads(f'{{"{seam}": {raw_token}}}'))
    assert server._route_ehp(body) == off
