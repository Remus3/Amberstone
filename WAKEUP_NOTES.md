# Wakeup Notes — 2026-05-01 (session 13 hand-off)

> Hand-off from session that shipped Slice 2C-5 (coach + replay + cost route group).
> Next session continues with route group 6 (bridge + champions + preview).

---

## What just shipped

| Commit | Summary |
|---|---|
| (this) | **Slice 2C-5**: coach + replay + cost route group. New: `dashboard/routes_coach.py` with 7 GET handlers — `/api/cost`, `/api/coach/trace`, `/api/coach/state`, `/api/replay/matches`, `/api/replay/match/<id>` (prefix), `/api/recommend-champ`, `/api/logs`. All read-only and self-contained: callers are `core.cost_tracker`, `core.coach_trace`, `core.replay_history`, `coaches.champ_pool_recommender` plus stdlib log tail — no `_VISION_TOKEN`, no Live Client probes, no `web_dashboard` imports, so no deferred-import dance. `_logs` uses `dashboard._context.APP_DIR` for the log path; `_coach_state` uses `dashboard._context.read_json` for the kill-switch config. `_dispatch._gather_get/_post` now also include `routes_coach.{GET,POST}_ROUTES`. web_dashboard.py: 1559 → 1417 (−142). The legacy section header `# ── AUDIT 2026-04-28 endpoints …` was dropped along with the elif blocks. Smoke-tested all 7 group-5 matchers + dispatcher returns 36 GET routes (12 static + 6 state + 4 history + 7 diag + 7 coach). `/api/bridge`, `/api/preview-build`, `/api/champions`, `/api/analyze` correctly fall through to legacy elif chain (group 6 / supervisor-proxy). No leading-`if` promotion needed — the supervisor-proxy block from 2C-4 still leads. |
| (prev) | Slice 2C-4: diag/vision group. 1710 → 1559 (−151). |
| (prev) | Slice 2C-3: history/home group. 1757 → 1710 (−47). |
| 0805e2c | Slice 2C-2: state-group routes. 1892 → 1757 (−135). |
| 26312de | Slice 2C-1: dispatcher + 12 static-asset GET routes. 2103 → 1892 (−211). |
| 5760b0c | Slice 2B: dashboard/builders.py (13 builders + sqlite cache). 2612 → 2103 (−509). |

## State at hand-off

