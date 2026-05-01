# Wakeup Notes — 2026-05-01 (session 12 hand-off)

> Hand-off from session that shipped Slice 2C-4 (diag/vision route group).
> Next session continues with route group 5 (coach + replay + cost).

---

## What just shipped

| Commit | Summary |
|---|---|
| (this) | **Slice 2C-4**: diag/vision route group. New: `dashboard/routes_diag.py` with 7 GET handlers — `/api/vision-state`, `/api/decisions`, `/api/diagnostics`, `/api/reload-regions`, `/api/ocr`, `/api/validate-ocr`, `/api/ocr-crop`. First non-trivial group: `/api/ocr*` and `/api/validate-ocr` reach the in-process vision server (`_VISION_TOKEN`) and the Live Client API; `/api/diagnostics` calls module-level `_diagnostics_cached`. Both are deferred-imported from `web_dashboard` inside each handler (same circular-import pattern as `routes_state._serve_state`). The nested `_close()` helper inside `validate-ocr` was lifted to module-level `_close_enough()`. `_dispatch._gather_get/_post` now also include `routes_diag.{GET,POST}_ROUTES`. web_dashboard.py: 1710 → 1559 (−151). Smoke-tested all 7 matchers + dispatcher returns 29 GET routes (12 static + 6 state + 4 history + 7 diag); confirmed `/api/bridge` and the supervisor-proxy chain still fall through to legacy. The supervisor-proxy `elif` (between former `/api/diagnostics` and `/api/reload-regions`) was promoted to the new leading `if`. |
| (prev) | Slice 2C-3: history/home group. 1757 → 1710 (−47). |
| 0805e2c | Slice 2C-2: state-group routes. 1892 → 1757 (−135). |
| 26312de | Slice 2C-1: dispatcher + 12 static-asset GET routes. 2103 → 1892 (−211). |
| 5760b0c | Slice 2B: dashboard/builders.py (13 builders + sqlite cache). 2612 → 2103 (−509). |

## State at hand-off

