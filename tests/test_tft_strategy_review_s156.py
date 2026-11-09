"""Session 156 (S6) TFT strategy review: coach statements the Set 18 data and
the live client contradict, fixed from RC's own data.

EVIDENCE
--------
- Level cap: the Set 18 HUD level box showed L10 as the max state (no x/y, Buy
  XP greyed) in ops/runtime/tft_qa/20261025-081234 game_0071..0080 (see
  tests/test_tft_coach_set18_xp_odds_s134.py), and the shop-odds table runs to
  L11. The coach told the model "Max feasible level this stage: 9" for every
  late stage, so it could never reason about a L10 board.
- Round structure: CommunityDragon map22 StageRoundData (Set 18, equal at
  16.21 and 16.22): stage 1 = carousel + 3 PvE rounds, stages 2+ = 7 rounds
  with the carousel at X-4 and the PvE round at X-7 (2-7 krugs, 3-7 wolves,
  4-7 raptors, 5-7 drake, 6-7 and 7-7 herald). tft/tft_data.py still carried
  the Set 14 transcription (carousel X-1, krugs 1-3, wolves 2-5 ...) in
  ROUND_EVENTS / PVE_ROUNDS, plus TEMPO_MILESTONES, ITEM_TIERS (a Set 14 S/A/B
  item tier list), COMPONENTS, EMBLEM_TRAITS, AUGMENT_TIERS and the interest
  constants. Zero modules read them (the engine guard bans them by name), they
  contradict the Set 18 data, and the tier list is the third-party-shaped claim
  RM-845 / RM-846 removed elsewhere, so they are deleted (nothing to derive).
- Double Up is a live queue, not a PBE feature: the engine's "(PBE)" label
  outlived the PBE engine RM-292 (b) deleted.

Names used, cited at the fix tree: tft/tft_data.py (module attributes listed
below); tft/tft_coach_engine.py `_build_prompt`; tft/tft_set.py `ENV_PIN`,
`clear_live_set`, `comp_state`; tft/tft_state_reader.py `_SET18_EVENTS`.
"""
from __future__ import annotations

import pytest

from tft import tft_data
from tft import tft_set

DEAD_GUIDE_TABLES = ("ROUND_EVENTS", "PVE_ROUNDS", "TEMPO_MILESTONES", "ITEM_TIERS",
                     "COMPONENTS", "EMBLEM_TRAITS", "AUGMENT_TIERS",
                     "INTEREST_BRACKETS", "INTEREST_PER_10")
LIVE_TABLES = ("TIER_ODDS", "TIER_ODDS_SET14", "TIER_ODDS_BY_SET", "POOL_SIZES",
               "UNITS_PER_COST", "XP_TO_LEVEL", "XP_TO_NEXT_SET18", "XP_BUY_COST",
               "tier_odds_for_set", "xp_to_next_level")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv(tft_set.ENV_PIN, raising=False)
    monkeypatch.setattr(tft_set, "comp_state", lambda root=None: {})
    tft_set.clear_live_set()
    yield
    tft_set.clear_live_set()


def _prompt(monkeypatch, **state) -> str:
    from tft import tft_coach_engine as eng
    monkeypatch.setenv(tft_set.ENV_PIN, "18")
    monkeypatch.setattr(eng, "_META_SECTION_CACHE", {})
    return eng._build_prompt({"stage": 4, "round": 2, "level": 7, **state})


def _max_level(msg: str) -> int:
    line = next(ln for ln in msg.splitlines() if ln.startswith("Max feasible level"))
    return int(line.rsplit(":", 1)[1])


@pytest.mark.parametrize("stage, want", [(1, 3), (2, 5), (3, 6), (4, 8), (5, 9),
                                         (6, 10), (7, 10), (8, 10)])
def test_max_feasible_level_reaches_the_client_cap_in_the_late_stages(stage, want, monkeypatch):
    assert _max_level(_prompt(monkeypatch, stage=stage, level=8)) == want


def test_no_stage_claims_more_than_the_ten_level_cap(monkeypatch):
    for stage in range(1, 10):
        assert _max_level(_prompt(monkeypatch, stage=stage)) <= 10


@pytest.mark.parametrize("name", DEAD_GUIDE_TABLES)
def test_the_set14_guide_tables_are_gone(name):
    assert not hasattr(tft_data, name)


@pytest.mark.parametrize("name", LIVE_TABLES)
def test_the_live_tables_and_accessors_stay(name):
    assert hasattr(tft_data, name)


def test_the_set18_round_schedule_still_matches_the_game_data_shape():
    from tft import tft_state_reader as sr
    ev = sr._SET18_EVENTS
    assert [ev[(1, r)] for r in (1, 2, 3, 4)] == ["carousel", "pve", "pve", "pve"]
    for stage in range(2, 8):
        assert ev[(stage, 4)] == "carousel" and ev[(stage, 7)] == "pve"
    assert (2, 1) not in sr._SET18_PVE and (1, 3) in sr._SET18_PVE


def test_double_up_is_not_labelled_pbe(monkeypatch):
    msg = _prompt(monkeypatch, variant="double_up")
    assert "MODE: DOUBLE UP" in msg and "(PBE)" not in msg
