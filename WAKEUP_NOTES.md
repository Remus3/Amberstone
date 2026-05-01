# Wakeup Notes — 2026-05-01 (session 17 hand-off)

> Hand-off from session that shipped Slice 2C-7c (coach-flavored POSTs).
> Next session continues 7d — the catch-all (analyze proxy,
> experimental/{get,adapt,mark}, aram-analyze, loadout/{list,apply},
> lcu-cmd). 7d closes Group 7 and Slice 2C in one shot.

---

## What just shipped

| Commit | Summary |
|---|---|
| (this) | **Slice 2C-7c**: coach-flavored POSTs. Four handlers from `web_dashboard.do_POST` into `dashboard/routes_coach.py`: `/api/replay-coach`, `/api/speak`, `/api/champ-select-coach`, `/api/coach/toggle`. Every handler reaches `coaches.*` / `core.cost_tracker` directly — no deferred-imports from `web_dashboard` (unlike 7b's bridge POST which needed `_bridge_post`). API key reads now use `APP_DIR` already imported in routes_coach (no new imports). web_dashboard.py: 1215 → 1146 (−69). routes_coach.py: 190 → 272 (+82). Smoke-tested: 9 POST routes total, each new path matches exactly one handler; `/api/coach/state` and `/api/coach/trace` GETs are unshadowed (toggle uses `equals` not `prefix`); legacy elif chain reflowed — `/api/analyze` is now the leading `if`. |
| (prev) | Slice 2C-7b: bridge POST + decisions POST. 1261 → 1215 (−46). |
| (prev) | Slice 2C-7a: input + command + console-error POSTs. 1339 → 1261 (−78). |
| 5851cab | Slice 2C-6: bridge + preview-build + champions group. 1417 → 1339 (−78). |
| (prev) | Slice 2C-5: coach + replay + cost group. 1559 → 1417 (−142). |
| (prev) | Slice 2C-4: diag/vision group. 1710 → 1559 (−151). |
| (prev) | Slice 2C-3: history/home group. 1757 → 1710 (−47). |
| 0805e2c | Slice 2C-2: state-group routes. 1892 → 1757 (−135). |
| 26312de | Slice 2C-1: dispatcher + 12 static-asset GET routes. 2103 → 1892 (−211). |
| 5760b0c | Slice 2B: dashboard/builders.py (13 builders + sqlite cache). 2612 → 2103 (−509). |

## State at hand-off

- **27 unpushed commits** on `main` (was 25 + this refactor + the
  upcoming wakeup-notes commit). User decides on push before 5/10
  cloud routine.
- **RC still NOT restarted.** Fourteen queued changes (#3 log-retention,
  #4 queue-compaction, #5 first slice, slice 2A, slice 2B, slice 2C-1
  through 2C-7c) all activate together at next restart. None is
  user-visible — all are internal refactor / housekeeping.
- Restart timing is user's call. `echo restart > restart_trigger.txt`;
  verify via `ops/runtime/health.json`.
- Game-PC bridge still dead. Liveclient relay snapshots still stale.
- `RC-PatchRefresh` still showing residual `last_result=2147942402` —
  fixed at script level; clears on next scheduled run.

## Inventory of `web_dashboard.py` (1146 lines)

Section map (post-2C-7c) — re-run `grep -n "def \|class " web_dashboard.py`
at session start to refresh; table is approximate.

| Lines | Section |
|---|---|
| 1–73 | imports, constants, `_VISION_TOKEN`, `_APP_DIR`, dashboard package re-imports |
| ~80–~190 | `_champ_select_brief_via_coach` |
| ~200–~325 | bridge log: `_BRIDGE_*` constants + hydrate / rotate / post / since |
| ~325–~345 | `_diagnostics_cached`, `_MODE_TO_FILE`, `_DIAG_*` cache constants |
| ~345–~495 | `_atomic_write_json`, `_set_pregame`, `_force_vision_scan`, `_lcu_summary`, `_liveclient_summary` |
| ~495–~570 | `_build_state`, `_sim_states`, `_SUPERVISOR_PROXY_PATHS` |
| ~575–~650 | `_Handler.do_GET` — one-liner over the dispatcher + supervisor-proxy fallback + 404 |
| ~700–~985 | `do_POST` body + remaining POST routes (target of group 7d) |
| ~985–~1095 | `_DualProtocolHTTPServer` |
| ~1095+ | `start_dashboard()` |

## Remaining POST endpoints in legacy `do_POST` elif chain

Migrated in 2C-7a (gone): `/api/input`, `/api/command`, `/api/console-error`.
Migrated in 2C-7b (gone): `/api/bridge`, `/api/decisions/<id>`.
Migrated in 2C-7c (gone): `/api/replay-coach`, `/api/speak`, `/api/champ-select-coach`, `/api/coach/toggle`.

Still in legacy chain (target of 7d — final POST sub-slice):
- `/api/analyze` — supervisor proxy POST (forwards to :8890)
- `/api/experimental/get` / `/adapt` / `/mark` — experimental builder
- `/api/aram-analyze` — ARAM team analyzer
- `/api/loadout/list` — variant list (POST-style query; legacy uses `startswith`)
- `/api/loadout/apply` — apply loadout (queues LCU commands via :8889)
- `/api/lcu-cmd` — forward to vision server LCU queue

## Slice 2C plan (recap, with progress)

Status:
- ✅ **Group 1 — static** (12 GET routes): shipped in 26312de
- ✅ **Group 2 — state** (6 GET routes): shipped in 0805e2c
- ✅ **Group 3 — history/home** (4 GET routes): shipped (2C-3)
- ✅ **Group 4 — diag/vision** (7 GET routes): shipped (2C-4)
- ✅ **Group 5 — coach + replay + cost** (7 GET routes): shipped (2C-5)
- ✅ **Group 6 — bridge + preview-build + champions** (3 GET routes): shipped (2C-6)
- 🟡 **Group 7 — POST migration** (multi-slice — 7a + 7b + 7c done, 7d remains)

GET migration is complete. POST migration ~69% done by handler count
(9 of 13 remaining endpoints migrated; experimental/* counts as 3).

## Pattern for the next sub-slice (7d: catch-all POSTs)

7d is the finisher: it absorbs every legacy POST elif left after 7c.
Suggested grouping:

| Path | Suggested module | Notes |
|---|---|---|
| `/api/analyze` | `routes_state.POST_ROUTES` | supervisor proxy; pure HTTP forward to `:8890`. Self-contained. |
| `/api/experimental/get`     | new `routes_experimental.py` (or routes_coach) | reaches `coaches.experimental_builder` |
| `/api/experimental/adapt`   | same module as `/get` | same import |
| `/api/experimental/mark`    | same module as `/get` | same import |
| `/api/aram-analyze`         | new `routes_experimental.py` (or routes_coach) | reaches `coaches.aram_team_analyzer` + `coaches.loadout_resolver` |
| `/api/loadout/list`         | new `routes_loadout.py` (or routes_coach) | reaches `coaches.loadout_resolver`. **Legacy uses `startswith` — use `prefix("/api/loadout/list")`** to preserve current matching. |
| `/api/loadout/apply`        | same module as `list` | reaches `coaches.loadout_resolver` + needs `_VISION_TOKEN` (deferred-import from web_dashboard, same pattern as routes_diag). |
| `/api/lcu-cmd`              | same module as loadout (or routes_state) | needs `_VISION_TOKEN` (same deferred-import) and the `_LCU_ALLOWED_CMDS` allowlist. The allowlist is local to the legacy handler — move it to module scope in the new module. |

**Recommendation**: avoid creating two new modules. The cleanest split is:
- A new `dashboard/routes_loadout.py` for `/api/loadout/list`, `/api/loadout/apply`, `/api/lcu-cmd` (all need `_VISION_TOKEN` and queue commands through the vision server's LCU agent). This module is the only one carrying that import dependency.
- Park the rest in existing modules: `/api/analyze` → `routes_state`; `/api/experimental/*` + `/api/aram-analyze` → `routes_coach` (already houses coach + replay handlers, fits semantically).

That avoids `routes_experimental.py` being created for 4 handlers that
mostly duplicate `routes_coach`'s import surface. If 7d's diff feels
too big in one commit, split as `7d-1` (analyze + experimental + aram-analyze
→ existing modules) and `7d-2` (loadout/* + lcu-cmd → new routes_loadout).

## Subtleties to watch (mostly unchanged from 7b/7c)

- **Cross-module circular imports**: `_VISION_TOKEN` lives in
  `web_dashboard`. Use `from web_dashboard import _VISION_TOKEN`
  *inside* the handler body (deferred). Don't lift to module scope
  — the dashboard package gets imported during `web_dashboard`
  start-up, which would re-introduce the cycle. Same pattern is
  already in `routes_diag` for `_VISION_TOKEN` use.
- **Prefix vs equals for path-style endpoints**:
  - `/api/loadout/list` legacy uses `startswith("/api/loadout/list")`
    → `prefix("/api/loadout/list")` to match.
  - `/api/loadout/apply` and `/api/lcu-cmd` are exact equals.
  - `/api/analyze` and `/api/experimental/*` are exact equals.
- **`_LCU_ALLOWED_CMDS` allowlist**: lives inside the legacy
  `/api/lcu-cmd` elif body. When migrating, hoist it to module scope
  so it's allocated once, not per-request.
- **Supervisor proxy timeout**: `/api/analyze` uses `timeout=30` for
  the urlopen, not the default 4. Keep that — analysis runs are
  multi-second.
- **`payload.get("body")` shadowing**: still applies if any 7d
  handler reaches for `payload["body"]`. None of them currently does,
  but worth noting if scope expands.
- **Deferred-import gotcha**: same as 7b — don't refactor deferred
  imports to top-level imports.

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:
1. All items 1-21 from prior sessions + items 1-3 from session 15
   + bridge round-trip + decisions POST 404 from session 16 — all
   unchanged.
2. NEW (7c): replay-coach POST against a known match id:
   ```
   curl -k -X POST -H 'Content-Type: application/json' \
     -d '{"match_id":"NA1_5438342899"}' \
     https://127.0.0.1:8888/api/replay-coach
   ```
   returns analysis JSON. (Use any real match id from
   `data/rewind_history.db`; the exact id doesn't matter.)
3. NEW (7c): coach toggle round-trip:
   ```
   curl -k -X POST -H 'Content-Type: application/json' \
     -d '{"mode":"aram","disabled":true}' \
     https://127.0.0.1:8888/api/coach/toggle
   ```
   returns `{"ok":true,"disabled_modes":[…,"aram"]}`. Then GET
   `https://127.0.0.1:8888/api/coach/state` shows aram disabled.
   Re-POST with `disabled:false` to restore.
4. NEW (7c): champ-select-coach POST with a stub body:
   ```
   curl -k -X POST -H 'Content-Type: application/json' \
     -d '{"my_champion":"Vayne","my_team":["Vayne"],"their_team":[]}' \
     https://127.0.0.1:8888/api/champ-select-coach
   ```
   returns Haiku coaching JSON (or an error if API key missing —
   that's fine; confirms the route is wired).

If any of those fail, the dispatcher wiring is broken. Hard fallback:
revert this commit; slice 2C-7b was the last green build.

## Slice 2D (later)

Extract cert-generation + `_DualProtocolHTTPServer` into
`dashboard/server.py`. Small, self-contained. After 2C-7d closes Group 7.

## After #5

Tier 1 list complete after the full #5 (multi-session). Tier 2 priorities
live in `git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` between #5 sub-slices. 7d
is its own focused task. After 7d ships, `do_POST` collapses to just
the body-parsing + dispatcher + 404 (~30 lines).
