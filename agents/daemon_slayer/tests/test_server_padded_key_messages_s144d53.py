"""RM-1275: a 400 names the stripped key; padded duplicates are last-wins.

RM-1242 / RM-1274 strip the dict keys of ``form_index``, ``block_index``,
``augment_stacks`` and ``granter_resists`` in
``agents/daemon_slayer/server.py``. Two follow-ups from the RM-1274 verifier:

* The ``augment_stacks`` and ``form_index`` 400 messages still printed the
  RAW key, so ``{" TapDancer ": "x"}`` answered
  ``augment_stacks. TapDancer : expected number`` - a key that is not the
  one the engine matches. The message now names the stripped key (strip
  only, no case change, so ``form_index[q]`` keeps its existing text).
* A body carrying both ``"W"`` and ``" W "`` (or ``" default "`` beside
  ``"default"``) collapses to one key. The outer spell keys were already
  last-wins with no error (a plain dict comprehension, RM-1242); the
  nested keys follow the same rule. Decision: pin last-wins with tests, no
  new 400 - JSON object key order is the caller's, json.loads itself is
  last-wins for exact duplicates, and a new refusal would change a
  contract that already answers 200. ASCII only.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer.server import (
    _ApiError,
    _opt_augment_stacks,
    _opt_dict,
    _parse_block_index,
    _parse_form_index,
    _strip_granter_keys,
)


@pytest.mark.parametrize("raw", ["x", True, float("inf")])
def test_augment_stacks_400_names_the_stripped_key(raw) -> None:
    with pytest.raises(_ApiError) as exc:
        _opt_augment_stacks({"augment_stacks": {" TapDancer ": raw}})
    assert exc.value.status == 400
    assert exc.value.message.startswith("augment_stacks.TapDancer: ")


def test_form_index_400_names_the_stripped_key() -> None:
    with pytest.raises(_ApiError) as exc:
        _parse_form_index({"form_index": {" q ": 1.5}})
    assert exc.value.message == "form_index[q]: expected integer, got 1.5"


def test_form_index_400_keeps_the_callers_case() -> None:
    # Strip only: the existing RM-1237 / RM-1154 texts stay byte-equal.
    with pytest.raises(_ApiError) as exc:
        _parse_form_index({"form_index": {"q": 1.5}})
    assert exc.value.message == "form_index[q]: expected integer, got 1.5"


def test_form_index_padded_duplicate_is_last_wins() -> None:
    assert _parse_form_index({"form_index": {"W": 0, " w ": 1}}) == {"W": 1}
    assert _parse_form_index({"form_index": {" w ": 1, "W": 0}}) == {"W": 0}


def test_block_index_padded_duplicate_spell_is_last_wins() -> None:
    assert _parse_block_index({"block_index": {"E": 0, " e ": 1}}) == {"E": 1}


def test_block_index_padded_duplicate_condition_is_last_wins() -> None:
    body = {"block_index": {"E": {"default": 0, " default ": 2}}}
    assert _parse_block_index(body) == {"E": {"default": 2}}
    body = {"block_index": {"E": {" default ": 2, "default": 0}}}
    assert _parse_block_index(body) == {"E": {"default": 0}}


def test_augment_stacks_padded_duplicate_is_last_wins() -> None:
    body = {"augment_stacks": {"TapDancer": 1, " TapDancer ": 4}}
    assert _opt_augment_stacks(body) == {"TapDancer": 4.0}


def test_granter_resists_padded_duplicate_is_last_wins() -> None:
    body = {"granter_resists": {"Taric": [1, 1, 1, 1], " Taric ": [2, 2, 2, 2]}}
    assert _strip_granter_keys(_opt_dict(body, "granter_resists")) == {
        "Taric": [2, 2, 2, 2]}
