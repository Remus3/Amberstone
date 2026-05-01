# Wakeup Notes — 2026-05-01 (session 15 hand-off)

> Hand-off from session that shipped Slice 2C-7a (first POST sub-slice).
> Next session continues 7b — bridge POSTs.

---

## What just shipped

| Commit | Summary |
|---|---|
| (this) | **Slice 2C-7a**: input + command + console-error POST group. New POST handlers in `dashboard/routes_state.py` — `_serve_input_post`, `_serve_command_post`, `_serve_console_error_post` — wired into `routes_state.POST_ROUTES`. The `/api/console-error` throttle cache (`_CE_LAST_TS`, `_CE_DROPPED`) moved from `web_dashboard` module-level into `routes_state`; same migration pattern as `_CHAMP_MAP_CACHE` → `routes_bridge._CACHE` in 2C-6. The other handlers deferred-import `_set_pregame`, `_force_vision_scan`, `_atomic_write_json` from `web_dashboard` inside the handler body. `_dispatch._gather_post` already pulls them in (wired in 2C-6). web_dashboard.py: 1339 → 1261 (−78). routes_state.py: 174 → 269 (+95). Smoke-tested: 3 new POST routes total, each path matches exactly one handler; `/api/decisions/*` & `/api/replay-coach` still fall through to legacy elif chain; `_set_pregame`, `_force_vision_scan`, `_atomic_write_json` all still importable from `web_dashboard`; `_CE_LAST_TS` / `_CE_DROPPED` no longer attributes of `web_dashboard`. |
| 5851cab | Slice 2C-6: bridge + preview-build + champions group. 1417 → 1339 (−78). |
| (prev) | Slice 2C-5: coach + replay + cost group. 1559 → 1417 (−142). |
| (prev) | Slice 2C-4: diag/vision group. 1710 → 1559 (−151). |
| (prev) | Slice 2C-3: history/home group. 1757 → 1710 (−47). |
| 0805e2c | Slice 2C-2: state-group routes. 1892 → 1757 (−135). |
| 26312de | Slice 2C-1: dispatcher + 12 static-asset GET routes. 2103 → 1892 (−211). |
| 5760b0c | Slice 2B: dashboard/builders.py (13 builders + sqlite cache). 2612 → 2103 (−509). |

## State at hand-off

- **24 unpushed commits** on `main` (was 23 + this refactor; the wakeup-notes commit
  for 2C-7a will land alongside this file). User decides on push before 5/10
  cloud routine.
