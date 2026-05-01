# Wakeup Notes — 2026-05-01 (session 22 hand-off)

> Hand-off from session that shipped **Tier 2 #3** (writers extraction).
> `dashboard/_writers.py` now owns `atomic_write_json` + `set_pregame` +
> `force_vision_scan`. `web_dashboard.py` is down to **590 lines**.
> Next focus: Tier 2 #4 — pull `_lcu_summary` + `_liveclient_summary`
> into `dashboard/_liveclient.py` (and decide what to do with
> `item_advisor`).

---

## What just shipped

| Commit | Summary |
|---|---|
| 3e20b11 | **Tier 2 #3**: writers extracted to `dashboard/_writers.py`. The three atomic-JSON helpers (`atomic_write_json`, `set_pregame`, `force_vision_scan`) move out of `web_dashboard.py`. `routes_state.py` switched from the lazy `from web_dashboard import …` inside request handlers (added in slice 2C-7a to dodge the import cycle) to a module-scope `from dashboard._writers import …`. `web_dashboard.py` retains underscored re-exports (`_atomic_write_json` / `_set_pregame` / `_force_vision_scan`) for any external caller. CLAUDE.md atomic-write contract preserved (tmp.write + replace); `set_pregame` still holds `core.coaching_data_lock` for its R-M-W on root `coaching_data.json` (NOTE-003). web_dashboard.py: 606 → 590 (−16). dashboard/_writers.py: 50 (new). Smoke-tested: re-exports identity-equal, force_vision_scan writes a float `force` key, atomic_write_json roundtrips, dashboard.routes_state importable in a fresh process without web_dashboard. |
| 8defac7 | Tier 2 #2: diagnostics cache → `dashboard/_diagnostics.py`. 621 → 606 (−15). |
| 4317d15 | Tier 2 #1: bridge log → `dashboard/_bridge_log.py`. 741 → 621 (−120). |

**Cumulative since slice 2B start: 2612 → 590 in `web_dashboard.py` (−2022 lines).**

## State at hand-off

- **32 unpushed commits** on `main` (was 31 + this refactor).
  Origin push still pending — user's call before the 2026-05-10 cloud routine.