- **21 unpushed commits** on `main` (was 20). User decides on push before 5/10 cloud routine.
- **RC still NOT restarted.** Nine queued changes (#3 log-retention, #4 queue-compaction, #5 first slice, slice 2A, slice 2B, slice 2C-1, slice 2C-2, slice 2C-3, slice 2C-4) all activate together at next restart. None is user-visible — all are internal refactor / housekeeping.
- Restart timing is user's call. `echo restart > restart_trigger.txt`; verify via `ops/runtime/health.json`.
- Game-PC bridge still dead. Liveclient relay snapshots still stale.
- `RC-PatchRefresh` still showing residual `last_result=2147942402` — fixed at script level; clears on next scheduled run.

## Inventory of `web_dashboard.py` (1559 lines)

Section map (post-2C-4) — re-run `grep -n "def \|class " web_dashboard.py` at session start to refresh; table is approximate.

| Lines | Section |
|---|---|
| 1–75 | imports, constants, `_VISION_TOKEN`, `_APP_DIR`, dashboard package re-imports |
| 81–193 | `_champ_select_brief_via_coach` |
| 201–325 | bridge log: `_BRIDGE_*` constants + hydrate / rotate / post / since |
| 328–345 | `_diagnostics_cached`, `_MODE_TO_FILE`, `_DIAG_*` cache constants |
| 347–498 | `_atomic_write_json`, `_set_pregame`, `_force_vision_scan`, `_lcu_summary`, `_liveclient_summary` |
| 500–574 | `_build_state`, `_sim_states`, `_SUPERVISOR_PROXY_PATHS` |
| 577–~870 | `class _Handler(BaseHTTPRequestHandler)` (do_GET shrank by 7 routes / ~150 lines) |
| ~920–1400 | `do_POST` body + remaining POST routes |
| ~1400–1505 | `class _DualProtocolHTTPServer` |
| ~1505+ | `start_dashboard()` |

## Slice 2C plan (recap, with progress)

Carve `_Handler` into focused route modules. Dispatcher infra in place — each subsequent group is just (a) a new `dashboard/routes_<name>.py` + (b) deletion of the corresponding elif blocks.

Status:
- ✅ **Group 1 — static** (12 GET routes): shipped in 26312de
- ✅ **Group 2 — state** (6 GET routes): shipped in 0805e2c
- ✅ **Group 3 — history/home** (4 GET routes): shipped (prev session)
- ✅ **Group 4 — diag/vision** (7 GET routes): shipped this session
- ⏳ **Group 5 — coach + replay + cost** (`/api/cost`, `/api/coach/trace`, `/api/coach/state`, `/api/replay/matches`, `/api/replay/match/*`, `/api/recommend-champ`, `/api/logs`)
- ⏳ **Group 6 — bridge + champions + preview** (`/api/bridge` GET, `/api/preview-build`, `/api/champions`)
- ⏳ **Group 7 — POST commands** (full POST migration; see prior hand-off)

Recommended order: 5 → 6 → 7.

## Pattern for the next group (group 5: coach + replay + cost)

All handlers in this group are read-only and self-contained — no `_VISION_TOKEN`, no Live Client probes. They each call into a `core/*` module:

| Path | core module |
|---|---|
| `/api/cost` | `core.cost_tracker.get_tracker` |
| `/api/coach/trace` (also `?…`) | `core.coach_trace.read_recent` |
| `/api/coach/state` | (verify location — probably also `core.coach_trace`) |
| `/api/replay/matches` (also `?…`) | `core.replay_history.list_matches` |
| `/api/replay/match/<id>` (prefix) | `core.replay_history.match_detail` |
| `/api/recommend-champ` (verify) | (verify) |
| `/api/logs` (verify) | (verify) |

1. Create `dashboard/routes_coach.py`. For each handler:
   - Lift the elif body into `def _serve_<name>(h): …` — replace `self` with `h`.
   - All imports are stdlib + `core.*` — no deferred imports needed.
   - The `/api/replay/match/<id>` handler does manual prefix-stripping (`self.path[len("/api/replay/match/"):]`) and a regex check on the match-id; preserve both.
2. `GET_ROUTES = [...]` — use `equals()` for exact paths, `prefix()` for path-with-query and the `/api/replay/match/` route.
3. Edit `dashboard/_dispatch.py`'s `_gather_get/_post` to include `routes_coach.{GET,POST}_ROUTES` (after `routes_diag`).
4. Delete the corresponding elif blocks from web_dashboard's `do_GET`. After 2C-4 the leading `if` in the legacy chain is the supervisor-proxy block — none of group 5 sits at the top, so no `elif → if` promotion needed.
5. py_compile + smoke-import + matcher coverage check.
6. Commit.

## Subtleties to watch

- **Cross-module circular imports**: `routes_state._serve_state` and `routes_diag._serve_diagnostics`/`_serve_ocr`/`_serve_validate_ocr`/`_serve_ocr_crop` all use `from web_dashboard import …` *inside* the handler body — deferred import. If group 5 needs anything from `web_dashboard` (it shouldn't, all callers are `core.*`), apply the same pattern.
- **`_global` caches inside route bodies**: `_CHAMP_MAP_CACHE` (champions group), `_CE_LAST_TS/_CE_DROPPED` (console-error in POST group). When migrating, move them into the routes module — they're not used elsewhere.
- **Import-time vs request-time**: many handlers do `import urllib.request as _ur` *inside* the handler body. Keep that pattern when migrating — moving to module top-level changes startup cost characteristics.
- **`self._send` / `self._proxy_to_supervisor` / `self.headers`**: still on `_Handler` — handlers receive `h` and call them via `h._send(...)`.
- **CSRF / body-parsing**: `do_POST` still does CSRF + body parsing at the entry, before dispatch. POST handlers receive the parsed dict as second arg.
- **First `if` vs `elif` after migration**: leading-block promotion only matters when you delete the current top branch. After 2C-4 the leading `if` is the supervisor-proxy block; group 5's branches all sit below it.
- **Ordering matters within a group** (more-specific paths first). Cross-group ordering matters too — append groups in registration order. None of the current groups overlap.
- **Deferred-import gotcha**: `routes_diag` imports `_VISION_TOKEN` from `web_dashboard` *each request*. That's fine — it's a module-level constant — but don't refactor it into a top-level import; that re-introduces the circular import that the deferred pattern exists to avoid.

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:
1. `ops/runtime/health.json` shows new pid + `alive=true` + `last_reload_ok=true`.
2. `curl -k https://127.0.0.1:8888/api/state` returns the live state JSON.
3. `curl -k https://127.0.0.1:8888/api/health` and `/api/health/all` return RC + rollup health.
4. `curl -k https://127.0.0.1:8888/api/home/summary` returns home aggregate (`routes_history._serve_home_summary`).
5. `curl -k https://127.0.0.1:8888/api/session/summary` returns session aggregate.
6. `curl -k "https://127.0.0.1:8888/api/history?scope=14d"` returns 14-day history.
7. `curl -k "https://127.0.0.1:8888/api/loadouts/all?mode=aram"` returns ARAM loadouts.
8. `curl -k https://127.0.0.1:8888/api/diagnostics` returns diag JSON (slice 2C-4).
9. `curl -k https://127.0.0.1:8888/api/vision-state` returns `{}` (no game) or fog state.
10. `curl -k https://127.0.0.1:8888/api/decisions` returns `{"pending": []}` when idle.
11. `curl -k https://127.0.0.1:8888/api/ocr` and `/api/validate-ocr` work when a game is running (will 500-ish without a frame, that's fine).
12. `curl -k "https://127.0.0.1:8888/api/ocr-crop?field=hp"` returns a PNG when a frame is cached.
13. `curl -k https://127.0.0.1:8888/` and `/manifest.json` still work (slice 2C-1).

If any of those fail, the dashboard package wiring is broken — likely an import-order issue under `pythonw.exe`. Hard fallback: revert the slice 2C-4 commit; slice 2C-3 was the last green build.

## Slice 2D (later)

Extract cert-generation + `_DualProtocolHTTPServer` into `dashboard/server.py`. Small, self-contained. After 2C is fully done.

## After #5

Tier 1 list complete after the full #5 (multi-session). Tier 2 priorities live in `git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` between #5 sub-slices. Each route group is its own focused task.
