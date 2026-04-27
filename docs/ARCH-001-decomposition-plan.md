# ARCH-001: app.py Decomposition Plan
**Author:** Claude Sonnet 4.6 — 2026-04-18
**Status:** PLANNED (not yet executed)
**Priority:** HIGH VALUE — execute when there is a full session available with no active games

---

## Problem

`app.py` is a 1,228-line god class (`OverlayApp`) with 8 distinct concerns mixed together.
Every bug fix, coach addition, and overlay change touches this file. The `_on_game_start`
and `_on_game_end` methods are particularly risky — they contain rating saves, coach
lifecycle, worker resets, and envelope transitions all in one function.

---

## Current concern map (49 methods)

| Concern | Methods | Lines |
|---|---|---|
| Game lifecycle | `_on_game_start`, `_on_game_end`, `_process_game_state`, `_process_worker_result`, `_start_game_poll`, `_drain_game_q`, `_drain_tft_q`, `_game_poll_worker`, `_try_read_api_key` | ~340 |
| Overlay management | `_build_windows`, `_all_windows`, `_apply_mode`, `_switch_mode`, `_switch_to_game_from_tab`, `_get_active_client_tab`, `_attach_preview_overlay`, `_teardown_preview_overlay`, `_close_client_panel`, `_reopen_client_panel`, `_persist_panel_state`, `_update_content` | ~200 |
| State authority | `_init_envelope`, `get_snapshot`, `_update_envelope`, `_apply_auto_fields`, `_calc_win_pct` | ~120 |
| Health monitoring | `_tk_pulse`, `get_health_state` (+ `_ui_pulse_lock`) | ~40 |
| Remediation service | `restart_game_poll`, `_rebuild_panel`, `rebuild_panel_game_bottom`, `rebuild_panel_game_rtop`, `rebuild_panel_game_rbot` | ~80 |
| Data I/O | `_init_data_file`, `_poll_file`, `_write_data`, `_force_refresh`, `_copy_state_to_clipboard`, `_wire_ops_tab`, `_refresh_ops_tab` | ~80 |
| OPS/UX | `_context_menu`, `_toggle_auto` | ~60 |
| Process lifecycle | `__init__` (~180L), `run`, `shutdown`, `_quit`, `_tk_exception` | ~210 |

---

## Proposed decomposition

### Target structure

```
app.py — OverlayApp (thin orchestrator, ~300 lines)
  ├── GameLifecycleManager   app/_game_lifecycle.py   (~340 lines)
  ├── OverlayManager         app/_overlay_manager.py  (~220 lines)
  ├── StateAuthority         app/_state_authority.py  (~140 lines)
  ├── HealthMonitor          app/_health_monitor.py   (~60 lines)
  └── RemediationService     app/_remediation.py      (~100 lines)
```

