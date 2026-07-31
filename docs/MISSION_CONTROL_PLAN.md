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
`Desktop/NEXT-SESSION.txt` instead of only emitting it inline. Purpose: park the
work and change topic later. Does not interrupt agents.

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
| S3 | Shortcuts 1 + 2 end to end - the two that cannot spawn a lane | medium | live: confirm STOP + Desktop prompt file |
| S4 | Dashboard panel wired to real `/api/loop-status`, read-only first | low | UI fixture ritual |
| S5 | Shortcut 3 - existing headless command, first real lane fire | medium | one supervised run |
| S6 | Commands 4, 5, 6 authored + wired | medium | one supervised run each |
| S7 | Steer channel - NOTE and STEER tiers only | medium | live |
| S8 | Commands 7, 8 - highest blast radius, worktree-first, frozen-file adjudicator | HIGH | operator sign-off |
| S9 | INTERRUPT tier | HIGH | operator sign-off |

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
2. **`Desktop/NEXT-SESSION.txt`** - **OVERWRITE** each time. Single well-known
   path, no timestamp suffix, no accumulating pile on the Desktop. The prior
   contents are recoverable from the session transcript if ever needed.
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
