# Orchestration Plan - relocated findings

> Append-only archive of `docs/ORCHESTRATION_PLAN.md` findings sections, relocated
> so the plan's newest `| R<n> |` row stays inside the 16000-byte tail window the
> loop director actually reads (`PLAN_CTX_CAP` 24000 minus `PLAN_CTX_HEAD` 8000).
> Nothing here is edited on relocation - the blocks are moved verbatim.

---

## R205 findings - 2026-07-27 - the nightly-CI loop-infra red, and what it taught

**Directive premise was stale for the fourth cycle running.** All four ordered tasks
(winmutex inbox APPLY, the UNSERIALIZED bump, the `SHARED_SHA256` pin, item 2's POSIX
exec bit, item 5's skip audit) were already on disk and were verified there by digest
and file:line before any code was written. Recording it here because the pattern now
has a measured cause - see the carry-forward at the bottom.

### The finding the directive was aiming at but mis-diagnosed

Push CI has been green on every commit. The SCHEDULED nightly (`30261946219`) was red:
`5 failed, 23474 passed, 254 skipped`. One property explains all five: **they assert
against the Legion working tree**, so they pass on this box and can only fail on a fresh
POSIX clone. A suite that is green where it runs and red where it does not is not a
flake - it is a test that encoded the developer's machine as a fact.

| # | Test | Class | Real defect? |
|---|------|-------|--------------|
| 1 | `test_mutex_serializes_two_threads` | asserts a Win32-only capability | no - test-side |
| 2 | `test_overflow_is_repaid_out_of_the_plan_slice` | depends on ambient repo size | yes, transitively |
| 3 | `test_operator_brief_is_labelled...` | reads a config that never loaded | **yes** |
| 4 | `test_sdk_timeout_kills_the_tree...` | POSIX teardown never worked | **yes** |
| 5 | `test_gate_is_active_in_this_repo` | asserts operator-local git config | no - test-side |

### Three lessons worth reusing

**1. A skip for an absent capability should trigger an audit of its siblings.** Fixing
(1) meant justifying a `skipif`, and that audit found
`test_mutex_is_reentrant_for_the_same_thread` carrying the identical defect in the
opposite direction: the POSIX no-op nests happily, so it went GREEN on every Linux run
while proving nothing. **A red eventually gets fixed; a vacuous pass never surfaces.**
Where one test asserts an absent primitive, look for the sibling that trivially succeeds
against the same absence.

**2. A skip must not silently delete coverage - check what it was carrying.** Both
existing POSIX no-op tests are single-threaded and only inspect the log, so
"never claims ACQUIRED" was pinned and "never serializes" - the substantive half, and
exactly what the new skips stop covering on Linux - was pinned by nobody.

**3. Static provability can be the whole protection.** Slice C was REFUTED for moving
`creationflags` behind `**kwargs`. Runtime Windows behavior stayed correct, but
`tests/test_no_console_flash_scheduled_tools.py` resolves it BY AST and went blind to
the loop's only spawn site (18 passed -> 2 failed). For a defect whose only symptom is a
flicker on the operator's desktop, nobody is watching at runtime - the static proof IS
the guard. **The fix restored the literal; the guard file was not edited.** Teaching a
guard to trust an indirection defeats it for every future call site.

### Defect-class sweep: the hardcoded repo root

`loop_controller.py`'s absolute config literal turned out to be one of three. Full
disposition of every module-level drive-letter constant under `ops/loop/`:

| Module | Constant | Disposition |
|---|---|---|
| `loop_controller.py` | config default | FIXED (slice B) - module-relative + `is_absolute()` guard |
| `done_sentinel.py:15` | `ROOT` | FIXED - no override and no fallback, strictly worse |
| `claude_stub.py:20` | `ROOT` | FIXED - worst case: a dry-run stub that only runs on Legion cannot prove the plumbing anywhere it is in doubt |
| `adjudicator.py:25` | `DEFAULT_CLAUDE_CMD` | **OUT OF SCOPE, with reason** - an external TOOL path with no repo-relative answer, already overridable at `adjudicator.py:188`. Widening the guard to cover it would force a fake fix. |

Guarded by `tests/test_loop_module_root_resolution.py`, written RED first (5 failed / 6
passed). The guard asserts its own REACH as well as its rule, because a scan that
silently matches nothing is this shape's real failure mode.

### CARRY-FORWARD - five cycles old, and this cycle made it worse

Controller pid 18300 started `2026-07-27 00:37:50`. `ops/loop/loop_controller.py` now
has mtime `08:20:22` - **this cycle edited the very module the running image cannot
reload.** Re-verified live, not carried forward on recollection.

It is structurally un-actionable by an executor cycle: bouncing the controller mid-cycle
abandons the `claude.done` handshake it is blocked on, and R202's self-reload guard is
itself inside the code the stale image cannot load. **The fix for stale code is in the
stale code.** One external bounce breaks the loop; no cycle can supply it. This is the
most likely cause of the four-cycle run of stale directive premises.

## R206 findings - 2026-07-27 - the guard recorded its correction where the guilty party never looks

**Two of the directive's four steps were no-ops and measuring that was the first
deliverable.** Fifth consecutive cycle with a stale premise. STEP 1 wanted a staged
`.githooks` exec-bit commit: `git diff --cached` empty, tree clean, `.githooks/*`
already `100755` in the index since `19b680cc`. STEP 4 wanted the TEST-NOT-TRANSCRIPT
rule made durable: it is at `ops/loop/director_prompt.md:147-153` and already pinned by
`test_prompt_carries_the_test_not_transcript_rule`.

### Item 7 was in three pieces, not two

| Piece | State on arrival |
|---|---|
| executor-side parser + serialize override | shipped long before tonight |
| director-side normative contract (what shape the parser reads) | shipped R204 `7f89cd6c` |
| **the REPORTING half** | **shipped here** |

Both guards correct a bad directive, log to `control/controller.log`, and prepend
`_REPORT_IT` (`executor.py:271`): "State this deviation in your summary line."

That ask was the whole reporting mechanism, and **controller.log is not a director
input**. `loop_controller.py:1047` takes `done = rec.raw`; `:577` dumps it forward as
`=== LAST claude.done ===`. `rec.raw` is the MODEL-authored payload. So whether the
director learned its own directive was wrong depended on the model volunteering it in
prose - and a model that silently complies teaches it nothing. That is verbatim the
failure `executor.py:96-100` says recording exists to prevent, one layer up.

`stamp_deviations()` now prefixes it mechanically. The model is asked for nothing.

### Two holes at the merge gate, both on the branch the seam is read on

Neither was in the build agent's claim set. Both proven by mutation before landing.

| Hole | Why it hid | Mutation that kills the new test |
|---|---|---|
| ahk write-back was unconditional | every test fixture supplied a `summary` key; the REAL producer `done_sentinel.py:45` writes none, so every LIVE cycle took the untested branch and gained `"summary": ""` on every CLEAN cycle | reverting the guard injects exactly `'summary': ''` into raw |
| 4 sdk failure paths stamped the record but left `raw` empty | the controller reads `rec.raw` and nothing else, so a cycle that deviated and then DIED carried the correction nowhere - the branch with no model prose at all | dropping `deviation_only_raw()` raises `KeyError: 'summary'` |

**The lesson is the first row.** The fixture was shaped to the feature, not to the
producer. Checking what `done_sentinel.py` actually writes - rather than what the tests
hand the channel - is what found it.

### Defect-class sweep: machinery that asks a model to report machinery's own action

`grep -rn "your summary line\|State this\|say which" --include=*.py ops/loop/` returns 3
hits, all in `executor.py`. Fixable population is a measured 1.

| Site | Disposition |
|---|---|
| `:271` `_REPORT_IT` (reached from BOTH guards) | **FIXED** - mechanical stamp |
| `:348` "run that one FIRST and say which" | OUT OF SCOPE - asks WHICH slice is the prerequisite, which the executor cannot compute |
| `:527` "pick the next NON-duplicate unit and say which" | OUT OF SCOPE - same reason |

No other module in the repo asks a model to self-report machinery's own action.

### CARRY-FORWARD - six cycles old, unchanged

The running controller predates its own self-reload fix (`d4b1a762`). It **must be
bounced by hand once**; no executor cycle can supply it, and it remains the measured
cause of the stale-premise run above.

## R207 - the exemption covered the future, not just the past (2026-07-27, `829700e1`)

`tests/test_smart_quote_hygiene.py` carried a blanket exemption for
`agents/agent6_auditor/reports/`, justified as "immutable dated artifacts - em-dash
drift inside them is operator-gated cleanup, not authored-source drift."

That justification is sound about history and silently wrong about the future. A
path-prefix exemption written to protect files that already exist also protects every
file that will ever exist at that prefix. This directory is not a closed archive - a
cloud scheduled routine appends to it weekly and commits straight to main. The
exemption therefore did not grandfather 4 old files; it permanently blinded CI to a
live write path.

Three reports landed carrying 58 non-ASCII bytes over the week before an audit caught
them by eye. Every automated gate on this repo was in place and none could fire:
PreToolUse hooks do not see a cloud routine's commits, git hooks on Legion do not
either, and the one gate that runs on the routine's own push had been told to skip
that path.

**The generalizable shape:** an exemption keyed on WHERE a file lives is a claim about
the file's PRODUCER, and producers change. `data/daemon_slayer/` is genuinely external
data with a stable producer, so its exemption is fine. A reports directory written by
an agent whose prompt nobody in the repo controls is not the same thing, and reusing
the same mechanism for both made them look identical in the code.

Worth checking the other prefix exemptions in `_is_external_data` against the same
question: is this prefix closed, or does something still write to it?

**Unreachable half, logged:** the routine's prompt lives in cloud scheduling config.
An executor cycle cannot read or edit it (`CronList` is session-scoped to jobs made
via `CronCreate` in-session). The durable in-repo move is exactly what shipped - let
CI go red on the next bad write instead of passing in silence - with the failure
message naming the prompt as the real fix site so the next reader is not left
guessing.

---

## R216 findings - 2026-07-28 - the override looked for drift in the wrong place

The directive came wrapped in a STALE-GROUNDING executor override: re-read ROADMAP.md
before trusting the from-digest premise that RM-121 item 3 sub-item 4 is NEXT. I did.
**The premise was TRUE** - `ROADMAP.md:42` said it verbatim.

**The stale artifact was not the digest. It was ROADMAP.md.**

The override is built on the assumption that a digest drifts away from the tree, so it
asks exactly one question: does the file still say what the digest claims? It has no
question for the case where the file agrees and both are wrong. Two sources agreeing is
one premise, not two.

The cheapest possible check closed it: **run the thing the row says is broken, before
fixing it.** `pytest tests/ agents/daemon_slayer/tests/ -n 8 --dist loadfile` -
23849 passed, 0 failed, 132s. Five of the six failures died in `cd0f115d` three hours
AFTER the desktop note that seeded the row was written; the sixth went with the RM-100
asyncio consolidation. The row was obsolete before it was ever scheduled.

### The unit that was actually available

`cd0f115d`'s own commit body:

> Swept every other subTest call site in both suites: the remaining ones pass only
> primitives and need no change, but any future hostile-input matrix is one
> non-primitive away from the same `-n`-only failure.

That diagnoses the residual risk correctly and then answers it with prose - across 463
call sites in 100 files, in a defect class **a serial run cannot observe by
construction** (no execnet channel serially, so the failure does not exist to be seen).
An eye-sweep is the weakest available instrument for a defect whose defining property is
invisibility in the default run.

Shipped: a repo-root `conftest.py` that validates every `subTest` kwarg against
execnet's OWN `dumps` at call time. Repo-root because `tests/conftest.py` cannot reach
`agents/daemon_slayer/tests/`, which has no conftest and held one of the five instances.

### Enumeration, mechanized rather than asserted

The guard IS the probe. Installed, full dual suite re-run: **23861 passed, 0 failed** -
exactly +12 tests / +17 subtests over baseline, which is the new file to the unit, so
**0 additional instances repo-wide**. Disposition: 5 FIXED (`cd0f115d`), 458 CLEAN and
now machine-proven instead of eye-proven, 0 OUT-OF-SCOPE. `cd0f115d`'s sweep was
CORRECT; the value delivered is that it is no longer a claim.

### Two things the build turned up that the directive did not ask for

- `tests/test_aram_action_rule.py` asserted in a docstring that `object()` "(or a
  `set()`)" raises `DumpError`. Probed directly: **sets and frozensets serialize fine**;
  the containers recurse, so `[object()]` fails and `{1, 2}` does not. Never
  load-bearing - no test passed a set - but exactly the remembered-not-measured detail
  that sends the next reader rewriting working code. The grammar is now pinned by a test
  instead of restated in a docstring. **If a fact matters enough to write down twice,
  assert it.**