Data I/O helpers stay in app.py (they're tight to the Tk data file).
OPS/UX (`_context_menu`, `_toggle_auto`) stay in app.py.

---

### Class responsibilities

#### `GameLifecycleManager`
Owns the game start/end transition and worker management.
```python
class GameLifecycleManager:
    def __init__(self, app: "OverlayApp"): ...

    def on_game_start(self, canon_mode: str) -> None
    def on_game_end(self) -> None
    def process_worker_result(self, result: WorkerResult) -> None
    def process_game_state(self, state, is_first=None, canon_mode=None) -> None
    def start_game_poll(self) -> None
    def drain_game_q(self) -> None
    def drain_tft_q(self) -> None
    def try_read_api_key(self) -> str
```

All `self._was_in_game`, `self._none_streak`, `self._tft_coach`, `self._tft_worker`,
`self._sr_aram_worker`, `self._sr_aram_q`, `self._tft_q` move here.

Key constraint: methods that call `self.root.after()` accept `root` as a parameter
or take it from `app.root`. Tk never touched directly from worker threads.

#### `OverlayManager`
Owns window creation, show/hide transitions, mode application, preview overlays.
```python
class OverlayManager:
    def __init__(self, app: "OverlayApp"): ...

    def build_windows(self) -> None
    def apply_mode(self, mode: str) -> None
    def switch_mode(self, mode: str, auto: bool = False) -> None
    def switch_to_game_from_tab(self) -> None
    def attach_preview_overlay(self, canon_mode: str) -> None
    def teardown_preview_overlay(self) -> None
    def close_client_panel(self) -> None
    def reopen_client_panel(self) -> None
    def update_content(self) -> None
    def get_active_client_tab(self) -> str
```

`game_windows`, `client_windows`, `mode_indicator`, `_preview_coach`,
`_client_panel_closed`, `_overlay_visible` all move here.

#### `StateAuthority`
Owns the `GameEnvelope` and all envelope update/read paths.
```python
class StateAuthority:
    def __init__(self): ...

    def init_envelope(self) -> None
    def get_snapshot(self) -> GameEnvelope
    def update_envelope(self, mode: str, payload) -> None
    def apply_auto_fields(self, state: dict) -> None

    @staticmethod
    def calc_win_pct(state: dict) -> float
```

`_current_envelope`, all mode flags (`_tft_mode`, `_aram_mode`, etc.) move here.
`update_envelope` still derives legacy flags for backward compatibility.

#### `HealthMonitor`
Owns the Tk pulse and health state reporting.
```python
class HealthMonitor:
    def __init__(self, app: "OverlayApp"): ...

    def start(self) -> None           # called once after Tk init
    def pulse(self) -> None           # schedules itself via root.after
    def get_health_state(self) -> dict
```

`_ui_pulse_ts`, `_ui_pulse_lock` move here.

#### `RemediationService`
Owns DevRuntime remediation callbacks.
```python
class RemediationService:
    def __init__(self, app: "OverlayApp"): ...

    def restart_game_poll(self) -> dict
    def rebuild_panel(self, key: str) -> dict
    def rebuild_panel_game_bottom(self) -> dict
    def rebuild_panel_game_rtop(self) -> dict
    def rebuild_panel_game_rbot(self) -> dict
```

No state of its own — delegates entirely to GameLifecycleManager and OverlayManager.

---

### Thin `OverlayApp` orchestrator (~300 lines)

After decomposition, `app.py` becomes:
```python
class OverlayApp:
    def __init__(self):
        self.root = tk.Tk()
        ...
        self.state     = StateAuthority()
        self.overlays  = OverlayManager(self)
        self.lifecycle = GameLifecycleManager(self)
        self.health    = HealthMonitor(self)
        self.remediate = RemediationService(self)

        self.overlays.build_windows()
        self.lifecycle.start_game_poll()
        self.health.start()
        ...

    # Kept in OverlayApp (tightly coupled to Tk + data file):
    def _poll_file(self): ...
    def _write_data(self): ...
    def _context_menu(self, event): ...
    def get_health_state(self) -> dict:  # delegates to self.health
        return self.health.get_health_state()
    # DevRuntime callbacks delegate to self.remediate:
    def restart_game_poll(self) -> dict:
        return self.remediate.restart_game_poll()
    ...
    def run(self): self.root.mainloop()
```

---

## Migration strategy (non-breaking)

1. **Create `app/` subdirectory** with `__init__.py`
2. **Extract one class at a time**, starting with the lowest-coupling classes:
   - `RemediationService` first (no state, pure delegation)
   - `HealthMonitor` second (tiny, no dependencies)
   - `StateAuthority` third (owns envelope, no Tk)
   - `OverlayManager` fourth (Tk-heavy but contained)
   - `GameLifecycleManager` last (most complex, most state)
3. **Keep `OverlayApp` as the public API** — all external callers (`main.py`,
   `ops/rc_supervisor.py`, etc.) instantiate `OverlayApp`, not the sub-classes
4. **Test each extraction** with a real ARAM game before moving to the next

## Execution prerequisites

- Minimum 2-hour session with no active games
- Full backup of `app.py` and new `app/` directory
- End-to-end smoke test: client mode → ARAM game start → coaching → game end → rating save
- The `_on_game_end` BUG-1 fix (already applied) is a model for the kind of
  subtle ordering bug this refactor can introduce — proceed with care

## Estimated impact

- `app.py`: 1,228 → ~300 lines (75% reduction)
- Total new `app/` code: ~860 lines (no net gain — same logic, better organised)
- Maintenance benefit: each concern is independently modifiable and testable
