# Wakeup Notes — 2026-05-01 (session 24 hand-off)

> Hand-off from session that shipped **Tier 2 #5** (state builder
> extraction). `dashboard/_state_builder.py` now owns `MODE_TO_FILE`,
> `build_state`, `sim_states`. `web_dashboard.py` is down to **423
> lines**. Next focus: Tier 2 #6 — judgment call on whether to move
> `_Handler` (and with it `_SUPERVISOR_PROXY_PATHS`/`_SUPERVISOR_ORIGIN`,
> the CSRF guard, and the POST-body cap) into `dashboard/_handler.py`,
> or to declare the helper-shake done and move on to other Tier 2
> priorities.

---

## What just shipped

| Commit | Summary |
|---|---|
| 778971d | **Tier 2 #5**: state builder + sim scenarios + `MODE_TO_FILE` extracted to `dashboard/_state_builder.py`. `_build_state`, `_sim_states`, `_MODE_TO_FILE` move out of `web_dashboard.py`. `dashboard/routes_state.py` switches from the deferred `from web_dashboard import _build_state` (slice 2C cycle-break) to module-scope `from dashboard._state_builder import build_state, sim_states` — mirrors Tier 2 #3/#4. State builder calls `liveclient_summary`/`lcu_summary` directly from `dashboard._liveclient` and `read_json` directly from `dashboard._context`. `_SUPERVISOR_PROXY_PATHS` + `_SUPERVISOR_ORIGIN` deliberately STAYED in web_dashboard — only consumer is `_Handler._proxy_to_supervisor`, which is still there; they'll move with `_Handler`. web_dashboard.py: 477 → 423 (−54). dashboard/_state_builder.py: 91 (new). Smoke-tested: re-exports identity-equal (`_build_state is build_state`, `_sim_states is sim_states`, `_MODE_TO_FILE is MODE_TO_FILE`); `routes_state.build_state.__module__ == "dashboard._state_builder"` (direct binding); `build_state()` returns the {mode_key, coach_source, health, coach, liveclient, lcu} shape (mode_key=client out of game, lcu+liveclient empty); `sim_states()` loads data/sim_states.json and exposes aram_blitz. |
| 3ac388e | Tier 2 #4: liveclient + LCU → `dashboard/_liveclient.py`. 590 → 477 (−113). |
| 3e20b11 | Tier 2 #3: writers → `dashboard/_writers.py`. 606 → 590 (−16). |
| 8defac7 | Tier 2 #2: diagnostics cache → `dashboard/_diagnostics.py`. 621 → 606 (−15). |
| 4317d15 | Tier 2 #1: bridge log → `dashboard/_bridge_log.py`. 741 → 621 (−120). |

**Cumulative since slice 2B start: 2612 → 423 in `web_dashboard.py` (−2189 lines).**

## State at hand-off

- **45 unpushed commits** on `main` (was 44 + this commit). Origin push
  still pending — user's call before the 2026-05-10 cloud routine.
