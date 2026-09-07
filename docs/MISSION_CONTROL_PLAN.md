# RC Mission Control - build + wire plan

Status: mockup BUILT and rendered. Wiring NOT built. This is the spec.
Ground truth probed live 2026-07-30, every path below verified on disk.

## What already exists (extend, do not invent)

| Surface | File | State |
|---|---|---|
| POST `/api/loop-control` | `dashboard/routes_loop_control.py` | SHIPPED - actions stop / resume / set_directive / clear_directive |
| GET `/api/loop-status` | `dashboard/routes_loop_status.py` | SHIPPED - `build_loop_status()` |
| Loop IPC dir | `ops/loop/control/` | SHIPPED - STOP, RUNNING.lock, cycle.txt, run_id.txt, directive.md, budget.json, blocker.txt |
| Single-flight primitive | `ops/loop/slots.py` | SHIPPED - `try_acquire` / `hold` / `pid_alive` / `is_stale` / `reap` |
| Named mutex | `ops/loop/winmutex.py` | SHIPPED - `hold(name, timeout)` |
| Transport into the live Claude window | `ops/loop/claude_gui_bridge.ahk` + `control/target_hwnd.txt` + `control/_claude_in.txt` | SHIPPED |
| Done ritual | `.claude/commands/done.md` | SHIPPED |
| Headless loop | `.claude/commands/headless-upgrade.md` | SHIPPED |

**Roughly 60 percent of the machinery is already there.** The work is a control
plane on top, not a new subsystem.

### HARD CONSTRAINT
`ops/loop/slots.py` and `ops/loop/winmutex.py` are **BYTE-IDENTICAL-BY-CONTRACT**
with `C:\Sibling-A`, pinned by `SHARED_SHA256` in
`tests/test_loop_concurrency.py`. Re-pinning is a JOINT act. **Do not edit either
file.** Build the lane lock as a NEW module that CONSUMES them.

### Live anomaly found while probing
`ops/loop/control/RUNNING.lock` holds **pid 9380, which is dead**. A stale lock
reads exactly like a live one from the file alone - `reference_loop_running_lock_stale_vs_dead`.
The UI therefore renders three lock states, not two: RUNNING / **RECLAIMABLE** / FREE,
and the reclaim decision comes from probing the pid, never from the file.

---

## Safety model (the operator's stated concern)

Four layers. Any one alone is insufficient.

1. **Arm-then-confirm.** First click ARMS with a 3s auto-disarm. Second click
   inside the window fires. A stray single click decays to nothing.
2. **Idempotency key.** The client mints one UUID per operator INTENT at arm
   time and reuses it on retry. The server keeps a short-TTL seen-key table;
   a repeat key returns the ORIGINAL result and spawns nothing. This is the
   layer that survives a frozen UI, which button-disabling does not.
3. **Lane lock, single-flight.** Shortcuts 3-8 are mutually exclusive. A fire
   while another lane holds the lock is **REFUSED, not queued** - a refused
   fire changes zero state. Lock held via `slots.try_acquire`, pid-probed.
4. **Queued intents never kill.** Shortcuts 1-2 write an intent file the running
   session consumes at its next safe boundary. Nothing is signalled or killed.

Every accepted, refused, collapsed and reclaimed event lands in the safety
ledger with its key, so a mis-fire is visible after the fact.

---

## The 8 shortcuts

### Session scope - queued, safe alongside a running lane

**1. Halt and Save.** Writes `control/STOP` (existing, proven path) plus
`control/INTENT_HALT_SAVE.json`. The session finishes its current step, runs the
done ritual, and writes the next-session bootstrap prompt to
`Desktop/RC-NEXT-SESSION.txt` instead of only emitting it inline. Purpose: park
the work and change topic later. Does not interrupt agents.

**2. /done Continue.** Writes `control/INTENT_DONE_CONTINUE.json`. Loop is
done ritual -> auto `/clear` -> auto-run the prompt the ritual just emitted.
Stays on the SAME line of work by construction: it consumes the emitted prompt
and nothing else, so it cannot be redirected by a headless directive.

### Headless lanes - mutually exclusive, one lock

**3. Headless-Upgrade.** Existing command. Ordering: UIUX or DS first, then the
other, then Research. Self-heals its own loop infrastructure. Runs until only
live-game-gated items remain.

**4. Headless-UIUX.** NEW command file. UI/UX queue plus usability deep-dives
across RC / DS / dashboard / overlay / menus / settings. Mock data rooted in real
match data so no client or live game is needed; OCR/CV confirmation on the
rendered result. Authorized to add, remove, relocate and redesign the UI
guidelines it works against.

**5. Headless-Research.** NEW. Research / lift / categorize. Expands and
clarifies items so lanes 4, 6, 7, 8 have well-formed work. This is the REFILL
lane - lane 3 drains, lane 5 refills.

**6. Headless-DS.** NEW. DS engine expand / lift / audit / bugfix / default-flip
with adjudication, plus creative tests that do not need the operator present.

**7. Headless-Repo.** NEW. File-by-file audit and refactor, prose reformatting,
file and folder restructuring, scratch cleanup, dead code, guards, health and
supervisors, modularization. Explicitly includes gitignored areas and Claude's
save locations elsewhere on the machine. Goal is an outsider-clean GitHub repo.
**Frozen-file edits require an adjudicating agent's approval** plus tests and CI.

