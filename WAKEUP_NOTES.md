# Wakeup Notes — 2026-05-01 (session 14 hand-off)

> Hand-off from session that shipped Slice 2C-6 (bridge + preview-build + champions route group).
> Next session continues with group 7 (POST migration — full do_POST carve-out).

---

## What just shipped

| Commit | Summary |
|---|---|
| (this) | **Slice 2C-6**: bridge + preview-build + champions route group. New: `dashboard/routes_bridge.py` with 3 GET handlers — `/api/bridge`, `/api/preview-build`, `/api/champions`. The first two deferred-import their helpers (`_bridge_since`, `_lcu_summary`, `_champ_select_brief_via_coach`) from `web_dashboard` inside the handler body — same circular-import workaround as `routes_diag`. `/api/champions` migrated its module-level cache (`_CHAMP_MAP_CACHE`) into `routes_bridge._CACHE`; the orphaned global was removed from `web_dashboard.py`. `_dispatch._gather_get/_post` now register `routes_bridge.{GET,POST}_ROUTES`. `do_GET` is now a one-liner over the dispatcher + supervisor-proxy fallback + 404 — no `elif` chain remains. web_dashboard.py: 1417 → 1339 (−78). Smoke-tested: 39 GET routes total (12 static + 6 state + 4 history + 7 diag + 7 coach + 3 bridge); each group-6 path matches exactly one handler; `/api/analyze` & `/api/adaptation` still fall through to supervisor-proxy. `_bridge_since`, `_lcu_summary`, `_champ_select_brief_via_coach` all still importable from `web_dashboard`. |
| (prev) | Slice 2C-5: coach + replay + cost group. 1559 → 1417 (−142). |
| (prev) | Slice 2C-4: diag/vision group. 1710 → 1559 (−151). |
| (prev) | Slice 2C-3: history/home group. 1757 → 1710 (−47). |
| 0805e2c | Slice 2C-2: state-group routes. 1892 → 1757 (−135). |
| 26312de | Slice 2C-1: dispatcher + 12 static-asset GET routes. 2103 → 1892 (−211). |
| 5760b0c | Slice 2B: dashboard/builders.py (13 builders + sqlite cache). 2612 → 2103 (−509). |

## State at hand-off

