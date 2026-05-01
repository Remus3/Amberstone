# Wakeup Notes — 2026-05-01 (session 18 hand-off)

> Hand-off from session that shipped Slice 2C-7d (catch-all POSTs).
> **Slice 2C is closed.** Group 7 done. The dashboard package now owns
> every route. Next session is Slice 2D — extract cert generation +
> `_DualProtocolHTTPServer` + `start_dashboard()` into `dashboard/server.py`.

---

## What just shipped

| Commit | Summary |
|---|---|
| 64b1427 | **Slice 2C-7d** (this commit): catch-all POSTs. Eight handlers from `web_dashboard.do_POST` into the dashboard package: `/api/analyze` → `routes_state`; `/api/experimental/{get,adapt,mark}` + `/api/aram-analyze` → `routes_coach`; `/api/loadout/list` (prefix), `/api/loadout/apply`, `/api/lcu-cmd` → **new** `routes_loadout.py` (only module carrying the `_VISION_TOKEN` deferred-import dependency for this group). `_LCU_ALLOWED_CMDS` hoisted from per-request to module scope. `do_POST` collapses to: CSRF check, 1 MiB cap, JSON parse, dispatch, 404 (~30 lines). web_dashboard.py: 1146 → 895 (−251). routes_loadout.py: 167 (new). Smoke-tested: 17 POST + 39 GET routes; each new path matches exactly one POST; GET-only paths (`/api/coach/state`, `/api/coach/trace`, `/api/decisions`) correctly do not match any POST. |
| (prev) | Slice 2C-7c: coach-flavored POSTs. 1215 → 1146 (−69). |
| (prev) | Slice 2C-7b: bridge POST + decisions POST. 1261 → 1215 (−46). |
| (prev) | Slice 2C-7a: input + command + console-error POSTs. 1339 → 1261 (−78). |
| 5851cab | Slice 2C-6: bridge + preview-build + champions group. 1417 → 1339 (−78). |
| (prev) | Slice 2C-5: coach + replay + cost group. 1559 → 1417 (−142). |
| (prev) | Slice 2C-4: diag/vision group. 1710 → 1559 (−151). |
| (prev) | Slice 2C-3: history/home group. 1757 → 1710 (−47). |
| 0805e2c | Slice 2C-2: state-group routes. 1892 → 1757 (−135). |
| 26312de | Slice 2C-1: dispatcher + 12 static-asset GET routes. 2103 → 1892 (−211). |
| 5760b0c | Slice 2B: dashboard/builders.py (13 builders + sqlite cache). 2612 → 2103 (−509). |

**Cumulative since slice 2B start: 2612 → 895 in `web_dashboard.py` (−1717 lines).**

## State at hand-off

- **28 unpushed commits** on `main` (was 27 + this refactor + the upcoming
  wakeup-notes commit). User decides on push before the 2026-05-10
  cloud routine.
- **RC still NOT restarted.** Fifteen queued changes (#3 log-retention,
  #4 queue-compaction, #5 first slice, slice 2A, slice 2B, slice 2C-1
  through 2C-7d) all activate together at next restart. None is
  user-visible — all are internal refactor / housekeeping.
- Restart timing is user's call. `echo restart > restart_trigger.txt`;
  verify via `ops/runtime/health.json`.
- Game-PC bridge still dead at hand-off. Liveclient relay snapshots
  still stale. (Bridge SessionStart anomaly noted at session start —
  Game-PC Claude was instructed to start gamepc_mcp_server.py and
  restart `/loop /process-bridge-tasks`.)
- `RC-PatchRefresh` still showing residual `last_result=2147942402` —
  fixed at script level; clears on next scheduled run.

## Inventory of `web_dashboard.py` (895 lines)

Re-run `grep -n "def \|class " web_dashboard.py` at session start to
refresh; table is approximate.

| Lines | Section |
|---|---|
| 1–73 | imports, constants, `_VISION_TOKEN`, `_APP_DIR`, dashboard package re-imports |
| ~80–~190 | `_champ_select_brief_via_coach` |
| ~200–~325 | bridge log: `_BRIDGE_*` constants + hydrate / rotate / post / since |
| ~325–~345 | `_diagnostics_cached`, `_MODE_TO_FILE`, `_DIAG_*` cache constants |
| ~345–~495 | `_atomic_write_json`, `_set_pregame`, `_force_vision_scan`, `_lcu_summary`, `_liveclient_summary` |
| ~495–~570 | `_build_state`, `_sim_states`, `_SUPERVISOR_PROXY_PATHS` |
| 570–736 | `_Handler` — `do_GET` (one-liner over dispatcher + supervisor-proxy fallback + 404), `do_POST` (CSRF + parse + dispatcher + 404), `_csrf_ok`, `_send` |
| 738–841 | **`_DualProtocolHTTPServer`** ← target of Slice 2D |
| 842+ | **`start_dashboard()`** ← target of Slice 2D (also creates the cert) |