- **Reach limit, recorded not papered over:** a rootdir conftest only loads when pytest
  runs from the repo root, so a DS-dir invocation bypasses the guard. NOT closed with a
  second conftest under `agents/daemon_slayer/tests/` - that path mirrors into
  `Share/src/`, and `Share/` runs standalone (RM-112) where `tests._subtest_channel_guard`
  does not exist, so the mirror would import a missing module and break a clean package.
  Already fenced by an unrelated rule (DS-dir runs produce 13 CWD failures). Written into
  the module docstring so nobody "fixes" it into a Share breakage.

### Carry-forward

Unchanged from LEDGER 1092 and still unclaimed: the **16-instance
whole-file-rewrite-under-a-narrowed-work-plan class**, with a live DS-consumer blast
radius. Schedule it before someone runs a narrowed regen by hand.

`ROADMAP.md` is at 91 percent of its 81920-byte doc budget and was ALREADY breaching at
HEAD (73178 bytes) - reported, not silenced. This session's ROADMAP edit was compressed
and the detail carried in LEDGER 1093, which is where CLAUDE.md says it belongs.

### The docs-guards red this cycle caused, and why it is structural

Pushing R216's row turned `docs-guards` RED on
`test_real_orchestration_plan_newest_row_survives`. Not a flake and not the test
being wrong - a real regression, caught exactly where it should be.

