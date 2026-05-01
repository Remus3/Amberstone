# Wakeup Notes — 2026-05-01 (session 7 hand-off)

> Hand-off from session that shipped Slice 2A of Tier 1 #5
> (split `web_dashboard.py`). Next session continues with Slice 2B.

---

## What just shipped

| Commit | Summary |
|---|---|
| 3984fba | Extract `_SIM_STATES` (228-line `aram_blitz` fixture) → `data/sim_states.json`, `_MANIFEST` → `web/manifest.json`, `_ICON_SVG` → `web/icon.svg`. Each gets a tiny `_X_bytes()` / `_sim_states()` lazy loader grouped with `_legacy_index_html()`. **`web_dashboard.py`: 2830 → 2612 lines.** Verified: manifest sha256 `8840117e…` (289 B), icon sha256 `32d58d04…` (370 B), sim `aram_blitz` route bytes sha256 `05c247b7…` (8568 B) all unchanged. The route output is byte-identical because `/api/sim-state` still calls `json.dumps(state).encode()` — only the in-memory source changed. |
| 6aca30e | (prev session) Extract `_INDEX_HTML` → `web/legacy_index.html`. 5799 → 2830 lines. |

## State at hand-off

- **9 unpushed commits** on `main` (was 8). User decides on push before 5/10 cloud routine.
- **RC still NOT restarted.** Four queued changes (#3 log-retention, #4 queue-compaction, #5 first slice, #5 slice 2A) all activate together at next restart. None is user-visible — all are internal refactor / housekeeping.
- Restart timing is user's call. `echo restart > restart_trigger.txt`; verify via `ops/runtime/health.json`.
- Game-PC bridge still dead. Liveclient relay snapshots still stale.
- `RC-PatchRefresh` still showing residual `last_result=2147942402` — fixed at script level; clears on next scheduled run.
- Reminder: `data/sim_states.json` is now reachable via `/data/sim_states.json` (the static asset handler exposes the entire `/data/` prefix). Harmless — LAN-only, fixture data — but worth keeping in mind if anything secret ever lands under `data/`.

## Inventory of `web_dashboard.py` (2612 lines remaining)

Section map (post-2A; line numbers approximate after the snip):

| Lines | Section |
|---|---|
| 1–43 | imports, constants, `_VISION_TOKEN`, `_APP_DIR` |
| 45–160 | `_champ_select_brief_via_coach` — single big helper |
| 161–271 | bridge log: `_BRIDGE_*` constants + `_bridge_hydrate_from_disk` / `_maybe_rotate` / `_post` / `_since` |
| 272–320 | `_MODE_TO_FILE`, `_DIAG_*`, `_DB_CONN_LOCAL`, `_ro_conn` *(was 500–547 pre-snip)* |
| 320–380 | `_diagnostics_cached`, `_compute_asset_hash`, `_inject_asset_hash` |
| 380–420 | `_read_json`, `_resolve_safe_icon` |
| 420–680 | home summary builders (`_build_home_summary`, `_home_tonight_pick`, `_home_last_build`, `_home_trends_14d`, `_home_streaks`) |
| 680–780 | session helpers (`_load_match_rows`, `_ts_to_epoch`, `_group_sessions`, `_agg_session`) |
| 780–910 | builders (`_build_session_summary`, `_build_history`, `_build_loadouts_all`, `_build_diagnostics`) |
| 910–1110 | `_atomic_write_json`, `_set_pregame`, `_force_vision_scan`, `_lcu_summary`, `_liveclient_summary`, `_build_state` |
| 1110–1150 | static-asset lazy loaders: `_legacy_index_html`, `_manifest_bytes`, `_icon_svg_bytes`, `_sim_states` (new in 2A) |
| 1150–1170 | `_SUPERVISOR_PROXY_PATHS`, `_SUPERVISOR_ORIGIN` |
| 1170–2440 | `class _Handler(BaseHTTPRequestHandler)` — ~1270 lines, all routes |
| 2440–2540 | `class _DualProtocolHTTPServer` — TLS+HTTP same-port server |
| 2540–2612 | `start_dashboard()` entry point |

External import surface unchanged — only `start_dashboard` is consumed externally (`main.py:142`).

## Next: Tier 1 #5 — Slice 2B (pure-builder helpers)

The biggest line win available without touching the route handler.
The cohesive block at ~lines 420–910 is home/session/history/loadouts/diagnostics builders. They share three helpers (`_ro_conn`, `_read_json`, `_resolve_safe_icon`) and the `_DB_CONN_LOCAL` thread-local.

**Recommended target:** new `dashboard/builders.py` (start the package now, since 2C will need it anyway), or `core/dashboard_builders.py` if you'd rather defer the package decision. Importer-ergonomic shape: a small module that takes `app_dir: Path` once at construction and exposes pure functions returning dicts.

**Important — `web/` is the static-asset directory.** A previous plan suggested a `web/` Python package; **don't** mix Python under `web/`. Use `dashboard/` for any new package.

Buys ~500 more lines off `web_dashboard.py`. One commit, possibly two if you split home/ from session/.

## Slice 2C (later — the "real" decomposition)

Carve `_Handler` routes into `dashboard/routes_*.py` modules. Needs a shared `dashboard/_context.py` for the cache + per-thread sqlite conn + `_APP_DIR`. Multiple commits, multiple sessions. Defer until 2B is in.

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:
1. `ops/runtime/health.json` shows new pid + `alive=true` + `last_reload_ok=true`.
2. `curl -k https://127.0.0.1:8888/manifest.json` returns the manifest (now from disk).
3. `curl -k https://127.0.0.1:8888/icon.svg` returns the SVG (now from disk).
4. `curl -k 'https://127.0.0.1:8888/api/sim-state?scenario=aram_blitz'` returns the fixture (now lazy-loaded from `data/sim_states.json`).

If any of those fail, the lazy-load path is broken — likely a path resolution issue under `pythonw.exe` cwd. Hard fallback: revert `3984fba`.

## After #5

Tier 1 list complete after the full #5 (which will span multiple sessions). Tier 2 priorities live in `git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Scoped sessions per CLAUDE.md "Session workflow". `/clear` between Tier items, and `/clear` between #5 slices too — each slice is its own focused task.
