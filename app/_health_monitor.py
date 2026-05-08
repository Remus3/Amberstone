# arch: Tk pulse + health state reporting | section=orchestration | frozen=yes
"""
app/_health_monitor.py — HealthMonitor extracted from app.py (ARCH-001)

Owns the UI pulse heartbeat and health-state reporting. Extracted so
OverlayApp's health concern is independently readable. Post-T2 #8 the
heartbeat re-arms via `app.scheduler.schedule(...)` instead of
`root.after(...)` — the loop name "ui_pulse" stuck since pre-headless.

State transferred from OverlayApp:
  _ui_pulse_lock  → self._lock
  _ui_pulse_ts    → self._ts
"""

import threading
import time


class HealthMonitor:
    """
    Owns the UI pulse loop and get_health_state() snapshot.

    Usage::
        self.health = HealthMonitor(self)
        # after the scheduler is ready:
        self.health.start()

    OverlayApp delegates:
        get_health_state()  → self.health.get_health_state()
    """

    def __init__(self, app: "OverlayApp") -> None:  # type: ignore[name-defined]
        self.app   = app
        self._lock = threading.Lock()
        self._ts   = time.monotonic()

    # ── Public lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        """Kick off the pulse loop. Call once after the scheduler is ready."""
        self.app.scheduler.schedule(1000, self.pulse)

    def pulse(self) -> None:
        """Re-armed every 2s by the asyncio scheduler. Proves the loop is alive."""
        with self._lock:
            self._ts = time.monotonic()
        self.app.scheduler.schedule(2000, self.pulse)

    def get_health_state(self) -> dict:
        """
        Thread-safe health snapshot consumed by DevRuntime state provider.
        Reads worker liveness timestamps without holding any Tk locks.
        """
        app = self.app
        now = time.monotonic()

        with self._lock:
            ui_age = now - self._ts

        # Worker liveness — prefer SrAramWorker; fall back to legacy timestamps
        if app._sr_aram_worker is not None:
            w_pulse = app._sr_aram_worker.pulse_ts
            w_last  = app._sr_aram_worker.last_success_ts
        else:
            w_pulse = getattr(app, "_poll_worker_pulse_ts",       0.0)
            w_last  = getattr(app, "_poll_worker_last_success_ts", 0.0)

        worker_age = (now - w_pulse) if w_pulse else 999.0

        return {
            "mode":                       app.mode,
            "tft_mode":                   app._tft_mode,
            "aram_mode":                  app._aram_mode,
            "arena_mode":                 app._arena_mode,
            "has_game":                   app._was_in_game,
            # Subsystem health
            "ui_loop_alive":              ui_age < 6.0,       # 3× 2s pulse interval
            "ui_pulse_age_s":             round(ui_age, 1),
            "game_poll_worker_alive":     worker_age < 12.0,  # 4× 3s max backoff
            "game_poll_worker_age_s":     (round(worker_age, 1) if w_pulse else None),
            "game_poll_last_success_at":  (w_last or None),
            "overlay_visible":            app._overlay_visible,
        }
