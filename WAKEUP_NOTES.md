# Wakeup Notes — 2026-05-01 (session 9 hand-off)

> Hand-off from session that shipped the dispatcher infrastructure +
> first route group of Slice 2C (Tier 1 #5). Next session continues
> migrating route groups out of `_Handler`.

---

## What just shipped

| Commit | Summary |
|---|---|
| 26312de | **Slice 2C-1**: dispatcher + static-asset routes. New: `dashboard/_dispatch.py` (equals/prefix matchers + `dispatch_get`/`dispatch_post` walking a cached registry), `dashboard/_static.py` (6 helpers: `compute_asset_hash`, `inject_asset_hash`, `resolve_safe_icon`, `legacy_index_html`, `manifest_bytes`, `icon_svg_bytes`), `dashboard/routes_static.py` (12 GET handlers — index, css/js/data, manifest, icon, 5× icons subdirs, agent). web_dashboard.py: 2103 → 1892 (-211). do_GET/do_POST each gained a 2-line dispatch call at the top; misses fall through to the legacy elif chain. Static-asset elif blocks + the 6 helpers deleted from web_dashboard. Helpers re-imported under their original underscored names for back-compat. Smoke-tested all 12 matchers + asset loaders. |
| 5760b0c | (prev session) Slice 2B — dashboard/builders.py (13 builders + sqlite cache). 2612 → 2103. |

## State at hand-off

- **15 unpushed commits** on `main` (was 14). User decides on push before 5/10 cloud routine.
- **RC still NOT restarted.** Six queued changes (#3 log-retention, #4 queue-compaction, #5 first slice, slice 2A, slice 2B, slice 2C-1) all activate together at next restart. None is user-visible — all are internal refactor / housekeeping.
- Restart timing is user's call. `echo restart > restart_trigger.txt`; verify via `ops/runtime/health.json`.
- Game-PC bridge still dead. Liveclient relay snapshots still stale.
- `RC-PatchRefresh` still showing residual `last_result=2147942402` — fixed at script level; clears on next scheduled run.

## Inventory of `web_dashboard.py` (1892 lines)

Section map (post-2C-1):

| Lines | Section |
|---|---|
| 1–80 | imports, constants, `_VISION_TOKEN`, `_APP_DIR`, **dashboard package re-imports** (now includes `_static`, `_dispatch`) |
| 82–197 | `_champ_select_brief_via_coach` |
| 198–308 | bridge log: `_BRIDGE_*` constants + hydrate / rotate / post / since |
| 310–329 | `_MODE_TO_FILE`, `_DIAG_*` cache constants, `_diagnostics_cached` |
| 331–407 | `_atomic_write_json`, `_set_pregame`, `_force_vision_scan`, `_lcu_summary`, `_liveclient_summary`, `_build_state` (rough — verify) |
| 408–540 | `_build_state` continuation + `_sim_states` loader |
| ~540–640 | static-asset proxy constants (`_SUPERVISOR_PROXY_PATHS`), supervisor origin |
| 645–1255 | `class _Handler(BaseHTTPRequestHandler)` — ~610 lines remaining (down from 1276; -666 net via 2C-1) |
| 1257–1740 | `do_POST` body + remaining POST routes |
| 1745–1840 | `class _DualProtocolHTTPServer` |
| 1842–1892 | `start_dashboard()` |

Re-run `grep -n "def \|class " web_dashboard.py` at session start to refresh the actual line numbers — the table above is approximate.

## Slice 2C plan (recap, with progress)

Carve `_Handler` into focused route modules. Dispatcher infra is in place — each subsequent group is just (a) a new `dashboard/routes_<name>.py` + (b) deletion of the corresponding elif blocks in web_dashboard.

Status:
- ✅ **Group 1 — static** (12 GET routes, 0 POST): shipped in 26312de
- ⏳ **Group 2 — state** (`/api/state`, `/api/health`, `/api/health/all`, `/api/ui-version`, `/api/asset-stamp`, `/api/sim-state`)
- ⏳ **Group 3 — history/home** (`/api/home/summary`, `/api/session/summary`, `/api/history`, `/api/loadouts/all`)
- ⏳ **Group 4 — diag/vision** (`/api/diagnostics`, `/api/vision-state`, `/api/decisions`, `/api/ocr`, `/api/validate-ocr`, `/api/ocr-crop`, `/api/reload-regions`)
- ⏳ **Group 5 — coach + replay + cost** (`/api/cost`, `/api/coach/trace`, `/api/coach/state`, `/api/replay/matches`, `/api/replay/match/*`, `/api/recommend-champ`, `/api/logs`)
- ⏳ **Group 6 — bridge + champions + preview** (`/api/bridge` GET, `/api/preview-build`, `/api/champions`)
- ⏳ **Group 7 — POST commands** (`/api/input`, `/api/command`, `/api/decisions/*`, `/api/bridge` POST, `/api/console-error`, `/api/replay-coach`, `/api/speak`, `/api/champ-select-coach`, `/api/analyze`, `/api/experimental/*`, `/api/aram-analyze`, `/api/loadout/*`, `/api/lcu-cmd`, `/api/coach/toggle`)

Each group is one commit. Recommended order: 2 → 3 → 4 → 5 → 6 → 7.

## Pattern for the next group (example: state)

1. Create `dashboard/routes_state.py`. For each handler:
   - Lift the `elif self.path == "…":` body into a free function `def _serve_state(h): …` — replace `self` with `h`.
   - State variables that the original handler referenced via `global _STATE_CACHE_PAYLOAD, _STATE_CACHE_TS` need to either move into the new module, or stay in web_dashboard and be imported back. (For `/api/state`, easiest is to move the cache vars into the routes module.)
2. Add `GET_ROUTES = [(equals("/api/state"), _serve_state), …]` (use `equals` for exact paths, `prefix` for `/api/sim-state` style).
3. Wire into the dispatcher: edit `dashboard/_dispatch.py`'s `_gather_get`/`_gather_post` to also include `routes_state.GET_ROUTES`.
4. Delete the corresponding elif blocks from web_dashboard's `do_GET`/`do_POST`.
5. py_compile + smoke-import + matcher coverage check.
6. Commit.

## Subtleties to watch

- **`_global` caches inside route bodies**: `/api/state` uses `_STATE_CACHE_PAYLOAD/_TS`, `/api/champions` uses `_CHAMP_MAP_CACHE`, `/api/console-error` uses `_CE_LAST_TS/_CE_DROPPED`. These need to move with the route, or be imported back. Easiest: move them into the routes module — they're not used elsewhere.
- **Import-time vs request-time**: many handlers do `import urllib.request as _ur` *inside* the handler body. Keep that pattern when migrating — moving imports to module top-level changes startup cost characteristics (some of these modules are slow to import).
- **`self._send` / `self._proxy_to_supervisor` / `self.headers`**: still on `_Handler` — handlers receive `h` (the BaseHTTPRequestHandler instance) and call them via `h._send(...)`.
- **CSRF / body-parsing**: `do_POST` still does CSRF + body parsing at the entry, before dispatch. POST handlers receive the parsed dict as second arg.
- **Ordering matters within a group** (more-specific paths first). Cross-group ordering matters too — currently `_dispatch._gather_get` only includes `routes_static.GET_ROUTES`, but as you add `routes_state.GET_ROUTES` etc, append in the order that produces correct first-match wins. None of the current static routes overlap with API routes so this is mostly moot, but `/api/sim-state` would conflict with a hypothetical `/api/sim-state/foo` matcher in another module.

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:
1. `ops/runtime/health.json` shows new pid + `alive=true` + `last_reload_ok=true`.
2. `curl -k https://127.0.0.1:8888/` returns the dashboard HTML (now from `routes_static._serve_index`).
3. `curl -k https://127.0.0.1:8888/manifest.json` returns the manifest (from `routes_static._serve_manifest`).
4. `curl -k https://127.0.0.1:8888/icon.svg` returns the icon SVG.
5. `curl -k https://127.0.0.1:8888/api/home` and `/api/diagnostics` still work (slice 2B builders, untouched).
6. `curl -k https://127.0.0.1:8888/agent/gamepc_screen_agent.py` returns the agent script.

If any of those fail, the dashboard package wiring is broken — likely an import-order issue under `pythonw.exe`. Hard fallback: revert `26312de` (slice 2B at `5760b0c` was the last green build).

## Slice 2D (later)

Extract cert-generation + `_DualProtocolHTTPServer` into `dashboard/server.py`. Small, self-contained. After 2C is fully done.

## After #5

Tier 1 list complete after the full #5 (multi-session). Tier 2 priorities live in `git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` between #5 sub-slices. Each route group is its own focused task.
