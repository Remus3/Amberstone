"""
app/__init__.py — OverlayApp orchestrator (ARCH-001 complete)

Original app.py: 1228 lines
After ARCH-001 Phases 1-4: 434 lines (-65%)

Extracted managers:
  app/_health_monitor.py   (81L)  — HealthMonitor
  app/_remediation.py     (132L)  — RemediationService
  app/_state_authority.py  (95L)  — StateAuthority + calc_win_pct
  app/_overlay_manager.py (238L)  — OverlayManager (12 Tk methods)
  app/_game_lifecycle.py  (494L)  — GameLifecycleManager (10 game methods)
"""
import queue
import sys
import os
import json
import logging
import threading
import time
import traceback

try:
    from core.hotkeys import start as _start_hotkeys
except Exception: _start_hotkeys = None
import tkinter as tk
from pathlib import Path
from typing import Optional
from core.theme import EXCLUDED_MODES, FIELD_COLORS
from core.game_snapshot import (
    GameEnvelope, ClientSnapshot, RiftSnapshot, AramSnapshot, TftSnapshot,
    MODE_CLIENT, MODE_SR, MODE_ARAM, MODE_TFT, MODE_ARENA, MODE_BRAWL,
    mode_from_game_mode_string,
)
from ui import GameBottomStrip, GameRightTop, GameRightBot, ClientPanel, ModeIndicator
from ._health_monitor  import HealthMonitor        # ARCH-001 Phase 1
from ._remediation    import RemediationService    # ARCH-001 Phase 1
from ._state_authority   import StateAuthority     # ARCH-001 Phase 2
from ._overlay_manager   import OverlayManager     # ARCH-001 Phase 3
from ._game_lifecycle    import GameLifecycleManager  # ARCH-001 Phase 4

_log = logging.getLogger("rc.app")
SCRIPT_DIR  = Path(__file__).parent.parent
ROOT_PATH   = SCRIPT_DIR
DATA_FILE   = SCRIPT_DIR / "coaching_data.json"

POLL_DATA_MS = 500
POLL_GAME_MS = 1500

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


def _safe_log(label):
    try: _log.error("%s:\n%s", label, traceback.format_exc())
    except Exception: pass


class OverlayApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        try:
            _cs = ROOT_PATH / "data" / "comp_state.json"
            self._client_panel_closed = __import__("json").loads(
                _cs.read_text(encoding="utf-8")).get("client_panel_closed", False) if _cs.exists() else False
        except Exception:
            self._client_panel_closed = False
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
        self.root.after(500, self._wire_ops_tab)
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

    # ── OPS tab ───────────────────────────────────────────────────────────────

    def _wire_ops_tab(self) -> None:
        try:
            panel = self.client_windows.get('main')
            if panel is not None and hasattr(panel, 'set_metrics_cache'):
                import sys as _sys
                _entrypoint = _sys.modules.get('__main__')
                mc = getattr(_entrypoint, '_metrics_cache', None) if _entrypoint is not None else None
                if mc is not None:
                    panel.set_metrics_cache(mc)
            self.root.after(5000, self._refresh_ops_tab)
        except Exception:
            self.root.after(5000, self._refresh_ops_tab)

    def _refresh_ops_tab(self) -> None:
        try:
            panel = self.client_windows.get('main')
            if panel is not None and hasattr(panel, 'refresh_ops'):
                panel.refresh_ops()
        except Exception:
            pass
        self.root.after(5000, self._refresh_ops_tab)

    def _tk_exception(self, et, ev, tb):
        msg = "".join(traceback.format_exception(et, ev, tb))
        _log.error("Tkinter exception:\n%s", msg)
        if sys.stderr:
            sys.stderr.write(msg)

    # ── Overlay stubs (Phase 3) ───────────────────────────────────────────────

    def _build_windows(self):
        self.overlays.build_windows()

    def _all_windows(self):
        yield from self.overlays.all_windows()

    def _get_active_client_tab(self) -> str:
        return self.overlays.get_active_tab()

    def _switch_to_game_from_tab(self) -> None:
        self.overlays.switch_to_game_from_tab()

    def _attach_preview_overlay(self, canon_mode: str) -> None:
        self.overlays.attach_preview(canon_mode)

    def _teardown_preview_overlay(self) -> None:
        self.overlays.teardown_preview()

    def _close_client_panel(self):
        self.overlays.close_panel()

    def _reopen_client_panel(self):
        self.overlays.reopen_panel()

    def _persist_panel_state(self, closed: bool):
        self.overlays.persist_panel_state(closed)

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

    # ── Context menu (stays in orchestrator) ──────────────────────────────────

    _TAB_TO_MODE = {
        "SR":    MODE_SR, "ARAM":  MODE_ARAM, "ARENA": MODE_ARENA,
        "BRAWL": MODE_BRAWL, "TFT": MODE_TFT, "OPS": MODE_ARAM,
    }

    def _context_menu(self, event):
        m = tk.Menu(self.root, tearoff=0, bg="#1a1a24", fg="#c0c0d0",
                    activebackground="#2a2a3a", activeforeground="#ffffff",
                    font=("Segoe UI", 9))
        m.add_command(label="Client Mode",
                      command=lambda: self._switch_mode("client", auto=False),
                      state="disabled" if self.mode == "client" else "normal")
        _tab_label = self._get_active_client_tab()
        _game_label = f"Game Mode ({_tab_label})" if _tab_label != "SR" else "Game Mode"
        m.add_command(label=_game_label,
                      command=self._switch_to_game_from_tab,
                      state="disabled" if self.mode == "game" else "normal")
        m.add_separator()
        if self.reader and self._game_state:
            m.add_command(label="Copy State for Claude", command=self._copy_state_to_clipboard)
            m.add_separator()
        if self._coach and self._game_state:
            m.add_command(label="Request Coaching Now",
                          command=lambda: self._coach.request_now(self._game_state))
            m.add_command(label="Flag Bad Advice", command=self._coach.flag_last_bad)
            wm = tk.Menu(m, tearoff=0, bg="#1a1a24", fg="#c0c0d0",
                         activebackground="#2a2a3a", activeforeground="#ffffff",
                         font=("Segoe UI", 9))
            for wk, wl in [
                ("freeze_or_hold", "Freeze / Hold (30s)"),
                ("neutral",        "Neutral (30s)"),
                ("slowpush",       "Slowpush (30s)"),
                ("hard_shove",     "Hard Shove (30s)"),
                ("crash",          "Crash (30s)"),
            ]:
                wm.add_command(label=wl, command=lambda s=wk: self._coach.set_wave_override(s))
            m.add_cascade(label="Wave Override \u2192", menu=wm)
            m.add_separator()
        m.add_command(
            label="Auto-detect: ON" if self._auto_mode else "Auto-detect: OFF",
            command=self._toggle_auto,
        )
        m.add_separator()
        m.add_command(label="Refresh Now", command=self._force_refresh)
        if self.mode == "client":
            m.add_command(label="Close Panel", command=self._close_client_panel)
        else:
            m.add_command(label="Show Client Panel", command=self._reopen_client_panel)
        m.add_separator()
        m.add_command(label="Quit", command=self._quit)
        try:   m.tk_popup(event.x_root, event.y_root)
        finally: m.grab_release()

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
        try: DATA_FILE.write_text(json.dumps(cl, indent=2), encoding="utf-8")
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
            DATA_FILE.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            self._last_mtime = DATA_FILE.stat().st_mtime
        except Exception: pass

    def _force_refresh(self): self._last_mtime = 0

    def _toggle_auto(self): self._auto_mode = not self._auto_mode

    def _copy_state_to_clipboard(self):
        if self.reader and self._game_state:
            t = self.reader.format_for_claude(self._game_state)
            if t:
                self.root.clipboard_clear()
                self.root.clipboard_append(t)

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
