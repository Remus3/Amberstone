# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-06 - LANE 10 BUILT AND RAN: a queue-drain loop shipped 15 rows overnight

**FIRST ACTION NEXT SESSION: stop the queue loop before firing anything else.**
The lane roster is a 1-slot mutex, so a new lane cannot start while this one
holds it. Clean stop, at a cycle boundary, no work lost:

```
echo stop > "C:\Riot Commander\ops\loop\control\lanes\QUEUE_STOP"
```

Then delete that file once the driver has exited, or the next launch refuses.
Hard stop if needed: `taskkill /F /T /PID <driver pid>` (never `Stop-Process`).
Driver pid is in `ops/loop/reports/queue_loop.log`; cycle history is
`ops/loop/reports/queue_loop.jsonl` (both gitignored as of this session).

STATE. LEDGER 1338. NEW lane 10 `queue`: `tools/headless-queue.md` (worker
prompt), `ops/loop/queue_loop.py` (driver), `ops/loop/launch_queue_loop.ps1`,
roster wiring in the five sites that must agree, plus a `README.md` refresh
(the port map was missing `:8890` / `:8891` / `:8895`). It drains one filed row
per cycle: the worker ships exactly one row and EXITS, and the driver re-fires
it, because a worker that looped internally would accumulate context until it
degraded and a crash in row 4 would take rows 1-3 with it.

SHIPPED BY THE LANE, unattended: **RM-348 through RM-360 plus RM-363** - the
entire lane-5 refill queue - each its own commit, ledger entry and CI green.
It also FILED RM-369 through RM-379 off its own sibling sweeps. Next free id
was RM-380 at hand-off; re-derive, do not inherit.

**THE LESSON WORTH THE MOST, and it cost three iterations: an instruction a
worker can rationalize past is not a mechanism.** CI acceptance was
unsatisfiable at the lane's own cadence - `ci.yml:38-40` cancels in-progress
runs per concurrency group, a run takes 45-67 min, a cycle takes 25-45, so
cycle N+1 always killed cycle N's run. Fix 1 moved the read to a
`workflow_dispatch` group; the lane's own next dispatch cancelled it 23 minutes
later. Fix 2 told the worker in prose to BLOCK until its run completed; over six
cycles it complied twice and bailed early four times. Fix 3 moved the wait into
the DRIVER (`wait_for_ci`), which cannot rationalize because it is the only
thing that starts the next cycle. Verdicts now land inside each cycle's own
JSONL row; a `failure` sets `stopped_by=ci_red` and stops the loop. **The lane
filed RM-370 against my first two attempts - read it before touching this.**

FOUR DEFECTS IN MY OWN WORK, all found by RUNNING it rather than reading it:
the launcher passed an unquoted path so `pythonw` got `C:\Riot` and the launcher
printed "driver started" over a dead process; three tests read live machine
state (one asserted a stale `STOP` file existed, two took the REAL driver mutex
and went red exactly when the lane was looping); and `lanes.py` said "seven
headless lanes" over an eight-entry tuple - fixed by deleting the count from the
prose, not incrementing it.

MEASURED THIS SESSION, for anyone sizing work on this box: dual suite 31854
items, **250s at `-n auto` / 5070s serial** (20.5x, superlinear - the suite is
wait-bound); `-n auto` resolves to **8 workers, not 16** (Ryzen 7 7700X, 8
physical / 16 logical); pre-commit gate on a 1-file commit **2.6-5.3s**; and
**there is no pre-push test hook at all** - `.githooks/pre-push` is the stock
Git LFS hook, so CI is the only suite gate.

NEXT SESSION, as directed: a **true-audit headless loop lane** and a **research
headless loop lane**, both on the lane-10 driver pattern rather than one-shot
fires. **Blocker, stated so it is not discovered at run time:**
`ops/loop/lanes.py:138` is `MAX_SLOTS = 1` and the 1-slot bucket IS the mutex,
so two concurrent RC lanes need that raised, with `tests/test_lane_lock.py:138`
and the module docstring updated deliberately. Machine budget and the
oversubscription math are now in `docs/MISSION_CONTROL_PLAN.md` under "Machine
concurrency budget": RC 2 lanes, Resin 1, Sibling-E 1, and a second RC slot
wants a worker-side `-n 4` cap because `-n auto` is 8 and two suites at once
would put 16 pytest processes on 8 physical cores.

