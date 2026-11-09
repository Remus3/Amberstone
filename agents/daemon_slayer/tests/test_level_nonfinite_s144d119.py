"""S144-D-119..122 - the DS level-taking public surfaces never raise on a
non-finite or junk level, and read +inf as level 18 and -inf as level 1 (the
convention S144-D-112 / S144-D-115 set for the rune grants and rune procs).

Measured at HEAD before the fix (direct calls on the real snapshot):
  * spike_markers.compute_spike_markers raised OverflowError at level=+-inf
    (``_clamp_level`` did ``int(inf)``) and at item_count_done=+-inf
    (S144-D-119).
  * fight_report.compute_fight_report, documented "NEVER raises", raised
    OverflowError at level=+-inf (S144-D-120).
  * self_shred.compute_self_shred_uplift, documented "NEVER raises", raised
    OverflowError at level=+-inf (S144-D-121).
  * combo.compute_combo and mana_sim.compute_mana_bounded_combo, both
    documented fail-soft, raised OverflowError at level=+-inf, ValueError at
    level=nan / "x" and TypeError at level=None - every ``int(level)`` site
    was outside the fail-soft wrap (S144-D-122).

Junk and NaN read as level 1, the same as fight_report / self_shred /
spike_markers already did for a non-integer level. Every int-convertible level
is byte-identical: finite out-of-range levels are NOT newly clamped in combo /
mana_sim (the burst walker's own range note still answers them).
"""

from __future__ import annotations

import math

import pytest

from agents.daemon_slayer import combo as cb
from agents.daemon_slayer import fight_report as fr
from agents.daemon_slayer import mana_sim as ms
from agents.daemon_slayer import self_shred as ss
from agents.daemon_slayer import spike_markers as sm
from agents.daemon_slayer.data_loader import DataSnapshot

INF = float("inf")
NAN = float("nan")
JUNK = [NAN, "x", None, object()]
SEQ = ["Q", "W", "E", "R"]


@pytest.fixture(scope="module")
def snap():
    return DataSnapshot.load()


# --- S144-D-119: spike_markers ------------------------------------------------


class TestSpikeMarkersLevel:
    def test_pos_inf_level_reads_18(self):
        r = sm.compute_spike_markers("Ahri", INF, annotate_dps=False)
        assert r.level == 18
        assert all(m.crossed for m in r.markers if m.kind == "level")

    def test_neg_inf_level_reads_1(self):
        r = sm.compute_spike_markers("Ahri", -INF, annotate_dps=False)
        assert r.level == 1
        ref = sm.compute_spike_markers("Ahri", 1, annotate_dps=False)
        assert r.to_dict() == ref.to_dict()

    @pytest.mark.parametrize("lv", JUNK, ids=["nan", "str", "none", "obj"])
    def test_junk_level_reads_1(self, lv):
        assert sm.compute_spike_markers("Ahri", lv, annotate_dps=False).level == 1

    def test_clamp_level_helper(self):
        assert sm._clamp_level(INF) == 18
        assert sm._clamp_level(-INF) == 1
        assert sm._clamp_level(NAN) == 1
        assert sm._clamp_level(10**400) == 18
        assert sm._clamp_level(7.9) == 7


class TestSpikeMarkersItemCount:
    def test_pos_inf_item_count_crosses_every_item_spike(self):
        r = sm.compute_spike_markers(
            "Ahri", 6, item_count_done=INF, annotate_dps=False)
        assert r.item_count_done == len(sm._ITEM_SPIKES)
        assert all(m.crossed for m in r.markers if m.kind == "item")

    def test_neg_inf_item_count_reads_0(self):
        r = sm.compute_spike_markers(
            "Ahri", 6, item_count_done=-INF, annotate_dps=False)
        assert r.item_count_done == 0
        assert not any(m.crossed for m in r.markers if m.kind == "item")

    @pytest.mark.parametrize("v", [NAN, "x", object()], ids=["nan", "str", "obj"])
    def test_junk_item_count_reads_0(self, v):
        r = sm.compute_spike_markers(
            "Ahri", 6, item_count_done=v, annotate_dps=False)
        assert r.item_count_done == 0

    def test_finite_item_count_unchanged(self):
        r = sm.compute_spike_markers(
            "Ahri", 6, item_count_done=5, annotate_dps=False)
        assert r.item_count_done == 5


