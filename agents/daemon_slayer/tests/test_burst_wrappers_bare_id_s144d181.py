"""S144-D-181..185 - the burst-walker wrappers read a bare item id as ONE id,
and the matchup mana gate never reads a failed mana walk as a full combo.

Measured at HEAD before the fix (Lux L11, Rabadon's Deathcap 3089, snapshot
16.22.1):

* S144-D-181 ``combo.compute_combo``: ``item_ids="3089"`` reached the burst
  walker as ``['3', '0', '8', '9']`` ("Unknown item id: '3'") and a bare int
  3089 raised TypeError inside it; both came back as the fail-soft 0.0 with
  "burst walker failed - see logs" instead of the 1169.75 of ``["3089"]``.
* S144-D-182 ``mana_sim.compute_mana_bounded_combo``: the same (0.0 total,
  0.0 mana pool).
* S144-D-183 ``fight_report.compute_fight_report`` (documented NEVER raises):
  a bare int raised TypeError out of the report; a bare "3089" was echoed as
  ``['3', '0', '8', '9']`` and failed the mana, ability_hps and rune sections.
* S144-D-184 ``scenario_matrix.sweep_scenarios``: an item set given as a bare
  "3089" was read as ``('3', '0', '8', '9')`` (``burst`` NaN, ``combo`` a
  FINITE 0.0 with an empty note, which reads like a real measurement); a bare
  int item set raised TypeError and aborted the whole sweep.
* S144-D-185 ``matchup._can_full_combo``: a mana walk that failed soft
  (``casts_requested == 0`` with the "burst walker failed" note) was read as
  "nothing to gate", so ``a_can_full_combo`` was True and the verdict could
  be ``all_in`` with no note that the mana gate never ran.

Contract pinned here: a bare ``str`` / ``int`` id (never ``bool``) is one id
and gives exactly the result of the one-element list; list / tuple pages are
unchanged. A failed mana walk reads as "full combo NOT confirmed"
(``can_full_combo`` False, 0 casts allowed), with one fixed note that says the
mana gate did not run, and never the "cannot afford" note. A walk with no
resolvable casts (the burst walker ran and found nothing) still reads as full.
"""
from __future__ import annotations

import logging
from dataclasses import asdict

import pytest

from agents.daemon_slayer import mana_sim
from agents.daemon_slayer.combo import compute_combo
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.fight_report import compute_fight_report
from agents.daemon_slayer.mana_sim import compute_mana_bounded_combo
from agents.daemon_slayer.matchup import compute_matchup
from agents.daemon_slayer.scenario_matrix import sweep_scenarios

_ID = "3089"
_SEQ = ["Q", "E", "R"]
_FAILED = "burst walker failed - see logs"
_BARE = [pytest.param(_ID, id="bare_str"), pytest.param(int(_ID), id="bare_int")]


@pytest.fixture(scope="module")
def snap():
    return DataSnapshot.load()


@pytest.fixture(autouse=True)
def _quiet(caplog):
    caplog.set_level(logging.CRITICAL)


# --- S144-D-181 compute_combo ---------------------------------------------

@pytest.mark.parametrize("ids", _BARE)
def test_combo_bare_id_is_one_id(snap, ids):
    ref = compute_combo("Lux", 11, item_ids=[_ID], sequence=_SEQ, snapshot=snap)
    got = compute_combo("Lux", 11, item_ids=ids, sequence=_SEQ, snapshot=snap)
    assert ref.total_mitigated > 0.0
    assert _FAILED not in got.notes
    assert asdict(got) == asdict(ref)


def test_combo_tuple_page_unchanged(snap):
    ref = compute_combo("Lux", 11, item_ids=[_ID], sequence=_SEQ, snapshot=snap)
    got = compute_combo("Lux", 11, item_ids=(_ID,), sequence=_SEQ, snapshot=snap)
    assert asdict(got) == asdict(ref)


def test_combo_bool_is_not_an_id(snap):
    got = compute_combo("Lux", 11, item_ids=True, sequence=_SEQ, snapshot=snap)
    assert got.total_mitigated == 0.0
    assert _FAILED in got.notes


# --- S144-D-182 compute_mana_bounded_combo --------------------------------

@pytest.mark.parametrize("ids", _BARE)
def test_mana_bare_id_is_one_id(snap, ids):
    ref = compute_mana_bounded_combo(
        "Lux", 11, item_ids=[_ID], sequence=_SEQ, snapshot=snap,
    )
    got = compute_mana_bounded_combo(
        "Lux", 11, item_ids=ids, sequence=_SEQ, snapshot=snap,
    )
    assert ref.total_mitigated > 0.0 and ref.mana_pool > 0.0
    assert _FAILED not in got.notes
    assert asdict(got) == asdict(ref)


