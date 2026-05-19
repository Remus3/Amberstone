# arch: mode switching (no UI overlays - legacy name) | section=orchestration | frozen=yes
"""
app/_overlay_manager.py - OverlayManager (post-T2 #6 dashboard-only)

The web dashboard at :8888 is the UI. Tkinter overlay windows are gone.
This module survives only because lifecycle code still calls
`overlays.switch_mode(...)` and `overlays.update_content()` to persist
mode transitions into `coaching_data.json` (which the dashboard reads).

Kept as a class (rather than free functions) so OverlayApp's existing
`self.overlays.X` call sites stay valid.

Removed in T2 #6: build_windows window creation, apply_mode show/hide,
attach_preview/teardown_preview, close_panel/reopen_panel/persist_panel_state,
get_active_tab/switch_to_game_from_tab, update_content window-push.
"""
import logging

_log = logging.getLogger("rc.app.overlays")


class OverlayManager:
    """No-op overlay shell. Owns mode persistence into coaching_data.json."""

    def __init__(self, app: "OverlayApp") -> None:  # type: ignore[name-defined]
        self.app = app

    def build_windows(self) -> None:
        """Initialize empty window dicts so downstream `.get()` calls don't crash."""
        app = self.app
        app.game_windows = {}
        app.client_windows = {}
        app.mode_indicator = None
        _log.info("OverlayManager: dashboard-only - no tk overlay windows created")

    def all_windows(self):
        return iter(())

    def switch_mode(self, mode: str, auto: bool = False) -> None:
        """Persist mode into data file so the dashboard sees the transition."""
        app = self.app
        app.mode = mode
        app._auto_mode = auto if auto else app._auto_mode
        app.data["mode"] = mode
        app._write_data()

    def apply_mode(self, mode: str) -> None:
        """No-op. Kept for the single call from OverlayApp.__init__ tail."""
        return

    def update_content(self) -> None:
        """No-op. Kept because lifecycle._apply_auto_fields still calls it."""
        return
