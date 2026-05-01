# Wakeup Notes — 2026-05-01 (session 11 hand-off)

> Hand-off from session that shipped Slice 2C-3 (history/home route group).
> Next session continues with route group 4 (diag/vision).

---

## What just shipped

| Commit | Summary |
|---|---|
| (this) | **Slice 2C-3**: history/home route group. New: `dashboard/routes_history.py` with 4 GET handlers — `/api/session/summary`, `/api/history`, `/api/loadouts/all`, `/api/home/summary`. All four were trivial — they're thin wrappers over `dashboard.builders` already extracted in slice 2B. `_dispatch._gather_get/_post` now also include `routes_history.{GET,POST}_ROUTES`. web_dashboard.py: 1757 → 1710 (−47). Removed 4 now-unused builder imports (`_build_history`, `_build_home_summary`, `_build_loadouts_all`, `_build_session_summary`). Smoke-tested all 4 matchers + dispatcher returns 22 GET routes (12 static + 6 state + 4 history); confirmed unmigrated routes still fall through. |
| 0805e2c | Slice 2C-2: state-group routes. 1892 → 1757 (−135). |
| 26312de | Slice 2C-1: dispatcher + 12 static-asset GET routes. 2103 → 1892 (−211). |
| 5760b0c | Slice 2B: dashboard/builders.py (13 builders + sqlite cache). 2612 → 2103 (−509). |

## State at hand-off