**8. Headless-True-Audit.** NEW. Professional deep audit, one file at a time:
rewrite, test, harden every weakness found, security, machine environment.

Lanes 7 and 8 carry the highest blast radius. Both should ship LAST and both
should run against a worktree first.

**9. Headless-Gated (live).** Added 2026-08-02 on operator request, after S10.
`tools/headless-gated.md`. The WATCHER lane, and the only one whose work is
gated on something outside the repo: a real game running on Legion. It polls
`/api/state` on a 20s to 30s cadence and runs the DRAIN half of
`docs/LIVE_GAME_GATED_SYNC.md` only while `mode_key` is a game mode AND
`liveclient` is non-empty; otherwise it runs the PREP half (ready the next
drain, kill mis-filed rows, build the evidence plumbing, doc hygiene).

Its hard gate is a Settled finding, not a style preference: **the live-gated set
is NOT synthetically drainable** (measured 2026-07-18, 14 agents over 124 rows,
6 closed; the dominant kill was SUBSTITUTION - answering the compute half of a
question that asks whether something RENDERED). So the lane may never tick a row
without recorded live evidence (value + source + timestamp + a predicate stated
BEFORE looking), may never re-pitch synthetic drainage, and reports an honest
"no game this window" as a SUCCESS. It is the headless sibling of
`tools/live-gated-drain.md`, which is the operator-present version and is the
one that asks framed questions, names a lobby to queue, and runs `/done`.

Blast radius is LOW by construction - most of what it commits is Tier-0 doc
edits to one checklist - but it is worktree-mandatory like every other lane.

**10. Headless-Queue (drain).** Added 2026-09-05 on operator request.
`tools/headless-queue.md`. The DRAIN half of the lane-5 pairing the plan
already names at line 86 ("lane 3 drains, lane 5 refills"): lane 5 files
acceptance-bearing `RM-NN` rows, lane 10 executes them. It is the first lane
built to be RE-FIRED rather than clicked - `ops/loop/queue_loop.py` is a
driver that takes the lane lock, launches one worker, waits on its pid,
releases, and repeats.

**One row per cycle, and the worker exits.** The repeat lives in the driver,
not in the worker, for two reasons that are failure modes rather than
preferences: a `claude -p` worker that looped internally would accumulate
context across rows until it degraded, and a crash in row 4 would lose rows
1 through 3 with it. One process per row also keeps each pushed commit
reviewable on its own.

It ships to `main` by pushing a ref (`git push origin HEAD:refs/heads/main`,
fast-forward only) rather than by merging in a working tree, because CI fires
on push to `main` only and an unattended loop that parked 13 rows on a branch
would have proven nothing. Pushing a ref does not touch `C:\Riot Commander`,
so the worktree-mandatory rule is intact.

Stops on three sentinels, any of which ends the loop at the next cycle
boundary: `control/STOP` (the existing global halt),
`control/lanes/QUEUE_STOP` (this lane only), and
`control/lanes/QUEUE_DRAINED`, which the WORKER writes when no open,
non-gated row remains. That last one is the lane reporting its own queue
empty, and it is the only write into the main tree any lane makes.

---

## Machine concurrency budget (operator, 2026-09-06)

Legion is now shared by four headless workers across three repos, so lane
capacity is a MACHINE question and not a per-repo one:

| Repo | Concurrent lanes | Notes |
|---|---|---|
| Riot Commander | **2** | next up: true-audit loop + research loop |
| Resin (`C:\Sibling-B`) | 1 | reserved, its own control plane |
| Sibling-E (`C:\Sibling-E`) | 1 | reserved, lane port in progress |

**Two concurrent RC lanes are NOT possible as the code stands, and this is the
first thing to fix.** `ops/loop/lanes.py:138` is `MAX_SLOTS = 1`, and the
1-slot bucket in `slots.py` IS the mutex - the roster is mutually exclusive by
construction, not by convention. Two sites pin it: `tests/test_lane_lock.py:138`
asserts the value with the message "every lane is mutually exclusive with the
rest", and `lanes.py`'s own module docstring says the same in prose. Raising it
to 2 is a deliberate change to a control-plane invariant and needs its own
tests, not a one-character edit at wrap time.

**The measured constraint that should shape it.** This box is a Ryzen 7 7700X:
**8 physical cores, 16 logical**, and `pytest -n auto` resolves to **8 workers**
(measured 2026-09-06 - it counts physical cores, so "16-core machine" overstates
what `auto` will use). The RC dual suite is 31854 items: **250s at `-n auto`,
5070s serial** - a 20.5x speedup, superlinear, because the suite is wait-bound
rather than CPU-bound. Two RC workers each running that suite at `-n auto`
puts 16 pytest processes on 8 physical cores plus two agent processes plus
whatever Resin and Sibling-E are doing. So a second RC slot should come with a
worker-side cap (`-n 4` while two RC lanes are live) or staggered suite runs -
`reference_parallel_slices_full_suite_oom` is what over-subscription looks like
when it goes wrong, and it presents as an API error rather than as memory
pressure.

