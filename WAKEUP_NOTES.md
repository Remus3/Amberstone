# Wakeup Notes — 2026-05-01 (session 23 hand-off)

> Hand-off from session that shipped **Tier 2 #4** (liveclient + LCU
> summary extraction). `dashboard/_liveclient.py` now owns
> `lcu_summary` + `liveclient_summary`. `web_dashboard.py` is down to
> **477 lines**. Next focus: Tier 2 #5 — pull `_build_state` +
> `_sim_states` + `_SUPERVISOR_PROXY_PATHS` + `_MODE_TO_FILE` into
> `dashboard/_state_builder.py` (or split — see notes).

---

## What just shipped

| Commit | Summary |
|---|---|
| 3ac388e | **Tier 2 #4**: liveclient + LCU summaries extracted to `dashboard/_liveclient.py`. The two relay-fetch helpers (`lcu_summary`, `liveclient_summary`) move out of `web_dashboard.py`. `routes_bridge.py`'s `/api/preview-build` switches from the deferred `from web_dashboard import _lcu_summary` (slice 2C-6 cycle-break) to module-scope `from dashboard._liveclient import lcu_summary` — mirrors the Tier 2 #3 routes_state.py change. `_champ_select_brief_via_coach` import stays deferred because that helper still lives in web_dashboard.py. `item_advisor` is hoisted from sys.path-mangling try/except inside the function to a top-level import; module load is pure-Python data dicts, no side effects. `_VISION_TOKEN` is sourced via `core.vision_token.get_vision_token()` inside `_liveclient.py` so it picks up the same rotation path as web_dashboard. web_dashboard.py: 590 → 477 (−113). dashboard/_liveclient.py: 158 (new). Smoke-tested: re-exports identity-equal, dashboard.routes_bridge importable in a fresh process with `lcu_summary.__module__ == "dashboard._liveclient"` (proves direct binding), `_build_state()` returns proper shape with both helpers resolving via the shim, behavioral call: `lcu_summary()` returned a 3-key dict (relay alive), `liveclient_summary()` returned `{}` (no game in progress, matches SessionStart anomaly). |
| 3e20b11 | Tier 2 #3: writers → `dashboard/_writers.py`. 606 → 590 (−16). |
| 8defac7 | Tier 2 #2: diagnostics cache → `dashboard/_diagnostics.py`. 621 → 606 (−15). |
| 4317d15 | Tier 2 #1: bridge log → `dashboard/_bridge_log.py`. 741 → 621 (−120). |

**Cumulative since slice 2B start: 2612 → 477 in `web_dashboard.py` (−2135 lines).**

## State at hand-off

- **33 unpushed commits** on `main`. Origin push still pending —
  user's call before the 2026-05-10 cloud routine.