- **20 unpushed commits** on `main` (was 18). User decides on push before 5/10 cloud routine.
- **RC still NOT restarted.** Eight queued changes (#3 log-retention, #4 queue-compaction, #5 first slice, slice 2A, slice 2B, slice 2C-1, slice 2C-2, slice 2C-3) all activate together at next restart. None is user-visible — all are internal refactor / housekeeping.
- Restart timing is user's call. `echo restart > restart_trigger.txt`; verify via `ops/runtime/health.json`.
- Game-PC bridge still dead. Liveclient relay snapshots still stale.
- `RC-PatchRefresh` still showing residual `last_result=2147942402` — fixed at script level; clears on next scheduled run.

## Inventory of `web_dashboard.py` (1710 lines)

Section map (post-2C-3):

| Lines | Section |
|---|---|
| 1–75 | imports, constants, `_VISION_TOKEN`, `_APP_DIR`, dashboard package re-imports |
| 81–193 | `_champ_select_brief_via_coach` |
| 201–325 | bridge log: `_BRIDGE_*` constants + hydrate / rotate / post / since |
| 328–345 | `_diagnostics_cached`, `_MODE_TO_FILE`, `_DIAG_*` cache constants |
| 347–498 | `_atomic_write_json`, `_set_pregame`, `_force_vision_scan`, `_lcu_summary`, `_liveclient_summary` |
| 500–574 | `_build_state`, `_sim_states`, `_SUPERVISOR_PROXY_PATHS` |
| 577–1020 | `class _Handler(BaseHTTPRequestHandler)` |
| 1075–1551 | `do_POST` body + remaining POST routes |
| 1553–1655 | `class _DualProtocolHTTPServer` |
| 1657+ | `start_dashboard()` |

Re-run `grep -n "def \|class " web_dashboard.py` at session start to refresh — table is approximate.

## Slice 2C plan (recap, with progress)

Carve `_Handler` into focused route modules. Dispatcher infra in place — each subsequent group is just (a) a new `dashboard/routes_<name>.py` + (b) deletion of the corresponding elif blocks.

Status:
- ✅ **Group 1 — static** (12 GET routes): shipped in 26312de
- ✅ **Group 2 — state** (6 GET routes): shipped in 0805e2c
- ✅ **Group 3 — history/home** (4 GET routes): shipped this session
- ⏳ **Group 4 — diag/vision** (`/api/diagnostics`, `/api/vision-state`, `/api/decisions`, `/api/ocr`, `/api/validate-ocr`, `/api/ocr-crop`, `/api/reload-regions`)
- ⏳ **Group 5 — coach + replay + cost** (`/api/cost`, `/api/coach/trace`, `/api/coach/state`, `/api/replay/matches`, `/api/replay/match/*`, `/api/recommend-champ`, `/api/logs`)
- ⏳ **Group 6 — bridge + champions + preview** (`/api/bridge` GET, `/api/preview-build`, `/api/champions`)
- ⏳ **Group 7 — POST commands** (full POST migration; see prior hand-off)

Recommended order: 4 → 5 → 6 → 7.

## Pattern for the next group (group 4: diag/vision)

This is the first non-trivial group. Several handlers (`/api/ocr`, `/api/validate-ocr`, `/api/ocr-crop`) reach out to the local vision server at `http://127.0.0.1:8889/latest-frame` and the Live Client API at `https://192.168.8.237:2999/...`. They use `_VISION_TOKEN` (module-level in web_dashboard.py).

1. Create `dashboard/routes_diag.py`. For each handler:
   - Lift the elif body into a free function `def _serve_<name>(h): …` — replace `self` with `h`.
   - Move `_VISION_TOKEN` reference: either `from web_dashboard import _VISION_TOKEN` inside the handler, or pass it via env. Prefer the deferred-import pattern (see `routes_state._serve_state`).
   - `_diagnostics_cached` is a module-level helper in web_dashboard — also deferred-import.
   - The `_close` nested helper inside `/api/validate-ocr` (line 758 ish) can stay nested or be lifted to a module-level `_close_enough()`.
2. `GET_ROUTES = [(equals("/api/diagnostics"), …), (equals("/api/vision-state"), …), (equals("/api/decisions"), …), (equals("/api/ocr"), …), (equals("/api/validate-ocr"), …), (prefix("/api/ocr-crop"), …), (equals("/api/reload-regions"), …)]`.
3. Edit `dashboard/_dispatch.py`'s `_gather_get/_post` to include `routes_diag.{GET,POST}_ROUTES` (after `routes_history`).
4. Delete the corresponding elif blocks from web_dashboard's `do_GET`. Note the **`/api/vision-state`** block is currently the first `if` (not `elif`) in the legacy chain — once removed, the next branch must become the new first `if`. Currently lines 640–650 have `if self.path == "/api/vision-state"`; after removal, `elif self.path == "/api/decisions"` must become `if`. Easiest path: delete the if-block, then convert the next `elif` to `if`.
5. py_compile + smoke-import + matcher coverage check.
6. Commit.

## Subtleties to watch

- **Cross-module circular imports**: `routes_state._serve_state` uses `from web_dashboard import _build_state` *inside* the handler body — deferred import. Same pattern for `_sim_states`. Apply the same pattern in `routes_diag` for `_diagnostics_cached` and `_VISION_TOKEN`.
- **`_global` caches inside route bodies**: `_CHAMP_MAP_CACHE` (champions group), `_CE_LAST_TS/_CE_DROPPED` (console-error in POST group). When migrating, move them into the routes module — they're not used elsewhere.
- **Import-time vs request-time**: many handlers do `import urllib.request as _ur` *inside* the handler body. Keep that pattern when migrating — moving to module top-level changes startup cost characteristics.
- **`self._send` / `self._proxy_to_supervisor` / `self.headers`**: still on `_Handler` — handlers receive `h` and call them via `h._send(...)`.
- **CSRF / body-parsing**: `do_POST` still does CSRF + body parsing at the entry, before dispatch. POST handlers receive the parsed dict as second arg.
- **First `if` vs `elif` after migration**: when group 4 removes the leading `if self.path == "/api/vision-state":`, the next `elif` must be promoted to `if`. The dispatcher returns early on match so this is safe.
- **Ordering matters within a group** (more-specific paths first). Cross-group ordering matters too — append groups in registration order. None of the current groups overlap.

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:
1. `ops/runtime/health.json` shows new pid + `alive=true` + `last_reload_ok=true`.
2. `curl -k https://127.0.0.1:8888/api/state` returns the live state JSON.
3. `curl -k https://127.0.0.1:8888/api/health` and `/api/health/all` return RC + rollup health.
4. `curl -k https://127.0.0.1:8888/api/home/summary` returns home aggregate (now from `routes_history._serve_home_summary`).
5. `curl -k https://127.0.0.1:8888/api/session/summary` returns session aggregate.
6. `curl -k "https://127.0.0.1:8888/api/history?scope=14d"` returns 14-day history.
7. `curl -k "https://127.0.0.1:8888/api/loadouts/all?mode=aram"` returns ARAM loadouts.
8. `curl -k https://127.0.0.1:8888/` and `/manifest.json` still work (slice 2C-1).

If any of those fail, the dashboard package wiring is broken — likely an import-order issue under `pythonw.exe`. Hard fallback: revert the slice 2C-3 commit (slice 2C-2 at `0805e2c` was the last green build).

## Slice 2D (later)

Extract cert-generation + `_DualProtocolHTTPServer` into `dashboard/server.py`. Small, self-contained. After 2C is fully done.

## After #5

Tier 1 list complete after the full #5 (multi-session). Tier 2 priorities live in `git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` between #5 sub-slices. Each route group is its own focused task.
