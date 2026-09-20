# Mission Control removal - surface-by-surface gap analysis

ROADMAP NOW-1 (`ROADMAP.md:39`), operator direction 2026-09-19, LEDGER 1430.

> ## STATUS: ACTED ON 2026-09-20. OPTION A WAS IMPLEMENTED.
>
> The operator adjudicated **Option A** from section 4: keep the `:8895`
> control plane HEADLESS, retire the Mission Control web UI. As of 2026-09-20
> the whole `web/mc/` tree is DELETED, `mc/handler.py` has no static branch and
> no document root, and `tests/test_mission_control_panel.py`,
> `tests/test_interrupt_panel.py` and `tests/test_mc_lane_roster_contract.py`
> are deleted with it. The listener, the bearer perimeter, the
> `RC-MissionControl` task, `GET /api/loop-status` and all nine
> `POST /api/loop-control` actions are UNCHANGED.
>
> **Option A's named cost was NOT paid blindly.** Section 3a H6 says the
> arm-then-confirm gate in `web/mc/arm_confirm.js` "is the only thing standing
> between one click and an irreversible act", and deleting a client cannot make
> a server safer. That gate was therefore PORTED into the route layer before
> the removal, not lost with it: it now lives in `dashboard/_arm_confirm.py`
> and is enforced by `dashboard/routes_loop_control.route_action`, with two new
> route actions (`arm`, `disarm`) and a 409 refusal for any unarmed
> `fire_lane` / `queue_intent` / `interrupt`. Proven by
> `tests/test_arm_confirm_server_gate.py`. What the browser had for one client,
> every client now has.
>
> **Every `web/mc/...` citation below is AS-OF `HEAD` = `0945ff334` and points
> into files that no longer exist.** They are PRESERVED rather than repaired,
> because this document is the record of a measurement taken before the
> deletion, and re-pointing a citation at a surviving file would turn a true
> historical claim into a false current one. They are declared to the citation
> guard in `tests/test_citation_drift_guard_rm171.py` under family `HISTORICAL`
> for exactly that reason - declared, not hidden.
>
> One citation IS corrected rather than preserved, because it points at a
> SURVIVING file whose line numbers this change moved: section 3b S8 now reads
> `dashboard/routes_loop_monitor.py:453-456`.

**ANALYSIS ONLY. Nothing was deleted, nothing was changed, no sibling repository
was read or written.** Every claim below carries a `file:line` verified in this
run on 2026-09-20 against `HEAD` = `0945ff334`.

Live probes used: `curl -k` against `https://127.0.0.1:8895` and
`https://127.0.0.1:8888`, `schtasks /query /tn RC-MissionControl /v /fo list`,
`Get-CimInstance Win32_Process`, `ops/runtime/health.json`, and the retained
`logs/mission_control-*.log` access log.

---

## 0. Live ground truth measured this run

| Fact | Measurement |
|---|---|
| MC process | `pythonw.exe "C:\Riot Commander\mission_control.py"`, **PID 19284**, alive |
| Scheduled task | `\RC-MissionControl`, **Status Running**, `At logon time`, Run As `Administrator`, Last Result `-2147020576` |
| `GET https://127.0.0.1:8895/api/loop-status` | **200**, full JSON payload, **no Authorization header sent** |
| `GET https://127.0.0.1:8895/` | **200** `text/html`, 596 bytes |
| `POST https://127.0.0.1:8895/api/loop-control` with no bearer | **401** `{"ok": false, "error": "unauthorized"}` (401 not 503, so a token IS configured) |
| `config/mission_control_token.txt` | present, 34 bytes, gitignored at `.gitignore:49` |
| `GET https://127.0.0.1:8888/api/loop-status` | **404** - the game dashboard no longer serves the loop routes |
| `GET https://127.0.0.1:8888/api/loop-monitor` and `/loop-monitor` | **200** both - the tool-call timeline is on `:8888`, NOT on MC |
| `GET https://127.0.0.1:8895/api/loop-monitor` | **404** - confirms the timeline is not an MC surface |
| MC in `ops/runtime/health.json` | **ABSENT** - grep for `8895` and `mission` returns nothing; MC is outside the supervisor, as `mission_control.py:4-7` says |
| MC access log, whole retained window (2026-09-05 to 2026-09-20) | **16** `GET /api/loop-status`, **4** page loads, **1** POST - and that single POST is this session's own 401 probe at `logs/mission_control-2026-09-19.log` 2026-09-20 10:01:25 |
| Most recent real operator visit | 2026-09-19 17:29 from **100.70.22.55** (the Tailscale address): page + css + js + 3 status polls, **no POST** |

**Caveat on the log figures, stated rather than glossed:** MC logs are per-process-start
daily files and only six exist. The window is real but it is not the project's full
history, and a GET made before 2026-09-05 left no retained record. The honest claim is
"the control half has no successful POST in the retained window", never "the control
half has never been used".

---

## 1. SURFACE INVENTORY

### 1a. VIEW surfaces (read-only rendering) - 21 rows

