"""
app/_remediation.py — RemediationService (post-T2 #6 dashboard-only)

DevRuntime callbacks. restart_game_poll restarts the SrAramWorker.
rebuild_panel_* are kept as no-ops because main.py (frozen) registers them
with DevRuntime; the panels they used to rebuild no longer exist.
"""

import queue
import threading


class RemediationService:
    """
    Owns:
      restart_game_poll()             — restart SrAramWorker safely
      rebuild_panel(key)              — no-op (panels removed in T2 #6)
      rebuild_panel_game_{bottom,rtop,rbot}() — no-op wrappers

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

    # ── Rebuild panel (no-op since T2 #6) ─────────────────────────────────────

    def rebuild_panel(self, key: str) -> dict:
        return {"ok": True, "detail": f"rebuild_panel({key!r}) no-op (T2 #6: dashboard-only)"}

    def rebuild_panel_game_bottom(self) -> dict:
        return self.rebuild_panel("game_bottom")

    def rebuild_panel_game_rtop(self) -> dict:
        return self.rebuild_panel("game_rtop")

    def rebuild_panel_game_rbot(self) -> dict:
        return self.rebuild_panel("game_rbot")
