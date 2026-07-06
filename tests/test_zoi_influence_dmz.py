"""Additive tests for core.zoi_influence compute_zoi capability + DMZ extension
(ZOI district orchestration, spec F, wave 3b).

CRITICAL: these are APPENDED tests. The pre-existing tests/test_zoi_influence.py
(esp. line 42: set(z.keys()) == {bubbles, demarcation, map_control}) is left
UNTOUCHED and must stay green. This file pins:
  (1) compute_zoi with the new kwargs at DEFAULTS is BYTE-IDENTICAL to the
      pre-edit output captured on a fixed dot fixture (no "dmz" key at all).
  (2) with ally_roster / enemy_roster provided, the payload gains a "dmz" key
      and folds capability_weight into per-dot radius.

Grep-confirmed surface: bubble dict core/zoi_influence.py:290-296
{team, cx, cy, r_frac, weight}; compute_zoi signature core/zoi_influence.py:258.
"""
import json

import pytest

from core.zoi_influence import compute_zoi

# Fixed dot fixture (identical to the pre-edit capture harness).
_DOTS = [
    {"team": "blue", "x_frac": 0.22, "y_frac": 0.78, "px": 44, "confidence": 0.82},
    {"team": "blue", "x_frac": 0.35, "y_frac": 0.61, "px": 38, "confidence": 0.7},
    {"team": "red", "x_frac": 0.79, "y_frac": 0.21, "px": 40, "confidence": 0.9},
    {"team": "red", "x_frac": 0.66, "y_frac": 0.44, "px": 36, "confidence": 0.75},
]

# Byte-identical snapshot captured from the UNMODIFIED compute_zoi (json.dumps
# sort_keys=True) BEFORE the wave-3b edit. Pins inertness of the new kwargs.
_PINNED = (
    '{"bubbles": [{"cx": 0.22, "cy": 0.78, "r_frac": 0.07439, "team": "blue", '
    '"weight": 36.08}, {"cx": 0.35, "cy": 0.61, "r_frac": 0.06747, "team": '
    '"blue", "weight": 26.6}, {"cx": 0.79, "cy": 0.21, "r_frac": 0.0713, '
    '"team": "red", "weight": 36.0}, {"cx": 0.66, "cy": 0.44, "r_frac": '
    '0.06549, "team": "red", "weight": 27.0}], "demarcation": {"ally_side": '
    '"left", "x1": 0.0617, "x2": 0.9314, "y1": 0.0, "y2": 1.0}, "map_control": '
    '{"action_quadrant": "bot_river", "ally_control_pct": 50, "line": "Map '
    'control 50%. Action bot river / dragon. ult rank 2 - force a fight"}}'
)


def test_defaults_byte_identical_to_pre_edit():
    z = compute_zoi(_DOTS, my_level=11, game_time_s=900)
    assert json.dumps(z, sort_keys=True) == _PINNED


def test_defaults_keyset_unchanged():
    z = compute_zoi(_DOTS, my_level=11, game_time_s=900)
    assert set(z.keys()) == {"bubbles", "demarcation", "map_control"}


def test_defaults_no_dmz_key_absent():
    # dmz key must be ABSENT (not None-valued) when rosters are not provided.
    z = compute_zoi(_DOTS, my_level=11, game_time_s=900)
    assert "dmz" not in z


def test_rosters_none_explicit_still_no_dmz():
    z = compute_zoi(
        _DOTS, my_level=11, game_time_s=900,
        ally_roster=None, enemy_roster=None,
    )
    assert "dmz" not in z
    assert set(z.keys()) == {"bubbles", "demarcation", "map_control"}


def test_rosters_provided_adds_dmz_key():
    z = compute_zoi(
        _DOTS, my_level=11, game_time_s=900,
        ally_roster=["Malphite", "Lulu"], enemy_roster=["Zed", "Jinx"],
    )
    assert "dmz" in z
    # dmz is either a valid payload or None (degenerate); key must be present.
    dmz = z["dmz"]
    assert dmz is None or set(dmz.keys()) == {"path", "band_w_frac"}
    # other keys still present + additive
    assert {"bubbles", "demarcation", "map_control"}.issubset(set(z.keys()))


def test_rosters_provided_emits_valid_dmz_on_two_team_fixture():
    z = compute_zoi(
        _DOTS, my_level=11, game_time_s=900,
        ally_roster=["Malphite", "Lulu"], enemy_roster=["Zed", "Jinx"],
    )
    dmz = z["dmz"]
    assert dmz is not None
    path = dmz["path"]
    assert len(path) >= 2
    for x, y in path:
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0


def test_capability_fold_changes_radius_vs_defaults():
    # With rosters, per-dot radius folds capability_weight, so at least one
    # bubble radius should differ from the no-roster baseline (unless every
    # champ weight lands exactly 1.0, which the mixed roster avoids).
    base = compute_zoi(_DOTS, my_level=11, game_time_s=900)
    withr = compute_zoi(
        _DOTS, my_level=11, game_time_s=900,
        ally_roster=["Malphite", "Lulu"], enemy_roster=["Zed", "Jinx"],
    )
    base_r = [b["r_frac"] for b in base["bubbles"]]
    with_r = [b["r_frac"] for b in withr["bubbles"]]
    assert base_r != with_r


def test_dot_champions_identity_tag_path():
    # When dot_champions=True each dot carries its own champion; capability is
    # per-dot, not team-mean. Must not raise, must still add dmz key.
    dots = [
        {"team": "blue", "x_frac": 0.22, "y_frac": 0.78, "px": 44,
         "confidence": 0.82, "champion": "Malphite"},
        {"team": "red", "x_frac": 0.79, "y_frac": 0.21, "px": 40,
         "confidence": 0.9, "champion": "Zed"},
    ]
    z = compute_zoi(
        dots, my_level=11, game_time_s=900,
        ally_roster=["Malphite"], enemy_roster=["Zed"],
        dot_champions=True,
    )
    assert "dmz" in z
    assert {"bubbles", "demarcation", "map_control"}.issubset(set(z.keys()))


def test_rosters_fail_soft_on_garbage_roster():
    # garbage roster entries must not raise; dmz key present, still additive.
    z = compute_zoi(
        _DOTS, my_level=11, game_time_s=900,
        ally_roster=[None, 42, ""], enemy_roster=["junk_champ_xyz"],
    )
    assert "dmz" in z
    assert {"bubbles", "demarcation", "map_control"}.issubset(set(z.keys()))
