"""S134: which TFT round is it? An OBSERVED round start first, the time table
only as a fallback - and the Set 18 table re-fit on two live games.

EVIDENCE
--------
Two live Set 18 normal games, every game frame's HUD stage label read (the
frame names carry the recorder's elapsed seconds; game clock = elapsed +
offset, zero from the LCU EOG gameLength):

- ops/runtime/tft_qa/20261025-070350 (QA_REPORT.md section 2): recorder
  start 12:03:50, clock zero 12:03:00 UTC -> offset 50 s; joined at 2-2.
- ops/runtime/tft_qa/20261025-081234 (QA_REPORT.md section 3): recorder
  start 13:12:34.5, clock zero 13:12:30.8 UTC -> offset 3.7 s.

A round's start = midpoint of the previous round's last frame and its own
first frame. The games ran at different paces (2-3..6-1 about 65 and 60.5 s
per round; 6-1 began at 2029 and 1849 s): the game-1-only table named the
HUD round on 10 of game 2's 80 frames and was 3 rounds behind by 6-1. No
fixed table can track both, so the table is re-fit to the MEAN start and
becomes the fallback.

The standalone client's per-round stats file (tft/tft_standalone.py; the
synthesized raw dict carries rc_standalone.game_length_s) is rewritten at
each planning phase. Watched passively through a third live Set 18 game
(2026-10-25, about 14:03-14:18 UTC; health values only, no names):
gameLengthSeconds 582, 647, 741, 821, 932, 1010, 1073, 1138, 1239, 1311,
1420 - one rewrite per round, none at a carousel (821 -> 932 and
1311 -> 1420 each span an x-3 and the x-4 carousel), and 582 -> 647 kept
all 8 healths (a PvE round). The round clock
(tft/tft_state_reader.py RoundClock) counts those starts; the PvE pin
corrects a late first placement.

Names used, cited at the fix tree: tft/tft_state_reader.py
`_TIME_TO_ROUND_SET18`, `_time_table`, `_estimate_round`, `_row_index`,
`_no_planning_rounds`, `RoundClock` (`note_start`, `round_at`),
`_MISSED_GAP_S`, `_observed_round_start`, `round_schedule`,
`RoundSchedule.pve`, `TftStateReader._parse`; tft/tft_standalone.py
`SOURCE_TAG`; tft/tft_set.py `ENV_PIN`, `clear_live_set`, `resolve_set`.
"""
from __future__ import annotations

import statistics
import threading

import pytest

from tft import tft_set
from tft import tft_standalone
from tft import tft_state_reader as tsr

