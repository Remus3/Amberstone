# tests/test_ds_capability_gap.py
"""Deterministic tests for core.ds_capability_gap.build_capability_gap.

L4 Phase-D consumer: a multi-axis composition-gap synthesizer that reads the
existing per-champion DS capability scorers (anti-tank via build_antitank_hint,
poke/siege via compute_threatrange) against a live enemy comp and emits the
single highest-severity capability deficit the operator's pick has versus the
enemy's demand. Pure read-only, never raises, no engine math change.

Fixtures are grounded against live scorer output (probed 2026-06-26):
  Garen   antitank=0.212 is_artillery=False archetype=bruiser
  Vayne   antitank=0.950 is_artillery=False archetype=carry
  Lux/Xerath/Ziggs/Velkoz  antitank=0.0 is_artillery=True archetype=mage
  Malphite antitank=0.0 is_artillery=False archetype=tank
  Sett     antitank=0.580 is_artillery=False archetype=bruiser
  MasterYi antitank=0.0 is_artillery=False archetype=bruiser
  Ornn     is_artillery=True (kept OUT of poke fixtures on purpose).
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer.threatrange import compute_threatrange
from core.archetype_picks import get_archetype_for
from core.ds_capability_gap import (
    OBJDMG_ENEMY_MIN,
    OBJDMG_HIGH_SCORE,
    POKE_ENEMY_MIN,
    SUSTAIN_ENEMY_MIN,
    SUSTAIN_HIGH_SCORE,
    ZONE_ENEMY_MIN,
    _rank_gaps,
    build_capability_gap,
)
from agents.daemon_slayer.objdamage import compute_objdamage
from agents.daemon_slayer.sustain import compute_sustain
from agents.daemon_slayer.zonecontrol import compute_zonecontrol

# Tanky enemies (tank/bruiser archetype) that are NOT flagged is_artillery.
_TANKY_NO_POKE = ["Malphite", "Sett", "MasterYi"]
# Artillery enemies (is_artillery True) that are NOT tank/bruiser archetype.
_ARTILLERY_SQUISH = ["Xerath", "Ziggs", "Velkoz"]
# Heavy-sustain enemies (total_sustain_score >= SUSTAIN_HIGH_SCORE) that are
# NOT is_artillery and do NOT trip the anti-tank recommend threshold, so a comp
# of these fires the sustain gap alone. Probed live 2026-06-26:
#   Vladimir 1.600 / Fiddlesticks 2.933 / Warwick 11.667.
_HIGH_SUSTAIN_NO_POKE = ["Vladimir", "Fiddlesticks", "Warwick"]
# Terrain-control enemies (controls_terrain True) that are NOT artillery, have
# sustain < SUSTAIN_HIGH_SCORE, and objdamage_score < OBJDMG_HIGH_SCORE, so a
# comp of these fires the zone_control gap alone. Probed live 2026-06-27:
#   Anivia / JarvanIV / Veigar all controls_terrain True, sustain 0.0, obj<0.5.
_ZONE_TERRAIN_NO_OTHER = ["Anivia", "JarvanIV", "Veigar"]
# Objective-pressure enemies (objdamage_score >= OBJDMG_HIGH_SCORE) that are NOT
# artillery, NOT controls_terrain, and sustain < SUSTAIN_HIGH_SCORE, so a comp of
# these fires the objective_damage gap alone. Probed live 2026-06-27:
#   Twitch 0.896 / Shyvana 0.889 / Tryndamere 0.938.
_OBJ_HIGH_NO_OTHER = ["Twitch", "Shyvana", "Tryndamere"]


# --- precondition guards: fail loudly if the underlying data shifts ----------

def test_fixture_preconditions_hold():
    """Pin the scorer/archetype facts every integration test below relies on,
    so a patch-data shift fails HERE with a clear message rather than as a
    mysterious downstream assertion."""
    for champ in _ARTILLERY_SQUISH:
        assert compute_threatrange(champ, "SR").is_artillery is True, champ
        assert get_archetype_for(champ).get("primary") not in {"tank", "bruiser"}, champ
    for champ in _TANKY_NO_POKE:
        assert compute_threatrange(champ, "SR").is_artillery is False, champ
        assert get_archetype_for(champ).get("primary") in {"tank", "bruiser"}, champ
    assert compute_threatrange("Garen", "SR").is_artillery is False
    # Sustain-gap fixtures: heavy-sustain AND non-artillery, so they fire the
    # sustain axis without bleeding into the poke axis.
    for champ in _HIGH_SUSTAIN_NO_POKE:
        assert compute_sustain(champ, "SR").total_sustain_score >= SUSTAIN_HIGH_SCORE, champ
        assert compute_threatrange(champ, "SR").is_artillery is False, champ
    # Lux is the low-sustain probe used as "me" - must stay below the threshold.
    assert compute_sustain("Lux", "SR").total_sustain_score < SUSTAIN_HIGH_SCORE
    # Zone-control fixtures: controls_terrain AND non-artillery, so they fire the
    # zone_control axis without bleeding into the poke axis.
    for champ in _ZONE_TERRAIN_NO_OTHER:
        assert compute_zonecontrol(champ, "SR").controls_terrain is True, champ
        assert compute_threatrange(champ, "SR").is_artillery is False, champ
    # Objective-damage fixtures: high objdamage_score AND non-artillery AND
    # non-terrain, so they fire the objective_damage axis cleanly.
    for champ in _OBJ_HIGH_NO_OTHER:
        assert compute_objdamage(champ, "SR").objdamage_score >= OBJDMG_HIGH_SCORE, champ
        assert compute_threatrange(champ, "SR").is_artillery is False, champ
        assert compute_zonecontrol(champ, "SR").controls_terrain is False, champ
    # "me" probes for the two new axes: Lux does not control terrain; Lulu does
    # not out-pressure objectives (both below their respective gates).
    assert compute_zonecontrol("Lux", "SR").controls_terrain is False
    assert compute_objdamage("Lulu", "SR").objdamage_score < OBJDMG_HIGH_SCORE


# --- anti-tank gap -----------------------------------------------------------

def test_antitank_gap_fires_for_squishy_vs_tanks():
    res = build_capability_gap("Lux", _TANKY_NO_POKE)
    assert res["applies"] is True
    assert res["top_gap"] == "anti_tank"
    assert "anti-tank" in res["verdict"].lower()
    axes = [g["axis"] for g in res["gaps"]]
    assert "anti_tank" in axes
    at = next(g for g in res["gaps"] if g["axis"] == "anti_tank")
    assert at["demand_count"] == 3


def test_antitank_lean_in_champion_no_gap():
    # Vayne already shreds tanks (antitank 0.95 >= 0.8) -> no anti-tank gap, and
    # no poke gap (the tanks are not artillery), so nothing applies.
    res = build_capability_gap("Vayne", _TANKY_NO_POKE)
    assert res["applies"] is False
    assert res["top_gap"] == ""
    assert res["verdict"] == ""
    assert res["gaps"] == []


# --- poke gap ----------------------------------------------------------------

def test_poke_gap_fires_for_melee_vs_artillery():
    res = build_capability_gap("Garen", _ARTILLERY_SQUISH)
    assert res["applies"] is True
    assert res["top_gap"] == "poke"
    assert "out-range" in res["verdict"].lower() or "range" in res["verdict"].lower()
    poke = next(g for g in res["gaps"] if g["axis"] == "poke")
    assert poke["demand_count"] == 3


def test_poke_gap_blocked_when_i_can_poke_back():
    # Xerath is artillery himself -> no poke deficit even vs an artillery comp.
    res = build_capability_gap("Xerath", ["Ziggs", "Velkoz", "Lux"])
    assert res["applies"] is False
    assert res["gaps"] == []


def test_poke_gap_below_min_does_not_fire():
    # Only one artillery enemy (< POKE_ENEMY_MIN) -> no poke gap.
    assert POKE_ENEMY_MIN == 2
    res = build_capability_gap("Garen", ["Xerath", "Garen", "Sett"])
    poke = [g for g in res["gaps"] if g["axis"] == "poke"]
    assert poke == []


# --- sustain gap -------------------------------------------------------------

def test_sustain_gap_fires_for_low_sustain_vs_heavy_sustain():
    res = build_capability_gap("Lux", _HIGH_SUSTAIN_NO_POKE)
    assert res["applies"] is True
    assert res["top_gap"] == "sustain"
    assert "anti-heal" in res["verdict"].lower() or "grievous" in res["verdict"].lower()
    sus = next(g for g in res["gaps"] if g["axis"] == "sustain")
    assert sus["demand_count"] == 3


def test_sustain_gap_blocked_when_i_out_sustain():
    # Aatrox out-sustains in kind (>= SUSTAIN_HIGH_SCORE) -> no sustain deficit.
    res = build_capability_gap("Aatrox", _HIGH_SUSTAIN_NO_POKE)
    assert all(g["axis"] != "sustain" for g in res["gaps"])


def test_sustain_gap_below_min_does_not_fire():
    # Only one heavy-sustain enemy (< SUSTAIN_ENEMY_MIN) -> no sustain gap.
    assert SUSTAIN_ENEMY_MIN == 2
    res = build_capability_gap("Lux", ["Warwick", "Garen", "Annie"])
    assert all(g["axis"] != "sustain" for g in res["gaps"])


# --- ranking across axes -----------------------------------------------------

def test_ranking_antitank_outranks_poke_on_higher_demand():
    # 3 tanky (Malphite/Sett/MasterYi) vs 2 artillery (Xerath/Ziggs).
    enemies = ["Malphite", "Sett", "MasterYi", "Xerath", "Ziggs"]
    res = build_capability_gap("Garen", enemies)
    assert res["applies"] is True
    assert {g["axis"] for g in res["gaps"]} == {"anti_tank", "poke"}
    assert res["top_gap"] == "anti_tank"


def test_ranking_poke_outranks_antitank_on_higher_demand():
    # 2 tanky (Malphite/Sett) vs 3 artillery (Xerath/Ziggs/Velkoz).
    enemies = ["Malphite", "Sett", "Xerath", "Ziggs", "Velkoz"]
    res = build_capability_gap("Garen", enemies)
    assert res["applies"] is True
    assert {g["axis"] for g in res["gaps"]} == {"anti_tank", "poke"}
    assert res["top_gap"] == "poke"


def test_rank_gaps_tie_breaks_on_registry_order():
    # Pure ordering logic, data-independent. Equal severity -> anti_tank first.
    gaps = [
        {"axis": "poke", "severity": 2.0, "demand_count": 2, "detail": "p"},
        {"axis": "anti_tank", "severity": 2.0, "demand_count": 2, "detail": "a"},
    ]
    ranked = _rank_gaps(gaps)
    assert [g["axis"] for g in ranked] == ["anti_tank", "poke"]


def test_rank_gaps_orders_by_severity_desc():
    gaps = [
        {"axis": "anti_tank", "severity": 1.0, "demand_count": 1, "detail": "a"},
        {"axis": "poke", "severity": 4.0, "demand_count": 4, "detail": "p"},
    ]
    ranked = _rank_gaps(gaps)
    assert [g["axis"] for g in ranked] == ["poke", "anti_tank"]


# --- zone_control gap --------------------------------------------------------

def test_zonecontrol_gap_fires_for_nonzoner_vs_terrain():
    res = build_capability_gap("Lux", _ZONE_TERRAIN_NO_OTHER)
    assert res["applies"] is True
    assert res["top_gap"] == "zone_control"
    zone = next(g for g in res["gaps"] if g["axis"] == "zone_control")
    assert zone["demand_count"] == 3


def test_zonecontrol_gap_self_exempt_when_i_control_terrain():
    # Veigar controls terrain himself -> no zone_control deficit.
    res = build_capability_gap("Veigar", ["Anivia", "JarvanIV"])
    assert all(g["axis"] != "zone_control" for g in res["gaps"])
    assert res["applies"] is False


def test_zonecontrol_gap_below_min_does_not_fire():
    # Only one terrain controller (< ZONE_ENEMY_MIN) -> no zone_control gap.
    assert ZONE_ENEMY_MIN == 2
    res = build_capability_gap("Lux", ["Anivia", "Lulu", "Karma"])
    assert all(g["axis"] != "zone_control" for g in res["gaps"])


# --- objective_damage gap ----------------------------------------------------

def test_objdamage_gap_fires_for_low_obj_vs_high_obj():
    res = build_capability_gap("Lulu", _OBJ_HIGH_NO_OTHER)
    assert res["applies"] is True
    assert res["top_gap"] == "objective_damage"
    obj = next(g for g in res["gaps"] if g["axis"] == "objective_damage")
    assert obj["demand_count"] == 3


def test_objdamage_gap_self_exempt_when_i_pressure_objectives():
    # Twitch out-pressures objectives himself -> no objective_damage deficit.
    res = build_capability_gap("Twitch", ["Shyvana", "Tryndamere"])
    assert all(g["axis"] != "objective_damage" for g in res["gaps"])


def test_objdamage_gap_below_min_does_not_fire():
    # Only one high-objdamage enemy (< OBJDMG_ENEMY_MIN) -> no objective_damage gap.
    assert OBJDMG_ENEMY_MIN == 2
    res = build_capability_gap("Lulu", ["Twitch", "Karma", "Orianna"])
    assert all(g["axis"] != "objective_damage" for g in res["gaps"])


# --- ranking across the two new axes -----------------------------------------

def test_ranking_zonecontrol_outranks_objdamage_on_higher_demand():
    # 3 terrain controllers vs 2 objective-pressure threats -> zone wins on
    # higher demand. (JarvanIV/Shyvana also read tanky, so anti_tank co-fires at
    # demand 2; the live-load-bearing claim is the zone>obj ordering, asserted
    # directly on the two demand counts and the top_gap.)
    enemies = ["Anivia", "JarvanIV", "Veigar", "Twitch", "Shyvana"]
    res = build_capability_gap("Lulu", enemies)
    axes = {g["axis"] for g in res["gaps"]}
    assert {"zone_control", "objective_damage"} <= axes
    zone = next(g for g in res["gaps"] if g["axis"] == "zone_control")
    obj = next(g for g in res["gaps"] if g["axis"] == "objective_damage")
    assert zone["demand_count"] == 3
    assert obj["demand_count"] == 2
    assert zone["demand_count"] > obj["demand_count"]
    assert res["top_gap"] == "zone_control"


def test_new_axis_verdicts_are_ascii():
    zone = build_capability_gap("Lux", _ZONE_TERRAIN_NO_OTHER)["verdict"]
    obj = build_capability_gap("Lulu", _OBJ_HIGH_NO_OTHER)["verdict"]
    zone.encode("ascii")
    obj.encode("ascii")


# --- fail-soft + hygiene -----------------------------------------------------

def test_blank_my_champion_returns_zero():
    res = build_capability_gap("", _TANKY_NO_POKE)
    assert res["applies"] is False
    assert res["my_champion"] == ""
    assert res["gaps"] == []


def test_none_enemies_does_not_raise():
    res = build_capability_gap("Garen", None)
    assert res["applies"] is False
    assert res["gaps"] == []


def test_unknown_champions_fail_soft():
    res = build_capability_gap("DefinitelyFakeChampXYZ", ["FakeA", "FakeB", "FakeC"])
    assert res["applies"] is False
    assert res["gaps"] == []


def test_dirty_enemy_entries_skipped():
    res = build_capability_gap("Lux", ["Malphite", "", None, "Sett", "  ", "MasterYi"])
    assert res["top_gap"] == "anti_tank"


def test_verdict_and_details_are_ascii():
    res = build_capability_gap("Garen", ["Malphite", "Sett", "Xerath", "Ziggs", "Velkoz"])
    res["verdict"].encode("ascii")
    for g in res["gaps"]:
        g["detail"].encode("ascii")


def test_deterministic_repeat():
    a = build_capability_gap("Garen", ["Malphite", "Sett", "Xerath", "Ziggs"])
    b = build_capability_gap("Garen", ["Malphite", "Sett", "Xerath", "Ziggs"])
    assert a == b


def test_mode_passthrough_does_not_raise():
    res = build_capability_gap("Lux", _TANKY_NO_POKE, mode="ARAM")
    assert res["mode"] == "ARAM"
