"""S136 T15 - the TFT stage must never run ahead of the game while it loads.

Live QA (s136 game 2, game 5667197548, run dir
ops/runtime/tft_qa/20261025-162857, LIVE_NOTES_s136_g2.md "D1"): the stage RC
served ran 2-3 rounds AHEAD of the HUD from game start until the first OCR
stage read at game 3:52. Reconstructed from the recorder (states.jsonl
liveclient.as_of = every per-round write, vision frames = the HUD label,
logs/2026-10-25.log "Round calibration" lines):

- The game clock RC reads is the game's own: before the first per-round
  write, now minus the TFT process create time (tft/tft_standalone.py
  ``_synth_allgamedata``); after it, the file's gameLengthSeconds plus its age.
  The two agree to 3 s (file clock zero 16:28:56, TFTClient 16:28:53), and
  BOTH count the loading screen: frames at 48 / 68 / 88 s show the loading
  screen, the HUD first shows 1-1 at 106 s.
- The Set 18 table (tft/tft_state_reader.py ``_TIME_TO_ROUND_SET18``) puts
  1-2 at 25 s, 1-3 at 65 s and 1-4 at 104 s - a clock whose zero is round 1-1.
  So during the load RC said 1-2 / 1-3 / 1-3, and ``RoundClock.note_start``
  placed the first per-round write (98 s, during 1-1) on the nearest table
  row, 1-4 (log "t=99.4s -> 1-4"), then 2-1 at the 120 s write, while the HUD
  showed 1-1 / 1-2 / 1-2 / 1-3 / 1-3 / 1-4. Lead = the load time.
- Game 1 (run 20261025-153652, pre-T9 code) shows the same mechanism with a
  shorter load: first write 43 s (HUD 1-1 at 46 s), placed on 1-2 -> one
  round ahead through stage 1. So T9 did not introduce it.

Measured in BOTH games: the FIRST per-round write of a game is written during
round 1-1 and carries the start-of-game placeholders (every player's health
unknown: liveclient hp / standing / players_alive null, lobby empty); the
second write already has real health (all 100).

Rules pinned here:
  (a) a per-round write whose every player is a start-of-game placeholder is
      round 1-1 (``rc_standalone["opening"]``; ``RoundClock.note_start``
      ``opening=True``), never the nearest table row;
  (b) before the first write of the game (the loading screen), a standalone
      game reads 1-1, not the table over a clock that includes the load -
      until ``_MISSED_GAP_S`` of game clock with no write, after which the
      table answers as before (T9's test_previous_game_file_sets_no_stage);
  (c) replaying both live games' real write times and lobby healths, the
      clock is never ahead of the HUD label and at most one round behind;
  (d) T9's guarantee stands: a previous game's placeholder file is no file,
      so it anchors nothing.

Names used, cited at the fix tree: tft/tft_standalone.py
``synth_allgamedata``, ``_round_state``, ``_game_create_time``,
``SOURCE_TAG``, ``_reset_caches_for_tests``; tft/tft_state_reader.py
``RoundClock`` (``note_start``, ``round_at``, ``has_start``),
``_TIME_TO_ROUND_SET18``, ``_MISSED_GAP_S``, ``_no_planning_rounds``,
``round_schedule``, ``TftStateReader._parse``; tft/tft_set.py
``resolve_set``.
"""
from __future__ import annotations

import copy
import json
import threading
import time
from pathlib import Path

import pytest

from tft import tft_set
from tft import tft_standalone as ts
from tft import tft_state_reader as tsr

FIX = Path(__file__).parent / "fixtures" / "tft_eog_round_human_lobby_n13.json"
GID = 5000000013
LOCAL_SID = 900004  # fixture entry 3's playerId
LCU = {"phase": "InProgress", "game_id": str(GID), "game_queue_mode": "TFT",
       "summoner_id": LOCAL_SID}

TABLE = tsr._TIME_TO_ROUND_SET18
SEQ = [f"{s}-{r}" for _, s, r in TABLE]
IDX = {lab: i for i, lab in enumerate(SEQ)}

OPEN = None  # a start-of-game write: every player health -1 / ffaStanding -1
ALL100 = (100,) * 8

