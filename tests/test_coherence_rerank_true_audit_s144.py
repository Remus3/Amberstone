"""True-audit (s144 cycle 160) of core/build_planner/coherence.py.

coherence_rerank is the carry build-reco chokepoint: every ds.dps carry build
the live client serves (core.daemon_slayer_client) passes through it, and its
rows come from the DS :8860 JSON payload (rank_for), which RC does not author.
Its own docstring promises "the re-rank can never crash". Measured at HEAD
before this fix (RM-1940..RM-1945):

  * an inf delta_dps (or effective_score) row took the TOP slot, and a NaN one
    - an unordered sort key - landed wherever its position put it (first at
    index 0) and scrambled the order of the real rows around it;
  * a non-numeric delta_dps (a drifted "abc" string) raised ValueError out of
    the whole carry reco;
  * a NaN or None kit metric (stat_fit / anti_synergy_penalty) gave a NaN key or
    raised TypeError instead of the documented fall-back to the base;
  * a non-numeric fight_length raised TypeError and a bool True engaged the
    effective_score branch;
  * a float top raised TypeError, a negative top silently served all rows but
    the last and None served every row;
  * rows=None raised TypeError.

Well-formed rows keep the exact order they had (characterized below with the
real Jinx kit data). The module-level kit primitives are patched where a test
needs a deterministic metric; the characterization tests use the real ones.
"""
from __future__ import annotations

import math
from types import SimpleNamespace
from unittest import mock

import pytest

from core.build_planner import coherence as coh
from core.build_planner.coherence import coherence_rerank

_CARRY = "Jinx"


def _row(iid, delta=0.0, eff=0.0):
    return SimpleNamespace(
        item_id=iid, item_name=iid, delta_dps=delta, effective_score=eff,
    )


def _ids(rows):
    return [r.item_id for r in rows]


def _clean_rows():
    return [
        _row("3031", 30.0, 300.0),
        _row("3508", 40.0, 280.0),
        _row("6692", 35.0, 290.0),
        _row("3094", 20.0, 150.0),
        _row("3046", 25.0, 260.0),
    ]


@pytest.fixture
def flat_metric():
    """A carry champ with a zero metric, so the key is the BASE alone."""
    with mock.patch.object(coh, "champ_kit_traits", return_value={"archetype": "carry"}), \
            mock.patch.object(coh, "is_caster_marksman", return_value=False), \
            mock.patch.object(coh, "is_ap_hybrid_marksman", return_value=False), \
            mock.patch.object(coh, "stat_fit", return_value=0.0), \
            mock.patch.object(coh, "anti_synergy_penalty", return_value=0.0):
        yield


# --------------------------------------------------------------------------- #
# Characterization - well-formed rows keep their pre-hardening order.
# --------------------------------------------------------------------------- #
def test_characterize_real_jinx_delta_branch():
    assert _ids(coherence_rerank(_clean_rows(), _CARRY, top=6)) == [
        "3031", "3046", "6692", "3094", "3508",
    ]


def test_characterize_real_jinx_effective_branch():
    got = _ids(coherence_rerank(_clean_rows(), _CARRY, top=6, fight_length=4.0))
    # Essence Reaver (3508) is docked by _MU_EFF below the crit core.
    assert got[0] == "3031"
    assert got[-1] == "3508"


def test_characterize_non_carry_is_a_prefix_slice():
    rows = _clean_rows()
    with mock.patch.object(coh, "champ_kit_traits", return_value={"archetype": "mage"}):
        out = coherence_rerank(rows, "Lux", top=3)
    assert out == rows[:3]
    assert all(a is b for a, b in zip(out, rows))


def test_characterize_coherence_adj_float_on_clean_row():
    adj = coh._coherence_adj(_row("3031", 30.0), _CARRY)
    assert isinstance(adj, float) and math.isfinite(adj)


