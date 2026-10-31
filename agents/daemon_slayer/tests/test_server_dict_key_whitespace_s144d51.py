"""RM-1242: ``form_index`` / ``block_index`` strip their spell keys.

``_parse_form_index`` and ``_parse_block_index`` in
``agents/daemon_slayer/server.py`` normalised each key with
``str(k).upper()`` and no strip. Measured on the live server (ENGINE
1.290.0, patch 16.21.1), POST /ability-dps at level 11:

* Jayce ``form_index {"W": 1}`` scored W at form 1; ``{" w ": 1}`` scored W
  at form 0 and echoed ``form_index_resolved {"Q": 1, " W ": 1}`` with
  ``form_index_source "override"`` - the override silently missed and the
  echo read as acknowledgement;
* Cassiopeia ``block_index {" E ": 1}`` left a dead ``" E "`` key beside the
  registry's ``E`` entry.

Policy, chosen to invent nothing: it is ``_opt_str``'s and RM-1239's
(``max_priority`` strips its string form) - the key is stripped, then
upper-cased, so a padded key is the key it names. Values are untouched: a
non-integer form rank is still a 400, a malformed block index is still
skipped (the field's pinned no-500 contract). ASCII only.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer.server import (
    _ApiError,
    _parse_block_index,
    _parse_form_index,
)

_PADDED = [" w ", "W ", " w", "\tW\n", "w"]


@pytest.mark.parametrize("key", _PADDED)
def test_form_index_padded_key_is_the_key(key) -> None:
    assert _parse_form_index({"form_index": {key: 1}}) == {"W": 1}


@pytest.mark.parametrize("key", _PADDED)
def test_block_index_padded_scalar_key_is_the_key(key) -> None:
    assert _parse_block_index({"block_index": {key: 1}}) == {"W": 1}


def test_block_index_padded_key_keeps_list_and_conditional_values() -> None:
    body = {"block_index": {
        " e ": [0, 1],
        "r\t": {"default": 1, "target_no_setup": 0},
    }}
    assert _parse_block_index(body) == {
        "E": [0, 1],
        "R": {"default": 1, "target_no_setup": 0},
    }


@pytest.mark.parametrize(
    "body, expected",
    [({}, None), ({"form_index": None}, None),
     ({"form_index": {}}, {}),
     ({"form_index": {"q": 2, "R": 0}}, {"Q": 2, "R": 0})],
)
def test_form_index_existing_forms_are_unchanged(body, expected) -> None:
    assert _parse_form_index(body) == expected


def test_form_index_value_errors_still_name_the_raw_key() -> None:
    with pytest.raises(_ApiError) as exc:
        _parse_form_index({"form_index": {" W ": "x"}})
    assert exc.value.status == 400
    assert "expected integer" in exc.value.message


def test_block_index_malformed_value_still_skipped() -> None:
    body = {"block_index": {" E ": "x", " Q ": 1.5, "W": 0}}
    assert _parse_block_index(body) == {"W": 0}


@pytest.fixture(scope="module")
def _loaded_cache():
    """Install the on-disk snapshot for the route handler, then restore
    whatever the cache held so no other module sees this one's state."""
    from agents.daemon_slayer import server
    from agents.daemon_slayer.data_loader import DataSnapshot

    prior = server._CACHE._snap
    server._CACHE.set(DataSnapshot.load())
    yield
    server._CACHE._snap = prior


def _jayce_forms(form_index) -> tuple[dict, dict]:
    from agents.daemon_slayer.server import _route_ability_dps

    out = _route_ability_dps(
        {"champion": "Jayce", "level": 11, "form_index": form_index})
    forms = {s["key"]: s["form_index"] for s in out["per_spell"]}
    return out["form_index_resolved"], forms


@pytest.mark.usefixtures("_loaded_cache")
def test_route_form_index_padded_key_reaches_the_engine() -> None:
    # Positive control: W=1 really moves W off form 0, so the padded case
    # below is the key being read, not two defaults agreeing.
    plain_resolved, plain_forms = _jayce_forms({"W": 1})
    _, zero_forms = _jayce_forms({"W": 0})
    assert plain_forms["W"] == 1 and zero_forms["W"] == 0
    padded_resolved, padded_forms = _jayce_forms({" w ": 1})
    assert padded_forms["W"] == 1
    assert padded_resolved == plain_resolved
    assert not any(k != k.strip() for k in padded_resolved)
