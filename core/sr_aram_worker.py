"""
core/sr_aram_worker.py
Phase 1 Step 4 / Step 4.1 - SR/ARAM/Arena/Brawl poll worker.

Owns a dedicated GameReader instance, runs the non-TFT read loop on a
background thread, and hands structured WorkerResult objects to app.py
via a thread-safe queue.  Also owns SR coaching orchestration:
the worker calls coach.submit_state() after building the enriched state
dict for SR (CLASSIC/RANKED) modes only.

ARAM coaching: app.py starts a dedicated coaches.aram_coach on ARAM game
start.  The worker does NOT submit generic coaching for ARAM - this is the
intended permanent architecture, not deferred debt.  ARAM coaching authority
belongs exclusively to coaches.aram_coach to avoid dual authority.

Ownership boundaries:
  WORKER owns:
    - GameReader lifecycle (init + per-game state reset via reset_reader_state())
    - poll backoff / retry logic
    - generation-safety (supersession detection)
    - health / liveness pulse timestamps
    - SR (CLASSIC/RANKED) coaching submission (submit_state + comp_context)
    - None-streak tracking and game-end detection
  APP.PY owns:
    - GameEnvelope authority (sole writer of _current_envelope)
    - derived compatibility surfaces (_game_state, legacy mode flags)
    - Tk/UI lifecycle
    - special-mode (TFT/ARAM/Arena/Brawl) coach startup/shutdown
    - consuming WorkerResult from the result_queue

No Tk calls may appear in this module.  All state mutations to the
authoritative GameEnvelope happen in app.py after consuming results.

Python 3.9 compatible: no X|Y unions, no walrus, no match.
"""
from __future__ import annotations

import logging
import queue
import time
from typing import Any, Dict, Optional

from core.base_worker import BaseCoachWorker

_log = logging.getLogger("rc.worker")

# -- Poll timing constants (shared with app.py) -----------------------------
POLL_INTERVAL_S:   float = 1.5    # nominal poll cadence between reads
BACKOFF_MIN_S:     float = POLL_INTERVAL_S
BACKOFF_MAX_S:     float = 8.0    # max backoff on None / exception
NONE_STREAK_END:   int   = 5      # None reads before declaring game ended


# -- WorkerResult ----------------------------------------------------------

class WorkerResult:
    __slots__ = (
        "state",
        "is_first",
        "canon_mode",
        "end_signal",
        "pulse_ts",
        "last_success",
    )

    def __init__(
        self,
        state: Optional[Dict[str, Any]],
        is_first: bool = False,
        canon_mode: str = "SR",
        end_signal: bool = False,
        pulse_ts: float = 0.0,
        last_success: float = 0.0,
    ) -> None:
        self.state        = state
        self.is_first     = is_first
        self.canon_mode   = canon_mode
        self.end_signal   = end_signal
        self.pulse_ts     = pulse_ts
        self.last_success = last_success


# -- SrAramWorker ----------------------------------------------------------

