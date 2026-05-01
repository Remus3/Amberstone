# Wakeup Notes — 2026-05-01 (session 20 hand-off)

> Hand-off from session that shipped **Tier 2 #1** (bridge log extraction).
> `dashboard/_bridge_log.py` now owns the cross-Claude bridge state
> + its four operations. `web_dashboard.py` is down to **621 lines**.
> Next focus: continue the helper-shake into `dashboard/_helpers.py`
> (or split modules) — the remaining stateful helpers in
> `web_dashboard.py` are the diagnostics cache, mode-resolution +
> liveclient/lcu summaries, and the `_set_pregame` /
> `_force_vision_scan` writers.

---

## What just shipped

| Commit | Summary |
|---|---|
| (this) | **Tier 2 #1**: bridge log extracted to `dashboard/_bridge_log.py`. State (`_bridge_lock`, `_bridge_log` deque) + four ops (`bridge_hydrate_from_disk`, `bridge_maybe_rotate`, `bridge_post`, `bridge_since`) all moved. `routes_bridge.py` switched to module-scope direct imports — the deferred `from web_dashboard import _bridge_*` pattern (added in slice 2C-6 to dodge the import cycle) is no longer needed since `_bridge_log` doesn't depend on `web_dashboard`. `web_dashboard.py` retains `_bridge_post`/`_bridge_since`/etc. re-exports (slice-2D pattern) for any external caller. New module uses `dashboard._context.APP_DIR` so the JSONL path stays identical. web_dashboard.py: 741 → 621 (−120). dashboard/_bridge_log.py: 150 (new). Smoke-tested: re-exports identity-equal, 75 entries hydrate from disk on first import, post+since round-trip works. |
| 1428040 | Tier 1 #5 closed: docs hand-off after slice 2D. |
| f22bd01 | Slice 2D: HTTP server + start_dashboard → dashboard/server.py. 895 → 741 (−154). |
| 64b1427 | Slice 2C-7d: catch-all POSTs. 1146 → 895 (−251). |

**Cumulative since slice 2B start: 2612 → 621 in `web_dashboard.py` (−1991 lines).**

## State at hand-off

- **30 unpushed commits** on `main` (was 29 + this refactor + this wakeup).
  Origin push still pending — user's call before the 2026-05-10 cloud routine.
- **RC still NOT restarted.** Sixteen+ queued changes (#3 log-retention,
  #4 queue-compaction, slices 1–2D + Tier 2 #1) all activate together
  at next restart. None is user-visible — all internal refactor.
- Restart timing is user's call. `echo restart > restart_trigger.txt`;
  verify via `ops/runtime/health.json`.
- Game-PC bridge still dead. Liveclient relay snapshots still stale.
  (Bridge SessionStart anomaly carried over from session 18; Game-PC
  Claude was instructed last session to start gamepc_mcp_server.py and
  restart `/loop /process-bridge-tasks`.)
- `RC-PatchRefresh` still showing residual `last_result=2147942402` —
  fixed at script level; clears on next scheduled run.

## Inventory of `web_dashboard.py` (621 lines)

Re-run `grep -n "def \|class " web_dashboard.py` at session start to
refresh; table is approximate.

| Lines | Section |
|---|---|
| 1–69 | imports, constants, `_VISION_TOKEN`, `_APP_DIR`, dashboard package re-imports + slice-2D re-export |
| ~70–~167 | `_champ_select_brief_via_coach` (Haiku build/runes/ally-notes) |
| 169–183 | bridge_log re-export shim (Tier 2 #1) |
| ~185–~225 | `_MODE_TO_FILE`, `_DIAG_*` cache, `_diagnostics_cached` |
| ~227–~370 | `_atomic_write_json`, `_set_pregame`, `_force_vision_scan`, `_lcu_summary`, `_liveclient_summary` |
| ~372–~445 | `_build_state`, `_sim_states`, `_SUPERVISOR_PROXY_PATHS` |
| ~450–~615 | `_Handler` — `do_GET`, `do_POST`, `_csrf_ok`, `_send`, `_proxy_to_supervisor` |
| 617–end | slice-2D server re-export shim |

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:

1. All items 1-21 from prior sessions + items 1-3 from session 15
   + bridge round-trip + decisions POST 404 from session 16 +
   replay-coach / speak / champ-select-coach / coach/toggle from
   session 17 + slice 2C-7d /api/analyze + experimental + loadout +
   lcu-cmd allowlist negative test (session 18) + slice 2D dashboard
   TLS / 301 / `_APP_DIR` propagation (session 19) — all unchanged.

2. **NEW (Tier 2 #1): bridge GET still works:**
   ```
   curl -k 'https://127.0.0.1:8888/api/bridge?since=0&limit=5'
   ```
   returns recent messages from the in-memory deque. The deque is
   now hydrated by `dashboard._bridge_log.bridge_hydrate_from_disk()`
   at module-import time (the explicit call moved out of
   `web_dashboard.py`). On a fresh process the count should match
   `wc -l ops/runtime/bridge_log.jsonl` capped at 100.

3. **NEW (Tier 2 #1): bridge POST still works:**
   ```
   curl -k -X POST https://127.0.0.1:8888/api/bridge \
     -H 'Content-Type: application/json' \
     -d '{"source":"smoke","summary":"post-restart Tier 2 #1 check"}'
   ```
   returns `{ok: true, ts, kind: "note"}`. Then `tail -1
   ops/runtime/bridge_log.jsonl` should show the new entry —
   confirms the JSONL append path still resolves to
   `<APP_DIR>/ops/runtime/bridge_log.jsonl`.

If either of those fail, the most likely cause is `APP_DIR`
divergence — `_bridge_log` resolves the JSONL via
`dashboard._context.APP_DIR` (project root), while web_dashboard's
`start_dashboard` mutates `web_dashboard._APP_DIR`. They should
agree because both derive from `Path(__file__)`, but mkdir +
append happens against `_bridge_log`'s view.

Hard fallback: revert this commit (`git revert HEAD~1` after the
docs commit lands); slice 2D (commit f22bd01) was the last green
build with bridge state inside `web_dashboard.py`.

## Tier 2 progress

- ✅ **#1 — bridge_log → `dashboard/_bridge_log.py`** (this session)
- ⏳ #2 — diagnostics cache (`_DIAG_CACHE` + `_diagnostics_cached`)
  could move next, alongside `_MODE_TO_FILE`. Small (~30 LOC). Lone
  caller is `routes_diag.py` via deferred import.
- ⏳ #3 — `_atomic_write_json` + `_set_pregame` + `_force_vision_scan`.
  Writers; tightly coupled to coaching-data lock + atomic-write
  invariant. Worth a `dashboard/_writers.py` of its own.
- ⏳ #4 — `_lcu_summary` + `_liveclient_summary`. ~120 LOC. The
  liveclient summary embeds item_advisor calls — keep that here or
  pull into `dashboard/_liveclient.py`.
- ⏳ #5 — `_build_state` + `_sim_states` + `_SUPERVISOR_PROXY_PATHS`.
  These are the dispatcher-facing helpers. Could be the last group
  before `web_dashboard.py` reduces to just `_Handler` + re-exports.

Other Tier 2 priorities (non-helper-shake) in
`git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` after this hand-off. The
next focused task is whichever Tier 2 #2-5 item to pick up first.
Diagnostics cache (#2) is the smallest and most self-contained
follow-up — same shape as bridge_log, ~30 LOC plus the `_MODE_TO_FILE`
constant.
