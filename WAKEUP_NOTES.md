# Wakeup Notes — 2026-05-01 (session 26 hand-off)

> Hand-off from session that shipped **Tier 2 #5, #6, and #7** in one
> sitting. The dashboard helper-shake is **complete**: every helper that
> used to live in `web_dashboard.py` now sits in its own
> `dashboard/_*.py` module, including the `_Handler` class itself.
> `web_dashboard.py` is down to **145 lines** — it is now a pure barrel
> module containing only the package docstring + 8 re-export shim
> blocks for backward compat. Next focus: **non-helper-shake Tier 2
> priorities**, see "Where to look next" below.

---

## What just shipped (this session)

| Commit | Summary |
|---|---|
| aa341cc | **Tier 2 #7**: `_Handler` class + supervisor-proxy constants → `dashboard/_handler.py`. The BaseHTTPRequestHandler subclass with `do_GET`/`do_POST`/`_send`/`_csrf_ok`/`_proxy_to_supervisor`/`log_message` (~165L) and `_SUPERVISOR_PROXY_PATHS`/`_SUPERVISOR_ORIGIN` (~22L) move out. `dashboard/server.py` switches from `handler_class = web_dashboard._Handler` to `from dashboard._handler import Handler`. Drops the now-dead `import logging` + `_log` definition + `from dashboard import _dispatch` + `import json` + `from http.server import BaseHTTPRequestHandler` from web_dashboard.py. web_dashboard.py: 332 → 145 (−187). dashboard/_handler.py: 234 (new). |
| 6d89a62 | Tier 2 #6: champ-select brief → `dashboard/_champ_select.py`. 423 → 332 (−91). |
| 778971d | Tier 2 #5: state builder → `dashboard/_state_builder.py`. 477 → 423 (−54). |

**Cumulative since slice 2B start: 2612 → 145 in `web_dashboard.py` (−2467 lines).**