class SrAramWorker(BaseCoachWorker):
    # AUDIT 2026-04-28 (proposal 1.4): lifecycle (start/stop/join/restart/
    # is_alive + pulse timestamps) lives on BaseCoachWorker. Subclass
    # holds reader + coaching specifics and the _run loop body only.
    _thread_name_prefix = "SrAramWorker"
    _restart_join_timeout_s = BACKOFF_MIN_S * 2

    def __init__(
        self,
        result_queue: "queue.Queue[WorkerResult]",
        coach: Any = None,
        comp_context_fn: Any = None,
    ) -> None:
        super().__init__()
        self._result_queue   = result_queue
        self._coach          = coach
        self._comp_ctx_fn    = comp_context_fn
        self._reader: Any = None

    def reset_reader_state(self, reason: str = "") -> None:
        if self._reader is not None:
            try:
                self._reader._enemy_last_seen  = {}
                self._reader._enemy_death_time = {}
                if reason:
                    _log.debug("SrAramWorker: reader state reset (%s)", reason)
            except Exception as exc:  # noqa: BLE001
                _log.warning("SrAramWorker: reset_reader_state failed: %s", exc)

    def _init_reader(self) -> bool:
        if self._reader is not None:
            return True
        try:
            from game_reader import GameReader
            self._reader = GameReader()
            return True
        except Exception as exc:  # noqa: BLE001
            _log.error("SrAramWorker: GameReader import failed: %s", exc)
            return False

    def _run(self, my_gen: int) -> None:
        if not self._init_reader():
            _log.error("SrAramWorker gen=%d: no GameReader - exiting", my_gen)
            return

        backoff      = BACKOFF_MIN_S
        was_in_game  = False
        none_streak  = 0

        while not self._stop_event.is_set():
            if my_gen != self._generation:
                _log.debug("SrAramWorker gen=%d superseded - exiting", my_gen)
                return

            self.pulse_ts = time.monotonic()

            try:
                state = self._reader.read_game()

                if my_gen != self._generation:
                    _log.debug("SrAramWorker gen=%d superseded post-read - discarding", my_gen)
                    return

                if state:
                    none_streak = 0
                    self.last_success_ts = time.monotonic()
                    backoff = BACKOFF_MIN_S
                    is_first = not was_in_game
                    was_in_game = True

                    canon_mode = "SR"
                    if is_first:
                        try:
                            from core.game_snapshot import mode_from_game_mode_string
                            gm = state.get("game_mode", "CLASSIC").upper()
                            canon_mode = mode_from_game_mode_string(gm)
                        except Exception:  # noqa: BLE001
                            canon_mode = "SR"

                    gm_upper = state.get("game_mode", "CLASSIC").upper()
                    # Fire SR coach for live PvP + Practice Tool. PRACTICETOOL
                    # re-enabled 2026-06-20 so the in-game overlay is usable and
                    # testable in practice (panels populate live, incl vs bots).
                    is_sr_mode = gm_upper in ("CLASSIC", "RANKED", "PRACTICETOOL")
                    if self._coach is not None and is_sr_mode:
                        self._submit_coaching(state)

                    result = WorkerResult(
                        state=state,
                        is_first=is_first,
                        canon_mode=canon_mode,
                        end_signal=False,
                        pulse_ts=self.pulse_ts,
                        last_success=self.last_success_ts,
                    )
                    self._enqueue(result)

                else:
                    none_streak += 1
                    backoff = min(backoff * 1.5, BACKOFF_MAX_S)

                    if was_in_game and none_streak >= NONE_STREAK_END:
                        _log.info("SrAramWorker: game-end detected (none_streak=%d)", none_streak)
                        result = WorkerResult(
                            state=None,
                            is_first=False,
                            end_signal=True,
                            pulse_ts=self.pulse_ts,
                            last_success=self.last_success_ts,
                        )
                        self._enqueue(result)
                        was_in_game = False
                        none_streak = 0
                        backoff = BACKOFF_MIN_S

            except Exception:  # noqa: BLE001
                backoff = min(backoff * 1.5, BACKOFF_MAX_S)
                _log.debug("SrAramWorker read error", exc_info=True)

            self._stop_event.wait(backoff)

        _log.info("SrAramWorker gen=%d exited cleanly", my_gen)

    def _submit_coaching(self, state: dict) -> None:
        try:
            try:
                from core.feature_policy import is_allowed, write_disabled_placeholder
                if not is_allowed("sr", "live_coaching"):
                    write_disabled_placeholder("sr")
                    return
            except Exception:  # noqa: BLE001
                pass  # policy module unavailable - allow by default

            dead_enemies = state.get("dead_enemies", [])
            dead_count   = len(dead_enemies)
            kill_window  = dead_count >= 2
            swd = dict(state, dead_count=dead_count, kill_window=kill_window)

            if self._comp_ctx_fn is not None:
                try:
                    swd["comp_context"] = self._comp_ctx_fn(
                        champion=state.get("champion", ""),
                        current_items=state.get("items", []),
                        enemy_champs=state.get("enemy_comp", []),
                        ally_champs=state.get("ally_comp", []),
                        enemy_items_flat=[],
                        game_mode=state.get("game_mode", "CLASSIC"),
                    )
                except Exception as _exc:  # QUAL-002  # noqa: BLE001
                    _log.debug("item_advisor call: %s", _exc)

            self._coach.submit_state(swd)
        except Exception:  # noqa: BLE001
            _log.debug("SrAramWorker: coaching submit failed", exc_info=True)

    def _enqueue(self, result: WorkerResult) -> None:
        try:
            self._result_queue.put_nowait(result)
        except queue.Full:
            try:    self._result_queue.get_nowait()
            except queue.Empty: pass
            try:    self._result_queue.put_nowait(result)
            except queue.Full: pass