# (HUD label, recorder elapsed s of every game frame showing it)
GAME1_OFFSET = 50.0
GAME1 = [
    ("2-2", (269,)), ("2-3", (294, 314, 334)), ("2-4", (359,)), ("2-5", (384, 409, 434)),
    ("2-6", (459, 479, 504, 524)), ("2-7", (549,)), ("3-1", (574, 599, 619, 644)),
    ("3-2", (664, 684, 704, 724)), ("3-3", (749, 774, 794)), ("3-4", (819, 839)),
    ("3-5", (859, 879, 899)), ("3-6", (924, 944, 964, 984)), ("3-7", (1004, 1029)),
    ("4-1", (1049, 1069, 1094, 1114)), ("4-2", (1139, 1164, 1184, 1209)),
    ("4-3", (1234, 1254, 1274, 1294)), ("4-4", (1314,)), ("4-5", (1339, 1359, 1379, 1399)),
    ("4-6", (1419, 1444, 1464, 1484)), ("4-7", (1504, 1524)), ("5-1", (1549, 1574)),
    ("5-2", (1619, 1639, 1664)), ("5-3", (1689, 1709, 1729, 1754)), ("5-4", (1774,)),
    ("5-5", (1794, 1814, 1834, 1859)), ("5-6", (1884, 1904, 1929)), ("5-7", (1949, 1969)),
    ("6-1", (1989, 2009, 2034)),
]
GAME2_OFFSET = 3.7
GAME2 = [
    ("1-3", (70, 90)), ("1-4", (110, 135)), ("2-1", (160, 180, 200)), ("2-2", (225, 250, 270)),
    ("2-3", (290, 310, 330)), ("2-4", (355, 375)), ("2-5", (395, 415, 435)),
    ("2-6", (460, 480)), ("2-7", (540,)), ("3-1", (565, 585, 605, 625)),
    ("3-2", (645, 670, 715)), ("3-3", (735, 755, 775)), ("3-4", (795, 815)),
    ("3-5", (840, 860, 880)), ("3-6", (900, 920, 945)), ("3-7", (970, 990)),
    ("4-1", (1015, 1035, 1055)), ("4-2", (1080, 1100, 1120, 1140)), ("4-3", (1160, 1185)),
    ("4-4", (1230, 1255)), ("4-5", (1275, 1300)), ("4-6", (1325, 1345, 1370)),
    ("4-7", (1395, 1420)), ("5-1", (1440, 1465, 1485)), ("5-2", (1510, 1535, 1555)),
    ("5-3", (1575, 1595, 1615)), ("5-4", (1640, 1660)), ("5-5", (1685, 1710, 1730)),
    ("5-6", (1750, 1770, 1790)), ("5-7", (1815, 1835)), ("6-1", (1855, 1875)),
]
GAMES = {"game1": (GAME1, GAME1_OFFSET), "game2": (GAME2, GAME2_OFFSET)}

# Third game: (gameLengthSeconds at each rewrite, every player's health).
WATCHED = [
    (582, (96, 87, 81, 97, 87, 84, 96, 83)),
    (647, (96, 87, 81, 97, 87, 84, 96, 83)),
    (741, (96, 87, 70, 97, 79, 75, 96, 74)),
    (821, (96, 80, 61, 97, 69, 75, 96, 66)),
    (932, (96, 68, 54, 98, 69, 75, 87, 58)),
    (1010, (96, 68, 54, 86, 60, 66, 87, 51)),
    (1073, (96, 61, 46, 86, 51, 66, 76, 51)),
    (1138, (96, 61, 46, 86, 51, 66, 69, 44)),
    (1239, (96, 61, 33, 77, 43, 66, 69, 35)),
    (1311, (96, 51, 24, 78, 43, 54, 58, 20)),
    (1420, (96, 51, 13, 68, 28, 54, 46, 20)),
]
# The only labelling consistent with the observations: 582 -> 647 kept every
# health (PvE, so 2-7), and the two long gaps 821 -> 932 (111 s) and
# 1311 -> 1420 (109 s) are each an x-3 plus the x-4 carousel.
WATCHED_ROUNDS = ["2-7", "3-1", "3-2", "3-3", "3-5", "3-6", "3-7", "4-1",
                  "4-2", "4-3", "4-5"]
# What the clock can say AT each start: the first is the table's placement
# (3-1; this game ran slower than both QA games); the PvE pin learns at 647
# that 582 was 2-7, and every later start is right.
WATCHED_AS_SEEN = ["3-1"] + WATCHED_ROUNDS[1:]

TABLE = tsr._TIME_TO_ROUND_SET18
SEQ = [f"{s}-{r}" for _, s, r in TABLE]
IDX = {lab: i for i, lab in enumerate(SEQ)}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv(tft_set.ENV_PIN, raising=False)
    tft_set.clear_live_set()
    yield
    tft_set.clear_live_set()


def _frames(game):
    runs, off = GAMES[game]
    return [(el + off, lab) for lab, els in runs for el in els]


def _starts(game):
    fr = _frames(game)
    return {b: (t0 + t1) / 2 for (t0, a), (t1, b) in zip(fr, fr[1:]) if a != b}


def _sched():
    return tsr.round_schedule(18)


def _skip():
    return tsr._no_planning_rounds(_sched())


def _rk(lab):
    s, r = lab.split("-")
    return int(s), int(r)


def _lab(stage_round) -> str:
    s, r = stage_round
    return f"{s}-{r}"


