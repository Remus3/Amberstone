# tests/test_ds_capability_gap_true_audit_s144t147.py
"""True-audit regressions for core.ds_capability_gap (s144 cycle 147).

Findings (provisional ids RM-1855..RM-1860):

- RM-1855: the poke / sustain / zone_control / objective_damage detectors
  handed Live Client DISPLAY names ("Kog'Maw", "Jarvan IV", "Bel'Veth") to DS
  registries keyed on DDragon ids, so every such champion scored 0.0 / False
  and a whole axis vanished (or a false self-deficit fired). Both live callers
  in dashboard/routes_state.py feed display names straight from the Live
  Client allPlayers[].championName.
- RM-1856: a non-str my_champion (int / float / list) raised
  AttributeError despite the "never raises" docstring, and bytes were echoed
  into the result, breaking json.dumps.
- RM-1857: a non-str enemy entry raised AttributeError (the strip sat
  outside every try), a non-iterable enemy_champions raised TypeError, and a
  bare string was iterated character by character.
- RM-1858: a non-str or blank mode was echoed verbatim (5, ["SR"], "  ")
  while the nested anti-tank detector coerced it to "SR".
- RM-1859: a detector-level failure (for example a DS scorer import error)
  was logged at DEBUG only, so a whole axis disappeared silently.
- RM-1860: a my_champion carrying a control character (newline, NUL) or
  an absurd length was echoed into the result and the capgap-shadow log line.
  (Enemy names are never echoed, so they are only type-checked and stripped.)

Scorer values these fixtures rely on were probed live 2026-11-05 and are
pinned by test_display_name_fixture_preconditions below.
"""
from __future__ import annotations

import json
import logging

import pytest

import core.ds_capability_gap as capgap
from agents.daemon_slayer.objdamage import compute_objdamage
from agents.daemon_slayer.threatrange import compute_threatrange
from agents.daemon_slayer.zonecontrol import compute_zonecontrol
from core.ds_capability_gap import (
    OBJDMG_HIGH_SCORE,
    build_capability_gap,
)

_RESULT_KEYS = {"applies", "my_champion", "mode", "top_gap", "verdict", "gaps"}


def _assert_strict_json(res: dict) -> None:
    assert set(res) == _RESULT_KEYS
    json.dumps(res, allow_nan=False)
    assert isinstance(res["my_champion"], str)
    assert isinstance(res["mode"], str)


# --- preconditions -----------------------------------------------------------

def test_display_name_fixture_preconditions():
    """The DDragon ids score; the matching display names (unbridged) do not.

    If this fails the DS data shifted and the fixtures below need re-probing.
    """
    for cid in ("KogMaw", "Velkoz", "MissFortune"):
        assert compute_threatrange(cid, "SR").is_artillery is True
    assert compute_threatrange("Garen", "SR").is_artillery is False
    for cid in ("JarvanIV", "RekSai"):
        assert compute_zonecontrol(cid, "SR").controls_terrain is True
    assert compute_zonecontrol("Garen", "SR").controls_terrain is False
    for cid in ("Belveth", "KogMaw", "MasterYi"):
        assert compute_objdamage(cid, "SR").objdamage_score >= OBJDMG_HIGH_SCORE
    assert compute_objdamage("Lux", "SR").objdamage_score < OBJDMG_HIGH_SCORE
    # Unbridged display names read as unknown champions.
    assert compute_threatrange("Kog'Maw", "SR").is_artillery is False
    assert compute_zonecontrol("Jarvan IV", "SR").controls_terrain is False
    assert compute_objdamage("Bel'Veth", "SR").objdamage_score == 0.0


# --- RM-1855: display names are bridged to DDragon ids --------------------

@pytest.mark.parametrize(
    "me, display, ids",
    [
        ("Garen", ["Kog'Maw", "Vel'Koz", "Miss Fortune"], ["KogMaw", "Velkoz", "MissFortune"]),
        ("Garen", ["Jarvan IV", "Rek'Sai", "Lux"], ["JarvanIV", "RekSai", "Lux"]),
        ("Lux", ["Bel'Veth", "Kog'Maw", "Master Yi"], ["Belveth", "KogMaw", "MasterYi"]),
        ("Lux", ["Dr. Mundo", "Bel'Veth", "Warwick", "Aatrox", "Ahri"],
         ["DrMundo", "Belveth", "Warwick", "Aatrox", "Ahri"]),
    ],
)
def test_display_name_enemies_score_like_ddragon_ids(me, display, ids):
    by_display = build_capability_gap(me, display)
    by_id = build_capability_gap(me, ids)
    assert by_id["applies"] is True
    assert by_display["gaps"] == by_id["gaps"]
    assert by_display["top_gap"] == by_id["top_gap"]


def test_display_name_enemies_fire_each_axis():
    assert build_capability_gap("Garen", ["Kog'Maw", "Vel'Koz"])["top_gap"] == "poke"
    zone = build_capability_gap("Garen", ["Jarvan IV", "Rek'Sai"])
    assert "zone_control" in {g["axis"] for g in zone["gaps"]}
    obj = build_capability_gap("Lux", ["Bel'Veth", "Kog'Maw"])
    assert "objective_damage" in {g["axis"] for g in obj["gaps"]}


def test_display_name_self_is_bridged_for_the_self_exemption():
    """Kog'Maw IS artillery: a display-name self must not get a poke deficit."""
    enemies = ["Velkoz", "MissFortune"]
    assert build_capability_gap("Garen", enemies)["top_gap"] == "poke"
    by_id = build_capability_gap("KogMaw", enemies)
    by_display = build_capability_gap("Kog'Maw", enemies)
    assert "poke" not in {g["axis"] for g in by_id["gaps"]}
    assert "poke" not in {g["axis"] for g in by_display["gaps"]}
    assert by_display["gaps"] == by_id["gaps"]


