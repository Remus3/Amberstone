# Wakeup Notes — 2026-05-01 (session 16 hand-off)

> Hand-off from session that shipped Slice 2C-7b (bridge + decisions POSTs).
> Next session continues 7c — coach-flavored POSTs (replay-coach, speak,
> champ-select-coach, coach/toggle).

---

## What just shipped

| Commit | Summary |
|---|---|
| (this) | **Slice 2C-7b**: bridge POST + decisions POST. New POST handler `_serve_bridge_post` in `dashboard/routes_bridge.py` (deferred-imports `_bridge_post` from `web_dashboard`); new POST handler `_serve_decision_choice_post` in `dashboard/routes_diag.py` (direct-imports `core.decision_detector.get_loop`, no web_dashboard helper needed). Decisions POST is co-located with the GET partner already living in `routes_diag.py` — overrides the wakeup-note 7a suggestion of routes_state, since co-location with the GET is cleaner. Decisions POST uses `prefix("/api/decisions/")` (trailing slash matters: it must NOT match the bare `/api/decisions` GET, only `/api/decisions/<id>`). web_dashboard.py: 1261 → 1215 (−46). routes_bridge.py: 131 → 161 (+30). routes_diag.py: 215 → 248 (+33). Smoke-tested: 5 POST routes total, each path matches exactly one handler; `/api/decisions` (no id) does NOT match the POST chain so the GET handler is unshadowed; `/api/replay-coach` still falls through to legacy elif chain; `_bridge_post` still importable from `web_dashboard`. |
| (prev) | Slice 2C-7a: input + command + console-error POST group. 1339 → 1261 (−78). |
| 5851cab | Slice 2C-6: bridge + preview-build + champions group. 1417 → 1339 (−78). |
| (prev) | Slice 2C-5: coach + replay + cost group. 1559 → 1417 (−142). |
| (prev) | Slice 2C-4: diag/vision group. 1710 → 1559 (−151). |
| (prev) | Slice 2C-3: history/home group. 1757 → 1710 (−47). |
| 0805e2c | Slice 2C-2: state-group routes. 1892 → 1757 (−135). |
| 26312de | Slice 2C-1: dispatcher + 12 static-asset GET routes. 2103 → 1892 (−211). |
| 5760b0c | Slice 2B: dashboard/builders.py (13 builders + sqlite cache). 2612 → 2103 (−509). |

## State at hand-off

- **25 unpushed commits** on `main` (was 24 + this refactor + the
  wakeup-notes commit). User decides on push before 5/10 cloud routine.
- **RC still NOT restarted.** Thirteen queued changes (#3 log-retention,
  #4 queue-compaction, #5 first slice, slice 2A, slice 2B, slice 2C-1
  through 2C-7b) all activate together at next restart. None is
  user-visible — all are internal refactor / housekeeping.
- Restart timing is user's call. `echo restart > restart_trigger.txt`;
  verify via `ops/runtime/health.json`.
- Game-PC bridge still dead. Liveclient relay snapshots still stale.
- `RC-PatchRefresh` still showing residual `last_result=2147942402` —
  fixed at script level; clears on next scheduled run.

## Inventory of `web_dashboard.py` (1215 lines)

Section map (post-2C-7b) — re-run `grep -n "def \|class " web_dashboard.py`
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
| ~700–~1055 | `do_POST` body + remaining POST routes (target of group 7c–d) |
| ~1055–~1165 | `_DualProtocolHTTPServer` |
| ~1165+ | `start_dashboard()` |

## Remaining POST endpoints in legacy `do_POST` elif chain

Migrated in 2C-7a (gone): `/api/input`, `/api/command`, `/api/console-error`.
Migrated in 2C-7b (gone): `/api/bridge`, `/api/decisions/<id>`.

Still in legacy chain (target of 7c–d):
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
- 🟡 **Group 7 — POST migration** (multi-slice — 7a + 7b done, 7c–d remain)

