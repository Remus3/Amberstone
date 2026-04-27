"""
app/_overlay_manager.py — OverlayManager extracted from app/__init__.py (ARCH-001 Phase 3)

Owns all overlay window creation, mode switching, panel visibility, preview overlays,
and data refresh.  No game logic — pure Tk/window concern.

State owned here (set on app, read by OverlayManager through app reference):
  app.game_windows    — dict of SR game overlay windows
  app.client_windows  — dict of client panel windows
  app.mode_indicator  — ModeIndicator window
  app._preview_coach  — active preview coach (stub, no worker)

OverlayApp delegates:
  _build_windows()          → self.overlays.build_windows()
  _all_windows()            → self.overlays.all_windows()
  _get_active_client_tab()  → self.overlays.get_active_tab()
  _switch_to_game_from_tab()→ self.overlays.switch_to_game_from_tab()
  _attach_preview_overlay() → self.overlays.attach_preview(canon_mode)
  _teardown_preview_overlay()→ self.overlays.teardown_preview()
  _close_client_panel()     → self.overlays.close_panel()
  _reopen_client_panel()    → self.overlays.reopen_panel()
  _persist_panel_state()    → self.overlays.persist_panel_state(closed)
  _switch_mode()            → self.overlays.switch_mode(mode, auto)
  _apply_mode()             → self.overlays.apply_mode(mode)
  _update_content()         → self.overlays.update_content()
"""
import logging
from pathlib import Path

_log = logging.getLogger("rc.app.overlays")

# Headless mode: web dashboard at :8888 replaces all tkinter overlays.
# Windows are still created (so downstream `client_windows.get('main')` etc
# don't NoneType-crash) but immediately hidden and never shown.
# Set to False to restore the legacy on-screen overlays.
_HEADLESS = True


