"""True-audit regressions for core.ds_antitank_hint (RM-1854).

Findings pinned here (each test was RED before the fix):

1. LIVE-NAME SCORING. The live ARAM deterministic coach
   (dashboard/_deterministic_coaching.py) passes the Live Client
   ``championName`` - a DISPLAY name ("Kog'Maw", "K'Sante", "Jarvan IV") -
   straight into build_antitank_hint. The DS anti-tank registry keys on
   canonical DDragon ids ("KogMaw"), so the local player's score read 0.0 and
   a strong anti-tank kit was told to "itemize anti-tank" instead of
   "your kit shreds". The enemy side was already name-form safe
   (get_archetype_for resolves both forms).
2. NEVER-RAISES CONTRACT. The docstring says "never raises", but a non-str
   my_champion, a non-str enemy entry (the .strip() sat OUTSIDE the per-entry
   try) or a non-iterable enemy_champions raised AttributeError / TypeError.
3. MODE NORMALISATION. A non-str or whitespace mode was echoed verbatim.

Real DS registry + real archetype resolver; no network. Synthetic enemy
comps only.
"""
from __future__ import annotations

import json

import pytest

from core.ds_antitank_hint import ANTITANK_STRONG, build_antitank_hint

_TANKS = ["Malphite", "Ornn", "Sion", "Lux", "Ezreal"]


# --- 1. display-name scoring ---------------------------------------------------

@pytest.mark.parametrize(
    ("display", "ddragon_id"),
    [("Kog'Maw", "KogMaw"), ("K'Sante", "KSante"), ("Jarvan IV", "JarvanIV")],
)
def test_display_name_scores_like_its_ddragon_id(display, ddragon_id):
    by_id = build_antitank_hint(ddragon_id, _TANKS, mode="ARAM")
    by_name = build_antitank_hint(display, _TANKS, mode="ARAM")
    # Precondition: the canonical id IS a strong anti-tank kit.
    assert by_id["my_antitank_score"] >= ANTITANK_STRONG
    assert by_id["lean_in"] is True
    # The display name must reach the same verdict and score.
    assert by_name["my_antitank_score"] == by_id["my_antitank_score"]
    assert by_name["my_top_kind"] == by_id["my_top_kind"]
    assert by_name["lean_in"] is True
    assert by_name["recommend_antitank_items"] is False
    assert "your kit shreds" in by_name["hint"]


def test_display_name_echo_is_the_callers_form():
    """The my_champion echo stays the caller's (stripped) form - shape unchanged."""
    out = build_antitank_hint("  Kog'Maw ", _TANKS)
    assert out["my_champion"] == "Kog'Maw"


def test_unknown_name_still_passes_through_to_zero_score():
    out = build_antitank_hint("NotAChampion", _TANKS)
    assert out["my_champion"] == "NotAChampion"
    assert out["my_antitank_score"] == 0.0
    assert out["applies"] is True
    assert out["recommend_antitank_items"] is True


# --- 2. never-raises contract --------------------------------------------------

@pytest.mark.parametrize("bad", [5, 3.5, ["Vayne"], {"name": "Vayne"}, b"Vayne", True])
def test_non_str_my_champion_returns_zero_result(bad):
    out = build_antitank_hint(bad, _TANKS)
    assert out["applies"] is False
    assert out["my_champion"] == ""
    assert out["hint"] == ""
    json.dumps(out, allow_nan=False)


def test_non_str_enemy_entries_are_skipped_not_raised():
    out = build_antitank_hint(
        "Lux", [7, {"name": "Ornn"}, b"Sion", None, "", "Malphite", "Ornn"],
    )
    assert out["tanky_enemies"] == ["Malphite", "Ornn"]
    assert out["tanky_enemy_count"] == 2
    assert out["applies"] is True


@pytest.mark.parametrize("bad", [5, 2.0, object(), {"Malphite": 1}, "MalphiteOrnn"])
def test_non_list_enemy_champions_treated_as_empty(bad):
    out = build_antitank_hint("Vayne", bad)
    assert out["tanky_enemy_count"] == 0
    assert out["tanky_enemies"] == []
    assert out["applies"] is False
    assert out["my_champion"] == "Vayne"


def test_tuple_enemy_champions_still_accepted():
    out = build_antitank_hint("Lux", ("Malphite", "Ornn", "Lux"))
    assert out["tanky_enemies"] == ["Malphite", "Ornn"]
    assert out["applies"] is True


# --- 3. mode normalisation -----------------------------------------------------

@pytest.mark.parametrize(
    ("mode", "expected"),
    [(None, "SR"), ("", "SR"), ("   ", "SR"), (7, "SR"), (" ARAM ", "ARAM")],
)
def test_mode_normalised(mode, expected):
    assert build_antitank_hint("Vayne", _TANKS, mode=mode)["mode"] == expected
    assert build_antitank_hint("", _TANKS, mode=mode)["mode"] == expected


def test_result_is_strict_json_and_ascii():
    for champ in ("Kog'Maw", "Vayne", "Lux", ""):
        out = build_antitank_hint(champ, _TANKS, mode="ARAM")
        text = json.dumps(out, allow_nan=False)
        assert text.isascii()