def test_echoed_my_champion_keeps_the_callers_form():
    res = build_capability_gap("  Kog'Maw ", ["Velkoz", "MissFortune", "Malphite", "Sett"])
    assert res["my_champion"] == "Kog'Maw"


def test_canonical_lookup_failure_falls_back_to_the_raw_name(monkeypatch):
    import core.archetype_picks as ap

    def _boom(name):
        raise RuntimeError("ddragon table unreadable")

    monkeypatch.setattr(ap, "canonical_champion_id", _boom)
    res = build_capability_gap("Garen", ["Velkoz", "MissFortune"])
    assert res["top_gap"] == "poke"


# --- RM-1856: non-str my_champion -----------------------------------------

@pytest.mark.parametrize("bad", [5, 3.0, ["Lux"], b"Lux", {"name": "Lux"}, True])
def test_non_str_my_champion_returns_zero_and_never_raises(bad):
    res = build_capability_gap(bad, ["Warwick", "Aatrox"])
    _assert_strict_json(res)
    assert res["applies"] is False
    assert res["my_champion"] == ""
    assert res["gaps"] == []


# --- RM-1857: non-str enemy entries and non-list containers ---------------

def test_non_str_enemy_entry_is_skipped_not_raised():
    clean = build_capability_gap("Lux", ["Malphite", "Sett", "MasterYi"])
    dirty = build_capability_gap("Lux", ["Malphite", 7, "Sett", b"X", 2.5, ["Y"], "MasterYi"])
    _assert_strict_json(dirty)
    assert dirty["gaps"] == clean["gaps"]
    assert dirty["top_gap"] == "anti_tank"


@pytest.mark.parametrize("bad", [5, 2.5, "WarwickAatrox", b"Warwick", {"Malphite": 1, "Sett": 2}, object()])
def test_non_list_enemy_container_is_treated_as_empty(bad):
    res = build_capability_gap("Lux", bad)
    _assert_strict_json(res)
    assert res["applies"] is False
    assert res["gaps"] == []


def test_bare_string_enemies_is_not_iterated_by_character(monkeypatch):
    seen: list = []

    def _spy(me, enemies, mode):
        seen.append(list(enemies))

    monkeypatch.setattr(capgap, "_DETECTORS", (_spy,))
    build_capability_gap("Lux", "Malphite")
    assert seen == [[]]


def test_tuple_enemies_still_accepted():
    res = build_capability_gap("Lux", ("Malphite", "Sett", "MasterYi"))
    assert res["top_gap"] == "anti_tank"


# --- RM-1858: mode coercion -----------------------------------------------

@pytest.mark.parametrize("bad", [5, ["SR"], "  ", "", None, b"SR"])
def test_non_str_or_blank_mode_becomes_sr(bad):
    res = build_capability_gap("Lux", ["Malphite", "Sett", "MasterYi"], bad)
    _assert_strict_json(res)
    assert res["mode"] == "SR"
    assert res["top_gap"] == "anti_tank"


def test_mode_is_stripped_and_passed_to_detectors(monkeypatch):
    seen: list = []

    def _spy(me, enemies, mode):
        seen.append(mode)

    monkeypatch.setattr(capgap, "_DETECTORS", (_spy,))
    res = build_capability_gap("Lux", ["Malphite"], "  ARAM ")
    assert res["mode"] == "ARAM"
    assert seen == ["ARAM"]
    zero = build_capability_gap("Lux", ["Malphite"], 5)
    assert zero["mode"] == "SR"
    assert seen[-1] == "SR"


# --- RM-1859: a detector-level failure is visible -------------------------

def test_detector_failure_logs_warning_once_and_keeps_other_axes(monkeypatch, caplog):
    def _broken(me, enemies, mode):
        raise ImportError("agents.daemon_slayer.sustain unavailable")

    detectors = tuple(
        _broken if d is capgap._detect_sustain_gap else d for d in capgap._DETECTORS
    )
    monkeypatch.setattr(capgap, "_DETECTORS", detectors)
    monkeypatch.setattr(capgap, "_WARNED_DETECTOR_FAILURES", set())
    caplog.set_level(logging.DEBUG, logger="rc.ds_capability_gap")

    first = build_capability_gap("Lux", ["Malphite", "Sett", "MasterYi"])
    second = build_capability_gap("Lux", ["Malphite", "Sett", "MasterYi"])
    assert first["top_gap"] == "anti_tank"
    assert second == first

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "_broken" in msg
    assert "ImportError" in msg


def test_unexpected_base_exception_still_propagates(monkeypatch):
    def _interrupt(me, enemies, mode):
        raise KeyboardInterrupt

    monkeypatch.setattr(capgap, "_DETECTORS", (_interrupt,))
    with pytest.raises(KeyboardInterrupt):
        build_capability_gap("Lux", ["Malphite"])


# --- RM-1860: control characters and absurd lengths -----------------------

@pytest.mark.parametrize("bad", ["Lu\nx", "Lux\x00", "Lux\r\ncapgap-shadow: forged", "L" * 65])
def test_my_champion_with_control_chars_or_absurd_length_is_refused(bad):
    res = build_capability_gap(bad, ["Malphite", "Sett", "MasterYi"])
    _assert_strict_json(res)
    assert res["applies"] is False
    assert res["my_champion"] == ""


def test_edge_whitespace_is_still_stripped_not_refused():
    res = build_capability_gap("\tLux \n", ["Malphite", "Sett", "MasterYi"])
    assert res["my_champion"] == "Lux"
    assert res["top_gap"] == "anti_tank"
