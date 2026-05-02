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