- **RC still NOT restarted.** Eighteen+ queued changes (#3 log-retention,
  #4 queue-compaction, slices 1–2D + Tier 2 #1 + #2 + #3) all activate
  together at next restart. None is user-visible — all internal refactor.
- Restart timing is user's call. `echo restart > restart_trigger.txt`;
  verify via `ops/runtime/health.json`.
- Game-PC bridge still dead (last gamepc result 69073s ago at session
  start). Liveclient relay snapshots still stale. Bridge SessionStart
  anomaly carried over from session 18; Game-PC Claude was instructed
  in session 20 to start `gamepc_mcp_server.py` and restart
  `/loop /process-bridge-tasks`.
- `RC-PatchRefresh` still showing residual `last_result=2147942402` —
  fixed at script level in `project_rc_patchrefresh_fixed`; clears on
  next scheduled run.
- Untracked / unstaged that this commit deliberately left alone:
  `config/coach_settings.json` (`disabled_coaches: []` field added —
  unrelated runtime config drift), `tools/claude-rc.ps1` (untracked).

## Inventory of `web_dashboard.py` (590 lines)

Re-run `grep -n "def \|class " web_dashboard.py` at session start to
refresh; table is approximate.

| Lines | Section |
|---|---|
| 1–67 | imports, constants, `_VISION_TOKEN`, `_APP_DIR`, dashboard package re-imports + slice-2D re-export |
| ~70–~167 | `_champ_select_brief_via_coach` (Haiku build/runes/ally-notes) |
| 169–183 | bridge_log re-export shim (Tier 2 #1) |
| ~185–~205 | diagnostics re-export shim (Tier 2 #2) |
| ~207–~217 | writers re-export shim (Tier 2 #3) |
| ~220–~230 | `_MODE_TO_FILE` |
| ~233–~336 | `_lcu_summary`, `_liveclient_summary` |
| ~340–~415 | `_build_state`, `_sim_states`, `_SUPERVISOR_PROXY_PATHS` |
| ~420–~585 | `_Handler` — `do_GET`, `do_POST`, `_csrf_ok`, `_send`, `_proxy_to_supervisor` |
| 586–end | slice-2D server re-export shim |

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:

1. All items 1–21 from prior sessions + items 1–3 from session 15
   + bridge round-trip + decisions POST 404 from session 16 +
   replay-coach / speak / champ-select-coach / coach/toggle from
   session 17 + slice 2C-7d /api/analyze + experimental + loadout +
   lcu-cmd allowlist negative test (session 18) + slice 2D dashboard
   TLS / 301 / `_APP_DIR` propagation (session 19) + bridge GET/POST
   round-trip (session 20) + /api/diagnostics first/cached call
   (session 21) — all unchanged.

2. **NEW (Tier 2 #3): /api/input + /api/command still work:**
   ```
   # set pregame text
   curl -k -X POST 'https://127.0.0.1:8888/api/input' \
       -H 'Content-Type: application/json' -d '{"text":"smoke test"}'
   # force vision scan
   curl -k -X POST 'https://127.0.0.1:8888/api/command' \
       -H 'Content-Type: application/json' -d '{"command":"force_vision"}'
   # touch refresh
   curl -k -X POST 'https://127.0.0.1:8888/api/command' \
       -H 'Content-Type: application/json' -d '{"command":"refresh"}'
   # clear pregame
   curl -k -X POST 'https://127.0.0.1:8888/api/command' \
       -H 'Content-Type: application/json' -d '{"command":"clear_pregame"}'
   ```
   All four should return `{"ok":true}`. Confirm side-effects:
   - `coaching_data.json` `pregame` field flips between "smoke test"
     and "" (cat / Read after each call).
   - `data/force_scan.json` `force` value updates each force_vision call.

3. Re-export sanity:
   ```
   py -c "import web_dashboard, dashboard._writers as w; \
     print(web_dashboard._set_pregame is w.set_pregame, \
           web_dashboard._atomic_write_json is w.atomic_write_json, \
           web_dashboard._force_vision_scan is w.force_vision_scan)"
   ```
   should print `True True True`. If False, the re-export shim regressed.

If either of those fail, the most likely cause is the
`core.coaching_data_lock` import inside `dashboard/_writers.set_pregame`
blowing up at first call (it's lazy — module load is clean). Hard
fallback: revert this commit; commit 8defac7 (Tier 2 #2) was the
last green build with the writers inside `web_dashboard.py`.

## Tier 2 progress

- ✅ **#1 — bridge_log → `dashboard/_bridge_log.py`** (4317d15)
- ✅ **#2 — diagnostics cache → `dashboard/_diagnostics.py`** (8defac7)
- ✅ **#3 — writers → `dashboard/_writers.py`** (this session)
- ⏳ **#4 — `_lcu_summary` + `_liveclient_summary` → `dashboard/_liveclient.py`**.
  Next up. ~120 LOC. Both currently sit in `web_dashboard.py`
  (~lines 233–336). Considerations:
  - `_liveclient_summary` embeds an `item_advisor` import (`resolve_build`,
    `boots_phase`, `endgame_boots_swap_target`, `is_redundant`) that
    lives at project root. In the new module, prefer a top-level
    `from item_advisor import …` over the current sys.path-mangling
    pattern (lines ~309–314). Module load doesn't run that code — it
    only fires when a real liveclient frame is fetched — so the import
    should be safe to hoist. If `item_advisor` has expensive side
    effects on import, defer to a function-local import.
  - Both helpers rely on `_VISION_TOKEN` from `web_dashboard.py`, which
    is wired through `core.vision_token.get_vision_token`. Easiest: have
    `_liveclient.py` import the same way (`from core.vision_token
    import get_vision_token`) instead of going through web_dashboard.
  - `_build_state` calls both functions — leave it in `web_dashboard.py`
    for now; just import the new names. (Tier 2 #5 owns build_state.)
  - Callers to verify with grep before extracting: `_lcu_summary`,
    `_liveclient_summary`. Both are likely web_dashboard-internal
    only. If a route handler imports them lazily, switch to a direct
    import the same way #3 did with routes_state.
- ⏳ #5 — `_build_state` + `_sim_states` + `_SUPERVISOR_PROXY_PATHS`
  + `_MODE_TO_FILE`. These are the dispatcher-facing helpers. Could be
  the last group before `web_dashboard.py` reduces to just `_Handler`
  + re-exports.

Other Tier 2 priorities (non-helper-shake) in
`git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` after this hand-off. The
next focused task is Tier 2 #4 (liveclient + LCU summary extraction).
Larger than #1–#3 (~120 LOC vs ~50), and the `item_advisor`
sys.path-mangling is the only non-trivial bit — everything else is the
same pattern: new module under `dashboard/`, direct imports from
existing callers, underscored re-exports in `web_dashboard.py` for
back-compat.