- **RC still NOT restarted.** Twelve queued changes (#3 log-retention, #4 queue-compaction, #5 first slice, slice 2A, slice 2B, slice 2C-1 through 2C-6, slice 2C-7a) all activate together at next restart. None is user-visible — all are internal refactor / housekeeping.
- Restart timing is user's call. `echo restart > restart_trigger.txt`; verify via `ops/runtime/health.json`.
- Game-PC bridge still dead. Liveclient relay snapshots still stale.
- `RC-PatchRefresh` still showing residual `last_result=2147942402` — fixed at script level; clears on next scheduled run.

## Inventory of `web_dashboard.py` (1261 lines)

Section map (post-2C-7a) — re-run `grep -n "def \|class " web_dashboard.py` at session start to refresh; table is approximate.

| Lines | Section |
|---|---|
| 1–73 | imports, constants, `_VISION_TOKEN`, `_APP_DIR`, dashboard package re-imports |
| ~80–~190 | `_champ_select_brief_via_coach` |
| ~200–~325 | bridge log: `_BRIDGE_*` constants + hydrate / rotate / post / since |
| ~325–~345 | `_diagnostics_cached`, `_MODE_TO_FILE`, `_DIAG_*` cache constants |
| ~345–~495 | `_atomic_write_json`, `_set_pregame`, `_force_vision_scan`, `_lcu_summary`, `_liveclient_summary` |
| ~495–~570 | `_build_state`, `_sim_states`, `_SUPERVISOR_PROXY_PATHS` |
| ~575–~650 | `class _Handler(BaseHTTPRequestHandler)` do_GET — one-liner over the dispatcher + supervisor-proxy fallback + 404 |
| ~700–~1100 | `do_POST` body + remaining POST routes (target of group 7b–d) |
| ~1100–~1210 | `class _DualProtocolHTTPServer` |
| ~1210+ | `start_dashboard()` |

## Remaining POST endpoints in legacy `do_POST` elif chain

Migrated in 2C-7a (gone): `/api/input`, `/api/command`, `/api/console-error`.

Still in legacy chain (target of 7b–d):
- `/api/decisions/<id>` — record decision choice
- `/api/bridge` — cross-Claude bridge POST
- `/api/replay-coach` — postgame match analysis
- `/api/speak` — TTS
- `/api/champ-select-coach` — live champ-select coaching
- `/api/analyze` — supervisor proxy POST
- `/api/experimental/get` / `/adapt` / `/mark` — experimental builder
- `/api/aram-analyze` — ARAM team analyzer
- `/api/loadout/list` — variant list (POST-style query)
- `/api/loadout/apply` — apply loadout (queues LCU commands via :8889)
- `/api/lcu-cmd` — forward to vision server LCU queue
- `/api/coach/toggle` — per-mode coach kill-switch

## Slice 2C plan (recap, with progress)

Status:
- ✅ **Group 1 — static** (12 GET routes): shipped in 26312de
- ✅ **Group 2 — state** (6 GET routes): shipped in 0805e2c
- ✅ **Group 3 — history/home** (4 GET routes): shipped (2C-3)
- ✅ **Group 4 — diag/vision** (7 GET routes): shipped (2C-4)
- ✅ **Group 5 — coach + replay + cost** (7 GET routes): shipped (2C-5)
- ✅ **Group 6 — bridge + preview-build + champions** (3 GET routes): shipped (2C-6)
- 🟡 **Group 7 — POST migration** (multi-slice — 7a done, 7b–d remain)

GET migration is complete. POST migration ~25% done by handler count.

## Pattern for the next sub-slice (7b: bridge POSTs)

`/api/bridge` (lines ~760–~782 of web_dashboard.py) is the obvious target.
The bridge GET migrated in 2C-6 to `routes_bridge.py` and deferred-imports
`_bridge_since` from `web_dashboard`. The POST equivalent will deferred-import
`_bridge_post` (and possibly `_bridge_maybe_rotate` if needed) the same way.

There's only one `/api/bridge` POST today; if it's the entire 7b slice,
that's a small one — consider folding `/api/decisions/<id>` into 7b too
since it's also small/self-contained and the wakeup-note's 7a definition
was loose. Alternatively keep 7b strictly to bridge and pull
decisions into 7c (coach group, since decision_detector lives in core
but is conceptually decision/coach state).

Recommended placement:
- `/api/bridge` POST → `routes_bridge.POST_ROUTES`
- `/api/decisions/<id>` POST → `routes_state.POST_ROUTES` (state mutation,
  no coach module — but `routes_coach` is fine if you'd rather keep
  decisions next to coach kill-switches)

## Subtleties to watch

- **Cross-module circular imports**: `routes_state` POST handlers in 7a use
  `from web_dashboard import …` *inside* the handler body — deferred
  import. Same workaround as `routes_diag` / `routes_bridge` GETs. Group
  7b–d will likely need it for `_bridge_post`, `_set_pregame`, etc.
- **`_global` caches inside route bodies**: `_CE_LAST_TS / _CE_DROPPED`
  migrated in 2C-7a (now `routes_state._CE_LAST_TS / _CE_DROPPED`). No
  more orphan caches in `web_dashboard.py` for the migrated handlers.
  Future POST handlers that move similar globals should follow this
  pattern: declare in the new module, remove from `web_dashboard`.
- **`self._send` / `self._proxy_to_supervisor` / `self.headers`**: still
  on `_Handler` — POST handlers receive `h` and call them via
  `h._send(...)`. The 7a console-error handler reads
  `h.headers.get("User-Agent", ...)` — `h.headers` is the BaseHTTPRequestHandler
  attribute, NOT something the dispatcher provides.
- **CSRF / body-parsing**: `do_POST` still does CSRF + body parsing at
  the entry, before dispatch. POST handlers receive the parsed dict
  as second arg — handler signature is `(h, payload)` (named `body`
  in `_dispatch.py` docstring; either is fine).
- **First `if` vs `elif` after migration**: the leading branch in the
  legacy chain after dispatch is now `/api/decisions/` (was `/api/input`).
  When 7b deletes `/api/bridge`'s elif, the chain reflows fine.
- **`/api/loadout/list`** uses `startswith` not `==` — when migrating,
  use `prefix("/api/loadout/list")` not `equals(...)`. Same for
  `/api/decisions/`.
- **Deferred-import gotcha**: `routes_state` POST handlers import
  `_set_pregame` etc. from `web_dashboard` *each request*. Don't refactor
  to top-level imports; that re-introduces the circular import.

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:
1. Items 1–21 from session-14 hand-off (state, health, history, diag,
   vision, decisions GET, OCR, ocr-crop, root, manifest, cost, coach
   trace, coach state GET, replay matches, logs, bridge GET,
   preview-build, champions) — all unchanged for 7a.
2. NEW: `curl -k -X POST -H 'Content-Type: application/json' -d '{"text":"smoke"}' https://127.0.0.1:8888/api/input` returns `{"ok":true}`; check `data/coaching_data.json` for `pregame: "smoke"`.
3. NEW: `curl -k -X POST -H 'Content-Type: application/json' -d '{"command":"clear_pregame"}' https://127.0.0.1:8888/api/command` clears the field.
4. NEW: `curl -k -X POST -H 'Content-Type: application/json' -d '{"kind":"smoke","message":"ignore"}' https://127.0.0.1:8888/api/console-error` returns `{"ok":true}`; today's log shows the smoke entry.

If any of those fail, the dispatcher wiring is broken. Hard fallback:
revert this commit; slice 2C-6 was the last green build.

## Slice 2D (later)

Extract cert-generation + `_DualProtocolHTTPServer` into `dashboard/server.py`.
Small, self-contained. After 2C is fully done.

## After #5

Tier 1 list complete after the full #5 (multi-session). Tier 2 priorities
live in `git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` between #5 sub-slices. Each
POST sub-slice (7b, 7c, 7d) is its own focused task.