def _row(lab):
    return next(ms for ms, s, r in TABLE if (s, r) == _rk(lab))


# -- the re-fit table ------------------------------------------------------------

def test_table_shape():
    assert [(s, r) for _, s, r in TABLE][:4] == [(1, 1), (1, 2), (1, 3), (1, 4)]
    assert len(TABLE) == 4 + 6 * 7
    starts = [ms for ms, _, _ in TABLE]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)
    assert tsr._time_table(18) is TABLE


def test_measured_rows_are_the_mean_of_both_games():
    s1, s2 = _starts("game1"), _starts("game2")
    both = set(s1) & set(s2)
    assert len(both) == 27  # 2-3 .. 6-1
    for lab in both:
        assert abs(_row(lab) - (s1[lab] + s2[lab]) / 2) <= 1, lab
        assert min(s1[lab], s2[lab]) - 1 <= _row(lab) <= max(s1[lab], s2[lab]) + 1


def test_early_rows_come_from_game2():
    s2 = _starts("game2")
    for lab in ("1-4", "2-1", "2-2"):
        assert abs(_row(lab) - s2[lab]) <= 1, lab


def test_the_two_games_really_differ_in_pace():
    s1, s2 = _starts("game1"), _starts("game2")
    pace1 = (s1["6-1"] - s1["2-3"]) / 26
    pace2 = (s2["6-1"] - s2["2-3"]) / 26
    assert pace1 - pace2 > 3  # about 65.3 vs 60.2 s per round
    assert s1["6-1"] - s2["6-1"] > 150


@pytest.mark.parametrize("game", sorted(GAMES))
def test_table_alone_stays_within_two_rounds_of_every_frame(game):
    errs = [IDX[_lab(tsr._estimate_round(t, 18))] - IDX[lab] for t, lab in _frames(game)]
    assert max(abs(e) for e in errs) <= 2
    assert statistics.mean(abs(e) for e in errs) <= 1.0


# -- the round clock on both QA games ----------------------------------------------

def _clock_labels(game):
    """Feed each game's planning-round starts (no carousel start: the file
    is not rewritten there) to a fresh clock, read it at every frame."""
    skip = _skip()
    bounds = sorted((t, lab) for lab, t in _starts(game).items() if _rk(lab) not in skip)
    clk, out, bi = tsr.RoundClock(), [], 0
    for t, lab in _frames(game):
        while bi < len(bounds) and bounds[bi][0] <= t:
            clk.note_start(game, bounds[bi][0], TABLE, skip)
            bi += 1
        out.append((_lab(clk.round_at(t, TABLE, skip)), lab, t))
    return out


def test_clock_names_every_frame_of_game2():
    got = _clock_labels("game2")
    assert [g for g, _, _ in got] == [lab for _, lab, _ in got]


def test_clock_on_game1_misses_only_the_join_and_two_carousel_edges():
    got = _clock_labels("game1")
    misses = [(lab, g) for g, lab, _ in got if g != lab]
    # 2-2: before the first observed start (the table answers); 4-3 / 5-3:
    # a frame in the last seconds of a long x-3, after its table length.
    assert misses == [("2-2", "2-3"), ("4-3", "4-4"), ("5-3", "5-4")]
    assert sum(g == lab for g, lab, _ in got) == 77


def test_clock_beats_the_table_on_both_games():
    for game in GAMES:
        clock_hits = sum(g == lab for g, lab, _ in _clock_labels(game))
        table_hits = sum(_lab(tsr._estimate_round(t, 18)) == lab
                         for t, lab in _frames(game))
        assert clock_hits >= 77 > 2 * table_hits, (game, clock_hits, table_hits)


# -- the round clock on the watched third game -------------------------------------

def _watched(use_hp):
    sched, skip = _sched(), _skip()
    clk, out = tsr.RoundClock(), []
    for t, hp in WATCHED:
        clk.note_start("g3", t, TABLE, skip, hp=hp if use_hp else None, pve=sched.pve)
        out.append(_lab(clk.round_at(t + 1, TABLE, skip)))
    return out


