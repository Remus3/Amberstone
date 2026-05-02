"""
app/__init__.py — OverlayApp orchestrator (post-T2 #6 dashboard-only)

ARCH-001 decomposed app.py 1228L into managers (HealthMonitor, RemediationService,
StateAuthority, OverlayManager, GameLifecycleManager). T2 #6 then removed the
tkinter overlay UI in favor of the web dashboard at :8888 — the tk.Tk() root
remains as the scheduler for game polling via root.after().

Sub-managers:
  app/_health_monitor.py     — HealthMonitor
  app/_remediation.py        — RemediationService (rebuild_panel_* now no-op)
  app/_state_authority.py    — StateAuthority + calc_win_pct
  app/_overlay_manager.py    — OverlayManager (mode persistence shell)
  app/_game_lifecycle.py     — GameLifecycleManager
"""
import queue
import sys
import os
import json
import logging
import threading
import traceback

import tkinter as tk
from pathlib import Path
from typing import Optional
from core.game_snapshot import (
    GameEnvelope, ClientSnapshot,
    MODE_CLIENT, MODE_SR, MODE_ARAM, MODE_TFT, MODE_ARENA, MODE_BRAWL,
)
from ._health_monitor   import HealthMonitor
from ._remediation     import RemediationService
from ._state_authority   import StateAuthority
from ._overlay_manager   import OverlayManager
from ._game_lifecycle    import GameLifecycleManager

_log = logging.getLogger("rc.app")
SCRIPT_DIR  = Path(__file__).parent.parent
ROOT_PATH   = SCRIPT_DIR
DATA_FILE   = SCRIPT_DIR / "coaching_data.json"

POLL_DATA_MS = 500
POLL_GAME_MS = 1500

from core.polled_json import atomic_write_json as _atomic_write_json

try:
    from game_reader import GameReader; HAS_READER = True
except ImportError: HAS_READER = False
try:
    from core.sr_aram_worker import SrAramWorker, WorkerResult; HAS_WORKER = True
except ImportError: HAS_WORKER = False
try:
    from core.tft_worker import TftWorker, TftWorkerResult; HAS_TFT_WORKER = True
except ImportError: HAS_TFT_WORKER = False
try:
    from item_advisor import get_purchase_advice; HAS_ADVISOR = True
except ImportError: HAS_ADVISOR = False
try:
    from coach_integration import CoachIntegration; HAS_COACH = True
except Exception: HAS_COACH = False
try:
    from performance_tracker import save_rating, save_tft_rating; HAS_TRACKER = True
except Exception: HAS_TRACKER = False
try:
    from composition_advisor import comp_context_str; HAS_COMP_ADVISOR = True
except Exception: HAS_COMP_ADVISOR = False


class OverlayApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.report_callback_exception = self._tk_exception

        self.mode          = "client"
        self.data          = {}
        self._last_mtime   = 0
        self._game_state   = None
        self._was_in_game  = False
        self._auto_mode    = True
        self._tft_mode     = False
        self._arena_mode   = False
        self._brawl_mode   = False
        self._aram_mode    = False
        self._tft_coach    = None
        self._last_mode    = "SR"

        self.reader  = GameReader() if HAS_READER else None
        self.overlays = OverlayManager(self)
        self.overlays.build_windows()
        self._init_data_file()

        self._coach = None
        if HAS_COACH:
            try:
                self._coach = CoachIntegration(
                    DATA_FILE,
                    debug="--debug" in sys.argv or os.environ.get("LOL_COACH_DEBUG") == "1",
                )
            except Exception as exc:
                # AUDIT P-rc-frozen-app-init-swallow (2026-04-22): silent
                # failure here used to leave self._coach=None with no log —
                # subsystems downstream would "work" but produce no coaching.
                _log.exception("CoachIntegration init failed — coach disabled: %s", exc)
                self._coach = None

        self._sr_aram_q = queue.Queue(maxsize=2)
        _comp_ctx = comp_context_str if HAS_COMP_ADVISOR else None
        self._sr_aram_worker: Optional[SrAramWorker] = (
            SrAramWorker(
                result_queue=self._sr_aram_q,
                coach=self._coach if HAS_COACH else None,
                comp_context_fn=_comp_ctx,
            )
            if HAS_WORKER else None
        )

        self._tft_q: queue.Queue = queue.Queue(maxsize=4)
        self._tft_worker: Optional[TftWorker] = None

        self._game_q         = queue.Queue(maxsize=2)
        self._game_poll_stop = threading.Event()
        self._none_streak    = 0
        self._game_poll_gen  = 0

        self._poll_worker_pulse_ts: float  = 0.0
        self._poll_worker_last_success_ts: float = 0.0
        self._overlay_visible:     bool    = False

        self._poll_file()
        self.root.after(200, self._start_game_poll)
        # Managers
        self.health    = HealthMonitor(self)
        self.remediate = RemediationService(self)
        self.state     = StateAuthority()
        self.lifecycle = GameLifecycleManager(self)
        self.health.start()
        self._init_envelope()
        self._apply_mode(self.mode)

    # ── Envelope stubs (Phase 2) ───────────────────────────────────────────────

    def _init_envelope(self) -> None:
        self.state.init()

    def get_snapshot(self) -> GameEnvelope:
        return self.state.get_snapshot()

    def _update_envelope(self, mode: str, payload) -> None:
        self.state.set_envelope(mode, payload)
        self._tft_mode   = (mode == MODE_TFT)
        self._aram_mode  = (mode == MODE_ARAM)
        self._arena_mode = (mode == MODE_ARENA)
        self._brawl_mode = (mode == MODE_BRAWL)
        _log.debug("envelope: mode=%s tft=%s aram=%s arena=%s brawl=%s",
                   mode, self._tft_mode, self._aram_mode, self._arena_mode, self._brawl_mode)

    def _tk_exception(self, et, ev, tb):
        msg = "".join(traceback.format_exception(et, ev, tb))
        _log.error("Tkinter exception:\n%s", msg)
        if sys.stderr:
            sys.stderr.write(msg)

    # ── Overlay stubs (post-T2 #6: dashboard-only) ───────────────────────────

    def _build_windows(self):
        self.overlays.build_windows()

    def _all_windows(self):
        yield from self.overlays.all_windows()

    def _switch_mode(self, mode, auto=False):
        self.overlays.switch_mode(mode, auto=auto)

    def _apply_mode(self, mode):
        self.overlays.apply_mode(mode)

    def _update_content(self):
        self.overlays.update_content()

    # ── Health stubs (Phase 1) ────────────────────────────────────────────────

    def _tk_pulse(self):
        self.health.pulse()

    def get_health_state(self) -> dict:
        return self.health.get_health_state()

    # ── Remediation stubs (Phase 1) ───────────────────────────────────────────

    def restart_game_poll(self) -> dict:
        return self.remediate.restart_game_poll()

    def _rebuild_panel(self, key: str) -> dict:
        return self.remediate.rebuild_panel(key)

    def rebuild_panel_game_bottom(self) -> dict:
        return self.remediate.rebuild_panel("game_bottom")

    def rebuild_panel_game_rtop(self) -> dict:
        return self.remediate.rebuild_panel("game_rtop")

    def rebuild_panel_game_rbot(self) -> dict:
        return self.remediate.rebuild_panel("game_rbot")

    # ── Lifecycle stubs (Phase 4) ─────────────────────────────────────────────

    def _on_game_start(self, canon_mode: str) -> None:
        self.lifecycle.on_game_start(canon_mode)

    def _on_game_end(self):
        self.lifecycle.on_game_end()

    def _start_game_poll(self):
        self.lifecycle.start_game_poll()

    def _game_poll_worker(self, my_gen: int):
        self.lifecycle.game_poll_worker(my_gen)

    def _drain_game_q(self):
        self.lifecycle.drain_game_q()

    def _drain_tft_q(self):
        self.lifecycle.drain_tft_q()

    def _try_read_api_key(self) -> str:
        return self.lifecycle.try_read_api_key()

    def _process_worker_result(self, result):
        self.lifecycle.process_worker_result(result)

    def _process_game_state(self, state, is_first=None, canon_mode=None):
        self.lifecycle.process_game_state(state, is_first=is_first, canon_mode=canon_mode)

    def _apply_auto_fields(self, state):
        self.lifecycle.apply_auto_fields(state)

    # ── Win-pct stub (Phase 2) ────────────────────────────────────────────────

    @staticmethod
    def _calc_win_pct(state):
        return StateAuthority.calc_win_pct(state)

    # ── Data file / poll ──────────────────────────────────────────────────────

    def _init_data_file(self):
        pg = ""
        try:
            if DATA_FILE.exists():
                pg = json.loads(DATA_FILE.read_text(encoding="utf-8")).get("pregame", "")
        except Exception: pass
        cl = {
            "mode": "client", "action": "", "immediate": "", "next": "",
            "fight_rule": "", "wave": "", "objective": "", "reset_item": "",
            "risk": "", "map": "", "win_pct": None, "log": [],
            "pregame": pg or "Waiting for draft data...\n\nPaste game state in chat to begin coaching.",
        }
        try: _atomic_write_json(DATA_FILE, cl)
        except Exception: pass

    def _poll_file(self):
        try:
            mt = DATA_FILE.stat().st_mtime
            if mt != self._last_mtime:
                self._last_mtime = mt
                self.data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
                nm = self.data.get("mode", self.mode)
                if nm != self.mode and not self._auto_mode:
                    self.mode = nm; self._apply_mode(nm)
                else:
                    self._update_content()
        except Exception: pass
        self.root.after(POLL_DATA_MS, self._poll_file)

    def _write_data(self):
        try:
            _atomic_write_json(DATA_FILE, self.data)
            self._last_mtime = DATA_FILE.stat().st_mtime
        except Exception: pass

    def _force_refresh(self): self._last_mtime = 0

    def _toggle_auto(self): self._auto_mode = not self._auto_mode

    # ── Process lifecycle ─────────────────────────────────────────────────────

    def shutdown(self):
        # AUDIT P-rc-frozen-app-init-swallow (2026-04-22): log shutdown
        # failures instead of swallowing — invisible failures here have
        # stranded workers during past restarts.
        if self._sr_aram_worker is not None:
            self._sr_aram_worker.stop()
        if self._tft_worker is not None:
            try: self._tft_worker.shutdown()
            except Exception:
                _log.exception("tft_worker.shutdown raised")
            self._tft_worker = None
        self._game_poll_stop.set()
        try: self._update_envelope(MODE_CLIENT, ClientSnapshot())
        except Exception:
            _log.exception("update_envelope(MODE_CLIENT) on shutdown raised")

    def _quit(self):
        if self._sr_aram_worker is not None:
            self._sr_aram_worker.stop()
        if self._tft_worker is not None:
            try: self._tft_worker.stop()
            except Exception:
                _log.exception("tft_worker.stop raised in _quit")
        self._game_poll_stop.set()
        self.root.quit()
        self.root.destroy()
        sys.exit(0)

    def run(self):
        self.root.mainloop()
