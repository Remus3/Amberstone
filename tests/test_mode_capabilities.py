# arch: tests for core.mode_capabilities fail-CLOSED truth table | section=tests | frozen=no
"""Tests for core.mode_capabilities - spec W ward-gate.

Spec: docs/ZOI_DISTRICT_ORCHESTRATION_PLAN.md section 5 (Ward-gate).
Ground truth grep-confirmed before scaffolding:
- core/game_snapshot.py:63-71 mode constants (MODE_SR="SR", ...)
- core/game_snapshot.py:74-95 mode_from_game_mode_string (defaults
  unrecognized input to MODE_SR - the fail-open hazard _normalize
  must reject)
- coach_integration/_sr_prompt.py:299 _build_user_prompt(gs, wave_state)
- coach_integration/_sr_prompt.py:438-439 dynamic ward prompt line
"""

import pytest

from core.game_snapshot import (
    MODE_ARAM,
    MODE_ARENA,
    MODE_BRAWL,
    MODE_JADE,
    MODE_SR,
    MODE_TFT,
)
from core.mode_capabilities import (
    MODE_CAPABILITIES,
    district_config,
    has_capability,
)


# ---------------------------------------------------------------------------
# has_wards truth table - SR is the ONLY warded mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["SR", "sr", "CLASSIC", "classic", "  SR  "])
def test_sr_forms_have_wards(mode):
    assert has_capability(mode, "has_wards") is True


@pytest.mark.parametrize(
    "mode",
    [
        # ARAM family incl. Mayhem (KIWI) and legacy ODIN
        "ARAM", "aram", "KIWI", "kiwi", "ODIN", "ARAM_UNRANKED_5X5",
        # Arena family
        "ARENA", "arena", "CHERRY", "cherry",
        # Brawl family (rotating modes)
        "BRAWL", "brawl", "URF", "ARURF", "NEXUSBLITZ", "ONEFORALL",
        # TFT
        "TFT", "tft",
    ],
)
def test_non_sr_modes_have_no_wards(mode):
    assert has_capability(mode, "has_wards") is False


# ---------------------------------------------------------------------------
# fail-CLOSED proof - unknown mode / cap / garbage all -> False, never raise
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode",
    [
        None, "", "   ", "GARBAGE", "NOT_A_MODE",
        # These fall through mode_from_game_mode_string's SR default but
        # are NOT SR spellings - must be rejected (fail-CLOSED), matching
        # the pre-existing game_mode == "CLASSIC" literal exactly.
        "PRACTICETOOL", "TUTORIAL", "TUTORIAL_MODULE_1",
        # canonical client mode has no in-game capabilities
        "client", "CLIENT",
        # non-string garbage
        42, 3.14, [], {}, ("SR",), object(), b"SR", True,
    ],
)
def test_unknown_mode_fails_closed(mode):
    assert has_capability(mode, "has_wards") is False


@pytest.mark.parametrize("cap", ["no_such_cap", "", None, 42, ["unhashable"]])
def test_unknown_cap_fails_closed(cap):
    assert has_capability("SR", cap) is False


def test_non_boolean_cap_value_is_not_true():
    # district_config is a config value, not a boolean capability -
    # a truthy non-True value must NOT leak through has_capability.
    assert has_capability("ARAM", "district_config") is False
    assert has_capability("TFT", "district_config") is False


# ---------------------------------------------------------------------------
# district_config - grid file stems resolving to config/minimap_grids/*.json
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("SR", "sr"), ("sr", "sr"), ("CLASSIC", "sr"),
        ("ARAM", "aram"), ("KIWI", "aram"),
        ("ARENA", "arena"), ("CHERRY", "arena"),
        ("BRAWL", "brawl"), ("URF", "brawl"),
        ("TFT", None), ("tft", None),
    ],
)
def test_district_config_values(mode, expected):
    assert district_config(mode) == expected


@pytest.mark.parametrize("mode", [None, "", "GARBAGE", "PRACTICETOOL", 123, []])
def test_district_config_fails_soft_none(mode):
    assert district_config(mode) is None


# ---------------------------------------------------------------------------
# table shape - keyed by the canonical game_snapshot constants
# ---------------------------------------------------------------------------


def test_table_keyed_by_canonical_constants():
    assert set(MODE_CAPABILITIES) == {
        MODE_SR, MODE_ARAM, MODE_ARENA, MODE_BRAWL, MODE_TFT, MODE_JADE,
    }
    for caps in MODE_CAPABILITIES.values():
        assert isinstance(caps, dict)
        assert isinstance(caps.get("has_wards"), bool)


def test_only_sr_has_wards_in_table():
    warded = [m for m, c in MODE_CAPABILITIES.items() if c.get("has_wards")]
    assert warded == [MODE_SR]


# ---------------------------------------------------------------------------
# consumer characterization - _sr_prompt dynamic ward line is has_wards-gated
# ---------------------------------------------------------------------------


def _min_gs(game_mode, ward_hint):
    return {
        "game_time": "12:00",
        "game_seconds": 720,
        "game_mode": game_mode,
        "ward_hint": ward_hint,
        "ally_comp": ["Ahri"],
        "enemy_comp": ["Zed"],
    }


def test_prompt_emits_ward_priority_for_classic():
    from coach_integration import _build_user_prompt
    out = _build_user_prompt(_min_gs("CLASSIC", "Ward river NOW"), "pushing")
    assert "Ward priority:" in out


@pytest.mark.parametrize("mode", ["CHERRY", "URF", "NEXUSBLITZ", "PRACTICETOOL"])
def test_prompt_suppresses_ward_priority_outside_sr(mode):
    # Non-ARAM modes reach the else branch at _sr_prompt.py:425-439;
    # the ward line must be capability-gated, not ward_hint-truthiness-only.
    from coach_integration import _build_user_prompt
    out = _build_user_prompt(_min_gs(mode, "Ward river NOW"), "pushing")
    assert "Ward priority:" not in out


def test_prompt_no_ward_line_when_hint_empty():
    from coach_integration import _build_user_prompt
    out = _build_user_prompt(_min_gs("CLASSIC", ""), "pushing")
    assert "Ward priority:" not in out