def test_pve_pin_corrects_a_late_first_placement():
    assert _watched(use_hp=True) == WATCHED_AS_SEEN


def test_without_the_health_signal_a_late_join_stays_one_round_off():
    """The table placed 582 at 3-1; counting alone keeps that error at every
    later start, the PvE pin removes it."""
    got = _watched(use_hp=False)
    assert got[0] == "3-1"
    assert got[:-1] == WATCHED_ROUNDS[1:]  # always one planning round ahead


# -- RoundClock units ---------------------------------------------------------------

def test_no_observation_falls_back_to_the_table():
    clk = tsr.RoundClock()
    assert clk.round_at(_row("3-2") + 1, TABLE) == (3, 2)


def test_first_start_is_placed_on_the_nearest_planning_round():
    clk = tsr.RoundClock()
    clk.note_start("g", _row("3-4") + 2, TABLE, _skip())  # nearest row is a carousel
    assert clk.round_at(_row("3-4") + 3, TABLE, _skip()) in {(3, 3), (3, 5)}
    assert clk.round_at(_row("3-4") + 3, TABLE, _skip()) != (3, 4)


def test_each_later_start_is_the_next_round_and_carousels_are_skipped():
    skip = _skip()
    clk = tsr.RoundClock()
    clk.note_start("g", 1000.0, TABLE, skip)
    clk.note_start("g", 1000.0, TABLE, skip)  # the same rewrite read twice
    first = clk.round_at(1000.5, TABLE, skip)
    clk.note_start("g", 1060.0, TABLE, skip)
    second = clk.round_at(1060.5, TABLE, skip)
    assert IDX[_lab(second)] == IDX[_lab(first)] + 1 or (
        IDX[_lab(second)] == IDX[_lab(first)] + 2
        and _rk(SEQ[IDX[_lab(first)] + 1]) in skip)


def test_x3_start_then_x5_start_skips_the_carousel():
    skip = _skip()
    clk = tsr.RoundClock()
    clk.note_start("g", _row("4-3"), TABLE, skip)
    assert clk.round_at(_row("4-3") + 5, TABLE, skip) == (4, 3)
    # no rewrite at 4-4: after 4-3's table length the clock shows the carousel
    assert clk.round_at(_row("4-4") + 1, TABLE, skip) == (4, 4)
    clk.note_start("g", _row("4-4") + 40, TABLE, skip)
    assert clk.round_at(_row("4-4") + 41, TABLE, skip) == (4, 5)


def test_a_missed_stretch_counts_the_table_rounds_in_it():
    skip = _skip()
    clk = tsr.RoundClock()
    clk.note_start("g", _row("2-1"), TABLE, skip)
    t = _row("3-2") + 1
    assert t - _row("2-1") > tsr._MISSED_GAP_S
    clk.note_start("g", t, TABLE, skip)
    assert clk.round_at(t + 1, TABLE, skip) == (3, 2)


def test_a_stale_observation_is_carried_forward_by_the_table():
    """No new start for longer than _MISSED_GAP_S (the per-round file went
    stale): the clock does not freeze on the last round seen."""
    skip = _skip()
    clk = tsr.RoundClock()
    clk.note_start("g", _row("3-1") + 30, TABLE, skip)  # this game runs 30 s slow
    assert clk.round_at(_row("3-1") + 100, TABLE, skip) == (3, 1)
    late = _row("4-2") + 30
    assert late - (_row("3-1") + 30) > tsr._MISSED_GAP_S
    assert clk.round_at(late, TABLE, skip) == (4, 2)


def test_a_new_game_or_a_clock_reset_starts_over():
    skip = _skip()
    clk = tsr.RoundClock()
    clk.note_start("g1", _row("5-1"), TABLE, skip)
    clk.note_start("g2", _row("1-3"), TABLE, skip)
    assert clk.round_at(_row("1-3") + 1, TABLE, skip) == (1, 3)
    clk.note_start("g2", _row("1-3") - 30, TABLE, skip)  # the clock went back
    assert clk.round_at(_row("1-3") - 29, TABLE, skip) == (1, 2)


