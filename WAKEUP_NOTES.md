# Wakeup Notes — 2026-05-01 (session 25 hand-off)

> Hand-off from session that shipped **Tier 2 #5 + #6** in one sitting.
> `dashboard/_state_builder.py` owns `MODE_TO_FILE`, `build_state`,
> `sim_states`. `dashboard/_champ_select.py` owns the Haiku champ-select
> brief generator + cache. `web_dashboard.py` is down to **332 lines**.
> Next focus: judgment call on whether to extract `_Handler` (and its
> proxy paths) into `dashboard/_handler.py`, or to declare the
> helper-shake done and move on to other Tier 2 priorities.

---

## What just shipped

| Commit | Summary |
|---|---|
| 6d89a62 | **Tier 2 #6**: champ-select brief generator → `dashboard/_champ_select.py`. The Haiku-backed build + runes + ally-notes helper (95L) and its 10-min LRU cache move out of `web_dashboard.py`. `dashboard/routes_bridge.py` switches from deferred `from web_dashboard import _champ_select_brief_via_coach` to module-scope `from dashboard._champ_select import brief_via_coach`. Sources `APP_DIR` from `dashboard._context` directly. Drops the now-unused `import time` from web_dashboard.py. web_dashboard.py: 423 → 332 (−91). dashboard/_champ_select.py: 126 (new). Smoke-tested with a live Haiku call (`brief_via_coach('Jinx', ['Yasuo'], ['Lulu'], 'adc', 'ARAM')` returned a real brief — build len=7, runes dict, ally_notes 125 chars). |
| 778971d | **Tier 2 #5**: state builder → `dashboard/_state_builder.py`. 477 → 423 (−54). |
| 3ac388e | Tier 2 #4: liveclient + LCU → `dashboard/_liveclient.py`. 590 → 477 (−113). |
| 3e20b11 | Tier 2 #3: writers → `dashboard/_writers.py`. 606 → 590 (−16). |
| 8defac7 | Tier 2 #2: diagnostics cache → `dashboard/_diagnostics.py`. 621 → 606 (−15). |
| 4317d15 | Tier 2 #1: bridge log → `dashboard/_bridge_log.py`. 741 → 621 (−120). |

**Cumulative since slice 2B start: 2612 → 332 in `web_dashboard.py` (−2280 lines).**

## State at hand-off

- **47 unpushed commits** on `main`. Origin push still pending —
  user's call before the 2026-05-10 cloud routine.
