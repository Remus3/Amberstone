"""s144 true-audit of core/liveclient_cache.py (RM-1040).

The module had a lane-8 pass on 2026-08-03 (LEDGER 1184, the fail-closed
age_s). Since then RM-604..608 and RM-637 hung five taps and the event hub on
its listener list, so this pass audits the listener, logging and stop / start
machinery. Each test below was red before the fix:

1. A listener that raises was logged at DEBUG on every 0.5 s tick, so a broken
   tap (recorder, event hub, ward producer) went silent with nothing in logs/.
   It is now warned once per failure streak, per listener.
2. An unusable relay `ts` was warned on EVERY poll - about 7200 WARNING lines an
   hour for a whole game after one relay contract change. Once per streak now.
3. A vision token that cannot be resolved was DEBUG-only on every poll, so the
   cache 401ed forever with nothing visible. Once per streak at WARNING now.
4. An optional tap that fails to install was DEBUG-only: an operator who set
   RC_SESSION_RECORDER=1 got no recording and no log line. WARNING now.
5. stop() then start() in thread mode, while the old poller was still inside a
   slow fetch past the join timeout, cleared the shared stop event and left TWO
   pollers running for the life of the process, the stale one still writing
   _snapshot and firing every listener. Each poller now carries a generation
   and exits (without publishing) once it is superseded.
6. The listener comment said listeners fire after every SUCCESSFUL fetch; the
   code fires after every fetch, failures included, and RM-637's transport
   failure count depends on that. The comment is fixed and the behaviour
   pinned.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import sys
import threading
import time
import types

import pytest

from core import liveclient_cache as lc
from tests._asyncio_isolation import run_coro
from tests._timing_budget import fleet_test_guard

_LOGGER = "rc.liveclient_cache"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    lc.clear_listeners()
    lc._reset_log_streaks_for_tests()
    saved = (lc._snapshot, lc._thread, lc._task)
    yield
    lc.stop()
    lc._snapshot, lc._thread, lc._task = saved
    lc._stop.clear()
    lc.clear_listeners()
    lc._reset_log_streaks_for_tests()


def _warnings(caplog):
    return [r for r in caplog.records
            if r.name == _LOGGER and r.levelno >= logging.WARNING]


# 1. listener failures -------------------------------------------------------

def test_raising_listener_is_warned_once_per_streak(caplog):
    state = {"fail": True}

    def flaky(snap):
        if state["fail"]:
            raise RuntimeError("tap broke")

    lc.add_listener(flaky)
    snap = lc.Snapshot(data={}, ts=1.0, fetched_at=1.0)
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    for _ in range(5):
        lc._fire_listeners(snap)
    assert len(_warnings(caplog)) == 1
    assert "tap broke" in _warnings(caplog)[0].getMessage()

    # A success ends the streak; the next failure is warned again.
    state["fail"] = False
    lc._fire_listeners(snap)
    state["fail"] = True
    lc._fire_listeners(snap)
    assert len(_warnings(caplog)) == 2


def test_listener_streaks_are_per_listener(caplog):
    def a(snap):
        raise RuntimeError("a broke")

    def b(snap):
        raise RuntimeError("b broke")

    lc.add_listener(a)
    lc.add_listener(b)
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    for _ in range(3):
        lc._fire_listeners(lc.Snapshot())
    msgs = sorted(r.getMessage() for r in _warnings(caplog))
    assert len(msgs) == 2
    assert "a broke" in msgs[0] and "b broke" in msgs[1]


def test_removed_listener_streak_is_forgotten(caplog):
    def boom(snap):
        raise RuntimeError("boom")

    lc.add_listener(boom)
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    lc._fire_listeners(lc.Snapshot())
    lc.remove_listener(boom)
    lc.add_listener(boom)
    lc._fire_listeners(lc.Snapshot())
    assert len(_warnings(caplog)) == 2


# 2. unusable relay ts --------------------------------------------------------

def _fetch_with(monkeypatch, body: str) -> lc.Snapshot:
    monkeypatch.setattr(lc, "urlopen",
                        lambda req, timeout=None: _Resp(body.encode()))
    monkeypatch.setattr(lc, "_auth_headers", lambda: {})
    return lc._fetch_once()


def test_unusable_ts_is_warned_once_per_streak(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    bad = json.dumps({"data": {"gameData": {}}, "ts": "abc"})
    for _ in range(4):
        snap = _fetch_with(monkeypatch, bad)
        assert snap.age_s == lc._UNKNOWN_AGE_S
    assert len(_warnings(caplog)) == 1

    good = json.dumps({"data": {"gameData": {}}, "ts": time.time()})
    assert _fetch_with(monkeypatch, good).age_s < 5.0
    _fetch_with(monkeypatch, bad)
    assert len(_warnings(caplog)) == 2


# 3. vision token unresolved --------------------------------------------------

def test_token_failure_is_warned_once_per_streak(monkeypatch, caplog):
    import core.vision_token as vt

    state = {"fail": True}

    def fake_token():
        if state["fail"]:
            raise RuntimeError("no token source")
        return "SYNTHETIC-TOKEN-7f3a"

    monkeypatch.setattr(vt, "get_vision_token", fake_token)
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    for _ in range(4):
        assert lc._auth_headers() == {"X-RC-Token": ""}
    assert len(_warnings(caplog)) == 1
    assert "no token source" in _warnings(caplog)[0].getMessage()

    state["fail"] = False
    assert lc._auth_headers() == {"X-RC-Token": "SYNTHETIC-TOKEN-7f3a"}
    state["fail"] = True
    lc._auth_headers()
    assert len(_warnings(caplog)) == 2
    # The resolved token never reaches a log record.
    assert not any("SYNTHETIC-TOKEN-7f3a" in r.getMessage() for r in caplog.records)


# 4. optional tap install failure ---------------------------------------------

_TAP_MODULES = (
    "core.live_session_recorder",
    "core.self_cast_log",
    "core.live_item_tape",
    "core.death_recap",
    "core.obs_recorder",
)


def _fake_taps(monkeypatch, broken: str) -> list:
    calls = []
    for name in _TAP_MODULES:
        mod = types.ModuleType(name)
        if name == broken:
            def install_if_enabled(_n=name):
                calls.append(_n)
                raise ImportError(f"{_n} missing dependency")
        else:
            def install_if_enabled(_n=name):
                calls.append(_n)
                return False
        mod.install_if_enabled = install_if_enabled
        monkeypatch.setitem(sys.modules, name, mod)
    return calls


@pytest.mark.parametrize("broken", _TAP_MODULES)
def test_tap_install_failure_is_a_warning_and_other_taps_still_install(
        monkeypatch, caplog, broken):
    calls = _fake_taps(monkeypatch, broken)
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    lc._install_optional_taps()
    assert calls == list(_TAP_MODULES)
    warns = _warnings(caplog)
    assert len(warns) == 1
    assert broken in warns[0].getMessage()


# 5. superseded poller --------------------------------------------------------

def _no_app_loop(monkeypatch):
    import app._loop as loop_mod
    monkeypatch.setattr(loop_mod, "get_loop", lambda: None)
    monkeypatch.setattr(lc, "_install_optional_taps", lambda: None)


def test_stop_then_start_never_leaves_two_thread_pollers(monkeypatch):
    _no_app_loop(monkeypatch)
    monkeypatch.setattr(lc, "_STOP_JOIN_S", 0.05)
    gate = threading.Event()
    entered = threading.Event()
    stale = lc.Snapshot(data={"who": "stale"}, ts=1.0, fetched_at=1.0)
    fresh = lc.Snapshot(data={"who": "fresh"}, ts=1.0, fetched_at=1.0)
    first = threading.Event()
    callers = []

    def fake_fetch():
        callers.append(threading.current_thread())
        if not first.is_set():
            first.set()
            entered.set()
            gate.wait(5)
            return stale
        return fresh

    seen = []
    monkeypatch.setattr(lc, "_fetch_once", fake_fetch)
    lc.add_listener(lambda s: seen.append(s.data["who"]))

    lc.start(poll_s=0.01)
    assert entered.wait(fleet_test_guard.budget(5))
    old = lc._thread
    lc.stop()                      # join times out: old is inside the fetch
    assert old.is_alive()
    lc.start(poll_s=0.01)
    new = lc._thread
    assert new is not old and new.is_alive()
    gate.set()
    old.join(fleet_test_guard.budget(5))
    assert not old.is_alive(), "superseded poller kept running"
    assert "stale" not in seen, "superseded poller published its snapshot"
    time.sleep(0.1)
    late = [t for t in callers[1:] if t is old]
    assert late == []
    assert lc._snapshot is fresh


def _blocking_first_fetch(monkeypatch):
    gate = threading.Event()
    entered = threading.Event()
    stale = lc.Snapshot(data={"who": "stale"}, ts=1.0, fetched_at=1.0)

    def fake_fetch():
        if not entered.is_set():
            entered.set()
            gate.wait(5)
            return stale
        return lc.Snapshot(data={"who": "fresh"}, ts=1.0, fetched_at=1.0)

    monkeypatch.setattr(lc, "_fetch_once", fake_fetch)
    return gate, entered, stale


def test_stop_with_a_fetch_in_flight_publishes_nothing(monkeypatch):
    """No restart at all: a fetch that was in flight when stop() returned must
    not rebind _snapshot or reach the listeners afterwards."""
    _no_app_loop(monkeypatch)
    monkeypatch.setattr(lc, "_STOP_JOIN_S", 0.05)
    gate, entered, stale = _blocking_first_fetch(monkeypatch)
    seen = []
    lc.add_listener(lambda s: seen.append(s.data["who"]))
    before = lc._snapshot
    lc.start(poll_s=0.01)
    assert entered.wait(fleet_test_guard.budget(5))
    old = lc._thread
    lc.stop()
    assert old.is_alive()
    gate.set()
    old.join(fleet_test_guard.budget(5))
    assert not old.is_alive()
    assert seen == []
    assert lc._snapshot is before


def test_start_supersedes_a_poller_whose_handle_was_lost(monkeypatch):
    """start() makes whatever polled before it non-current, so a poller whose
    handle was dropped (``_thread`` rebound to None while it still runs)
    cannot keep publishing beside the new one."""
    _no_app_loop(monkeypatch)
    gate, entered, stale = _blocking_first_fetch(monkeypatch)
    seen = []
    lc.add_listener(lambda s: seen.append(s.data["who"]))
    lc.start(poll_s=0.01)
    assert entered.wait(fleet_test_guard.budget(5))
    old = lc._thread
    lc._thread = None               # handle lost; no stop() call
    lc.start(poll_s=0.01)
    assert lc._thread is not old
    gate.set()
    old.join(fleet_test_guard.budget(5))
    assert not old.is_alive()
    assert "stale" not in seen


def test_superseded_async_loop_returns_without_fetching(monkeypatch):
    calls = []
    monkeypatch.setattr(lc, "_fetch_once",
                        lambda: calls.append(1) or lc.Snapshot())
    old_gen = lc._gen
    lc._gen = old_gen + 1
    try:
        # Off the main thread (tests/_asyncio_isolation.py): a bare
        # asyncio.run() raises after any snapshot_panels test in the worker.
        run_coro(asyncio.wait_for(lc._loop_async(0.01, old_gen), 2))
    finally:
        lc._gen = old_gen
    assert calls == []


# 6. listeners fire on failed fetches too -------------------------------------

def test_listeners_fire_on_a_failed_fetch(monkeypatch):
    _no_app_loop(monkeypatch)
    failed = lc.Snapshot(data=None, fetched_at=1.0, failure="transport")
    monkeypatch.setattr(lc, "_fetch_once", lambda: failed)
    got = threading.Event()
    lc.add_listener(lambda s: got.set() if s.failure == "transport" else None)
    lc.start(poll_s=0.01)
    assert got.wait(fleet_test_guard.budget(5))