def test_mana_bool_is_not_an_id(snap):
    got = compute_mana_bounded_combo(
        "Lux", 11, item_ids=True, sequence=_SEQ, snapshot=snap,
    )
    assert got.total_mitigated == 0.0
    assert _FAILED in got.notes


# --- S144-D-183 compute_fight_report --------------------------------------

@pytest.mark.parametrize("ids", _BARE)
def test_fight_report_bare_id_is_one_id(snap, ids):
    ref = compute_fight_report("Lux", 11, item_ids=[_ID], snapshot=snap)
    got = compute_fight_report("Lux", 11, item_ids=ids, snapshot=snap)
    assert list(got.item_ids) == [_ID]
    assert got.to_dict() == ref.to_dict()


# --- S144-D-184 sweep_scenarios item sets ---------------------------------

def _cells(snap, item_sets, metric):
    return [
        (c.item_ids, c.value, c.note)
        for c in sweep_scenarios(
            "Lux", [11], item_sets, [(30.0, 30.0, 1900.0, 800.0)],
            metric=metric, snapshot=snap, sequence=_SEQ,
        )
    ]


@pytest.mark.parametrize("metric", ["burst", "combo", "mana_bounded_dps"])
@pytest.mark.parametrize("bare", _BARE)
def test_sweep_bare_item_set_is_one_id(snap, bare, metric):
    ref = _cells(snap, [[_ID]], metric)
    got = _cells(snap, [bare], metric)
    assert ref[0][0] == (_ID,) and ref[0][1] > 0.0
    assert got == ref


@pytest.mark.parametrize("metric", ["burst", "combo"])
@pytest.mark.parametrize(
    "falsy", ["", 0, None, (), []], ids=["empty_str", "zero", "none", "tuple", "list"],
)
def test_sweep_falsy_item_set_stays_empty(snap, falsy, metric):
    # A falsy item set is the empty set, never the one-item set ('',) / ('0',).
    ref = _cells(snap, [[]], metric)
    got = _cells(snap, [falsy], metric)
    assert ref[0][0] == () and ref[0][1] > 0.0
    assert got == ref


def test_sweep_bare_item_set_beside_good_sets(snap):
    ref = _cells(snap, [[_ID], []], "combo")
    got = _cells(snap, [int(_ID), []], "combo")
    assert got == ref


# --- S144-D-185 matchup mana gate -----------------------------------------

def _failed_walk(champion, level, item_ids=None, sequence=None, mode="SR",
                 **_kw):
    return mana_sim._empty(
        champion, level, mode, tuple(sequence or ()), [_FAILED],
        champ_name=champion,
    )


def _no_casts_walk(champion, level, item_ids=None, sequence=None, mode="SR",
                   **_kw):
    return mana_sim._empty(
        champion, level, mode, tuple(sequence or ()),
        ["no resolvable actions (champion absent or sequence empty)"],
        champ_name=champion,
    )


def test_matchup_reference_is_all_in(snap):
    # Control: with a working mana walk Lux kills a 10%-HP Garen -> all_in.
    r = compute_matchup(snap, "Lux", "Garen", 11, 11, item_ids_a=[_ID],
                        hp_b_pct=0.1)
    assert r.verdict == "all_in" and r.a_can_full_combo is True


def test_matchup_failed_mana_walk_is_not_a_full_combo(snap, monkeypatch):
    monkeypatch.setattr(mana_sim, "compute_mana_bounded_combo", _failed_walk)
    r = compute_matchup(snap, "Lux", "Garen", 11, 11, item_ids_a=[_ID],
                        hp_b_pct=0.1)
    assert r.a_can_full_combo is False
    assert r.b_can_full_combo is False
    assert r.a_casts_allowed == 0
    assert r.verdict != "all_in"
    gate = [n for n in r.notes if "mana gate did not run" in n]
    assert len(gate) == 2
    assert not any("cannot afford" in n for n in r.notes)


def test_matchup_no_resolvable_casts_still_reads_full(snap, monkeypatch):
    monkeypatch.setattr(mana_sim, "compute_mana_bounded_combo", _no_casts_walk)
    r = compute_matchup(snap, "Lux", "Garen", 11, 11, item_ids_a=[_ID],
                        hp_b_pct=0.1)
    assert r.a_can_full_combo is True
    assert r.verdict == "all_in"
    assert not any("mana gate" in n for n in r.notes)