# --- S144-D-120: fight_report -------------------------------------------------


class TestFightReportLevel:
    def test_pos_inf_level_matches_level_18(self, snap):
        r = fr.compute_fight_report("Ahri", level=INF, snapshot=snap)
        ref = fr.compute_fight_report("Ahri", level=18, snapshot=snap)
        assert r.level == 18
        assert repr(r.to_dict()) == repr(ref.to_dict())

    def test_neg_inf_level_matches_level_1(self, snap):
        r = fr.compute_fight_report("Ahri", level=-INF, snapshot=snap)
        ref = fr.compute_fight_report("Ahri", level=1, snapshot=snap)
        assert r.level == 1
        assert repr(r.to_dict()) == repr(ref.to_dict())

    def test_nan_level_still_reads_1(self, snap):
        r = fr.compute_fight_report("Ahri", level=NAN, snapshot=snap)
        assert r.level == 1


# --- S144-D-121: self_shred ---------------------------------------------------


class TestSelfShredLevel:
    def _call(self, lv):
        return ss.compute_self_shred_uplift("Corki", lv, 100.0, 60.0, 500.0, 300.0)

    def test_pos_inf_level_matches_level_18(self):
        r = self._call(INF)
        assert r.level == 18
        assert repr(r.to_dict()) == repr(self._call(18).to_dict())

    def test_neg_inf_level_matches_level_1(self):
        r = self._call(-INF)
        assert r.level == 1
        assert repr(r.to_dict()) == repr(self._call(1).to_dict())

    def test_shred_is_finite_at_inf(self):
        r = self._call(INF)
        assert math.isfinite(r.dps_uplift_abs)
        assert r.dps_uplift_abs > 0.0


# --- S144-D-122: combo + mana_sim ---------------------------------------------


@pytest.mark.parametrize(
    "fn", [cb.compute_combo, ms.compute_mana_bounded_combo],
    ids=["combo", "mana_sim"])
class TestComboAndManaLevel:
    def test_pos_inf_matches_level_18(self, fn, snap):
        r = fn("Ahri", INF, sequence=SEQ, snapshot=snap)
        ref = fn("Ahri", 18, sequence=SEQ, snapshot=snap)
        assert r.level == 18
        assert len(r.hits) == len(SEQ)
        assert repr(r) == repr(ref)

    def test_neg_inf_matches_level_1(self, fn, snap):
        r = fn("Ahri", -INF, sequence=SEQ, snapshot=snap)
        ref = fn("Ahri", 1, sequence=SEQ, snapshot=snap)
        assert r.level == 1
        assert repr(r) == repr(ref)

    @pytest.mark.parametrize("lv", JUNK, ids=["nan", "str", "none", "obj"])
    def test_junk_level_reads_1_never_raises(self, fn, snap, lv):
        r = fn("Ahri", lv, sequence=SEQ, snapshot=snap)
        ref = fn("Ahri", 1, sequence=SEQ, snapshot=snap)
        assert r.level == 1
        assert repr(r) == repr(ref)

    @pytest.mark.parametrize("lv", [INF, NAN, None], ids=["inf", "nan", "none"])
    def test_blank_champion_never_raises(self, fn, snap, lv):
        r = fn("", lv, sequence=SEQ, snapshot=snap)
        assert r.hits == () or list(r.hits) == []
        assert isinstance(r.level, int)

    @pytest.mark.parametrize("lv", JUNK[:3], ids=["nan", "str", "none"])
    def test_empty_sequence_never_raises(self, fn, snap, lv):
        r = fn("Ahri", lv, sequence=[], snapshot=snap)
        assert r.level == 1

    def test_finite_out_of_range_not_newly_clamped(self, fn, snap):
        # Byte-identical to HEAD: level 19 still reaches the burst walker,
        # which refuses it, and the fail-soft note answers.
        r = fn("Ahri", 19, sequence=SEQ, snapshot=snap)
        assert r.level == 19
        assert "burst walker failed - see logs" in r.notes
