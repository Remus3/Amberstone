"""RM-607 wiring (merger ruling): the tape is installed and persisted ONLY
behind ``RC_ITEM_TAPE`` (default OFF), through non-frozen seams:

  * core/liveclient_cache.py ``_install_optional_taps`` installs the listener;
  * lcu/lcu_postgame_collector.py ``_publish_game_end_pin`` (the point that
    holds a PROVEN-FRESH end-of-game gameId) schedules the game-end persist;
  * scripts/rewind_catchup.py ``_insert_timeline_rows`` purges superseded tape
    rows when Match-V5 rows arrive (a no-op while the column is absent).

Synthetic, name-scrubbed. Temp databases only.
"""
from __future__ import annotations

import sqlite3

import pytest

from core import live_item_tape as lit
from core import live_item_tape_store as store
from core import liveclient_cache
from scripts import rewind_catchup
from scripts.rewind_scraper import SCHEMA

MID = "NA1_9000000001"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(lit.FLAG_ENV, raising=False)
    monkeypatch.setattr(lit, "_LISTENER_INSTALLED", False)
    liveclient_cache.clear_listeners()
    yield
    liveclient_cache.clear_listeners()


def _ev(iid, kind=lit.EV_PURCHASED):
    return lit.TapeEvent(60.0, "TapeP1#TST", "ORDER", kind, iid, 1, ())


# ------------------------------------------------------------- flag + listener

@pytest.mark.parametrize("val,want", [(None, False), ("0", False), ("", False),
                                      ("1", True), ("true", True), ("ON", True)])
def test_flag_default_off(monkeypatch, val, want):
    if val is not None:
        monkeypatch.setenv(lit.FLAG_ENV, val)
    assert lit.is_enabled() is want


def test_flag_off_installs_no_listener():
    assert lit.install_if_enabled() is False
    assert lit.tick_from_snapshot not in liveclient_cache._listeners


def test_flag_on_installs_the_listener_once(monkeypatch):
    monkeypatch.setenv(lit.FLAG_ENV, "1")
    assert lit.install_if_enabled() is True
    assert lit.install_if_enabled() is False
    assert liveclient_cache._listeners.count(lit.tick_from_snapshot) == 1


def test_optional_taps_seam_honours_the_flag(monkeypatch):
    liveclient_cache._install_optional_taps()
    assert lit.tick_from_snapshot not in liveclient_cache._listeners
    monkeypatch.setenv(lit.FLAG_ENV, "1")
    liveclient_cache._install_optional_taps()
    assert lit.tick_from_snapshot in liveclient_cache._listeners


def test_optional_taps_seam_is_fail_soft(monkeypatch):
    monkeypatch.setenv(lit.FLAG_ENV, "1")

    def boom():
        raise RuntimeError("tap broke")
    monkeypatch.setattr(lit, "install_if_enabled", boom)
    liveclient_cache._install_optional_taps()     # must not raise


# ------------------------------------------------------------- game-end persist

