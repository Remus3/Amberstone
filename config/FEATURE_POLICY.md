# FEATURE_POLICY.md
# Amberstone -- Feature Policy Matrix
# Phase 1 Step 7 / Phase 2 Step 2 / Phase 3 Step 1 update

---

## Purpose

`config/feature_flags.json` is the runtime feature policy file.
It is read by `core/feature_policy.py` and cached with automatic hot-reload.
It controls which features are active per game mode.

---

## Hot-Reload Behavior (Phase 2 Step 2 -- actual implementation)

`feature_policy.py` uses a `_PolicyCache` object that performs a lazy pull
hot-reload on each gate call:

- **mtime check**: every call to `is_allowed()` or `get_policy_state()` performs
  a cheap `os.stat()` call to compare the current file mtime to the cached mtime.
  If unchanged, no I/O occurs.

- **Valid reload**: if the file has changed and parses successfully with valid
  decision values, the new policy replaces the active effective policy. The
  previous policy becomes the new last-known-good.

- **Invalid / malformed reload**: if the file changed but contains invalid JSON,
  a non-dict top-level value, or an unrecognised decision value (not `"allow"` or
  `"disabled"`), the reload is rejected. The last-known-good policy remains active.
  A warning is recorded and surfaced through the OPS tab.

- **File disappears after valid load**: if `feature_flags.json` is deleted or
  temporarily unavailable after a valid load, the last-known-good policy remains
  active. The policy source status changes to `"last_known_good"`.

- **Startup with no file**: all decisions default to `"allow"`.
  Policy source status is `"missing"`.

**Propagation time**: changes take effect within one gate call:
  - During gameplay: within ~1.5s (worker poll interval).
  - In idle/client mode: within ~5s (MetricsCache refresh interval calls
    `get_policy_state()` which also triggers the mtime check).

---

## Policy Source Status Values

| status | meaning |
|---|---|
| `loaded` | File parsed and validated successfully |
| `default` | No file; all-allow defaults (startup before first file seen) |
| `missing` | File was never present at startup |
| `last_known_good` | File disappeared after a valid load; prior policy retained |
| `invalid_reload_retained` | File changed but was invalid; prior policy retained |

These values are surfaced in MetricsCache -> OPS tab FEATURE POLICY section.

---

## Warning Behavior

Warnings are **last-one-wins** (a single string field, not a history list).
Cleared to None after a valid reload.
Surfaced via `get_policy_state()["policy_last_warning"]` and the OPS tab warning line.

---

## OPS Visibility

Policy state is **not** read directly from `feature_flags.json` by the UI.
The data flow is:

  feature_flags.json
    -> core/feature_policy._PolicyCache (hot-reload, owns matrix)
      -> feature_policy.get_policy_state() (read-only snapshot)
        -> MetricsCache._read_policy_state() (every 5s refresh)
          -> MetricsSummary.policy_* fields
            -> ui/client_panel.py FEATURE POLICY section (read-only display)

---

## Matrix Shape

```json
{
  "sr":    { "live_coaching": "allow" | "disabled" },
  "aram":  { "live_coaching": "allow" | "disabled" },
  "arena": { "live_coaching": "allow" | "disabled" },
  "brawl": { "live_coaching": "allow" | "disabled" },
  "tft":   {
    "live_coaching":       "allow" | "disabled",
    "tft_vision_analysis": "allow" | "disabled"
  }
}
```

Keys are lowercase mode names. Decision values are strings, not booleans.

---

## Supported Modes

| mode key | game modes covered |
|---|---|
| sr | CLASSIC, RANKED (Summoner's Rift) |
| aram | ARAM, ARAM_UNRANKED_5X5 |
| arena | CHERRY (Arena) |
| brawl | NEXUSBLITZ, URF, ARURF, and other brawl variants |
| tft | TFT (Teamfight Tactics) |

---

## Supported Features

### live_coaching (all modes)

Controls whether Claude AI coaching calls are submitted during gameplay.

| decision | runtime effect |
|---|---|
| allow | coaching submissions proceed normally |
| disabled | coaching submissions are suppressed; a neutral placeholder is written to coaching artifact files so overlays show no stale advice |

When disabled:
- SR: SrAramWorker._submit_coaching() is skipped
- ARAM: coaches.aram_coach._run_coach() is not started (startup gate);
          coaches.aram_coach._run_coach() skips inference (per-poll gate, Phase 4 Step 2);
          coaches.aram_coach._run_vision() returns before any screenshot call (Phase 4 Step 2.1)
- Arena: arena_coach._run_coach() skips inference (per-poll gate);
          arena_coach._run_vision() returns before any screenshot call (Phase 3 Step 1)
- Brawl: brawl_coach._run_coach() skips inference (per-poll gate);
          brawl_coach._run_vision() returns before any screenshot call (Phase 3 Step 1)
- TFT: TftWorker skips engine.submit() (per-poll gate)

State capture and GameEnvelope authority are unaffected by this policy.
Workers continue to run for state tracking even when coaching is disabled.

### tft_vision_analysis (TFT only)

Controls whether TftLiveAnalysis vision scans run during TFT gameplay.

| decision | runtime effect |
|---|---|
| allow | TftLiveAnalysis runs normally; vision scans update tft_live_data.json |
| disabled | TftLiveAnalysis is not started; tft_live_data.json cleared to neutral |

TFT runtime state authority (TftSnapshot, GameEnvelope) is unaffected.
TftStateReader continues to poll the Riot API for non-vision TFT state.

---

## Default Behavior

The default `feature_flags.json` sets all decisions to "allow".
This preserves current runtime behavior identically.
No existing feature is disabled by default.

---

## Fallback and Warning Behavior

Policy gating never crashes startup.

**Before any valid policy file has ever been loaded (startup conditions):**

| condition | fallback | status |
|---|---|---|
| File missing at startup | all-allow defaults | `missing` |
| JSON parse error at startup | all-allow defaults | `missing` |
| Unknown mode key (no prior valid load) | safe default `"allow"` | `missing` |
| Unknown feature key (no prior valid load) | safe default `"allow"` | `missing` |

**After a valid policy file has been loaded at least once (runtime conditions):**

| condition | fallback | status |
|---|---|---|
| Invalid reload (bad JSON, wrong type) | retain last-known-good | `invalid_reload_retained` |
| Malformed decision value | retain last-known-good | `invalid_reload_retained` |
| Unknown mode/feature key | safe default `"allow"` (additive) | `loaded` |
| File disappears after valid load | retain last-known-good | `last_known_good` |

Warnings are **last-one-wins**. Cleared to None after a valid reload.
Surfaced via `get_policy_state()["policy_last_warning"]` and the OPS tab warning line.