**The budget is a convention, not an enforced limit.** Each repo owns its own
lock (RC's lives at `ops/loop/control/lanes/`), so nothing stops all four
running at once, and nothing on this machine currently counts workers across
repos. That gap is worth a row before the count grows past four.

---

## Steer channel (added on operator request)

The native mechanism already works - a message sent mid-turn reaches the running
turn without stopping it. The panel exposes it with three tiers, default never
interrupting:

- **NOTE** - lands at the next safe boundary. Nothing is interrupted. DEFAULT.
- **STEER** - lands at the next tool boundary, seconds away. The turn adapts
  mid-flight; agents keep running.
- **INTERRUPT** - stops the turn. Arm-then-confirm, and the button must NAME the
  agents it will kill before you confirm.

An adjudicator states which tier is sufficient and why, so escalation is a
decision rather than a reflex. Transport is the existing AHK bridge writing
`control/_claude_in.txt`.

---

## Progress honesty

Percent is computed from **planned steps vs completed steps in the live
directive**, never from elapsed time. The basis is printed under the bar. Steps
can be added mid-run, so the number can go DOWN - that is honest and is stated
in the UI. When the step list is unknown the panel renders UNKNOWN, not 0 percent.
Source: Cloud Four, "Truth, Lies and Progress Bars"; AI UX Design Guide,
"Agent Status Monitoring" (layered ambient / expandable / interrupt-only-on-input).

---

## Build order

| Stage | Scope | Risk | Gate |
|---|---|---|---|
| S1 | Lane-lock module over `slots.py` (new file, no edits to the pinned pair) + 3-state pid-probed status + tests | low | unit tests |
| S2 | `/api/loop-control` extended with idempotency keys + `fire_lane` / `queue_intent` actions; refuse-not-queue semantics; tests | low | unit tests, no UI yet |
| S3 | Shortcuts 1 + 2 end to end - the two that cannot spawn a lane | medium | SHIPPED 2026-07-30 - live-confirmed STOP + Desktop prompt file |
| S4 | Dashboard panel wired to real `/api/loop-status`, read-only first | low | SHIPPED 2026-07-31 - see "S4 as shipped" |
| S5 | Shortcut 3 - existing headless command, first real lane fire | medium | SHIPPED 2026-07-31 `583c3430` |
| S6 | Commands 4, 5, 6 authored + wired | medium | SHIPPED 2026-07-31 `1153924e` |
| S7 | Steer channel - NOTE and STEER tiers only | medium | SHIPPED 2026-07-31 `1153924e` |
| S8 | Commands 7, 8 - highest blast radius, worktree-first, frozen-file adjudicator | HIGH | SHIPPED 2026-07-31 - see "S8-S9 as shipped" |
| S9 | INTERRUPT tier | HIGH | SHIPPED 2026-07-31 - see "S8-S9 as shipped" |
| S10 | DECOUPLE - Mission Control off the RC dashboard, own process + port, reachable by IP | HIGH | OPEN - operator-requested 2026-07-31, see "S10" |

## S10 - decouple Mission Control from the RC dashboard (OPEN)

**Operator requirement, verbatim 2026-07-31:** "i want to have this mission
control to be separate away from the RC game overlay : and accessible remotely
via ip or something . that way when someone is changes on the rc game overlay
and dashboard - the mission control is not affected."

### Why this is not a preference - the coupling is already proven harmful

Mission Control today is not a separate surface in any sense. It is a settings
card inside the RC game dashboard:

| Coupling | Where | Consequence |
|---|---|---|
| Same process | `web_dashboard.py` `:8888`, supervisor-managed | an RC restart for an overlay change bounces Mission Control too |
| Same routes module set | `dashboard/_dispatch.py:147` + `:210` wire `routes_loop_status` / `routes_loop_control` beside every game route | a fault anywhere in dispatch takes the control plane with it |
| Same JS bundle | the panel lives in `web/js/panels/dev.js`, the SHARED dev/settings panel | one syntax or scope error anywhere in that file kills Mission Control |
| Same page | `#loop-status-body` inside `web/index.html` | the control plane is only reachable by loading the whole game dashboard |

**S9 demonstrated the third row for real.** A single `mk` ReferenceError in
`dev.js` - a file whose other 900 lines are game-dashboard concerns - left the
INTERRUPT victim list unrendered while the armed kill button still displayed.
The control plane's most safety-critical element was broken by its proximity to
unrelated UI code. That is the argument for S10 stated as a measurement rather
than a principle.

The reverse direction is just as real: Mission Control is the surface you reach
for WHEN the dashboard is misbehaving, and today it dies with it. A control
plane that shares a failure domain with the thing it controls is not a control
plane.

### S10 design questions - RESOLVED by operator 2026-07-31

Full implementation-grade spec:
`docs/superpowers/specs/2026-07-31-mission-control-s10-decouple-design.md`.
The decisions, one line each:

1. **Port 8895**, own process (`mission_control.py` + `mc/`). Measured free;
   in use are 8888, 8889, 8890, 8891, 8860, 8861, 8901. `:8888` stays the game
   dashboard and loses both loop routes entirely (404, not a redirect).
2. **Own asset tree** `web/mc/{index.html,mc.css,mc.js}` plus `arm_confirm.js`
   moved out of `web/js/lib/`. Imports no game JS and no shared stylesheet -
   the small CSS duplication is accepted on purpose, because sharing
   `header.css` would restore the failure domain S10 exists to break.
3. **Reachable by IP, no cert regen needed.** A SAN is host-scoped, not
   port-scoped, and `tools/regen_rc_cert.ps1` already carries `legion-rc`,
   `legion-rc.tailc150de.ts.net` and `100.70.22.55`, so
   `https://100.70.22.55:8895/` validates against the cert Legion already
   trusts. `-k` is not used. Bind is **tailnet + loopback only**
   (`100.70.22.55` + `127.0.0.1`), never a wildcard - LAN `192.168.8.x` cannot
   reach the control plane at all.
4. **Auth: bearer token, POST-only**, resolved from `RC_MC_TOKEN` then
   `config/mission_control_token.txt`, mirroring `core/vision_token.py`. No
   hardcoded fallback and **no fail-open**: a server with no token configured
   refuses every POST with 503. GET stays open behind the bind scope.
   Comparison via `hmac.compare_digest`; the token is never logged or echoed.
5. **Shared modules, not duplicated ones.** `mc/` imports
   `dashboard.routes_loop_{status,control}` directly; `ops/loop/*` stays put.
   The one enabling edit is extracting `equals` / `prefix` into a stdlib-only
   `dashboard/_matchers.py` that `_dispatch.py` re-exports - without it, an
   `mc/` import would drag in `api_schema` + pydantic and quietly re-couple the
   two surfaces. Verified: `_dispatch.py` imports the game routes LAZILY inside
   the cache builders, so nothing in the game route tree is reachable from
   `mc/`.
6. **Lifecycle: own scheduled task `RC-MissionControl`** (ONLOGON, HIGHEST,
   `pythonw.exe`), NOT an `ops/rc_supervisor.py` entry - that file is frozen,
   and a shared watchdog would re-couple the two processes. Because that trade
   gives up the supervisor's auto-restart and ONLOGON fires only once, the task
   carries **`RestartCount=3` / `RestartInterval=1 minute`**; Task Scheduler is
   the watchdog. A bind failure **exits non-zero** rather than warning and
   idling, so the failure is visible in Last Result. `core.hot_reload` is
   deliberately not started: a control plane must not restart itself because an
   unrelated `.py` changed. Its own log file, not the shared daily log.
7. **The dashboard card is removed with no link left behind** (operator call).

Sequencing note: this is a relocation of a surface that now has **159 tests**
across `tests/test_interrupt_{tier,route,panel}.py`,
`test_mission_control_panel.py`, `test_loop_status_route.py`,
`test_lane_launcher.py` and `test_steer_channel.py`. Only the two panel files
pin file paths (they read `dev.js` and `header.css` off disk); the other five
are path-agnostic and move unchanged. Corrects the earlier "65 tests" estimate.

Verified while designing, so it does not need re-deriving: lanes outlive the
process that fired them (`lane_launcher` uses `CREATE_NO_WINDOW` with no job
object), and S9's INTERRUPT walks descendants of the LOCK HOLDER rather than of
the serving process - so moving the serving layer leaves the victim set
unchanged and Mission Control never appears in its own preview.

S1 and S2 are pure backend with tests and no ability to launch anything. They are
the correct first session.

## Decisions - RESOLVED by operator 2026-07-30

1. **Lane fire vs live interactive session** - **ALLOWED, WORKTREE-MANDATORY.**
   A lane may fire while an interactive session is live, but it may only ever
   run against a git worktree - never the main tree. Your session owns
   `C:\Riot Commander`; the lane owns a worktree and merges only when the main
   tree is idle. This is what makes the phone button usable without ever
   creating two writers to the same working directory, so the concurrent-index
   corruption class (`reference_gist_hook_worktree_index_corruption`) cannot
   arise. `try_acquire_lane` therefore REQUIRES a worktree argument and raises
   on empty, None, or a path resolving to the repo root.
2. **`Desktop/RC-NEXT-SESSION.txt`** - **OVERWRITE** each time. Single
   well-known path, no timestamp suffix, no accumulating pile on the Desktop.
   The prior contents are recoverable from the session transcript if ever
   needed. **RC- namespaced (operator, S3):** the Desktop is SHARED, and this
   design is meant to be lifted into Sibling-A and RM, so all three may
   run concurrently. Each repo owns its own prefix (`RC-` / `LW-` / `RM-`) and
   the consumer ENFORCES it - `resolve_next_session_path` falls back to its own
   default rather than honour a doc pointing at a sibling's file. Same rule as
   never cleaning another repo's file system without direct operator
   instruction. The intent files need no prefix: they already live under each
   repo's own `ops/loop/control/`.
3. **Lane 7 out-of-repo paths** - **ADJUDICATOR PER PATH.** No up-front
   allowlist. Every path outside the repo is proposed with a rationale and
   adjudicated individually before anything is touched.

## Integration constraints found by adversarial verification (S2, 2026-07-30)

**1. A fresh idempotency key per ARM is load-bearing, not cosmetic.**
MEASURED against the real S2 route with a stubbed lane module:

| step | lane | key | result |
|---|---|---|---|
| 1 | held | A | 200 `ok:false refused:lane_held` |
| 2 | held | A | 200 replayed, still refused - correct |
| 3 | **FREE** | A | 200 **replayed, STILL refused** - stale |
| 4 | FREE | B | 200 `ok:true`, token issued |

A refusal is remembered like any other settled 200, so a client that reuses one
key across arms sticks on "refused" forever even after the lane frees. The
arm-then-confirm design already mints a new UUID per arm, so this is correct as
specified - but it means **stage S4 must mint the key at ARM time and discard it
on disarm.** A key minted once per page load, or reused on retry-after-refusal,
produces a button that silently never works again. Pin this with a UI test in S4.

**2. The `root=` argument across the S1/S2 seam is unpinned.** S2 calls
`try_acquire_lane(lane, run_id=..., worktree=...)` with no `root=`, taking the
contract default. The contract says `root=None` but never states whether that
resolves to the control dir or the `lanes/` lock dir. Resolve when S1 lands and
add an integration test that exercises the real pair - a mismatch here is silent,
because both sides individually pass their own stubs.

**3. `/api/loop-control` has no schema model in `_dispatch._REQUEST_MODELS`** and
never has. S2 correctly followed the existing pattern rather than inventing one.
If schema validation is wanted it is a separate, deliberate change covering all
six actions, not a side effect of adding two.

## S3 as shipped (2026-07-30) - the consumer half

| Piece | File | Note |
|---|---|---|
| Intent reader / consumer | `ops/loop/intents.py` | `pending()` (never writes) + `consume()` + `resolve_next_session_path()` |
| CLI the ritual calls | `tools/session_intent.py` | `--peek` (always exit 0) / `--consume --prompt-file` (exit 1 on refusal) |
| Safe boundary | `.claude/commands/done.md` sections 0 + 10b | the done ritual IS the boundary; peek at the top, consume after the prompt is printed |
| Tests | `tests/test_session_intents.py` | 40 tests, incl. the seam pinned against the route module itself |

Three findings worth keeping, all of them measured rather than reasoned:

**Write order is prompt-first, marker-second.** A crash between the two leaves
`consumed: false`, so the retry rewrites the same bytes. The reverse order
strands the intent as done with no prompt on disk.

**`Path.write_text` corrupted the byte count.** The first live consume reported
1375 bytes while the Desktop file held 1395: text mode rewrites every LF as
CRLF on Windows, and a `read_text` round-trip translates it back, so a
string-equality test passes while the status line lies. `_awrite` writes bytes;
the guard test asserts raw bytes and that `result["bytes"] == st_size`.

**The already-consumed guard was unreachable in-suite.** Every test called
`consume(doc=None)`, so `pending()` filtered the consumed intent out before the
guard ran - a mutation removing it left the suite green. The real sequence is
peek -> (someone consumes) -> `consume(peeked_doc)`, which without the re-read
clobbers a fresh hand-off with a stale prompt. Found by the adversarial pass,
now pinned by `test_a_stale_peeked_doc_cannot_clobber_a_fresh_handoff`.

## S4 as shipped (2026-07-31) - the panel

| Piece | File | Note |
|---|---|---|
| Host element | `web/index.html` | `#loop-status-body`, a new MISSION CONTROL settings card |
| Lock blocks on the status route | `dashboard/routes_loop_status.py` | `lanes` + `controller_lock`, three-state, pid-probed, read-only |
| Renderer | `web/js/panels/dev.js` | lock rows + the two shortcut buttons |
| Arm-then-confirm | `web/js/lib/arm_confirm.js` | pure; key minted at arm, discarded on disarm |
| Tests | `tests/test_mission_control_panel.py`, `tests/test_loop_status_route.py`, `web/js/lib/arm_confirm.test.mjs` | 50 py (25 + 25) + 14 node |

**The panel had never rendered.** `#loop-status-body` existed only as a CSS class
and a `getElementById` call - it was in no markup anywhere - so
`renderLoopStatus` returned on its first line and the card shipped 2026-06-07
was dead from the day it landed. Nothing reported this, because every test that
touched it tested the renderer's inputs rather than its host.

**Constraint 2 above is RESOLVED.** `root=None` resolves to
`lanes.DEFAULT_ROOT` = `ops/loop/control/lanes`, and both sides take that
default. Pinned by `test_status_and_control_share_one_lane_root`, which fires
through the real `POST /api/loop-control` and reads back through the real
`build_loop_status()` with only `DEFAULT_ROOT` redirected - so a divergence
fails rather than passing on two sets of stubs.

**Two locks, not one.** `lane_state` reads `control/lanes/0.lock`, and that dir
does not exist until the first lane fires. The dead-holder case live on this
machine is `control/RUNNING.lock` (pid 9380), the loop controller's OWN
single-flight lock - a different file with a different owner and lifetime.
Reporting only the lane lock would have rendered FREE and hidden the exact
state the third state exists for, so both are probed and reported side by side.

Four defects the 5-phase UI audit caught before the commit, each of them a rule
worth keeping:

**A `var()` naming an undefined property fails SILENTLY.** `color: var(--bg)` on
the armed button was invalid at computed-value time and fell back to inherited
near-white: 1.9:1 on amber, on the one state where misreading the button costs
the most. `--bg` is defined in NO stylesheet in `web/css`. It passed every
source grep for the token name. Now `var(--canvas)`, measured 9.03:1 live, and
`test_every_custom_property_the_s4_css_uses_is_actually_defined` fails on the
whole class.

**A 4Hz repaint made the flow mouse-only.** `_mcPaint` rebuilds the row via
`innerHTML` while the countdown runs, so arming from the keyboard threw focus to
`<body>` and the confirm click inside the 3s window could not be reached. Focus
is now carried across the repaint.

**`dim` is inert.** `web/css` defines no bare `.dim` rule - every one is
descendant-scoped - so the incidental pid/run metadata rendered at full
brightness, LOUDER than the `--fs-xs` note explaining the RECLAIMABLE state
beside it. The least important text in the row was the brightest.

**Two tokens fail AA on `--surface-alt`.** `--text-faint` measures 3.94:1 and
`--bad` 3.66:1 there; `base.css` documents `--text-faint` as AA-raised "on
--surface", and the lighter alt surface loses that guarantee.

## S5-S7 as shipped (2026-07-31)

| Piece | File | Note |
|---|---|---|
| Lane launcher | `ops/loop/lane_launcher.py` | worktree + spawn + pid re-point; releases the lane on ANY failure |
| Lock re-point | `ops/loop/lanes.repoint_lane_pid` | rewrites the holder pid AND `_OWNED` together |
| Lane docs | `tools/headless-{uiux,research,ds}.md` | wired; `repo` + `true-audit` deliberately NOT |
| Steer channel | `ops/loop/steer.py` + `tools/session_steer.py` | append-only JSONL + a separate cursor |
| Tests | `tests/test_lane_launcher.py`, `tests/test_steer_channel.py`, `tests/test_web_js_esm_parse.py` | 21 + 17 + 2 |

**The steer transport in this document was WRONG in both halves, and the
correction is the finding.** It said "the existing AHK bridge writing
`control/_claude_in.txt`". That file is the ADJUDICATOR's stdin
(`ops/loop/adjudicator.py`); the bridge polls `control/gemini.ready`, which is
the loop controller's own directive channel and would collide with a live
directive. On top of that the bridge was not running and `target_hwnd.txt` held
hwnd 66248, which `IsWindow` reports dead. The decisive fact is structural
rather than incidental: a headless lane worker spawned by S5 has NO window, so a
GUI transport can never steer the lanes this plan exists to create. The channel
is a file.

**Tier honesty.** The tier does not change the transport, only when the consumer
looks and how urgently it is told to act. Latency is the consumer's poll
cadence, not magic - a consumer that only peeks at its done ritual sees a STEER
there and nowhere earlier. INTERRUPT is a different act (it stops a turn and
kills agents) and is REJECTED with a 400 until S9, never downgraded to a note.

**`DETACHED_PROCESS` makes a spawned worker a silent no-op.** Three spawns of
one script differing only in creationflags: `NO_WINDOW|DETACHED` gave a pid,
rc=0 and NO log; `NO_WINDOW` alone worked; `DETACHED` alone gave a pid, rc=0 and
no log. powershell.exe cannot initialise its host without a console. A lane
would have flipped RUNNING then RECLAIMABLE right on schedule having done
nothing - a failure indistinguishable from a healthy short run.

**`node --check` is not a syntax gate for this tree.** Measured on node
v24.15.0: it catches a duplicate `const` in a file leading with `export`, and in
plain CommonJS, but goes blind on a file leading with `import` - which is every
module in `web/js`. One duplicate `const` killed the whole panel while
`node --check` and 35 source-contract tests stayed green.

**`core.hooksPath` is absolute and worktrees share `.git/config`.** Hooks fire
inside a lane worktree but execute the MAIN tree's hook bodies, so a hook change
made on a lane branch is inert until merged. Lane 7 must not run
`scripts/install_hooks.py` from a worktree - it rewrites shared config.

## Out-of-repo footprint - MEASURED 2026-07-30

Answers "are there other locations". Yes: roughly **67 GB** outside the repo.

| Path | Files | Size | Lane-7 posture |
|---|---|---|---|
| `%LOCALAPPDATA%\Temp\claude\C--Sibling-A` | 3,376 | **35.5 GB** | SIBLING REPO scratch. Cross-repo act - propose, never auto-clean |
| `%LOCALAPPDATA%\Temp\claude\C--Riot-Commander` | 152,231 | 9.5 GB | RC session scratch. Safe to prune BY AGE |
| `%APPDATA%\Claude\vm_bundles` | 9 | 8.9 GB | Desktop-app runtime. Do not touch without app-version check |
| `%USERPROFILE%\.cache` | 5,628 | 7.5 GB | Mixed tooling cache. Per-subdir adjudication |
| `%USERPROFILE%\.claude\projects` | 6,707 | 1.9 GB | **EVIDENCE, NOT GARBAGE - see below** |
| `%USERPROFILE%\.claude\plugins` | 116,872 | 1.5 GB | Plugin installs. Prune only unreferenced marketplaces |
| `%APPDATA%\npm` | 1,830 | 0.9 GB | Global npm. Out of scope |
| `%USERPROFILE%\.gemini` | 1,314 | 151 MB | Director state. Retain |
| `%USERPROFILE%\.perseus-vault` | 4 | 99 MB | Recall store. RETAIN - never prune |

### Carve-out that must be encoded before lane 7 runs
`~/.claude/projects` holds the **session transcripts**. Those are the exact input
CCR-143 (`red-handed`, scored 9 this session) audits to verify "tests pass"
claims against git history. Pruning them destroys the only record that makes
retroactive verification possible. They are evidence. Lane 7 may compress or
archive them; it may not delete them.

`Temp\claude\C--Sibling-A` at 35.5 GB is the single largest item and it
belongs to the SIBLING repo. Touching it is a cross-repo act under the same
joint-action rule as `slots.py`. Propose to the operator; never auto-clean.

## S8-S9 as shipped (2026-07-31)

| Piece | File | Note |
|---|---|---|
| Lane 7 doc | `tools/headless-repo.md` | BREADTH - restructure, clean, modularize |
| Lane 8 doc | `tools/headless-true-audit.md` | DEPTH - one file at a time, rewrite + harden |
| Wiring | `ops/loop/lane_launcher.py` LANE_COMMANDS | all six lanes wired; the panel derives its greyed-out set from this map |
| INTERRUPT | `ops/loop/interrupt.py` | preview / fingerprint / execute |
| Route | `dashboard/routes_loop_control.py` | `interrupt_preview` (read, unkeyed) + `interrupt` (keyed, fingerprint-gated) |
| Panel | `web/js/panels/dev.js` + `web/css/panels/header.css` | arm goes through the preview, never the raw click |
| Tests | `tests/test_interrupt_{tier,route,panel}.py` | 17 + 13 + 16 |

**Naming the victims is the easy half; the fingerprint is the half that makes it
true.** The plan asked that the button "NAME the agents it will kill before you
confirm". A list rendered at preview time is a claim about a moment that has
already passed - between the preview and the confirm a worker exits, a lane is
reclaimed, another fires, and Windows recycles the pid. A confirm that simply
re-enumerates would kill processes the operator never saw while the UI had
honestly named the ones it did: the list would be true and the kill still
wrong. So `preview` mints a digest over the exact victim set, `execute`
re-probes and compares, and a mismatch is a REFUSAL carrying the fresh list.
The digest covers process START TIME, not just pid, because a pid alone cannot
tell a live worker from its recycled number.

**Descendants are victims, and order matters.** The lock records the pid of the
`run_lane.ps1` powershell runner; the process doing the work is the `claude -p`
child under it. Naming only the holder would let the operator confirm a kill
that leaves the actual agent running. They are reaped deepest-first - killing
a parent first re-parents its live children away, and the next enumeration no
longer links them. `taskkill` is called WITHOUT `/T` for the same reason the
fingerprint exists: letting taskkill walk the tree itself would kill
descendants that appeared after the preview, which are by definition unnamed.

**An unknown tier degrading to NOTE was the safe answer until it wasn't.**
`steer.normalize_tier` maps anything unrecognised to the default, and while
INTERRUPT existed only as a 400 at the route that was correct - an unknown tier
became a note that executes nothing. The moment S9 made INTERRUPT real the same
degrade became the hazard: a caller asking to stop the agents would get a note,
and the UI would report an interrupt that never happened. `append` now REFUSES
an audit-only tier instead of degrading it, and `record` is the only door into
the log for one. An S7 test asserted the old behaviour using "INTERRUPT" as its
literal example, so shipping S9 required changing a test that was right when it
was written.

**Two S5 tests were hostages to the roster.** `test_the_two_highest_blast_radius_lanes_stay_unwired`
and the missing-doc test both used "true-audit" as a fixture BECAUSE it was
unwired. Wiring it in S8 did not just break them - it would have silently
emptied them: a test whose subject is "an unwired lane raises" measures nothing
once no lane is unwired. The first is now the S8 acceptance (all six wired) and
the second builds its fixture explicitly.

**TWO defects were invisible to every source-level test and died only under a
live click.** Both were in the panel, both left the whole suite green, and both
were found by driving the real dashboard against a real staged victim set.

1. **`mk` is a function-LOCAL const, so at module scope it is a ReferenceError.**
   `_mcPaintInterrupt` built the victim list with `mk(...)`, copying the idiom
   from inside `renderLoopStatus` where `mk` is in scope. The throw was
   swallowed by the preview's own `.catch` and surfaced as "request failed",
   while the armed button still read `Confirm INTERRUPT - kill 3` with NO list
   beneath it. A blind kill wearing the safety feature's clothes. The existing
   code already solved this twice - define a local, or take `mk` as a parameter
   the way `_loopLockRow(mk, ...)` does - and a guard now fails on any
   module-scope function that reaches for it.

2. **`_mcArm.confirm()` notifies SYNCHRONOUSLY, and the repaint ate the
   fingerprint.** The confirm handler read `_mcIrq.fp` after calling
   `confirm()`; that call disarms, notifies, repaints, and the repaint sees
   `armed === false` and clears the fingerprint by design. So the POST went out
   with no fingerprint and the server correctly answered 400. The tier failed
   SAFE - nothing was killed - but it could never kill anything either, and it
   looked identical to a network error. The handler now captures the
   fingerprint before `confirm()` and passes it in.

The shared lesson is that both bugs were about a binding's lifetime, and a
source-literal test cannot see a lifetime. Mutation testing did not help
either: every mutant of the WRITTEN property was caught, because the written
property was not the broken one.

**End-to-end, measured.** With three real staged processes (a powershell
parent, its conhost, and a sleeping worker child), preview named all three,
the confirm killed all three, and the ledger recorded
`killed [23884, 27572, 5960]` - children before the parent, which is the
ordering the docstring claims and `taskkill` without `/T` requires.

**The no-`/T` property was documented and pinned by nothing.** Adding `/T` to
the argv left all 124 tests green. It is now pinned as exact argv, the way
`tests/test_loop_executor.py` already pins the executor's.

**The psutil fallback silently voided two of the three safety properties.** An
ImportError degraded to naming seed pids with `started=None`, which drops every
descendant from the victim list AND collapses the fingerprint to pid-only,
behind one log line. It now raises: a tier that cannot enumerate honestly must
refuse to run.

**`--bad` fails AA as button ink in five of six themes.** Measured live at the
rendered 18px/700 - below the 18.66px bold large-text threshold, so the 4.5:1
bar applies: arcane 3.28, moonlit 3.31, hextech 3.66, ember 3.79, bloodmoon
3.79, terminal 4.59. The border keeps the danger colour (a non-text element
owes 3:1) and the label is `--text`, measured 10.83:1 - the same split
`.loop-lock-state.unavailable` already made in this card.

**The mirror drifted against a moving target.** `tools/*.md` and
`.claude/commands/*.md` were byte-equal and `drift_guard` reported clean, then
diverged minutes later: the authoring agents were still editing the tracked
side after the mirror was taken. The mirror is only meaningful once every
writer has stopped - the same rule as never committing while agents are live.
CRLF is the usual suspect here and was not the cause; both sides were pure LF.

## S10 as shipped (2026-07-31, complete)

Nine tasks. Tasks 1-8 built and proved the standalone control plane; task 9
deleted the dashboard's own copy. Both halves shipped the same day.

| Piece | Where | Note |
|---|---|---|
| Standalone package | `mc/__init__.py`, `mc/auth.py`, `mc/handler.py`, `mc/routes.py`, `mc/server.py`, `mission_control.py` | imports the existing `dashboard/routes_loop_status.py` + `routes_loop_control.py` - never forks the loop logic |
| Standalone page | `web/mc/index.html`, `mc.css`, `mc.js`, `arm_confirm.js` (+ `arm_confirm.test.mjs`) | moved out of `web/js/lib/`; imports NO game-dashboard code, checked by `mc.js`'s own header comment and `test_mc_package_imports_no_game_code` |
| Bind + auth | `mc/server.py` | :8895, loopback + tailnet only (`127.0.0.1`, `100.70.22.55`) - no LAN, no wildcard; bearer token, fails closed on an unconfigured server (503, never open) |
| Scheduled task | `tools/install_mission_control_task.ps1` -> `RC-MissionControl` | its OWN task, not an `rc_supervisor` entry - an RC restart for a game-overlay change must never touch the control plane. AtLogOn (fast boot start) + a `-Once` trigger with a 1-min indefinite repeat (the AtLogOn-only first attempt never got a computable `NextRunTime`, so the repeat trigger IS the watchdog: alive -> `MultipleInstances=IgnoreNew` no-ops the tick, dead -> the tick starts it) |
| Dashboard removal | `web/js/panels/dev.js`, `main.js`, `index.html`, `web/css/panels/header.css`, `dashboard/_dispatch.py`, `dashboard/routes_static.py` | task 9 - the Headless-loop-status panel, its router call, its settings-card, its CSS block, its two route registrations, and the fix-round-1 transitional `/mc/` static route are all gone. `:8888/api/loop-status` and `/api/loop-control` are 404 by design |
| Residue guard | `tests/test_mission_control_server.py` | set-equality over 25 identifiers across the four edited dashboard files - a partial deletion fails loudly instead of shipping a card that renders and does nothing |

**Six acceptance criteria, all live-verified before task 9 started:** the
standalone process serves both routes on :8895 independent of `web_dashboard.py`
being up or down; auth gates POST and fails closed; the scheduled task
self-heals a killed process (measured: dead with no hand-start, back on a new
pid within the observation window); the page renders and arm-then-confirm
works against the real server; the cert covers both bind addresses; and
`ops/loop/*` was never forked - `mc/routes.py` imports the same two dashboard
route modules the old dashboard dispatch table used to register.

**The failure domain S10 exists to sever, closed from both directions.**
S9 proved the forward case live: a single `mk` ReferenceError in
`web/js/panels/dev.js` - dashboard code, not Mission Control code - left the
INTERRUPT victim list unrendered while the armed kill button still displayed.
Task 9 proved the reverse would have been just as real: `dev.js` had a
bottom-of-file `export { ... renderLoopStatus ... }` statement neither the
plan nor its corrections named. Deleting the function without also removing
it from that export list is a static SyntaxError - exporting an undefined
name - which aborts the whole ES module graph and blanks the ENTIRE dashboard,
not just the panel. `tests/test_web_js_esm_parse.py` (extended over `web/mc/`
in task 7) is what would have caught it in CI; here TDD order caught it before
that mattered. Same lesson, opposite file, opposite direction - which is the
actual argument for two failure domains instead of one.

**Verification a source-level test cannot do: two live clicks.** Armed
"Halt and Save" and let the 3s window expire - the `.loop-btn-armed` class,
the "Confirm ... (3s)" label and a same-tick `Cancel` button all appeared on
arm and fully reverted on timeout, no stuck state. Armed "/done Continue" and
confirmed it within the window, which fires the real `_mcFire`-equivalent
code path including a real `fetch` to the real server - safe by construction
(auth runs before dispatch, proven by this repo's own
`test_live_post_without_token_never_reaches_the_route`, and no MC token was
cached in the audit browser) and confirmed after the fact two ways: the
network log shows a genuine `401 Unauthorized`, and `ops/loop/control/STOP`
- the untouchable operator halt - is byte-identical before and after, same 30
files in the directory, same 39 bytes. This is the same defect class S9 found
twice (a function-local `mk` referenced at module scope; a confirm that ate
its own fingerprint on repaint) and the class the S9 section above says
plainly: mutation testing did not catch either one, because every mutant of
the WRITTEN property was caught - the written property was not the broken
one. Only a live click has ever found this class of bug in Mission Control,
and it is now 2 for 2 confirming a clean state rather than finding a third.
