# Wakeup Notes — 2026-05-01 (session 8 hand-off)

> Hand-off from session that shipped Slice 2B of Tier 1 #5
> (split `web_dashboard.py`). Next session continues with Slice 2C.

---

## What just shipped

| Commit | Summary |
|---|---|
| 07e8f77 | Extract 13 pure-builder helpers + their shared sqlite cache out of `web_dashboard.py` into a new `dashboard/` package. New files: `dashboard/__init__.py`, `dashboard/_context.py` (APP_DIR + `ro_conn` + `read_json` + `DB_CONN_LOCAL`), `dashboard/builders.py` (the 13 builders + `SESSION_GAP_S`). Function bodies byte-identical to originals; `web_dashboard.py` re-imports each one under its original underscored name. **`web_dashboard.py`: 2612 → 2103 lines (-509).** Smoke-tested: builders return live data, `_diagnostics_cached()` still works, `DB_CONN_LOCAL` is a shared singleton across both modules. |
| 3984fba | (prev session) Extract `_SIM_STATES` / `_MANIFEST` / `_ICON_SVG`. 2830 → 2612 lines. |
| 6aca30e | (older) Extract `_INDEX_HTML` blob. 5799 → 2830 lines. |

## State at hand-off

- **14 unpushed commits** on `main` (was 12). User decides on push before 5/10 cloud routine.
- **RC still NOT restarted.** Five queued changes (#3 log-retention, #4 queue-compaction, #5 first slice, #5 slice 2A, #5 slice 2B) all activate together at next restart. None is user-visible — all are internal refactor / housekeeping.
- Restart timing is user's call. `echo restart > restart_trigger.txt`; verify via `ops/runtime/health.json`.
- Game-PC bridge still dead. Liveclient relay snapshots still stale.
- `RC-PatchRefresh` still showing residual `last_result=2147942402` — fixed at script level; clears on next scheduled run.

## Inventory of `web_dashboard.py` (2103 lines remaining)

Section map (post-2B):

| Lines | Section |
|---|---|
| 1–70 | imports, constants, `_VISION_TOKEN`, `_APP_DIR`, **dashboard package re-imports** |
| 72–187 | `_champ_select_brief_via_coach` |
| 188–298 | bridge log: `_BRIDGE_*` constants + hydrate / rotate / post / since |
| 300–319 | `_MODE_TO_FILE`, `_DIAG_*` cache constants |
| 321–337 | `_diagnostics_cached` |
| 340–376 | `_compute_asset_hash`, `_inject_asset_hash` |
| 378–397 | `_resolve_safe_icon` *(stays — only used by icon routes)* |
| 400–425 | `_atomic_write_json`, `_set_pregame`, `_force_vision_scan` |
| 426–600 | `_lcu_summary`, `_liveclient_summary`, `_build_state` |
| 601–660 | static-asset lazy loaders (`_legacy_index_html`, `_manifest_bytes`, `_icon_svg_bytes`, `_sim_states`) |
| 662–667 | `_SUPERVISOR_PROXY_PATHS`, `_SUPERVISOR_ORIGIN` |
| 668–1944 | `class _Handler(BaseHTTPRequestHandler)` — ~1276 lines, all routes (the big remaining target) |
| 1946–2048 | `class _DualProtocolHTTPServer` — TLS+HTTP same-port server |
| 2050–2103 | `start_dashboard()` entry point |

External import surface unchanged — only `start_dashboard` is consumed externally (`main.py:142`).

## `dashboard/` package shape (locked in 2B)

```
dashboard/
  __init__.py       package marker
  _context.py       APP_DIR + ro_conn + read_json + DB_CONN_LOCAL
                    (web_dashboard.py and dashboard.builders share this)
  builders.py       13 builders + SESSION_GAP_S
                    (re-imported into web_dashboard.py with underscored aliases)
```

Slice 2C should add `dashboard/routes_*.py` modules that import from `_context`.

## Next: Tier 1 #5 — Slice 2C (the "real" decomposition)

Carve `_Handler` (lines 668–1944, ~1276 lines) into focused route modules. The class is a single mega-class with one method per HTTP path; each method is small and largely independent.

**Recommended grouping** (based on a quick scan of routes — confirm before splitting):
- `dashboard/routes_state.py` — `/api/state`, `/api/health`, `/api/ui-version`
- `dashboard/routes_history.py` — `/api/home`, `/api/session`, `/api/history`, `/api/loadouts`
- `dashboard/routes_diag.py` — `/api/diagnostics`, `/api/vision-state`, `/api/ocr*`
- `dashboard/routes_ingame.py` — champ-select brief, build chooser, vision endpoints
- `dashboard/routes_static.py` — `/`, `/manifest.json`, `/icon.svg`, `/icons/*`, `/data/*`, `/web/*`
- `dashboard/routes_command.py` — POST `/api/input`, `/api/command`
- `dashboard/routes_bridge.py` — bridge log endpoints
- `dashboard/routes_supervisor.py` — `/api/analyze` proxy + Phase 3 supervisor proxies

Approach (recommended):
1. Make `_Handler` a thin dispatcher: a `do_GET`/`do_POST` that walks an ordered list of `(matcher, handler)` pairs imported from each routes module. Each route handler is a free function `(handler_self, parsed_url, body) -> None`.
2. Move routes one group at a time. Each group is one commit.
3. Keep response bytes byte-identical — diff `/api/state` etc. before/after if possible.

Buys ~1000+ lines off `web_dashboard.py`. Multiple commits, possibly 2-3 sessions.

## Slice 2D (later, optional)

Extract the cert-generation + `_DualProtocolHTTPServer` into `dashboard/server.py`. Small, self-contained. Save for after 2C.

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:
1. `ops/runtime/health.json` shows new pid + `alive=true` + `last_reload_ok=true`.
2. `curl -k https://127.0.0.1:8888/api/home` returns the home summary (now from `dashboard/builders.py`).
3. `curl -k https://127.0.0.1:8888/api/diagnostics` returns the cached diagnostics blob.
4. `curl -k 'https://127.0.0.1:8888/api/history?scope=14d'` returns the 14-day session list.
5. `curl -k 'https://127.0.0.1:8888/api/sim-state?scenario=aram_blitz'` still returns the fixture (slice 2A check).

If any of those fail, the dashboard package import is broken — likely a path resolution issue under `pythonw.exe` cwd. Hard fallback: revert `07e8f77` (and `3984fba` if needed).

## After #5

Tier 1 list complete after the full #5 (which will span multiple sessions). Tier 2 priorities live in `git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Scoped sessions per CLAUDE.md "Session workflow". `/clear` between Tier items, and `/clear` between #5 slices too — each slice is its own focused task.