ALSO: RM-368 filed for the `github.com/affaan-m/ECC` harness lift - MIT, license
gate passed against all three declarations, whole-package lift REFUTED in the
row itself, three sub-rows worth taking. A Sibling-E session was spawned
separately to port this lane there.

---

# 2026-09-05e - ROW EXECUTION: RM-347 shipped, gate caught two false rationale lines

STATE. LEDGER 1337. One row, inline TDD, `be7747fcb` on `main` (single production
file + single test file, so there were no disjoint slices to parallelize; the
adversarial property was preserved with a read-only `verifier` against the
finished tree). Suites measured on the committed tree: `pytest tests -n 8`
**20697 passed / 96 skipped / 4859 subtests / exit 0** (baseline 20673, so +24 =
exactly the new file); `pytest agents/daemon_slayer -n 8` **10856 passed / 13662
subtests / exit 0**, unchanged. No `ENGINE_VERSION` bump, no `:8860` bounce, no
Share sync, no frozen file. Next free id **RM-368** - RM-367 was minted.

WHAT SHIPPED. `lcu/lcu_pregame.py` `get_gameflow_phase` returned the string
`"None"` from all three bail-outs (bare `except`, no cached port/auth, non-str
non-None body), and `"None"` is a REAL phase - the LCU's idle-at-home-screen
value. Failure is now Python `None`; genuine phases including `"None"` still
return strings. New `_phase_or_none` unwraps LCU JSON quoting on both paths and
rejects an empty body.

FOUR THINGS WORTH CARRYING FORWARD.

1. **A test-only MIRROR is not the consumer.** Filing RM-367 nearly cited
   `dashboard/view_router_state.py` as the code a naive fix would break. It has
   the right three `not phase` arms and reads exactly like the router - and its
   own docstring at `:1-7` says it is NOT imported at runtime. The live arms are
   `web/js/main.js:711` and `:728`. Sibling of
   `feedback_scan_is_not_a_reachability_probe`: a faithful mirror of live logic
   can still be zero-consumer code.

2. **Two existing conventions means "be consistent" settles nothing.** This
   failure class already had `""` (`lcu_postgame_collector.py:1034`) AND
   `"Unknown"` (`snapshot_shape.py:415-421`) in-tree. The sentinel was picked
   from the CONSUMER contract instead - `dashboard/_cs_retention.py:49-56`
   treats the string `"None"` as a clear phase and Python `None` as "unknown, do
   not act".

3. **A realism pin is not a breadth pin.** A test justified itself by claiming
   `HTTPError` is not an `OSError` subclass, so the handler could not be a narrow
   `except OSError`. The gate measured the MRO: HTTPError -> URLError ->
   **OSError**. False, and the test proved less than it claimed. Relabelled, and
   a real `ValueError` case now carries the breadth claim.

4. **Zero-caller rows again, second day running.** `get_gameflow_phase` has no
   in-repo caller, so the row's "caller-side assertion" acceptance clause was met
   with consumer-contract tests that SAY they are not caller tests. RM-346 hit
   the same shape yesterday. When a row asserts a call path, re-derive it.

FILED, NOT FIXED. **RM-367** - `snapshot_shape.py:415-421` reports an empty
gameflow body as phase `""`, same class, and this reader IS live behind
`/api/state.lcu`. The one-line consistency fix to `"Unknown"` is a regression: a
falsy phase is load-bearing at `web/js/main.js:711`/`:728`, and `"Unknown"` is
truthy and matches no explicit arm. Body + acceptance in `BACKLOG.md`.

HOUSEKEEPING. ROADMAP hit 90.4 pct (`tools/drift_guard.py` warns at 90), so the
closed RM-346 / RM-362 line was relocated verbatim to
`docs/ROADMAP_HISTORY.md` (2026-09-05b) in the same commit; back to 89.5 pct.
The RM-344/345/361 line was left alone on purpose - RM-345 is SHIPPED-PARTIAL
with RM-366 open on the same line, the mixed state the convention excludes.

STILL GATED. **RM-366** needs operator approval - it edits the FROZEN
`lcu/lcu_client.py`. Until then a faulting LCU POST is still sent twice.

---

# 2026-09-05d - ROW EXECUTION: RM-346 / RM-362 shipped, gate refuted the MERGER this time