- **RC still NOT restarted.** Twenty-one+ queued changes (#3
  log-retention, #4 queue-compaction, slices 1–2D + Tier 2 #1–#6) all
  activate together at next restart. None is user-visible — all
  internal refactor.
- Restart timing is user's call. `echo restart > restart_trigger.txt`;
  verify via `ops/runtime/health.json`.
- Game-PC bridge still dead-ish — `lcu_summary()` returned `{}` this
  session (relay status appears to have changed since #4 hand-off).
  Liveclient relay still empty (no game in progress). Bridge auto-flow
  loop on Game-PC may still be down.
- `RC-PatchRefresh` still showing residual `last_result=2147942402` —
  fixed at script level in `project_rc_patchrefresh_fixed`; clears on
  next scheduled run.
- `web_dashboard._APP_DIR` is now defined but unread inside the file
  (the last reader, `_champ_select_brief_via_coach`, moved out and
  switched to `dashboard._context.APP_DIR`). The
  `start_dashboard()` mutation in `dashboard/server.py` is still there
  for backward compat with any external caller, but is now a no-op
  for in-process consumers.
- Untracked / unstaged that this session deliberately left alone:
  `config/coach_settings.json` (`disabled_coaches: []` field added —
  unrelated runtime config drift), `tools/claude-rc.ps1` (untracked).

## Inventory of `web_dashboard.py` (332 lines)

Re-run `grep -n "def \|class " web_dashboard.py` at session start to
refresh; table is approximate.

| Lines | Section |
|---|---|
| 1–66 | imports, constants, `_VISION_TOKEN`, `_APP_DIR`, dashboard package re-imports + slice-2D re-export |
| ~67–~75 | champ_select re-export shim (Tier 2 #6) |
| ~77–~89 | bridge_log re-export shim (Tier 2 #1) |
| ~92–~101 | diagnostics re-export shim (Tier 2 #2) |
| ~103–~111 | writers re-export shim (Tier 2 #3) |
| ~113–~120 | liveclient re-export shim (Tier 2 #4) |
| ~122–~130 | state_builder re-export shim (Tier 2 #5) |
| ~133–~155 | `_SUPERVISOR_PROXY_PATHS`, `_SUPERVISOR_ORIGIN` |
| ~158–~end | `_Handler` — `do_GET`, `do_POST`, `_csrf_ok`, `_send`, `_proxy_to_supervisor` + final `start_dashboard` re-export |

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:

1. All items from prior sessions through Tier 2 #5 (this morning) —
   /api/state, /api/health, /api/input, /api/command, /api/diagnostics,
   /api/bridge GET+POST, /api/sim-state, etc. — all unchanged.

2. **NEW (Tier 2 #6): /api/preview-build still works:**
   ```
   curl -k 'https://127.0.0.1:8888/api/preview-build?champion=Jinx&mode=ARAM' | py -c "import json,sys; d=json.load(sys.stdin); print('keys:', sorted(d.keys()), 'build_len:', len(d.get('build') or []))"
   ```
   Should print `keys: ['ally_notes', 'build', 'champion', 'mode', 'runes', 'source'] build_len: 7`. `source` is `"coach"` for ARAM (Haiku-only) or `"curated+coach"` for SR with a curated champion.

3. Re-export sanity:
   ```
   py -c "import web_dashboard, dashboard._champ_select as cs; print(web_dashboard._champ_select_brief_via_coach is cs.brief_via_coach)"
   ```
   Should print `True`.

If either of those fail, the most likely cause is an import-order issue
in `dashboard/_champ_select.py` (it imports `dashboard._context.APP_DIR`
at module scope; circular-ish because `_context` doesn't import
`_champ_select`, but worth checking). Hard fallback: revert this
commit (6d89a62); commit 778971d (Tier 2 #5) was the last green build
with the function inside `web_dashboard.py`.

## Tier 2 progress

- ✅ **#1 — bridge_log → `dashboard/_bridge_log.py`** (4317d15)
- ✅ **#2 — diagnostics cache → `dashboard/_diagnostics.py`** (8defac7)
- ✅ **#3 — writers → `dashboard/_writers.py`** (3e20b11)
- ✅ **#4 — liveclient + LCU → `dashboard/_liveclient.py`** (3ac388e)
- ✅ **#5 — state builder → `dashboard/_state_builder.py`** (778971d)
- ✅ **#6 — champ-select brief → `dashboard/_champ_select.py`** (6d89a62)
- ⏳ **#7 (judgment call) — `_Handler` → `dashboard/_handler.py`?**.
  After #6, `web_dashboard.py` is 332 lines. The remaining content is:
  - 8 re-export import blocks (~70L total)
  - `_SUPERVISOR_PROXY_PATHS` + `_SUPERVISOR_ORIGIN` (~22L)
  - `_Handler` class with 5 methods (~165L: `do_GET`, `do_POST`,
    `_csrf_ok`, `_send`, `_proxy_to_supervisor`)
  - Final `start_dashboard` re-export shim (~6L)

  Two reasonable paths:

  **(a) Move `_Handler` (and the proxy paths) into
  `dashboard/_handler.py`.** Reduces `web_dashboard.py` to ~140L of
  pure shim. Tradeoff: `_Handler` references many module-scope names
  through the shims (`_diagnostics_cached`, `_build_state`,
  `_VISION_TOKEN`, etc.) but those are mostly already abstracted —
  `_Handler.do_GET` delegates to `_dispatch.dispatch_get(self)` and
  `_Handler.do_POST` delegates to `_dispatch.dispatch_post(self,
  payload)`. The handler is now mostly scaffolding (CSRF check, body
  cap, send helper). Should be a clean extract.

  **(b) Declare helper-shake done.** 332L is reasonable for a module
  named `web_dashboard.py` that owns the HTTP server's request handler
  + supervisor-proxy glue. Move on to other Tier 2 priorities listed in
  `git show 201ff3a -- WAKEUP_NOTES.md`.

  Recommended: do (a). The handler-extraction is a clean carving cut
  (no domain logic, just HTTP plumbing). After (a), `web_dashboard.py`
  becomes a pure aggregation point — the 1980s "barrel module" pattern,
  which is fine for backward compat. Would bring it to ~140L.

  If (a): `dashboard/_handler.py` will need access to `_VISION_TOKEN`
  (used by `do_POST` somewhere? actually let me re-check — most token
  use moved out with the route handlers; `_Handler` itself probably
  doesn't read it directly). Verify with grep before extracting.

- After #7 (or skip): the other remaining Tier 2 priorities are non-
  helper-shake (different file, different concerns). Get them from
  `git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` after this hand-off. Next
focused task: either Tier 2 #7 path (a) — extract `_Handler` into
`dashboard/_handler.py` — or pivot to a non-helper-shake Tier 2 item.
Recommended: do #7 (a) first; it's a clean carving cut and leaves
`web_dashboard.py` as a pure barrel module.