`web_dashboard.py` is now a **barrel module** — every name it exports is
re-bound from a `dashboard/_*.py` submodule. The `_APP_DIR` assignment
+ `start_dashboard()` mutation in `dashboard/server.py` is kept as a
defensive backward-compat hook (no in-package consumer reads it
anymore as of #6).

## State at hand-off

- **49 unpushed commits** on `main`. Origin push still pending — user's
  call before the 2026-05-10 cloud routine.
- **RC still NOT restarted.** Twenty-two+ queued changes (#3
  log-retention, #4 queue-compaction, slices 1–2D + Tier 2 #1–#7) all
  activate together at next restart. None is user-visible — all
  internal refactor.
- Restart timing is user's call. `echo restart > restart_trigger.txt`;
  verify via `ops/runtime/health.json`.
- Game-PC bridge still dead-ish — `lcu_summary()` returned `{}` this
  session, liveclient relay empty (no game in progress). Bridge
  auto-flow loop on Game-PC may still be down (last gamepc result
  >70000s ago at session start).
- `RC-PatchRefresh` still showing residual `last_result=2147942402` —
  fixed at script level in `project_rc_patchrefresh_fixed`; clears on
  next scheduled run.
- Untracked / unstaged that this session deliberately left alone:
  `config/coach_settings.json` (`disabled_coaches: []` field added —
  unrelated runtime config drift), `tools/claude-rc.ps1` (untracked).

## Final shape of `web_dashboard.py` (145 lines)

```
1–11    docstring
13      from pathlib import Path
15–22   _VISION_TOKEN (still defined here — used by some routes via shim)
24      _APP_DIR (defensive backward-compat; defined but unread in-package)
27–35   from dashboard._context import (...)        # _DB_CONN_LOCAL, _read_json, _ro_conn
36–47   from dashboard.builders import (...)        # _agg_session, _build_diagnostics, etc.
49–60   from dashboard._static import (...)         # _compute_asset_hash, _icon_svg_bytes, etc.
62–67   from dashboard._champ_select import (...)   # _champ_select_brief_via_coach (Tier 2 #6)
69–82   from dashboard._bridge_log import (...)     # _bridge_post, _bridge_since, etc. (Tier 2 #1)
84–92   from dashboard._diagnostics import (...)    # _diagnostics_cached (Tier 2 #2)
94–101  from dashboard._writers import (...)        # _atomic_write_json, _set_pregame, etc. (Tier 2 #3)
103–110 from dashboard._liveclient import (...)     # _lcu_summary, _liveclient_summary (Tier 2 #4)
112–121 from dashboard._state_builder import (...)  # _build_state, _sim_states, _MODE_TO_FILE (Tier 2 #5)
123–133 from dashboard._handler import (...)        # _Handler, _SUPERVISOR_PROXY_PATHS, _SUPERVISOR_ORIGIN (Tier 2 #7)
135–144 from dashboard.server import (...)          # _DualProtocolHTTPServer, start_dashboard (slice 2D)
```

## Bookkeeping to verify when next restarting RC

After `echo restart > restart_trigger.txt`:

1. All items from prior sessions through Tier 2 #6 (this morning) — all
   API endpoints unchanged.

2. **NEW (Tier 2 #7): /api/state, /api/health, /api/input, /api/command,
   /api/bridge GET+POST, /api/preview-build, /api/sim-state, supervisor
   proxy fallbacks (/api/activity, /api/adaptation, /api/minimap-crop,
   etc.) ALL still served correctly.** The handler class moved but the
   wiring is identical. Spot-check:
   ```
   curl -k https://127.0.0.1:8888/api/state | py -c "import json,sys; print(sorted(json.load(sys.stdin).keys()))"
   curl -k -X POST -H "Content-Type: application/json" -d "{\"command\":\"refresh\"}" https://127.0.0.1:8888/api/command
   ```

3. **CSRF guard still works** — POSTs without an Origin/Referer pass;
   browser cross-origin POSTs are rejected with 403.

4. Re-export sanity:
   ```
   py -c "import web_dashboard, dashboard._handler as hm; print(web_dashboard._Handler is hm.Handler, web_dashboard._SUPERVISOR_PROXY_PATHS is hm.SUPERVISOR_PROXY_PATHS)"
   ```
   Should print `True True`.

If the dashboard fails to start, the most likely cause is a circular
import at module load — `dashboard/server.py` does
`from dashboard._handler import Handler` at function-call time inside
`start_dashboard()`, which should be safe. Hard fallback: revert this
commit (aa341cc); commit 6d89a62 (Tier 2 #6) was the last green build
with `_Handler` in `web_dashboard.py`.

## Tier 2 helper-shake status: COMPLETE

- ✅ #1 — bridge_log → `dashboard/_bridge_log.py` (4317d15)
- ✅ #2 — diagnostics cache → `dashboard/_diagnostics.py` (8defac7)
- ✅ #3 — writers → `dashboard/_writers.py` (3e20b11)
- ✅ #4 — liveclient + LCU → `dashboard/_liveclient.py` (3ac388e)
- ✅ #5 — state builder → `dashboard/_state_builder.py` (778971d)
- ✅ #6 — champ-select brief → `dashboard/_champ_select.py` (6d89a62)
- ✅ #7 — `_Handler` + proxy constants → `dashboard/_handler.py` (aa341cc)

## Where to look next

The remaining Tier 2 priorities are non-helper-shake (different files,
different concerns). Get the original list from
`git show 201ff3a -- WAKEUP_NOTES.md`. Spot-check candidates:

- **Push the 49 unpushed commits to origin/main** before 2026-05-10 so
  the cloud routine sees them. This is now overdue; user has been
  deferring it but the deadline is approaching. Recommend: bring it up
  at the start of the next session. (Memory entry
  `project_verify_github_access_cloud_routine` covers the OAuth
  prereq.)
- **RC restart** to flush 22+ queued internal-refactor commits. None
  user-visible, but a clean restart while everything is still in
  conversation memory minimizes risk if something regresses.
- **Bridge auto-flow on Game-PC** is dead (>70000s old). Either
  Game-PC Claude needs its `/loop /process-bridge-tasks` restarted
  (memory entry `reference_bridge_autoflow`) or the LCU agent on
  Game-PC stopped. Worth investigating before the next champ-select.
- **Other Tier 2 priorities** (whatever the original user direction
  before the helper-shake started): re-read the older WAKEUP_NOTES
  diff or ask the user where to focus next.

## Session workflow note

Per CLAUDE.md "Session workflow": `/clear` after this hand-off. The
helper-shake stream is closed. Next session starts on a fresh focus
area — push to origin, restart RC, or pick the next Tier 2 priority,
whichever the user wants to drive.
