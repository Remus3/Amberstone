# arch: regression - RM-237 poll tick subresource budget + fresh GameReader per worker generation | section=vision | frozen=no
"""RM-237 - the poll tick could outlast the 12 s liveness threshold, and the
restart that followed handed the new thread the SAME GameReader.

1. `_process_game` subresource GETs share one per-tick wall-clock budget.
2. `SrAramWorker._init_reader(gen)` mints a fresh reader per generation.
3. `reset_reader_state` no longer rebinds the tracking dicts from another
   thread; the poll thread clears them IN PLACE before its next read.
"""

import queue
import sys
import time
import types

from core.sr_aram_worker import SrAramWorker
from game_reader import snapshot_normalizer as sn
from game_reader.snapshot_normalizer import _NormalizerMixin


class _SlowHost(_NormalizerMixin):
    DELAY = 0.3

    def __init__(self):
        self._enemy_last_seen: dict = {}
        self._enemy_death_time: dict = {}
        self.calls = 0

    def _try_lcu_game_id(self):
        return ""

    def _get(self, url):
        self.calls += 1
        time.sleep(self.DELAY)
        return {}


def _env():
    players = [{"championName": "Ahri", "riotIdGameName": "Me",
                "summonerName": "Me#NA1", "team": "ORDER", "level": 6,
                "scores": {}, "items": [], "position": {"x": 0, "z": 0}}]
    for i, c in enumerate(("Zed", "Lux", "Jinx", "Leona", "Vi")):
        players.append({"championName": c, "riotIdGameName": f"E{i}",
                        "summonerName": f"E{i}#NA1", "team": "CHAOS",
                        "level": 6, "scores": {}, "items": [],
                        "position": {"x": 0, "z": 0}})
    return {"activePlayer": {"level": 6, "summonerName": "Me#NA1",
                             "riotIdGameName": "Me", "championStats": {}},
            "gameData": {"gameMode": "CLASSIC", "gameTime": 600.0,
                         "mapNumber": 11},
            "allPlayers": players, "events": {"Events": []}}


def test_tick_subresource_time_is_budgeted(monkeypatch):
    monkeypatch.setattr(sn, "SUBRESOURCE_TICK_BUDGET_S", 0.5, raising=False)
    host = _SlowHost()
    t0 = time.monotonic()
    state = host._process_game(_env())
    elapsed = time.monotonic() - t0
    assert state is not None
    # Unbudgeted: 1 runes + 5 enemy runes + 1 abilities = 7 x 0.3 = 2.1 s.
    # Budgeted: a GET starts only while budget remains -> <= 0.5 + one call.
    assert host.calls < 7
    assert elapsed < 0.5 + _SlowHost.DELAY + 0.4


class _StubReader:
    def __init__(self):
        self._enemy_last_seen = {}
        self._enemy_death_time = {}


def test_new_generation_gets_fresh_reader(monkeypatch):
    fake = types.ModuleType("game_reader")
    fake.GameReader = _StubReader
    monkeypatch.setitem(sys.modules, "game_reader", fake)
    w = SrAramWorker(result_queue=queue.Queue())
    assert w._init_reader(1)
    r1 = w._reader
    assert w._init_reader(1) and w._reader is r1      # same gen reuses
    assert w._init_reader(2)
    assert w._reader is not r1                        # new gen is fresh


class _OneTick:
    def __init__(self, stop_event):
        self._stop_event = stop_event
        self._enemy_last_seen = {"Zed": {"dead": False}}
        self._enemy_death_time = {"Zed": 1.0}
        self.seen_during_read = None

    def read_game(self):
        self.seen_during_read = (dict(self._enemy_last_seen),
                                 dict(self._enemy_death_time))
        self._stop_event.set()
        return None


def test_reset_is_applied_in_place_by_poll_thread():
    w = SrAramWorker(result_queue=queue.Queue())
    r = _OneTick(w._stop_event)
    w._reader = r
    last_seen, death = r._enemy_last_seen, r._enemy_death_time
    w.reset_reader_state(reason="game_start")
    w._run(w._generation)
    # Cleared before the read, and the SAME dict objects (no cross-thread
    # rebind a mid-derivation tick could straddle).
    assert r.seen_during_read == ({}, {})
    assert r._enemy_last_seen is last_seen
    assert r._enemy_death_time is death
