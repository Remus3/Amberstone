"""RM-854 - the RM-844 focus-board shadow follow-ups (shadow-only throughout).

(a) A row written while the board was warming / throttled / pending is
    re-logged ONCE when a board becomes ready for the same tick key, never
    twice. (b) The board compute runs on a daemon worker in
    ``core.focus_board_live``; the state-builder hook only reads a cached
    result and never waits on a compute. The kill switch still disables
    everything and the served coach never changes.

Grounded before writing (file:line at main 17ae75595, before this change):

* ``core/arena_coach_shadow.py:163`` ``log_arena_coach(det_block, live_block,
  lc, mode_key, *, round_label, path, now_iso)``; the per-path dedup
  ``_LAST_SIG`` (``:50``) checked at ``:219-221``, BEFORE the ``focus_board``
  column (``_focus_board_column``, ``:111``) is built at ``:237``; every test
  uses its own tmp_path because the dedup is keyed by ``str(target)``.
* ``core/focus_board_live.py``: ``board_for_lc(lc, mode_key, *, now,
  wait_engine)`` (``:481``), ``_load_engine`` (``:296``), the warm thread
  (``_engine``, ``:320``), the throttle (``MIN_COMPUTE_INTERVAL_S``, ``:77``,
  return at ``:469``), ``KILL_SWITCH_ENV`` (``:76``), the STATUS_* names
  (``:81-88``), ``_set_engine_for_tests`` (``:503``),
  ``_join_warm_for_tests`` (``:509``), ``reset_for_tests`` (``:515``).
* ``dashboard/_deterministic_coaching.py:1377`` ``shadow_log_arena_coach(
  coach, lc, mode_key, *, path, live_path)`` - the hook the state builder
  calls on its own thread (``dashboard/_state_builder.py:840``); the live
  Haiku block is read through ``_live_arena_block`` (``:1162``), so a missing
  ``live_path`` is a blank side.
* ``agents/daemon_slayer/focus_board.py:475`` ``compute_focus_board``.
* Added by this change (cited from the new code): ``STATUS_PENDING``,
  ``TRANSIENT_STATUSES``, ``board_for_lc(..., background=True)``,
  ``prefetch``, ``_set_engine_for_tests(engine, *, inline_worker)``,
  ``_wait_worker_idle_for_tests``, ``WORKER_THREAD_NAME``, and the row field
  ``focus_board_relog``.
"""

from __future__ import annotations

import copy
import json
import threading
import time

import pytest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.focus_board import compute_focus_board
from core import arena_coach_shadow as shadow
from core import focus_board_live as fbl
from dashboard._deterministic_coaching import shadow_log_arena_coach

_NOW = "2026-10-24T00:00:00+00:00"

_DET = {
    "action": "FIGHT SMART",
    "round_strategy": "Your HP 80% - trade efficiently and kite",
    "fight_rule": "",
    "augment_advice": "",
    "anvil_advice": "",
    "target_priority": "Kill Kai'Sa first - squishy threat; tanks last",
    "risk": "",
    "choices": [],
}

# The hook must return well inside this while a compute is held open; the
# fake compute holds for _HOLD_S, so a hook that waited would blow it.
_HOOK_BUDGET_S = 1.0
_HOLD_S = 10.0


@pytest.fixture(scope="module")
def snapshot():
    return DataSnapshot.load()


def _clear_shadow_dedup():
    # The dedup is keyed by str(target). With tmp_path retention "failed" a
    # passed test's dir is removed, so the NEXT test whose name shares the
    # 30-char tmp prefix gets the very same path string back (seen: the RM-844
    # byte-identical test after this file's) - clear on both sides.
    shadow._LAST_SIG.clear()
    shadow._LAST_FB_STATUS.clear()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv(fbl.KILL_SWITCH_ENV, raising=False)
    fbl.reset_for_tests()
    _clear_shadow_dedup()
    yield
    fbl.reset_for_tests()
    _clear_shadow_dedup()


def _player(name, raw, team, level, items, summ):
    return {"summonerName": summ, "riotIdGameName": summ.split("#")[0],
            "championName": name, "rawChampionName": raw, "team": team,
            "level": level,
            "items": [{"itemID": i, "slot": n} for n, i in enumerate(items)],
            "scores": {"kills": 0, "deaths": 0, "assists": 0}}


