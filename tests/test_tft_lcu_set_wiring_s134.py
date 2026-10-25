"""Session 134: the LCU half of the running-set rule gets a caller path.

LT-01 measured the rule (ops/runtime/tft_qa/LCU_TFT_INVENTORY.md rows "Set /
patch metadata" and "Queue / mode"): the running set is
GET /lol-game-data/assets/v1/tftsets.json LCTFTModeData.mDefaultSet.SetName
("TFTSet18", any phase) PAIRED with GET /lol-gameflow/v1/session
gameData.queue.id (1090 Normal; 6110 is the Set 17 revival queue, so it runs
Set 17 whatever mDefaultSet says). tft/tft_set.py set_from_lcu /
note_live_set_from_lcu encode the rule but had no caller.

This slice adds the reads (tft/tft_set.py read_lcu_set_facts /
lcu_default_set / lcu_tft_queue_id) and a throttled call from the TFT poll
loop (core/tft_worker.py TftWorker, kwarg lcu_request). The noted set lives
LIVE_TTL_S, so a one-shot note at game start would expire mid-game: the
worker refreshes it every LCU_SET_REFRESH_S. The worker reads the LCU only
when it is handed a request (lcu_request=None reads nothing), so the game
start site that builds the worker - app/_game_lifecycle.py on_game_start, a
P0 / frozen file this slice does not edit - passes
lcu_request=core.tft_worker.make_lcu_request().

Names used, cited at the fix tree: tft/tft_set.py `TFTSETS_URI`,
`GAMEFLOW_SESSION_URI`, `lcu_default_set`, `lcu_tft_queue_id`,
`read_lcu_set_facts`, `note_live_set_from_lcu`, `noted_live_set`,
`clear_live_set`, `LIVE_TTL_S`, `QUEUE_SETS`; core/tft_worker.py `TftWorker`,
`LCU_SET_REFRESH_S`, `make_lcu_request`, `_maybe_note_lcu_set`.
"""
from __future__ import annotations

import queue

import pytest

from core import tft_worker
from tft import tft_set

# Shapes as measured (LCU_TFT_INVENTORY.md), trimmed to the keys read.
TFTSETS = {"LCTFTModeData": {"mDefaultSet": {"SetName": "TFTSet18"}}}
SESSION_1090 = {"gameData": {"queue": {"id": 1090, "gameMode": "TFT",
                                       "mapId": 22, "type": "NORMAL_TFT"}}}
SESSION_6110 = {"gameData": {"queue": {"id": 6110, "gameMode": "TFT", "mapId": 22}}}
SESSION_SR = {"gameData": {"queue": {"id": 420, "gameMode": "CLASSIC", "mapId": 11}}}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv(tft_set.ENV_PIN, raising=False)
    tft_set.clear_live_set()
    yield
    tft_set.clear_live_set()


class FakeLcu:
    """request(method, path, body=None) -> (payload, err), recording paths."""

    def __init__(self, session, tftsets=TFTSETS, boom=False):
        self.session = session
        self.tftsets = tftsets
        self.boom = boom
        self.paths = []

    def __call__(self, method, path, body=None):
        assert method == "GET"
        self.paths.append(path)
        if self.boom:
            raise OSError("LCU down")
        if path == tft_set.GAMEFLOW_SESSION_URI:
            return self.session, None
        if path == tft_set.TFTSETS_URI:
            return self.tftsets, None
        return None, "404"


# -- the readers --------------------------------------------------------------

def test_uris_are_the_measured_ones():
    assert tft_set.TFTSETS_URI == "/lol-game-data/assets/v1/tftsets.json"
    assert tft_set.GAMEFLOW_SESSION_URI == "/lol-gameflow/v1/session"


@pytest.mark.parametrize("doc, want", [
    (TFTSETS, "TFTSet18"),
    ({"LCTFTModeData": {"mDefaultSet": {"SetName": "  TFTSet18 "}}}, "TFTSet18"),
    ({"LCTFTModeData": {"mDefaultSet": {}}}, None),
    ({"LCTFTModeData": {"mDefaultSet": None}}, None),
    ({"LCTFTModeData": None}, None),
    ({"mDefaultSet": {"SetName": "TFTSet18"}}, None),  # not the measured path
    ({"LCTFTModeData": {"mDefaultSet": {"SetName": 18}}}, None),
    (None, None), ([], None), ("TFTSet18", None),
])
def test_lcu_default_set_reads_only_the_measured_path(doc, want):
    assert tft_set.lcu_default_set(doc) == want


@pytest.mark.parametrize("doc, want", [
    (SESSION_1090, 1090), (SESSION_6110, 6110),
    ({"gameData": {"queue": {"id": "1100", "gameMode": "TFT"}}}, 1100),
    (SESSION_SR, None),  # not a TFT queue: no set to note
    ({"gameData": {"queue": {"id": 1090}}}, None),  # gameMode unknown
    ({"gameData": {"queue": {"id": 0, "gameMode": "TFT"}}}, None),
    ({"gameData": {"queue": {"id": True, "gameMode": "TFT"}}}, None),
    ({"gameData": {"queue": None}}, None), ({"gameData": None}, None),
    (None, None), ([], None),
])
def test_lcu_tft_queue_id(doc, want):
    assert tft_set.lcu_tft_queue_id(doc) == want


