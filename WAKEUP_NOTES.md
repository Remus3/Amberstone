# Wakeup Notes — 2026-05-01 (session 19 hand-off)

> Hand-off from session that shipped **Slice 2D** (server module).
> **Tier 1 #5 is closed.** `dashboard/` package now owns every route
> AND the HTTP/TLS server. `web_dashboard.py` is down to 741 lines —
> stateful helpers + `_Handler`. Next focus is the Tier 2 list
> (`git show 201ff3a -- WAKEUP_NOTES.md`) — top of which is the
> helper-shake into `dashboard/_helpers.py`.

---

## What just shipped

| Commit | Summary |
|---|---|
| (this) | **Slice 2D**: `_DualProtocolHTTPServer` + `start_dashboard` extracted into `dashboard/server.py`. Cert lookup (`ops/tls/rc.pem` + `rc-key.pem`), TLS context, daemon-thread bootstrap, vision_tracker + decision_detector spin-up — all moved. `_Handler` stays in `web_dashboard.py` (deferred-imported by `start_dashboard` via `web_dashboard._Handler`). `_APP_DIR` mutation now done by setting `web_dashboard._APP_DIR = app_dir` from inside `start_dashboard`. `PORT`, `HOST`, `ThreadingHTTPServer` import all dropped from `web_dashboard.py`. Re-export `from dashboard.server import _DualProtocolHTTPServer, start_dashboard` preserves the public surface; `main.py` import (`from web_dashboard import start_dashboard`) untouched. web_dashboard.py: 895 → 741 (−154). dashboard/server.py: 190 (new). Smoke-tested: re-exported objects are identity-equal (`start_dashboard is dashboard.server.start_dashboard`), both files `py_compile` clean. |
| 64b1427 | Slice 2C-7d: catch-all POSTs. 1146 → 895 (−251). |
| (prev)  | Slice 2C-7c: coach-flavored POSTs. 1215 → 1146 (−69). |
| (prev)  | Slice 2C-7b: bridge POST + decisions POST. 1261 → 1215 (−46). |
| (prev)  | Slice 2C-7a: input + command + console-error POSTs. 1339 → 1261 (−78). |
| 5851cab | Slice 2C-6: bridge + preview-build + champions. 1417 → 1339 (−78). |
| (prev)  | Slice 2C-5: coach + replay + cost. 1559 → 1417 (−142). |
| (prev)  | Slice 2C-4: diag/vision. 1710 → 1559 (−151). |
| (prev)  | Slice 2C-3: history/home. 1757 → 1710 (−47). |
| 0805e2c | Slice 2C-2: state-group routes. 1892 → 1757 (−135). |
| 26312de | Slice 2C-1: dispatcher + 12 static-asset GETs. 2103 → 1892 (−211). |
| 5760b0c | Slice 2B: dashboard/builders.py. 2612 → 2103 (−509). |

**Cumulative since slice 2B start: 2612 → 741 in `web_dashboard.py` (−1871 lines).**

## State at hand-off

- **29 unpushed commits** on `main` (was 28 + slice 2D + this wakeup).
  User decides on push before the 2026-05-10 cloud routine.
