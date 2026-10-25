"""Session 134 (Set 18 coach follow-up): the TFT coach prompt reads roll odds
and the XP-to-next-level table by the RESOLVED set, and the XP lookup is no
longer one level off.

EVIDENCE (XP)
-------------
The HUD level box ("Lvl. N  x/XP") of a live Set 18 normal game (queue 1090,
build rls-18.5), read off every game frame of ops/runtime/tft_qa/
20261025-070350/frames (QA_REPORT.md section 5 table). The denominator is the
XP needed AT that level to reach the next one; it was constant across every
frame at a level:

  L4 10 (game_0001_el0269 2/10 .. game_0006_el0384 6/10)
  L5 20 (game_0007_el0409 0/20 .. game_0014_el0574 6/20)
  L6 36 (game_0015_el0599 2/36 .. game_0030_el0924 34/36)
  L7 56 (game_0031_el0944 2/56 .. game_0040_el1139 20/56)
  L8 68 (game_0041_el1164 0/68 .. game_0064_el1689 62/68; 5-2 game_0061_el1619 60/68)
  L9 68 (game_0065_el1709 2/68 .. game_0080_el2034 10/68)

L1-L3 were never on screen (the recorder joined at 2-2, already L4) and L10
was never reached, so the Set 18 table carries L4-L9 only.

Cross-check, facts only, nothing vendored: Riot's TFT B-patch 18.2 notes as
reported by gamewave.fr (2026-09-15): "XP du Niveau 8 au 9 : 64 => 68",
"XP du Niveau 9 au 10 : 64 => 68", and the Level 7 -> 8 reduction kept
(18.2: 60 -> 56). All three equal the HUD.

THE OFF-BY-ONE
--------------
tft/tft_data.py XP_TO_LEVEL is keyed by the CURRENT level (its L4-L7 values
equal the HUD denominators above). tft/tft_coach_engine.py _build_prompt
read XP_TO_LEVEL[level + 1], so at L8 it told the model "XP to Lv9: 100XP"
(the L9 row) while the client needed 68 (Set 18) or 80 (that table's own L8
row).

THE ODDS
--------
_build_prompt imported tft_data.TIER_ODDS directly, so since LT-02 (TIER_ODDS
became the Set 18 table) a Set 17 game - the revival queue 6110 - was sent
Set 18 odds. It now reads tft_data.tier_odds_for_set(<resolved set>), the
accessor LT-01 / LT-02 route by set + queue (tft/tft_set.py
note_live_set_from_lcu -> resolve_set).

Names used, cited at the fix tree: tft/tft_data.py `XP_TO_LEVEL`,
`XP_TO_NEXT_SET18`, `XP_TO_NEXT_BY_SET`, `xp_to_next_level`, `XP_BUY_COST`,
`TIER_ODDS`, `tier_odds_for_set`; tft/tft_pbe_data.py `TIER_ODDS`; tft/tft_set.py
`ENV_PIN`, `clear_live_set`, `note_live_set_from_lcu`, `resolve_set`,
`comp_state`; tft/tft_coach_engine.py `_build_prompt`, `_META_SECTION_CACHE`.
"""
from __future__ import annotations

import ast
import math
import re
from pathlib import Path

import pytest

from tft import tft_data
from tft import tft_pbe_data as pbe
from tft import tft_set

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE = REPO_ROOT / "tft" / "tft_coach_engine.py"

# level -> XP needed at that level to reach the next (HUD denominator).
HUD_XP_SET18 = {4: 10, 5: 20, 6: 36, 7: 56, 8: 68, 9: 68}
# The pre-existing table, byte for byte (Set 14 transcription).
LEGACY_XP = {2: 2, 3: 6, 4: 10, 5: 20, 6: 36, 7: 56, 8: 80, 9: 100, 10: 120}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv(tft_set.ENV_PIN, raising=False)
    monkeypatch.setattr(tft_set, "comp_state", lambda root=None: {})
    tft_set.clear_live_set()
    yield
    tft_set.clear_live_set()


def _prompt(level: int, monkeypatch, *, pin=None, noted=None) -> str:
    from tft import tft_coach_engine as eng
    if pin is not None:
        monkeypatch.setenv(tft_set.ENV_PIN, str(pin))
    if noted is not None:
        assert tft_set.note_live_set_from_lcu(*noted) is not None
    monkeypatch.setattr(eng, "_META_SECTION_CACHE", {})
    return eng._build_prompt({"stage": 4, "round": 2, "level": level})


def _odds_line(row: dict) -> str:
    return "  ".join(f"{c}c={v:.0%}" for c, v in row.items() if v > 0)


# -- the XP table -------------------------------------------------------------

def test_set18_xp_table_is_the_measured_hud_denominators():
    assert tft_data.XP_TO_NEXT_SET18 == HUD_XP_SET18
    for level, xp in HUD_XP_SET18.items():
        assert tft_data.xp_to_next_level(level, 18) == xp, level


@pytest.mark.parametrize("level", [1, 2, 3, 10, 11, 0, -1])
def test_set18_levels_never_seen_in_client_have_no_value(level):
    """No other set's row is borrowed for an unmeasured Set 18 level."""
    assert tft_data.xp_to_next_level(level, 18) is None


def test_earlier_sets_keep_the_existing_table_intact():
    assert tft_data.XP_TO_LEVEL == LEGACY_XP
    for set_n in (14, 17):
        for level, xp in LEGACY_XP.items():
            assert tft_data.xp_to_next_level(level, set_n) == xp, (set_n, level)
    assert tft_data.XP_TO_NEXT_BY_SET[18] is tft_data.XP_TO_NEXT_SET18
    assert tft_data.XP_TO_NEXT_BY_SET[14] is tft_data.XP_TO_LEVEL


