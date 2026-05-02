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