GET migration is complete. POST migration ~38% done by handler count
(5 of 13 remaining endpoints migrated; experimental/* counts as 3).

## Pattern for the next sub-slice (7c: coach POSTs)

Recommended grouping for 7c — the four "coach-flavored" POSTs:
- `/api/replay-coach`  → `routes_coach.POST_ROUTES` (postgame match analysis)
- `/api/speak`         → `routes_coach.POST_ROUTES` (voice TTS)
- `/api/champ-select-coach` → `routes_coach.POST_ROUTES` (live haiku coaching)
- `/api/coach/toggle`  → `routes_coach.POST_ROUTES` (per-mode kill-switch)

All four reach `coaches.*` modules directly and don't need any
`web_dashboard` helper deferred-imports — even cleaner than 7b. The
bridge post in 7b was the only handler that *needed* a web_dashboard
helper (`_bridge_post`); the rest of the migration should be
helper-free.

That leaves 7d for the catch-all (`/api/analyze` supervisor proxy,
experimental/{get,adapt,mark}, aram-analyze, loadout/{list,apply},
lcu-cmd) — heterogeneous but all mutate / proxy state. They'd land
naturally in `routes_state.POST_ROUTES` or a new `routes_supervisor`
module if the count gets unwieldy.

## Subtleties to watch

- **Cross-module circular imports**: 2C-7b's `_serve_bridge_post` uses
  `from web_dashboard import _bridge_post` *inside* the handler body
  (deferred). Only do this when the handler genuinely needs a helper
  that lives in `web_dashboard`. 7c handlers should NOT need this —
  they import from `coaches.*` directly.
- **Prefix vs equals for path-id endpoints**: `/api/decisions/<id>`
  uses `prefix("/api/decisions/")` (trailing slash required so it
  doesn't shadow the GET on bare `/api/decisions`). When migrating
  `/api/loadout/list` (legacy uses `startswith` — see 2C plan), use
  `prefix("/api/loadout/list")`.
- **`self._send` / `self.headers`**: still on `_Handler` — POST handlers
  receive `h` and call `h._send(...)`, `h.headers.get(...)`,
  `h.path` etc. Standard pattern.
- **CSRF / body-parsing**: `do_POST` still does CSRF + body parsing at
  the entry, before dispatch. Handlers receive the parsed dict as
  second arg. Signature is `(h, payload)`.
- **`payload.get("body")` shadowing the outer `body` variable**: the
  legacy `/api/bridge` POST elif used `body = payload.get("body")`,
  which silently shadowed the `body` bytes from the rfile.read above.
  In 7b's migrated handler I renamed it `msg_body` to avoid the foot-gun
  if the function is ever extended. Same renaming may be useful in 7c
  if any handler reaches for `payload["body"]`.
- **First branch in legacy chain after 7b**: `/api/replay-coach` is now
  the leading `if` (was `/api/decisions`). When 7c removes
  `/api/replay-coach`, the chain reflows fine.
- **Deferred-import gotcha**: Don't refactor deferred imports to
  top-level imports; that re-introduces the circular import (web_dashboard
  imports the dashboard package at start-up).

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:
1. All items 1-21 from prior sessions + items 1-3 from session 15
   (input/command/console-error POSTs) — all unchanged.
2. NEW: bridge POST round-trip:
   ```
   curl -k -X POST -H 'Content-Type: application/json' \
     -d '{"source":"smoke","summary":"7b verify","kind":"note"}' \
     https://127.0.0.1:8888/api/bridge
   ```
   returns `{"ok":true,"ts":...,"id":...,"kind":"note"}`; then
   `curl -k 'https://127.0.0.1:8888/api/bridge?since=0&limit=5'`
   shows the entry in `messages`.
3. NEW: decision POST returns 404 for an unknown id (correct — there's
   no pending decision in a quiet RC):
   ```
   curl -k -X POST -H 'Content-Type: application/json' \
     -d '{"choice":"skip"}' \
     https://127.0.0.1:8888/api/decisions/nonexistent
   ```
   returns `{"error":"id not pending"}` with HTTP 404. Confirms the
   route is wired AND that the GET on bare `/api/decisions` still
   works (run `curl -k https://127.0.0.1:8888/api/decisions` →
   `{"pending":[]}`).

If any of those fail, the dispatcher wiring is broken. Hard fallback:
revert this commit; slice 2C-7a was the last green build.

## Slice 2D (later)

Extract cert-generation + `_DualProtocolHTTPServer` into
`dashboard/server.py`. Small, self-contained. After 2C is fully done.

## After #5

Tier 1 list complete after the full #5 (multi-session). Tier 2 priorities
live in `git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` between #5 sub-slices. Each
POST sub-slice (7c, 7d) is its own focused task.