The director reads this file through
`cap_bytes_head_tail(..., PLAN_CTX_CAP=24000, PLAN_CTX_HEAD=8000)`, so it sees the
first 8000 bytes and the LAST 16000. R216's row landed **16087 bytes from EOF - it
missed the window by 87 bytes.**

The mechanism is arithmetic, not bad luck. Every cycle appends a row in the middle
and a findings block at the END, so the newest row is pushed roughly one
findings-block further from EOF each time while barely moving itself. R215 sat at
about 13500; R216 at 16087; R217 would have been near 20000. **It was going to fail
every cycle from here, and it happened to break on the cycle whose whole subject is
gates that fire late.**

Fixed by relocating R205 / R206 / R207 findings to
`docs/ORCHESTRATION_PLAN_HISTORY.md` (verbatim, nothing edited), which puts the
newest row at 6632 from EOF. **The correct lever is relocating old findings - never
shrinking the new row and never relaxing the guard.** Budget two to three cycles per
relocation. `tools/md_guard_selector.py` reproduces the CI job locally; note its
output is CRLF, so pipe through `tr -d '\r'` before `xargs`.

---

## R217 findings - 2026-07-28 - the notes were half already-done, and the trap was a header

**The override fired correctly and the premise held.** Cycles 13 through 19 kept
ordering units that were already on disk; this one did not. `ROADMAP.md:42` carries
the sentence the digest attributed to it, word for word, and both desktop sources
exist. The re-read still earned its keep - it is one Read, and it is the only thing
standing between a stale digest and a wasted cycle.