- **22 unpushed commits** on `main` (was 21). User decides on push before 5/10 cloud routine.
- **RC still NOT restarted.** Ten queued changes (#3 log-retention, #4 queue-compaction, #5 first slice, slice 2A, slice 2B, slice 2C-1, slice 2C-2, slice 2C-3, slice 2C-4, slice 2C-5) all activate together at next restart. None is user-visible — all are internal refactor / housekeeping.
- Restart timing is user's call. `echo restart > restart_trigger.txt`; verify via `ops/runtime/health.json`.
- Game-PC bridge still dead. Liveclient relay snapshots still stale.
- `RC-PatchRefresh` still showing residual `last_result=2147942402` — fixed at script level; clears on next scheduled run.

## Inventory of `web_dashboard.py` (1417 lines)

Section map (post-2C-5) — re-run `grep -n "def \|class " web_dashboard.py` at session start to refresh; table is approximate.

| Lines | Section |
|---|---|
| 1–75 | imports, constants, `_VISION_TOKEN`, `_APP_DIR`, dashboard package re-imports |
| 81–193 | `_champ_select_brief_via_coach` |
| 201–325 | bridge log: `_BRIDGE_*` constants + hydrate / rotate / post / since |
| 328–345 | `_diagnostics_cached`, `_MODE_TO_FILE`, `_DIAG_*` cache constants |
| 347–498 | `_atomic_write_json`, `_set_pregame`, `_force_vision_scan`, `_lcu_summary`, `_liveclient_summary` |
| 500–574 | `_build_state`, `_sim_states`, `_SUPERVISOR_PROXY_PATHS` |
| 577–~728 | `class _Handler(BaseHTTPRequestHandler)` do_GET — only group 6 (`/api/bridge`, `/api/preview-build`, `/api/champions`) + supervisor-proxy remain |
| ~780–~1260 | `do_POST` body + remaining POST routes |
| ~1260–~1365 | `class _DualProtocolHTTPServer` |
| ~1365+ | `start_dashboard()` |

## Slice 2C plan (recap, with progress)

Carve `_Handler` into focused route modules. Dispatcher infra in place — each subsequent group is just (a) a new `dashboard/routes_<name>.py` + (b) deletion of the corresponding elif blocks.

Status:
- ✅ **Group 1 — static** (12 GET routes): shipped in 26312de
- ✅ **Group 2 — state** (6 GET routes): shipped in 0805e2c
- ✅ **Group 3 — history/home** (4 GET routes): shipped (2C-3)
- ✅ **Group 4 — diag/vision** (7 GET routes): shipped (2C-4)
- ✅ **Group 5 — coach + replay + cost** (7 GET routes): shipped this session
- ⏳ **Group 6 — bridge + champions + preview** (`/api/bridge` GET, `/api/preview-build`, `/api/champions`)
- ⏳ **Group 7 — POST commands** (full POST migration; see prior hand-off)

Recommended order: 6 → 7.

## Pattern for the next group (group 6: bridge + champions + preview)

Three remaining GET handlers. Read web_dashboard.py — they sit between the supervisor-proxy block and the `else:` 404 fallback:

| Path | Notes |
|---|---|
| `/api/bridge` (and `?…`) | Cross-Claude bridge log read. Uses `_BRIDGE_*` constants + helpers (lines 201–325). Heaviest of the group. |
| `/api/preview-build` | Pre-game build preview. |
| `/api/champions` | DDragon champion id→name/slug map. **Stateful** — keeps a module-level `_CHAMP_MAP_CACHE` populated lazily on first hit. Migrate that cache into `routes_champions` (or wherever it lands); not used elsewhere. |

1. Create `dashboard/routes_bridge.py` (or split bridge into its own file and lump champions+preview into `routes_misc.py` — single file is fine, all 3 are small and only `/api/bridge` is non-trivial).
2. For `/api/bridge`: the bridge helpers (`_bridge_hydrate`, `_bridge_rotate`, `_bridge_post`, `_bridge_since`) are still used by `do_POST` for the bridge-write side, so leave them in `web_dashboard.py` and *deferred-import* them inside the GET handler. Same circular-import pattern as `routes_diag._serve_diagnostics`.
3. For `/api/champions`: move `_CHAMP_MAP_CACHE` into the routes module as a module-level `_CACHE: dict | None = None`. Use `_APP_DIR` from `dashboard._context.APP_DIR` (no deferred import needed).
4. For `/api/preview-build`: read its body to confirm it's self-contained — likely just calls into `core.*` like the cost routes. If it touches anything in `web_dashboard.py`, deferred-import it.
5. `GET_ROUTES = [...]` — exact matches for `/api/preview-build` and `/api/champions`, `equals("/api/bridge")` for the bridge route (it accepts `?…` query strings).
6. Add `routes_bridge` to `_dispatch._gather_get/_post` (after `routes_coach`).
7. Delete the 3 elif blocks. After this, the only thing left in `do_GET` should be the supervisor-proxy block + the `else: 404` fallback.
8. py_compile + smoke-import + matcher coverage check.
9. Commit.

After group 6, `do_GET` can be reduced to a one-liner that calls `_dispatch.dispatch_get(self)` and falls back to the supervisor-proxy + 404 otherwise (or fold the supervisor-proxy into the dispatcher as a wildcard route — judgment call at the time).

## Subtleties to watch

- **Cross-module circular imports**: `routes_state._serve_state` and `routes_diag._serve_diagnostics`/`_serve_ocr`/`_serve_validate_ocr`/`_serve_ocr_crop` all use `from web_dashboard import …` *inside* the handler body — deferred import. `routes_coach` (2C-5) needed none of this; group 6 (bridge) will need it for the `_bridge_*` helpers.
- **`_global` caches inside route bodies**: `_CHAMP_MAP_CACHE` (champions group, still in `web_dashboard.py`), `_CE_LAST_TS/_CE_DROPPED` (console-error in POST group). When migrating, move them into the routes module — they're not used elsewhere.
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
14. `curl -k https://127.0.0.1:8888/api/cost` returns spend ledger (slice 2C-5).
15. `curl -k "https://127.0.0.1:8888/api/coach/trace?limit=10"` returns recent coach calls.
16. `curl -k https://127.0.0.1:8888/api/coach/state` returns per-mode coach kill-switch state.
17. `curl -k "https://127.0.0.1:8888/api/replay/matches?limit=5"` returns recent matches.
18. `curl -k "https://127.0.0.1:8888/api/logs?n=20"` returns the last 20 log lines.

If any of those fail, the dashboard package wiring is broken — likely an import-order issue under `pythonw.exe`. Hard fallback: revert the slice 2C-5 commit; slice 2C-4 was the last green build.

## Slice 2D (later)

Extract cert-generation + `_DualProtocolHTTPServer` into `dashboard/server.py`. Small, self-contained. After 2C is fully done.

## After #5

Tier 1 list complete after the full #5 (multi-session). Tier 2 priorities live in `git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` between #5 sub-slices. Each route group is its own focused task.
