"""S144-D-127..129 - the per-champion axis scorers keep their documented
"never raises" contract for a champion or mode token that is not a string.

Measured at HEAD before the fix (direct calls):
  * S144-D-127: compute_allyamp / antitank / cc_output / extendedduel /
    mobility / objdamage / scaling / sustain / threatrange / waveclear /
    zonecontrol each document "all-zero ... for an unregistered or blank
    champion (never raises)", but a list / dict / set champion raised
    TypeError (unhashable) out of ``<REGISTRY>.get(champion)``.
  * S144-D-128: compute_cc_pressure raised AttributeError for mode=5
    (``mode.upper()`` in ``_is_aram_mode``, whose docstring says it returns
    False for "any unknown mode token") and TypeError for a list / dict
    mode or champion.
  * S144-D-129: cc_conditional.get_conditional_entries ("Returns the empty
    tuple for unknown champions") and get_total_conditional_cc_seconds
    ("Never raises") raised TypeError on a list / dict champion.

Contract pinned here: a champion that is not a string reads as blank (the
same empty result a None champion gets); a mode that is not a string is
not an ARAM-family mode. Every string input is byte-identical.
"""

from __future__ import annotations

import importlib

import pytest

from agents.daemon_slayer import cc_conditional, cc_pressure

AXIS_MODULES = (
    "allyamp", "antitank", "cc_output", "extendedduel", "mobility",
    "objdamage", "scaling", "sustain", "threatrange", "waveclear",
    "zonecontrol",
)
JUNK_CHAMPIONS = (["Annie"], {"Annie": 1}, {"Annie"}, 5, 5.5, b"Annie")
JUNK_IDS = ("list", "dict", "set", "int", "float", "bytes")


def _scorer(name):
    mod = importlib.import_module(f"agents.daemon_slayer.{name}")
    return getattr(mod, f"compute_{name}")


# --- S144-D-127: the eleven axis scorers ---------------------------------------


@pytest.mark.parametrize("name", AXIS_MODULES)
@pytest.mark.parametrize("champ", JUNK_CHAMPIONS, ids=JUNK_IDS)
def test_axis_non_string_champion_reads_blank(name, champ):
    fn = _scorer(name)
    assert fn(champ) == fn(None)
    assert fn(champ).champion == ""


@pytest.mark.parametrize("name", AXIS_MODULES)
def test_axis_string_champion_unchanged(name):
    fn = _scorer(name)
    for champ in ("Annie", "Malphite", "Jinx", "NotAChampion"):
        res = fn(champ)
        assert res.champion == champ


# --- S144-D-128: cc_pressure ---------------------------------------------------


@pytest.mark.parametrize("mode", [5, 5.5, ["ARAM"], {"ARAM": 1}, b"ARAM"],
                         ids=["int", "float", "list", "dict", "bytes"])
def test_cc_pressure_non_string_mode_is_not_aram(mode):
    assert cc_pressure._is_aram_mode(mode) is False
    got = cc_pressure.compute_cc_pressure("Annie", mode)
    ref = cc_pressure.compute_cc_pressure("Annie", "SR")
    assert got.total_cc_seconds == ref.total_cc_seconds
    assert got.tenacity_mult == 1.0
    assert got.spells == ref.spells


@pytest.mark.parametrize("champ", JUNK_CHAMPIONS, ids=JUNK_IDS)
def test_cc_pressure_non_string_champion_reads_blank(champ):
    for kw in ({}, {"include_conditional": True}):
        got = cc_pressure.compute_cc_pressure(champ, **kw)
        assert got == cc_pressure.compute_cc_pressure(None, **kw)
        assert got.champion == ""
        assert got.total_cc_seconds == 0.0


def test_cc_pressure_string_inputs_unchanged():
    assert cc_pressure._is_aram_mode("ARAM") is True
    assert cc_pressure._is_aram_mode("aram_mayhem") is True
    assert cc_pressure._is_aram_mode("SR") is False
    assert cc_pressure._is_aram_mode("") is False
    assert cc_pressure._is_aram_mode(None) is False
    res = cc_pressure.compute_cc_pressure("Annie", "SR")
    assert res.champion == "Annie"
    assert res.total_cc_seconds > 0.0


# --- S144-D-129: cc_conditional getters ----------------------------------------


@pytest.mark.parametrize("champ", JUNK_CHAMPIONS, ids=JUNK_IDS)
def test_cc_conditional_non_string_champion_is_empty(champ):
    assert cc_conditional.get_conditional_entries(champ) == ()
    assert cc_conditional.get_total_conditional_cc_seconds(champ) == 0.0
    assert cc_conditional.get_total_conditional_cc_seconds(
        champ, apply_probability=False) == 0.0


def test_cc_conditional_string_champion_unchanged():
    champ = next(iter(cc_conditional._PER_SPELL_CC_CONDITIONAL))
    assert cc_conditional.get_conditional_entries(champ)
    assert cc_conditional.get_total_conditional_cc_seconds(champ) > 0.0
    assert cc_conditional.get_conditional_entries("NotAChampion") == ()