| # | Surface | Citation |
|---|---|---|
| V1 | `:8895` HTTPS listener, GET half, **unauthenticated by design** (bind scope is the perimeter) | `mc/server.py:36` (`PORT = 8895`), `mc/server.py:39` (`BIND_ADDRESSES = ["127.0.0.1", "100.70.22.55"]`), `mc/auth.py:13-14` ("GET is not gated here"), `mc/handler.py:90-101` |
| V2 | `GET /api/loop-status` JSON payload | `mc/routes.py:16,19`; `dashboard/routes_loop_status.py:515-517`; assembled at `dashboard/routes_loop_status.py:448,481-497` |
| V3 | Static `index.html` (the MC page shell) | `mc/handler.py:70-86`; `web/mc/index.html:1-21` |
| V4 | Static `mc.css` (370 lines) | `mc/handler.py:84-85`; `web/mc/index.html:7` |
| V5 | Static `mc.js` (966 lines, ES module) | `mc/handler.py:84-85`; `web/mc/index.html:19` |
| V6 | Static `arm_confirm.js` (137 lines) | `web/mc/mc.js:101` imports it; `web/mc/arm_confirm.js:45` |
| V7 | Loop state dot + state word | `web/mc/mc.js:537-538` |
| V8 | `cycle` / `max_cycles` | `web/mc/mc.js:542-543` |
| V9 | `mode` (live / dry) | `web/mc/mc.js:544` |
| V10 | `stop_reason` free text | `web/mc/mc.js:560`; source `dashboard/routes_loop_status.py:482` |
| V11 | LANE lock row (state / lane / pid / run_id / worktree / age) | `web/mc/mc.js:566`, row builder `web/mc/mc.js:92`; source `dashboard/routes_loop_status.py:489` -> `:382` |
| V12 | LOOP controller lock row (same field set) | `web/mc/mc.js:567`; source `dashboard/routes_loop_status.py:492` -> `:401` |
| V13 | `last_done` - cycle, sha, `tests_pass`, regressions flag | `web/mc/mc.js:572-579`; source `dashboard/routes_loop_status.py:486` -> `:281` |
| V14 | `budget` - adjudicator USD, executor USD, claude USD | `web/mc/mc.js:583-590`; source `dashboard/routes_loop_status.py:487` |
| V15 | `last_commit` - sha + subject | `web/mc/mc.js:595-599`; source `dashboard/routes_loop_status.py:488` -> `:260` |
| V16 | **LANE LOG content tail** (held-lane-first selection, decoded) | `web/mc/mc.js:617-637`; source `dashboard/routes_loop_status.py:497` -> `:165-200`, decode at `:118` |
| V17 | **LOOP CONTROLLER LOG content tail** | `web/mc/mc.js:643-644`; source `dashboard/routes_loop_status.py:493` |
| V18 | `lanes_available` roster with "N of M wired" | `web/mc/mc.js:687-690`; source `dashboard/routes_loop_status.py:490` -> `:345`; labels `web/mc/mc.js:172-194` |
| V19 | Steer channel summary (pending / note / steer counts) | `web/mc/mc.js:700-703`; source `dashboard/routes_loop_status.py:491` -> `:371` |
| V20 | Stale-poll notice (ARIA live region) | `web/mc/mc.js:554-557`, `web/mc/mc.js:894-895` |
| V21 | **INTERRUPT PREVIEW victim list + fingerprint** (a POST, but documented read-only: kills nothing, writes nothing, does not even create `control/`) | `dashboard/routes_loop_control.py:414-438`, explicitly excluded from side effects at `:575-579`; client at `web/mc/mc.js:320-343`, painted `web/mc/mc.js:384-447` |

### 1b. CONTROL surfaces (mutate state, fire a lane, steer, interrupt) - 13 rows

| # | Surface | Citation | What it mutates |
|---|---|---|---|
| C1 | `POST /api/loop-control` endpoint | `mc/routes.py:21-23`; `dashboard/routes_loop_control.py:636-638`; handler `:605` | the single entry point for everything below |
| C2 | Bearer-token gate, **fails CLOSED** (503 unconfigured, 401 absent/wrong, byte-identical bodies) | `mc/handler.py:105-108`; `mc/auth.py:36-45` (resolution: env `RC_MC_TOKEN` then `config/mission_control_token.txt`), `mc/auth.py:48-61` | the perimeter itself |
| C3 | `stop` | `dashboard/routes_loop_control.py:584-588` | writes `ops/loop/control/STOP` |
| C4 | `resume` | `dashboard/routes_loop_control.py:589-591` | unlinks `ops/loop/control/STOP` |
| C5 | `set_directive` | `dashboard/routes_loop_control.py:592-598` | writes `ops/loop/control/directive_override.md` (cap `MAX_DIRECTIVE` 8000, `:105`) |
| C6 | `clear_directive` | `dashboard/routes_loop_control.py:599-601` | unlinks that file |
| C7 | `fire_lane` | `dashboard/routes_loop_control.py:245-...`, dispatch `:545-546`; late-bound module `:111` | claims a mutually exclusive lane lock via `ops/loop/lanes.py`, then launches via `ops/loop/lane_launcher.py` (`:115`) |
| C8 | `queue_intent` (`halt_save` / `done_continue`) | `dashboard/routes_loop_control.py:325-348`; file map `:128-131` | writes `INTENT_HALT_SAVE.json` / `INTENT_DONE_CONTINUE.json`; `halt_save` also raises `STOP` (`:343`) |
| C9 | `steer` (tier `note` or `steer`) | `dashboard/routes_loop_control.py:350-...`, dispatch `:547-548`; module `:139` -> `ops/loop/steer.py:152` `append` | appends to `ops/loop/control/STEER.jsonl` |
| C10 | `interrupt` - **the only action that kills processes** | `dashboard/routes_loop_control.py:441-...`, dispatch `:549-550`; module `:142` -> `ops/loop/interrupt.py:262` `execute`, `:226` `_taskkill` | `taskkill` over the previewed victim set, fingerprint-gated |
| C11 | Idempotency replay ledger for the four intent-carrying actions | `dashboard/routes_loop_control.py:136-141` (`_IDEMPOTENT_ACTIONS`), `:482-565`, `:175` (`INFLIGHT_WAIT_S`); store `dashboard/_idempotency.py` | prevents a retried phone request from firing twice |
| C12 | Arm-then-confirm client gate (3 s window, key minted at arm) | `web/mc/arm_confirm.js:21,45,86,109`; wired `web/mc/mc.js:133` | the only thing standing between one click and an irreversible act |
| C13 | Process lifecycle: `RC-MissionControl` scheduled task, plus refuse-to-start without TLS and non-zero exit on bind failure | `tools/install_mission_control_task.ps1:43-63`; `mc/server.py:62-66`, `:79-84`; entry `mission_control.py:35-38` | keeps the control plane alive independently of `rc_supervisor` |

