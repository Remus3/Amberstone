# Wakeup Notes — 2026-05-01 (session 6 hand-off)

> Hand-off from session that shipped the first incremental slice of Tier 1 #5
> (split `web_dashboard.py`). Next session continues #5 with a second slice.

---

## What just shipped

| Commit | Summary |
|---|---|
| 6aca30e | Extract `_INDEX_HTML` (the `?ui=legacy` fallback HTML blob) from `web_dashboard.py` to `web/legacy_index.html`. Lazy-loaded + cached in a tiny `_legacy_index_html()` helper. **`web_dashboard.py`: 5799 → 2830 lines.** Verified the loader returns byte-identical content (sha256 `1fd93d33…`, 148,632 bytes) to what the original `_INDEX_HTML.encode('utf-8')` produced. The extracted file lives under `web/`, but is NOT under any of the public static prefixes (`/css/`, `/js/`, `/data/`), so it's not exposed by the asset server. Git's CRLF normalization on Windows checkouts will produce CRLF on disk; harmless for HTML/CSS/JS — browsers treat both line endings identically. |

## State at hand-off

- **8 unpushed commits** on `main` (was 7). User decides on push before 5/10 cloud routine.
- **RC still NOT restarted.** Three queued changes (#3 log-retention, #4 queue-compaction, #5 first slice) all activate together at next restart. The #5 slice is purely a refactor — once activated, the legacy fallback path serves the file from disk instead of the in-memory string. No user-visible difference.
- Restart timing is user's call. `echo restart > restart_trigger.txt`; verify via `ops/runtime/health.json`.
- Game-PC bridge still dead. Liveclient relay snapshots still stale.
- `RC-PatchRefresh` still showing residual `last_result=2147942402` — fixed at script level; clears on next scheduled run.

## Inventory of `web_dashboard.py` (2830 lines remaining)

A previous session's plan in WAKEUP_NOTES anticipated a `web/` Python package, but **`web/` is already in use as the static-asset directory** (index.html, css/, js/, data/). When this refactor needs a Python package, use `dashboard/` instead — don't mix Python under `web/`.

Rough section map (post-extract):

| Lines | Section |
|---|---|
| 1–43 | imports, constants, `_VISION_TOKEN`, `_APP_DIR` |
| 45–160 | `_champ_select_brief_via_coach` — single big helper |
| 161–271 | bridge log: `_BRIDGE_*` constants + `_bridge_hydrate_from_disk` / `_maybe_rotate` / `_post` / `_since` |
| 272–499 | `_SIM_STATES` — 228-line dict of sim/test fixtures |
| 500–547 | `_MODE_TO_FILE`, `_DIAG_*`, `_DB_CONN_LOCAL`, `_ro_conn` |
| 549–605 | `_diagnostics_cached`, `_compute_asset_hash`, `_inject_asset_hash` |
| 606–643 | `_read_json`, `_resolve_safe_icon` |
| 644–906 | home summary builders (`_build_home_summary`, `_home_tonight_pick`, `_home_last_build`, `_home_trends_14d`, `_home_streaks`) |
| 907–1005 | session helpers (`_load_match_rows`, `_ts_to_epoch`, `_group_sessions`, `_agg_session`) |
| 1006–1133 | builders (`_build_session_summary`, `_build_history`, `_build_loadouts_all`, `_build_diagnostics`) |
| 1135–1330 | `_atomic_write_json`, `_set_pregame`, `_force_vision_scan`, `_lcu_summary`, `_liveclient_summary`, `_build_state` |
| 1332–1340 | new `_legacy_index_html()` lazy loader |
| ~1342–1366 | `_MANIFEST`, `_ICON_SVG` |
| ~1370–1390 | `_SUPERVISOR_PROXY_PATHS`, `_SUPERVISOR_ORIGIN` |
| ~1390–2660 | `class _Handler(BaseHTTPRequestHandler)` — ~1270 lines, all routes |
| ~2660–2760 | `class _DualProtocolHTTPServer` — TLS+HTTP same-port server |
| ~2760–2830 | `start_dashboard()` entry point |

External import surface: only `start_dashboard` is imported externally (`main.py:142`). The other "web_dashboard" hits across the repo are doc comments referencing the module by name. So the public API is one symbol.

## Routes catalogue (~40 in `_Handler`)

GET — natural groups:
- **Static / HTML:** `/`, `/css/*`, `/js/*`, `/data/*`, `/manifest.json`, `/icon.svg`, `/icons/champions/*`, `/icons/maps/*`, `/icons/spells/*`, `/icons/runes/*`, `/icons/items/*`, `/agent/*`
- **Core state:** `/api/state`, `/api/sim-state`, `/api/health`, `/api/asset-stamp`, `/api/ui-version`, `/api/coach/state`, `/api/coach/trace`, `/api/health/all`, `/api/cost`
- **Vision / decisions:** `/api/vision-state`, `/api/decisions`, `/api/ocr`, `/api/validate-ocr`, `/api/ocr-crop`, `/api/reload-regions`
- **History / replay:** `/api/session/summary`, `/api/history`, `/api/replay/matches`, `/api/replay/match/*`, `/api/home/summary`, `/api/logs`
- **Loadouts / champ data:** `/api/loadouts/all`, `/api/preview-build`, `/api/champions`, `/api/recommend-champ`
- **Bridge:** `/api/bridge`
- **Diagnostics:** `/api/diagnostics`
- **Supervisor proxy:** all paths in `_SUPERVISOR_PROXY_PATHS` proxied to `:8890`

POST — natural groups:
- **Pregame / coach commands:** `/api/input`, `/api/command`, `/api/coach/toggle`, `/api/champ-select-coach`, `/api/replay-coach`, `/api/aram-analyze`, `/api/speak`
- **Decisions / experimental:** `/api/decisions/*`, `/api/experimental/get`, `/api/experimental/adapt`, `/api/experimental/mark`
- **LCU / loadouts:** `/api/lcu-cmd`, `/api/loadout/list`, `/api/loadout/apply`
- **Bridge / debug:** `/api/bridge`, `/api/console-error`, `/api/analyze`

## Next: Tier 1 #5 — second slice

The first slice was a static-asset extraction (mechanical, byte-exact). The remaining work is two flavours, in increasing order of risk:

**Slice 2A — small static blobs + sim fixtures (very low risk).** Move:
- `_MANIFEST` + `_ICON_SVG` → `web/manifest.json` + `web/icon.svg` (already served as those URLs; just stop synthesizing them in code).
- `_SIM_STATES` (228 lines, pure data) → `data/sim_states.json` or `dashboard/sim_states.py`. Currently consumed by `/api/sim-state` only. Loaded once at module import; no shared mutable state.

Buys ~250 more lines off `web_dashboard.py`. One commit.

**Slice 2B — pure-builder helpers (low risk, biggest line win).** Group at lines 644–1133 is a coherent block — home/session/history/loadouts/diagnostics builders. They share three helpers (`_ro_conn`, `_read_json`, `_resolve_safe_icon`) and the `_DB_CONN_LOCAL` thread-local. Move to `core/dashboard_builders.py` (or `dashboard/builders.py` if we're starting the package now). Importer-ergonomic shape: a small module that takes `app_dir: Path` once and exposes pure functions returning dicts.

Buys ~500 more lines off. One commit, possibly two if you separate home/ from session/.

**Slice 2C — start the `dashboard/` package + carve `_Handler` routes.** This is the "real" decomposition. Needs a shared `dashboard/_context.py` for the cache + per-thread sqlite conn + `_APP_DIR`. Then move route groups (static, state, vision, history, loadout, bridge, diagnostics) into `dashboard/routes_*.py`. Multiple commits, multiple sessions.

**Recommended order:** 2A in one short session, 2B in a focused session, then start 2C with a careful design pass. Don't try to do 2A+2B in one shot — keep each commit small and reversible.

## After #5

Tier 1 list complete after the full #5 (which will span multiple sessions). Tier 2 priorities live in `git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Scoped sessions per CLAUDE.md "Session workflow". `/clear` between Tier items, and `/clear` between #5 slices too — each slice is its own focused task.