# --------------------------------------------------------------------------- #
# RM-1940: a non-finite base never takes a slot above a real row and never
# scrambles the real rows' order.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("pos", range(6))
def test_non_finite_delta_sinks_and_keeps_real_order(flat_metric, bad, pos):
    rows = _clean_rows()
    rows.insert(pos, _row("X", bad))
    got = _ids(coherence_rerank(rows, _CARRY, top=10))
    assert got == ["3508", "6692", "3031", "3046", "3094", "X"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_effective_score_sinks(flat_metric, bad):
    rows = [_row("A", 0, 100.0), _row("X", 0, bad), _row("B", 0, 50.0), _row("C", 0, 90.0)]
    got = _ids(coherence_rerank(rows, _CARRY, top=10, fight_length=4.0))
    assert got == ["A", "C", "B", "X"]


# --------------------------------------------------------------------------- #
# RM-1941: a non-numeric base never raises; it sinks like a non-finite one.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", ["abc", [1.0], {"v": 1}, object(), True, b"\xff"])
def test_non_numeric_delta_never_raises_and_sinks(flat_metric, bad):
    rows = _clean_rows() + [_row("X", bad)]
    rows.insert(0, rows.pop())
    got = _ids(coherence_rerank(rows, _CARRY, top=10))
    assert got[-1] == "X"
    assert got[:-1] == ["3508", "6692", "3031", "3046", "3094"]


def test_numeric_string_and_none_delta_unchanged(flat_metric):
    # Pre-hardening float("30") worked and None read as 0.0: both kept.
    rows = [_row("A", "30"), _row("B", None), _row("C", 10.0)]
    assert _ids(coherence_rerank(rows, _CARRY, top=10)) == ["A", "C", "B"]


# --------------------------------------------------------------------------- #
# RM-1942: a non-finite or non-numeric kit metric falls back to the base.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["stat_fit", "anti_synergy_penalty"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), None, "x"])
def test_bad_metric_falls_back_to_base(name, bad):
    with mock.patch.object(coh, "champ_kit_traits", return_value={"archetype": "carry"}), \
            mock.patch.object(coh, "is_caster_marksman", return_value=False), \
            mock.patch.object(coh, "is_ap_hybrid_marksman", return_value=False), \
            mock.patch.object(coh, "stat_fit", return_value=0.0), \
            mock.patch.object(coh, "anti_synergy_penalty", return_value=0.0), \
            mock.patch.object(coh, name, return_value=bad):
        adj = coh._coherence_adj(_row("3031", 30.0), _CARRY)
        got = _ids(coherence_rerank(_clean_rows(), _CARRY, top=10))
    assert adj == 30.0
    assert got == ["3508", "6692", "3031", "3046", "3094"]


def test_overflowing_adjustment_falls_back_to_base():
    with mock.patch.object(coh, "stat_fit", return_value=1e308), \
            mock.patch.object(coh, "anti_synergy_penalty", return_value=0.0):
        adj = coh._coherence_adj(_row("3031", 1e308), _CARRY)
    assert adj == 1e308


# --------------------------------------------------------------------------- #
# RM-1943: a junk fight_length never raises and never engages the
# effective_score branch; only a real finite positive number does.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", ["5", [4.0], object(), True, float("nan"), float("inf")])
def test_junk_fight_length_uses_delta_branch(flat_metric, bad):
    rows = [_row("A", 10.0, 1.0), _row("B", 5.0, 999.0)]
    assert _ids(coherence_rerank(rows, _CARRY, top=10, fight_length=bad)) == ["A", "B"]


def test_real_fight_length_engages_effective_branch(flat_metric):
    rows = [_row("A", 10.0, 1.0), _row("B", 5.0, 999.0)]
    assert _ids(coherence_rerank(rows, _CARRY, top=10, fight_length=4)) == ["B", "A"]


# --------------------------------------------------------------------------- #
# RM-1944: a junk top never raises and never reads a negative as "all but
# the last" or None as "everything".
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("top,want", [
    (3.0, 3), (-1, 0), (-100, 0), (0, 0), (None, 6), ("3", 6), (True, 6),
    (float("nan"), 6), (float("inf"), 6), (2.5, 6), (100, 7),
])
@pytest.mark.parametrize("carry", [True, False])
def test_junk_top_is_normalized(flat_metric, top, want, carry):
    rows = _clean_rows() + [_row("F", 1.0), _row("G", 0.5)]
    if carry:
        out = coherence_rerank(rows, _CARRY, top=top)
    else:
        with mock.patch.object(coh, "champ_kit_traits", return_value={"archetype": "tank"}):
            out = coherence_rerank(rows, "Ornn", top=top)
    assert len(out) == want


# --------------------------------------------------------------------------- #
# RM-1945: rows that are not a row list never raise.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [None, 5, "3031", b"3031", {"3031": 1}])
def test_non_list_rows_return_empty(flat_metric, bad):
    assert coherence_rerank(bad, _CARRY, top=6) == []


def test_generator_rows_still_accepted(flat_metric):
    got = _ids(coherence_rerank((r for r in _clean_rows()), _CARRY, top=2))
    assert got == ["3508", "6692"]