class OverlayManager:
    """
    Owns Tk overlay window lifecycle and mode visibility.
    All methods run on the Tk main thread.
    """

    def __init__(self, app: "OverlayApp") -> None:  # type: ignore[name-defined]
        self.app = app

    # ── Window creation ───────────────────────────────────────────────────────

    def build_windows(self) -> None:
        """Create all overlay windows and set them on the app instance."""
        from ui import GameBottomStrip, GameRightTop, GameRightBot, ClientPanel, ModeIndicator
        app = self.app
        try:
            app.game_windows = {
                "bottom": GameBottomStrip(app.root),
                "rtop":   GameRightTop(app.root),
                "rbot":   GameRightBot(app.root),
            }
            app.client_windows = {"main": ClientPanel(app.root)}
            app.mode_indicator = ModeIndicator(app.root)
            for win in self.all_windows():
                win.attach_menu(app._context_menu)
            if _HEADLESS:
                for win in self.all_windows():
                    # AUDIT P-rc-frozen-overlay-mgr-swallow (2026-04-22):
                    # log-at-debug so stale window state is traceable.
                    try: win.hide()
                    except Exception as _exc:
                        _log.debug("headless hide failed for %s: %s", win, _exc)
                _log.info("OverlayManager: HEADLESS — windows created, all hidden (dashboard at :8888 is the UI)")
        except Exception:
            import traceback
            _log.error("build_windows CRASH:\n%s", traceback.format_exc())

    def all_windows(self):
        """Yield all overlay windows in a consistent order."""
        app = self.app
        yield from app.game_windows.values()
        yield from app.client_windows.values()
        yield app.mode_indicator

    # ── Tab and mode switching ────────────────────────────────────────────────

    def get_active_tab(self) -> str:
        """Return the currently active ClientPanel tab name, or 'SR' if unavailable."""
        try:
            panel = self.app.client_windows.get("main")
            if panel is not None and hasattr(panel, "_active_tab"):
                return panel._active_tab or "SR"
        except Exception:
            pass
        return "SR"

    def switch_to_game_from_tab(self) -> None:
        """Switch to game mode using the currently active ClientPanel tab."""
        from core.game_snapshot import MODE_SR
        app = self.app
        tab   = self.get_active_tab()
        canon = app._TAB_TO_MODE.get(tab, MODE_SR)
        if canon != MODE_SR:
            app._update_envelope(canon, None)
        self.switch_mode("game", auto=False)
        if canon != MODE_SR:
            app.root.after(100, lambda: self.attach_preview(canon))
        _log.info("Manual game mode switch: tab=%s canon=%s", tab, canon)

    def switch_mode(self, mode: str, auto: bool = False) -> None:
        """Switch overlay layout mode ('client' or 'game') and persist to data file."""
        from core.game_snapshot import MODE_CLIENT
        app = self.app
        app.mode       = mode
        app._auto_mode = auto if auto else app._auto_mode
        app.data["mode"] = mode
        app._write_data()
        if mode == "client":
            self.teardown_preview()
            if not app._was_in_game:
                try: app._update_envelope(MODE_CLIENT, None)
                except Exception: pass
        self.apply_mode(mode)
        app.mode_indicator.set_mode(mode, auto=auto)

    def apply_mode(self, mode: str) -> None:
        """Show/hide game vs client windows based on current mode and game flags."""
        app = self.app
        if _HEADLESS:
            try:
                app.mode_indicator.set_mode(mode, auto=app._auto_mode)
            except Exception:
                pass
            self.update_content()
            return
        # AUDIT P-rc-frozen-overlay-mgr-swallow (2026-04-22): route the
        # 6 hide/show toggles through _log.debug so a broken window is
        # at least traceable.
        if mode == "game":
            for w in app.client_windows.values():
                try: w.hide()
                except Exception as _exc:
                    _log.debug("client.hide in apply_mode(game) failed: %s", _exc)
            sp = app._tft_mode or app._arena_mode or app._brawl_mode or app._aram_mode
            for w in app.game_windows.values():
                try: w.hide() if sp else w.show()
                except Exception as _exc:
                    _log.debug("game.%s in apply_mode(game) failed: %s",
                               "hide" if sp else "show", _exc)
            app._overlay_visible = not sp
        else:
            for w in app.game_windows.values():
                try: w.hide()
                except Exception as _exc:
                    _log.debug("game.hide in apply_mode(client) failed: %s", _exc)
            if not getattr(app, "_client_panel_closed", False):
                for w in app.client_windows.values():
                    try: w.show()
                    except Exception as _exc:
                        _log.debug("client.show in apply_mode(client) failed: %s", _exc)
            app._overlay_visible = False
        try:
            app.mode_indicator.set_mode(mode, auto=app._auto_mode)
            app.mode_indicator.show()
        except Exception:
            pass
        self.update_content()

    # ── Preview overlays ──────────────────────────────────────────────────────

    def attach_preview(self, canon_mode: str) -> None:
        """
        Attach a stub coach overlay for the given mode.
        No worker started — panels show empty state for layout positioning.
        """
        from core.game_snapshot import MODE_ARAM, MODE_ARENA, MODE_BRAWL, MODE_TFT
        app = self.app
        self.teardown_preview()
        _coach_map = {
            MODE_ARAM:  ("coaches.aram_coach",  "aram_coaching_data.json"),
            MODE_ARENA: ("coaches.arena_coach", "arena_coaching_data.json"),
            MODE_BRAWL: ("coaches.brawl_coach", "brawl_coaching_data.json"),
            MODE_TFT:   ("coaches.tft_coach",   "tft_coaching_data.json"),
        }
        entry = _coach_map.get(canon_mode)
        if not entry:
            return
        mod_path, data_fname = entry
        try:
            import importlib as _il
            mod   = _il.import_module(mod_path)
            coach = mod.Coach(Path(__file__).parent.parent / "data" / data_fname)
            coach.attach_overlay(app.root)
            if hasattr(coach, "_overlay") and isinstance(coach._overlay, dict):
                for win in coach._overlay.values():
                    try:
                        if _HEADLESS:
                            if hasattr(win, "hide"):       win.hide()
                            elif hasattr(win, "withdraw"): win.withdraw()
                        else:
                            if hasattr(win, "show"):        win.show()
                            elif hasattr(win, "deiconify"): win.deiconify()
                    except Exception:
                        pass
            app._preview_coach = coach
            _log.info("Preview overlay attached for mode %s%s", canon_mode,
                      " (HEADLESS — hidden)" if _HEADLESS else "")
        except Exception:
            import traceback
            _log.error("attach_preview(%s):\n%s", canon_mode, traceback.format_exc())

    def teardown_preview(self) -> None:
        """Shut down and discard any active preview coach + windows."""
        app = self.app
        coach = getattr(app, "_preview_coach", None)
        if coach is not None:
            try:
                coach.shutdown()
            except Exception:
                pass
            app._preview_coach = None

    # ── Client panel show/hide ────────────────────────────────────────────────

    def close_panel(self) -> None:
        """Hide the client panel and persist the closed state."""
        app = self.app
        app._client_panel_closed = True
        self.persist_panel_state(True)
        for w in app.client_windows.values():
            try: w.hide()
            except Exception as _exc:
                _log.debug("close_panel hide failed: %s", _exc)

    def reopen_panel(self) -> None:
        """Show the client panel and persist the open state."""
        app = self.app
        app._client_panel_closed = False
        self.persist_panel_state(False)
        for w in app.client_windows.values():
            try: w.show()
            except Exception as _exc:
                _log.debug("reopen_panel show failed: %s", _exc)

    def persist_panel_state(self, closed: bool) -> None:
        """Write client_panel_closed to data/comp_state.json atomically."""
        try:
            import json as _j
            _f = Path(__file__).parent.parent / "data" / "comp_state.json"
            _d = _j.loads(_f.read_text(encoding="utf-8")) if _f.exists() else {}
            _d["client_panel_closed"] = closed
            _tmp = _f.with_suffix(".json.tmp")
            _tmp.write_text(_j.dumps(_d, indent=2), encoding="utf-8")
            _tmp.replace(_f)
        except Exception:
            pass

    # ── Data refresh ──────────────────────────────────────────────────────────

    def update_content(self) -> None:
        """Push current data dict to all visible overlay windows."""
        app = self.app
        if app.mode == "game":
            if app._tft_mode:
                return
            for k, w in app.game_windows.items():
                try:
                    w.update_data(app.data)
                except Exception:
                    _log.error("update crash: game/%s", k)
        else:
            for k, w in app.client_windows.items():
                try:
                    w.update_data(app.data)
                except Exception:
                    _log.error("update crash: client/%s", k)