- **23 unpushed commits** on `main` (was 22). User decides on push before 5/10 cloud routine.
- **RC still NOT restarted.** Eleven queued changes (#3 log-retention, #4 queue-compaction, #5 first slice, slice 2A, slice 2B, slice 2C-1, slice 2C-2, slice 2C-3, slice 2C-4, slice 2C-5, slice 2C-6) all activate together at next restart. None is user-visible — all are internal refactor / housekeeping.
- Restart timing is user's call. `echo restart > restart_trigger.txt`; verify via `ops/runtime/health.json`.
- Game-PC bridge still dead. Liveclient relay snapshots still stale.
- `RC-PatchRefresh` still showing residual `last_result=2147942402` — fixed at script level; clears on next scheduled run.

## Inventory of `web_dashboard.py` (1339 lines)

Section map (post-2C-6) — re-run `grep -n "def \|class " web_dashboard.py` at session start to refresh; table is approximate.

| Lines | Section |
|---|---|
| 1–73 | imports, constants, `_VISION_TOKEN`, `_APP_DIR`, dashboard package re-imports |
| ~80–~190 | `_champ_select_brief_via_coach` |
| ~200–~325 | bridge log: `_BRIDGE_*` constants + hydrate / rotate / post / since |
| ~325–~345 | `_diagnostics_cached`, `_MODE_TO_FILE`, `_DIAG_*` cache constants |
| ~345–~495 | `_atomic_write_json`, `_set_pregame`, `_force_vision_scan`, `_lcu_summary`, `_liveclient_summary` |
| ~495–~570 | `_build_state`, `_sim_states`, `_SUPERVISOR_PROXY_PATHS` |
| ~575–~650 | `class _Handler(BaseHTTPRequestHandler)` do_GET — now a one-liner over the dispatcher + supervisor-proxy fallback + 404 (no elif chain remains) |
| ~700–~1185 | `do_POST` body + remaining POST routes (target of group 7) |
| ~1185–~1290 | `class _DualProtocolHTTPServer` |
| ~1290+ | `start_dashboard()` |

## Slice 2C plan (recap, with progress)

Carve `_Handler` into focused route modules. Dispatcher infra in place — each subsequent group is just (a) a new `dashboard/routes_<name>.py` + (b) deletion of the corresponding elif blocks.

Status:
- ✅ **Group 1 — static** (12 GET routes): shipped in 26312de
- ✅ **Group 2 — state** (6 GET routes): shipped in 0805e2c
- ✅ **Group 3 — history/home** (4 GET routes): shipped (2C-3)
- ✅ **Group 4 — diag/vision** (7 GET routes): shipped (2C-4)
- ✅ **Group 5 — coach + replay + cost** (7 GET routes): shipped (2C-5)
- ✅ **Group 6 — bridge + preview-build + champions** (3 GET routes): shipped this session
- ⏳ **Group 7 — POST commands** (full POST migration; see prior hand-off)

GET migration is complete after 2C-6. `do_GET` is now a 12-line method (dispatcher + supervisor-proxy fallback + 404). All future work is on POST.

## Pattern for the next group (group 7: POST migration)

`do_POST` (~lines 700–1185) still owns the full POST chain. Body parsing + CSRF check stay at the entry; each registered POST handler receives `(h, body)` per `_dispatch.dispatch_post`. Re-read `do_POST` at session start; the elif chain has many endpoints (input write, command, console-error, bridge-write, kill-switch toggles, validate-ocr write, decisions ack, replay write, etc.).

Recommended sub-slicing:
- 7a — small/self-contained POSTs: `/api/input`, `/api/command`, `/api/console-error` (note `_CE_LAST_TS/_CE_DROPPED` cache — migrate alongside the handler, same pattern as `_CHAMP_MAP_CACHE` → `routes_bridge._CACHE`).
- 7b — bridge POSTs: `/api/bridge` (POST), `/api/bridge/ack`, etc. Bridge helpers (`_bridge_post`, `_bridge_maybe_rotate`) live in `web_dashboard` and stay there — deferred-import into `routes_bridge` POST handlers.
- 7c — coach POSTs: `/api/coach/state` toggle, kill-switch writes — sibling to `routes_coach` GETs.
- 7d — vision/OCR POSTs (calibration, region writes) — sibling to `routes_diag`.

After all four, `do_POST` reduces to a body-read + CSRF + `_dispatch.dispatch_post(self, body)` + 404 fallback.

Subtleties (group 7 specific):
- CSRF + body parsing happen *before* dispatch — handlers receive a parsed dict.
- Several POST handlers do their own auth checks (`_VISION_TOKEN` for vision writes). Keep that pattern; deferred-import the constant if needed.
- POST registry list per module is currently empty; populate `POST_ROUTES = [...]` and the existing `_dispatch._gather_post` already pulls them in (wired in 2C-6).

## Subtleties to watch

- **Cross-module circular imports**: `routes_state`, `routes_diag`, and now `routes_bridge` all use `from web_dashboard import …` *inside* the handler body — deferred import. `routes_coach` needed none. Group 7 (POST) will likely need it for `_bridge_post`, `_set_pregame`, `_force_vision_scan`, etc.
- **`_global` caches inside route bodies**: `_CHAMP_MAP_CACHE` already migrated (now `routes_bridge._CACHE`). `_CE_LAST_TS/_CE_DROPPED` (console-error in POST group) still in `web_dashboard.py` — move with the handler in 7a.
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
19. `curl -k "https://127.0.0.1:8888/api/bridge?since=0&limit=5"` returns recent cross-Claude messages (slice 2C-6).
20. `curl -k "https://127.0.0.1:8888/api/preview-build?champion=Vayne&mode=ARAM"` returns build/runes/ally_notes (will hit Haiku — costs a few cents).
21. `curl -k https://127.0.0.1:8888/api/champions` returns the championId→name/slug map.

If any of those fail, the dashboard package wiring is broken — likely an import-order issue under `pythonw.exe`. Hard fallback: revert the slice 2C-6 commit; slice 2C-5 was the last green build.

## Slice 2D (later)

Extract cert-generation + `_DualProtocolHTTPServer` into `dashboard/server.py`. Small, self-contained. After 2C is fully done.

## After #5

Tier 1 list complete after the full #5 (multi-session). Tier 2 priorities live in `git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` between #5 sub-slices. Each route group is its own focused task.