# s136 game 2 (run 20261025-162857): every per-round write the recorder saw
# (liveclient.as_of.game_s) with the lobby healths it carried.
G2_WRITES = [
    (98, OPEN), (120, ALL100), (170, ALL100), (213, ALL100), (282, ALL100),
    (363, (100, 100, 100, 100, 97, 95, 95, 94)),
]
# (recorder game clock of a vision frame, the HUD stage label on it);
# "load" = the loading screen (no HUD yet).
G2_FRAMES = [
    (48.3, "load"), (68.6, "load"), (88.4, "load"), (106.1, "1-1"),
    (132.1, "1-2"), (151.8, "1-2"), (172.3, "1-3"), (192.0, "1-3"),
    (212.2, "1-4"), (231.5, "2-1"), (256.4, "2-1"), (276.4, "2-1"),
    (296.9, "2-1"), (316.9, "2-1"), (336.6, "2-2"), (356.9, "2-2"),
    (377.0, "2-2"), (396.8, "2-2"),
]
# s136 game 1 (run 20261025-153652, RC on pre-T9 code).
G1_WRITES = [
    (43, OPEN), (65, ALL100), (108, ALL100), (150, ALL100), (217, ALL100),
    (298, (100, 100, 100, 97, 97, 96, 95, 94)),
    (375, (100, 100, 97, 97, 94, 94, 92, 91)),
]
G1_FRAMES = [
    (46, "1-1"), (66, "1-2"), (86, "1-2"), (106, "1-3"), (126, "1-3"),
    (146, "1-4"), (167, "1-4"), (186, "2-1"), (206, "2-1"), (227, "2-1"),
    (247, "2-1"), (272, "2-2"), (297, "2-2"), (317, "2-2"), (337, "2-2"),
    (357, "2-3"),
]
GAMES = {"s136_game1": (G1_WRITES, G1_FRAMES), "s136_game2": (G2_WRITES, G2_FRAMES)}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    ts._reset_caches_for_tests()
    monkeypatch.setattr(tft_set, "resolve_set", lambda *a, **k: 18)
    yield
    ts._reset_caches_for_tests()


def _doc(game_len, hp, game_id=GID) -> dict:
    doc = json.loads(FIX.read_text(encoding="utf-8"))
    doc["gameId"] = game_id
    doc["statsBlock"]["gameLengthSeconds"] = game_len
    for i, p in enumerate(doc["statsBlock"]["players"]):
        if hp is OPEN:
            p["health"], p["ffaStanding"] = -1, -1
        else:
            p["health"], p["ffaStanding"] = hp[i], i + 1
        p["boardPieces"] = []
    return doc


def _raw(gt, write=None, *, lcu=LCU, now=None, game_id=GID):
    """The synthesized standalone raw dict at game clock ``gt`` (s since the
    TFT process started), with ``write`` = (gameLengthSeconds, healths) the
    newest per-round write so far, or None before the first one."""
    now = time.time() if now is None else now
    doc = None
    if write is not None:
        doc = _doc(write[0], write[1], game_id=game_id)
        doc["_mtime"] = now - (gt - write[0])
    return ts.synth_allgamedata(lcu=copy.deepcopy(lcu), running=True, eog=doc, now=now)


def _reader():
    rdr = object.__new__(tsr.TftStateReader)  # skip __init__ (OCR thread)
    rdr._my_name = ""
    rdr._last_level = 1
    rdr._confirmed_stage = 1
    rdr._confirmed_round = 1
    rdr._ocr_cache = {}
    rdr._ocr_lock = threading.Lock()
    return rdr


def _replay(game, monkeypatch):
    """Feed one live game's writes to ONE reader at every frame, through the
    whole synthesized standalone path; (frame gt, HUD label, RC label)."""
    writes, frames = GAMES[game]
    now = time.time()
    rdr, out = _reader(), []
    for gt, hud in frames:
        # the process started gt seconds before this frame
        monkeypatch.setattr(ts, "_game_create_time", lambda gt=gt: now - gt)
        done = [w for w in writes if w[0] <= gt]
        st = rdr._parse(_raw(gt, done[-1] if done else None, now=now))
        out.append((gt, hud, st["stage_round"]))
    return out


def _lab(stage_round) -> str:
    s, r = stage_round
    return f"{s}-{r}"


def _lag(hud, rc) -> int:
    """Rounds the RC label is BEHIND the HUD (negative = ahead)."""
    return IDX["1-1" if hud == "load" else hud] - IDX[rc]


# -- (a) the opening write ------------------------------------------------------------

def test_placeholder_write_is_flagged_opening():
    raw = _raw(106.0, (98, OPEN))
    assert raw["rc_standalone"]["eog_match"] is True
    assert raw["rc_standalone"]["opening"] is True
    raw = _raw(132.0, (120, ALL100))
    assert raw["rc_standalone"]["opening"] is False
    # no per-round file yet: nothing to call an opening write
    assert _raw(60.0, None)["rc_standalone"]["opening"] is False


def test_one_scored_player_is_not_an_opening_write():
    doc = _doc(98, OPEN)
    doc["statsBlock"]["players"][5].update({"health": 100, "ffaStanding": 6})
    doc["_mtime"] = time.time() - 8
    raw = ts.synth_allgamedata(lcu=dict(LCU), running=True, eog=doc, now=time.time())
    assert raw["rc_standalone"]["opening"] is False


def test_first_opening_write_is_round_1_1_not_the_nearest_table_row(monkeypatch):
    """The live 98 s write: the table's nearest planning row is 1-4."""
    now = time.time()
    monkeypatch.setattr(ts, "_game_create_time", lambda: now - 106.0)
    st = _reader()._parse(_raw(106.0, (98, OPEN), now=now))
    assert st["stage_round"] == "1-1", st["stage_round"]