- **RC still NOT restarted.** Sixteen queued changes (#3 log-retention,
  #4 queue-compaction, #5 slices 1–2D + first slice) all activate
  together at next restart. None is user-visible — all internal refactor.
- Restart timing is user's call. `echo restart > restart_trigger.txt`;
  verify via `ops/runtime/health.json`.
- Game-PC bridge still dead. Liveclient relay snapshots still stale.
  (Bridge SessionStart anomaly carried over from session 18; Game-PC
  Claude was instructed last session to start gamepc_mcp_server.py and
  restart `/loop /process-bridge-tasks`.)
- `RC-PatchRefresh` still showing residual `last_result=2147942402` —
  fixed at script level; clears on next scheduled run.

## Inventory of `web_dashboard.py` (741 lines)

Re-run `grep -n "def \|class " web_dashboard.py` at session start to
refresh; table is approximate.

| Lines | Section |
|---|---|
| 1–69 | imports, constants, `_VISION_TOKEN`, `_APP_DIR`, dashboard package re-imports + slice-2D re-export |
| ~70–~190 | `_champ_select_brief_via_coach` |
| ~190–~325 | bridge log: `_BRIDGE_*` constants + hydrate / rotate / post / since |
| ~325–~345 | `_diagnostics_cached`, `_MODE_TO_FILE`, `_DIAG_*` cache constants |
| ~345–~495 | `_atomic_write_json`, `_set_pregame`, `_force_vision_scan`, `_lcu_summary`, `_liveclient_summary` |
| ~495–~570 | `_build_state`, `_sim_states`, `_SUPERVISOR_PROXY_PATHS` |
| ~570–~736 | `_Handler` — `do_GET`, `do_POST`, `_csrf_ok`, `_send`, `_proxy_to_supervisor` |
| 737–end | slice-2D re-export shim |

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:

1. All items 1-21 from prior sessions + items 1-3 from session 15
   + bridge round-trip + decisions POST 404 from session 16 +
   replay-coach / speak / champ-select-coach / coach/toggle from
   session 17 + slice 2C-7d /api/analyze + experimental + loadout +
   lcu-cmd allowlist negative test (session 18) — all unchanged.

2. **NEW (slice 2D): Dashboard responds on :8888 over TLS:**
   ```
   curl -k https://127.0.0.1:8888/api/health
   ```
   returns the health JSON. The server is now backed by
   `dashboard.server._DualProtocolHTTPServer` rather than a class
   inside `web_dashboard.py`.

3. **NEW (slice 2D): Plain HTTP redirects to HTTPS on the same port:**
   ```
   curl -v http://127.0.0.1:8888/api/health
   ```
   returns `301 Moved Permanently` with `Location:
   https://127.0.0.1:8888/api/health`. Confirms `_inline_redirect` +
   the peek-first-byte multiplexer survived the move.

4. **NEW (slice 2D): `_APP_DIR` propagation:**
   ```
   curl -k https://127.0.0.1:8888/api/state
   ```
   returns a populated state envelope. Failures here would mean
   `web_dashboard._APP_DIR` was not mutated by the new
   `dashboard.server.start_dashboard`, so all downstream JSON reads
   point at the wrong root.

5. **NEW (slice 2D): vision_tracker + decision_detector spawn:**
   `ops/runtime/health.json` shouldn't change shape — but a tail of
   today's log should still show `vision_tracker started` /
   `decision_detector started` (the optional spin-up branches at the
   bottom of `start_dashboard`). Absence is non-fatal but is the only
   way to spot a silent regression.

If any of those fail, the cert/server extraction is broken. Hard
fallback: revert this commit; slice 2C-7d (commit 64b1427) was the
last green build with `start_dashboard` still in `web_dashboard.py`.

## Tier 1 #5 — CLOSED ✅

`web_dashboard.py` decomposition complete:

- ✅ Slice 2A: `dashboard/_context.py` (sqlite cache + read_json)
- ✅ Slice 2B: `dashboard/builders.py` (13 builders)
- ✅ Slice 2C-1: dispatcher + static-asset GETs
- ✅ Slice 2C-2 through 2C-6: state / history / diag / coach / bridge GETs
- ✅ Slice 2C-7a through 2C-7d: every POST migrated
- ✅ **Slice 2D**: server + cert + start_dashboard

Final shape:
- `web_dashboard.py` (741 lines): `_Handler` + state helpers used by
  the dispatcher's deferred imports.
- `dashboard/`: 7 routes_* modules (39 GET + 17 POST), `_dispatch.py`,
  `_static.py`, `_context.py`, `builders.py`, `server.py`.

## NEXT — Tier 2 helper-shake (optional)

The remaining ~700 lines of `web_dashboard.py` are stateful helpers
consumed only by the dispatcher's deferred imports from
`dashboard/*`. The next refactor pass would shake them into
`dashboard/_helpers.py` (or split into bridge_log + state_helpers),
leaving `web_dashboard.py` as effectively just `_Handler` + the
re-exports. **This is Tier 2**, not Tier 1 — strictly polish; the
dashboard package surface is already complete.

Other Tier 2 priorities live in `git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` after this hand-off. The
next focused task is whichever Tier 2 item the user wants picked up
first. If continuing the helper-shake, start with bridge_log helpers
(`_BRIDGE_*` constants + `_bridge_hydrate/_bridge_rotate/_bridge_post/
_bridge_since`) — they're the most self-contained group.
