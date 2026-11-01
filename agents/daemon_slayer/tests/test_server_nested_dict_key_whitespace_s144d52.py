"""RM-1274: the nested / keyed-by-name dict keys strip like the spell keys.

RM-1242 stripped the spell keys of ``form_index`` / ``block_index``. Three
keys in ``agents/daemon_slayer/server.py`` still matched on the raw string.
Measured on the live server (ENGINE 1.290.0, patch 16.21.1):

* POST /ability-dps Cassiopeia level 11 ``block_index {"E": {"default": 0}}``
  scored E at 100 raw damage per cast; ``{"E": {" default ": 0}}`` failed
  the "must carry default" check, so the entry was skipped and E fell back
  to the registry's default block (168 raw) while ``block_index_source``
  still read ``"override"``. A padded condition key (``" target_no_setup "``)
  skipped the whole entry the same way.
* POST /ally-protected-ehp Garen level 11 with ally Taric:
  ``granter_resists {"Taric": [300, 200, 40, 30]}`` gave
  ``ally_grant_armor 24.0``; ``{" Taric ": ...}`` gave 0.0. The ally list is
  stripped by ``_coerce_str_list``, the dict key was not, so the lookup
  missed and Taric's percent-of-resist grant silently read as absent.
* ``augment_stacks {" TapDancer ": n}`` misses the engine's exact
  ``TAP_DANCER`` lookup (``augments.py``) while the ``augments`` list entry
  is stripped, so the assumed stack count silently replaced the caller's.

Policy, chosen to invent nothing: strip only (``_opt_str`` / RM-1239 /
RM-1242). No case change: condition keys, DDragon champion ids and augment
apiNames are case-sensitive, so a wrong-case key keeps missing as before.
Values are untouched. ASCII only.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer.server import (
    _ApiError,
    _opt_augment_stacks,
    _opt_dict,
    _parse_block_index,
    _strip_granter_keys,
)


def _parse_granter_resists(body: dict):
    # The route's own composition (``_route_ally_protected_ehp``).
    return _strip_granter_keys(_opt_dict(body, "granter_resists"))

_PAD = [" {} ", "{} ", " {}", "\t{}\n"]


@pytest.mark.parametrize("pad", _PAD)
def test_block_index_padded_default_key_is_default(pad) -> None:
    body = {"block_index": {"E": {pad.format("default"): 0}}}
    assert _parse_block_index(body) == {"E": {"default": 0}}


@pytest.mark.parametrize("pad", _PAD)
def test_block_index_padded_condition_key_is_the_condition(pad) -> None:
    body = {"block_index": {"E": {
        "default": 1, pad.format("target_no_setup"): [0, 1]}}}
    assert _parse_block_index(body) == {
        "E": {"default": 1, "target_no_setup": [0, 1]}}


def test_block_index_condition_keys_stay_case_sensitive() -> None:
    # Unknown / wrong-case condition keys still skip the entry (unchanged).
    for bad in ({"Default": 0}, {"default": 0, "Target_No_Setup": 1},
                {"default": 0, "bogus": 1}, {" ": 0}):
        assert _parse_block_index({"block_index": {"E": bad}}) == {}


def test_block_index_malformed_nested_value_still_skipped() -> None:
    body = {"block_index": {"E": {" default ": "x"}, "W": 0}}
    assert _parse_block_index(body) == {"W": 0}


@pytest.mark.parametrize("pad", _PAD)
def test_granter_resists_padded_key_is_the_champion(pad) -> None:
    body = {"granter_resists": {pad.format("Taric"): [300, 200, 40, 30]}}
    assert _parse_granter_resists(body) == {"Taric": [300, 200, 40, 30]}


@pytest.mark.parametrize(
    "body, expected",
    [({}, None), ({"granter_resists": None}, None),
     ({"granter_resists": {}}, {}),
     ({"granter_resists": {"taric": [1]}}, {"taric": [1]})],
)
def test_granter_resists_existing_forms_unchanged(body, expected) -> None:
    assert _parse_granter_resists(body) == expected


def test_granter_resists_non_object_is_still_a_400() -> None:
    with pytest.raises(_ApiError) as exc:
        _parse_granter_resists({"granter_resists": ["Taric"]})
    assert exc.value.status == 400


@pytest.mark.parametrize("pad", _PAD)
def test_augment_stacks_padded_key_is_the_api_name(pad) -> None:
    body = {"augment_stacks": {pad.format("TapDancer"): 3}}
    assert _opt_augment_stacks(body) == {"TapDancer": 3.0}


def test_augment_stacks_case_and_value_errors_unchanged() -> None:
    assert _opt_augment_stacks({"augment_stacks": {"tapdancer": 2}}) == {
        "tapdancer": 2.0}
    with pytest.raises(_ApiError) as exc:
        _opt_augment_stacks({"augment_stacks": {" TapDancer ": "x"}})
    assert exc.value.status == 400


@pytest.fixture(scope="module")
def _loaded_cache():
    """Install the on-disk snapshot for the route handlers, then restore
    whatever the cache held so no other module sees this one's state."""
    from agents.daemon_slayer import server
    from agents.daemon_slayer.data_loader import DataSnapshot

    prior = server._CACHE._snap
    server._CACHE.set(DataSnapshot.load())
    yield
    server._CACHE._snap = prior


def _cassio_e_raw(block_index) -> float:
    from agents.daemon_slayer.server import _route_ability_dps

    out = _route_ability_dps(
        {"champion": "Cassiopeia", "level": 11, "block_index": block_index})
    (e,) = [s for s in out["per_spell"] if s["key"] == "E"]
    return e["raw_damage_per_cast"]


@pytest.mark.usefixtures("_loaded_cache")
def test_route_block_index_padded_default_reaches_the_engine() -> None:
    # Positive control: default 0 vs default 1 really move E, so the padded
    # case is the key being read, not two registry fallbacks agreeing.
    zero = _cassio_e_raw({"E": {"default": 0}})
    one = _cassio_e_raw({"E": {"default": 1}})
    assert zero != one
    assert _cassio_e_raw({"E": {" default ": 0}}) == zero


def _taric_grant_armor(granter_resists) -> float:
    from agents.daemon_slayer.server import _route_ally_protected_ehp

    out = _route_ally_protected_ehp({
        "champion": "Garen", "level": 11,
        "ally_grant_champions": ["Taric"],
        "granter_resists": granter_resists})
    return out["ally_grant_armor"]


@pytest.mark.usefixtures("_loaded_cache")
def test_route_granter_resists_padded_key_reaches_the_engine() -> None:
    row = [300, 200, 40, 30]
    plain = _taric_grant_armor({"Taric": row})
    assert plain > _taric_grant_armor(None)  # positive control
    assert _taric_grant_armor({" Taric ": row}) == plain