STATE. LEDGER 1336. Two worktree slices merged `--no-ff` with zero conflicts
(`753ea0937`, `fe1678f2b`) plus in-merger follow-up `7d9e9b7a7`. Suites measured
on the merged tree: `pytest tests -n 8` **20673 passed / 96 skipped / 4859
subtests / exit 0**; `pytest agents/daemon_slayer -n 8` **10856 passed / 13662
subtests / exit 0**. No `ENGINE_VERSION` bump, no `:8860` bounce, no Share sync,
no frozen file touched. Next free id still **RM-367** - nothing new was minted,
because the one sibling defect found was fixed in-slice rather than filed.

WHAT SHIPPED. **RM-362** - `core/hot_reload.py:95` was `any(s in r for s in
_SKIP_DIRS)`, an unanchored substring test, so any watched file whose path
merely CONTAINED `data` / `web` / `logs` / `Share` was silently dropped. Now
segment-anchored, basename excluded from the window, `docs/_archive` matched as
a consecutive run at any depth. **RM-346** - the three `lcu/lcu_pregame.py`
champ-select readers are now total against JSON `null` and non-dict elements.

THREE THINGS WORTH CARRYING FORWARD.

1. **The row's count was wrong and the missing item was the interesting one.**
   RM-362 said 22 unwatched files; the truth is 23, and the 23rd is
   `web_dashboard.py` itself - excluded because its own BASENAME contains `web`,
   so the watcher could not see the module that starts it at `:59`. Three
   parties derived 23 independently before comparing.

2. **The verifier refuted the MERGER, not a slice.** The merger swept for
   sibling cases by grepping `int(` and declared the three sites complete. The
   root cause is not `int()`, it is `.get()` returning `None` - so the sweep
   missed `get_my_pick_action` 15 lines up, measured raising on five shapes.
   **A pattern-scoped sweep is not a root-cause sweep.** Fixed in the same slice
   per the root-cause-first rule.

3. **A crashed xdist run reads exactly like a green one.** Three suite runs were
   discarded: two had all 8 workers die with `OSError: cannot send (already
   closed?)` at `pytest_sessionfinish`, leaving a truncated file with NO summary
   line - and `grep -c FAILED` on it returns 0, which looks like success. The
   third was a real `1 failed` (`test_live_three_profiles`, `engine error: timed
   out` vs DS `:8860`) that passed standalone with `:8860` reporting `status:
   ok`. Cause of all three was contention - a verifier subagent running pytest
   while the merge had just bounced RC. Assert on the summary line AND the exit
   code, never on the absence of `FAILED`.

ALSO. The RM-346 row's "spell auto-push path" framing is REFUTED - all three
readers have zero in-repo callers, and the auto-push path reads the same wire
fields inline at `lcu_rune_writer.py:879` with its own `or 0` guard. The defect
is latent public surface on the `LcuClient` mixin, not a live crash. Correction
is committed in the shipped docstrings, not only in the ledger. Two residuals
deliberately not filed, with reasons in LEDGER 1336: `_aram_mode` (declares
`mode: str`, no null contract, zero callers) and the pre-existing
case-sensitivity of the skip match (non-regressing, non-leaking).

NOTE. RC now restarts on edits it previously ignored - 14 of the 23 newly
watched files are under `tests/`.

---

# 2026-09-05c - ROW EXECUTION: RM-344 / RM-345 / RM-361 shipped, and the gate refuted one

STATE. LEDGER 1335, pushed `cfb46f99b..f459e56eb`. Three worktree slices merged
`--no-ff` with zero conflicts, worktrees + branches cleaned. CI green at STEP
level on `f459e56eb`: `check` -> `full dual suite (RM-119) => success`, and
`docs-guards` success. Local dual suite measured THIS run from the merged tree:
`pytest tests -n 8` **20625 passed / 96 skipped / 4859 subtests**, `pytest
agents/daemon_slayer -n 8` **10856 passed / 13662 subtests**, both exit 0. RC
bounced pid 24988 -> **16220**, `last_reload_ok=true`. Next free id **RM-367**,
moved in BOTH pointers in one commit.