def test_a_table_change_starts_over():
    skip = _skip()
    clk = tsr.RoundClock()
    clk.note_start("g", _row("3-1"), TABLE, skip)
    legacy = tsr._TIME_TO_ROUND
    assert clk.round_at(500, legacy) == tsr._estimate_round(500, 17)


def test_pve_pin_needs_every_health_unchanged():
    sched, skip = _sched(), _skip()
    clk = tsr.RoundClock()
    clk.note_start("g", _row("3-1") - 2, TABLE, skip, hp=(90, 80), pve=sched.pve)
    clk.note_start("g", _row("3-2"), TABLE, skip, hp=(90, 79), pve=sched.pve)
    assert clk.round_at(_row("3-2") + 1, TABLE, skip) == (3, 2)  # no pin: counted


# -- the reader, end to end -----------------------------------------------------------

def _reader():
    rdr = object.__new__(tsr.TftStateReader)  # skip __init__ (OCR thread)
    rdr._my_name = ""
    rdr._last_level = 1
    rdr._confirmed_stage = 1
    rdr._confirmed_round = 1
    rdr._ocr_cache = {}
    rdr._ocr_lock = threading.Lock()
    return rdr


def _standalone_raw(game_time, round_start, hp, game_id="1000000913"):
    return {
        "gameData": {"gameMode": "TFT", "gameTime": game_time, "queueId": 1090},
        "activePlayer": {"summonerName": tft_standalone.LOCAL_NAME},
        "allPlayers": [{"summonerName": tft_standalone.LOCAL_NAME if i == 0 else f"opponent-{i}",
                        "health": h, "isDead": h <= 0, "scores": {}, "items": []}
                       for i, h in enumerate(hp)],
        "events": {"Events": []},
        "rc_source": tft_standalone.SOURCE_TAG,
        "rc_standalone": {"eog": True, "game_id": game_id, "game_length_s": round_start,
                          "eog_age_s": game_time - round_start, "local": {}},
    }


def test_observed_round_start_reads_only_a_standalone_raw():
    raw = _standalone_raw(600.0, 582, (96, 87))
    assert tsr._observed_round_start(raw) == ("1000000913", 582.0, (96, 87))
    assert tsr._observed_round_start({"gameData": {"gameTime": 600}}) is None
    raw["rc_standalone"]["eog"] = False
    assert tsr._observed_round_start(raw) is None
    raw = _standalone_raw(600.0, 582, (96,))
    raw["rc_standalone"]["game_length_s"] = True
    assert tsr._observed_round_start(raw) is None
    assert tsr._observed_round_start(None) is None


def test_reader_follows_the_watched_game_not_the_table():
    rdr = _reader()
    got = []
    for t, hp in WATCHED:
        st = rdr._parse(_standalone_raw(t + 5.0, t, hp))
        got.append(st["stage_round"])
    assert got == WATCHED_AS_SEEN
    # the table alone would have said otherwise at most of these starts
    assert sum(_lab(tsr._estimate_round(t + 5.0, 18)) == w
               for (t, _), w in zip(WATCHED, WATCHED_ROUNDS)) <= 2


def test_reader_without_a_per_round_file_uses_the_table():
    rdr = _reader()
    raw = {"activePlayer": {"summonerName": "Me", "level": 5},
           "allPlayers": [{"summonerName": "Me", "items": [], "scores": {}}],
           "gameData": {"gameMode": "TFT", "gameTime": _row("3-6") + 1, "mapNumber": 22}}
    assert rdr._parse(raw)["stage_round"] == "3-6"


def test_ocr_still_overrides_the_clock():
    rdr = _reader()
    rdr._ocr_cache = {"stage_round": "3-4"}
    st = rdr._parse(_standalone_raw(_row("3-3") + 20.0, _row("3-3"), (90, 80)))
    assert st["stage_round"] == "3-4" and st["is_carousel"] is True