- **RC still NOT restarted.** Twenty+ queued changes (#3 log-retention,
  #4 queue-compaction, slices 1–2D + Tier 2 #1–#5) all activate
  together at next restart. None is user-visible — all internal refactor.
- Restart timing is user's call. `echo restart > restart_trigger.txt`;
  verify via `ops/runtime/health.json`.
- Game-PC bridge still dead-ish — `lcu_summary()` smoke call returned
  `{}` this session (relay status appears to have changed since #4 hand-off
  when it returned a 3-key dict). Either Game-PC LCU agent stopped or
  League client closed. Liveclient relay still empty (no game in progress).
  Bridge auto-flow loop on Game-PC may still be down.
- `RC-PatchRefresh` still showing residual `last_result=2147942402` —
  fixed at script level in `project_rc_patchrefresh_fixed`; clears on
  next scheduled run.
- Untracked / unstaged that this commit deliberately left alone:
  `config/coach_settings.json` (`disabled_coaches: []` field added —
  unrelated runtime config drift), `tools/claude-rc.ps1` (untracked).

## Inventory of `web_dashboard.py` (423 lines)

Re-run `grep -n "def \|class " web_dashboard.py` at session start to
refresh; table is approximate.

| Lines | Section |
|---|---|
| 1–67 | imports, constants, `_VISION_TOKEN`, `_APP_DIR`, dashboard package re-imports + slice-2D re-export |
| ~70–~166 | `_champ_select_brief_via_coach` (Haiku build/runes/ally-notes) |
| ~167–~180 | bridge_log re-export shim (Tier 2 #1) |
| ~183–~192 | diagnostics re-export shim (Tier 2 #2) |
| ~194–~202 | writers re-export shim (Tier 2 #3) |
| ~204–~211 | liveclient re-export shim (Tier 2 #4) |
| ~213–~221 | state_builder re-export shim (Tier 2 #5) |
| ~224–~246 | `_SUPERVISOR_PROXY_PATHS`, `_SUPERVISOR_ORIGIN` |
| ~249–~end | `_Handler` — `do_GET`, `do_POST`, `_csrf_ok`, `_send`, `_proxy_to_supervisor` + final `start_dashboard` re-export |

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:

1. All items from prior sessions through Tier 2 #4 (session 23) —
   /api/state, /api/health, /api/input, /api/command, /api/diagnostics,
   /api/bridge GET+POST, /api/preview-build, /api/sim-state, etc. — all
   unchanged.

2. **NEW (Tier 2 #5): /api/state still returns the canonical shape:**
   ```
   curl -k https://127.0.0.1:8888/api/state | py -c "import json,sys; d=json.load(sys.stdin); print(sorted(d.keys()))"
   ```
   Should print `['coach', 'coach_source', 'health', 'lcu', 'liveclient', 'mode_key']`.

3. **NEW (Tier 2 #5): /api/sim-state still returns aram_blitz:**
   ```
   curl -k 'https://127.0.0.1:8888/api/sim-state?scenario=aram_blitz' | py -c "import json,sys; d=json.load(sys.stdin); print(type(d).__name__, len(d))"
   ```
   Should print `dict <n>` with n>0. 404 means sim_states didn't load.

4. Re-export sanity:
   ```
   py -c "import web_dashboard, dashboard._state_builder as sb; print(web_dashboard._build_state is sb.build_state, web_dashboard._sim_states is sb.sim_states, web_dashboard._MODE_TO_FILE is sb.MODE_TO_FILE)"
   ```
   Should print `True True True`.

If either of those fail, the most likely cause is a circular import
between `dashboard._state_builder` and `dashboard._liveclient` at module
load time. Hard fallback: revert this commit (778971d); commit 3ac388e
(Tier 2 #4) was the last green build with helpers in `web_dashboard.py`.

## Tier 2 progress

- ✅ **#1 — bridge_log → `dashboard/_bridge_log.py`** (4317d15)
- ✅ **#2 — diagnostics cache → `dashboard/_diagnostics.py`** (8defac7)
- ✅ **#3 — writers → `dashboard/_writers.py`** (3e20b11)
- ✅ **#4 — liveclient + LCU → `dashboard/_liveclient.py`** (3ac388e)
- ✅ **#5 — state builder → `dashboard/_state_builder.py`** (this session)
- ⏳ **#6 — `_Handler` → `dashboard/_handler.py` (judgment call)**.
  After #5, the only meaningful chunks left in `web_dashboard.py` are:
  - `_champ_select_brief_via_coach` (~95L Haiku-call helper)
  - `_SUPERVISOR_PROXY_PATHS` + `_SUPERVISOR_ORIGIN` (~22L of constants)
  - `_Handler` (~140L: `do_GET`, `do_POST`, `_csrf_ok`, `_send`,
    `_proxy_to_supervisor`)
  - The shims (~8 import blocks)

  Two reasonable paths from here:

  **(a) Move `_Handler` (and the proxy paths/origin with it) into
  `dashboard/_handler.py`.** Reduces `web_dashboard.py` to just
  `_champ_select_brief_via_coach` + shims. Tradeoff: `_Handler` references
  many module-scope names through the shims (`_diagnostics_cached`,
  `_build_state`, `_VISION_TOKEN`, `_APP_DIR`, etc.) but most of those
  routes have already been peeled off into `dashboard.routes_*` and the
  dispatcher; the residual handler scaffolding is small. The big concern
  is `_APP_DIR` mutation in `start_dashboard()` — moving `_Handler`
  means `_APP_DIR` lookups inside the handler need to resolve through
  the shim too.

  **(b) Move `_champ_select_brief_via_coach` out instead.** It's a
  champ-select-specific Haiku call, used only by `routes_bridge.py` for
  `/api/preview-build`. Natural home: `dashboard/_champ_select.py` or
  fold into `routes_bridge.py` directly. This is the easier extraction
  (no `_Handler` coupling) and brings web_dashboard.py to ~325L.

  Recommended order: do (b) first (easy win, no risk), then evaluate
  whether (a) is worth doing or if web_dashboard.py is already small
  enough that extracting `_Handler` is overkill. CLAUDE.md frozen-files
  list doesn't include `web_dashboard.py` so we have permission to
  keep going, but the marginal benefit drops sharply once the file is
  under ~300L.

- After #6: evaluate whether further Tier 2 helper-shake is worthwhile.
  Other Tier 2 priorities (non-helper-shake) listed in
  `git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` after this hand-off. Next
focused task is Tier 2 #6 path (b) — extract `_champ_select_brief_via_coach`
into either its own module or fold into `routes_bridge.py`. Smaller
than #1–#5 in surface area, single caller (`routes_bridge.py:55`), no
shared state.