def _lc(foe_level: int = 12) -> dict:
    return {
        "champion": "Jinx",
        "level": 12,
        "enemy_team": ["Wukong", "Dr. Mundo", "Kai'Sa"],
        "activePlayer": {"summonerName": "Me#TST", "riotIdGameName": "Me"},
        "allPlayers": [
            _player("Jinx", "game_character_displayname_Jinx", "100", 12,
                    [3006, 3031], "Me#TST"),
            _player("Karma", "game_character_displayname_Karma", "100", 12,
                    [3504], "Duo#TST"),
            _player("Wukong", "game_character_displayname_MonkeyKing", "200",
                    foe_level, [3071], "FoeA#TST"),
            _player("Dr. Mundo", "game_character_displayname_DrMundo", "200",
                    11, [3084], "FoeB#TST"),
            _player("Kai'Sa", "game_character_displayname_Kaisa", "300", 12,
                    [], "FoeC#TST"),
        ],
    }


def _coach(round_no: int = 4) -> dict:
    return {
        "champion": "Jinx",
        "hp_pct": 80,
        "camp_phase": False,
        "round": round_no,
        "alive_teams": 3,
        "teams": [
            {"name": "Jinx", "is_you": True},
            {"name": "Karma", "is_partner": True},
            {"name": "Wukong", "is_dead": False},
            {"name": "Dr. Mundo", "is_dead": False},
            {"name": "Kai'Sa", "is_dead": False},
        ],
        "items": [],
    }


def _rows(path):
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def _log(target, lc, round_label=4, det=None):
    return shadow.log_arena_coach(det or _DET, {}, lc, "arena",
                                  round_label=round_label, path=target,
                                  now_iso=_NOW)