## Remaining POST endpoints in legacy `do_POST` elif chain

**None.** The legacy chain is gone. `do_POST` is now:

```
CSRF check → 1 MiB body cap → JSON parse → dispatch_post → 404
```

## Slice 2C plan — COMPLETE ✅

- ✅ **Group 1 — static** (12 GET routes): shipped in 26312de
- ✅ **Group 2 — state** (6 GET routes): shipped in 0805e2c
- ✅ **Group 3 — history/home** (4 GET routes): shipped (2C-3)
- ✅ **Group 4 — diag/vision** (7 GET routes): shipped (2C-4)
- ✅ **Group 5 — coach + replay + cost** (7 GET routes): shipped (2C-5)
- ✅ **Group 6 — bridge + preview-build + champions** (3 GET routes): shipped (2C-6)
- ✅ **Group 7 — POST migration** (7a + 7b + 7c + 7d): shipped (2C-7d this commit)

Final dispatcher tally: **39 GET + 17 POST routes** across 7 routes_* modules.
Module breakdown:
- `routes_static`: GETs only (assets + manifest + icons)
- `routes_state`:    /api/state, sim-state, health, health/all, ui-version, asset-stamp + POST: input, command, console-error, analyze
- `routes_history`:  history/home GETs
- `routes_diag`:     vision/decisions/diagnostics/ocr GETs + POST: decisions/<id>
- `routes_coach`:    cost/coach-state/coach-trace/replay/recommend/logs GETs + POST: replay-coach, speak, champ-select-coach, coach/toggle, experimental/{get,adapt,mark}, aram-analyze
- `routes_bridge`:   bridge GETs + POST: bridge
- `routes_loadout`:  POSTs only — loadout/list, loadout/apply, lcu-cmd

## NEXT SESSION — Slice 2D: dashboard/server.py

Goal: extract `_DualProtocolHTTPServer` + cert generation +
`start_dashboard()` from `web_dashboard.py` into a new
`dashboard/server.py`. Small, self-contained.

### Inventory to extract (web_dashboard.py lines 738–end, ~160 lines)

1. **`_DualProtocolHTTPServer(ThreadingHTTPServer)`** (738–841)
   — peek-first-byte HTTP/TLS multiplexer, the 2026-04-28 Game-PC fix.
   Self-contained class. Imports: `ssl`, `socket`, `ThreadingHTTPServer`.

2. **`start_dashboard(app_dir: Path)`** (842–end) — entry point that
   the daemon thread in `main.py` calls. Generates a self-signed cert
   on first run (or refreshes if expired), wraps the server in TLS,
   binds, serves forever. Signature: `start_dashboard(app_dir: Path) -> None`.

### Pattern for slice 2D

```python
# dashboard/server.py — new module
"""HTTP/TLS server for the dashboard.

Slice 2D (2026-05-01): extracts _DualProtocolHTTPServer + cert
generation + the start_dashboard entry point from web_dashboard.py.
"""
from http.server import ThreadingHTTPServer
import ssl, socket, ...
from dashboard._context import APP_DIR

class _DualProtocolHTTPServer(ThreadingHTTPServer):
    ...

def start_dashboard(app_dir):
    from web_dashboard import _Handler  # deferred — _Handler stays
    ...
```

Then in `web_dashboard.py`:
```python
from dashboard.server import start_dashboard, _DualProtocolHTTPServer  # noqa: F401
```

### Subtleties

- **`_Handler` stays in `web_dashboard.py`**: it references many
  module-scope helpers (`_build_state`, `_diagnostics_cached`,
  `_VISION_TOKEN`, `_set_pregame`, etc.). Moving it would re-introduce
  the circular surface the deferred-imports were designed to avoid.
  Server module only needs to know the handler class to pass to
  `ThreadingHTTPServer.__init__`, so deferred-import it.
- **`main.py` import surface**: `start_dashboard` is currently imported
  as `from web_dashboard import start_dashboard`. Either re-export from
  `web_dashboard.py` (the `# noqa: F401` line above) or update `main.py`.
  Re-export is the smaller diff and preserves the public surface.
