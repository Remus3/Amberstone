"""LT-01 / RM-855 (session 134): the Set 18 round schedule and stage timing,
from a MEASURED live game, routed by set (and by queue, for the revival queue).

EVIDENCE (live client wins; sources are cross-checks only)
----------------------------------------------------------
Post-match QA of a live Set 18 normal game (queue 1090), report
ops/runtime/tft_qa/20261025-070350/QA_REPORT.md sections 2-3 (gitignored run
dir; frames re-read for this slice: the HUD round strip of game_0001 at 2-2 and
game_0080 at 6-1). Game clock zero = 12:03:00 UTC (LCU EOG gameLength 2097 s
counted back from PreEndOfGame); every time below is seconds after it.

- HUD strip, one icon per round: stages 2-6 have 7 rounds; carousel (gear) at
  x-4; PvE (diamond) at x-7; augment (card) at 2-1, 3-2 and 4-2; no augment
  card in the stage 5 or 6 strip. Stage 1 was not captured (recorder gap).
- CommunityDragon game data (map22 TFTSet18 StageRoundData, content 16.21,
  file dated 2026-10-21) agrees: stage 1 = Intro_Carousel + Intro1-3 (minion
  PvE), stages 2+ = Combat x3, Carousel, Combat x2, a PvE round. Facts only;
  nothing is vendored. Augment rounds are not in that structure.
- Pace: 2-3 to 6-1 is 26 rounds in about 1697 s (about 65 s per round). The
  Set 17 Double Up table (`_TIME_TO_ROUND`, about 51 s per round) matched 0 of
  the 28 observed rounds.
- S134 follow-up: a second QA game (20261025-081234) ran at about 60.5 s per
  round, so `_TIME_TO_ROUND_SET18` is now the MEAN of both games' starts and
  only a fallback behind the observed-round clock (RoundClock). This file
  keeps the game-1 view of it; tests/test_tft_round_clock_s134.py holds both
  games and the clock.

The LCU inventory (ops/runtime/tft_qa/LCU_TFT_INVENTORY.md section 3.10)
measured the running-set rule: tftsets.json `mDefaultSet` ("TFTSet18") paired
with the gameflow queue id, because queue 6110 "Set 17 (Normal)" runs Set 17.

Names used, cited at the fix tree: tft/tft_state_reader.py `_TIME_TO_ROUND`,
`_TIME_TO_ROUND_SET18`, `_time_table`, `_estimate_round`, `SCHEDULE_SET18`,
`SCHEDULE_GODS`, `SCHEDULE_NEUTRAL`, `round_schedule`, `RoundSchedule.fields`,
`TftStateReader._parse`; tft/tft_set.py `QUEUE_SETS`, `set_from_lcu`,
`note_live_set_from_lcu`, `resolve_set`, `clear_live_set`, `ENV_PIN`, `ROOT`;
tft/tft_data.py `tier_odds_for_set`, `TIER_ODDS`; tft/tft_pbe_data.py
`TIER_ODDS`.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from tft import tft_data
from tft import tft_pbe_data as pbe
from tft import tft_set
from tft import tft_state_reader as tsr

REPO_ROOT = Path(__file__).resolve().parent.parent

# (stage, round, first frame seen, last frame seen) - QA_REPORT.md section 2.
OBSERVED = [
    (2, 2, 319, 319), (2, 3, 344, 384), (2, 4, 409, 409), (2, 5, 434, 484),
    (2, 6, 509, 574), (2, 7, 599, 599),
    (3, 1, 624, 694), (3, 2, 714, 774), (3, 3, 799, 844), (3, 4, 869, 889),
    (3, 5, 909, 949), (3, 6, 974, 1034), (3, 7, 1054, 1079),
    (4, 1, 1099, 1164), (4, 2, 1189, 1259), (4, 3, 1284, 1344),
    (4, 4, 1364, 1364), (4, 5, 1389, 1449), (4, 6, 1469, 1534),
    (4, 7, 1554, 1574),
    (5, 1, 1599, 1624), (5, 2, 1669, 1714), (5, 3, 1739, 1804),
    (5, 4, 1824, 1824), (5, 5, 1844, 1909), (5, 6, 1934, 1979),
    (5, 7, 1999, 2019),
    (6, 1, 2039, 2084),
]
HUD_CAROUSEL = {(2, 4), (3, 4), (4, 4), (5, 4), (6, 4)}
HUD_PVE = {(2, 7), (3, 7), (4, 7), (5, 7), (6, 7)}
HUD_AUGMENT = {(2, 1), (3, 2), (4, 2)}

SET18 = "set18_measured"
GODS = "set17_realm_of_gods"
NEUTRAL = "neutral_unverified"

_GODS_NOTES = {
    "carousel": "REMOVED - replaced by Realm of the Gods",
    "realm_of_gods": "Stage X-4 = God offering. Stage 4-7 = God Boon armory.",
}


@pytest.fixture(autouse=True)
def _isolated_resolver(monkeypatch):
    monkeypatch.delenv(tft_set.ENV_PIN, raising=False)
    tft_set.clear_live_set()
    yield
    tft_set.clear_live_set()


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(obj, indent=1).encode("ascii") + b"\n")


@pytest.fixture
def two_sets(tmp_path, monkeypatch):
    """Set 17 meta carrying its Realm of the Gods record, Set 18 skeleton."""
    meta = tmp_path / "data" / "meta"
    _write(meta / "tft_set17_meta.json", {
        "_set": 17, "_note": "SKELETON - UNVERIFIED", "comps": {},
        "_patch_notes_17.1": dict(_GODS_NOTES),
    })
    _write(meta / "tft_set18_meta.json", {
        "_set": 18, "_note": "SKELETON - UNVERIFIED", "comps": {},
    })
    _write(meta / "tft_set18_cdragon.json", {"_set": 18, "champions": ["Kobuko"]})
    monkeypatch.setattr(tft_set, "ROOT", tmp_path)
    return tmp_path


def _reader(ocr=None) -> tsr.TftStateReader:
    rdr = object.__new__(tsr.TftStateReader)  # skip __init__ (OCR thread)
    rdr._my_name = ""
    rdr._last_level = 1
    rdr._confirmed_stage = 1
    rdr._confirmed_round = 1
    rdr._ocr_cache = dict(ocr or {})
    rdr._ocr_lock = threading.Lock()
    return rdr


def _raw(game_time: float) -> dict:
    return {
        "activePlayer": {"summonerName": "Me", "level": 5},
        "allPlayers": [{"summonerName": "Me", "items": [], "scores": {}}],
        "gameData": {"gameMode": "TFT", "gameTime": game_time, "mapNumber": 22},
    }


def _start(table, stage, rnd):
    for ms, st, rn in table:
        if (st, rn) == (stage, rnd):
            return ms
    raise AssertionError(f"{stage}-{rnd} not in the table")


# -- round types --------------------------------------------------------------

def test_set18_schedule_labels_every_observed_round_like_the_hud():
    sched = tsr.round_schedule(18, root=REPO_ROOT)
    assert sched.label == SET18 == tsr.SCHEDULE_SET18
    assert sched.gods == frozenset() and sched.tempo == {}
    rounds = {(s, r) for s, r, _, _ in OBSERVED} | HUD_CAROUSEL | HUD_PVE | HUD_AUGMENT
    for s, r in sorted(rounds):
        f = sched.fields(s, r)
        assert f["round_schedule"] == SET18
        assert f["is_god_round"] is False and f["tempo_note"] == ""
        if (s, r) in HUD_CAROUSEL:
            assert (f["round_event"], f["is_carousel"], f["is_pve"]) == ("carousel", True, False), (s, r)
        elif (s, r) in HUD_PVE:
            assert (f["round_event"], f["is_carousel"], f["is_pve"]) == ("pve", False, True), (s, r)
        elif (s, r) in HUD_AUGMENT:
            assert (f["round_event"], f["is_carousel"], f["is_pve"]) == ("augment", False, False), (s, r)
        else:
            assert (f["round_event"], f["is_carousel"], f["is_pve"]) == ("pvp", False, False), (s, r)


def test_set18_has_no_augment_after_stage_4_and_seven_rounds_per_stage():
    sched = tsr.round_schedule(18, root=REPO_ROOT)
    augments = {rk for rk, ev in sched.events.items() if ev == "augment"}
    assert augments == HUD_AUGMENT
    stages = {}
    for _, st, rn in tsr._TIME_TO_ROUND_SET18:
        stages.setdefault(st, []).append(rn)
    assert stages[1] == [1, 2, 3, 4]
    for st in range(2, 8):
        assert stages[st] == [1, 2, 3, 4, 5, 6, 7], st


def test_set18_stage_one_follows_the_game_data():
    """Not observed live (recorder gap); CommunityDragon StageRoundData:
    1-1 Intro_Carousel, 1-2..1-4 minion PvE rounds."""
    sched = tsr.round_schedule(18, root=REPO_ROOT)
    assert sched.fields(1, 1)["is_carousel"] is True
    for r in (2, 3, 4):
        assert sched.fields(1, r)["is_pve"] is True, r


def test_set17_schedule_still_has_no_plain_carousel_flag():
    """Routing by set: the Set 17 gods schedule keeps its own labels."""
    sched = tsr.round_schedule(17, root=REPO_ROOT)
    assert sched.label == GODS
    assert sched.fields(2, 4)["is_god_round"] is True
    assert sched.fields(2, 4)["is_carousel"] is False
    assert sched.fields(2, 4)["round_event"] == pbe.ROUND_EVENTS[(2, 4)]


def test_unknown_set_keeps_the_neutral_schedule():
    sched = tsr.round_schedule(19, root=REPO_ROOT)
    assert sched.label == NEUTRAL
    assert sched.fields(2, 4) == {
        "round_event": "pvp", "is_pve": False, "is_god_round": False,
        "is_carousel": False, "tempo_note": "", "round_schedule": NEUTRAL}


# -- timing -------------------------------------------------------------------

def _seq_index(stage, rnd):
    return [(s, r) for _, s, r in tsr._TIME_TO_ROUND_SET18].index((stage, rnd))


def test_set18_fallback_table_stays_within_two_rounds_of_game1():
    """S134 re-fit: the table is the two-game mean, so on game 1 alone (the
    slower game) it may run ahead, never by more than two rounds."""
    for s, r, first, last in OBSERVED:
        for t in (first, last):
            got = tsr._estimate_round(t, 18)
            assert abs(_seq_index(*got) - _seq_index(s, r)) <= 2, (s, r, t, got)


def test_set18_round_starts_never_lag_game1():
    """Game 2 ran faster than game 1 at every measured round, so the mean
    start of an observed round is never after game 1 first showed it."""
    table = tsr._TIME_TO_ROUND_SET18
    for s, r, first, _ in OBSERVED[1:]:
        assert _start(table, s, r) <= first, (s, r)


def test_set18_measured_pace_is_between_60_and_68_seconds_per_round():
    table = tsr._TIME_TO_ROUND_SET18
    span = _start(table, 6, 1) - _start(table, 2, 3)
    assert 60 <= span / 26 <= 68
    starts = [ms for ms, _, _ in table]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)
    assert table[0] == (0, 1, 1)
    assert _start(table, 6, 2) > _start(table, 6, 1) + 60


def test_set17_table_does_not_track_set18():
    """Characterisation of the QA verdict: the Set 17 table, if it were used
    for Set 18, names the observed round on none of the 28 first frames."""
    hits = sum(tsr._estimate_round(first, 17) == (s, r) for s, r, first, _ in OBSERVED)
    assert hits == 0


def test_time_table_is_routed_by_set():
    assert tsr._time_table(18) is tsr._TIME_TO_ROUND_SET18
    assert tsr._time_table(17) is tsr._TIME_TO_ROUND
    assert tsr._time_table(19) is tsr._TIME_TO_ROUND  # no measured table: legacy
    assert tsr._time_table(None) is tsr._TIME_TO_ROUND


# -- the reader, end to end ---------------------------------------------------

def test_reader_parses_a_set18_game_with_the_set18_table_and_labels(two_sets):
    """No per-round file in these raw dicts, so the reader uses the Set 18
    fallback table: one second into each observed round's table start."""
    assert tft_set.resolve_set() == 18
    rdr = _reader()
    for s, r, _, _ in OBSERVED:
        st = rdr._parse(_raw(_start(tsr._TIME_TO_ROUND_SET18, s, r) + 1))
        assert st["stage_round"] == f"{s}-{r}", (s, r)
        assert st["round_schedule"] == SET18
        assert st["is_carousel"] is ((s, r) in HUD_CAROUSEL), (s, r)
        assert st["is_pve"] is ((s, r) in HUD_PVE), (s, r)
        assert st["round_event"] == (
            "carousel" if (s, r) in HUD_CAROUSEL else "pve" if (s, r) in HUD_PVE
            else "augment" if (s, r) in HUD_AUGMENT else "pvp"), (s, r)


