# CONFIG_AUTHORITY.md
# Amberstone - Config File Authority and Domain Ownership
# Phase 1 Step 1 - documentation only, no behavior changes.

---

## Config Hierarchy (highest to lowest authority)

```
ops/rc_config.json
    │  Runtime ops stack: supervisor, file bridge, DevRuntime.
    │  Single source of truth for process lifecycle settings.
    │
    ├── config/self_monitor_profile.json
    │       Self-monitor behaviour, remediation ladder, hot-reload allowlist.
    │       Read by rc_supervisor.py (FROZEN) and rc_self_monitor.py (FROZEN).
    │
    ├── config/coach_settings.json
    │       AI coaching settings: model, debounce, timeout, TFT PBE toggle.
    │       Read by coach_integration.py and coaches/__init__.py.
    │
    └── config/feature_flags.json  [Phase 1 Step 7]
            Per-mode feature policy matrix.
            Read ONLY by: core/feature_policy.py (non-frozen).
            Consumed at: sr_aram_worker._submit_coaching(), tft_worker._run(),
              tft_worker._init_components(), app._on_game_start().
```

---

## File Domain Ownership

### ops/rc_config.json - Runtime Ops Authority

Owns:
- `project_root`, `runtime_dir`, `python_exe`, `app_cmd`, `health_file`
- `admin_bridge_enabled` (security gate for shell/process commands)
- `max_heartbeat_age_seconds` (supervisor heartbeat window)
- `poll_interval_seconds` (supervisor main loop tick)
- `max_restart_attempts`, `restart_window_seconds`, `restart_cooldown_seconds`
  (supervisor circuit-breaker limits)
- `bridge_poll_interval_seconds` (file bridge polling)
- `image_retention_days`, `control_file_retention_hours`, `backup_retention_count`
  (retention/cleanup)

Does NOT own: coaching behaviour, hot-reload policy, feature flags.

### config/self_monitor_profile.json - Monitor Behaviour Authority

Owns:
- `enabled`, `resume_on_boot` (whether SelfMonitor is armed at startup)
- `auto_retry`, `safe_live_patch_only` (remediation behaviour)
- `remediation_ladder` (escalation step sequence)
- `allowed_hot_reload_modules`, `allowed_panel_rebuild_keys` (safe-reload lists)
- `max_hot_reload_attempts`, `incident_log_retention_days`
- `screen_validation_enabled`, `screen_validation_interval_s`

Phase 0 FROZEN readers: `ops/rc_supervisor.py`, `ops/rc_self_monitor.py`.
Phase 1 must NOT add new keys that those frozen files read.
Any new Phase 1 keys in this file may only be read by non-frozen code.

Note on `max_restart_attempts`: this key also exists in `ops/rc_config.json`.
They are read by different subsystems independently:
- ops/rc_config.json value -> supervisor circuit breaker
- self_monitor_profile.json value -> SelfMonitor circuit breaker
They may legitimately differ. Both values are documented here for audit purposes.

### config/coach_settings.json - AI Coaching Authority

Owns:
- `model` (Anthropic model string for Claude API calls)
- `debounce_seconds` (minimum interval between coaching calls)
- `timeout` (Claude API call timeout in seconds)
- `max_tokens` (max response tokens per coaching call)
- `tft_pbe` (route TFT sessions to PBE coach when true)

Read by: `coach_integration.py`, `coaches/__init__.py`.
Does NOT affect the control plane, supervisor, or self-monitor.

### config/feature_flags.json - Feature Policy Authority [Phase 1 Step 7]

Owns:
- Per-mode feature enable/disable matrix (modes: sr, aram, arena, brawl, tft)
- Per-feature decisions: "allow" | "disabled"
- Supported features: live_coaching (all modes), tft_vision_analysis (tft only)

Read ONLY by: `core/feature_policy.py` (non-frozen).