def test_facts_for_a_normal_game_read_both_endpoints():
    lcu = FakeLcu(SESSION_1090)
    assert tft_set.read_lcu_set_facts(lcu) == ("TFTSet18", 1090)
    assert lcu.paths == [tft_set.GAMEFLOW_SESSION_URI, tft_set.TFTSETS_URI]


def test_revival_queue_needs_no_tftsets_read():
    lcu = FakeLcu(SESSION_6110)
    assert tft_set.read_lcu_set_facts(lcu) == (None, 6110)
    assert lcu.paths == [tft_set.GAMEFLOW_SESSION_URI]
    assert tft_set.set_from_lcu(None, 6110) == 17


def test_a_known_default_set_is_not_refetched():
    lcu = FakeLcu(SESSION_1090)
    assert tft_set.read_lcu_set_facts(lcu, default_set="TFTSet18") == ("TFTSet18", 1090)
    assert lcu.paths == [tft_set.GAMEFLOW_SESSION_URI]


def test_no_tft_session_reads_nothing_more():
    lcu = FakeLcu(SESSION_SR)
    assert tft_set.read_lcu_set_facts(lcu) == (None, None)
    assert lcu.paths == [tft_set.GAMEFLOW_SESSION_URI]


# -- the worker: throttled, injectable, never raises ---------------------------

def _worker(lcu=None, clock=None):
    w = tft_worker.TftWorker(result_queue=queue.Queue(maxsize=4), lcu_request=lcu)
    if clock is not None:
        w._lcu_clock = clock
    return w


def test_worker_notes_set18_for_a_normal_queue():
    w = _worker(FakeLcu(SESSION_1090))
    assert w._maybe_note_lcu_set() == 18
    assert tft_set.noted_live_set() == 18


def test_worker_notes_set17_for_the_revival_queue():
    w = _worker(FakeLcu(SESSION_6110))
    assert w._maybe_note_lcu_set() == 17
    assert tft_set.noted_live_set() == 17


def test_worker_without_a_request_reads_and_notes_nothing():
    w = _worker(None)
    assert w._maybe_note_lcu_set() is None
    assert tft_set.noted_live_set() is None


def test_worker_refresh_is_throttled_and_inside_the_ttl():
    assert 0 < tft_worker.LCU_SET_REFRESH_S < tft_set.LIVE_TTL_S
    now = [1000.0]
    lcu = FakeLcu(SESSION_1090)
    w = _worker(lcu, clock=lambda: now[0])
    assert w._maybe_note_lcu_set() == 18
    first = list(lcu.paths)
    now[0] += tft_worker.LCU_SET_REFRESH_S - 1
    assert w._maybe_note_lcu_set() is None
    assert lcu.paths == first
    now[0] += 2
    assert w._maybe_note_lcu_set() == 18
    # tftsets.json read once per worker; the queue id every refresh
    assert lcu.paths.count(tft_set.TFTSETS_URI) == 1
    assert lcu.paths.count(tft_set.GAMEFLOW_SESSION_URI) == 2


def test_worker_survives_an_lcu_fault():
    w = _worker(FakeLcu(SESSION_1090, boom=True))
    assert w._maybe_note_lcu_set() is None
    assert tft_set.noted_live_set() is None


def test_worker_run_loop_calls_the_note(monkeypatch):
    """The poll loop itself refreshes the set (not only a helper on the side)."""
    lcu = FakeLcu(SESSION_1090)
    w = _worker(lcu)

    class _Reader:
        def read(self):
            w.stop()
            return None

        def shutdown(self):
            pass

    w._reader, w._engine, w._live = _Reader(), None, None
    w._run(w._generation)
    assert tft_worker.TftWorker._maybe_note_lcu_set  # exists
    assert tft_set.GAMEFLOW_SESSION_URI in lcu.paths
    assert tft_set.noted_live_set() == 18


# -- the request factory for the game-start site --------------------------------

class _FakeClient:
    instances = []

    def __init__(self):
        self._port = None
        self.connects = 0
        self.refreshes = 0
        self.calls = []
        _FakeClient.instances.append(self)

    def connect(self):
        self.connects += 1
        self._port = 1234
        return True

    def _refresh_conn_if_changed(self):
        self.refreshes += 1
        return False

    def _request(self, method, endpoint, data=None):
        self.calls.append((method, endpoint))
        return {"ok": endpoint}


def test_make_lcu_request_owns_one_lazy_client(monkeypatch):
    import lcu.lcu_client as lc
    _FakeClient.instances = []
    monkeypatch.setattr(lc, "LcuClient", _FakeClient)
    req = tft_worker.make_lcu_request()
    assert _FakeClient.instances == []  # nothing built until the first call
    assert req("GET", "/a") == ({"ok": "/a"}, None)
    assert req("GET", "/b") == ({"ok": "/b"}, None)
    (client,) = _FakeClient.instances
    assert client.connects == 1 and client.refreshes == 1
    assert client.calls == [("GET", "/a"), ("GET", "/b")]
