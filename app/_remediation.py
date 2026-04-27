"""
app/_remediation.py — RemediationService extracted from app.py (ARCH-001)

Owns DevRuntime remediation callbacks (restart_game_poll, rebuild_panel).
No state of its own — delegates entirely to OverlayApp and its sub-systems.

All methods are called from the DevRuntimeCommands thread.
ALL Tk interactions are marshalled via app.root.after(0, fn).
Results are returned through a queue.Queue with a 5-second timeout.
"""

import queue
import threading


class RemediationService:
    """
    Owns:
      restart_game_poll()             — restart SrAramWorker safely
      rebuild_panel(key)              — destroy and recreate a named game panel
      rebuild_panel_game_bottom()     — convenience wrapper
      rebuild_panel_game_rtop()       — convenience wrapper
      rebuild_panel_game_rbot()       — convenience wrapper

    OverlayApp delegates all five methods here.
    """

    def __init__(self, app: "OverlayApp") -> None:  # type: ignore[name-defined]
        self.app = app

    # ── Restart poll worker ───────────────────────────────────────────────────

    def restart_game_poll(self) -> dict:
        """
        Restart the game-poll worker safely.
        Prefers SrAramWorker.restart() (generation-safe);
        falls back to legacy thread spawn when no worker is present.
        """
        app = self.app
        result_q: queue.Queue = queue.Queue(maxsize=1)

        def _do_restart():
            try:
                if app._sr_aram_worker is not None:
                    app._sr_aram_worker.restart()
                    result_q.put({"ok": True, "detail": "SrAramWorker restarted"})
                else:
                    # Legacy path: no SrAramWorker — spawn a bare thread
                    app._game_poll_gen += 1
                    new_gen = app._game_poll_gen
                    app._none_streak = 0
                    app._game_poll_stop.clear()
                    t = threading.Thread(
                        target=app._game_poll_worker,
                        args=(new_gen,),
                        name=f"GamePoll-{new_gen}",
                        daemon=True,
                    )
                    t.start()
                    result_q.put({"ok": True,
                                  "detail": f"legacy game_poll_worker gen={new_gen} started"})
            except Exception as exc:
                result_q.put({"ok": False, "error": str(exc)})

        app.root.after(0, _do_restart)
        try:
            return result_q.get(timeout=5.0)
        except queue.Empty:
            return {"ok": False, "error": "restart_game_poll timeout"}

    # ── Rebuild named panel ───────────────────────────────────────────────────

    def rebuild_panel(self, key: str) -> dict:
        """
        Destroy and recreate a named game-mode overlay panel.
        key must be one of: "game_bottom", "game_rtop", "game_rbot".
        """
        app = self.app
        result_q: queue.Queue = queue.Queue(maxsize=1)

        panel_map = {
            "game_bottom": "bottom",
            "game_rtop":   "rtop",
            "game_rbot":   "rbot",
        }
        win_key = panel_map.get(key)

        def _do_rebuild():
            try:
                if win_key is None or win_key not in app.game_windows:
                    result_q.put({"ok": False, "error": f"unknown panel key: {key!r}"})
                    return
                old_win = app.game_windows[win_key]
                try:
                    old_win.hide()
                    old_win.top.destroy()
                except Exception:
                    pass
                # Import panel classes from the same place app.py does
                from ui import GameBottomStrip, GameRightTop, GameRightBot
                cls_map = {
                    "bottom": GameBottomStrip,
                    "rtop":   GameRightTop,
                    "rbot":   GameRightBot,
                }
                new_win = cls_map[win_key](app.root)
                new_win.attach_menu(app._context_menu)
                app.game_windows[win_key] = new_win
                # Respect HEADLESS: never show rebuilt panels when tkinter is disabled.
                from app._overlay_manager import _HEADLESS
                sp = (app._tft_mode or app._arena_mode
                      or app._brawl_mode or app._aram_mode)
                if app.mode == "game" and not sp and not _HEADLESS:
                    new_win.show()
                result_q.put({"ok": True, "detail": f"panel {key} rebuilt"})
            except Exception as exc:
                result_q.put({"ok": False, "error": str(exc)})

        app.root.after(0, _do_rebuild)
        try:
            return result_q.get(timeout=5.0)
        except queue.Empty:
            return {"ok": False, "error": f"rebuild_panel_{key} timeout"}

    # ── Convenience wrappers ──────────────────────────────────────────────────

    def rebuild_panel_game_bottom(self) -> dict:
        return self.rebuild_panel("game_bottom")

    def rebuild_panel_game_rtop(self) -> dict:
        return self.rebuild_panel("game_rtop")

    def rebuild_panel_game_rbot(self) -> dict:
        return self.rebuild_panel("game_rbot")
