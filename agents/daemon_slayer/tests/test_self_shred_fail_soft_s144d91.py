"""S144-D-91 - pin ``compute_self_shred_uplift``'s fail-soft and selection rules.

The docstring promises a 0.0-uplift result with a note, never a raise, when the
snapshot is unavailable, the champion is unknown or the snapshot is
degenerate, and says the source with the largest mitigation-factor gain wins.
``test_self_shred.py`` reaches the unknown and blank champion branches through
the real snapshot only; the snapshot-load failure, the non-AbilitiesNotFound
lookup failure, the empty / non-dict ability map, the "no candidates" note,
selection by percent gain (not by absolute DPS), the first-wins tie, the
negative-resist clamp, the level coercion and the rank used for the magnitude
had no test.

Every test passes a stub snapshot (or patches ``load_default``), so no real
abilities data is read. Synthetic champion ids only.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.daemon_slayer import self_shred as ss
from agents.daemon_slayer.abilities import AbilitiesNotFound
from agents.daemon_slayer.dps import _armor_factor


class _Snap:
    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc
        self.calls = []

    def get_abilities(self, champion):
        self.calls.append(champion)
        if self._exc is not None:
            raise self._exc
        return self._result


def _shred(attribute="Armor Reduction", values=(10, 20, 30, 40, 50),
           units=("",), damage_type="PHYSICAL"):
    blk = SimpleNamespace(
        attribute=attribute, attribute_kind="modifier",
        raw_modifiers=({"values": list(values), "units": list(units)},),
    )
    return (SimpleNamespace(damage_blocks=(blk,), damage_type=damage_type),)


def _assert_zero(r, champion, level, note_fragment):
    assert r.champion == champion
    assert r.level == level
    assert r.shred_source == ""
    assert r.resist_kind == ""
    assert (r.flat_shred, r.pct_shred, r.target_resist) == (0.0, 0.0, 0.0)
    assert (r.old_mit_factor, r.new_mit_factor) == (0.0, 0.0)
    assert (r.dps_uplift_pct, r.dps_uplift_abs) == (0.0, 0.0)
    assert note_fragment in r.notes


# ---- fail-soft branches --------------------------------------------------

def test_snapshot_load_failure_is_a_zero_result(monkeypatch):
    def boom():
        raise RuntimeError("disk gone")

    monkeypatch.setattr(ss, "load_default", boom)
    r = ss.compute_self_shred_uplift("Synth", 9, 100.0, 50.0, 200.0, 0.0)
    _assert_zero(r, "Synth", 9, "abilities snapshot unavailable (RuntimeError)")


def test_load_default_is_not_called_when_a_snapshot_is_passed(monkeypatch):
    def boom():
        raise AssertionError("load_default must not run")

    monkeypatch.setattr(ss, "load_default", boom)
    snap = _Snap(result={"E": _shred()})
    r = ss.compute_self_shred_uplift("Synth", 9, 100.0, 50.0, 200.0, snapshot=snap)
    assert r.shred_source == "Synth:E"
    assert snap.calls == ["Synth"]


def test_unknown_champion_is_a_zero_result():
    snap = _Snap(exc=AbilitiesNotFound("missing"))
    r = ss.compute_self_shred_uplift("Synth", 5, 100.0, 50.0, snapshot=snap)
    _assert_zero(r, "Synth", 5, "not in abilities snapshot")


@pytest.mark.parametrize("exc", [KeyError("x"), ValueError("bad"), TypeError("t")])
def test_any_other_lookup_failure_is_a_zero_result(exc):
    snap = _Snap(exc=exc)
    r = ss.compute_self_shred_uplift("Synth", 5, 100.0, 50.0, snapshot=snap)
    _assert_zero(r, "Synth", 5, f"ability lookup failed ({type(exc).__name__})")


@pytest.mark.parametrize("result", [{}, None, [], ("E",)])
def test_empty_or_non_dict_ability_map_is_a_zero_result(result):
    snap = _Snap(result=result)
    r = ss.compute_self_shred_uplift("Synth", 5, 100.0, 50.0, snapshot=snap)
    _assert_zero(r, "Synth", 5, "no ability forms for 'Synth'")


def test_no_shred_candidate_is_a_zero_result():
    snap = _Snap(result={"Q": _shred(attribute="Attack Damage Reduction")})
    r = ss.compute_self_shred_uplift("Synth", 5, 100.0, 50.0, snapshot=snap)
    _assert_zero(r, "Synth", 5, "has no armor/MR target_shred ability")


@pytest.mark.parametrize("champion", ["", "   ", None])
def test_blank_champion_never_touches_the_snapshot(champion):
    snap = _Snap(exc=AssertionError("must not be called"))
    r = ss.compute_self_shred_uplift(champion, 5, 100.0, 50.0, snapshot=snap)
    _assert_zero(r, "", 5, "blank champion id")
    assert snap.calls == []


def test_champion_id_is_stripped_before_lookup():
    snap = _Snap(result={"E": _shred()})
    r = ss.compute_self_shred_uplift("  Synth  ", 9, 100.0, 50.0, snapshot=snap)
    assert snap.calls == ["Synth"]
    assert r.champion == "Synth"
    assert r.shred_source == "Synth:E"


# ---- level coercion and rank ---------------------------------------------

@pytest.mark.parametrize(
    ("level", "expected"),
    [("abc", 1), (None, 1), (0, 1), (-4, 1), ("7", 7), (7.9, 7), (18, 18)],
)
def test_level_is_coerced_and_floored_at_one(level, expected):
    snap = _Snap(result={"E": _shred()})
    r = ss.compute_self_shred_uplift("Synth", level, 100.0, 50.0, snapshot=snap)
    assert r.level == expected


@pytest.mark.parametrize(
    ("level", "flat"),
    [(1, 10.0), (2, 10.0), (3, 20.0), (8, 40.0), (9, 50.0), (18, 50.0)],
)
def test_magnitude_comes_from_the_rank_the_level_supports(level, flat):
    snap = _Snap(result={"E": _shred()})
    r = ss.compute_self_shred_uplift("Synth", level, 100.0, 50.0, snapshot=snap)
    assert r.flat_shred == flat


def test_a_three_rank_ult_clamps_to_its_last_rank():
    snap = _Snap(result={"R": _shred(values=(5, 10, 15))})
    r = ss.compute_self_shred_uplift("Synth", 18, 100.0, 50.0, snapshot=snap)
    assert r.flat_shred == 15.0


# ---- math and selection --------------------------------------------------

def test_flat_armor_shred_math():
    snap = _Snap(result={"E": _shred()})
    r = ss.compute_self_shred_uplift("Synth", 9, 100.0, 50.0, 200.0, 999.0,
                                     snapshot=snap)
    old, new = _armor_factor(100.0), _armor_factor(50.0)
    assert r.resist_kind == ss.RESIST_ARMOR
    assert r.target_resist == 100.0
    assert r.old_mit_factor == pytest.approx(old)
    assert r.new_mit_factor == pytest.approx(new)
    assert r.dps_uplift_pct == pytest.approx((new / old - 1.0) * 100.0)
    # Armor shred scales the PHYSICAL channel only.
    assert r.dps_uplift_abs == pytest.approx(200.0 * (new / old - 1.0))


def test_selection_is_by_percent_gain_not_by_absolute_dps():
    # Armor: 10 flat off 100 -> small gain on a big physical channel.
    # MR: 50% off 100 -> bigger gain on a zero magic channel. MR wins.
    snap = _Snap(result={
        "Q": _shred(values=(10,)),
        "W": _shred(attribute="Magic Resistance Reduction", values=(50,),
                    units=("%",), damage_type="MAGIC"),
    })
    r = ss.compute_self_shred_uplift("Synth", 1, 100.0, 100.0, 5000.0, 0.0,
                                     snapshot=snap)
    assert r.shred_source == "Synth:W"
    assert r.resist_kind == ss.RESIST_MR
    assert r.pct_shred == 0.5
    assert r.dps_uplift_pct > 0.0
    assert r.dps_uplift_abs == 0.0


def test_equal_gain_keeps_the_first_candidate():
    snap = _Snap(result={"Q": _shred(values=(20,)), "E": _shred(values=(20,))})
    r = ss.compute_self_shred_uplift("Synth", 1, 100.0, 50.0, 100.0,
                                     snapshot=snap)
    assert r.shred_source == "Synth:Q"


def test_negative_target_resist_never_yields_a_negative_uplift():
    snap = _Snap(result={"E": _shred(values=(50,), units=("%",))})
    r = ss.compute_self_shred_uplift("Synth", 1, -20.0, 50.0, 300.0,
                                     snapshot=snap)
    assert r.target_resist == -20.0
    assert r.new_mit_factor == pytest.approx(_armor_factor(0.0))
    assert r.dps_uplift_pct == 0.0
    assert r.dps_uplift_abs == 0.0


def test_result_round_trips_through_to_dict():
    snap = _Snap(result={"E": _shred()})
    r = ss.compute_self_shred_uplift("Synth", 9, 100.0, 50.0, 200.0,
                                     snapshot=snap)
    d = r.to_dict()
    assert ss.SelfShredUplift(**d) == r