- **RC still NOT restarted.** Nineteen+ queued changes (#3 log-retention,
  #4 queue-compaction, slices 1–2D + Tier 2 #1–#4) all activate
  together at next restart. None is user-visible — all internal refactor.
- Restart timing is user's call. `echo restart > restart_trigger.txt`;
  verify via `ops/runtime/health.json`.
- Game-PC bridge still dead-ish — but `lcu_summary()` smoke call
  returned a 3-key dict, so the LCU relay on Game-PC IS pushing.
  Liveclient relay still empty (no game in progress). Bridge auto-flow
  loop on Game-PC may still be down (last gamepc result 69300s ago at
  session start).
- `RC-PatchRefresh` still showing residual `last_result=2147942402` —
  fixed at script level in `project_rc_patchrefresh_fixed`; clears on
  next scheduled run.
- Untracked / unstaged that this commit deliberately left alone:
  `config/coach_settings.json` (`disabled_coaches: []` field added —
  unrelated runtime config drift), `tools/claude-rc.ps1` (untracked).

## Inventory of `web_dashboard.py` (477 lines)

Re-run `grep -n "def \|class " web_dashboard.py` at session start to
refresh; table is approximate.

| Lines | Section |
|---|---|
| 1–67 | imports, constants, `_VISION_TOKEN`, `_APP_DIR`, dashboard package re-imports + slice-2D re-export |
| ~70–~167 | `_champ_select_brief_via_coach` (Haiku build/runes/ally-notes) |
| ~169–~183 | bridge_log re-export shim (Tier 2 #1) |
| ~185–~205 | diagnostics re-export shim (Tier 2 #2) |
| ~207–~217 | writers re-export shim (Tier 2 #3) |
| ~219–~226 | liveclient re-export shim (Tier 2 #4) |
| ~228–~238 | `_MODE_TO_FILE` |
| ~241–~278 | `_build_state` |
| ~282–~301 | `_SIM_STATES_PATH`, `_SIM_STATES_CACHE`, `_sim_states` |
| ~303–~322 | `_SUPERVISOR_PROXY_PATHS`, `_SUPERVISOR_ORIGIN` |
| ~325–~end | `_Handler` — `do_GET`, `do_POST`, `_csrf_ok`, `_send`, `_proxy_to_supervisor` |

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:

1. All items from prior sessions through Tier 2 #3 (session 22) —
   /api/state, /api/health, /api/input, /api/command, /api/diagnostics,
   /api/bridge GET+POST, /api/preview-build, etc. — all unchanged.

2. **NEW (Tier 2 #4): /api/preview-build still works:**
   ```
   curl -k 'https://127.0.0.1:8888/api/preview-build?champion=Jinx&mode=ARAM'
   ```
   Should return JSON with `{champion, mode, source, build, runes,
   ally_notes}`. `source` is `"coach"` for ARAM (Haiku-only) or
   `"curated+coach"` for SR with a curated champion.

3. **NEW (Tier 2 #4): /api/state liveclient + lcu fields still populate:**
   ```
   curl -k https://127.0.0.1:8888/api/state | py -c "import json,sys; d=json.load(sys.stdin); print('lcu keys:', sorted((d.get('lcu') or {}).keys())); print('liveclient keys:', sorted((d.get('liveclient') or {}).keys()))"
   ```
   In a game: liveclient should have `game_time, kda, level, gold, hp,
   mana, sr_items, sr_boots_phase, ...`. Out of game: both empty `{}`.

4. Re-export sanity:
   ```
   py -c "import web_dashboard, dashboard._liveclient as lc; print(web_dashboard._lcu_summary is lc.lcu_summary, web_dashboard._liveclient_summary is lc.liveclient_summary)"
   ```
   Should print `True True`. If False, the shim regressed.

If either of those fail, the most likely cause is the top-level
`from item_advisor import …` in `dashboard/_liveclient.py` failing
because the project root isn't on sys.path at import time. Hard
fallback: revert this commit (3ac388e); commit 3e20b11 (Tier 2 #3)
was the last green build with the helpers inside `web_dashboard.py`.

## Tier 2 progress

- ✅ **#1 — bridge_log → `dashboard/_bridge_log.py`** (4317d15)
- ✅ **#2 — diagnostics cache → `dashboard/_diagnostics.py`** (8defac7)
- ✅ **#3 — writers → `dashboard/_writers.py`** (3e20b11)
- ✅ **#4 — liveclient + LCU → `dashboard/_liveclient.py`** (this session)
- ⏳ **#5 — `_build_state` + `_sim_states` + `_SUPERVISOR_PROXY_PATHS`
  + `_MODE_TO_FILE` → `dashboard/_state_builder.py`**. Next up. The
  dispatcher-facing helpers. Last group before `web_dashboard.py`
  reduces to just `_Handler` + re-exports + entry point.
  Considerations:
  - `_build_state` calls `_liveclient_summary` and `_lcu_summary` —
    in the new module, prefer direct `from dashboard._liveclient import
    lcu_summary, liveclient_summary` over going through web_dashboard.
  - `_build_state` also uses `_read_json` from `dashboard._context` —
    direct import there too.
  - `_sim_states` reads `data/sim_states.json` once and caches in a
    module-level global. Same pattern transfers cleanly.
  - `_SUPERVISOR_PROXY_PATHS` + `_SUPERVISOR_ORIGIN` are read by
    `_Handler._proxy_to_supervisor`. They could either stay in
    web_dashboard (small constants) or move with `_build_state`.
    If you move them, `_Handler` needs to grab them via a re-export
    shim or direct import.
  - Callers to verify with grep before extracting: `_build_state`,
    `_sim_states`, `_SUPERVISOR_PROXY_PATHS`. Routes that build state
    from `dashboard.routes_*` likely already call `_build_state`
    via deferred import — the same cycle-break pattern as #3 and #4
    applies.
- After #5: `web_dashboard.py` should be ~250 lines — purely the
  HTTP server entry, `_Handler` glue, and the re-export shim block.
  Then evaluate whether `_Handler` itself should move to
  `dashboard/_handler.py` or `dashboard/server.py` (already exists —
  check what's in there first).

Other Tier 2 priorities (non-helper-shake) in
`git show 201ff3a -- WAKEUP_NOTES.md`.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` after this hand-off. The
next focused task is Tier 2 #5 (state builder + sim states + supervisor
proxy paths). Larger than #1–#4 in surface area but smaller in code
volume — `_build_state` is ~37 lines, `_sim_states` ~5, the constants
are static data. The big judgment call is whether `_SUPERVISOR_PROXY_PATHS`
moves out (couples to `_Handler`) or stays. Check `dashboard/server.py`
first — it might already be the right home for both the state builder
and the proxy paths.
