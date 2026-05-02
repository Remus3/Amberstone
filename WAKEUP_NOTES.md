# Wakeup Notes — 2026-05-01 (session 27 hand-off)

> Multi-stream session. After the helper-shake closed (#1–#7) the user
> drove eight more audit items in sequence: bridge watchdog, OBS
> publisher, portalocker, decisions API decouple, SSE for /api/state,
> loadout diff highlight, recent coach calls panel, PyInstaller spec.
> Two RC restarts mid-session (each verified clean). Currently running
> RC PID 4556 — fully up to date with every commit through 8337d63.
> **58 unpushed commits** on `main`. **Cloud routine deadline
> 2026-05-10 (~9 days).** Push is overdue.

---

## What just shipped this session (in order)

| Commit | Audit | Summary |
|---|---|---|
| 22248fe | T2 #7 | bridge auto-flow watchdog: `/api/health/all` gains a `bridge` block with age + green/yellow/red status, dot caps at yellow on bridge silence. Currently surfaces as **red, ~21h stale** — the persistent Game-PC `/loop /process-bridge-tasks` outage. |
| 36edb82 | T3 #14 | swap `core/coaching_data_lock` from msvcrt loop to `portalocker.Lock`. Same external API + 2s timeout. Added `portalocker>=2.0.0` to requirements.txt; installed portalocker 3.2.0 + pywin32 311. |
| c3a68e5 | T4 #17 | items that differ across loadout variants get an amber ring (`.cs-build-item--diff` via `_csDiffItemIds(variants)`). Used `--gold` token; flagged that `--clock` is silently undefined in dashboard.css (only in legacy_index.html). |
| 21997e3 | T3 #11 | OBS WebSocket publisher (264L). Daemon thread pushes a one-line state summary to an OBS Text source via OBS-WS v5 protocol. Disabled by default; opt-in via `config/coach_settings.json` `obs.enabled`. Resilient to OBS being down. |
| 0caedc7 | T4 #16 | SSE: `/api/state-stream` route + `EventSource` subscriber on the dashboard. Eliminates ~30 fetches/min when idle. Subscriber cap of 8, 600s connection lifetime, hash-based change detection + 15s heartbeat. |
| 55332c7 | T4 #18 | `/api/decisions/log?limit=N` endpoint + "Recent Coach Calls" dashboard section under the live pending banner. Renders last N resolved decisions with their choice tags (contest=coral / give=lavender / skip=dim). |
| ffcfba9 | T3 #13 | `riot-commander.spec` PyInstaller spec at project root. Opt-in starter — does NOT install PyInstaller, does NOT run a build. ~228L with hidden imports, data files, build instructions in the docstring header. |
| 8337d63 | T3 #15 | `/api/decisions` GET + POST handlers now instantiate `DecisionStore()` directly instead of going through `get_loop().store()`. Decouples API from the in-process singleton so future loop-relocation is a localized change. Full process move deferred — needs cross-process locking on reconcile↔record_choice. |

Plus the helper-shake finale that opened the session:

| Commit | Audit | Summary |
|---|---|---|
| 778971d | T2 #5 | state builder → `dashboard/_state_builder.py`. 477→423. |
| 6d89a62 | T2 #6 | champ-select brief → `dashboard/_champ_select.py`. 423→332. |
| aa341cc | T2 #7 | `_Handler` + supervisor proxy constants → `dashboard/_handler.py`. 332→145. **web_dashboard.py is now a pure barrel module.** |

## RC restart state

- **Current PID: 4556** (was 5108 → 6560 → 4648 → 4556 across two restarts).
- All eight new audit items + the helper-shake extractions are **live in
  production**. Last verification (post-restart 3): `/api/decisions/log`,
  `/api/decisions`, `/api/state-stream`, `/api/health/all` bridge field
  all return 200 with the expected shapes.
- Bridge watchdog reads **status=red, age_s=76188** (~21h) — exactly
  the case the watchdog was designed to surface.

## Operational backlog

- **58 unpushed commits** on `main` tracking origin/main. Cloud routine
  trigger fires 2026-05-10 — that's 9 days out. Push is overdue.
  Recommend pushing at the start of the next session before any new
  work.
- **Game-PC `/loop /process-bridge-tasks` is dead** (>21h). Bridge
  watchdog catches this now, but the underlying fix is on the Game-PC
  Claude side. See memory `reference_bridge_autoflow`.
- `RC-PatchRefresh` scheduled task — fixed at script level last
  session (`project_rc_patchrefresh_fixed`); residual error code
  clears on next scheduled run (Wednesday).

## Audit completion status

Tier 1 (5/5 ✅): all shipped before this session — sqlite per-thread
cache (9bca527), liveclient consolidation (8a47737), log retention
(72ff0d4), task-queue compaction (5e24afb), web_dashboard split
(Tier 2 helper-shake).

Tier 2 architecture & reliability:
- ✅ #7 bridge auto-flow watchdog (this session, 22248fe)
- ⏳ #6 tkinter shim removal — **frozen file**, needs explicit
  approval. ~200L removable from `app/_overlay_manager.py` plus
  callers in `app/__init__.py` and the four mode coaches.
- ⏳ #8 daemon threads → asyncio (Phase 4 ARCH-002 follow-up, large)
- ⏳ #9 DB compression (`match_metrics.db` 32 MB, `rewind_history.db`
  1.7 GB; high blast radius)

Tier 3 technologies:
- ✅ #11 OBS WebSocket (this session, 21997e3) — opt-in via config
- ✅ #13 PyInstaller spec (this session, ffcfba9) — opt-in starter
- ✅ #14 portalocker swap (this session, 36edb82)
- ✅ #15 decisions API decouple (this session, 8337d63) — full
  process move deferred
- ⏳ #12 Prometheus + Grafana — fresh stack, never started

Tier 4 UI polish:
- ✅ #16 SSE for /api/state (this session, 0caedc7)
- ✅ #17 loadout diff highlight (this session, c3a68e5)
- ✅ #18 recent coach calls panel (this session, 55332c7) — scoped
  from the audit's "kill-time graph overlay" since that infrastructure
  doesn't exist

## How to enable the opt-in features that shipped

Three of this session's deliverables are **disabled by default** —
add config or do a one-time setup to activate:

1. **OBS publisher** (#11): add an `obs` block to
   `config/coach_settings.json`:
   ```json
   "obs": {
     "enabled": true, "host": "127.0.0.1", "port": 4455,
     "password": "", "source_name": "RC State", "interval_s": 2.0
   }
   ```
   Then enable Tools → WebSocket Server in OBS, create a Text (GDI+)
   source named "RC State", restart RC. Module gracefully no-ops if
   OBS isn't running.

2. **PyInstaller bundle** (#13): from project root,
   `py -m pip install pyinstaller>=6.0` then
   `py -m PyInstaller riot-commander.spec --noconfirm`. Output lands
   at `dist/riot-commander/riot-commander.exe`. The spec docstring
   has the full instructions including known limitations (Tesseract
   not bundled, PIL hooks may need extending on first build).

3. **Recent coach calls panel** (#18): no setup needed — appears
   automatically below the pending decisions banner once
   `data/decisions_log.jsonl` has entries from real games.

## Where things live now (cheat sheet for next session)

`dashboard/` (Tier 2 helper-shake completed earlier this session):
- `_handler.py` — `Handler` class + supervisor-proxy constants
- `_state_builder.py` — `build_state`, `sim_states`, `MODE_TO_FILE`
- `_liveclient.py` — `lcu_summary`, `liveclient_summary`
- `_champ_select.py` — `brief_via_coach` (Haiku)
- `_writers.py` — atomic JSON writers + `set_pregame`, `force_vision_scan`
- `_diagnostics.py` — diagnostics cache
- `_bridge_log.py` — cross-Claude bridge log + `gamepc_result_age_s` (T2 #7)
- `_dispatch.py` / `routes_*.py` — per-area HTTP routes
- `server.py` — HTTP/TLS server bootstrap

`web_dashboard.py` is **145 lines of pure shims** — every name is
re-bound from `dashboard/_*.py`.

`core/`:
- `obs_publisher.py` — new this session, opt-in OBS WS push
- `coaching_data_lock.py` — portalocker-backed (this session)
- `decision_detector.py` — unchanged; loop still launched from
  `dashboard/server.py:start_dashboard`

## Session workflow note

Per CLAUDE.md "Session workflow": user requested `/clear` after this
hand-off. The big stream is closed. Next session starts on whichever
operational item the user picks (push, more audit work, or a fresh
feature ask).

If the next session picks a new audit item, candidates ranked by ease:
- Easiest: `git push origin main` and watch the cloud routine
- Easy: T3 #12 Prometheus + Grafana — net new, no frozen-file touch
- Moderate: full T3 #15 process move (add portalocker locking on
  reconcile/record_choice, then move launch from dashboard/server.py
  to agents/supervisor.py)
- Hard: T2 #6 tkinter shim removal — needs explicit approval first;
  ~200L removable from frozen `app/_overlay_manager.py` plus callers
- Avoid: T2 #8 (asyncio refactor) and T2 #9 (DB compression) —
  larger-scope, likely multi-session

## Restart verification record (this session)

Three RC restarts ran cleanly:

| Restart | Old PID → New PID | Key changes activated |
|---|---|---|
| 1st | 5108 → 6560 | Tier 2 helper-shake #1–#7 (8 commits, all internal refactor) + bridge watchdog T2 #7 |
| 2nd | 6560 → 4648 | T3 #14 portalocker, T3 #11 OBS publisher, T4 #16 SSE |
| 3rd | 4648 → 4556 | T4 #18 /api/decisions/log + T3 #15 API decouple |

Each restart verified via the same battery: PID change, `last_reload_ok`,
`ui_pulse_age_s`, all helper-shake shim identities, current endpoints.
No regressions detected.

---

# Follow-on session 27b — 2026-05-01 19:14 hand-off

> Short follow-on after the user opened the next session and chose
> "push, then continue". Three small things shipped + the Tier 3 #15
> finish. **Origin/main is current** through `fa9dc45`.

## What shipped

| Commit | Type | Summary |
|---|---|---|
| (push) | ops | Pushed the 59 backlog commits (`597df0a..54588bd`). Cloud routine deadline 2026-05-10 is now safe — origin will have a fresh tree when it fires. |
| 3740dff | chore | Untracked `config/coach_settings.json` (runtime-mutated by `/api/coach/toggle`); shipped `coach_settings.example.json` as the template. Committed `tools/claude-rc.ps1` (personal launcher). Working tree clean for the first time this session. |
| fa9dc45 | refactor | **T3 #15 finish** — moved DecisionLoop daemon thread out of RC main into `agents/supervisor.py`. Added `_decisions_critical_section()` (threading.Lock + portalocker file lock on `ops/runtime/decisions.lock`, mirrors `coaching_data_lock` pattern) so cross-process reconcile↔record_choice is safe. |

## Cloud routine verification (trig_01RBhupHp49EhrhKdAtExVND)

`RemoteTrigger get` showed: enabled, `run_once_at: 2026-05-10T14:00:00Z`,
repo `Remus3/riot-commander`, model `claude-sonnet-4-6`, tools allowlist
correct, no MCP attached. Creator is `Nicolas`. Schedule + repo wired
correctly. **Untested:** GitHub OAuth on the private repo — only the
browser dashboard at `claude.ai/code/routines/<id>` shows auth state, or
`RemoteTrigger run` (which actually opens a real PR). Deferred.

## Restarts this follow-on

| Process | Old PID → New PID | Why |
|---|---|---|
| Phase 3 supervisor | 4564 → 2956 | Pick up T3 #15 — load DecisionLoop in `Supervisor.start()` |
| RC main | 4556 → 9252 | Pick up T3 #15 — stop launching DecisionLoop in `dashboard/server.py` |

Verified via probe-clear (write fake pending entry, observe wipe within ~1s):
* Pre-RC-restart probe: wiped — supervisor loop alive
* Post-RC-restart probe: still wiped — no double-launch, supervisor still alive

Endpoint smoke after both restarts: `/api/decisions`, `/api/decisions/log`,
`/api/health/all` bridge field — all 200 with expected shapes.

## Audit completion (updated)

Tier 3:
- ✅ #11 OBS WebSocket — opt-in via config (last session)
- ✅ #13 PyInstaller spec — opt-in starter (last session)
- ✅ #14 portalocker swap (last session)
- ✅ **#15 decisions process move (THIS — fa9dc45)**
- ⏳ #12 Prometheus + Grafana — fresh stack, never started

Everything else from the prior table unchanged. Tier 1 still 5/5,
Tier 4 still 3/3, Tier 2 still has #6 (tkinter shim, frozen-file
approval needed), #8 (asyncio refactor), #9 (DB compression) open.

## Operational backlog

- ~58 commits backlog → **0** (push cleared it)
- **Game-PC `/loop /process-bridge-tasks` still dead** (>21h per the
  bridge watchdog; same status as prior session). Not addressed here.
- `RC-PatchRefresh` residual error code clears on Wednesday's
  scheduled run (unchanged).

## Known cosmetic gap from T3 #15

`agents/supervisor.py` only configures the `supervisor` logger; INFO
lines from `rc.decision_detector` (and other `rc.*` loggers) are
silently dropped when those modules run inside the supervisor process
under `pythonw.exe`. Loop liveness verified via probe-clear, not log
grep. Saved to memory as `reference_supervisor_logger_gap`. Fix would
attach the rotating handler to `getLogger("rc")` too — out of scope.

## Next-session candidates (re-ranked)

- **Easiest unstarted:** T3 #12 Prometheus + Grafana — fresh stack,
  never started. Likely multi-session if dashboards are required;
  single-session if only the instrumentation pass.
- **Moderate:** T2 #8 asyncio refactor — large, multi-session.
- **Avoid:** T2 #9 DB compression — high blast radius.
- **Bridge watchdog says red, ~22h** — next time the user opens
  Game-PC Claude, kicking `/loop /process-bridge-tasks` back up is
  the actual fix (not RC-side).

---

# Session 27c — 2026-05-01 19:42 hand-off (T2 #6 ship)

> User invoked T2 #6 (tkinter shim removal) directly. Three commits, two
> RC restarts, both verified clean. **The audit's "Hard + needs approval"
> item is done.**

## What shipped

| Commit | Audit | Summary |
|---|---|---|
| 27e8a43 | T2 #6 part 1 | RC-main process: `_overlay_manager.py` cut from 275L 12-method window manager to a 50L 3-method shell (build_windows / switch_mode / update_content). `__init__.py` lost `_wire_ops_tab`/`_refresh_ops_tab`/`_context_menu`/`_TAB_TO_MODE`/`_copy_state_to_clipboard` plus 7 dead overlay stub delegates. `_remediation.rebuild_panel_*` are no-ops returning `{ok: true}`. `_game_lifecycle` lost the preview-teardown call, two `attach_overlay` calls in TFT start, and the `game_windows[rtop].update_stats` push. `ops/reattach_overlay.py` deleted. **−466 lines.** |
| 9a162a2 | T2 #6 part 2 | Coaches: BaseCoach lost `attach_overlay`/`detach_overlay`/`_poll_overlay_file`/`_teardown_overlay`/`_attach_overlay_windows`/`teardown_overlay`-free-fn + the `_HEADLESS` import. Mode coaches each dropped `_attach_overlay_windows`; arena lost its `_poll_overlay_file` override. `tft_coach.py` lost 230L (attach_overlay + _poll_overlay_files + comp/board wiring + `_active_instance` global). `tft_pbe_coach.py` parallel cut. `aram_pregame_panel.py` dropped its `_HEADLESS` deiconify branch — panel stays withdrawn. `self._overlay = {}` kept on every coach so existing `.get(...)` reads safely return None. **−502 lines.** |
| (this) | T2 #6 part 3 | Doc sync: CLAUDE.md "Headless mode" §, README.md, ROADMAP.md, `RC_ARCHITECTURE_INFOGRAPH.{md,html}`. Historical audit ledgers (AUDIT_*, PHASE_7_*, ARCH-001-decomposition-plan, AUDIT_PHASE_2_STATUS, phase3_file_rc_audit_proposals.py) intentionally left untouched. |

**Net: −968 lines** across 12 source files + 5 docs. py_compile clean,
all 7 changed coach modules import clean, RC live + healthy.

## What remains tkinter-shaped

The Tk root itself stays — `app/__init__.py` still does `tk.Tk()` because
game polling schedules via `root.after(POLL_DATA_MS, self._poll_file)` and
`root.after(POLL_GAME_MS, self._drain_game_q)`. Replacing that with
`threading.Timer` or asyncio is **T2 #8** (asyncio refactor), not this task.

`AramPregamePanel` (`ui/aram_pregame_panel.py`) is still launched from
frozen `main.py:234` and continues to poll LCU + apply summoner-spell
data. It just never `deiconify()`s. No call sites visible to the user.

`TftWorker.wire_ai_bar` and `core/tk_ai_bar_proxy.TkAiBarProxy` are now
unused in production but still exercised by `tests/phase2_smoke/test_tft_worker.py`.
Cleaning those up is outside T2 #6 scope.

## Restarts this session

| Process | Old PID → New PID | Why |
|---|---|---|
| RC main | 9252 → 8332 | Pick up C1 (overlay mgr + RC-main strip) |
| RC main | 8332 → 3544 | Pick up C2 (coach overlay strip) |

Both verified: PID change, `last_reload_ok=true`, all 4 dashboard
endpoints (`/api/state`, `/api/health/all`, `/api/decisions`,
`/api/decisions/log`) return 200, no ERROR/Traceback in post-restart logs.

## Audit completion (updated)

Tier 2 architecture & reliability:
- ✅ #5 dashboard helper-shake (s27)
- ✅ #6 dashboard helper-shake (s27)
- ✅ #7 bridge auto-flow watchdog + dashboard helper-shake (s27)
- ✅ **#6 tkinter shim removal (THIS)**
- ⏳ #8 daemon threads → asyncio (large, multi-session)
- ⏳ #9 DB compression (high blast radius)

Tier 1 still 5/5, Tier 3 4/5 (only #12 left), Tier 4 3/3.

## Operational backlog

- **3 unpushed commits** (C1, C2, C3) on `main` — push at start of next
  session before any new work.
- **Game-PC `/loop /process-bridge-tasks` still dead** (>22h per the
  bridge watchdog; same status as prior sessions).
- `RC-PatchRefresh` residual error code clears on Wednesday's run.

## Next-session candidates

- **Push the 3 backlog commits** (one-line, ~30s).
- **T3 #12 Prometheus + Grafana** is the only T1-T3 audit item left.
  Multi-session if dashboards are wanted; single-session if just the
  instrumentation pass on existing `cost_tracker`/`coach_trace`.
- **T2 #8 asyncio refactor** — would finally let us drop `tk.Tk()`
  and become genuinely Tk-free. Large, multi-session.
- **T2 #9 DB compression** — still avoid.

---

# Session 27d — 2026-05-01 20:35 hand-off (push backlog + T3 #12 ship)

> User opened the next session, picked the queue: pushed backlog, then
> shipped T3 #12 (Prometheus instrumentation). Origin/main is current
> through `c9191a3`. **Tier 3 is now 5/5 ✅.**

## What shipped

| Commit | Type | Summary |
|---|---|---|
| (push) | ops | Pushed `aff07fb..3e765ab` (the 3 T2 #6 commits) to origin/main. Cloud routine deadline 2026-05-10 again safe. |
| c9191a3 | feat | **T3 #12** — `core/prom_metrics.py` (zero-dep Counter/Gauge/Histogram + `render_all`) + `dashboard/routes_metrics.py` serving `/metrics` in Prometheus 0.0.4 text format. Counters wired into `cost_tracker.record_call` (calls/tokens/USD by model+purpose), `acquire_vision_token` (granted/denied), `vision_dedupe_get` (hits/misses). Latency histogram in `coach_trace.append` (mode+model). 7 scrape-time gauges: `rc_alive`, `rc_dashboard_ui_pulse_age_seconds`, `rc_game_poll_worker_age_seconds`, `rc_bridge_gamepc_result_age_seconds`, `rc_decisions_pending`, `rc_daily_spend_usd`, `rc_daily_calls`. **Render ~0.3 ms, ~2.3 KB body.** |

Plus a doc-sync of CLAUDE.md (architecture map + `curl /metrics` command)
in the same commit.

## Restarts this session

| Process | Old PID → New PID | Why |
|---|---|---|
| RC main | 3544 → 5808 | Pick up T3 #12 (initial wire) |
| RC main | 5808 → 8636 | Pick up eager-import fix so the `coach_latency` histogram declares before first traffic |

Both verified clean: PID change, `last_reload_ok=true`, all 5 dashboard
endpoints (`/api/state`, `/api/health/all`, `/api/decisions`,
`/api/decisions/log`, `/metrics`) return 200.

## Audit completion (updated)

Tier 3 **complete (5/5)**:
- ✅ #11 OBS WebSocket (s27)
- ✅ #13 PyInstaller spec (s27)
- ✅ #14 portalocker swap (s27)
- ✅ #15 decisions process move (s27b)
- ✅ **#12 Prometheus /metrics (THIS — c9191a3)**

Tier 1 still 5/5, Tier 4 still 3/3. Tier 2 has #8 (asyncio refactor)
and #9 (DB compression) still open — both flagged "avoid until needed".

## What `/metrics` does NOT include yet

By design, the endpoint is just exposition — nothing scrapes it. The
counters with labels (`rc_coach_calls_total`, `rc_coach_tokens_total`,
`rc_coach_cost_usd_total`, `rc_coach_latency_seconds`) emit only
`# HELP`/`# TYPE` lines until first observation; that's correct
Prometheus convention. Once the user plays a real game, the bumped
samples appear automatically.

## Operational backlog

- **1 unpushed commit** (`c9191a3`) — push at start of next session if
  cloud routine wiring matters before 2026-05-10.
- **Game-PC `/loop /process-bridge-tasks` still dead** (>22.8h per the
  bridge gauge `rc_bridge_gamepc_result_age_seconds`; ~82,000s).
- `RC-PatchRefresh` residual error code clears on Wednesday 2026-05-06.

## Known-non-obvious follow-on

If a future session wants to add metrics from a new module that ISN'T
already imported on dashboard boot, the metric won't appear in
`/metrics` until the module loads (lazy registration pattern). The fix
is to add `import core.<module>  # noqa: F401` to
`dashboard/routes_metrics.py` near the eager-import block. Saved as
memory `reference_prom_metrics`.

## Next-session candidates (re-ranked)

- **Easiest:** push `c9191a3` and stop. (Good stopping point — Tier 1-3
  are all green.)
- **T2 #8 asyncio refactor** is the only remaining Tier 1-2 item. Large,
  multi-session. Would finally let us drop `tk.Tk()` and become Tk-free.
- **T2 #9 DB compression** — still avoid (high blast radius on a 1.7 GB
  rewind_history.db).
- **Stack install:** if a real Prometheus scraper + Grafana is wanted,
  that's a separate "ops day" task — install the binaries, write a
  scrape config pointing at `https://127.0.0.1:8888/metrics`
  (insecure_skip_verify=true), wire a Grafana panel set. RC-side is
  already ready.
- **Bridge fix** is still Game-PC-side, not RC-side.

---

# Session 27e — 2026-05-01 20:42 hand-off (push-only)

> User picked the "push, then stop" option from s27d. One push, no code
> changes. Origin/main is current through `b04b1c6`. **0 backlog.**

## What shipped

| Action | Detail |
|---|---|
| `git push origin main` | `3e765ab..b04b1c6` — the c9191a3 (T3 #12 Prometheus) + b04b1c6 (CLAUDE.md sync) pair. |

No restarts, no source edits beyond this WAKEUP append.

## Anomalies confirmed (no action taken — both already explained)

- `RC-PatchRefresh` last_result=2147942402 — script-level fix already in place (memory `project_rc_patchrefresh_fixed`); error code clears on next scheduled run (Wednesday 2026-05-06).
- Bridge gauge ~82,400s stale — Game-PC-side `/loop /process-bridge-tasks` outage, fix is on Game-PC Claude, not RC-side. Watchdog (T2 #7) is correctly surfacing it.

## Audit completion (unchanged from s27d)

- Tier 1: 5/5 ✅
- Tier 2: ✅ #5 #6 (helper-shake) #6 (tkinter shim) #7 — only #8 (asyncio) and #9 (DB compression) remain
- Tier 3: 5/5 ✅
- Tier 4: 3/3 ✅

## Next-session candidates (unchanged from s27d)

- **T2 #8 asyncio refactor** is the only remaining Tier 1-2 item. Large, multi-session. Would let us drop `tk.Tk()` and become genuinely Tk-free.
- **T2 #9 DB compression** — still avoid (high blast radius on 1.7 GB rewind_history.db).
- **Stack install:** real Prometheus scraper + Grafana is a separate "ops day" task; RC-side `/metrics` is already ready.
- **Bridge fix** is Game-PC-side. Next time the user opens Game-PC Claude, restarting `/loop /process-bridge-tasks` is the actual fix.

---

# Session 27f — 2026-05-01 21:25 hand-off (T2 #8 plan, no code)

> User asked for T2 #8 plan only; no code shipped. `/clear` next, then C1
> in a scoped session. Origin/main current through `b04b1c6` (no change).

## T2 #8 plan summary

Multi-session asyncio refactor. **Strategy: incremental, hybrid first.** Plan via Plan subagent — full output in this session's transcript; key points below.

**Commit 1 (one focused session, ~250-350 LOC, 5 frozen files touched):** Replace `tk.Tk()` with asyncio scheduler.
- New file: `app/_loop.py` — owns `asyncio.new_event_loop()`, exposes `schedule(ms, fn)` mimicking `root.after()`, exposes `spawn_task(coro)`, exposes `stop()` for graceful shutdown.
- Frozen files touched (this is pre-approved as part of T2 #8 scope per WAKEUP s27c precedent):
  - `app/__init__.py` — drop `import tkinter as tk`, `self.root = tk.Tk()`, `self.root.withdraw()`, `mainloop()`, `report_callback_exception`. Replace 12 `root.after(...)` call sites with `app.scheduler.schedule(...)`. (12 sites verified by Grep across `app/__init__.py`, `app/_health_monitor.py`, `app/_remediation.py`, `app/_game_lifecycle.py`.)
  - `app/_health_monitor.py` — pulse heartbeat (lines 39, 45) → `scheduler.schedule(2000, self.pulse)`.
  - `app/_remediation.py` — line 60 marshal `restart_game_poll` onto loop.
  - `app/_game_lifecycle.py` — 4 sites (lines 128, 247, 267, 301) for `_drain_game_q`, `_drain_tft_q`, `_poll_file`.
  - `main.py` — minor: `app.run()` semantics now wrap `loop.run_forever()`. Also: **delete the `AramPregamePanel(app.root, _lcu)` line at main.py:234** and delete `ui/aram_pregame_panel.py` (~480 LOC). WAKEUP s27c already flagged it as dead-but-launched; this is the natural cut.
- Verification battery (run after restart, before commit ships):
  - `py_compile` clean on every modified file
  - `restart_trigger.txt` → new PID in `ops/runtime/health.json`
  - `last_reload_ok=true`
  - `ui_pulse_age_s < 6.0`, `game_poll_worker_age_s < 12.0` (steady over 30s)
  - `/api/state`, `/api/health/all`, `/api/decisions`, `/api/decisions/log`, `/metrics` all 200
  - No `ImportError: tkinter` or `Traceback` in post-restart log

**Commit 2:** Repo-wide `import tkinter` purge (no frozen). ~15 files in `tft/`, `modes/`, `ui/`, `core/`, `ops/` are dead since T2 #6. Verify `tests/phase2_smoke/test_tft_worker.py:139` first (it asserts on `root.after`).

**Commit 3:** Convert `_base_coach._poll_loop` + `_vision_loop` to async. ~150 LOC in `coaches/_base_coach.py`. Wrap blocking `messages.create` and Tesseract OCR calls in `asyncio.to_thread`. Mode coach subclasses don't change (abstract methods stay sync, run via `to_thread`).

**Commit 4:** Convert isolated module pollers (`liveclient_cache`, `vision_tracker`, `obs_publisher`, `metrics_cache`, `log_retention`). ~120 LOC. Each is `_loop` daemon thread → `spawn_task(_loop_async())`.

**Commit 5 (optional):** LCU pollers (`lcu_client`, `lcu_rune_writer`, `lcu_postgame_collector`). `lcu_client.py` is frozen — needs a fresh approval. Buys little, can defer.

**Commit 6 (optional):** Doc sync — CLAUDE.md "Headless mode" §, README, ROADMAP, INFOGRAPH.

## Out of scope (do NOT pull into T2 #8)

- Dashboard HTTP server (`dashboard/server.py`) — `ThreadingHTTPServer` stays. Migrating to `aiohttp`/`Hypercorn` is a separate item.
- Supervisor process (`agents/supervisor.py`) — already async; isolated process.
- Hotkey listener (`core/hotkeys.py`) — Win32 polling, no benefit from converting.
- DB compression (T2 #9), TFT vision relay refactor — separate audit items.

## Risk register (top 3 to remember)

- **R1 — `restart_trigger.txt` workflow break.** New scheduler must propagate `KeyboardInterrupt`/`SIGTERM` to `loop.stop()` so supervisor restarts cleanly. Wire `signal.signal(SIGTERM, ...)` early in `OverlayApp.run()`.
- **R2 — Anthropic blocking calls.** Today's coach call is sync HTTP and runs in a per-call daemon thread. Under asyncio, must use `asyncio.to_thread(self._run_coach, ...)` or migrate to `anthropic.AsyncAnthropic` (out of scope for C3).
- **R3 — `ui_pulse_age_s` health gauge stops updating** if pulse cadence subtly differs. Verify after restart that gauge stays under 6.0s for 30s.

## Success criteria (when is T2 #8 done?)

1. `Grep '^import tkinter'` → 0 hits in `app/`, `coaches/`, `core/`, `lcu/`, `ui/`, `main.py`
2. `Grep 'tk\.Tk\(\)'` → 0 production hits
3. `Grep 'root\.after'` → 0 hits in `app/` and `coaches/`
4. `_base_coach._poll_loop` and `_vision_loop` are `async def`
5. `restart_trigger.txt` workflow still works end-to-end
6. All 5 dashboard endpoints 200, ARAM smoke (lobby → coaching_data updates)
7. CLAUDE.md "Headless mode" section no longer says "tk.Tk() root remains"

## Bootstrap for next session

1. Read CLAUDE.md (frozen file list, restart workflow)
2. Read this hand-off (s27f) + s27c (T2 #6 ship — same frozen-file pattern as C1 here)
3. Read `app/__init__.py`, `app/_health_monitor.py`, `app/_remediation.py`, `app/_game_lifecycle.py` end-to-end before touching
4. Start with C1 only. Do NOT bundle C2-C4 — each is its own restart + verification.

---

# Post-T2 #8 follow-ups (parked 2026-05-01)

> Items the user wants revisited only AFTER T2 #8 ships. Don't pull these
> forward — they're explicitly deferred so the asyncio refactor stays focused.

## PowerShell 7 migration

- Current env: Windows PowerShell 5.1 (`powershell.exe`).
- PS 5.1 quirks we work around today: no `&&`/`||` chain operators (use `; if ($?) { ... }`), no `??`/`?.`/ternary, no `ConvertFrom-Json -AsHashtable`, default file encoding UTF-16 LE w/ BOM (we pass `-Encoding utf8` explicitly).
- None of these have blocked RC work. Migration cost is near-zero (PS 7 installs side-by-side as `pwsh.exe`) but benefit is also near-zero until a specific PS 5.1 limit bites.
- **Plan:** Bundle with the "ops day" hygiene pass that includes Prometheus+Grafana stack install and any other env upgrades. Not before T2 #8.

## Plugin evaluation pass

User-provided list at `C:\Users\Administrator\Desktop\plugins.txt`. Preliminary fit assessment (2026-05-01, based on claude.com plugin pages):

| Plugin | Fit | Reason |
|---|---|---|
| `claude-md-management` | ✅ try | RC has 4 CLAUDE.md files; `/revise-claude-md` automates the session-learning capture currently done by hand in WAKEUP_NOTES |
| `optibot` | ✅ try | diff-aware code review (uncommitted / branch-vs-main / patch); leaner everyday alternative to `/ultrareview` |
| `frontend-design` | ✅ already loaded as skill | dashboard CSS/HTML work |
| `superpowers` | ⚠ maybe | TDD + structured-debugging methodology; light test surface today (snapshot + smoke), could add discipline or friction |
| `nimble` | ⚠ niche | web data extraction; only relevant if we resume league-of-graphs scraping (currently using `rewind_history.db` instead) |
| `github` | ➖ likely overlap | RC uses `gh` CLI directly; plugin probably redundant |
| `remember` | ➖ likely overlap | auto-memory system already at `~/.claude/projects/.../memory/` |
| `sanity-plugin` | ❌ skip | Sanity CMS — RC doesn't use it |
| `atomic-agents` | ❌ skip | Atomic Agents framework — RC doesn't use it |

**Plan:** After T2 #8 ships, install `claude-md-management` and `optibot` in a single session, run each against the repo once to verify they don't conflict with existing workflows, then keep or revert based on actual fit. Defer `superpowers` until there's a session where TDD discipline is desired. Skip the rest unless requirements change.

## Recent Coach Calls panel — move off home page

- Shipped in T4 #18 (s27, commit 55332c7) under the live pending decisions banner. Sits just above the footer on the home page.
- User wants it OFF the home page. Doesn't need to live there — likely belongs on a sub-page (e.g. a `/decisions` or `/coach-history` view) or behind a toggle.
- Frontend files: `web/index.html` (panel markup), `web/dashboard.css` (styles), `web/dashboard.js` (renderer + `/api/decisions/log` fetch). Backend `/api/decisions/log` endpoint stays.
- **Plan:** Small UI move, ~one commit. Verify with screenshot capture per `feedback_screenshot_after_ui_changes` memory.

---

# Session 27g — 2026-05-01 21:45 hand-off (T2 #8 C1 ship)

> User invoked C1 directly off the s27f plan. One commit, one RC restart,
> verified clean. **`tk.Tk()` is gone from the orchestrator** — RC is
> genuinely Tk-free for the first time since the project started.

## What shipped

| Commit | Audit | Summary |
|---|---|---|
| (this) | T2 #8 C1 | Replace `tk.Tk()` with asyncio scheduler. New file `app/_loop.py` (AppLoop, ~95L) owns `asyncio.new_event_loop()` + thread-safe `schedule(ms, fn)` (drop-in for `root.after`) + `spawn_task(coro)` + `run_forever()`/`stop()`. Manager files swap their 7 `app.root.after(...)` sites to `app.scheduler.schedule(...)`. `app/__init__.py` drops `import tkinter as tk`, the `tk.Tk()` constructor, `withdraw()`, `report_callback_exception`, `mainloop()`, `_tk_exception` (no longer needed — AppLoop has its own exception handler), and `_tk_pulse` (was a dead delegate). `_quit()` calls `scheduler.stop()` instead of `root.quit()/.destroy()`. `run()` is `scheduler.run_forever()`. `main.py` drops the 7-line `AramPregamePanel(app.root, _lcu)` block. **Deleted `ui/aram_pregame_panel.py`** (~700L, dead since T2 #6). Test fixtures in `tests/snapshot_regressions/test_app_authority.py` switch from `app.root = FakeRoot()` to `app.scheduler = FakeScheduler()`. CLAUDE.md "Headless mode" §, frozen list, and architecture map synced. |

**Net: app/_loop.py +95L, ~700L deletion (aram_pregame_panel.py), small touch-ups across 5 frozen files + main.py + tests + CLAUDE.md.**

## What's still tkinter-shaped (deferred to C2/C3)

- ~15 files in `tft/`, `modes/`, `ui/`, `core/`, `ops/` still `import tkinter`
  but never instantiate widgets. Inert since T2 #6. **C2 is the repo-wide
  purge.**
- `coaches/_base_coach._poll_loop` and `_vision_loop` are still threading-based,
  not async. **C3 converts them to `async def`** (wrap blocking
  `messages.create` + Tesseract calls in `asyncio.to_thread`).
- `lcu_client`, `lcu_rune_writer`, `lcu_postgame_collector` still use daemon
  threads. **C5 (optional) covers LCU pollers.** `lcu_client.py` is frozen so
  needs explicit approval first.
- `dashboard/server.py` ThreadingHTTPServer stays — out of T2 #8 scope.

## AppLoop design notes (so a future session doesn't relearn)

- `schedule(ms, fn)` is thread-safe: from the loop thread it calls
  `loop.call_later(...)` directly; from any other thread it uses
  `loop.call_soon_threadsafe(loop.call_later, ...)` (an extra hop, negligible).
- During `OverlayApp.__init__`, `_loop_thread_id` is still `None` (loop hasn't
  started), so the very first `schedule(...)` calls take the threadsafe path.
  That's fine — `call_soon_threadsafe` enqueues the task; it runs as soon as
  `run_forever()` starts.
- `_safe_call` wraps every scheduled callback in try/except → log. Mirrors
  `tk.Tk().report_callback_exception` semantics.
- `set_exception_handler` catches uncaught task exceptions (separate from
  scheduled-callback failures).
- `loop.is_closed()` short-circuits `schedule()` after `stop()` so post-shutdown
  callers no-op cleanly.
- No SIGTERM handler wired. The supervisor force-kills via `taskkill /F /PID`
  per CLAUDE.md "Hard fallback" — SIGTERM doesn't fire on that path. The
  `restart_trigger.txt` workflow uses force-kill; verified clean.

## Restart verification

| Process | Old PID → New PID | Why |
|---|---|---|
| RC main | 8636 → 4536 | Pick up T2 #8 C1 |

- `last_reload_ok=true` on first health snapshot
- `ui_pulse_age_s` oscillates 0.4 ↔ 1.4 over 30s (pulse loop intact, 2s cadence)
- `game_poll_worker_age_s` 2.0–7.5 (under 12s threshold; SrAramWorker fine)
- `/api/state`, `/api/health/all`, `/api/decisions`, `/api/decisions/log`,
  `/metrics` all 200
- No `Traceback`, `ImportError`, `AttributeError`, `tkinter`, or `self.root`
  references in post-restart log
- Bootstrap log shows clean init: DevRuntime + MetricsCache + liveclient_cache
  + log_retention + dashboard + OverlayManager dashboard-only + 4 remediation
  callbacks + LCU armed + RuneWriter

## Audit completion (updated)

Tier 2 architecture & reliability:
- ✅ #5 dashboard helper-shake (s27)
- ✅ #6 dashboard helper-shake (s27)
- ✅ #6 tkinter shim removal (s27c)
- ✅ #7 bridge auto-flow watchdog (s27)
- ⏳ **#8 daemon threads → asyncio** — C1 done (this); C2/C3/C4 remain
- ⏳ #9 DB compression (high blast radius)

Tier 1 still 5/5, Tier 3 still 5/5, Tier 4 still 3/3.

## Operational backlog

- **1 unpushed commit** (this) — push at start of next session before any
  new work. Cloud routine deadline 2026-05-10 — 9 days away.
- **Game-PC `/loop /process-bridge-tasks`** — bridge gauge was ~36 minutes
  stale at session start (much fresher than the prior 22h reported in s27e/f),
  suggests the loop came back up at some point. Worth re-checking with
  `rc_facts.py` next session.
- `RC-PatchRefresh` residual error code clears on Wednesday 2026-05-06.

## Next-session candidates (ranked)

- **Easiest:** push the C1 commit, optional stop point.
- **Logical next:** **T2 #8 C2** — repo-wide `import tkinter` purge (no
  frozen files). ~15 files in `tft/`, `modes/`, `ui/`, `core/`, `ops/` carry
  dead imports since T2 #6. Verify `tests/phase2_smoke/test_tft_worker.py:139`
  doesn't break (it asserts `root.after` not in `tft_worker.py` source —
  still fine). One small commit.
- **Medium:** **T2 #8 C3** — convert `_base_coach._poll_loop` + `_vision_loop`
  to `async def`. ~150L in `coaches/_base_coach.py`. Wrap blocking
  `messages.create` and Tesseract OCR in `asyncio.to_thread`.
- **Avoid:** T2 #9 DB compression (still high blast radius).

## Bootstrap for next session

1. Read CLAUDE.md (frozen list now includes `app/_loop.py`)
2. Read this hand-off (s27g) — AppLoop design notes are non-obvious
3. For C2: `Grep "^import tkinter" --glob "*.py"` to enumerate the purge set,
   then verify each file doesn't actually use tk before deleting the import.
4. For C3: read `coaches/_base_coach.py` end-to-end before touching.

---

# Session 27h — 2026-05-01 21:55 hand-off (T2 #8 C2 ship)

> User invoked C2 directly off the s27g/s27f plan. One commit, one RC restart,
> verified clean during a live ARAM game (re-attached seamlessly). **Production
> code is genuinely tkinter-free** for the first time since the project started —
> success criteria #1 from s27f satisfied.

## What shipped

| Commit | Audit | Summary |
|---|---|---|
| (this) | T2 #8 C2 | Repo-wide `import tkinter` purge — but as **archive**, not delete. Per `reference_archive_dir` memory, dead files moved (not deleted) to `_archive/2026-05-01-audit/{ui,modes,tft,core}/`. **13 files, ~5000 LOC**: entire `ui/` package (7 files: `__init__.py`, `base.py`, `client_panel.py`, `game_bottom.py`, `game_right_bot.py`, `game_right_top.py`, `mode_indicator.py`); `modes/{aram,arena,brawl}_overlay.py` (3); `tft/tft_overlay.py` + `tft/comp_control.py` (2); `core/tk_ai_bar_proxy.py` (1). All git-mv'd as pure renames so history follows. CLAUDE.md architecture map synced (modes/ now lists only `shared_vision`; tft/ lists engine modules; ui/ marked empty). Headless mode § already correct. |

**Net diff: 13 file renames, 0 byte changes** (the renames ARE the cleanup). 4999 LOC moved out of production tree.

## Why archive, not delete

User memory `reference_archive_dir` is explicit: "move dead files to dated _archive/YYYY-MM-DD-audit/<area>/ subtree, **never delete**; reversible." s27g's one-off delete of `ui/aram_pregame_panel.py` was a special case (small file, dead since T2 #6, deleted in C1 sweep). For a 13-file purge, follow the documented pattern. Recovery is a single `git mv _archive/...` away.

## Verification

- **Pre-archive grep** confirmed zero production importers of any candidate file. The only `from ui.*` imports were *internal* to the `ui/` package itself; the only `from tft.comp_control` was internal to `tft/tft_overlay.py`; `core/tk_ai_bar_proxy.py` was referenced only by tests using a `FakeAiBarProxy` stub.
- **Post-archive `Grep "^import tkinter"`** in production tree → **0 hits**. (18 hits remain in `_archive/`, expected and correct.)
- **`py_compile`** clean on `main.py`, all 8 files in `app/`, all 7 coach files, and `core/tft_worker.py` + `core/sr_aram_worker.py` + `core/game_snapshot.py` + `modes/shared_vision.py`.
- **Smoke tests:** `tests/phase2_smoke/test_tft_worker.py` 8/8 OK (including `test_no_tk_import_in_worker`), `tests/phase2_smoke/test_sr_aram_worker.py` 8/8 OK.
- **`ops/rc_self_monitor.py`'s `allowed_panel_rebuild_keys`** still references `"game_bottom"`, `"game_rtop"`, `"game_rbot"` strings — these route to `app/_remediation.py:rebuild_panel(key)` which is a no-op since T2 #6, so the strings are harmless.
- **`ops/rc_dev_runtime.py`'s `RESTART_ONLY_MODULES`** frozenset still names the archived modules (`tft.tft_overlay`, `ui.base`, `ui.game_bottom`, etc.) but as a *blocklist* (modules that may NOT be hot-reloaded). Since they no longer exist in the tree they can't be reloaded anyway. Frozen file → leave it.

## Restart verification

| Process | Old PID → New PID | Why |
|---|---|---|
| RC main | 4536 → 3436 | Pick up T2 #8 C2 archive |

- `last_reload_ok=true` immediately
- `ui_pulse_age_s=1.4` (under 6s threshold; pulse loop intact)
- `game_poll_worker_age_s=9.0` (under 12s; SR/ARAM worker fine)
- All 5 dashboard endpoints return 200 (`/api/state`, `/api/health/all`, `/api/decisions`, `/api/decisions/log`, `/metrics`)
- Post-restart log: **no Traceback, ImportError, AttributeError, or tkinter references**
- Live game in progress at restart time — **ARAM Haiku coach producing fresh advice within seconds of new PID coming up**, so the live-game re-attach worked seamlessly

(One pre-existing harmless DEBUG line keeps appearing every ~750ms: `vision_tracker loop: 'str' object has no attribute 'get'`. Not introduced by C2; it was present in the s27g log too. Worth investigating in a separate session if vision-tracker overlay starts misbehaving on the dashboard.)

## What's still tkinter-shaped (deferred to C3+)

- **`coaches/_base_coach._poll_loop` and `_vision_loop`** are still threading-based. **C3** converts to `async def` (wrap blocking `messages.create` + Tesseract OCR in `asyncio.to_thread`). ~150L in `coaches/_base_coach.py`.
- **`lcu/lcu_client.py`, `lcu/lcu_rune_writer.py`, `lcu/lcu_postgame_collector.py`** still use daemon threads. **C5 (optional)** covers these — `lcu_client.py` is frozen so needs explicit approval.
- **Other module pollers** (`liveclient_cache`, `vision_tracker`, `obs_publisher`, `metrics_cache`, `log_retention`) per the s27f plan map to **C4** (~120L total).
- **`dashboard/server.py` `ThreadingHTTPServer`** stays — out of T2 #8 scope.

## Audit completion (updated)

Tier 2 architecture & reliability:
- ✅ #5 dashboard helper-shake (s27)
- ✅ #6 dashboard helper-shake (s27)
- ✅ #6 tkinter shim removal (s27c)
- ✅ #7 bridge auto-flow watchdog (s27)
- ⏳ **#8 daemon threads → asyncio** — C1 ✅ (s27g), **C2 ✅ (THIS)**, C3/C4/C5 remain
- ⏳ #9 DB compression (high blast radius)

Tier 1 still 5/5, Tier 3 still 5/5, Tier 4 still 3/3.

## Operational backlog

- **1 unpushed commit** (this) — push at start of next session before any new work. Cloud routine deadline 2026-05-10 — 9 days away.
- **Game-PC `/loop /process-bridge-tasks`** — bridge gauge was ~53 minutes stale at session start (much fresher than s27g's 22h+; loop appears to have come back up since). Worth re-checking with `rc_facts.py` next session.
- `RC-PatchRefresh` residual error code clears on Wednesday 2026-05-06.

## Next-session candidates (ranked)

- **Easiest:** push the C2 commit, optional stop point. Tier 1+3+4 fully green; Tier 2 only #8 (partial) + #9 (avoid) remain.
- **Logical next:** **T2 #8 C3** — convert `_base_coach._poll_loop` + `_vision_loop` to `async def`. ~150L in `coaches/_base_coach.py`. Wrap blocking `messages.create` and Tesseract OCR in `asyncio.to_thread`. Mode coach subclasses don't change (abstract methods stay sync, run via `to_thread`).
- **Medium:** **T2 #8 C4** — convert isolated module pollers (`liveclient_cache`, `vision_tracker`, `obs_publisher`, `metrics_cache`, `log_retention`) from daemon threads to `spawn_task(_loop_async())`. ~120L total.
- **Avoid:** T2 #9 DB compression (still high blast radius on 1.7 GB rewind_history.db).

## Bootstrap for next session

1. Read CLAUDE.md (frozen list, arch map now reflects post-C2 state)
2. Read this hand-off (s27h) — archive pattern is the precedent for future dead-code purges
3. For C3: read `coaches/_base_coach.py` end-to-end before touching. Pay attention to `_poll_loop`, `_vision_loop`, hotkey registration, debounce, and how mode-coach subclasses plug in.

---

# Session 27i — 2026-05-01 22:02 hand-off (T2 #8 C3 ship)

> User invoked C3 directly off the s27f plan. One commit, one RC restart,
> verified clean during a live ARAM game (Aram Coach hot-reattached and
> produced 5 fresh Haiku calls within seconds of the new PID coming up).
> **BaseCoach is now fully asyncio-native** — `_poll_loop` and
> `_vision_loop` are `async def`, mode coaches' blocking `_run_coach` /
> `_run_vision` calls dispatch via `asyncio.to_thread`.

## What shipped

| Commit | Audit | Summary |
|---|---|---|
| (this) | T2 #8 C3 | `coaches/_base_coach.py`: `_poll_loop` + `_vision_loop` → `async def` (use `await asyncio.sleep` not `time.sleep`). `_vision_loop` wraps `_run_vision()` in `asyncio.to_thread` (blocking HTTP relay + Sonnet). `_maybe_coach` replaces its per-call `threading.Thread(target=_run_coach)` with `_sched.spawn_task(asyncio.to_thread(self._run_coach, _state_copy))`. `__init__` swaps the two `threading.Thread(...).start()` lines for `_sched.spawn_task(self._poll_loop()) / spawn_task(self._vision_loop())`. Both spawn paths fall back to threads if `app._loop.get_loop()` returns None (tests / standalone scripts). `app/_loop.py` gains a module-level `_INSTANCE` set in `AppLoop.__init__` plus a `get_loop()` accessor — keeps coach constructor signatures unchanged. **+38L `_base_coach.py`, +12L `_loop.py`, ~30L deleted.** |

## Why a singleton accessor in `app/_loop.py`

Coaches don't have an app reference at construction time (mode-coach call sites in `app/_game_lifecycle.py` only pass `data_file` + `debug`). Two options:

- (a) thread `app.scheduler` through every coach constructor — invasive, touches every coach + the lifecycle dispatch
- (b) module-level singleton on the AppLoop side, accessed via `from app._loop import get_loop`

Picked (b) because there's only ever one `AppLoop` per process (RC main), and the fallback-to-thread path keeps test harnesses and the rare standalone-coach-import case working without ceremony. The accessor returns `Optional[AppLoop]` — coaches branch on it.

## Restart verification

| Process | Old PID → New PID | Why |
|---|---|---|
| RC main | 3436 → 6792 | Pick up T2 #8 C3 |

- `last_reload_ok=true` immediately
- `ui_pulse_age_s=1.5` (under 6s threshold)
- `game_poll_worker_age_s` 0.6→11.6 (under 12s; pre-existing oscillation, unchanged)
- All 5 dashboard endpoints 200
- **Live ARAM game in progress at restart** — `Aram Coach started` logged, `data/aram_coaching_data.json` mtime 8s after probe, `action="WAIT RESPAWN"` populated correctly
- `/metrics`: `rc_coach_calls_total{model="claude-haiku-4-5-20251001",purpose="aram_coach"} 5` within ~30s of restart — `_maybe_coach` → `spawn_task(asyncio.to_thread(_run_coach))` path is firing real Anthropic calls, all latencies in the 2-5s histogram bucket
- Post-restart log scan for `ERROR|Traceback|ImportError|AttributeError|tkinter` in the 400 lines after `Aram Coach started` → **0 matches**

## What's still tkinter/threading-shaped (deferred)

- **Module pollers** still daemon-thread: `liveclient_cache`, `vision_tracker`, `obs_publisher`, `metrics_cache`, `log_retention`. **C4** maps each `_loop` daemon → `spawn_task(_loop_async())`. ~120L total. Same `get_loop()` pattern works here.
- **LCU pollers** (`lcu_client`, `lcu_rune_writer`, `lcu_postgame_collector`) still daemon-thread. `lcu_client.py` is frozen so **C5 (optional)** needs explicit approval. Buys little.
- **`tft_coach.py` / `tft_pbe_coach.py`** are NOT BaseCoach subclasses (they have their own internal threading). C3 doesn't touch them; they'd be a separate refactor.
- **`coach_integration.py` / `sr_coach.py`** are not BaseCoach subclasses either; SR coaching runs through the worker queue path, not the BaseCoach loop. Out of T2 #8 scope.
- **`dashboard/server.py` `ThreadingHTTPServer`** stays — out of T2 #8 scope.

## Audit completion (updated)

Tier 2 architecture & reliability:
- ✅ #5 dashboard helper-shake (s27)
- ✅ #6 dashboard helper-shake (s27)
- ✅ #6 tkinter shim removal (s27c)
- ✅ #7 bridge auto-flow watchdog (s27)
- ⏳ **#8 daemon threads → asyncio** — C1 ✅ (s27g), C2 ✅ (s27h), **C3 ✅ (THIS)**, C4/C5 remain
- ⏳ #9 DB compression (high blast radius)

Tier 1 still 5/5, Tier 3 still 5/5, Tier 4 still 3/3.

## Operational backlog

- **1 unpushed commit** (this) — push at start of next session before any new work. Cloud routine deadline 2026-05-10 — 9 days away.
- **Game-PC `/loop /process-bridge-tasks`** — bridge gauge ~70 min stale at restart time (4220s). Same status as session start: Game-PC-side, not RC-side.
- `RC-PatchRefresh` residual error code clears on Wednesday 2026-05-06.

## Next-session candidates (ranked)

- **Easiest:** push the C3 commit; optional stop point.
- **Logical next:** **T2 #8 C4** — convert the 5 module pollers (`liveclient_cache`, `vision_tracker`, `obs_publisher`, `metrics_cache`, `log_retention`) from daemon threads to `spawn_task(_loop_async())`. ~120L total. Each module is independent; can ship as one commit or one-per-module.
- **Medium:** **T2 #8 C5 (optional)** — LCU pollers. `lcu_client.py` frozen, needs approval. Low payoff.
- **Avoid:** T2 #9 DB compression (still high blast radius).

## Bootstrap for next session

1. Read CLAUDE.md (frozen list)
2. Read this hand-off (s27i) — `get_loop()` singleton accessor pattern is the reusable hook for any future "needs the AppLoop without a constructor reference" case
3. For C4: `Grep "threading.Thread\(target.*_loop"` to enumerate the daemon-poller call sites; each module's `_loop` becomes `async def _loop_async`, and the module-level `start()` calls `_get_loop().spawn_task(_loop_async())` with the same thread-fallback pattern as `_base_coach.__init__`.

---

# Session 27j — 2026-05-01 22:13 hand-off (T2 #8 C4 ship)

> User invoked C4 directly off the s27i plan. One commit, one RC restart,
> verified clean. **All 5 module pollers (`liveclient_cache`,
> `vision_tracker`, `obs_publisher`, `metrics_cache`, `log_retention`)
> now ride the AppLoop in production**, with thread fallbacks for tests
> and standalone harnesses. Every running daemon thread in this group
> moved onto the asyncio loop in a single restart.

## What shipped

| Commit | Audit | Summary |
|---|---|---|
| (this) | T2 #8 C4 | `app/_loop.py`: add `ensure_loop()` — idempotent factory that creates the AppLoop singleton if one doesn't exist yet, so subsystems can spawn_task on the loop **before** OverlayApp constructs. `app/__init__.py:OverlayApp.__init__` switches from `AppLoop()` to `ensure_loop()` to share the same instance. **`main.py`** (frozen, T2 #8 pre-approved per s27c precedent): one early `from app._loop import ensure_loop; ensure_loop()` block before `metrics_cache.start()`. The 5 module pollers each gain an `async _loop_async()` next to the existing sync `_loop()`, plus a `start()` (or `start_background()`) that branches on `get_loop()` — scheduler path → `spawn_task(_loop_async())`, fallback → daemon thread as before. `liveclient_cache._fetch_once()` (blocking HTTP up to 2s) wraps in `asyncio.to_thread` inside the async loop. `metrics_cache.start()` runs `_refresh()` synchronously before scheduling so `get_summary()` returns real data immediately, matching the prior thread behavior. `obs_publisher` skips its inner `asyncio.run` thread wrapper when riding the AppLoop — `_async_loop` spawns directly. **+~190 LOC across 7 files.** |

## Why ensure_loop() was needed

`main.py` starts `metrics_cache`, `liveclient_cache`, `log_retention`, the dashboard (which starts `vision_tracker` + `obs_publisher`), all **before** `OverlayApp()` is constructed. Pre-C4, `AppLoop()` only gets created in `OverlayApp.__init__`, so by the time those modules tried to `get_loop()` they'd see `None` and fall back to threads — defeating the whole conversion. Adding `ensure_loop()` lets `main.py` create the loop early; `OverlayApp.__init__` reuses it via the same accessor. Tasks scheduled on the loop before `run_forever()` queue and fire when the loop spins up — verified by all 5 pollers showing `async` startup mode in the log.

## Restart verification

| Process | Old PID → New PID | Why |
|---|---|---|
| RC main | 6792 → 7076 | Pick up T2 #8 C4 |

- `last_reload_ok=true` immediately
- `ui_pulse_age_s=0.6` (well under 6s threshold)
- `game_poll_worker_age_s=5.1` (well under 12s threshold)
- All 5 dashboard endpoints 200 (`/api/state`, `/api/health/all`, `/api/decisions`, `/api/decisions/log`, `/metrics`)
- Boot log lines confirm async path:
  - `liveclient_cache started (poll=0.50s, async)`
  - `log_retention started (interval=3600s ..., async)`
  - `vision_tracker started (poll=0.75s, ..., async)`
  - `OBS publisher disabled (config.obs.enabled=None)` (correctly no-ops; would say `, async)` if enabled)
  - `MetricsCache started (refresh=5s ...)` (no path suffix on this one — running silently as designed)
- ARAM Coach started cleanly mid-restart; `data/aram_coaching_data.json` mtime 5.7s old, `action="POKE PHASE"` populated — confirms `liveclient_cache` async loop is actually fetching and consumers are reading from it
- No `ERROR | Traceback | ImportError | AttributeError | tkinter` in post-restart log

## Pre-existing bug surfaced (NOT a C4 regression)

`data/vision_state.json` mtime is ~2 days old and the `vision_tracker loop:` debug log fires every 0.75s with `'str' object has no attribute 'get'` — exact same noise pattern WAKEUP s27h flagged ("worth investigating in a separate session if vision-tracker overlay starts misbehaving"). Verified across the 2026-05-01 log (1856 occurrences pre- and post-C4), proving:

1. The async loop **is** running at the correct cadence (matches the 0.75s poll)
2. `_fetch_snapshot()` returns data, `ingest()` raises somewhere, exception is swallowed, `_write_atomic()` never fires
3. C4 didn't introduce this — it's the same bug the threading version had

Fix is a separate task — not in T2 #8 scope.

## Audit completion (updated)

Tier 2 architecture & reliability:
- ✅ #5 dashboard helper-shake (s27)
- ✅ #6 dashboard helper-shake (s27)
- ✅ #6 tkinter shim removal (s27c)
- ✅ #7 bridge auto-flow watchdog (s27)
- ⏳ **#8 daemon threads → asyncio** — C1 ✅ (s27g), C2 ✅ (s27h), C3 ✅ (s27i), **C4 ✅ (THIS)**, C5 (optional, LCU pollers, frozen-file approval needed) remains
- ⏳ #9 DB compression (high blast radius)

Tier 1 still 5/5, Tier 3 still 5/5, Tier 4 still 3/3.

## What's still threading-shaped (intentional / out of scope)

- **LCU pollers** — `lcu_client`, `lcu_rune_writer`, `lcu_postgame_collector`. **C5** is optional per s27f plan; `lcu_client.py` is frozen so needs explicit approval. Low payoff (LCU is a request/response API not a long-running poll loop in the same sense).
- **`tft_coach.py` / `tft_pbe_coach.py`** — not BaseCoach subclasses, separate refactor.
- **`dashboard/server.py` `ThreadingHTTPServer`** — out of T2 #8 scope; would require switching to `aiohttp` or `Hypercorn`.
- **`coaches/sr_coach`** — inherits from `CoachIntegration` not `BaseCoach`; runs through `SrAramWorker` queue path.
- **`agents/supervisor.py` Phase 3 supervisor process** — already async; isolated process.
- **`core/hotkeys.py` Win32 polling** — no benefit from converting.

## Operational backlog

- **2 unpushed commits** (C3 + C4) on `main`. Cloud routine deadline 2026-05-10 — 9 days away. Push at start of next session before any new work.
- **Game-PC `/loop /process-bridge-tasks`** — bridge gauge ~70 min stale at C4 restart time. Same status as session start. Game-PC-side, not RC-side.
- `RC-PatchRefresh` residual error code clears on Wednesday 2026-05-06.
- **vision_tracker `_fetch_snapshot` shape bug** — pre-existing, fires every 0.75s, swallowed, prevents `data/vision_state.json` from updating. Open follow-up; not in T2 #8 scope.

## Next-session candidates (ranked)

- **Easiest:** push the C3 + C4 commits; optional stop point. **T2 #8 is functionally complete** — the only deferral is C5 (LCU pollers, frozen-file approval, low payoff).
- **Easy:** fix the pre-existing `vision_tracker._fetch_snapshot` `'str' object has no attribute 'get'` bug — single-file investigation, restores `data/vision_state.json` updates and lets the dashboard minimap overlay reflect live fog-of-war state.
- **Medium:** **T2 #8 C5 (optional)** — LCU pollers. Needs `lcu_client.py` approval. Low payoff.
- **Avoid:** T2 #9 DB compression (still high blast radius on 1.7 GB rewind_history.db).

## Bootstrap for next session

1. Read CLAUDE.md (frozen list)
2. Read this hand-off (s27j) — `ensure_loop()` is the pattern for any future "subsystem needs the AppLoop before OverlayApp constructs" case. Add the early `ensure_loop()` call in `main.py` whenever you add another pre-OverlayApp subsystem.
3. If picking up the vision_tracker bug: read `core/vision_tracker.py:228-300`, particularly `_fetch_snapshot` and `_compute_enemies` — the shape error is somewhere in there. Likely a Live Client field that flipped from dict to string in a recent patch.

---

# Session 27k — 2026-05-01 22:23 hand-off (vision_tracker fix + push)

> User picked the queue: pushed C3 + C4 backlog (clean origin/main), then
> fixed the pre-existing vision_tracker shape bug surfaced by C4. One
> commit, one RC restart, vision_state.json now updates every 0.75s and
> the 1856-per-day debug log spam is gone.

## What shipped

| Action | Detail |
|---|---|
| `git push origin main` | `7f97e9d..725bcaf` — C3 (async coach loops) + C4 (async module pollers). Backlog → 0. Cloud routine deadline 2026-05-10 again safe. |
| (this commit) | **vision_tracker fix.** `_compute_enemies` line 303: `pos = p.get("position") or {}` couldn't catch the case where Live Client emits `position: "NONE"` as a string (always in ARAM, sometimes for dead/loading players in SR) — `'NONE'` is truthy so `or {}` never fires, then `pos.get("x", 0.0)` raised `'str' object has no attribute 'get'` once per iteration, swallowed by the catch-all in `_loop`/`_loop_async`. Replaced with explicit `isinstance(pos, dict)` guard. **+5 LOC.** |

## Why ARAM was always broken

The Live Client API at `:2999/liveclientdata/allgamedata` exposes `position` as a `{x, z}` dict only for SR-style maps with locational data. **ARAM (and SR-on-fountain / dead / loading) returns `position: "NONE"` (literal string).** The `or {}` idiom is the standard "default to empty" pattern but it relies on falsy values; `'NONE'` is truthy so it bypasses the fallback.

This was not a recent regression — it's been broken since the relay rolled out. WAKEUP s27g first noted the spam ("pre-existing harmless DEBUG line keeps appearing every ~750ms"), s27h reiterated, s27j re-confirmed (1856 occurrences in the 2026-05-01 log alone). C4 didn't introduce the bug; it just put the same broken loop on the AppLoop and re-surfaced the noise.

## Verification

- `data/vision_state.json` mtime age **0.5s** post-restart (was 178,011s = ~2 days stale beforehand)
- Live ARAM game showed `total: 5` enemies tracked, `dead_count: 0`, all `visible=False` and `missing_for_s=None` — correct behavior since ARAM doesn't expose positions, so the tracker can't derive fog. is_dead and respawn timing still flow through.
- 0 `vision_tracker loop: '...'` debug lines in the 197 post-restart log lines (was firing every 0.75s before)
- All 6 dashboard endpoints 200 (`/api/state`, `/api/health/all`, `/api/decisions`, `/api/decisions/log`, `/metrics`, `/api/vision-state`)
- ARAM Coach producing fresh advice mid-restart, ui_pulse_age_s healthy

## What this DOESN'T fix (deferred)

`vision_tracker` in ARAM still produces no actionable fog data — every enemy reads `visible=False, missing_for_s=null` because there are no position deltas to track. Enriching ARAM tracking would require:

- (a) Marking ARAM enemies as "always visible to map" (since ARAM has shared lane vision)
- (b) Or: switching to a different signal (e.g. event-stream parsing for kills/objectives)

That's a feature, not a fix. The bug fix here just stops the crash; future work can lift ARAM out of the "no useful state" pit.

## Restart verification

| Process | Old PID → New PID | Why |
|---|---|---|
| RC main | 7076 → 9464 | Pick up vision_tracker fix |

- `last_reload_ok=true` immediately
- `ui_pulse_age_s=1.4`, `game_poll_worker_age_s=8.2` — both healthy
- All 6 dashboard endpoints 200
- vision_state.json updating every 0.75s as expected

## Audit completion (unchanged from s27j)

Tier 1 ✅ 5/5, Tier 2: ✅ #5/#6/#6/#7 + #8 C1-C4 ✅ (C5 LCU pollers optional, frozen-file approval needed) + #9 (avoid). Tier 3 ✅ 5/5, Tier 4 ✅ 3/3.

## Operational backlog

- **1 unpushed commit** (this fix). Cloud routine deadline 2026-05-10 — 9 days away. Push at start of next session.
- **Game-PC `/loop /process-bridge-tasks`** — bridge gauge ~75 min stale at restart time. Same Game-PC-side issue.
- `RC-PatchRefresh` residual error code clears on Wednesday 2026-05-06.

## Next-session candidates

- **Easiest:** push the fix; optional stop point.
- **Easy / feature:** improve vision_tracker for ARAM specifically — mark all enemies as `visible=True` when `game_mode in ("ARAM", "KIWI", ...)` since ARAM has shared lane vision. Updates the dashboard minimap to actually show ARAM enemy presence. ~10 LOC, single file.
- **Medium:** **T2 #8 C5 (optional)** — LCU pollers. `lcu_client.py` frozen, needs approval. Low payoff.
- **Avoid:** T2 #9 DB compression (still high blast radius).

## Bootstrap for next session

1. Read CLAUDE.md (frozen list)
2. Read this hand-off (s27k) — the `position == "NONE"` Live Client quirk is worth remembering for any other code that touches `allPlayers[i].position`. **Always `isinstance(pos, dict)` before `.get()`** when the source is the Live Client API.
3. If picking up ARAM vision improvement: `core/vision_tracker.py:_compute_enemies` is where to special-case `game_mode == "KIWI"` (ARAM Mayhem internal name per CLAUDE.md `mode_strings` map; also `"ARAM"`).

---

# Session 27l — 2026-05-01 22:32 hand-off (ARAM vision shared-vision branch)

> User picked candidate #1 from s27k (the easy-feature item). One commit,
> one RC restart, verified clean — though no live game right now, so the
> ARAM `visible=True` behavior was proven via synthetic snapshot, not
> against live `vision_state.json`. Both ARAM/KIWI alive enemies now
> register as visible and the SR fog-of-war path is unchanged.

## What shipped

| Commit | Audit | Summary |
|---|---|---|
| (this) | feature | `core/vision_tracker.py`: new `_SHARED_VISION_MODES = frozenset({"ARAM","KIWI"})`. `_compute_enemies` precomputes `shared_vision = game_mode.upper() in _SHARED_VISION_MODES`, then per-enemy adds an `elif shared_vision: visible = True` branch between the `is_dead` short-circuit and the SR position-tracking path. Death still overrides — dead enemies report `is_dead=True, visible=False, respawn_in_s=N` as before. Tracked-state dict stays empty in shared-vision mode (no positions to track), which keeps `last_seen_pos / last_seen_t / last_seen_zone` as `None` — correct, since ARAM's Live Client emits `position: "NONE"` and there's nothing meaningful to record. **+12 LOC.** |

## Verification

- `py_compile` clean on `core/vision_tracker.py`
- restart_trigger.txt consumed (size=0 post-restart)
- RC PID 9464 → 9624, `last_reload_ok=true`, `ui_pulse_age_s=0.5`, `game_poll_worker_age_s=4.5`
- 6 endpoints all 200: `/api/state`, `/api/health/all`, `/api/decisions`, `/api/decisions/log`, `/metrics`, `/api/vision-state`
- 0 `Traceback / ImportError / AttributeError / tkinter / vision_tracker loop:` lines in 450 post-restart log lines
- **Synthetic snapshot test** (no live game to probe against — disk file is leftover pre-restart):
  - KIWI snapshot, 3 enemies: Lux (alive, position="NONE") → `visible=True`; Ezreal (dead) → `visible=False, is_dead=True`; Garen (alive) → `visible=True`. Summary `visible_count=2, dead_count=1, missing_count=0`.
  - CLASSIC snapshot, 3 enemies: Yasuo (self), Zed (alive, position="NONE") → `visible=False, last_seen_zone=None` (SR fog can't establish first sighting without a real position); Akali (alive, position={7400,7400}) → `visible=True, last_seen_zone=mid`. SR fog path **untouched**.

## What this fix does (and doesn't)

- **Does:** updates the dashboard minimap to actually reflect ARAM enemy presence — every alive enemy on the enemy team registers as `visible=True` in `data/vision_state.json`, so any consumer (minimap overlay, coach prompts) gets a meaningful "yes you can see them" instead of the previous always-`False`.
- **Doesn't:** add position tracking for ARAM. Live Client doesn't expose ARAM positions, so `last_seen_pos`, `last_seen_t`, `last_seen_zone` stay `None` for shared-vision modes. The minimap can show "enemy is visible / on map" but not "enemy is at coordinate X". That's a Riot API limitation, not a code limitation.

## Audit completion (unchanged from s27k)

Tier 1 ✅ 5/5 · Tier 2 ✅ #5/#6/#6/#7 + #8 C1-C4 ✅ (C5 LCU pollers optional, frozen-file approval needed) + #9 (avoid) · Tier 3 ✅ 5/5 · Tier 4 ✅ 3/3.

## Operational backlog

- **1 unpushed commit** (this fix). Cloud routine deadline 2026-05-10 — 9 days away. Push at start of next session.
- **Game-PC `/loop /process-bridge-tasks`** — bridge gauge ~93 min stale at session start (5573s). Same Game-PC-side issue.
- `RC-PatchRefresh` residual error code clears on Wednesday 2026-05-06.

## Next-session candidates

- **Easiest:** push the fix; optional stop point.
- **Easy:** **Recent Coach Calls panel — move off home page** (parked from s27f). Frontend-only, ~one commit. Files: `web/index.html` markup, `web/dashboard.css` styles, `web/dashboard.js` renderer + `/api/decisions/log` fetch. Needs screenshot verify per `feedback_screenshot_after_ui_changes` memory.
- **Medium:** **T2 #8 C5 (optional)** — LCU pollers. `lcu_client.py` frozen, needs approval. Low payoff.
- **Avoid:** T2 #9 DB compression (still high blast radius).

## Bootstrap for next session

1. Read CLAUDE.md (frozen list)
2. Read this hand-off (s27l) — `_SHARED_VISION_MODES` is the extension point if Riot ever ships another shared-vision mode (e.g. URF if they re-enable shared lane vision, or a new gamemode). Just add the upper-case mode string to the frozenset; no other code changes needed.

---

# Session 27m — 2026-05-01 22:42 hand-off (Recent Coach Calls → /coach-calls sub-page)

> User picked candidate #2 from s27l (the parked Recent Coach Calls move).
> One commit, **no RC restart needed** — `web/*` are static assets the
> dashboard server hands out per-request, so a browser refresh picks up
> the change. Bonus: live ARAM game ran through restart and confirmed the
> s27l vision_tracker fix against real data (3 alive enemies → visible=True,
> 2 dead → is_dead=True).

## What shipped

| Commit | Type | Summary |
|---|---|---|
| (this) | feature | New `coach-calls` sub-page replaces the home-page Recent Coach Calls panel. Wired through the existing view-router system (no new routing infra). **HTML:** added `<button data-view="coach-calls">Coach Calls</button>` after Diagnostics in the menu; added `<section id="view-coach-calls" class="view-section" hidden>` after `#view-replay` containing the moved `<section id="recent-coach-calls">` plus a `#recent-coach-calls-empty` placeholder shown when the list is empty; **deleted** the old standalone `<section id="recent-coach-calls">` block that sat above `<main>` on every view. **JS:** `VIEW_IDS` += `"coach-calls"`, `VIEW_LABELS` += `"coach-calls":"Coach Calls"`, `RECENT_CALLS.empty = el("recent-coach-calls-empty")`, `renderRecentCoachCalls` toggles the empty placeholder inverse to the list section. **CSS:** extended the 3 visibility-rule lists in dashboard.css (hide `main`, show `#view-coach-calls`, hide `#home-overlay`) to include `body[data-view="coach-calls"]`. **Net: ~25 LOC across 3 files.** |

## Why a sub-page (not a toggle, not in an existing view)

s27f's parked plan said "likely belongs on a sub-page (e.g. a /decisions or /coach-history view) or behind a toggle." Sub-page won because:
- The view-router system already exists with 9 views; adding a 10th costs ~15 lines vs. a toggle's bespoke show/hide JS
- Coach Calls is logically distinct from any existing view (not session-scoped, not match-scoped, not history-of-matches)
- Hash-based URL (`#coach-calls`) is shareable / linkable
- Auto-derive logic stays untouched: live games still snap to `last-match`, lobby stays `lobby`, Coach Calls is purely manual navigation

## What stayed the same

- Polling: `/api/decisions/log?limit=8` every 30s, **globally**. Data is fresh whenever the user navigates to the view; no lazy-fetch hook needed in `applyView`.
- The inner `<section id="recent-coach-calls">` still toggles `hidden` based on entries (used to control whether the styled card showed up on the home page; now it controls whether the styled card shows inside the view-section).
- Empty state: when 0 entries, the inner section hides and the new `#recent-coach-calls-empty` placeholder shows ("No resolved coach calls yet — they'll appear here after the detector flags a moment and you make a choice."). Uses the existing `.home-empty` class for visual consistency with other empty states.

## Verification

- **Static-asset HTTPS fetch** confirmed all 3 file changes are live:
  - `index.html` (71569 bytes): contains `data-view="coach-calls"` button, contains `id="view-coach-calls"` section, exactly 1 `id="recent-coach-calls"` (the old standalone block above main is gone)
  - `dashboard.js`: `"coach-calls"` in VIEW_IDS, `"Coach Calls"` label present, `R.empty.hidden` empty-state handling present
  - `dashboard.css`: `body[data-view="coach-calls"]` rules present (3 occurrences)
- **Live `/api/decisions/log?limit=8`**: 2 entries available — when the user navigates to `#coach-calls`, the panel renders with content (not the empty state).
- **No RC restart**: `web/*` are static files served by `dashboard/server.py` per-request. Confirmed by re-reading via curl after edits — the server delivers the new content without restart.
- **No screenshot of the new view captured**: the dashboard was running an active ARAM game (auto-derived to `last-match` view) with the user playing on the primary display. Sending SendKeys to refresh would target the game, not Edge. The DOM/JS/CSS structure is fully verified via fetched-content checks; visual confirmation is deferred to the user's next refresh.

## s27l fix verified live (bonus)

Live ARAM (KIWI mode) snapshot at session-start time:
- 5 enemies tracked
- 3 alive (Malphite, Poppy, LeBlanc) → all `visible=True`
- 2 dead (Kassadin, Jayce) → `visible=False, is_dead=True`
- `summary: visible_count=3, missing_count=0, dead_count=2, total=5`
- `vision_state.json` mtime 0.7s — actively updating

Real-data confirmation that s27l's `_SHARED_VISION_MODES` branch produces the intended behavior in production. Synthetic-only verification from s27l is now backed by live data.

## Audit completion (no Tier change)

Tier 1 ✅ 5/5 · Tier 2 ✅ #5/#6/#6/#7 + #8 C1-C4 ✅ (C5 LCU pollers optional, frozen-file approval needed) + #9 (avoid) · Tier 3 ✅ 5/5 · Tier 4 ✅ 3/3.

The Recent Coach Calls move was a **parked s27f follow-up**, not an audit item. No tier deltas.

## Operational backlog

- **2 unpushed commits** (s27l vision_tracker fix + s27m sub-page move). Cloud routine deadline 2026-05-10 — 9 days away. Push at start of next session.
- **Game-PC `/loop /process-bridge-tasks`** — bridge gauge was ~93 min stale at s27l session start; not re-checked this session. A live ARAM game is running so RC-side data is fresh; the bridge silence is independent.
- `RC-PatchRefresh` residual error code clears on Wednesday 2026-05-06.

## Next-session candidates

- **Easiest:** push the 2 backlog commits; optional stop point.
- **Easy:** ARAM-side feature follow-up — the s27l fix surfaces visibility but `vision_tracker._compute_enemies` still leaves `last_seen_zone=None` for shared-vision modes. Could add a coarse "alive on bridge" zone string for ARAM so the dashboard minimap caption isn't blank. Or: drive shared-vision logic into per-mode UI ("see all 3 enemies on map" badge). Both are small.
- **Easy:** Capture a screenshot of the new `#coach-calls` view next time the user has the dashboard idle (no live game) — verifies the visual layout matches expectation. Current commit is verified by content, not by render.
- **Medium:** **T2 #8 C5 (optional)** — LCU pollers. `lcu_client.py` frozen, needs approval. Low payoff.
- **Avoid:** T2 #9 DB compression (still high blast radius).

## Bootstrap for next session

1. Read CLAUDE.md (frozen list)
2. Read this hand-off (s27m) — the `view-section` + `body[data-view]` pattern is the canonical way to add a sub-page. To add another, hit these 3 spots: VIEW_IDS/LABELS in dashboard.js, menu button + `<section id="view-X" class="view-section" hidden>` in index.html, and the 3 CSS visibility-rule lists in dashboard.css. No `applyView` lazy-fetch hook needed if the data is already polled globally.
3. **Refresh tip**: dashboard `web/*` changes don't need an RC restart — Edge on the secondary display picks them up via Ctrl+F5. Useful to remember for any future UI-only commit.

---

# Session 27n — 2026-05-01 22:50 hand-off (ARAM "on_bridge" zone label)

> User picked candidate #2 from s27m — small follow-up to s27l. One commit,
> one RC restart, verified clean against the still-running ARAM game.
> Every alive ARAM enemy now reports `last_seen_zone="on_bridge"` instead
> of `None`, giving downstream consumers (minimap caption, coach prompts)
> a meaningful state string for the most common game mode.

## What shipped

| Commit | Type | Summary |
|---|---|---|
| (this) | feature | `core/vision_tracker.py:_compute_enemies` shared-vision branch now stamps `tracked["last_seen_t"] = game_time` and `tracked["last_seen_zone"] = "on_bridge"` whenever an alive enemy is processed in shared-vision mode (ARAM/KIWI). Dead enemies still skip the stamp (the `is_dead` short-circuit runs first), so a dead champion's `last_seen_zone` reflects their most recent alive sighting — correct semantics. **+5 LOC.** |

## Why "on_bridge" and not a coordinate-derived zone

Live Client emits `position: "NONE"` for ARAM, so we can't compute *where* on the bridge any given champion is. The existing `_aggregator_k(x, z)` function returns `"blue_side_bridge" / "mid_bridge" / "red_side_bridge"` based on (x+z)/296 percent — but with no coordinates we can't call it. Constant `"on_bridge"` is the honest data: "alive on Howling Abyss, exact position unknown to us." Consumers can render this as "5 on bridge" rather than "5 alive (location unknown)" or, worse, blank.

`_aggregator_k` stays in place — defensive; if Riot ever exposes ARAM positions, the SR path's `_zone_for(game_mode, x, z)` call would route through it automatically.

## Verification

- `py_compile` clean on `core/vision_tracker.py`
- restart_trigger.txt consumed (size=0 post-restart)
- RC PID 9624 → 2944, `last_reload_ok=true`
- Initial `game_poll_worker_age_s=15.3` (slightly elevated) settled to **3.0 within 6s** — transient post-restart latency, not a regression. ui_pulse stayed healthy throughout (0.4 → 1.5).
- All 6 dashboard endpoints 200
- 0 problem lines (Traceback / ImportError / AttributeError / tkinter / vision_tracker loop:) in 242 post-restart log lines
- **Live ARAM verification** (game still in progress from s27m):
  - 5 enemies, all 5 now report `last_seen_zone="on_bridge"`
  - 3 alive (Kassadin, Malphite, Poppy) → `visible=True, on_bridge`
  - 2 dead (Jayce, LeBlanc) → `visible=False, is_dead=True, on_bridge` — zone persists from last alive sighting (correct semantics)
- **Synthetic SR check**: CLASSIC mode with real position {x:7400, z:7400} → `last_seen_zone="mid"` — SR fog tracking unchanged.

## Audit completion (no Tier change)

Tier 1 ✅ 5/5 · Tier 2 ✅ #5/#6/#6/#7 + #8 C1-C4 ✅ + #9 (avoid) · Tier 3 ✅ 5/5 · Tier 4 ✅ 3/3.

s27n was a follow-up to s27l, not an audit item.

## Operational backlog

- **3 unpushed commits** (s27l vision_tracker fix + s27m sub-page move + s27n on_bridge label). Cloud routine deadline 2026-05-10 — 9 days away. Push at start of next session.
- **Game-PC `/loop /process-bridge-tasks`** — bridge gauge not re-checked this session; live ARAM data is fresh on RC-side independently of the bridge.
- `RC-PatchRefresh` residual error code clears on Wednesday 2026-05-06.

## Next-session candidates

- **Easiest:** push the 3 backlog commits; optional stop point.
- **Easy:** Capture screenshot of the new `#coach-calls` view next time the dashboard is idle (no live game) — verifies the visual layout. Current commit is verified by content, not by render.
- **Easy / minimap UX:** the minimap caption (`#mm-img-caption` in index.html) probably renders the legacy "missing for X seconds" template that doesn't fit shared-vision mode. Quick survey: `Grep "last_seen_zone\|missing_for" web/` to see where the new `on_bridge` string would surface, then a small JS branch that says "5 on bridge · shared vision" for ARAM modes instead of the per-enemy timer list.
- **Medium:** **T2 #8 C5 (optional)** — LCU pollers. `lcu_client.py` frozen, needs approval. Low payoff.
- **Avoid:** T2 #9 DB compression (still high blast radius).

## Bootstrap for next session

1. Read CLAUDE.md (frozen list)
2. Read this hand-off (s27n) — `tracked` dict accepts partial stamps (zone + t without pos), which is the pattern for shared-vision style branches. Any future "no positional data but enemies are observable" mode just needs a constant zone label, no coordinate plumbing.
3. If picking up the minimap caption follow-up: start with `Grep "mm-img-caption\|last_seen_zone" web/js/dashboard.js` to find the render path, then check what it does with empty/None zone strings today — the fix may simply be "render the new on_bridge string verbatim" or "special-case ARAM caption text."

---

# Session 27o — 2026-05-01 22:54 hand-off (push backlog + screenshot verify)

> User picked candidate (a) from s27n — pushed the 3-commit backlog and
> closed s27m's deferred visual verification of the `#coach-calls` sub-page.
> No code changes; ops + verification only.

## What shipped

| Action | Detail |
|---|---|
| `git push origin main` | `eaa35a8..29ed1e1` — s27l/s27m/s27n trio. Backlog → 0. Cloud routine deadline 2026-05-10 again safe. |
| Screenshot verify | Captured Game-PC monitor 1 with dashboard navigated to `https://192.168.8.230:8888/#coach-calls`. View badge reads `AUTO · COACH CALLS`, section heading + subtitle render correctly, two `/api/decisions/log` entries display with `CONTEST` tags ("Dragon in 18s — 3 enemies missing", "Baron in 30s — 3 enemies missing"), empty placeholder correctly hidden. **s27m's deferred visual verification is now closed.** |

## Bonus signal (still parked from s27n)

While dashboard was on default `last-match` view (pre-nav), MAP STATE panel only rendered the timeline bar — no `on_bridge` enemy presence visible. That **confirms** the s27n on_bridge stamp data isn't being consumed by the minimap caption renderer. Fresh evidence that the parked s27n minimap-UX follow-up is real work, not speculative.

## Audit completion (unchanged)

Tier 1 ✅ 5/5 · Tier 2 ✅ #5/#6/#6/#7 + #8 C1-C4 ✅ + #9 (avoid) · Tier 3 ✅ 5/5 · Tier 4 ✅ 3/3.

## Operational backlog

- **0 unpushed commits.** Origin/main current through `29ed1e1`.
- **Game-PC `/loop /process-bridge-tasks`** — bridge gauge ~115 min stale at session start (6916s per SessionStart probe). Same Game-PC-side issue.
- `RC-PatchRefresh` residual error code clears on Wednesday 2026-05-06.

## Next-session candidates

- **Easy / minimap UX:** s27n's parked minimap caption follow-up — now backed by visual evidence from this session's first capture (MAP STATE panel doesn't surface on_bridge). `Grep "mm-img-caption\|last_seen_zone" web/js/dashboard.js` to find the render path, then either render `last_seen_zone` verbatim or special-case shared-vision modes. ~10–30 LOC.
- **Easy / cosmetic:** Edge isn't currently fullscreen (visible browser chrome in the screenshot). User exited fullscreen to navigate. F11 restores the documented setup; no code change needed.
- **Medium:** **T2 #8 C5 (optional)** — LCU pollers. `lcu_client.py` frozen, needs approval. Low payoff.
- **Avoid:** T2 #9 DB compression (still high blast radius).

## Bootstrap for next session

1. Read CLAUDE.md (frozen list)
2. Read this hand-off (s27o) — visual-verify-after-UI-changes per `feedback_screenshot_after_ui_changes` is now confirmed working: capture Game-PC monitor 1 (1920×1280, secondary display via Duet), browser will show the dashboard if user is on it.
3. If picking up the minimap caption follow-up: the render path lives in `web/js/dashboard.js`; `data/vision_state.json` already updates every 0.75s with the new `last_seen_zone="on_bridge"` data per s27n verify.

---

# Session 27p — 2026-05-01 23:05 hand-off (MAP STATE pill — shared-vision render)

> User said "continue WAKEUP_NOTES" — picked s27o's parked minimap-UX
> follow-up. One commit, **no RC restart** (web/* are static, Edge picks
> them up on refresh). Verified live against the in-progress ARAM game from
> s27m/s27n — pill now reads `● 3 on bridge · 2 dead 0s ago` instead of
> being hidden.

## What shipped

| Commit | Type | Summary |
|---|---|---|
| (this) | feature | `web/js/dashboard.js` — split the MAP STATE pill render into SR vs shared-vision paths. **(1)** Refactored `_renderMmStateLine(host, allyCount, enemyCount)` → `_renderMmStateLine(host, countText)` so callers build their own count line. SR site at L2511 now passes `` `${allyCount} ally · ${enemyCount} enemy` `` verbatim. **(2)** In `renderMinimapCanvases`, when `state.mode === "aram"`, skip the position-based pill render entirely (positions are always empty in shared-vision; would otherwise hide the pill). **(3)** In `refreshVisionOverlay`, hoisted the `/api/vision-state` fetch above the imgWrap-hidden early-return, then added a shared-vision branch driven by `vs.summary.visible_count` / `dead_count`: renders `` `${visibleCount} on bridge · ${deadCount} dead` `` via `_renderMmStateLine`. Caches the count signature on `MM.status._sharedSig` so we only force a heart-pulse + age-reset when numbers change; idle ticks just refresh `_lastT` to keep "Xs ago" pinned at 0s. SR path also clears `_sharedSig` on entry so a mode swap doesn't suppress the next shared-vision redraw. **+~30 LOC, 1 file.** |

## Why split SR vs shared-vision in two places

`renderMinimapCanvases` runs from state-poll (~1.5s); `refreshVisionOverlay` runs every 500ms. They both target `MM.status`. In SR-style modes the position-based path knows `ally/enemy` counts at state-poll time, so let it own the pill. In shared-vision modes positions are always empty, so state-poll has nothing useful to render — let vision overlay (which already fetches vision_state for the dot canvas) own it. Split avoids races (the slower poll would clobber the faster one); the `_sharedSig` cache avoids the heart-pulse re-firing every 500ms.

## What this fixes (s27n's parked follow-up)

s27n added `last_seen_zone="on_bridge"` to vision_state.json for shared-vision modes, but no consumer was reading it. s27o's screenshot bonus signal flagged the gap: MAP STATE panel "only rendered the timeline bar — no on_bridge enemy presence visible". Root cause: the pill render path in `renderMinimapCanvases` checked `p.positions?.allies/enemies`, which Live Client emits as `"NONE"` (not arrays) in ARAM, so `allyCount === 0` always → the `else` branch hid the pill. Fix routes the data flow through vision_state.summary instead.

## What this DOESN'T fix (intentionally)

- The dot-canvas overlay (`VT_OVERLAY`) still draws nothing in shared-vision because there are no `last_seen_pos` values. That's correct — Riot doesn't expose ARAM positions. The pill carries the meaningful signal; the canvas stays empty. If Riot ever exposed ARAM positions, the existing dot-render path would activate automatically (no code changes needed).
- The `_renderMmStateLine` heart-pulse animation is still the SR-style 1s rhythm. In shared-vision modes the pill text only changes when someone dies/respawns (rare), so the pulse fires accurately on those events — anti-feature would be it pulsing every 500ms tick. Solved by `_sharedSig` change-detection.

## Verification

- **JS served by dashboard**: `curl -k https://127.0.0.1:8888/js/dashboard.js` → contains `sharedVision` (4×), `VT_SHARED_VISION` (2×), `_sharedSig` (3×), and the literal `on bridge ·` (1×). No RC restart needed.
- **Live ARAM verification** (game still in progress from s27m/s27n/s27o, `game_mode=KIWI`):
  - `/api/vision-state` summary: `{visible_count: 4, missing_count: 0, dead_count: 1, total: 5}` then later `{visible_count: 3, dead_count: 2}` as a second enemy died
  - **Game-PC monitor 1 screenshot** captured via `mcp__gamepc__capture_monitor` (bridge dead per SessionStart, used direct MCP path bypass): MAP STATE panel shows `● 3 on bridge · 2 dead 0s ago` under the minimap image. Heart pulse and age suffix render correctly.
- **No regressions on SR**: refactored `_renderMmStateLine` signature; only one production caller (the SR path), updated atomically. The `state.mode === "aram"` check matches `core/game_snapshot.py`'s ARAM/KIWI → MODE_ARAM normalization, so KIWI (ARAM Mayhem) correctly takes the shared-vision branch.

## Cross-MCP-vs-bridge note

Bridge gauge was ~2h stale at session start (Game-PC `/loop /process-bridge-tasks` still dead). Used `mcp__gamepc__capture_monitor` directly (the gamepc MCP server at :8892, listed alive in SessionStart probe) instead of routing the capture through the bridge. Worked first try. Future sessions: when the bridge is red but the gamepc MCP is up, direct MCP calls are the workaround for `feedback_screenshot_after_ui_changes` verification. (The bridge's value is async/round-trip; for one-shot screenshots the MCP path is fine.)

## Audit completion (no Tier change)

Tier 1 ✅ 5/5 · Tier 2 ✅ #5/#6/#6/#7 + #8 C1-C4 ✅ + #9 (avoid) · Tier 3 ✅ 5/5 · Tier 4 ✅ 3/3.

s27p was a parked s27n follow-up, not an audit item.

## Operational backlog

- **1 unpushed commit** (this). Cloud routine deadline 2026-05-10 — 9 days away. Push at start of next session.
- **Game-PC `/loop /process-bridge-tasks`** — bridge gauge ~2h stale at session start. Workaround for screenshot verification documented above. Underlying fix is still Game-PC-side.
- `RC-PatchRefresh` residual error code clears on Wednesday 2026-05-06.

## Next-session candidates

- **Easiest:** push the commit; optional stop point.
- **Easy:** the MAP STATE pill now reports a count, but the dashboard COMP STRIPS (top of `enemy-comp` strip in the `last-match` view) probably still don't reflect ARAM "this enemy is alive on map RIGHT NOW" status. If that's user-visible, surfacing `vision_state.enemies[champ].is_dead` on the enemy comp tiles (greying the dead, full color the alive) is a small JS pass.
- **Easy:** Game-PC bridge fix — when the user opens Game-PC Claude next, kick `/loop /process-bridge-tasks` back up. RC watchdog correctly surfaces the outage; fix isn't on RC side.
- **Medium:** **T2 #8 C5 (optional)** — LCU pollers. `lcu_client.py` frozen, needs approval. Low payoff.
- **Avoid:** T2 #9 DB compression (still high blast radius).

## Bootstrap for next session

1. Read CLAUDE.md (frozen list)
2. Read this hand-off (s27p) — when the bridge is red but gamepc MCP is up (per SessionStart probe), prefer `mcp__gamepc__capture_monitor` directly for one-shot screenshot verification. Saves a session waiting for the bridge.
3. The pill-split pattern (state-poll for SR, vision-overlay for shared-vision, with `_sharedSig` change-detection) is the model for any future "two refresh paths fighting over the same DOM" case.

---

# Session 27q — 2026-05-01 23:05+ hand-off (push to origin)

> User said "commit to github". Working tree was clean — the prior session
> (s27p) had already committed `957dab7` (MAP STATE pill) but never pushed.
> This session was a one-shot `git push origin main`. **No code changes, no
> RC restart.**

## What shipped

| Action | Detail |
|---|---|
| `git push origin main` | `29ed1e1..957dab7  main -> main`. origin/main is now caught up at `957dab7` (MAP STATE pill). |

## State after

- Local `main` == `origin/main` == `957dab7`.
- **Unpushed commit count: 0.** Cloud-routine deadline 2026-05-10 (~9 days)
  is no longer at risk of clone-empty-branch failure.
- RC PID + bridge state per SessionStart probe at 23:03:50: PID 2944,
  mode=game, last_reload_ok=True; bridge gauge ~2h stale (still the
  Game-PC `/loop /process-bridge-tasks` outage); Game-PC LCU phase
  `EndOfGame` (game just ended).

## Anomalies surfaced by SessionStart probe (not addressed this session)

- `RC-PatchRefresh` last_result `2147942402` (0x80070002 — file not found).
  Memory `project_rc_patchrefresh_fixed` says the script-level fix is in
  but the residual error code only clears on the next scheduled run
  (Wednesday 2026-05-06). Ignore until then; if it re-fires post-Wed,
  re-investigate.
- Bridge auto-flow age `7888s` (~2h). Watchdog (s27, 22248fe) is correctly
  surfacing this — fix is Game-PC-side (`/loop /process-bridge-tasks`).

## Next-session candidates

Same as s27p's list, minus "push the commit":

- **Easy:** ARAM enemy-comp tile alive/dead greying via
  `vision_state.enemies[champ].is_dead` (s27p's parked follow-up).
- **Easy:** kick `/loop /process-bridge-tasks` back up on Game-PC Claude.
- **Medium:** T2 #8 C5 (LCU pollers) — frozen file, low payoff.
- **Avoid:** T2 #9 DB compression.

## Bootstrap for next session

1. Read CLAUDE.md (frozen list).
2. Skim s27p (MAP STATE pill pattern) and s27q (this push).
3. Working tree clean, origin caught up — start fresh.

---

# Session 27r — 2026-05-01 23:30 hand-off (ARAM dead-tile greying — reverted, no target DOM)

> User said "continue WAKEUP_NOTES" — picked s27q's top easy candidate
> (ARAM enemy-comp tile alive/dead greying via vision_state).
> Implemented, committed (`504d9af`), then **reverted on verify** when
> the targeted DOM was found to not exist. **No code shipped this session.**
> Origin/main still at `957dab7`. Memory updated to prevent re-chasing
> this ghost.

## What happened

| Step | Detail |
|---|---|
| 1. Implemented | Added `data-champ` attribute to `renderTeamTile`, new `_applyVisionDeadState()` helper that toggles `.dead` on enemy-strip tiles in shared-vision modes (ARAM/KIWI), wired the cache into `refreshVisionOverlay`. JS syntax-clean (`node --check`). +23 LOC. Committed as `504d9af`. |
| 2. Verified | curl-fetched `/js/dashboard.js`, confirmed 8 occurrences of new symbols (matches expected count). Captured Game-PC monitor 1: dashboard renders, MAP STATE pill from s27p still works (`5 on bridge · 0 dead`). **No enemy tile strip visible in the screenshot.** |
| 3. Investigated | `curl -sk https://127.0.0.1:8888/ \| grep -ci 'team-tile\|enemy-strip\|ally-strip'` → **0 hits**. `git log -S "enemy-strip-row" -- web/` → only the 2 commits referencing it (initial + s27r). The IDs `enemy-strip`, `enemy-strip-row` (and ally counterparts) **have never existed in any served HTML in the project's git history**. |
| 4. Reverted | `git reset --soft HEAD~1` + `git restore --staged` + `git checkout --`. Working tree clean. |

## Root cause

`web/js/dashboard.js` declares `renderAllyStrip`, `renderEnemyStrip`, and `renderTeamTile` (~lines 1810-1985) and calls them per state-poll from `renderMinimap` (line ~2497) — but the DOM IDs they look up (`ally-strip-row`, `enemy-strip-row`, `ally-strip`, `enemy-strip`) appear nowhere in `web/index.html` or `web/legacy_index.html`. The functions early-return on `if (!row || !wrap) return;` every call. The CSS rules at `web/css/dashboard.css:1803-1940` (`.team-tile`, `.enemy-strip`, `.team-tile.dead`) are also orphan.

WAKEUP s27p mentioned "the dashboard COMP STRIPS (top of `enemy-comp` strip in the `last-match` view)" as a parked candidate. That description was based on a misperception — the strip doesn't exist in the production dashboard. The implicit "last match" view (default `<main>` content per `web/index.html:741-744` comment) shows RIGHT NOW + NEXT + MAP STATE + STATS + ITEM BUILD — no per-champion enemy tiles.

## What was saved as memory

`reference_orphan_team_strips.md` — added to `MEMORY.md` index. Covers:
- Where the orphan functions/IDs/CSS live
- Why s27p's "last-match enemy-comp strip" candidate has no target
- The 3-step path if a future session genuinely wants per-enemy alive/dead visualization (add markup → reuse orphan CSS → wire `vision_state.is_dead`)

## Audit completion (unchanged)

Tier 1 ✅ 5/5 · Tier 2 ✅ #5/#6/#6/#7 + #8 C1-C4 ✅ + #9 (avoid) · Tier 3 ✅ 5/5 · Tier 4 ✅ 3/3.

## Operational backlog

- **0 unpushed commits.** Origin/main current through `957dab7`.
- **Game-PC `/loop /process-bridge-tasks`** — bridge gauge ~2.5h stale at session start (9110s per SessionStart probe). Same Game-PC-side issue.
- `RC-PatchRefresh` residual error code clears on Wednesday 2026-05-06.

## Next-session candidates (revised — s27q's top candidate is now eliminated)

- **Easy / new feature:** Decide whether per-enemy alive/dead visualization is wanted on the home/last-match view at all. If yes, ship the 3-step path documented in `reference_orphan_team_strips`: add `<section id="enemy-strip">` markup to index.html, the orphan `.team-tile` CSS already covers styling, then re-add the `_applyVisionDeadState` helper. ~50-80 LOC across 2 files. Single commit.
- **Easy / Game-PC side:** kick `/loop /process-bridge-tasks` back up on Game-PC Claude.
- **Medium:** **T2 #8 C5 (optional)** — LCU pollers. `lcu_client.py` frozen, needs approval. Low payoff.
- **Avoid:** T2 #9 DB compression (still high blast radius).

## Bootstrap for next session

1. Read CLAUDE.md (frozen list).
2. Read `reference_orphan_team_strips` memory before touching any team-strip rendering — saves the same investigation cycle.
3. Working tree clean; origin caught up at `957dab7`. No carry-over.
4. **Verification lesson:** when adding rendering code, confirm the target DOM element exists in served HTML *before* committing — `curl -sk https://127.0.0.1:8888/ \| grep -i 'target-id'` is the 5-second check. Saves a revert.

---

# Session 27s — 2026-05-02 00:08 hand-off (T2 #8 C5 ship — LCU pollers async)

> User pre-approved the frozen-file touch for `lcu_client.py` ("2 approved").
> One commit, one RC restart, verified clean during a live ARAM game (Aram
> Coach hot-reattached and fired 4 Haiku calls within ~30s of the new PID
> coming up). **All 3 LCU pollers now ride the AppLoop in production.**
> T2 #8 is now **fully complete (C1-C5 ✅)** — Tier 2 only #9 (DB
> compression, avoid) remains.

## What shipped

| Commit | Audit | Summary |
|---|---|---|
| (this) | T2 #8 C5 | All 3 LCU pollers gain `_*_async` siblings + `start*` branches that prefer the AppLoop via `app._loop.get_loop()` and fall back to a daemon thread when no loop exists (tests, standalone harnesses). Same pattern as C4. **`lcu/lcu_client.py` (frozen, pre-approved):** added `import asyncio` + `Optional/Any` typing, `self._task` attr, refactored `_auto_accept_loop` body into a shared `_auto_accept_tick()` (sync, used by both paths), added `_auto_accept_loop_async` that wraps the tick in `asyncio.to_thread` + `asyncio.sleep`. `start_auto_accept` branches on `get_loop()`; `stop_auto_accept` cancels `self._task`. **`lcu/lcu_rune_writer.py`:** identical pattern — `_run_async` wraps `self._poll` in `to_thread`, `start()` branches on get_loop(), `stop()` cancels the task. **`lcu/lcu_postgame_collector.py`:** trickier (event-driven, not poll-driven). Refactored `_run` body into a shared `_capture_after_trigger(game_mode)` that owns the EOG-poll/HTTP burst. `_run_async` does `await asyncio.to_thread(self._trigger.wait, 30.0)` + `await asyncio.to_thread(self._capture_after_trigger, ...)` — the threading.Event still drives signaling (since `trigger()` is called from game_lifecycle on another thread), but the wait+burst no longer block the AppLoop. **+~80 LOC, 3 files.** |

## Why threading.Event for the postgame trigger

`PostgameCollector.trigger(game_mode)` is called from `app/_game_lifecycle.py` when a game ends — that runs on the AppLoop thread, but the trigger is consumed asynchronously by the collector's loop. Using `asyncio.Event` would require either the trigger sender to be on the same loop (it is, but it's also called from worker threads in some paths) or an extra `loop.call_soon_threadsafe(event.set)`. `threading.Event` with `await asyncio.to_thread(self._trigger.wait, 30.0)` works for both senders without ceremony — wait blocks on a worker thread, returns to the event loop. Same approach the C4 work used for `_stop` events.

## Restart verification

| Process | Old PID → New PID | Why |
|---|---|---|
| RC main | 2944 → 5268 | Pick up T2 #8 C5 |

- `last_reload_ok=true` immediately
- `ui_pulse_age_s=0.6` (well under 6s threshold)
- `game_poll_worker_age_s=0.6` (well under 12s threshold)
- All 6 dashboard endpoints 200 (`/api/state`, `/api/health/all`, `/api/decisions`, `/api/decisions/log`, `/metrics`, `/api/vision-state`)
- Boot log lines confirm async path:
  - `Auto-accept started (1.0s interval, async)`
  - `RuneWriter started (172 champion IDs loaded, async)`
  - `PostgameCollector started (async)`
- Live ARAM game (KIWI mode, in progress at restart): **4 Haiku calls fired within ~30s** (`rc_coach_calls_total{purpose="aram_coach"} 4`, latency sum 13.7s = ~3.4s avg, vision tokens granted 3/0 denied). Confirms the async coach path (C3) interacts cleanly with the now-async LCU pollers (C5).
- 0 problem-pattern lines (`ERROR | Traceback | ImportError | AttributeError | tkinter`) in 272 post-restart log lines

## What's now non-threading-shaped (T2 #8 done)

T2 #8 success criteria from s27f all green:
1. ✅ `^import tkinter` → 0 hits in production tree (s27h)
2. ✅ `tk\.Tk\(\)` → 0 production hits (s27g)
3. ✅ `root\.after` → 0 hits in `app/` and `coaches/` (s27g)
4. ✅ `_base_coach._poll_loop` and `_vision_loop` are `async def` (s27i)
5. ✅ `restart_trigger.txt` workflow still works end-to-end
6. ✅ All 5 dashboard endpoints 200, ARAM smoke clean
7. ✅ CLAUDE.md "Headless mode" section updated (s27g)

Plus the C4/C5 expansion: every long-running poller in production rides the AppLoop. The only remaining threading sources are (a) `dashboard/server.py` ThreadingHTTPServer (out of T2 #8 scope), (b) `core/hotkeys.py` Win32 polling (no benefit from converting), and (c) `to_thread` worker-pool offload of blocking I/O inside async tasks (intentional — keeps the AppLoop responsive).

## Audit completion (updated)

Tier 2 architecture & reliability:
- ✅ #5 dashboard helper-shake (s27)
- ✅ #6 dashboard helper-shake (s27)
- ✅ #6 tkinter shim removal (s27c)
- ✅ #7 bridge auto-flow watchdog (s27)
- ✅ **#8 daemon threads → asyncio** — C1 ✅ (s27g), C2 ✅ (s27h), C3 ✅ (s27i), C4 ✅ (s27j), **C5 ✅ (THIS)**
- ⏳ #9 DB compression (high blast radius, avoid)

Tier 1 still 5/5, Tier 3 still 5/5, Tier 4 still 3/3. **#9 is the only remaining audit item across all tiers.**

## Operational backlog

- **1 unpushed commit** (this). Cloud routine deadline 2026-05-10 — 8 days away. Push at start of next session.
- **Game-PC `/loop /process-bridge-tasks`** — bridge gauge ~3.3h stale at restart time (11,775s per `rc_bridge_gamepc_result_age_seconds`). Same Game-PC-side issue.
- `RC-PatchRefresh` residual error code clears on Wednesday 2026-05-06.

## Next-session candidates (post-T2 #8)

- **Easiest:** push the C5 commit; **clean stopping point — every Tier 1-3 audit item is done**, only #9 (avoid) remains.
- **Easy / Game-PC side:** kick `/loop /process-bridge-tasks` back up on Game-PC Claude.
- **Easy / new feature ideas (not from audit):**
  - Per-enemy alive/dead tiles on home/last-match view (needs `<section id="enemy-strip">` markup added to `web/index.html` first; orphan CSS in `dashboard.css:1803-1940` already styles it). See memory `reference_orphan_team_strips`.
  - Improve ARAM minimap coords if Riot ever exposes positions (today: `position: "NONE"` per s27k memory; the existing `_aggregator_k(x,z)` would activate automatically if positions appear).
- **Avoid:** T2 #9 DB compression — high blast radius on 1.7 GB rewind_history.db, low real benefit.

## Bootstrap for next session

1. Read CLAUDE.md (frozen list).
2. Read this hand-off (s27s) — the C4/C5 pattern (sibling `_loop_async` next to `_loop`, `start()` branches on `get_loop()` with thread fallback) is now applied to **every** poller in the codebase. If you add a new poller, follow this pattern.
3. **Postgame nuance:** the `threading.Event` + `asyncio.to_thread(event.wait, ...)` pattern is the right call for any "external sender wakes a long-running consumer" case where the sender lives on multiple threads. Pure-AppLoop senders should prefer `asyncio.Event`; mixed-source senders should stay on `threading.Event`.
4. Working tree clean after push; origin caught up. No carry-over.

---

# Session 27t — 2026-05-02 00:38 hand-off (enemy-strip candidate killed; memory hardened)

> User said "continue WAKEUP_NOTES" — picked s27s's top "Easy / new feature"
> candidate (per-enemy alive/dead tiles via the orphan team-strip render
> functions). **No code shipped.** Investigation surfaced two independent
> blockers that make this NOT an easy task; updated `reference_orphan_team_strips`
> memory so future sessions don't re-attempt without the full picture.

## What happened

| Step | Detail |
|---|---|
| 1. Verified state | Origin/main caught up at `7e7c8af` (s27s C5 already pushed). Working tree clean. RC PID 5268 alive, mode=game (live ARAM in progress, KIWI). |
| 2. Re-read s27r memory | `reference_orphan_team_strips` documented "step 1: add `<section id="enemy-strip">` markup". Began drafting the markup add. |
| 3. Inspected `web/index.html:458` | **Smoking gun**: artifact comment `<!-- Ally/Enemy team strips removed 2026-04-23: giving minimap panel more visual space. -->`. Strips were *deliberately* removed; the orphan JS+CSS exist only because `feedback_field_remove_visual_only` mandates JS hooks survive UI removals. |
| 4. Verified the data plumbing | Orphan JS reads `p.enemy_comp`; server-side `dashboard/_liveclient.py:116` emits `out["enemy_team"]`. **No rename layer between them.** Even if markup were re-added, `renderEnemyStrip(p.enemy_comp, ...)` would receive `undefined` → silent no-op. `p.ally_comp / team_comp / ally_spells / enemy_spells / enemy_respawns / target_priority` are all absent from current state pipeline. |
| 5. Updated memory | `reference_orphan_team_strips.md` rewritten to flag both blockers prominently. `MEMORY.md` index line updated to reflect "not easy". |

## Why this matters

s27p, s27q, and s27s all ranked "per-enemy alive/dead tiles" as an **easy** candidate based on s27r's analysis. s27r found blocker #1 (no DOM) but missed:
- **Blocker #1 is a deliberate product decision** — re-adding the strips reverses the 2026-04-23 visual-space call, not just enables dead code
- **Blocker #2 (data field mismatch)** — never surfaced in s27r's investigation. The orphan JS would still no-op silently even with markup added.

If a future session genuinely wants this feature, the *real* path:
1. **Get explicit user approval** to undo the 2026-04-23 visual-space decision
2. Server-side: rename or alias `enemy_team` → `enemy_comp` in `dashboard/_liveclient.py`; populate `ally_comp` from the same `allPlayers` filter
3. HTML markup add (placement is its own design decision — inside or outside `<section id="minimap">`?)
4. CSS already covers it via the orphan rules at `dashboard.css:1803-1940`
5. Then optional: ARAM dead-state greying via `vision_state.enemies[champ].is_dead` (the s27r code that got reverted)

That's at least 3 commits across 3 files, not the "single small commit" s27s implied.

## Audit completion (unchanged)

Tier 1 ✅ 5/5 · Tier 2 ✅ #5/#6/#6/#7 + #8 C1-C5 ✅ + #9 (avoid) · Tier 3 ✅ 5/5 · Tier 4 ✅ 3/3.

s27t was a research-and-document outcome — no code shipped, no audit deltas.

## Operational backlog

- **0 unpushed commits** going in. **1 unpushed commit** going out (this WAKEUP_NOTES + memory update). Cloud routine deadline 2026-05-10 — 8 days away.
- **Game-PC `/loop /process-bridge-tasks`** — bridge gauge ~3.7h stale at session start (13,375s per SessionStart probe). Same Game-PC-side issue.
- `RC-PatchRefresh` residual error code clears on Wednesday 2026-05-06 (4 days away).

## Next-session candidates

The s27s candidate list shrinks: "per-enemy alive/dead tiles" is now correctly tagged as **non-easy / needs UI approval**. Remaining options:

- **Easiest:** push this hand-off; clean stop.
- **Easy / Game-PC side:** kick `/loop /process-bridge-tasks` back up on Game-PC Claude. Not RC-side.
- **If user wants the team-strip feature anyway:** explicit approval to revert the 2026-04-23 removal, then ship the 3-commit plan above.
- **Avoid:** T2 #9 DB compression (still high blast radius).
- **Speculative:** ARAM minimap coords if Riot ever exposes positions (no work to do today; existing `_aggregator_k(x,z)` would activate automatically).

Note: every Tier 1-3 audit item is still done. The audit-driven backlog is exhausted apart from #9 (avoid). New work past this point is **product feature work**, not audit work.

## Bootstrap for next session

1. Read CLAUDE.md (frozen list).
2. Read this hand-off (s27t) — the orphan-strip rabbit hole is now fully documented in `reference_orphan_team_strips`. Trust the memory; don't re-investigate.
3. **Investigation lesson:** when memory says "step 1 was never done", verify the *reason* before treating it as a typo of intent. The 2026-04-23 removal comment was 5 lines from the proposed insertion site; reading the surrounding HTML before drafting the markup change would have caught it in step 1, not step 3.
4. Working tree state at end-of-session: clean (this hand-off is its own commit).

---

# Session 27u — 2026-05-02 00:55 hand-off (CLAUDE.md TFT-vision line sync)

> User said "continue WAKEUP_NOTES" again after s27t. Audit backlog is
> already exhausted; looked for stale-doc / known-bug cleanups instead.
> Found CLAUDE.md carrying a stale "TFT vision is broken post-migration"
> claim that was already fixed at the code level. One-line doc sync.

## What shipped

| Commit | Type | Summary |
|---|---|---|
| (this) | docs | `CLAUDE.md` line 109-110: replaced "TFT vision still uses local `ImageGrab` and is broken post-migration — needs the same relay refactor" with the current truth: both `tft/tft_vision_reader.py` and `tft/tft_ocr_reader.py` were already migrated to the `/latest-frame` relay (audit comments at lines 111-118 and 53-61 of those files prove the migration happened on 2026-04-22 and during cycle 11 / 2026-04-25 respectively). Added a positive statement of where `ImageGrab` is *correctly* still used: Game-PC-side tools (`tools/gamepc_screen_agent.py`, `tools/gamepc_mcp_server.py`, `ops/rc_file_bridge.py`) — Game-PC has the screen, so those calls are correct. **+5 LOC, -2 LOC in CLAUDE.md.** No code changes; no RC restart. |

## How the staleness was caught

s27t closed the obvious "easy" candidate with a Document outcome rather than code. With the audit backlog exhausted, scanning for stale-doc / known-bug items was the cleanest productive use of the session. CLAUDE.md was the natural target — it's the canonical "what's broken now" reference for future sessions. A `Grep "ImageGrab" --include="*.py"` confirmed the only production-tree callers are Game-PC-side, which means TFT vision is *not* broken — the doc was just out of date.

## What this prevents

Before this fix, a future session reading CLAUDE.md might:
- Pick "TFT vision relay refactor" as a productive task
- Spend an hour discovering both files have already been migrated
- End with a doc-sync commit that does the same work this session does in 2 minutes

That's exactly what would have happened to me this session if I hadn't stopped to verify the claim before working.

## Audit completion (unchanged)

Tier 1 ✅ 5/5 · Tier 2 ✅ #5/#6/#6/#7 + #8 C1-C5 ✅ + #9 (avoid) · Tier 3 ✅ 5/5 · Tier 4 ✅ 3/3.

s27u was a doc-sync, not an audit item.

## Operational backlog

- **1 unpushed commit** (this) once committed. Cloud routine deadline 2026-05-10 — 8 days away.
- **Game-PC `/loop /process-bridge-tasks`** — bridge gauge ~3.7h stale at session start. Same Game-PC-side issue.
- `RC-PatchRefresh` residual error code clears on Wednesday 2026-05-06.

## Next-session candidates

The audit backlog is still exhausted apart from #9 (avoid). Possibilities:

- **Easiest:** push this commit; clean stop.
- **Easy / Game-PC side:** kick `/loop /process-bridge-tasks` back up on Game-PC Claude.
- **Easy / doc audit:** scan the rest of CLAUDE.md (and README, ROADMAP, INFOGRAPH per `feedback_no_history_rewrite`) for any *other* stale claims like the TFT line. Quick win if any are found; cheap no-op if not. Low risk.
- **Easy / known issue from CLAUDE.md priority 3:** Tiered vision still 🟡 — needs (a) calibration against an in-game frame and (b) coach-side routing that calls Tesseract for cheap fields and only escalates to Sonnet when needed. The pieces are in place (`/api/ocr`, `/api/ocr-crop`, regions in `data/vision_regions.json`). One scoped session per piece.
- **Avoid:** T2 #9 DB compression.
- **Speculative:** team-strip feature if user *explicitly* approves the 2026-04-23 visual-space reversal (per s27t memory).

## Bootstrap for next session

1. Read CLAUDE.md (frozen list) — now slightly more trustworthy after this sync.
2. Read this hand-off (s27u). The pattern: when a CLAUDE.md claim is suspicious, `Grep` the codebase before treating it as truth.
3. **Doc-sync discipline:** only update CLAUDE.md / living docs. `feedback_no_history_rewrite` says don't touch dated artifacts (AUDIT_*, PHASE_*, ARCH-* docs, the `(2026-04-19)` priority snapshot header).

---

# s28 hand-off — 2026-05-02 (RC↔Peer bridge live; inheritance arc closed)

> Long session, two arcs. **Arc 1**: Peer-VIP inheritance — RC sent the
> WT/PS7 + session-control discipline + bridge contract; Peer sent back
> a parity report showing they applied nearly everything verbatim plus
> two bug fixes RC mirrored. **Arc 2**: cross-Claude bridge stood up
> end-to-end over Tailscale. RC ↔ Peer now exchanging acks/asks/notes
> via `/api/bridge/inbox` without operator file relay. Currently
> running RC PID 11836; supervisor PID 10796. **5 commits this session,
> all pushed (origin/main at `7307e6a`).**

## What just shipped this session (in order)

| Commit | Type | Summary |
|---|---|---|
| `a38d002` | docs | Seed `docs io RC peer/` with 5 durable inheritance docs (3 Peer originals + RC update + WT inheritance). `.gitignore` patterns for `*ASKS*`/`*BUNDLE*`/`*POST_UPDATE*` so round-trip scratch auto-ignores. |
| `3b22bce` | fix | `ops/rc_supervisor.py`: pythonw stub pid latch + `os.replace` retry-with-backoff. Both bugs surfaced by Peer's first multi-child supervisor smoke; RC mirrored defensively. Frozen-file edit (authorized). Activated via supervisor restart (taskkill 4996 + `schtasks /Run RC-Supervisor` → adopted Main 3312 cleanly). |
| `64de1ca` | docs | WT inheritance hardening (explicit pwsh profile block per Peer's parity-reply flag) + session control inheritance + bridge contract from Peer. |
| `7e80513` | feat | RC bridge: `core/bridge.py` (config readers + outbound `send()` via stdlib urllib) + `dashboard/routes_bridge.py` `/api/bridge/inbox` POST (Bearer guard) + `/api/bridge/status` GET + `ops/local_paths.example.json` template. Activated via Main restart. |
| `7307e6a` | chore | `.gitignore` hardening: `*SECRET*`, `*HANDSHAKE*`, `*PIVOT*`, `*REPLY*`, `*TOKEN*`, `*KEY*` patterns + `ops/local_paths.json` (the actual secret store). |

## RC restart state

- **Main PID 11836** (was 3312 → 9432 → 2956 → 11836 across four
  restarts: bridge endpoint activation, bridge URL IP form, bridge URL
  MagicDNS form, plus the supervisor activation cycle). Each restart
  verified clean (`last_reload_ok=true`, new pid).
- **Supervisor PID 10796** (was 4996 — replaced once this session via
  `taskkill /F` + `schtasks /Run RC-Supervisor` → adopted running Main).
  msvcrt byte-range lock cleanly released and reclaimed.

## Cross-Claude bridge — operational state (new since s27u)

- **Transport**: Tailscale free Personal plan. Both nodes in tailnet
  `tailc150de.ts.net` under `<operator-email>`. Direct
  peer-to-peer (`tailscale status` shows "active; direct").
  - **RC** = `legion-rc.tailc150de.ts.net` / `100.70.22.55`
  - **Peer** = `peer-host.tailc150de.ts.net` / `<peer-tailnet-ip>`
    (renamed from `desktop-ctbma25` mid-setup — see
    `reference_tailscale_magicdns_rename.md`)
- **Auth**: 43-char urlsafe-base64 bearer in each side's
  `ops/local_paths.json` (gitignored). Identical on both sides.
- **Endpoints live**: RC inbox `/api/bridge/inbox` (POST, Bearer-guarded,
  503/401/400/200 path); RC outbound `from core import bridge;
  bridge.send(...)`; Peer symmetric.
- **Path-name asymmetry**: RC's read endpoint is at `/api/bridge` (legacy
  pre-contract); Peer's at `/api/bridge/messages` (per contract). Tracked
  in `feedback_rc_peer_bridge_live.md`. Future v1 alignment is a 2-line
  add (route the same handler at both paths).
- **First handshake**: bidirectional, `ts ~1777745800`. Peer→RC and
  RC→Peer both `(True, 'ok')`, both persisted to bridge logs.
- **Live use**: operator's "ask peer what's next" → bridge → Peer replied
  via bridge → answer parsed, no operator-mediated file relay needed.
  This is the new pattern.

## Memory entries written this session

- `reference_pythonw_launcher_stub` — pid mismatch under venv pythonw stub
- `reference_os_replace_winerror5` — Windows transient PermissionError on rename
- `reference_rc_peer_bridge` — endpoint + config + opt-in semantics
- `feedback_rc_peer_bridge_live` — bridge live timestamp + path asymmetry
- `reference_tailscale_magicdns_rename` — Tailscale hostname-rename gotcha

## Operational backlog

- **Bridge monitor mirror** — Peer shipped their `bridge_monitor_agent.py`
  (commit `b2e30b5`, always-on auto-pong sidecar). RC needs the
  symmetric agent. Design spec landed at
  `docs io RC peer/PEER_VIP_BRIDGE_MONITOR_FOR_RC_2026-05-02.md`
  (now tracked — committed in s28). **Top of next-session queue.**
- **Cloud routine deadline 2026-05-10** — 8 days. Origin/main is current
  through `7307e6a`. Repo OAuth still untested on private
  `Remus3/riot-commander` (per `project_verify_github_access_cloud_routine`).
- **Game-PC `/loop /process-bridge-tasks`** — old Legion↔Game-PC bridge
  separate from the new RC↔Peer bridge. Watchdog still surfaces silence;
  Game-PC-side fix.
- **Tiered vision** still 🟡 (CLAUDE.md priority 3, unchanged).

## Next-session candidates (ranked)

1. **Bridge monitor mirror** — design doc in hand. RC stack uses different
   agent base than Peer (no multi-child supervisor on RC). Adapt to RC's
   pattern: probably a daemon thread spawned from `dashboard/server.py`
   alongside `vision_tracker` and `obs_publisher` — same shape as those.
   Filter: `ts > last_seen_ts AND not source.startswith("rc") AND source
   != "self-test"`. Auto-pong gate: `kind=task AND
   summary.strip().lower()=="ping" AND target.lower()=="rc"`. Reply with
   `source="rc-monitor", kind="result", summary="pong",
   in_reply_to=<original-id>`. State at `data/bridge_monitor_state.json`,
   atomic-written, mirrors Peer's shape.
2. **Push-channel for bridge inbox** (v1 conversation) — replace the
   2s polling with an internal SSE/push from `_bridge_log.bridge_post()`
   so the monitor sees inbound in <100ms instead of <2s. Peer mentioned
   this as their v1 thinking too. Touches frozen `dashboard/_bridge_log.py`.
3. **Cloud routine OAuth verification** — open `claude.ai/code/routines/<id>`
   and confirm GitHub token is valid for `Remus3/riot-commander` ahead of
   2026-05-10 fire.
4. **Path-name alignment** — add `/api/bridge/messages` as a second
   matcher on RC's existing `_serve_bridge` handler so Peer's contract
   path also resolves on RC (1-line change in `dashboard/routes_bridge.py`
   GET_ROUTES table).

## Bootstrap for next session

1. Read CLAUDE.md (frozen list).
2. Read this hand-off (s28).
3. Read `docs io RC peer/PEER_VIP_BRIDGE_MONITOR_FOR_RC_2026-05-02.md` —
   the design spec for the mirror.
4. Read memory: `reference_rc_peer_bridge`, `feedback_rc_peer_bridge_live`,
   `reference_tailscale_magicdns_rename`.
5. **Bridge is opt-in but currently ON** — `core/bridge.is_configured()`
   returns True; `ops/local_paths.json` has the bearer + Peer URL. To
   send a one-off message: `from core import bridge;
   bridge.send(source='rc', summary='...', kind='note', target='peer')`.
6. **Don't restart the supervisor** unless you have a reason — it's at
   PID 10796 with the new patches active and works. Main restarts via
   `restart_trigger.txt` are fine.

---

# s29 hand-off — 2026-05-02 15:05 (Game-PC on tailnet + RC bridge_monitor live)

> Two-arc session, both operator-driven via the now-live cross-Claude
> bridge. **Arc 1**: Game-PC joined the tailnet as `gamepc-rc`
> (`100.95.66.128`); RC's bridge tooling flipped from `192.168.8.230`
> LAN IP to `legion-rc` MagicDNS. **Arc 2**: RC's symmetric bridge
> monitor sidecar (top of s28's next-session queue) shipped, smoke
> verified, auto-pongs `kind=task summary=ping target=rc` in <100 ms.
> Currently running RC PID 9832; supervisor still 10796.

## What just shipped this session (in order)

| Type | Files | Summary |
|---|---|---|
| network | (Tailscale on Game-PC, no repo change) | Game-PC installed Tailscale 1.96.3, joined tailnet `tailc150de.ts.net` as `gamepc-rc` (`100.95.66.128`). `tailscale ping` to legion-rc: 0% loss, 8 ms. `https://legion-rc:8888/api/bridge/status` from Game-PC → 200. Three-node tailnet now: legion-rc / peer-host / gamepc-rc. |
| chore (uncommitted at hand-off) | `tools/bridge_*.py` (7), `tools/scheduled_boot_verify.py`, `tools/bridge_setup.ps1`, `tools/gamepc_boot.ps1`, `tools/rc_facts.py` | Bridge tooling URL constants flipped `https://192.168.8.230:8888` → `https://legion-rc:8888`; `rc_facts` Game-PC MCP probe → `http://gamepc-rc:8892/health`. Section headers in `rc_facts` now read `Legion (legion-rc · 100.70.22.55 · 192.168.8.230)` — all three identities side-by-side. LAN refs intentionally retained for LCU/MCP/screen-relay paths and cert/UNC scripts (those aren't "bridge" config). |
| feat (uncommitted at hand-off) | `core/bridge_monitor.py` (NEW, ~210 LOC), `main.py` (frozen, +8 lines) | RC's mirror of Peer's `bridge_monitor_agent.py`. Daemon-thread/AppLoop poller (mirrors `core/vision_tracker.py` lifecycle); polls `dashboard._bridge_log.bridge_since()` every 2 s; filters `source.startswith("legion")`, `source.startswith("rc-monitor")`, `source == "self-test"`; auto-pong gate `kind=task summary=ping target=rc` → `bridge_post(source="rc-monitor", summary="pong", kind="result", body={replier:"rc-bridge_monitor", in_reply_to_summary:"ping", auto:true}, in_reply_to=<id>)`. State at `ops/runtime/bridge_monitor_state.json` (atomic-write w/ `os.replace` retry-with-backoff); cold-boot starts `last_seen_ts=time.time()` so historical entries don't replay; warm-restart hydrates from disk. |

## RC restart state

- **Main PID 9832** (was 11836). Single restart this session via
  `restart_trigger.txt` to activate `core.bridge_monitor`. `last_reload_ok=true`.
- **Supervisor PID 10796** — unchanged from s28.
- **Bridge monitor live**: log line at boot
  `bridge_monitor started (poll=2.0s, async, last_seen_ts=1777752207)`.
  Smoke: simulated `peer-test` ping → auto-pong fired in **+0.09 s**;
  state file shows `inbound_count=1, auto_pong_count=1, recent[1]`.

## Cross-Claude bridge — operational state

- **Tailnet**: 3 nodes now (was 2 in s28).
  - `legion-rc` / `100.70.22.55`
  - `peer-host`  / `<peer-tailnet-ip>`
  - `gamepc-rc` / `100.95.66.128` *(new this session)*
- **RC↔Peer bridge**: unchanged from s28; still opt-in, live.
- **RC↔Game-PC bridge**: still on the legacy in-process `dashboard/_bridge_log.py`
  + Game-PC `/loop /process-bridge-tasks`. Game-PC's `/loop` rebooted
  fresh this session — last result 332 s ago at probe, healthy.
  Game-PC's installed copies of `tools/bridge_*.py` still point to the
  LAN IP; they self-update to `legion-rc` on next `gamepc_boot.ps1` re-pull.
- **Bridge monitor scope**: only watches the RC↔Peer-shape bridge log
  (the same `dashboard/_bridge_log.py` deque the dashboard's
  `/api/bridge` POST writes into). Game-PC's task/result entries
  ride the same log so the monitor sees them too — but `summary=="ping"`
  with `target=="rc"` is the *only* auto-action; everything else is
  log-only, exactly per spec.

## Memory entries written this session

None (the URL flip + monitor build are both code; no surprising or
non-obvious facts to commit to memory). The s28 `feedback_rc_peer_bridge_live`
remains the authoritative bridge-state memory.

## Operational backlog (delta from s28)

- ✅ ~~Bridge monitor mirror~~ (shipped; was top of s28 queue)
- **Cloud routine deadline 2026-05-10** — 8 days. Push the s29 commits
  before the routine fires.
- **Push-channel for bridge inbox (v1)** — promote from "next-candidate"
  if 2 s polling latency ever bites. Currently Peer→RC ping latency is
  bounded by the polling interval; first smoke landed at +0.09 s only
  because the post happened mid-polling-interval.
- **Game-PC bridge tooling re-pull** — Game-PC still has the old `192.168.8.230`
  copies. Non-breaking (LAN IP works), but tasking Game-PC to re-run
  `gamepc_boot.ps1` would normalize them to `legion-rc`.
- **Path-name alignment** (`/api/bridge/messages` as alias for `/api/bridge`)
  — unchanged from s28.

## Next-session candidates (ranked)

1. **Push s29 commits** — URL flip + monitor land as two commits
   (chore + feat). 8 days to cloud routine deadline.
2. **Game-PC re-pull** — task Game-PC's Claude to `iex (iwr
   https://legion-rc:8888/agent/gamepc_boot.ps1).Content` (note: also
   updated to use the tailnet hostname) so Game-PC's local
   `bridge_pull_tasks.py` etc. switch off the LAN IP.
3. **Bridge monitor v1 (push channel)** — replace polling with
   in-process notify in `bridge_post()` so the monitor sees inbound in
   <10 ms. Touches frozen `dashboard/_bridge_log.py`.
4. **Tiered vision** — still 🟡, unchanged from s28.
5. **CLAUDE.md sync** — the post-2026-04-19 topology section still
   names `192.168.8.230` / `192.168.8.237` as the canonical addresses.
   Now that all three nodes have stable tailnet identity, the doc
   could lead with the tailnet names. Low priority — the LAN IPs are
   still valid.

## Bootstrap for next session

1. Read `CLAUDE.md` (frozen list + restart workflow)
2. Read this hand-off (s29) + s28
3. `git status` — confirm s29 commits land before any new work; push
   ahead of the 2026-05-10 cloud-routine fire
4. Bridge monitor is **live and self-managing** — no action needed.
   To verify: `cat ops/runtime/bridge_monitor_state.json` shows
   `inbound_count` ticking up if any non-legion source has posted.