### The deliverable was the QA, not the extraction

RM-121's own row warns that "a row marked STILL OPEN without a cited empty search
manufactures work that is already done", and these two notes proved it: **5 of 11
claims were dead on arrival.** The `wakeup_prune` claim is the sharpest example - the
note says 12 sessions are invisible, `--check` wrongly reports compliant, and the
file has bloated to 61KB. Measured: `--check` exits 0, `WAKEUP_NOTES.md` is 10759
bytes, and it holds exactly three session headings, which is the keep-3 prune having
visibly run. `2f35163d` fixed SESSION_RE by giving it a `\d{4}-\d{2}-\d{2}`
alternative. Same shape for the `GRADE_LABEL` em-dashes (already spaced hyphens) and
the `data/ratings/*.json` backfill queued behind them - 0 of 4 files carry a dash to
backfill, so that unit was never work at all. **A note is a snapshot of a moment, and
an operator note is no more current than an audit digest.** Every line of one gets
the same re-probe an inherited premise gets.

### The trap was a header, and it was one line above the work

`random.txt`'s second half opens "UI/UX pass - session 2 (operator-present; continues
2026-07-22b). Do NOT run headless." Directly beneath it sits a well-specified 6-item
queue with named files, a priority order and a read-first list - which is exactly the
shape a headless executor is built to consume. **The disqualifying instruction was
the header, not the content, and nothing in the content repeats it.** It is filed as
an operator-present lane with the prohibition restated inside the row, so the next
director reads the fence rather than the queue.

### What was chunked out rather than built

