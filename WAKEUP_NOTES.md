# Wakeup Notes — 2026-05-01 (session 21 hand-off)

> Hand-off from session that shipped **Tier 2 #2** (diagnostics cache extraction).
> `dashboard/_diagnostics.py` now owns `_DIAG_CACHE` + `_DIAG_LOCK` +
> `diagnostics_cached()`. `web_dashboard.py` is down to **606 lines**.
> Next focus: Tier 2 #3 — pull `_atomic_write_json` + `_set_pregame` +
> `_force_vision_scan` into `dashboard/_writers.py`.

---

## What just shipped

| Commit | Summary |
|---|---|
| 8defac7 | **Tier 2 #2**: diagnostics cache extracted to `dashboard/_diagnostics.py`. State (`_DIAG_CACHE`, `_DIAG_LOCK`, `_DIAG_TTL_S`) + `diagnostics_cached()` all moved. `routes_diag.py` switched from the deferred `from web_dashboard import _diagnostics_cached` shim (added in slice 2C to dodge the import cycle) to a module-scope `from dashboard._diagnostics import diagnostics_cached`. `web_dashboard.py` retains underscored re-exports (`_DIAG_CACHE` / `_DIAG_LOCK` / `_DIAG_TTL_S` / `_diagnostics_cached`) for any external caller. Also dropped now-dead `import sqlite3` (unused since slice 2B, 07e8f77) and `import threading` (unused after this commit). web_dashboard.py: 621 → 606 (−15). dashboard/_diagnostics.py: 40 (new). Smoke-tested: re-exports identity-equal, first call populates 5593-byte payload, second call short-circuits (same bytes object, `expires` unchanged), GET_ROUTES has 7 routes, dashboard.routes_diag importable in a fresh process without web_dashboard. |
| 4317d15 | Tier 2 #1: bridge log → `dashboard/_bridge_log.py`. 741 → 621 (−120). |
| f22bd01 | Slice 2D: HTTP server + start_dashboard → `dashboard/server.py`. 895 → 741 (−154). |

**Cumulative since slice 2B start: 2612 → 606 in `web_dashboard.py` (−2006 lines).**

## State at hand-off

- **31 unpushed commits** on `main` (was 30 + this refactor).
  Origin push still pending — user's call before the 2026-05-10 cloud routine.
- **RC still NOT restarted.** Seventeen+ queued changes (#3 log-retention,
  #4 queue-compaction, slices 1–2D + Tier 2 #1 + Tier 2 #2) all activate
  together at next restart. None is user-visible — all internal refactor.
- Restart timing is user's call. `echo restart > restart_trigger.txt`;
  verify via `ops/runtime/health.json`.
- Game-PC bridge still dead (last gamepc result 68539s ago at session
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

## Inventory of `web_dashboard.py` (606 lines)

Re-run `grep -n "def \|class " web_dashboard.py` at session start to
refresh; table is approximate.

| Lines | Section |
|---|---|
| 1–67 | imports, constants, `_VISION_TOKEN`, `_APP_DIR`, dashboard package re-imports + slice-2D re-export |
| ~70–~167 | `_champ_select_brief_via_coach` (Haiku build/runes/ally-notes) |
| 169–183 | bridge_log re-export shim (Tier 2 #1) |
| ~185–~205 | `_MODE_TO_FILE` + diagnostics re-export shim (Tier 2 #2) |
| ~210–~355 | `_atomic_write_json`, `_set_pregame`, `_force_vision_scan`, `_lcu_summary`, `_liveclient_summary` |
| ~357–~430 | `_build_state`, `_sim_states`, `_SUPERVISOR_PROXY_PATHS` |
| ~435–~600 | `_Handler` — `do_GET`, `do_POST`, `_csrf_ok`, `_send`, `_proxy_to_supervisor` |
| 602–end | slice-2D server re-export shim |

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:

1. All items 1-21 from prior sessions + items 1-3 from session 15
   + bridge round-trip + decisions POST 404 from session 16 +
   replay-coach / speak / champ-select-coach / coach/toggle from
   session 17 + slice 2C-7d /api/analyze + experimental + loadout +
   lcu-cmd allowlist negative test (session 18) + slice 2D dashboard
   TLS / 301 / `_APP_DIR` propagation (session 19) + bridge GET/POST
   round-trip (session 20) — all unchanged.

2. **NEW (Tier 2 #2): /api/diagnostics still works:**
   ```
   curl -k 'https://127.0.0.1:8888/api/diagnostics'
   ```
   returns the JSON payload. First call after restart sustains ~2 s
   (heavy probes); subsequent calls within 30 s short-circuit on the
   cached bytes. The cache lives in `dashboard._diagnostics._DIAG_CACHE`
   now, not in `web_dashboard`. Confirm by checking the response time
   on call 1 (>1s) vs call 2 (<50ms).

3. Re-export sanity:
   ```
   py -c "import web_dashboard, dashboard._diagnostics as d; print(web_dashboard._diagnostics_cached is d.diagnostics_cached)"
   ```
   should print `True`. If False, the re-export shim regressed.

If either of those fail, the most likely cause is the
`dashboard.builders._build_diagnostics` import inside
`dashboard/_diagnostics.py` blowing up at module load — that pulls in
the full builders module (DB cache, sqlite, etc.). Hard fallback:
revert this commit (`git revert HEAD~1` after the docs commit lands);
commit 4317d15 (Tier 2 #1) was the last green build with the cache
inside `web_dashboard.py`.

## Tier 2 progress

- ✅ **#1 — bridge_log → `dashboard/_bridge_log.py`** (4317d15)
- ✅ **#2 — diagnostics cache → `dashboard/_diagnostics.py`** (this session)
- ⏳ **#3 — writers → `dashboard/_writers.py`**. Next up.
  `_atomic_write_json` (raw atomic JSON write under `_APP_DIR`),
  `_set_pregame` (R-M-W on root `coaching_data.json` under
  `coaching_data_lock`), `_force_vision_scan` (writes
  `data/force_scan.json` to trigger BaseCoach._vision_loop). All three
  share the atomic-write invariant from CLAUDE.md ("Atomic writes
  only: tmp.write_text + tmp.replace(target). Overlays poll
  mid-write."). Worth its own module because the lock dependency
  (`core.coaching_data_lock`) is a hard rule that future writers
  should also pick up. Callers to verify with grep before extracting:
  `_set_pregame` (POST /api/input handler, somewhere in
  `routes_state.py` or `routes_coach.py`) and `_force_vision_scan`
  (POST /api/command "force_vision" handler). Use `dashboard._context.APP_DIR`
  for the path resolution (same pattern as `_bridge_log`).
- ⏳ #4 — `_lcu_summary` + `_liveclient_summary`. ~120 LOC. The
  liveclient summary embeds `item_advisor` calls — keep that here or
  pull into `dashboard/_liveclient.py`.
- ⏳ #5 — `_build_state` + `_sim_states` + `_SUPERVISOR_PROXY_PATHS`
  + `_MODE_TO_FILE` (deferred from #2 since it's tightly coupled to
  `_build_state`). These are the dispatcher-facing helpers. Could be
  the last group before `web_dashboard.py` reduces to just `_Handler`
  + re-exports.

Other Tier 2 priorities (non-helper-shake) in
`git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` after this hand-off. The
next focused task is Tier 2 #3 (writers extraction). Slightly larger
than the bridge_log / diagnostics extractions (~50 LOC + the
`coaching_data_lock` integration to preserve), but follows the same
pattern: new module under `dashboard/`, direct imports from existing
route handlers (after grep'ing for callers), underscored re-exports
in `web_dashboard.py` for back-compat.
