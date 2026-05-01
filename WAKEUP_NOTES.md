# Wakeup Notes — 2026-05-01 (session 10 hand-off)

> Hand-off from session that shipped Slice 2C-2 (state route group).
> Next session continues with route group 3 (history/home).

---

## What just shipped

| Commit | Summary |
|---|---|
| (this) | **Slice 2C-2**: state-group routes. New: `dashboard/routes_state.py` with 6 GET handlers — `/api/state`, `/api/sim-state`, `/api/health`, `/api/health/all`, `/api/ui-version`, `/api/asset-stamp`. `_STATE_CACHE_PAYLOAD/_TS` moved into the routes module. `_dispatch._gather_get/_post` now also include `routes_state.{GET,POST}_ROUTES`. web_dashboard.py: 1892 → 1757 (-135). do_GET legacy chain now starts with `/api/vision-state`. Smoke-tested all 6 matchers + 4 cheap handlers (health, asset-stamp, ui-version, sim-state) returning 200. |
| 26312de | Slice 2C-1: dispatcher + 12 static-asset GET routes. 2103 → 1892 (-211). |
| 5760b0c | Slice 2B: dashboard/builders.py (13 builders + sqlite cache). 2612 → 2103 (-509). |

## State at hand-off

- **16 unpushed commits** on `main` (was 15). User decides on push before 5/10 cloud routine.
- **RC still NOT restarted.** Seven queued changes (#3 log-retention, #4 queue-compaction, #5 first slice, slice 2A, slice 2B, slice 2C-1, slice 2C-2) all activate together at next restart. None is user-visible — all are internal refactor / housekeeping.
- Restart timing is user's call. `echo restart > restart_trigger.txt`; verify via `ops/runtime/health.json`.
- Game-PC bridge still dead. Liveclient relay snapshots still stale.
- `RC-PatchRefresh` still showing residual `last_result=2147942402` — fixed at script level; clears on next scheduled run.

## Inventory of `web_dashboard.py` (1757 lines)

Section map (post-2C-2):

| Lines | Section |
|---|---|
| 1–80 | imports, constants, `_VISION_TOKEN`, `_APP_DIR`, dashboard package re-imports |
| 85–197 | `_champ_select_brief_via_coach` |
| 198–308 | bridge log: `_BRIDGE_*` constants + hydrate / rotate / post / since |
| 310–329 | `_MODE_TO_FILE`, `_DIAG_*` cache constants, `_diagnostics_cached` |
| 331–407 | `_atomic_write_json`, `_set_pregame`, `_force_vision_scan`, `_lcu_summary`, `_liveclient_summary` |
| 504–578 | `_build_state`, `_sim_states`, `_SUPERVISOR_PROXY_PATHS` |
| 581–1067 | `class _Handler(BaseHTTPRequestHandler)` |
| 1122–1598 | `do_POST` body + remaining POST routes |
| 1600–1702 | `class _DualProtocolHTTPServer` |
| 1704+ | `start_dashboard()` |

Re-run `grep -n "def \|class " web_dashboard.py` at session start to refresh — table is approximate.

## Slice 2C plan (recap, with progress)

Carve `_Handler` into focused route modules. Dispatcher infra in place — each subsequent group is just (a) a new `dashboard/routes_<name>.py` + (b) deletion of the corresponding elif blocks.

Status:
- ✅ **Group 1 — static** (12 GET routes): shipped in 26312de
- ✅ **Group 2 — state** (6 GET routes): shipped this session
- ⏳ **Group 3 — history/home** (`/api/home/summary`, `/api/session/summary`, `/api/history`, `/api/loadouts/all`)
- ⏳ **Group 4 — diag/vision** (`/api/diagnostics`, `/api/vision-state`, `/api/decisions`, `/api/ocr`, `/api/validate-ocr`, `/api/ocr-crop`, `/api/reload-regions`)
- ⏳ **Group 5 — coach + replay + cost** (`/api/cost`, `/api/coach/trace`, `/api/coach/state`, `/api/replay/matches`, `/api/replay/match/*`, `/api/recommend-champ`, `/api/logs`)
- ⏳ **Group 6 — bridge + champions + preview** (`/api/bridge` GET, `/api/preview-build`, `/api/champions`)
- ⏳ **Group 7 — POST commands** (full POST migration; see prior hand-off)

Recommended order: 3 → 4 → 5 → 6 → 7.

## Pattern for the next group (example: history/home)

1. Create `dashboard/routes_history.py`. For each handler:
   - Lift the elif body into a free function `def _serve_history(h): …` — replace `self` with `h`.
   - History group is straightforward — all four handlers call into `dashboard.builders` (already extracted) and just need wiring to `equals(...)` / `prefix(...)` matchers.
2. `GET_ROUTES = [(equals("/api/home/summary"), _serve_home_summary), (equals("/api/session/summary"), …), (prefix("/api/history"), …), (prefix("/api/loadouts/all"), …)]`.
3. Edit `dashboard/_dispatch.py`'s `_gather_get/_post` to include `routes_history.{GET,POST}_ROUTES` (after `routes_state`).
4. Delete the corresponding elif blocks from web_dashboard's `do_GET`.
5. py_compile + smoke-import + matcher coverage check.
6. Commit.

## Subtleties to watch

- **Cross-module circular imports**: `routes_state._serve_state` uses `from web_dashboard import _build_state` *inside* the handler body — deferred import. Same pattern for `_sim_states`. This avoids a cycle at module-load time. Apply the same pattern in `routes_history` if any helper still lives in web_dashboard.
- **`_global` caches inside route bodies**: `_CHAMP_MAP_CACHE` (champions group), `_CE_LAST_TS/_CE_DROPPED` (console-error in POST group). When migrating, move them into the routes module — they're not used elsewhere.
- **Import-time vs request-time**: many handlers do `import urllib.request as _ur` *inside* the handler body. Keep that pattern when migrating — moving to module top-level changes startup cost characteristics.
- **`self._send` / `self._proxy_to_supervisor` / `self.headers`**: still on `_Handler` — handlers receive `h` and call them via `h._send(...)`.
- **CSRF / body-parsing**: `do_POST` still does CSRF + body parsing at the entry, before dispatch. POST handlers receive the parsed dict as second arg.
- **Ordering matters within a group** (more-specific paths first). Cross-group ordering matters too — append groups in registration order. None of the current groups overlap.

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:
1. `ops/runtime/health.json` shows new pid + `alive=true` + `last_reload_ok=true`.
2. `curl -k https://127.0.0.1:8888/api/state` returns the live state JSON (now from `routes_state._serve_state`).
3. `curl -k https://127.0.0.1:8888/api/health` returns RC health + `rc_version`.
4. `curl -k https://127.0.0.1:8888/api/health/all` returns the rollup with status (red/yellow/green).
5. `curl -k https://127.0.0.1:8888/api/asset-stamp` and `/api/ui-version` return mtime / hash.
6. `curl -k "https://127.0.0.1:8888/api/sim-state?scenario=aram_blitz"` returns the sim payload.
7. `curl -k https://127.0.0.1:8888/` and `/manifest.json` still work (slice 2C-1).

If any of those fail, the dashboard package wiring is broken — likely an import-order issue under `pythonw.exe`. Hard fallback: revert the slice 2C-2 commit (slice 2C-1 at `26312de` was the last green build).

## Slice 2D (later)

Extract cert-generation + `_DualProtocolHTTPServer` into `dashboard/server.py`. Small, self-contained. After 2C is fully done.

## After #5

Tier 1 list complete after the full #5 (multi-session). Tier 2 priorities live in `git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` between #5 sub-slices. Each route group is its own focused task.
