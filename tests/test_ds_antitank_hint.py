# tests/test_ds_antitank_hint.py
"""Deterministic tests for core.ds_antitank_hint.build_antitank_hint.

No network calls. Uses real DS antitank registry and real archetype resolver.

Champion archetype ground truth (DDragon tags, verified live 2026-06-06):
  Malphite  -> tank
  Ornn      -> tank
  Sion      -> tank    (also has antitank_score ~1.209 itself)
  Sett      -> bruiser
  Leona     -> tank
  Darius    -> bruiser
  Vayne     -> carry   (antitank_score ~0.95 > ANTITANK_STRONG=0.8 -> lean_in)
  Lux       -> mage    (antitank_score 0.0 -> recommend_antitank_items)
"""
import sys
import os

# Ensure project root is on the path.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.ds_antitank_hint import (
    build_antitank_hint,
    HIGH_HP_ENEMY_MIN,
    ANTITANK_STRONG,
)

# Robust tank / bruiser enemy ids (DDragon tag-verified).
_TANKY_ENEMIES = ["Malphite", "Ornn", "Sion", "Sett", "Leona"]
# Non-tanky filler for "not enough tanks" test.
_SQUISH_ENEMIES = ["Lux", "Ezreal", "Jinx"]

_REQUIRED_KEYS = {
    "applies",
    "my_champion",
    "mode",
    "my_antitank_score",
    "my_top_kind",
    "shreds_resist",
    "tanky_enemy_count",
    "tanky_enemies",
    "lean_in",
    "recommend_antitank_items",
    "hint",
}


# ---------------------------------------------------------------------------
# (a) Tanky comp + strong anti-tank carry -> applies True, lean_in True
# ---------------------------------------------------------------------------

def test_lean_in_vayne_vs_tank_heavy():
    """Vayne (antitank_score ~0.95) vs 3 tanks -> lean_in, hint mentions shred."""
    result = build_antitank_hint("Vayne", ["Malphite", "Ornn", "Sett", "Lux", "Ezreal"])
    assert result["applies"] is True, "Should apply vs tank-heavy comp"
    assert result["lean_in"] is True, "Vayne antitank_score should clear ANTITANK_STRONG"
    assert result["recommend_antitank_items"] is False
    assert result["hint"] != "", "Hint should be non-empty when applies"
    # Hint should contain something about the mechanic kind (MAX_HP for Vayne)
    assert "shreds" in result["hint"] or "kit" in result["hint"], (
        "lean_in hint should mention kit/shred"
    )
    assert result["tanky_enemy_count"] >= HIGH_HP_ENEMY_MIN
    assert result["my_antitank_score"] >= ANTITANK_STRONG
    assert result["my_champion"] == "Vayne"
    assert result["mode"] == "SR"


# ---------------------------------------------------------------------------
# (b) Tanky comp + low/zero antitank champ -> applies True, recommend_items True
# ---------------------------------------------------------------------------

def test_recommend_items_lux_vs_tank_heavy():
    """Lux (antitank_score 0.0) vs 3 tanks -> recommend_antitank_items."""
    result = build_antitank_hint("Lux", ["Malphite", "Ornn", "Sett", "Jinx", "Ezreal"])
    assert result["applies"] is True
    assert result["lean_in"] is False
    assert result["recommend_antitank_items"] is True
    assert "itemize" in result["hint"], "Hint should say itemize anti-tank"
    assert "anti-tank" in result["hint"]
    assert result["my_antitank_score"] == 0.0
    assert result["tanky_enemy_count"] >= HIGH_HP_ENEMY_MIN


# ---------------------------------------------------------------------------
# (c) Fewer than HIGH_HP_ENEMY_MIN tanky enemies -> applies False, hint ""
# ---------------------------------------------------------------------------

def test_not_applies_one_tank():
    """Only 1 tanky enemy -> applies=False, hint empty."""
    result = build_antitank_hint("Vayne", ["Malphite", "Lux", "Ezreal", "Jinx", "Caitlyn"])
    assert result["applies"] is False
    assert result["lean_in"] is False
    assert result["recommend_antitank_items"] is False
    assert result["hint"] == ""
    assert result["tanky_enemy_count"] < HIGH_HP_ENEMY_MIN