def _record_on_game_end(monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr(store, "on_game_end",
                        lambda match_id, **kw: calls.append((match_id, kw)) or
                        {"status": "scheduled"})
    return calls


def test_game_end_flag_off_no_persist_no_drain(monkeypatch):
    calls = _record_on_game_end(monkeypatch)
    drained: list = []
    monkeypatch.setattr(lit, "drain_tape", lambda: drained.append(1) or [])
    res = store.on_game_end_if_enabled(9000000001, platform="NA1")
    assert res == {"status": "disabled"}
    assert calls == [] and drained == []


def test_game_end_flag_on_uses_platform_match_id(monkeypatch):
    monkeypatch.setenv(lit.FLAG_ENV, "1")
    calls = _record_on_game_end(monkeypatch)
    store.on_game_end_if_enabled("9000000001", platform="euw1")
    assert calls == [("EUW1_9000000001", {})]


def test_game_end_flag_on_default_platform_from_operator_identity(monkeypatch):
    monkeypatch.setenv(lit.FLAG_ENV, "1")
    monkeypatch.setenv("RC_RIOT_PLATFORM", "NA1")
    calls = _record_on_game_end(monkeypatch)
    store.on_game_end_if_enabled(9000000001)
    assert calls == [(MID, {})]


def test_game_end_default_delay_never_blocks(monkeypatch, tmp_path):
    """The default path is a daemon Timer: returns 'scheduled' at once."""
    started: list = []

    class FakeTimer:
        def __init__(self, delay, fn, args=()):
            started.append(delay)
            self.daemon = False

        def start(self):
            started.append(self.daemon)
    monkeypatch.setattr(store.threading, "Timer", FakeTimer)
    res = store.on_game_end(MID, db_path=tmp_path / "x.db", events=[_ev(1036)])
    assert res["status"] == "scheduled"
    assert started == [store.DEFAULT_DELAY_S, True]


def _collector():
    import lcu.lcu_postgame_collector as pgc
    return pgc.PostgameCollector.__new__(pgc.PostgameCollector)


def _quiet_pin(monkeypatch):
    import lib.rewind_live_writer as rlw
    monkeypatch.setattr(rlw, "write_game_end_pin", lambda *a, **k: None)


def test_collector_seam_flag_off_does_not_persist(monkeypatch):
    _quiet_pin(monkeypatch)
    calls = _record_on_game_end(monkeypatch)
    _collector()._publish_game_end_pin({"gameId": 9000000001}, summoner={})
    assert calls == []


def test_collector_seam_flag_on_persists_with_the_eog_game_id(monkeypatch):
    monkeypatch.setenv(lit.FLAG_ENV, "1")
    monkeypatch.setenv("RC_RIOT_PLATFORM", "NA1")
    _quiet_pin(monkeypatch)
    calls = _record_on_game_end(monkeypatch)
    _collector()._publish_game_end_pin({"gameId": 9000000001}, summoner={})
    assert calls == [(MID, {})]


def test_collector_seam_survives_a_failing_pin_and_a_failing_tape(monkeypatch):
    monkeypatch.setenv(lit.FLAG_ENV, "1")
    import lib.rewind_live_writer as rlw

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(rlw, "write_game_end_pin", boom)
    calls = _record_on_game_end(monkeypatch)
    _collector()._publish_game_end_pin({"gameId": 9000000001}, summoner={})
    assert calls and calls[0][0].endswith("_9000000001")   # pin failure isolated
    monkeypatch.setattr(store, "on_game_end_if_enabled", boom)
    _collector()._publish_game_end_pin({"gameId": 9000000001}, summoner={})


# ------------------------------------------------------------- catchup purge

def _db(tmp_path) -> sqlite3.Connection:
    c = sqlite3.connect(str(tmp_path / "rewind.db"))
    c.executescript(SCHEMA)
    return c


def _timeline(item_id=3031):
    return {"info": {"frames": [{"timestamp": 60000, "participantFrames": {},
                                 "events": [{"type": "ITEM_PURCHASED",
                                             "timestamp": 61000,
                                             "participantId": 1,
                                             "itemId": item_id}]}]}}


def test_catchup_purges_tape_rows_when_match_v5_arrives(tmp_path):
    c = _db(tmp_path)
    store.persist_tape(c, MID, [_ev(1036)])
    store.persist_tape(c, "NA1_9000000002", [_ev(1037)])
    rewind_catchup._insert_timeline_rows(c, MID, _timeline())
    rows = c.execute("SELECT match_id, item_id, source FROM timeline_events "
                     "WHERE event_type LIKE 'ITEM_%' ORDER BY id").fetchall()
    assert sorted(rows) == [(MID, 3031, None),
                            ("NA1_9000000002", 1037, "live_tape")]


def test_catchup_purge_is_a_noop_without_the_column(tmp_path):
    c = _db(tmp_path)
    rewind_catchup._insert_timeline_rows(c, MID, _timeline())
    cols = [r[1] for r in c.execute("PRAGMA table_info(timeline_events)")]
    assert "source" not in cols                  # flag-off: table never altered
    n = c.execute("SELECT COUNT(*) FROM timeline_events").fetchone()[0]
    assert n == 1


def test_catchup_purge_failure_never_costs_the_v5_write(tmp_path, monkeypatch):
    c = _db(tmp_path)

    def boom(*a, **k):
        raise sqlite3.OperationalError("purge broke")
    monkeypatch.setattr(store, "purge_superseded_tape_rows", boom)
    rewind_catchup._insert_timeline_rows(c, MID, _timeline())
    n = c.execute("SELECT COUNT(*) FROM timeline_events").fetchone()[0]
    assert n == 1