def test_unknown_set_gets_no_xp_value():
    assert tft_data.xp_to_next_level(8, 19) is None
    assert tft_data.xp_to_next_level("8", 18) is None
    assert tft_data.xp_to_next_level(True, 18) is None


def test_xp_accessor_defaults_to_the_resolved_set(monkeypatch):
    monkeypatch.setattr(tft_set, "resolve_set", lambda *a, **k: 18)
    assert tft_data.xp_to_next_level(8) == 68
    monkeypatch.setattr(tft_set, "resolve_set", lambda *a, **k: 17)
    assert tft_data.xp_to_next_level(8) == 80


# -- the coach prompt: XP line, no off-by-one ---------------------------------

def _xp_line(level: int, xp: int) -> str:
    buys = math.ceil(xp / tft_data.XP_BUY_COST)
    gold = buys * tft_data.XP_BUY_COST
    return (f"XP to Lv{level + 1}: {xp}XP = {buys} buys "
            f"({gold}g at {tft_data.XP_BUY_COST}g each)")


@pytest.mark.parametrize("level", sorted(HUD_XP_SET18))
def test_set18_prompt_states_the_hud_xp_for_the_current_level(level, monkeypatch):
    msg = _prompt(level, monkeypatch, pin=18)
    assert _xp_line(level, HUD_XP_SET18[level]) in msg


def test_l8_prompt_no_longer_reads_the_l9_row(monkeypatch):
    """The live failure: at L8 the HUD showed x/68, the prompt said 100."""
    msg = _prompt(8, monkeypatch, pin=18)
    assert "XP to Lv9: 68XP" in msg
    assert "100XP" not in msg and "80XP" not in msg


def test_set17_prompt_reads_its_table_at_the_current_level(monkeypatch):
    msg = _prompt(8, monkeypatch, noted=("TFTSet18", 6110))
    assert _xp_line(8, 80) in msg
    assert "XP to Lv9: 100XP" not in msg


def test_buys_cover_the_requirement(monkeypatch):
    """10 XP is 3 buys (12g), not 2 buys (8 XP, one level short)."""
    msg = _prompt(4, monkeypatch, pin=18)
    assert "XP to Lv5: 10XP = 3 buys (12g at 4g each)" in msg


@pytest.mark.parametrize("level", [1, 2, 3, 10])
def test_unmeasured_set18_level_adds_no_xp_line(level, monkeypatch):
    msg = _prompt(level, monkeypatch, pin=18)
    assert "XP to Lv" not in msg


# -- the coach prompt: roll odds by the resolved set ---------------------------

def test_set18_prompt_carries_set18_odds(monkeypatch):
    msg = _prompt(7, monkeypatch, pin=18)
    assert f"Roll odds at Lv7: {_odds_line(tft_data.TIER_ODDS[7])}" in msg
    assert f"Roll odds at Lv8: {_odds_line(tft_data.TIER_ODDS[8])}" in msg


def test_set17_game_gets_set17_odds_not_set18(monkeypatch):
    """Revival queue 6110 under a TFTSet18 client: Set 17 odds (LT-01 route)."""
    msg = _prompt(7, monkeypatch, noted=("TFTSet18", 6110))
    assert tft_set.resolve_set() == 17
    assert f"Roll odds at Lv7: {_odds_line(pbe.TIER_ODDS[7])}" in msg
    assert _odds_line(tft_data.TIER_ODDS[7]) not in msg
    assert pbe.TIER_ODDS[7] != tft_data.TIER_ODDS[7]  # the test can fail


def test_set17_env_pin_also_routes_the_odds(monkeypatch):
    msg = _prompt(8, monkeypatch, pin=17)
    assert f"Roll odds at Lv8: {_odds_line(pbe.TIER_ODDS[8])}" in msg


def test_a_set_without_an_odds_table_gets_no_odds_line(monkeypatch):
    from tft import tft_coach_engine as eng
    monkeypatch.setattr(tft_set, "resolve_set", lambda *a, **k: 19)
    monkeypatch.setattr(eng, "_META_SECTION_CACHE", {})
    msg = eng._build_prompt({"stage": 4, "round": 2, "level": 7})
    assert "Roll odds" not in msg and "XP to Lv" not in msg


def test_prompt_resolves_the_set_once(monkeypatch):
    from tft import tft_coach_engine as eng
    calls = []

    def _resolve(*a, **k):
        calls.append(1)
        return 18

    monkeypatch.setattr(tft_set, "resolve_set", _resolve)
    monkeypatch.setattr(eng, "_META_SECTION_CACHE", {})
    monkeypatch.setattr(eng, "_set_has_gods", lambda: False)
    monkeypatch.setattr(eng, "_meta_verified", lambda: False)
    eng._build_prompt({"stage": 4, "round": 2, "level": 7})
    assert len(calls) == 1


def test_engine_never_imports_a_raw_set_table():
    """Odds and XP go through the set-aware accessors only."""
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    raw = {"TIER_ODDS", "TIER_ODDS_SET14", "XP_TO_LEVEL", "XP_TO_NEXT_SET18"}
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "tft_data" in node.module:
            hits += [a.name for a in node.names if a.name in raw]
        if isinstance(node, ast.Attribute) and node.attr in raw:
            hits.append(node.attr)
    assert hits == []
    src = ENGINE.read_text(encoding="utf-8")
    assert re.search(r"\btier_odds_for_set\b", src)
    assert re.search(r"\bxp_to_next_level\b", src)