def test_not_applies_all_squish():
    """All-squish enemy comp -> applies=False."""
    result = build_antitank_hint("Vayne", _SQUISH_ENEMIES)
    assert result["applies"] is False
    assert result["hint"] == ""


# ---------------------------------------------------------------------------
# (d) Blank my_champion -> applies False, no raise
# ---------------------------------------------------------------------------

def test_blank_my_champion_empty_string():
    result = build_antitank_hint("", ["Malphite", "Ornn"])
    assert result["applies"] is False
    assert result["my_antitank_score"] == 0.0
    assert result["my_top_kind"] == ""
    assert result["shreds_resist"] is False
    assert result["hint"] == ""


def test_blank_my_champion_none():
    """None my_champion is coerced to blank - no raise."""
    result = build_antitank_hint(None, ["Malphite", "Ornn"])  # type: ignore[arg-type]
    assert result["applies"] is False
    assert result["hint"] == ""


# ---------------------------------------------------------------------------
# (e) Return dict contains all required keys
# ---------------------------------------------------------------------------

def test_return_keys_complete():
    """All required keys present regardless of which branch fires."""
    for champion, enemies in [
        ("Vayne", ["Malphite", "Ornn", "Sett"]),
        ("Lux", ["Malphite", "Ornn"]),
        ("Vayne", ["Lux"]),
        ("", ["Malphite"]),
    ]:
        result = build_antitank_hint(champion, enemies)
        missing = _REQUIRED_KEYS - set(result.keys())
        assert not missing, f"Missing keys for ({champion!r}, ...): {missing}"


# ---------------------------------------------------------------------------
# (f) Edge cases - None enemy list, blank entries in list, unknown champ
# ---------------------------------------------------------------------------

def test_none_enemy_list():
    """None enemy_champions -> treated as empty, no raise."""
    result = build_antitank_hint("Vayne", None)
    assert result["applies"] is False
    assert result["tanky_enemy_count"] == 0
    assert result["tanky_enemies"] == []


def test_blank_entries_in_enemy_list_skipped():
    """Blank/None entries in enemy list are ignored, valid tanks counted."""
    result = build_antitank_hint("Lux", ["Malphite", "", None, "Ornn", "  "])  # type: ignore[list-item]
    # Malphite + Ornn = 2 tanks -> applies
    assert result["applies"] is True
    assert result["tanky_enemy_count"] == 2


def test_unknown_my_champion_treated_as_zero():
    """Unknown champion id -> antitank_score 0.0, applies if comp is tanky."""
    result = build_antitank_hint("DefinitelyFakeChampXYZ", ["Malphite", "Ornn", "Sett"])
    assert result["applies"] is True
    assert result["my_antitank_score"] == 0.0
    assert result["lean_in"] is False
    assert result["recommend_antitank_items"] is True


def test_unknown_enemy_treated_as_nontanky():
    """Unknown enemy champion id does not crash and is not counted as tanky."""
    result = build_antitank_hint("Vayne", ["Malphite", "FakeChampXYZ", "Lux"])
    # Only Malphite is tanky -> 1 < HIGH_HP_ENEMY_MIN -> applies=False
    assert result["applies"] is False
    assert "FakeChampXYZ" not in result["tanky_enemies"]


# ---------------------------------------------------------------------------
# (g) Tanky enemy count accuracy
# ---------------------------------------------------------------------------

def test_tanky_enemy_count_accuracy():
    """tanky_enemies list + count match the expected classified set."""
    enemies = ["Malphite", "Ornn", "Sett", "Lux", "Ezreal"]
    result = build_antitank_hint("Vayne", enemies)
    assert result["tanky_enemy_count"] == len(result["tanky_enemies"])
    assert "Malphite" in result["tanky_enemies"]
    assert "Ornn" in result["tanky_enemies"]
    assert "Sett" in result["tanky_enemies"]
    assert "Lux" not in result["tanky_enemies"]
    assert "Ezreal" not in result["tanky_enemies"]


# ---------------------------------------------------------------------------
# (h) Mode is threaded through
# ---------------------------------------------------------------------------

def test_mode_aram_passed_through():
    result = build_antitank_hint("Vayne", ["Malphite", "Ornn"], mode="ARAM")
    assert result["mode"] == "ARAM"