- **Cert file paths**: cert + key are written under `APP_DIR / "ops" /
  "runtime"`. Use `APP_DIR` from `dashboard._context` rather than
  re-deriving — same as builders.py and routes_*.
- **Logger name**: keep `logging.getLogger("rc.web_dashboard")` so
  log filters keep working.
- **`_DualProtocolHTTPServer.handle_error` signature**: stdlib's
  `BaseServer.handle_error` is `(self, request, client_address)`. Keep
  it intact when you cut/paste — easy to drop a `self` and break the
  override silently.

### Verification after restart

After `echo restart > restart_trigger.txt`, plus the slice-2D-specific:

1. **Dashboard responds on :8888 over TLS**:
   ```
   curl -k https://127.0.0.1:8888/api/health
   ```
   returns the health JSON.
2. **Plaintext HTTP on the same port redirects to HTTPS**:
   ```
   curl -v http://127.0.0.1:8888/
   ```
   should land a `301` to `https://...:8888/` (the dual-protocol
   handler's plaintext branch).
3. **Cert refresh path**: delete `ops/runtime/dashboard.{crt,key}`,
   restart, confirm new cert is regenerated and dashboard is reachable.

If any of those fail, the cert/server extraction is broken. Hard
fallback: revert the slice-2D commit; this commit (2C-7d) was the last
green build with `start_dashboard` still in `web_dashboard.py`.

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:
1. All items 1-21 from prior sessions + items 1-3 from session 15
   + bridge round-trip + decisions POST 404 from session 16 +
   replay-coach / speak / champ-select-coach / coach/toggle from
   session 17 — all unchanged.
2. **NEW (7d): /api/analyze supervisor proxy:**
   ```
   curl -k -X POST -H 'Content-Type: application/json' \
     -d '{}' \
     https://127.0.0.1:8888/api/analyze
   ```
   returns supervisor's analysis JSON (or 500 with `error` if the
   supervisor at :8890 is down — that's fine; confirms the route
   wiring + 30 s timeout).
3. **NEW (7d): /api/experimental/get** (POST):
   ```
   curl -k -X POST -H 'Content-Type: application/json' \
     -d '{"champion":"Vayne","mode":"aram"}' \
     https://127.0.0.1:8888/api/experimental/get
   ```
   returns `{ok, champion, current, history}`.
4. **NEW (7d): /api/loadout/list** (POST, prefix-matched):
   ```
   curl -k -X POST -H 'Content-Type: application/json' \
     -d '{"champion":"Vayne","mode":"sr"}' \
     https://127.0.0.1:8888/api/loadout/list
   ```
   returns `{champion, mode, variants, default}`.
5. **NEW (7d): /api/lcu-cmd** allowlist negative-test (no live LCU needed):
   ```
   curl -k -X POST -H 'Content-Type: application/json' \
     -d '{"cmd":"this_is_not_allowed"}' \
     https://127.0.0.1:8888/api/lcu-cmd
   ```
   returns 400 with `{"error":"unknown_lcu_cmd","allowed":[...]}` —
   confirms the allowlist hoist into routes_loadout works.

If any of those fail, the dispatcher wiring is broken. Hard fallback:
revert this commit; slice 2C-7c was the last green build.

## After Slice 2D

Once Slice 2D ships, `web_dashboard.py` is left with: `_Handler` +
the helpers it pulls (`_build_state`, `_diagnostics_cached`,
`_lcu_summary`, `_liveclient_summary`, `_set_pregame`,
`_force_vision_scan`, `_atomic_write_json`, bridge log helpers,
`_champ_select_brief_via_coach`, `_sim_states`). That's ~700 lines —
all consumed by the dispatcher's deferred-imports from `dashboard/*`.
The next refactor pass would shake those helpers out into
`dashboard/_helpers.py` (or two — bridge_log + state_helpers), but
that is **Tier 2**, not Tier 1.

## Tier 1 #5 status

#5 itself (web_dashboard.py decomposition) is functionally complete
after Slice 2D. The remaining helper-shake is a Tier 2 task. After
Slice 2D ships, the Tier 1 list is closed.

Tier 2 priorities live in `git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` between #5 sub-slices.
Slice 2D is its own focused task. After 2D ships, the dashboard
package is the dashboard's only owner; `web_dashboard.py` is the
stateful-helper module + `_Handler`.
