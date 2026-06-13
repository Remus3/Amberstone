"""P2-W2 DS-C audit (cycle 11) - regression tests for the slice findings.

Scope: agents/daemon_slayer/ability_hps.py NaN/inf boundary guard.

FIX-NOW under test
------------------
``ability_hps._value_at_rank`` is the single chokepoint every heal/shield
block ``values`` entry flows through (flat terms, percent terms, and the
rank-indexed reads in ``_eval_heal_shield_block``). Its prior
``try/except (TypeError, ValueError)`` did NOT reject non-finite values
because ``float("nan")`` / ``float("inf")`` succeed rather than raise. A
malformed scraped value would therefore propagate a NaN / inf through
``heal_per_cast`` -> ``heal_per_sec`` -> ``total_ability_hps`` -> the
``to_dict`` payload, which ``json.dumps`` emits as a bare ``NaN`` /
``Infinity`` token (invalid JSON the dashboard ``JSON.parse`` rejects -
standing finding class 1). The guard floors non-finite reads to 0.0,
matching the existing unparseable-value behavior.

These tests FAIL on the pre-fix code (NaN/inf leaked) and PASS on the
guarded code. Self-contained: ``_value_at_rank`` is a pure helper and
``_eval_heal_shield_block`` is exercised with a minimal SimpleNamespace
block stub (it reads only ``.raw_modifiers`` plus the optional
``.level_scaled`` / ``.bilinear_terms`` attributes - confirmed via the
function body at ability_hps.py lines 289-324).
"""

import math
import json
from types import SimpleNamespace

import pytest

from agents.daemon_slayer.ability_hps import (
    _eval_heal_shield_block,
    _value_at_rank,
)


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", float("nan"), float("inf"), float("-inf")])
def test_value_at_rank_rejects_non_finite(bad):
    """NaN / +-inf (string or float form) floor to 0.0, not leak through."""
    out = _value_at_rank([bad], 0)
    assert out == 0.0
    assert math.isfinite(out)


def test_value_at_rank_preserves_finite_and_clamp():
    """The guard must not regress the finite / clamp / empty contract."""
    assert _value_at_rank([2.5], 0) == 2.5
    # rank past the end clamps to the last element (unchanged behavior).
    assert _value_at_rank([1.0, 2.0, 3.0], 9) == 3.0
    # negative rank reads element 0 (unchanged behavior).
    assert _value_at_rank([7.0, 8.0], -1) == 7.0
    # empty list -> 0.0 (unchanged behavior).
    assert _value_at_rank([], 0) == 0.0


def test_eval_block_flat_nan_does_not_propagate():
    """A NaN flat-term value must not poison the accumulated heal total."""
    block = SimpleNamespace(raw_modifiers=[{"values": [float("nan")], "units": [""]}])
    total, unresolved = _eval_heal_shield_block(block, 0, SimpleNamespace(ap=0.0))
    assert math.isfinite(total)
    assert total == 0.0


def test_eval_block_inf_percent_term_does_not_propagate():
    """An inf percent-term value must not produce a non-finite product."""
    # unit "ability power" maps into ctx.ap via _HEAL_UNIT_TO_CTX; an inf
    # value would otherwise yield (inf/100)*ap = inf. The guard zeroes it.
    block = SimpleNamespace(
        raw_modifiers=[{"values": [float("inf")], "units": ["ability power"]}]
    )
    total, _ = _eval_heal_shield_block(block, 0, SimpleNamespace(ap=200.0))
    assert math.isfinite(total)
    assert total == 0.0


def test_eval_block_result_is_json_safe():
    """The guarded total must serialize under strict (allow_nan=False) JSON.

    This is the concrete dashboard-parse hazard: json.dumps(..., allow_nan=
    False) raises ValueError on a bare NaN/Infinity token, which is exactly
    what JSON.parse rejects in the browser. A finite total serializes clean.
    """
    block = SimpleNamespace(
        raw_modifiers=[
            {"values": [float("nan")], "units": [""]},
            {"values": [3.0], "units": [""]},
        ]
    )
    total, _ = _eval_heal_shield_block(block, 0, SimpleNamespace(ap=0.0))
    # NaN term zeroed, finite term kept -> total == 3.0 and JSON-safe.
    assert total == 3.0
    json.dumps({"heal_per_cast": total}, allow_nan=False)  # must not raise