def test_reader_ocr_override_relabels_from_the_set18_schedule(two_sets):
    st = _reader({"stage_round": "3-4"})._parse(_raw(_start(tsr._TIME_TO_ROUND_SET18, 3, 3) + 1))
    assert st["stage_round"] == "3-4"
    assert st["is_carousel"] is True and st["round_event"] == "carousel"


def test_reader_under_a_set17_pin_keeps_the_set17_table(two_sets, monkeypatch):
    monkeypatch.setenv(tft_set.ENV_PIN, "17")
    t = _start(tsr._TIME_TO_ROUND, 2, 4) + 1
    st = _reader()._parse(_raw(t))
    assert st["stage_round"] == "2-4"
    assert st["round_schedule"] == GODS and st["is_god_round"] is True


# -- running set from the LCU: mDefaultSet paired with the queue id -----------

@pytest.mark.parametrize("default, queue, want", [
    ("TFTSet18", 1090, 18), ("TFTSet18", 1100, 18), ("TFTSet18", 1160, 18),
    ("TFTSet18", 6110, 17), ("TFTSet18", "6110", 17), (None, 6110, 17),
    ("TFTSet18", None, 18), (None, None, None), ("garbage", 1090, None),
    ("TFTSet18", "x", 18), ("TFTSet18", True, 18),
])
def test_set_from_lcu_pairs_default_set_with_queue(default, queue, want):
    assert tft_set.set_from_lcu(default, queue) == want


def test_queue_sets_holds_only_the_measured_revival_queue():
    assert tft_set.QUEUE_SETS == {6110: 17}


def test_lcu_route_drives_both_the_schedule_and_the_odds(two_sets):
    assert tft_set.note_live_set_from_lcu("TFTSet18", 1090) == 18
    assert tft_set.resolve_set() == 18
    assert tsr.round_schedule().label == SET18
    assert tft_data.tier_odds_for_set() is tft_data.TIER_ODDS

    assert tft_set.note_live_set_from_lcu("TFTSet18", 6110) == 17
    assert tft_set.resolve_set() == 17
    assert tsr.round_schedule().label == GODS
    assert tft_data.tier_odds_for_set() is pbe.TIER_ODDS


def test_lcu_route_with_nothing_usable_notes_nothing(two_sets):
    assert tft_set.note_live_set_from_lcu(None, None) is None
    assert tft_set.noted_live_set() is None