def test_clock_unit_opening_anchor_then_counting():
    sched = tsr.round_schedule(18)
    skip = tsr._no_planning_rounds(sched)
    clk = tsr.RoundClock()
    clk.note_start("g", 98.0, TABLE, skip, hp=None, pve=sched.pve, opening=True)
    assert clk.has_start("g") and not clk.has_start("other")
    assert clk.round_at(106.0, TABLE, skip) == (1, 1)
    # a second placeholder write in the same 1-1 keeps 1-1
    clk.note_start("g", 104.0, TABLE, skip, hp=None, pve=sched.pve, opening=True)
    assert clk.round_at(110.0, TABLE, skip) == (1, 1)
    clk.note_start("g", 120.0, TABLE, skip, hp=ALL100, pve=sched.pve)
    assert clk.round_at(132.0, TABLE, skip) == (1, 2)
    clk.note_start("g", 170.0, TABLE, skip, hp=ALL100, pve=sched.pve)
    assert clk.round_at(172.0, TABLE, skip) == (1, 3)


def test_placeholder_file_after_stage_1_never_rewinds_the_clock():
    """A junk all-unknown file mid-game is not an opening: no jump to 1-1."""
    sched = tsr.round_schedule(18)
    skip = tsr._no_planning_rounds(sched)
    clk = tsr.RoundClock()
    clk.note_start("g", 900.0, TABLE, skip, hp=(90, 80), pve=sched.pve)
    before = clk.round_at(901.0, TABLE, skip)
    clk.note_start("g", 960.0, TABLE, skip, hp=None, pve=sched.pve, opening=True)
    after = clk.round_at(961.0, TABLE, skip)
    assert IDX[_lab(after)] >= IDX[_lab(before)] > IDX["1-1"]


# -- (b) the loading screen -------------------------------------------------------------

@pytest.mark.parametrize("gt", [3.2, 28.5, 48.3, 68.6, 88.4])
def test_process_started_before_round_1_1_is_not_a_round_clock(gt, monkeypatch):
    """Process start = loading screen: with no per-round write yet the
    stage is 1-1, never the table over the load (live: 1-2 / 1-3 / 1-3)."""
    now = time.time()
    monkeypatch.setattr(ts, "_game_create_time", lambda: now - gt)
    raw = _raw(gt, None, now=now)
    assert raw["gameData"]["gameTime"] == pytest.approx(gt, abs=0.2)
    assert _reader()._parse(raw)["stage_round"] == "1-1"


def test_no_write_for_longer_than_the_missed_gap_falls_back_to_the_table(monkeypatch):
    now = time.time()
    gt = tsr._MISSED_GAP_S + 20.0
    monkeypatch.setattr(ts, "_game_create_time", lambda: now - gt)
    st = _reader()._parse(_raw(gt, None, now=now))
    assert st["stage_round"] == _lab(tsr._estimate_round(gt, 18))


def test_live_client_raw_still_reads_the_table():
    """The hold is for the standalone source only: a :2999 gameTime is
    untouched (tests/test_tft_round_clock_s134.py covers a late one)."""
    raw = {"activePlayer": {"summonerName": "Me", "level": 2},
           "allPlayers": [{"summonerName": "Me", "items": [], "scores": {}}],
           "gameData": {"gameMode": "TFT", "gameTime": 70.0, "mapNumber": 22}}
    assert _reader()._parse(raw)["stage_round"] == "1-3"


# -- (c) both live games, replayed ---------------------------------------------------------

@pytest.mark.parametrize("game", sorted(GAMES))
def test_replayed_game_never_runs_ahead_of_the_hud(game, monkeypatch):
    got = _replay(game, monkeypatch)
    ahead = [(gt, hud, rc) for gt, hud, rc in got if _lag(hud, rc) < 0]
    assert ahead == [], ahead
    behind = [(gt, hud, rc) for gt, hud, rc in got if _lag(hud, rc) > 1]
    assert behind == [], behind


def test_replayed_game2_names_stage_1_from_the_first_write(monkeypatch):
    got = {gt: rc for gt, _, rc in _replay("s136_game2", monkeypatch)}
    assert [got[g] for g in (48.3, 68.6, 88.4)] == ["1-1"] * 3
    assert got[106.1] == "1-1"
    assert got[132.1] == got[151.8] == "1-2"
    assert got[172.3] == got[192.0] == "1-3"
    assert got[377.0] == "2-2"


# -- (d) T9's no-stale-file guarantee ---------------------------------------------------------

def test_previous_games_placeholder_file_anchors_nothing(monkeypatch):
    now = time.time()
    monkeypatch.setattr(ts, "_game_create_time", lambda: now - 250.0)
    raw = _raw(250.0, (98, OPEN), now=now, game_id=GID + 1)
    st_raw = raw["rc_standalone"]
    assert st_raw["eog"] is False and st_raw["opening"] is False
    st = _reader()._parse(raw)
    assert st["eog_match"] is False
    # no write of THIS game for longer than the missed gap: the table
    assert st["stage_round"] == _lab(tsr._estimate_round(250.0, 18))