THE THING WORTH CARRYING FORWARD: **RM-345 shipped PARTIAL, and only the
adversarial gate caught it.** The slice was green, its tests were real, and its
claim was still wrong. The pool now sends a non-idempotent method exactly once -
but `lcu/lcu_client.py:191` reads the give-up `None` as "pool unavailable" and
falls through to urlopen at `:200`, re-sending the identical body. True effect is
3 sends to 2, NOT to 1. This is the `feedback_verified_claim_vs_measured_
downstream` class: the slice proved its change happened, not that it mattered
end-to-end. Docstring was scoped and the residual disclosed BEFORE merge; residual
is RM-366 and needs operator approval because `lcu_client.py` is FROZEN.

THE OTHER ONE: **two independent censuses of the sanitizer population DISAGREED**
(16 sites / 14 builders vs 19 sites / 14 modules + 3 `moon_proxy` relay paths).
Recorded unaveraged in RM-364 as probes. The structural finding is the valuable
half - the SDK `messages.create` is the FALLBACK for the top TFT sites, the
primary leaving via `moon_proxy`, so **a fix at the API call would be dead code**;
patches belong at prompt ASSEMBLY. Census 2 also sharpened the threat model: no
summoner name / riot ID / chat / queue name reaches any prompt (identity-match
keys, discarded), so the unconstrained bytes are VISION/OCR MODEL OUTPUT - a
self-inflicted model-to-model channel. And it killed three non-exposures a naive
reading of RM-361's acceptance would have had someone "fix":
`modes/shared_vision.py:400` (image + RC-authored constant only),
`warm_session.py:222` (operator text), `aram_team_analyzer.py:201` (no caller).

TWO TRAPS THAT COST TIME:
1. **A serial `pytest tests` ran 15 min and wrote ZERO bytes** (`-q` buffers), so
   it looked wedged. Killed and re-run under `-n 8`: 377s. Always `-n 8`.
2. **The stop-claim gate blocked twice on TRUE statements** about
   subagent-authored commits. `tools/stop_claim_gate.py:322` derives `did_commit`
   from THIS session's own Bash, so `git show` corroboration cannot satisfy it by
   design. Do not rephrase around it - do the real commit work; a merge session
   whose commits were all authored in worktrees will hit this every turn.

NEXT. Queue is RM-346..RM-360 + RM-362/363 still open from the lane-5 refill,
plus RM-364/365/366 filed today. RM-366 is operator-gated (frozen file).

---

# 2026-09-05b - MERGE SESSION: both cycle-48 lanes are ON MAIN, ids assigned, MC bounced

STATE. LEDGER 1334. `lane/research` then `lane/true-audit` merged in plan order
(`e173e6ab2`, `ea45ff5be`), then `8263bb311` for ids + a CI fix, then the wrap
commit. Main is green: dispatched run 33968377531 on `8263bb311`, `check` job
`full dual suite (RM-119) => success` verified at STEP level, `nightly-full-suite
=> success`. `RC-MissionControl` pid 2092 -> **20600**, `/api/loop-status` 200.

THE TWO THINGS THAT COST TIME, so they do not cost it twice:
1. The merge went in RED and the lanes could not have known. `docs-guards` +
   `ci` both failed on `ea45ff5be` on ONE test - the RM-171 citation guard, on
   `coach_integration/_sr_prompt.py:308` in the refill doc, written there with a
   leading dot-slash. That prefix reads as an untracked path. Content was
   correct; the prefix was dropped. Do NOT write the dot-slash form in a doc,
   not even when quoting the defect - this entry tripped the same guard once.
2. **A docs-only fix cannot prove itself.** `ci.yml:24` path-ignores `**/*.md`,
   so the fix commit ran ONLY `docs-guards`. Believing that green would have left
   the full suite unverified on HEAD. `ci.yml:31` has `workflow_dispatch` and
   `:143` runs `check` on every event but `schedule` - dispatch is the close, and
   this is NOT the RM-157 ban (that bans DUPLICATING a push run; none existed).

IDS. RM-344..RM-363 assigned to the 20 rows in `docs/_research_refill_2026-09-05.md`,
re-derived from the tree (max live = RM-343), NOT minted from the tracker on faith.
Both pointers now RM-364 (`docs/DS_SWEEP_TRACKER.md` + `ROADMAP.md`), in one commit.

DO NOT REDO. RM-250 stays closed. RM-343 stays open and is NOT closed by
re-materializing 1884 files in a branch. MC is HTTPS on `:8895` - an http probe
returns 000 and reads like a dead process. RC needs no bounce for loop-route
changes (`dashboard/_errors.py:6`).
