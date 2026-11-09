"""S144-D-154..156: the carry ranker's opt-in knobs never go non-finite.

Measured at HEAD (Python level only - the HTTP routes parse fight_length and
kit_conversion_strength with ``server._opt_float``, which already refuses a
non-finite token, and no route parses mana_value_per_point):

* S144-D-154: ``rank_items(fight_length=+inf)`` engaged the burst reweight
  because ``inf > 0.0``. ``effective_score = burst_gain + delta * inf`` is then
  +inf for a positive delta, -inf for a negative one and NaN for a zero delta,
  so the rows carry non-finite scores and the NaN rows break the sort order.
  The docstring treats a non-positive value as ``None``; a non-finite one is
  just as meaningless and now takes the same default path.
* S144-D-155: ``rank_items(mana_value_per_point=+inf)`` did the same through
  ``mana_adjusted_score = delta + inf * mana_gained`` (NaN at zero mana).
* S144-D-156: ``kit_conversion.conversion_factor`` promises a multiplier in
  [0, 1] that is "Never above 1.0", but each channel term
  ``1 - strength * exposure * shortfall`` goes negative once strength > 1, and
  two negative terms multiply back to a positive factor that can exceed 1.0
  (strength 3 on two full channels gave 4.0; strength +inf gave +inf). A
  negative-score factor RAISES a row's sort key, the opposite of the gate. Each
  term now floors at 0.0: byte-identical for every strength in [0, 1], and the
  five rankers that share the factor (rank, _rank_mage, burst, ehp, hybrid)
  inherit the bound.
"""

from __future__ import annotations

import math

import pytest

from agents.daemon_slayer import kit_conversion as kc
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import rank_items

_CHAMP = "Caitlyn"
_MANA_CHAMP = "Ziggs"
_LEVEL = 11
_ARMOR = 100.0


@pytest.fixture(scope="module")
def snap():
    return DataSnapshot.load()


def _rows(snap, champ, **kw):
    return rank_items(
        snap, champion_id=champ, level=_LEVEL, mode="SR",
        target_armor=_ARMOR, top_n=200, **kw,
    ).ranked


def _sig(rows):
    return [
        (r.item_id, r.delta_dps, r.effective_score, r.mana_adjusted_score)
        for r in rows
    ]


# ---------------------------------------------------------------------------
# S144-D-154 - fight_length
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan])
def test_nonfinite_fight_length_is_the_default_ranking(snap, bad):
    assert _sig(_rows(snap, _CHAMP, fight_length=bad)) == _sig(_rows(snap, _CHAMP))


def test_infinite_fight_length_leaves_every_row_finite(snap):
    for r in _rows(snap, _CHAMP, fight_length=math.inf):
        assert math.isfinite(r.effective_score), r.item_id
        assert math.isfinite(r.delta_dps), r.item_id


def test_finite_fight_length_still_engages_the_reweight(snap):
    rows = _rows(snap, _CHAMP, fight_length=5.0)
    assert any(r.effective_score != 0.0 for r in rows)


# ---------------------------------------------------------------------------
# S144-D-155 - mana_value_per_point
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan])
def test_nonfinite_mana_value_is_the_default_ranking(snap, bad):
    assert (
        _sig(_rows(snap, _MANA_CHAMP, mana_value_per_point=bad))
        == _sig(_rows(snap, _MANA_CHAMP))
    )


def test_infinite_mana_value_leaves_every_row_finite(snap):
    for r in _rows(snap, _MANA_CHAMP, mana_value_per_point=math.inf):
        assert math.isfinite(r.mana_adjusted_score), r.item_id


def test_finite_mana_value_still_engages(snap):
    rows = _rows(snap, _MANA_CHAMP, mana_value_per_point=0.02)
    assert any(r.mana_adjusted_score != 0.0 for r in rows)


# ---------------------------------------------------------------------------
# S144-D-156 - conversion_factor stays in [0, 1]
# ---------------------------------------------------------------------------

_ZERO = kc.KitConversion(attack_speed=0.0, crit=0.0, on_hit=0.0, off_axis_stat=0.0)


def _two_full_channels(monkeypatch):
    def fake(item_id, rec, objective):
        return {"attack_speed": 1.0, "crit": 1.0, "on_hit": 0.0, "off_axis_stat": 0.0}

    monkeypatch.setattr(kc, "item_exposures", fake)


@pytest.mark.parametrize("strength", [1.5, 2.0, 3.0, 10.0, 1e300, math.inf])
def test_conversion_factor_never_leaves_unit_interval(monkeypatch, strength):
    _two_full_channels(monkeypatch)
    f = kc.conversion_factor(_ZERO, "x", {}, strength, "ad")
    assert 0.0 <= f <= 1.0
    # Past strength 1 a fully exposed, fully non-converting channel is gone.
    assert f == 0.0


@pytest.mark.parametrize("strength", [0.0, 0.25, 0.5, 1.0])
def test_conversion_factor_in_design_range_is_unchanged(monkeypatch, strength):
    _two_full_channels(monkeypatch)
    expected = (1.0 - strength) * (1.0 - strength)
    assert kc.conversion_factor(_ZERO, "x", {}, strength, "ad") == expected


@pytest.mark.parametrize("strength", [0.3, 1.0, 2.5, 7.0, math.inf])
def test_conversion_factor_bounded_over_the_real_registry(snap, strength):
    for champ, conv in kc._KIT_CONVERSION.items():
        objective = kc.damage_objective(snap, champ)
        for iid, rec in snap.items.items():
            f = kc.conversion_factor(conv, iid, rec, strength, objective)
            assert 0.0 <= f <= 1.0, (champ, iid, strength, f)