**Total: 34 surfaces (21 VIEW, 13 CONTROL).**

Note on V21 / C10: `interrupt_preview` is deliberately NOT in `_IDEMPOTENT_ACTIONS`
(`dashboard/routes_loop_control.py:143-151` explains why - remembering it would freeze
one stale victim list into every later arm). The preview is the mechanism that makes the
kill honest, so it is inventoried as VIEW and the kill as CONTROL, but they are one
feature and neither is useful alone.

---

## 2. WIDGET COVERAGE

The lane widget is `C:\Riot Commander\lane-widget`, Electron, 15 source files,
9 test files. Its own statement of scope: `lane-widget/src/main.js:15-17`
("READ-ONLY observer ... never writes, locks, unlinks or reaps anything. The only
thing it writes anywhere is its own state file under Electron userData") and
`lane-widget/README.md:7-10`.

**Absence check performed, not assumed.** Patterns tried over `lane-widget/src`:
`8895`, `loop-status`, `loop-control`, `fetch(`, `Bearer`, `Authorization`,
`http://`, `https://`, `127.0.0.1`, `localhost`, `XMLHttpRequest`, `WebSocket`,
`axios`, `net.request`, `require("http")`. **Zero code hits.** The only textual
matches anywhere in the tree are comments citing Python line numbers
(`lane-widget/src/locks.js:9`, `lane-widget/src/heartbeat.js:9`). The page is
additionally CSP-locked to `connect-src 'none'` at
`lane-widget/src/renderer/index.html:33-34`.

Mutation check: patterns `taskkill`, `Stop-Process`, `writeFile`, `unlink`,
`fire_lane`, `queue_intent`, `steer`, `interrupt`, `reclaim`. The only writes in
the whole app are `lane-widget/src/store.js:78,83,84,89`, all targeting the
widget's own `lane-widget-state.json` under Electron `userData`
(path built at `lane-widget/src/main.js:108-110`). The only `process.kill` is
`lane-widget/src/poll.js:217`, signal 0, an existence probe annotated as such at
`lane-widget/src/poll.js:210-211`. The only spawn is a read-only
`Get-CimInstance Win32_Process` at `lane-widget/src/poll.js:41-48,159`.

### 2a. VIEW coverage verdicts

| # | Surface | Verdict | Widget citation (required for COVERED) |
|---|---|---|---|
| V1 | `:8895` listener | NOT COVERED | n/a - the widget has no listener and no client |
| V2 | `GET /api/loop-status` | NOT COVERED | reads files directly, never HTTP |
| V3-V6 | MC static page + css + js + arm_confirm | NOT COVERED | the widget is a different page with a different job |
| V7 | loop state dot | NOT COVERED | it renders LOCK state, not loop state; `lane-widget/src/renderer/widget.js:75-80` returns only `running`/`stale`/`idle`/`unreadable` for a lock |
| V8 | cycle / max_cycles | NOT COVERED | no reader for `ops/loop/control/cycle.txt` |
| V9 | mode | NOT COVERED | - |
| V10 | stop_reason | NOT COVERED | `ops/loop/control/STOP` is never read; the read set is fixed at `lane-widget/src/locks.js:20,22` and `lane-widget/src/poll.js:37` |
| **V11** | **LANE lock row** | **COVERED, and a superset** | read `lane-widget/src/poll.js:444` with `LANE_LOCK_REL` from `lane-widget/src/locks.js:20`; row built `lane-widget/src/model.js:140-147`; rendered `lane-widget/src/renderer/widget.js:518-537`; lane name `:96-105`; run_id `:249`; age `:116-123`; adds descendant count `:145` and stall flag `:143`, and does it for **every repo in the roster**, not just RC (`lane-widget/src/repos.js:142-149`) |
| **V12** | **LOOP controller lock row** | **COVERED** | read `lane-widget/src/poll.js:449` with `CTRL_LOCK_REL` from `lane-widget/src/locks.js:22`; same row builder `lane-widget/src/model.js:140-147` |
| V13 | last_done (sha / tests_pass / regressions) | NOT COVERED | - |
| V14 | budget USD | NOT COVERED | `ops/loop/control/budget.json` is never read |
| V15 | last_commit | NOT COVERED | no git call anywhere; grep for `git` in `lane-widget/src` returns zero |
| **V16** | **LANE LOG content tail** | **PARTIAL - freshness only, never content** | log AGE is covered: directory listing `lane-widget/src/poll.js:497-502`, newest-per-lane `lane-widget/src/heartbeat.js:63-102`, rendered as the `log Ym` token at `lane-widget/src/renderer/widget.js:146`. **Content is explicitly out of scope**: `lane-widget/README.md:47-49` ("Only mtimes are stat'ed. There is no log tailing in v1") and `lane-widget/src/heartbeat.js:8-13` |
| V17 | LOOP CONTROLLER LOG tail | NOT COVERED | same reason - no log decoding at all |
| V18 | lanes_available roster | NOT COVERED | the widget shows the lane name held by a lock; it has no view of which lanes are wired |
| V19 | steer pending counts | NOT COVERED | `STEER.jsonl` / `STEER.cursor` are never read |
| V20 | stale-poll notice | NOT COVERED by MC's meaning, but the widget has its own equivalent for its own data (`lane-widget/src/renderer/widget.js:342-382`) - not a replacement for MC's poll-staleness signal |
| V21 | interrupt preview victim list | NOT COVERED | the widget counts descendants (`lane-widget/src/proctree.js:127-133`) but never names, fingerprints or lists them for an action |

**VIEW tally: 2 COVERED, 1 PARTIAL, 18 NOT COVERED, out of 21.**

### 2b. CONTROL coverage verdicts

**0 of 13 covered.** The widget exposes exactly five IPC channels
(`lane-widget/src/preload.js:25,39,43,46,50`), enumerated as frozen at
`lane-widget/src/main.js:633-634`. Only one of them writes anything
(`lane-widget:state:set`, `lane-widget/src/main.js:641-653`), and its accepted
keys are clamped to `{x, y, width, height, opacity, alwaysOnTop, showFree, fastMs}`
at `lane-widget/src/store.js:111-126`. Nothing in the app can reach
`ops/loop/control/` for writing in any repository
(`lane-widget/src/locks.js:12-13`).

---

## 3. THE GAP - what is LOST if MC is deleted today

### 3a. HARD losses (no replacement anywhere in the tree)

| # | Lost | Why there is no replacement |
|---|---|---|
| H1 | **Remote control at all** - the `POST /api/loop-control` endpoint and its bearer perimeter | `mc/routes.py:16` is the only production importer of `dashboard/routes_loop_control.py` (stated at `dashboard/routes_loop_control.py:1` and `:10-11`), and `:8888` returns **404** for the loop routes, measured live. Deleting MC removes every phone / Tailscale path to the loop. |
| H2 | **`steer` WRITE** (tier `note` and `steer`) | `ops/loop/steer.py:152` `append` has exactly one non-test caller, `dashboard/routes_loop_control.py:139`. The CLI that exists, `tools/session_steer.py`, is **read-only**: its only modes are `--peek` and `--drain` (`tools/session_steer.py:62-65`), and its own docstring says `--peek` "never writes" (`tools/session_steer.py:6`). There is no writer CLI. |
| H3 | **`queue_intent` WRITE** (`halt_save`, `done_continue`) | The route writes the intent file itself (`dashboard/routes_loop_control.py:337-345`). `ops/loop/intents.py` exposes `pending` (`:186`), `consume` (`:336`) and `write_prompt` (`:297`) - **readers and consumers, no queue writer** - and `tools/session_intent.py` mirrors exactly those three modes (`tools/session_intent.py:38-44`). |
| H4 | **`interrupt` - preview, fingerprint gate, and the kill** | `ops/loop/interrupt.py` has **one importer in the entire tree**: `dashboard/routes_loop_control.py:142`. It has no `__main__`, no `argparse`, and no `tools/` wrapper. The safety property (`preview` at `:214` names the victims, `execute` at `:262` re-probes and refuses on `victims_changed`) exists nowhere else; the fallback would be a bare `taskkill` chosen by eye. |
| H5 | **Idempotent replay protection** for retried control actions | `dashboard/routes_loop_control.py:136-141`, `:482-565`. A file-write fallback has no notion of a repeated operator intent. |
| H6 | **Arm-then-confirm** as the guard on irreversible acts | `web/mc/arm_confirm.js:45,86,109`. A shell has no equivalent. |
| H7 | **The rendered loop-status view**: state, cycle, mode, stop_reason, `last_done`, budget, `last_commit`, lane-log CONTENT, controller-log CONTENT, lanes wired, steer pending | V7-V10, V13-V19 above. The underlying bytes stay on disk in `ops/loop/control/`, but **no renderer survives**: `:8888` 404s the route and the widget reads neither the files nor the endpoint. |
| H8 | **`GET /api/loop-status` as an HTTP surface** | Only `mc/routes.py:19` registers it. Measured: `:8888` returns 404. |

### 3b. SOFT losses (another route exists - named)

| # | Lost from MC | Surviving route |
|---|---|---|
| S1 | LANE lock row (V11) | Lane widget, `lane-widget/src/poll.js:444` -> `lane-widget/src/renderer/widget.js:518-537`. Strictly better: adds descendant count, stall flag and cross-repo scope. |
| S2 | LOOP controller lock row (V12) | Lane widget, `lane-widget/src/poll.js:449`, same renderer. |
| S3 | Lane-log FRESHNESS (half of V16) | Lane widget, `lane-widget/src/heartbeat.js:63-102`, rendered `lane-widget/src/renderer/widget.js:146`. The log CONTENT half is a hard loss (H7). |
| S4 | `stop` / `resume` (C3, C4) | `ops/loop/control/STOP` is an ordinary file. `ops/loop/loop_controller.py:230` already writes it itself, and reads it at `:828`, `:842` and `:1100`. Any local editor or `awrite` call replaces this. **The loop controller does not break; it loses one of two writers.** |
| S5 | `set_directive` / `clear_directive` (C5, C6) | Same shape - `ops/loop/control/directive_override.md` is consumed by `ops/loop/loop_controller.py:186-193`, which does not care who wrote it. |
| S6 | `fire_lane` (C7) | `ops/loop/queue_loop.py:207-208` binds `ops.loop.lanes` and `ops.loop.lane_launcher` directly; `ops/loop/run_lane.ps1` and `ops/loop/spawn_lanes.ps1:7,18-26` launch lanes without any HTTP. The **lock-claim-and-refuse** semantics would need to be re-obtained from `lanes.py` by hand, but the launcher path exists. |
| S7 | `last_commit` (V15) | `git log -1`. |
| S8 | The tool-call timeline | **Not an MC surface at all.** `/api/loop-monitor` and `/loop-monitor` are registered at `dashboard/routes_loop_monitor.py:453-456` (re-pointed 2026-09-20 after the dangling `/api/loop-status` fetch was cut from that page; the registration itself is unchanged) and dispatched on `:8888` at `dashboard/_dispatch.py:81,143`. Measured live: **200 on `:8888`, 404 on `:8895`.** It survives MC deletion untouched. This is worth stating explicitly because it is the surface most likely to be mistaken for MC's. |

**One pre-existing defect found while sweeping this, reported rather than fixed.**
The `:8888` loop-monitor page already fetches `/api/loop-status`
(`dashboard/routes_loop_monitor.py:389`, called at `:390`) - a route `:8888` has
not served since S10, which is why `:8888/api/loop-status` measured **404**. The
page degrades correctly: `rStatus(null)` renders `loop-status unavailable` at
`dashboard/routes_loop_monitor.py:397`. So this is a **dangling caller that is
already broken today and fails soft**, not something MC deletion causes. It does
mean the `:8888` page has no recovery path once MC is gone, and it is a live
argument for Option B (re-registering the status route on `:8888` would repair a
page that is already asking for it).

---

## 4. THE CONTROL-PLANE DECISION - framed question for the operator

**Question, verbatim:**

> The lane widget replaces two of Mission Control's twenty-one VIEW surfaces and
> none of its thirteen CONTROL surfaces. Four control capabilities - `steer`
> write, `queue_intent` write, `interrupt` (preview plus fingerprint-gated kill),
> and idempotent replay protection - exist nowhere else in the tree and die with
> Mission Control. The retained `:8895` access log shows the VIEW half was used
> from the tailnet as recently as 2026-09-19 17:29 and shows zero successful
> POSTs in the window. Which of these three do you want, and do you accept the
> named cost?
>
> **Option A - Keep `:8895` headless, delete the UI.** Keep `mission_control.py`,
> `mc/`, both route modules and the `RC-MissionControl` task; delete `web/mc/`
> and the static-serving branch at `mc/handler.py:70-86,96-97`. The control
> plane survives intact and is driven by `curl` with the bearer token.
> **Cost:** you lose the arm-then-confirm gate (`web/mc/arm_confirm.js:45`),
> which is the only thing today that stops a single click from killing agents,
> and you lose the phone-friendly view the log shows you actually used
> yesterday. You keep a whole process, a port, a scheduled task and a TLS
> surface for a CLI-only consumer.
>
> **Option B - Fold the control endpoints into the existing `:8888` dashboard.**
> Re-register `routes_loop_control` and `routes_loop_status` in
> `dashboard/_dispatch.py` (they were de-registered there by S10 - see
> `dashboard/routes_loop_control.py:1`), move `web/mc/` under the dashboard's
> asset tree, and retire `mission_control.py`, `mc/` and the
> `RC-MissionControl` task. One process, one port, one cert, one page.
> **Cost:** this re-litigates ADR-era decision S10 in reverse. `mc/server.py:6-16`
> lists the three properties you would give up: a narrow explicit bind instead
> of the dashboard's wildcard, non-zero exit on bind failure instead of a logged
> warning, and no hot-reload watcher on a control plane. You would also put the
> kill action back on a process that `restart_trigger.txt` bounces for game
> overlay changes, which `mission_control.py:4-7` says is the exact thing S10
> was built to prevent. `dashboard/_handler.py:532` still lists
> `/api/loop-control` in the `:8888` control-endpoint auth set, but that gate is
> inert - `RC_DASH_TOKEN` is set nowhere (see `BACKLOG.md:120`, RM-296c) - so
> this option also inherits an open auth decision.
>
> **Option C - Move control into the widget.** Add a write path to the Electron
> app and delete Mission Control entirely.
> **Cost:** this inverts the widget's stated contract in six places
> (`lane-widget/README.md:7-10`, `lane-widget/src/main.js:15-17`,
> `lane-widget/src/poll.js:20-21`, `lane-widget/src/locks.js:12-13`,
> `lane-widget/src/repos.js:6-7`, `lane-widget/src/model.js:7`) and in its CSP
> (`lane-widget/src/renderer/index.html:33-34`). The widget watches **every repo
> in the moon-sync roster** (`lane-widget/src/repos.js:142-149`), so a write path
> there is a write path into sibling repositories - which is the standing
> halt-and-ping boundary, not a design choice a session can make. It also loses
> phone access entirely: a desktop Electron window is not reachable over
> Tailscale.
>
> A fourth axis you named, **retire control entirely and drive lanes from the
> CLI**, is not offered as an option because it is not currently achievable:
> `steer` write, `queue_intent` write and `interrupt` have no CLI at all
> (H2, H3, H4 above). It becomes an option only after three small writer CLIs
> are built, and that is itself a piece of work to schedule, not a deletion.

**No option is picked here, per the task.**

---

## 5. BLAST RADIUS - what breaks on deletion

### 5a. Process, port, task

| Item | Citation | Effect |
|---|---|---|
| `RC-MissionControl` scheduled task (Running, PID 19284) | `tools/install_mission_control_task.ps1:63`; `docs/OPERATIONS.md:220` | must be unregistered, or it restarts a deleted entry point every minute (the repeat trigger at `tools/install_mission_control_task.ps1:56-58` is indefinite) |
| Port 8895 | `mc/server.py:36` | freed. Note `README.md:111` and `docs/API.md:135-146` document it |
| TLS material | `mc/server.py:41-42` shares `ops/tls/rc.pem` with the dashboard | **nothing to do** - shared cert, and a SAN is host-scoped not port-scoped (`mc/server.py:18-21`) |
| `config/mission_control_token.txt` | `mc/auth.py:26`; `.gitignore:49`; provisioning runbook `docs/OPERATIONS.md:265-296` | **needs explicit handling.** It is gitignored, so `git rm` will not touch it: a deletion that only removes tracked files leaves a live 34-byte bearer secret on disk for a service that no longer exists |
| `ops/runtime/health.json` | MC is **absent** from it (measured) | no health wiring to unpick |
| `rc_supervisor` | MC is deliberately not supervised (`mission_control.py:4-7`) | no supervisor change |

### 5b. Code

| File | Citation | Effect |
|---|---|---|
| `mission_control.py` (43 lines) | `mission_control.py:35-38` | deleted |
| `mc/` package (5 files, 332 lines) | `mc/__init__.py`, `mc/server.py`, `mc/auth.py`, `mc/routes.py`, `mc/handler.py` | deleted |
| `web/mc/` (5 files, 1676 lines) | `web/mc/index.html`, `mc.js`, `mc.css`, `arm_confirm.js`, `arm_confirm.test.mjs` | deleted |
| `dashboard/routes_loop_control.py` (638 lines) | only importer is `mc/routes.py:16` | becomes dead unless re-registered (Option B) |
| `dashboard/routes_loop_status.py` (519 lines) | same | same |
| `ops/loop/interrupt.py` | only importer `dashboard/routes_loop_control.py:142` | becomes **unreachable** - no other caller, no CLI |
| `ops/loop/steer.py` `append` (`:152`) / `record` (`:166`) | only writer-caller `dashboard/routes_loop_control.py:139`; its only other in-repo importer is `ops/loop/interrupt.py:86`, which is itself MC-only | write half becomes unreachable; `tools/session_steer.py:38` keeps the READ half alive and `tools/done.md:70` still invokes it |
| `ops/loop/lanes.py`, `ops/loop/lane_launcher.py` | also bound by `ops/loop/queue_loop.py:207-208` and used there at `:853`, `:879`, `:912`, `:991`, `:1255` | **survive** - `queue_loop.py` is an independent driver, not an MC client |
| `ops/loop/intents.py` | also imported by `tools/session_intent.py:26`, invoked by `tools/done.md:62,300,312` | **survives as a CONSUMER with no PRODUCER.** The only writer of `INTENT_*.json` is `dashboard/routes_loop_control.py:339`, so after deletion `--peek` returns "no pending intent" forever and the `/done` ritual's intent branch becomes permanently dead |
| `ops/loop/loop_controller.py` | writes STOP itself at `:230`, reads at `:828`, `:842`, `:1100`; consumes the override at `:186-193` | **does not break** - it loses a remote writer, not a dependency |
| `core/ports.py:150` | `MISSION_CONTROL = 8895`, with a "Do not renumber 8895" note at `core/ports.py:122` and block prose at `:36`, `:49`, `:128` | constant orphaned; `tests/test_ports.py:113-114` asserts it equals `mc.server.PORT` by live import |
| `tools/gen_archmap.py:73` | `"mc": "Mission Control (:8895 control plane)"` section title | dead section key in the arch-map generator |
| `dashboard/_matchers.py:1-11` | this module **exists only because** MC must import the loop routes without pulling in pydantic (`dashboard/_matchers.py:4-9`), guarded by `tests/test_mission_control_server.py::test_matchers_module_is_stdlib_only` | survives (re-exported by `_dispatch`), but loses its stated reason to exist |
| `dashboard/_errors.py:6-9` | docstring describes the `:8895` splice | prose needs correction |
| `dashboard/_handler.py:532` | lists `/api/loop-control` in the `:8888` control-endpoint auth set although the route is no longer on `:8888` | already-stale entry; would become plainly wrong |
| `dashboard/routes_auto_accept.py:18` | comment cites `/api/loop-control` as the trust-model exemplar | prose needs correction |
| `atlas.html:427` | claims the `:8888` route family serves "loop-control endpoints" | already stale; would become plainly wrong |
| `web/js/panels/dev.js:121` | comment only, no call | cosmetic |

### 5c. Tests - counted with `grep -c '^def test_'` this run

| File | `def test_` count | Relationship |
|---|---|---|
| `tests/test_mission_control_server.py` | 26 | MC-only |
| `tests/test_mission_control_panel.py` | 38 | MC-only |
| `tests/test_loop_control_idempotency.py` | 52 | MC-only |
| `tests/test_loop_status_route.py` | 25 | MC-only |
| `tests/test_interrupt_panel.py` | 19 | MC-only |
| `tests/test_loop_control_route.py` | 15 | MC-only |
| `tests/test_loop_control_contention.py` | 13 | MC-only |
| `tests/test_interrupt_route.py` | 12 | MC-only |
| `tests/test_loop_control_sibling_writers_lane8_cycle48.py` | 6 | MC-only |
| `tests/test_loop_control_override.py` | 4 | MC-only |
| `tests/test_mc_lane_roster_contract.py` | 3 | MC-only (pins `web/mc/mc.js:172-194` against `ops/loop/lanes.py`) |
| **MC-only subtotal** | **213** | every one of these goes red or gets deleted |
| `tests/test_session_intents.py` | 32 | PARTIAL - pins `NEXT_SESSION_PATH` against `dashboard/routes_loop_control.py:122` (`test_default_next_session_path_matches_the_route`) |
| `tests/test_lane_launcher.py` | 23 | PARTIAL - `:338` does `import dashboard.routes_loop_control as ctlmod` and asserts the launcher and the route share one `lanes` module object |
| `tests/test_ports.py` | 19 | PARTIAL - `:114` live-imports `mc.server` to assert `ports.MISSION_CONTROL == mc.server.PORT` |
| `tests/test_interrupt_tier.py` | 19 | PARTIAL - imports `ops/loop/interrupt.py`, which becomes unreachable production code |
| `tests/test_citation_drift_guard_rm171.py` | 14 | PARTIAL - `:555` cites `mc.js:509` directly |
| `tests/test_dashboard_error_scrub_rm134.py` | 8 | PARTIAL - `:110` `import mc.routes`; `:153` names the three route modules |
| `tests/test_control_endpoint_auth.py` | 7 | PARTIAL - asserts on `dashboard/_handler.py:532` |
| `tests/test_css_var_definitions_rm209.py` | 6 | PARTIAL - `:135` asserts `"web/mc/mc.css"` is in the scanned corpus |
| `tests/test_web_js_esm_parse.py` | 2 | **SILENT** coverage loss - `WEB_MC` at `:50`; an `rglob` over a deleted dir returns empty and the `assert files` at `:74` still passes on `web/js` alone, so `mc.js` and `arm_confirm.js` just stop being syntax-checked with no red test. This is exactly the ADR-015 / empty-enumeration trap |
| `tests/test_mc_s10_spec_doc_rm152.py` | 1 | PARTIAL - audits `docs/MISSION_CONTROL_PLAN.md` |
| `tests/test_web_ascii_sweep.py` | 39 | PARTIAL - **10** lines reference `web/mc`, including a pinned source COUNT at `:102-103` |
| `web/mc/arm_confirm.test.mjs` | 14 `test(` | node test, deleted with the file |

`tests/test_loop_monitor_route.py` is **NOT** affected - its subject is on `:8888`.

### 5c-bis. Citation drift - the largest mechanical cost

Roughly **42** `file:line` citations in code and living docs point INTO MC files
and would all become broken on deletion. Representative, each verified:
`core/ports.py:151` cites `mc/server.py:36`;
`dashboard/routes_loop_control.py:10-15` cites `mc/routes.py:16`, `mc/server.py:39`,
`mc/server.py:62-66`, `mc/handler.py:105-108`, `mc/auth.py:48-61`;
`dashboard/routes_loop_control.py:510-523` cites six `web/mc/mc.js` lines;
`tests/test_citation_drift_guard_rm171.py:555` cites `mc.js:509`.

**Correction to a plausible but wrong belief about where this is enforced.**
The citation and drift guards are **pytest tests**
(`tests/test_citation_drift_guard_rm171.py`, `tests/test_drift_guard.py`, run in
CI at `.github/workflows/ci.yml:422-424`), **not git hooks**.
`.githooks/post-commit` runs only `git lfs post-commit` (`:24`); its sole mention
of `drift_guard` is a comment at `:16`. `.githooks/pre-push` runs
`tools/sibling_name_sweep.py` (`:39`) and then `git lfs pre-push` (`:56`) and has
no MC or citation involvement. So broken citations surface as a RED SUITE, which
is a stronger gate than a hook, but the commit itself will not be blocked.

### 5d. Docs citing Mission Control or `:8895` (tracked `.md`, `docs/_archive` excluded; counts measured with `git grep -c -i '8895|mission control'`)

`docs/superpowers/plans/2026-07-31-mission-control-s10-decouple.md` 61,
`docs/LEDGER.md` 36, `docs/history_notes.md` 33,
`docs/superpowers/specs/2026-07-31-mission-control-s10-decouple-design.md` 27,
`docs/MISSION_CONTROL_PLAN.md` 16, `BACKLOG.md` 14,
`docs/ARCHITECTURE.md` 10 (`:101`, `:126`, `:128`, `:141`, `:144-149`),
`docs/ROADMAP_HISTORY.md` 9, `docs/OPERATIONS.md` 6 (`:220`, `:265`, `:287-302`),
`docs/API.md` 4 (`:135-146`), `ROADMAP.md` 3, `WAKEUP_NOTES.md` 2,
`docs/CONCURRENT_HEADLESS_CONTRACT.md` 1, `docs/DS_SWEEP_TRACKER.md` 1,
`docs/REFUTATION_GATE_BACKTEST_2026-09-12.md` 1, `README.md` 1 (`:111`),
`docs/_scratch_fparm_B.md` 2, `docs/COST_LATENCY_SWEEP_2026-08-02.md` (`:233`),
`docs/RESPONDER_RUNNER_SPEC.md` (`:231`), `NEXT_SESSION_PROMPT.md` (`:80`, since
2026-09-20 at `docs/_archive/2026-09-07-NEXT_SESSION_PROMPT.md`; the count above
is the census AS MEASURED and is deliberately not restated),
`BACKLOG.md:592` (an OPEN row whose whole subject is this task's
`MultipleInstances=IgnoreNew` watchdog gap), plus the lane skill prompts:
`tools/headless-ds.md` 3, `tools/headless-queue.md` 3, `tools/headless-repo.md` 3,
`tools/headless-true-audit.md` 3, `tools/headless-gated.md` 2,
`tools/headless-uiux.md` 2, `tools/headless-research.md` 1, `tools/done.md` 1.

**Pattern disclosure, because the number depends on it.** These counts come from
`git grep -c -i "8895\|mission control"`. A wider alternation that also matches
`RC-MissionControl` and `mission_control` returns higher per-file numbers (for
example `docs/OPERATIONS.md` 6 under the narrow pattern, 14 under the wide one).
Both are correct for their pattern; neither is "the" count. **`CLAUDE.md` is
clean under BOTH patterns - verified, zero hits.**

**25 tracked markdown files under the narrow pattern.** `docs/LEDGER.md` and `docs/history_notes.md` are
append-only history and must NOT be rewritten (`feedback_no_history_rewrite`);
the living docs that need a real edit are `docs/ARCHITECTURE.md`,
`docs/OPERATIONS.md`, `docs/API.md`, `README.md`, `ROADMAP.md` and the eight
`tools/headless-*.md` lane prompts, which describe MC as the lane-firing surface.

### 5e. Hooks

**No hook references Mission Control.** `.claude/settings.json` and all six
`.githooks/*` files were grepped for `8895`, `mission_control` and
`mission control` - zero hits. `.githooks/post-commit` runs only
`git lfs post-commit` (`:24`); `.githooks/pre-push` runs
`tools/sibling_name_sweep.py` (`:39`) then `git lfs pre-push` (`:56`). The
citation and drift guards that WOULD go red are pytest tests, not hooks - see
section 5c-bis.

### 5f. AutoHotkey

`ops/loop/claude_gui_bridge.ahk` polls `ops/loop/control/STOP` (cited at
`ops/loop/loop_controller.py:170-173` as one of the three STOP readers). It reads
the FILE, not the HTTP route, so it is **unaffected** by MC deletion.

---

## 6. WHAT I COULD NOT DETERMINE

Stated plainly rather than guessed.

1. **Which "two sibling monitors" the operator means.** `ROADMAP.md:39` and
   `WAKEUP_NOTES.md:29` both say "MC and two sibling monitors can go" and neither
   names them. Nothing in RC's tree identifies them, and reading a sibling
   repository is out of bounds for this task. **This analysis covers Mission
   Control only.** The two sibling monitors are un-analysed and their removal is
   not cleared by anything written here.

2. **Whether the control half has ever been used successfully.** Measured: zero
   successful POSTs in the retained log window, which starts 2026-09-05 and has
   only six files. That is an absence of evidence over 15 days, not evidence of
   absence over the project's life. Before deletion is decided on usage grounds,
   this should be re-measured over a window the operator considers
   representative, or answered by the operator directly.

3. **The meaning of `Last Result -2147020576`** on the scheduled task. The task
   reads `Status: Running` with a live PID, so the process is healthy; the code
   is most consistent with the once-a-minute repeat trigger being discarded by
   `MultipleInstances=IgnoreNew` (`tools/install_mission_control_task.ps1:61`),
   which is the designed no-op. **I did not verify that mapping** and am not
   asserting it.

4. **Whether the widget's roster actually contains more than RC on this host.**
   `lane-widget/src/repos.js:130` reads the gitignored
   `ops/moon_sync_repos.json`. I did not read that file (it names sibling
   checkout paths, and the task forbids touching sibling repos). So "the widget
   covers every participating repo" is a claim about the CODE
   (`lane-widget/src/repos.js:142-149`), not a measurement of this host's live
   roster.

5. **Whether re-registering the loop routes on `:8888` (Option B) would pass the
   existing guard** at `tests/test_mission_control_server.py`
   (`test_mc_package_imports_no_game_code`, cited at `mc/routes.py:12`). The
   guard runs in the MC direction; its behaviour under a reversed topology was
   not simulated, because simulating it means changing the dispatch table and
   this task changes nothing.

6. **The real operator cost of losing the phone path.** The log proves a tailnet
   page load on 2026-09-19 17:29 from `100.70.22.55`. It cannot tell me whether
   that was routine, or whether it was this project's own verification. Only the
   operator can say.

7. **One unattributed working-tree change during this run, reported rather than
   explained away.** At the start of this session `git status --porcelain`
   listed one untracked file, `lane-widget/src/renderer/_probe_glyph.css`. At the
   end of the session it is gone from disk and from `git status`. **This analysis
   ran read-only and issued no delete, and no `electron.exe` was running when
   checked.** I cannot attribute the removal to a named writer, so I am not
   guessing at one. The file was untracked, so it is not recoverable from git.
   Its name is consistent with a transient probe artifact from the 2026-09-19
   lane-widget UI audit, but that is a hypothesis, not a measurement.

---

---

## 7. Summary counts

| Dimension | Count |
|---|---|
| MC surfaces inventoried | **34** (21 VIEW, 13 CONTROL) |
| VIEW surfaces the widget covers | **2** COVERED + **1** PARTIAL (log freshness, not content) |
| CONTROL surfaces the widget covers | **0** |
| HARD losses | **8** (H1-H8) |
| SOFT losses | **8** (S1-S8) |
| Files deleted | 11 source files (`mission_control.py`, 5 in `mc/`, 5 in `web/mc/`) + 1 scheduled task, plus 2 orphaned route modules (1157 lines) if not re-registered |
| Test files affected | **21** |
| `def test_` in MC-only files (go red or get deleted) | **213** |
| `file:line` citations into MC files needing reconciliation | approx **42** |
| Tracked `.md` files citing MC (narrow pattern) | **25** |
| `ops/loop/` modules left with ZERO callers | **1** - `ops/loop/interrupt.py` |
| `ops/loop/` modules left with a consumer but no producer | **1** - `ops/loop/intents.py` |
| Secret left on disk if not handled explicitly | `config/mission_control_token.txt` (34 bytes, gitignored) |

**The one-sentence finding:** nothing crashes if Mission Control is deleted - the
loop controller, the AHK bridge, `queue_loop.py` and the `/done` ritual all keep
working because each reads control files that MC only co-writes - but the repo
loses its ONLY remote control plane for nine actions including `interrupt`
(process kill), `ops/loop/interrupt.py` becomes unreachable code with no CLI,
`ops/loop/intents.py` becomes a consumer with no producer, the `steer` write path
disappears entirely, and roughly 213 test definitions plus 42 citations need
reconciliation. The widget replaces 2 of 34 surfaces.

---

*End of analysis. No file outside this one was created or modified; nothing was
committed.*