The directive scoped this cycle to docs, roadmap and backlog. Two code units fell
out and are filed as OPEN rows on disjoint file sets: R217-U1 (`ci.yml`, the RM-119
RC-half promotion the operator has explicitly authorized, with its measured 19m42s
runner price) and R217-U2 (`tools/extract_panels.py` + `tools/rc_facts.py`, with
`tools/p3_ascii_sweep.py` carved out by the operator's own exemption). Both carry
their acceptance criteria and their traps in the row, so neither needs the notes
re-read to execute.

### Carry-forward

The RM-119 ROADMAP row was measurably stale in one clause - it still says ZERO DS
test files are collected on push, and `ci.yml:322` has run the DS suite in the
`check:` job since. Corrected this cycle. Worth noticing that the stale clause and
the note asking for the follow-on work were both written by people who were right at
the time; the row aged, the note did not know it had.

---

## R217-U1 findings - 2026-07-28 - the directive named three edits, and the fourth one was the defect

**The premise held and the unit was real.** `check:` (job at `ci.yml:108`) ran
`pytest agents/daemon_slayer/tests/` and nothing else, and `pip install -r
requirements.txt` existed only inside `nightly-full-suite:`. Both were re-read on disk
before any edit, and both were exactly as R217 filed them. Two real cycles in a row.

### The defect the directive did not name was the timeout, and it would have failed the first push

The row carried `timeout-minutes: 25` forward from the DS-only promotion with the note
"no raise needed, but under 6 minutes of slack". That arithmetic only works if the
19m42s dispatch price were the whole job. It is not: the dispatch run measures pytest
inside a job that does nothing else, while `check:` also installs, caches and installs
Playwright, sweeps py_compile over the tree, runs ruff, re-derives the Share mirror,
and runs four named-file guard steps - the DS-only shape of this job measured **9m1s
end to end** (run `30342574878`) against a DS pytest step of about 2m47s. Same
subtraction on the new shape prices the job at **about 26 minutes**, which is OVER the
ceiling, and GitHub reports a blown ceiling as **cancelled**, not failed - the exact
misread that cost a cycle on 2026-07-27. Raised to 40. Not to 27: a ceiling one minute
above the estimate converts ordinary runner variance into a fake red, and a timeout
here exists to catch a HANG, not to police minutes.

### The remaining named-file pytest steps were enumerated, and none of the four is redundant

The directive said to drop the two that become pure subsets and keep the two
special-env steps. Enumerated the rest rather than assuming that was the whole list.
Four named-file steps survive. `RC_REQUIRE_HOOK_GATE` and
`RC_REQUIRE_BUILD_ORDER_TABLES` turn a skip into a failure, so the full run cannot
replace them - the promoted `pytest tests/` collects those same files and they skip.
The hygiene trio and the docs-guard step ARE strict subsets, and they stay anyway,
because a 20-minute suite that reports an ASCII break in minute 20 is worse than a
10-second step that reports it in minute 1. **That rationale is now written IN
`ci.yml`**, because the next reader will otherwise delete them as duplicates and be
right by every argument except the one that matters.

### The install line is what makes the promotion mean anything

`pip install -r requirements.txt` is not bookkeeping. The RC tree imports anthropic /
PIL / websockets / portalocker / psutil, and an ImportError-guarded test that cannot
import is a **skip**, which is a green tick - so promoting the suite without the
runtime stack would have bought a longer job and almost no new assertions. The two
ad-hoc pins that requirements.txt already carries (`json5==0.14.0`, `pydantic>=2.0`)
were dropped so a version lives in one place; `pyyaml` stays pinned in the workflow
because it is test-only and `tests/test_ci_docs_guard_coverage.py::
test_ci_installs_the_yaml_parser_it_needs` asserts the literal `pip install ... pyyaml`
in any workflow that names that module.

### Carry-forward

RM-119 is CLOSED, both halves, and its narrative was relocated to
`docs/ROADMAP_HISTORY.md` in the same pass - `ROADMAP.md` had **1569 bytes** of headroom
against its 81920 budget, so this row could not have been updated in place. The skip
audit's B2 / B4 / B5 classes stay in `ROADMAP.md`: they are open work, not shipped
narrative. **The real acceptance is the runner, not this file** - a green local suite
proves the command, and only the push proves the price. It was paid and it was
CHEAPER than the estimate: run `30345614564` green, 23703 passed / 254 skipped /
6165 subtests / 0 failed, 19m10s of pytest inside a 20m54s job. The number that
matters more than the minutes: this job passes 96 MORE tests than the nightly
dispatch (23607), because it installs pyyaml and arms the git hooks before it runs,
so fewer guards degrade to skips. Push CI is now strictly stronger than the nightly.