Runtime consumers via feature_policy.is_allowed() - final gate locations:

  SR live_coaching:
    `core/sr_aram_worker._submit_coaching()` - per-poll gate

  ARAM live_coaching:
    `app._on_game_start()` - startup gate
    `coaches/aram_coach._run_coach()` - per-poll gate (Phase 4 Step 2)
    `coaches/aram_coach._run_vision()` - per-poll vision gate (Phase 4 Step 2.1)

  Arena live_coaching:
    `app._on_game_start()` - startup gate
    `coaches/arena_coach._run_coach()` - per-poll gate (Phase 2)
    `coaches/arena_coach._run_vision()` - per-poll vision gate (Phase 3 Step 1)

  Brawl live_coaching:
    `app._on_game_start()` - startup gate
    `coaches/brawl_coach._run_coach()` - per-poll gate (Phase 2)
    `coaches/brawl_coach._run_vision()` - per-poll vision gate (Phase 3 Step 1)

  TFT live_coaching:
    `core/tft_worker._run()` - per-poll gate

  TFT tft_vision_analysis:
    `core/tft_worker._init_components()` - startup gate

Artifact paths affected by policy-disabled output:
- sr.live_coaching disabled -> `coaching_data.json` (project root)
- aram.live_coaching disabled -> `data/aram_coaching_data.json`
- arena.live_coaching disabled -> `data/arena_coaching_data.json`
- brawl.live_coaching disabled -> `data/brawl_coaching_data.json`
- tft.live_coaching disabled -> `data/tft_coaching_data.json` ONLY
- tft.tft_vision_analysis disabled -> `data/tft_live_data.json` ONLY

No remaining gate debt: all modes have full per-poll live_coaching gate coverage.
(ARAM and Arena/Brawl per-poll gates closed in Phase 4 Steps 2/2.1.)

---

## Frozen vs Non-Frozen Readers

| config file | frozen readers | non-frozen readers |
|---|---|---|
| ops/rc_config.json | rc_supervisor.py (FROZEN) | main.py (DevRuntime init), ops/rc_transactional_deploy.py |
| self_monitor_profile.json | rc_supervisor.py (FROZEN), rc_self_monitor.py (FROZEN) | - |
| coach_settings.json | - | coach_integration.py, coaches/__init__.py |
| feature_flags.json | - | core/feature_policy.py (Step 7) |

---

## Constants That Must Agree

The following constant pairs are documented as needing to agree.
In Phase 1 Step 1, disagreements are NOT automatically detected -- this table
exists for audit and manual review purposes only. Auto-checking these pairs
would require reading from frozen files (rc_supervisor.py, rc_self_monitor.py),
which is not permitted in Phase 1.

| constant A | location A | constant B | location B | relationship |
|---|---|---|---|---|
| `max_heartbeat_age_seconds` (default 15) | ops/rc_config.json | `max_heartbeat_age` (default 15.0) | rc_supervisor.py (reads from config) | must match; supervisor reads from rc_config.json directly - no separate agreement needed |
| `startup_heartbeat_timeout_s` (default 30) | rc_supervisor.py (reads from rc_config.json) | `_startup_grace_s` (hardcoded 30.0) | rc_self_monitor.py | must match; _startup_grace_s is frozen hardcoded; rc_config.json value drives supervisor only |
| `_BOOTSTRAP_GRACE_S` (hardcoded 60.0) | rc_self_monitor.py | no config key exists | - | bootstrap grace is 2x startup grace by design; document only |
| `max_restart_attempts` | ops/rc_config.json | `max_restart_attempts` | self_monitor_profile.json | different subsystems; may intentionally differ; document disagreements |

---

## Files That Are Read-Only from Phase 0's Perspective

These files MUST NOT be modified in Phase 1 or any subsequent phase without an
explicit approved exception:

- `ops/rc_supervisor.py`
- `ops/rc_self_monitor.py`
- `ops/rc_incident_log.py`
- `ops/rc_league_watcher.ps1`
- `ops/run_self_healing_watchdog.ps1`

Their config-reading behavior is frozen. Adding new config keys that these files
read constitutes a behavior change and is not permitted.

---

## Install-Time vs Runtime

- `config/runtime.json` - install-time only; NOT read by the runtime ops stack.
  Written by install.bat; contains install paths for LCU integration. Ignored
  after installation is complete.
- `config/settings.json` - REMOVED 2026-07-09 (dead-config sweep). It had NO
  runtime reader anywhere: keys memory_warn_mb / memory_limit_mb /
  memory_watchdog_interval_s / game_poll_ms / data_poll_ms were never read, and
  the file was not in config_validator.validate_all(). The watchdog and poll
  loops use hardcoded defaults.