def _wait_until(pred, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def _board_threads():
    return [t.name for t in threading.enumerate()
            if t.name in (fbl.WORKER_THREAD_NAME, "rc-focus-board-warm")
            and t.is_alive()]


# -- the contract the shadow keys on ----------------------------------------------

def test_transient_statuses_are_the_not_yet_ready_ones():
    assert fbl.TRANSIENT_STATUSES == frozenset({
        fbl.STATUS_WARMING, fbl.STATUS_THROTTLED, fbl.STATUS_PENDING})
    # A settled answer is never transient (it must not be re-logged).
    for settled in (fbl.STATUS_OK, fbl.STATUS_NO_BOARD, fbl.STATUS_NO_ROSTER,
                    fbl.STATUS_UNAVAILABLE, fbl.STATUS_ERROR,
                    fbl.STATUS_DISABLED):
        assert settled not in fbl.TRANSIENT_STATUSES
    # The shadow keeps its own literal copy (no adapter import on its import
    # path); the two must never drift apart.
    assert shadow._TRANSIENT_FB == fbl.TRANSIENT_STATUSES


# -- (a) warming / throttled, then ready: recorded exactly once --------------------

def test_warming_then_ready_records_the_board_exactly_once(
        tmp_path, monkeypatch, snapshot):
    gate = threading.Event()

    def slow_load():
        gate.wait(_HOLD_S)
        return snapshot, compute_focus_board
    monkeypatch.setattr(fbl, "_load_engine", slow_load)
    target = tmp_path / "s.jsonl"
    lc = _lc()

    assert _log(target, lc) is not None                 # engine cold
    assert _log(target, lc) is None                     # same state, still warming
    [first] = _rows(target)
    assert first["focus_board"]["status"] == fbl.STATUS_WARMING
    assert "focus_board_relog" not in first

    gate.set()
    fbl._join_warm_for_tests(_HOLD_S)
    # Engine up, board not computed yet: the read only queues it (pending).
    assert _log(target, lc) is None
    assert fbl._wait_worker_idle_for_tests(_HOLD_S)

    relog = _log(target, lc)
    assert relog is not None
    for _ in range(5):                                  # never a duplicate
        assert _log(target, lc) is None
    rows = _rows(target)
    assert len(rows) == 2
    assert rows[1] == relog
    fb = rows[1]["focus_board"]
    assert fb["status"] == fbl.STATUS_OK, fb["notes"]
    assert fb["board_pick"] and fb["rule_pick"] == "Kai'Sa"
    assert rows[1]["focus_board_relog"] is True
    # Same tick key, same authoritative rule column.
    assert rows[1]["deterministic"] == rows[0]["deterministic"] == _DET
    assert rows[1]["round"] == rows[0]["round"] == 4
    assert [r["focus_board"]["status"] for r in rows].count(fbl.STATUS_OK) == 1


def test_throttled_then_ready_records_once(tmp_path, monkeypatch, snapshot):
    # inline_worker=True keeps the old synchronous compute, the one path that
    # can still hand the shadow a ``throttled`` status.
    fbl._set_engine_for_tests((snapshot, compute_focus_board),
                              inline_worker=True)
    target = tmp_path / "s.jsonl"
    assert _log(target, _lc(12), round_label=4)["focus_board"]["status"] \
        == fbl.STATUS_OK
    # A new round with a changed roster inside the 2 s window is throttled.
    rec = _log(target, _lc(13), round_label=5)
    assert rec["focus_board"]["status"] == fbl.STATUS_THROTTLED
    assert _log(target, _lc(13), round_label=5) is None
    monkeypatch.setattr(fbl, "MIN_COMPUTE_INTERVAL_S", 0.0)
    relog = _log(target, _lc(13), round_label=5)
    assert relog is not None and relog["focus_board_relog"] is True
    assert relog["focus_board"]["status"] == fbl.STATUS_OK
    assert _log(target, _lc(13), round_label=5) is None
    assert [(r["round"], r["focus_board"]["status"]) for r in _rows(target)] == [
        (4, fbl.STATUS_OK), (5, fbl.STATUS_THROTTLED), (5, fbl.STATUS_OK)]


def test_settled_rows_are_never_relogged(tmp_path, snapshot):
    fbl._set_engine_for_tests((snapshot, compute_focus_board),
                              inline_worker=True)
    target = tmp_path / "s.jsonl"
    # no_roster is a settled answer: no re-log however many ticks follow.
    assert _log(target, {"champion": "Jinx"})["focus_board"]["status"] \
        == fbl.STATUS_NO_ROSTER
    assert _log(target, _lc()) is None      # roster appears, same tick key
    assert len(_rows(target)) == 1


def test_dedup_ticks_feed_the_worker_so_the_next_row_is_ready(
        tmp_path, monkeypatch, snapshot):
    monkeypatch.setattr(fbl, "MIN_COMPUTE_INTERVAL_S", 0.0)
    fbl._set_engine_for_tests((snapshot, compute_focus_board),
                              inline_worker=False)
    target = tmp_path / "s.jsonl"
    _log(target, _lc(12), round_label=4)               # pending (queued)
    assert fbl._wait_worker_idle_for_tests(_HOLD_S)
    assert _log(target, _lc(12), round_label=4)["focus_board_relog"] is True
    # The roster changes inside the same tick key: no row, but the board for
    # the new roster is computed off-thread from the dedup tick ...
    assert _log(target, _lc(13), round_label=4) is None
    assert fbl._wait_worker_idle_for_tests(_HOLD_S)
    # ... so the next round's row is ready on its first write (no re-log).
    nxt = _log(target, _lc(13), round_label=5)
    assert nxt["focus_board"]["status"] == fbl.STATUS_OK
    assert "focus_board_relog" not in nxt
    assert len(_rows(target)) == 3


# -- (b) the compute is off the state-builder thread --------------------------------

def test_state_builder_hook_never_waits_on_the_compute(
        tmp_path, monkeypatch, snapshot):
    release = threading.Event()
    started = threading.Event()
    compute_threads: list = []

    def slow_compute(*a, **k):
        compute_threads.append(threading.current_thread().name)
        started.set()
        release.wait(_HOLD_S)
        return compute_focus_board(*a, **k)
    fbl._set_engine_for_tests((snapshot, slow_compute), inline_worker=False)
    missing = tmp_path / "missing.json"
    # Warm every cold import the hook touches (kill switch on, no board).
    monkeypatch.setenv(fbl.KILL_SWITCH_ENV, "0")
    shadow_log_arena_coach(_coach(3), _lc(), "arena",
                           path=tmp_path / "warmup.jsonl", live_path=missing)
    monkeypatch.delenv(fbl.KILL_SWITCH_ENV)

    target = tmp_path / "s.jsonl"
    t0 = time.perf_counter()
    shadow_log_arena_coach(_coach(), _lc(), "arena", path=target,
                           live_path=missing)
    elapsed = time.perf_counter() - t0
    try:
        assert elapsed < _HOOK_BUDGET_S, f"hook blocked {elapsed:.3f}s"
        [row] = _rows(target)
        assert row["focus_board"]["status"] == fbl.STATUS_PENDING
        # The compute really is running, and not on this (caller) thread.
        assert started.wait(_HOLD_S)
        assert compute_threads == [fbl.WORKER_THREAD_NAME]
        # A tick while the compute is still held open does not wait either.
        t1 = time.perf_counter()
        shadow_log_arena_coach(_coach(), _lc(), "arena", path=target,
                               live_path=missing)
        assert time.perf_counter() - t1 < _HOOK_BUDGET_S
        assert len(_rows(target)) == 1
    finally:
        release.set()
    assert fbl._wait_worker_idle_for_tests(_HOLD_S)
    shadow_log_arena_coach(_coach(), _lc(), "arena", path=target,
                           live_path=missing)
    rows = _rows(target)
    assert len(rows) == 2
    assert rows[1]["focus_board"]["status"] == fbl.STATUS_OK
    assert rows[1]["focus_board_relog"] is True


def test_worker_queue_is_bounded_latest_roster_wins(monkeypatch, snapshot):
    monkeypatch.setattr(fbl, "MIN_COMPUTE_INTERVAL_S", 0.0)
    release = threading.Event()
    started = threading.Event()
    seen: list = []

    def gated(snap, me, enemies, allies, **k):
        seen.append(enemies[0][1])          # the Wukong level = the roster
        started.set()
        release.wait(_HOLD_S)
        return compute_focus_board(snap, me, enemies, allies, **k)
    fbl._set_engine_for_tests((snapshot, gated), inline_worker=False)

    assert fbl.board_for_lc(_lc(12), "arena", background=True)["status"] \
        == fbl.STATUS_PENDING
    assert started.wait(_HOLD_S)            # level 12 is in flight
    for lvl in (13, 14, 15):                # each replaces the queued one
        out = fbl.board_for_lc(_lc(lvl), "arena", background=True)
        assert out["status"] == fbl.STATUS_PENDING
        assert out["top_kill"] is None
    release.set()
    assert fbl._wait_worker_idle_for_tests(_HOLD_S)
    assert seen == [12, 15]
    assert fbl.board_for_lc(_lc(15), "arena", background=True)["status"] \
        == fbl.STATUS_OK
    assert fbl.board_for_lc(_lc(12), "arena", background=True)["status"] \
        == fbl.STATUS_OK


def test_worker_waits_out_the_throttle_instead_of_dropping(monkeypatch,
                                                           snapshot):
    monkeypatch.setattr(fbl, "MIN_COMPUTE_INTERVAL_S", 0.3)
    fbl._set_engine_for_tests((snapshot, compute_focus_board),
                              inline_worker=False)
    fbl.board_for_lc(_lc(12), "arena", background=True)
    assert fbl._wait_worker_idle_for_tests(_HOLD_S)
    # Inside the window: the read never says throttled, the worker holds the
    # job and computes it once the window has passed.
    out = fbl.board_for_lc(_lc(13), "arena", background=True)
    assert out["status"] == fbl.STATUS_PENDING
    assert fbl._wait_worker_idle_for_tests(_HOLD_S)
    assert fbl.board_for_lc(_lc(13), "arena", background=True)["status"] \
        == fbl.STATUS_OK


def test_worker_failure_never_raises_and_settles(monkeypatch, snapshot):
    def broken(*_a, **_k):
        raise RuntimeError("SECRET-LEAK-MARKER")
    fbl._set_engine_for_tests((snapshot, compute_focus_board),
                              inline_worker=False)
    real_compute = fbl._compute
    monkeypatch.setattr(fbl, "_compute", broken)
    assert fbl.board_for_lc(_lc(12), "arena", background=True)["status"] \
        == fbl.STATUS_PENDING
    assert fbl._wait_worker_idle_for_tests(_HOLD_S)
    out = fbl.board_for_lc(_lc(12), "arena", background=True)
    assert out["status"] == fbl.STATUS_ERROR     # settled, not retried per tick
    assert "SECRET-LEAK-MARKER" not in json.dumps(out)
    # The worker survived: the next roster is computed normally.
    monkeypatch.setattr(fbl, "_compute", real_compute)
    monkeypatch.setattr(fbl, "MIN_COMPUTE_INTERVAL_S", 0.0)
    fbl.board_for_lc(_lc(13), "arena", background=True)
    assert fbl._wait_worker_idle_for_tests(_HOLD_S)
    assert fbl.board_for_lc(_lc(13), "arena", background=True)["status"] \
        == fbl.STATUS_OK


def test_the_worker_is_a_daemon_thread(snapshot):
    fbl._set_engine_for_tests((snapshot, compute_focus_board),
                              inline_worker=False)
    fbl.board_for_lc(_lc(), "arena", background=True)
    assert _wait_until(lambda: fbl.WORKER_THREAD_NAME in _board_threads())
    [worker] = [t for t in threading.enumerate()
                if t.name == fbl.WORKER_THREAD_NAME]
    assert worker.daemon is True


# -- the kill switch still disables everything --------------------------------------

def test_kill_switch_disables_everything(tmp_path, monkeypatch, snapshot):
    monkeypatch.setenv(fbl.KILL_SWITCH_ENV, "0")
    loads: list = []
    computes: list = []
    monkeypatch.setattr(fbl, "_load_engine", lambda: loads.append(1))
    target = tmp_path / "s.jsonl"
    missing = tmp_path / "missing.json"
    for rnd in (4, 4, 4, 5, 5):
        shadow_log_arena_coach(_coach(rnd), _lc(), "arena", path=target,
                               live_path=missing)
    assert fbl.board_for_lc(_lc(), "arena", background=True)["status"] \
        == fbl.STATUS_DISABLED
    fbl.prefetch(_lc(), "arena")
    # A ready engine is never asked for a board either.
    def counting(*a, **k):
        computes.append(1)
        return compute_focus_board(*a, **k)
    fbl._set_engine_for_tests((snapshot, counting), inline_worker=False)
    target2 = tmp_path / "s2.jsonl"
    for rnd in (4, 4, 5):
        shadow_log_arena_coach(_coach(rnd), _lc(), "arena", path=target2,
                               live_path=missing)
    fbl.prefetch(_lc(), "arena")
    rows = _rows(target) + _rows(target2)
    assert len(rows) == 4
    assert all("focus_board" not in r and "focus_board_relog" not in r
               for r in rows)
    fbl._join_warm_for_tests(5)
    assert loads == [] and computes == []
    assert _board_threads() == []


def test_kill_switch_drops_a_job_already_queued(monkeypatch, snapshot):
    release = threading.Event()
    started = threading.Event()
    seen: list = []

    def gated(snap, me, enemies, allies, **k):
        seen.append(enemies[0][1])
        started.set()
        release.wait(_HOLD_S)
        return compute_focus_board(snap, me, enemies, allies, **k)
    monkeypatch.setattr(fbl, "MIN_COMPUTE_INTERVAL_S", 0.0)
    fbl._set_engine_for_tests((snapshot, gated), inline_worker=False)
    fbl.board_for_lc(_lc(12), "arena", background=True)
    assert started.wait(_HOLD_S)
    fbl.board_for_lc(_lc(13), "arena", background=True)     # queued
    monkeypatch.setenv(fbl.KILL_SWITCH_ENV, "0")
    release.set()
    assert fbl._wait_worker_idle_for_tests(_HOLD_S)
    assert seen == [12]


# -- the served coach never changes ------------------------------------------------

def test_coach_output_byte_identical_with_and_without_the_shadow(
        tmp_path, monkeypatch, snapshot):
    fbl._set_engine_for_tests((snapshot, compute_focus_board),
                              inline_worker=False)
    missing = tmp_path / "missing.json"
    coach, lc = _coach(), _lc()
    coach_before = json.dumps(coach, sort_keys=True)
    lc_before = copy.deepcopy(lc)

    on = tmp_path / "on.jsonl"
    shadow_log_arena_coach(coach, lc, "arena", path=on, live_path=missing)
    assert fbl._wait_worker_idle_for_tests(_HOLD_S)
    shadow_log_arena_coach(coach, lc, "arena", path=on, live_path=missing)
    shadow_log_arena_coach(coach, lc, "arena", path=on, live_path=missing)
    assert json.dumps(coach, sort_keys=True) == coach_before
    assert lc == lc_before

    monkeypatch.setenv(fbl.KILL_SWITCH_ENV, "0")
    off = tmp_path / "off.jsonl"
    for _ in range(3):
        shadow_log_arena_coach(coach, lc, "arena", path=off, live_path=missing)
    assert json.dumps(coach, sort_keys=True) == coach_before
    assert lc == lc_before

    rows_on, [row_off] = _rows(on), _rows(off)
    assert [r["focus_board"]["status"] for r in rows_on] == [
        fbl.STATUS_PENDING, fbl.STATUS_OK]
    for row in rows_on:
        assert (json.dumps(row["deterministic"], sort_keys=True)
                == json.dumps(row_off["deterministic"], sort_keys=True))
        assert (json.dumps(row["live_haiku"], sort_keys=True)
                == json.dumps(row_off["live_haiku"], sort_keys=True))
    assert "focus_board" not in row_off
