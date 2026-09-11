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
already `100755` in the index since `04a5a534`. STEP 4 wanted the TEST-NOT-TRANSCRIPT
rule made durable: it is at `ops/loop/director_prompt.md:147-153` and already pinned by
`test_prompt_carries_the_test_not_transcript_rule`.

### Item 7 was in three pieces, not two

| Piece | State on arrival |
|---|---|
| executor-side parser + serialize override | shipped long before tonight |
| director-side normative contract (what shape the parser reads) | shipped R204 `a7a957a0` |
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

The running controller predates its own self-reload fix (`35df5e5c`). It **must be
bounced by hand once**; no executor cycle can supply it, and it remains the measured
cause of the stale-premise run above.

## R207 - the exemption covered the future, not just the past (2026-07-27, `058f5b5b`)

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
23849 passed, 0 failed, 132s. Five of the six failures died in `462f1255` three hours
AFTER the desktop note that seeded the row was written; the sixth went with the RM-100
asyncio consolidation. The row was obsolete before it was ever scheduled.

### The unit that was actually available

`462f1255`'s own commit body:

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
**0 additional instances repo-wide**. Disposition: 5 FIXED (`462f1255`), 458 CLEAN and
now machine-proven instead of eye-proven, 0 OUT-OF-SCOPE. `462f1255`'s sweep was
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
visibly run. `4a707962` fixed SESSION_RE by giving it a `\d{4}-\d{2}-\d{2}`
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

## R217-U2 findings - 2026-07-28 - the two glyphs the directive did not flag were the load-bearing ones

**Both premises were re-read on disk and both held.** `docs/ORCHESTRATION_PLAN.md`
carried R217-U2 as OPEN, and `tools/p3_ascii_sweep.py` really does hold 167
non-ASCII bytes with its exemption rationale written into the row itself. The
byte counts matched the filed figures exactly - 189 of 11094 and 10 of 10139 -
which is worth saying out loud after seven no-op cycles: a from-digest premise
is not automatically stale, it is just unverified.

### The parallel block was refused, and the override header refused it for the wrong reason

The directive dispatched AGENT 1 on `tools/extract_panels.py` and AGENT 2 on
`tools/rc_facts.py`. The executor-override header claims those two file sets
COLLIDE because "AGENT 1 and AGENT 2 both name extract_panels.py". They do not -
the block names one distinct file per agent and the sets are disjoint. **The
collision detector misfired**, and a false collision report is worse than no
report, because the next reader learns to discount it. The shape was refused
anyway on the real ground: two mechanical file edits plus one guard test is
under the R9 subagent floor, so worktree isolation would have cost more than the
edit. Ran inline, sole author.

### The hazard the directive did not name

The `U+25B6` and `U+2022` bytes in `extract_panels.py` are not decoration - they
sit inside `.replace()` MATCH patterns at `:158-162`. That is the same
load-bearing-data class that makes `p3_ascii_sweep.py` exempt, and it is the
reason a blind sweep of this file is not obviously safe. Resolved by checking
the tree instead of reasoning about it:

- `web/js/panels/champ_select.js:195` already reads `"> "` and `:200` already
  reads `"  *  "`. The repo-wide retro-purge swept the JS half; the extractor's
  glyph patterns had already stopped matching the shipped output.
- The extractor's own input is gone in the shape it addresses. `SRC =
  web/js/main.js` is **7565 lines** today, and every `L(start, end)` range in
  the tool slices the **6223-line pre-split** file. Re-running it would not
  re-extract anything; it would destroy `main.js`.

So the patterns match nothing on disk in either form, the file is a spent
one-shot, and the sweep is cosmetic - but the ASCII forms now at least agree
with what the tree actually holds rather than preserving a dead pre-purge
pattern. **This is why the file was worth reading before sweeping it**, and why
the p3 exemption is a class rather than a one-off.

### The guard cannot import the file it guards

`tools/extract_panels.py` opens and rewrites `web/js/main.js` at MODULE SCOPE.
Any test that imports it destroys the file. `tests/test_tools_ascii_hygiene.py`
parses it with `ast` and pulls `PANEL_IMPORTS` out of the tree, then compares
the emitted rule against the real `// -- Panel modules` line in `main.js` on
disk and asserts equal WIDTH - which is what proves the substitution was 1:1
rather than a re-flow. Reading the contract off disk beats pinning a literal.

### The exemption is now pinned in the direction that can actually break

`test_p3_ascii_sweep_exemption_is_intact` asserts the sweeper still HAS
non-ASCII bytes. A guard that only bans glyphs would let the next well-meaning
sweep disarm the tool and stay green. The plan row asked for the carve-out to be
explicit rather than discovered by regression; a test is the only form of that
which survives the next agent who has not read this file.

### Scope, kept narrow on purpose

This is a per-file pin, not a repo-wide ASCII ban, and the docstring says so.
`U+2500` is not a banned codepoint here - `web/js/main.js` alone carries **1310**
of them, and `tests/test_u2500_hygiene.py` has made the same scope note since
item 176. Extend the pin only alongside an actual sweep.

`tools/rc_facts.py` is LIVE - a `SessionStart` hook in `.claude/settings.json` -
so its strings are user-visible text, not comments. Re-ran it after the sweep:
the probe is unchanged and the output is ASCII.

### Verification

TDD RED first: 3 failed / 2 passed on the new guard before the edit (both byte
counts, plus the emitted-rule width). After: py_compile + ruff clean, the
hygiene set (new guard + mojibake + smart-quote + u2500 + rc_facts port probe)
**24 passed**, and the full RC suite **13766 passed / 106 skipped / 477 subtests
/ 0 failed** in 104.97s at `-n 8`. DS suite not run and not needed:
ENGINE-IMPACT NONE, no path under `agents/daemon_slayer/` touched, no
ENGINE_VERSION, no Share mirror, no restart.

## R219 findings - 2026-07-28 - the directive's data source does not contain the data

### The Meraki premise, measured

The directive ordered a champion-base-stat sweep "vs Meraki bulk truth". The local
Meraki mirror cannot answer that question, and the reason is structural rather than
stale. `data/daemon_slayer/16.14.1/items_meraki.json` holds 320 entries under an
`items` key, and a key census across all 320 returns exactly ten field names:
`name`, `id`, `tier`, `rank`, `removed`, `simpleDescription`, `passives`, `active`,
`shop`, `noEffects`. There is no `stats` block on any entry and there is no champion
half of the file at all. The mirror was fetched with an effects-shaped projection,
which is correct for what DS uses it for - the standing memory is that a Meraki
clause lives in the effects PROSE field - but it means an offline stat comparison
has no Meraki side.

A first pass at a prose-based substitute produced 178 apparent hits for items whose
description mentions Move Speed while DDragon reports no movespeed stat. That number
is an artifact: the regex was matching inside the `str()` repr of the `passives`
structure, so `Doran's Shield` and `Recurve Bow` scored. It is recorded here so the
next cycle does not rediscover it as a finding. Prose is a source for CLAUSES, not
for a stat census.

The consequence for Section 8: a champion-stat sweep against Meraki needs a mirror
refresh that requests the champion endpoint and the full stat projection. That is a
data-plumbing slice, not a math slice, and it was not in this cycle's two-file grant.

### Two slices, one shipped guard each, and neither needed a behavior change

Both slices went looking for a wrong number and both found the population already
correct. That is a real outcome, not a no-op, because in both cases the correctness
was undefended. Slice A's override set covers exactly the 5 of 9 DDragon-zeroed
champions that need covering, and the other 4 classify correctly on their own - but
nothing on disk said so, and the module exists because a champion silently
mis-classifying is a shipped user-visible bug. Slice B's `_FALLBACK_MS` is a
defensible value, but the sentence justifying it was factually false against the
mirror it describes.

The pattern worth carrying forward: when a sweep finds the data already right, the
deliverable is the guard that makes the next drift loud, and the guard is only worth
shipping if its teeth are demonstrated. Both slices did that by injection rather than
by assertion - Slice A fabricates a zeroed champion and watches the universe grow,
Slice B swaps the fallback for a `-1.0` sentinel so that the 28 champions whose real
movespeed happens to BE 345 cannot mask a fallthrough. Without that sentinel the
coverage test would have passed while measuring nothing.

### The orchestrator's own brief carried the defect, and only the tree-level gate saw it

Slice A shipped with a `skipTest` on an absent DDragon mirror, because the brief I
wrote told it to - "it is a data mirror, not source". That reasoning is wrong, and
the repo already knows it is wrong: `data/meta/ddragon_champions.json` is tracked, so
a checkout always has it, and an absent one is a broken tree rather than an absent
capability. `tests/test_skip_condition_hygiene.py` failed it as a B5 masking skip,
the class the RM-119 skip audit catalogued as "reports green by not running". A
completeness guard that skips when its own data disappears is the worst possible
shape for this particular test, since a vanished mirror is one of the two ways the
thing it guards can break.

Both the slice agent and its verifier passed it. They were scoped to the slice, and
in isolation the two files run 100 passed. The tree-level guard is the only thing in
the chain that could have seen it, which is the argument for running the full suite
even when the tier rules say a two-file `core/` change does not need one. Recorded
here as an orchestrator error, not an agent error.

### The tie rule, and why it was pinned rather than fixed

Three consumers merge the same curated info block and then disagree about what a tie
means. `dashboard/routes_dictionary.py:101` answers `attack >= magic` and so returns
a confident "AD" when it has no signal at all; `dashboard/routes_pickban.py:255-260`
returns "EVEN"; `core/build_planner/fed_threat.py:147-151` returns "". The `>=` site
is the same shape as the original defect - Seraphine rendered "AD SUPPORT" out of a
0 versus 0 comparison - and it is one unpinned newcomer away from doing it again.

It was not fixed here because it is outside the two-file grant and because the right
answer is a product call: whether the champ-select chip should be allowed to show a
neutral state. The guard demands strict polarity, which is the intersection where all
three agree, so it holds the line without choosing. Filed in the row, not deferred to
memory.

### The constant that was found by sweeping for the constant

The defect class was defined narrowly on purpose: a hardcoded constant in live code
whose attached comment makes a checkable factual claim about data on disk. That
definition is what let the sweep score itself honestly - 62 candidates, 2 confirmed
by opening the file and checking, 3 refuted by checking, ~55 outside the class as
tuning judgments, and 1 recorded UNRESOLVED because the extraction did not match the
registry's shape. The unresolved one is not counted as a find.

The second confirmed instance is worth more than the assigned one.
`agents/daemon_slayer/burst.py:124-127` claims no champion sits between melee and
ranged attack range and picks 350 on that basis; eight do, Urgot sits exactly on the
strict-greater-than boundary, and the DS engine already has a canonical split at 250
in `ehp.py:254` that `rank.py` documents as authoritative. Two thresholds for one
concept, disagreeing on three champions, in a live rune-scaling branch. Filed as
RM-123 with ENGINE-IMPACT BUMP, because reconciling it moves numbers and belongs in
its own Tier-2 slice with a re-baseline, not in a `core/` docs cycle.

## R220 findings - 2026-07-28 - the category was thin, and the best finding was ours

### Rotating the target is not dodging the directive

The directive named Overlay App F or Aggregator B. Three places on disk say do not. RM-01 in
`ROADMAP.md` retires the whole rotation by name and tells the director what to do
instead; the R100 block and the 2026-07-16 block in the competitor index both
declare the live-overlay family drained, the second one counting five passes; and
Overlay App F has two completed teardowns sitting in `docs/_archive/`. Re-running it
would have produced a third document agreeing with the first two, which is the
failure mode the drain notes exist to prevent.

The rotation was chosen by search, not by preference. Six keyword probes across
every prior `COMPETITOR_LIFT_*.md` returned zero hits for wave management, wave
simulators, CS trainers, minion waves, freezing and slow pushing. That is a real
empty result over the actual corpus, so the lane / wave / minion-economy category
is the one thing in this space nobody here has looked at.

### The category is thin and I am recording that rather than padding it

There is no standalone wave-simulator product. Six distinct search angles returned
SEO guide articles, unrelated combat simulators, and two calculators. Three targets
were torn down properly instead of eight skimmed. If a later cycle is tempted to
re-enter this category expecting depth, the honest expectation is two findings and
two useful negatives, which is what it produced.

The two negatives are worth as much as the findings. A live wave STATE machine -
telling freeze from slow-push from fast-push - is data-blocked three independent
ways: `:2999` exposes no minion entities, the Overlay Platform M GEP contract that bounds
every competitor in this category gives minion KILL COUNTS only, and Match-V5 has
no minion event type at all, so nothing wave-shaped is backfillable from the 2966
stored matches. That also refutes the category's own marketing: a product running
inside that contract cannot be observing wave state, so its "wave state" is a
clock, a CS-rate inference, or prose. RC can compute the deterministic subset
honestly, which is F1.

### The enabling fact had been sitting in a comment

`dashboard/_state_cooldowns.py:18` lists `MinionsSpawning` among the events the
Live Client actually emits, and two lines later the module passes an empty event
list downstream because it wanted summoner-spell events that do not exist. A
repo-wide grep for `MinionsSpawning` returns that comment and nothing else. So the
one anchor a wave clock needs has been documented in this repo, unread, for as
long as that comment has existed. `dashboard/_liveclient.py` already extracts
three other event classes out of the same top-level block, which means the
transport is built and the missing piece is a fourth extract in the same shape.

That is why F1 is NOW rather than FUTURE, and it is also the answer to the finding's
only real risk. Three prose sources disagree on when the first wave spawns (0:30,
1:05, 1:30) and on where the cannon cadence breaks (14:00, 15:00), and a 2025
change moved first-cannon arrival from 2:05 to 2:35. A hardcoded spawn constant
would have been wrong by construction. Anchoring on the live event's own
`EventTime` makes the disagreement irrelevant for the anchor and confines it to the
cadence table, which one real game validates.

### The best finding was not a lift

The HAVE column was supposed to be bookkeeping. It found that RC renders a wave
feature nobody built. `web/js/panels/next.js:16-83` is a finished 3-lane readout
with a documented band table, per-lane colouring and the player's own lane marked,
reading `wave_top` / `wave_mid` / `wave_bot`. The only writers of those keys in the
entire repo are test fixtures in `scripts/rebuild_sim_fixtures.py`. In a live game
it renders the no-data sentinel on all three lines and always has.

It is not alone. `wave_state_now`, `wave_control`, `wave_freezes` and
`cannon_cs_summary` are labelled STATS rows wired from `core/match_metrics.py`
through `right_now.js` with zero producers, `gd_at_15` is the same shape, and the
ARAM wave tier-shift rule in `core/aram_action_rule.py:36-39` is dead because the
live call site passes `wave_pct=None` with a comment saying so. Six identifiers
that read as shipped in any grep and are inert in production.

The lesson generalises past waves: a rendered surface with a plausible name is not
evidence of a producer, and the fixtures that make it look alive in tests are
exactly what hides that. The cheap check is to grep for writers outside
`scripts/` and `tests/` before believing any panel field exists.

### One thing this finding will not do

`tools/hz_shadow_report.py:196-201` excludes crash, freeze, push, split and roam
from the laning agreement sample as non-laning macro actions. So a wave clock will
not move the Lane A agreement number, and the RM-124 row says so explicitly. It was
worth writing down because the adjacency is tempting and wrong: the wave work is
its own capability, not a fix for the laning gate.

## R221 findings - 2026-07-28 - both backend slices shipped, panel wiring still deferred

**SHIPPED (commit 7121ca85):** the 4th Live Client event extract. `MinionsSpawning`
now reaches `liveclient_summary` as `minion_spawn_events` -> `[{"spawn_at_s": float,
"event_id": int | None}]` (`dashboard/_liveclient.py:387-402`), purely additive, the
3 sibling extracts byte-unchanged, 11 TDD tests including the anti-regression pin
that events nested under `gameData` are NOT read. Verifier CONFIRMED 7/7 claims.

**SLICE 2 ALSO SHIPPED, late in the cycle.** `dashboard/_wave_timing.py` (pure spawn
clock) + `tests/test_wave_timing.py` (42 tests / 801 subtests). Verifier CONFIRMED 9/9.
The clock is fully observational: the interval is the MEDIAN of observed gaps, so one
dropped event leaving a doubled gap is harmless, and `_DEFAULT_WAVE_INTERVAL_S` is
reachable ONLY when no gap is measurable at all. No first-spawn constant exists in the
module - which is the whole point, since three sources disagree on first wave
(0:30 / 1:05 / 1:30).

**A process scar worth keeping.** The orchestrator briefly deleted this slice's files
mid-flight: the agent was still working, the module on disk was a self-labelled TDD RED
stub, and a red `tests/test_wave_timing.py` collected 787 failures - which WOULD have
poisoned the next cycle's baseline had it been committed. Deleting was right for a red
stub and wrong for a live agent's workspace. The agent then reported that `ls`, `Glob`,
and `git status` each showed the file missing while it was on disk; that was partly the
documented stale-tool-result replay and partly the orchestrator genuinely removing it
underneath. Two rules fall out: do not garbage-collect a slice's files until its agent
has REPORTED, and confirm a file's absence with a real probe before acting on it.

**THE SCOPE CORRECTION, which is the load-bearing finding of this cycle.** The R221
directive said to key the compute to `wave_top` / `wave_mid` / `wave_bot`. **Refuse
that.** Those three keys are lane wave-PUSH PERCENTAGES driving the
FREEZE/TRADE/CRASH/DISENGAGE readout at `web/js/panels/next.js:27-47` - they ARE the
live wave STATE machine that this feature's own parent, ROADMAP RM-124, declares
data-blocked three ways (`:2999` exposes no minion entities, Overlay Platform M GEP gives
`minionKills` counts only, Match-V5 has no minion event type). A spawn clock cannot
know where a wave sits in a lane, so emitting those keys from it would be fabrication,
and RC's standing rule is that a wrong precompute is worse than no precompute. Slice 2
computes the TIMING subset ONLY: `wave_number`, `last_spawn_s`, `next_spawn_s`,
`next_spawn_in_s`, `next_is_cannon`, `cannon_every_n_waves` - all honest-None on no
data - and must carry an anti-fabrication test asserting the returned dict holds no
`wave_top`/`wave_mid`/`wave_bot` key.

**Two more directive defects worth teaching back.** (1) The instruction to append the
new row "ABOVE the EXCLUDED section" would have BROKEN the guard the relocation exists
to satisfy: `## EXCLUDED` sits at line ~104 near the HEAD, while
`test_real_orchestration_plan_newest_row_survives` takes `rows[-1]` in FILE order, so
a row placed there can never reach the tail window. The row went after R220's instead.
(2) The serialization override claimed AGENT 1 and AGENT 2 shared files; measured, the
two file sets were genuinely DISJOINT. Serializing anyway cost wall-clock and is what
left slice 2 half-built when the cycle was cut.

**Census - "documented-but-unread LiveClient event" (the defect class).** Emitted names
per `dashboard/_state_cooldowns.py:14-18` plus the published Live Client list, checked
against every name RC actually extracts (`grep -rn '"<Name>"' dashboard/ core/ --include=*.py`,
test files excluded). READ after this cycle (7): `TurretKilled`, `InhibKilled`,
`DragonKill`, `BaronKill`, `HeraldKill`, `ChampionKill`, and now `MinionsSpawning`.
STILL UNREAD (8), all OUT-OF-SCOPE this slice with reasons: `GameStart` (the 3 repo
hits are LCU gameflow PHASE strings at `dashboard/view_router_state.py:102,162,174`,
NOT the Live Client event - the event itself is genuinely unread; low value, RC already
has `gameTime`), `FirstBrick`, `Multikill`, `Ace`, `FirstBlood` (all tempo//morale
signals with no current consumer), `InhibRespawningSoon` / `InhibRespawned` (partially
subsumed - `core.event_callouts` already computes the 300s respawn ETA from
`InhibKilled`, so reading these would be a cross-check, not new information), `GameEnd`
(post-game path is Match-V5 / SGP, not `:2999`). The sibling producer-less RM-124 panel
fields - `wave_state_now` / `wave_control` / `wave_freezes` / `cannon_cs_summary` /
`gd_at_15` - remain OUT-OF-SCOPE and are NOT unblocked by this slice.

**Live-gated: G2-45 filed.** Nobody has ever seen real `MinionsSpawning` bytes. Whether
it REPEATS per wave or fires ONCE at first spawn decides whether slice 2 needs a
gameTime-projection fallback, and the cannon-cadence table is unvalidated by
construction (sources disagree 14:00 vs 15:00; a 2025 change moved first-cannon arrival
2:05 -> 2:35). Do not wire the panel before that row closes.

**Suite noise, diagnosed properly so it is not re-investigated as a regression.** Two
tests failed locally and NEITHER is a regression - CI ran the full suite on 73d7b49e and
went GREEN on all three workflows, which is the fact that settles it. They fail for two
DIFFERENT reasons, and the distinction is the useful part:
- `tests/snapshot_panels/test_overlay_view.py::test_ovx_hidden_suppresses_a_panel` -
  genuine xdist/Playwright contention. Failed under `-n 8` on one run, passed under
  `-n 8` on the next, passes serially. Feeds a hardcoded `"liveclient"` mock dict, so it
  never touches `dashboard/_liveclient.py`.
- `tests/test_loop_gemini_timeout.py::test_gemini_logs_stderr_head_on_empty` - **NOT
  xdist.** It fails SERIALLY on Legion and still passes in CI. The difference is that
  Legion was running the live loop controller during the run - this session IS the loop
  executor - so the test is not isolated from a live controller process touching the same
  module state. Expect this test to fail on Legion any time the loop is running and to be
  green in CI and on a quiet box. Do not "fix" it by chasing the assertion; the test file
  is byte-identical to baseline `3e731064` and this run touched zero files under
  `ops/loop/`.

**A tool-pipe warning, because it cost real time here.** An early serial re-run reported
both tests PASSING; a later identical serial run failed one of them. That is the
stale-tool-result replay CLAUDE.md documents, and the slice-2 agent independently hit the
same thing (`ls` / `Glob` / `git status` all reporting a file missing while it was on
disk). Treat a single green re-run as weak evidence when the pipe has already misbehaved
in a session - CI on a pushed SHA is the ground truth that actually settled this.

## R224 findings - 2026-07-28 - the guard was right about the leak and wrong about the fix shape

RM-126 was filed by R223 with an unusually complete diagnosis, and it held up on
disk without amendment. The interesting part of this cycle is what the filing did
NOT say.

**The obvious fix is the wrong fix.** The row prescribed "attach once per element,
or tear down before re-attaching". Attach-once alone is a trap. `_installDrag`
returns a `begin` closure that `_makeHandle` binds to the `.ovx-handle` child, and
that child is LEGITIMATELY recreated on every repaint - it has to be, the renderer
destroyed it. So an implementation that early-returns before the binds but still
builds and returns a FRESH `begin` looks correct, passes any "listeners bound
once" test, and is broken: the el-level `pointermove`/`pointerup` listeners that
survived from the first call close over the FIRST call's `dragging`/`startX` state,
while the new handle drives a second, unobserved copy. The leak becomes a desync.
The fix stores `begin` on the element and hands back the stored one, so there is
exactly one closure and one listener set for the life of the mount. This was
called out to the build agent up front and re-verified by the verifier as a
gating claim, because it is invisible in a bind-count assertion.

**A population of 1 is still a measured result.** The enumeration covered 19
`addEventListener` sites (17 in `overlay_layout.js`, 2 in `overlay_idle.js`) and
found 4 defective instances, all in one defect class, all in the reported
function pair. Nothing else. The load-bearing negative is `_ensureLauncher`
(sites 674/715/749/750): it is re-entered by the same MutationObserver and by
`resetOverlayLayout`, but it early-returns on
`document.querySelector("#w-launcher")` - it asks whether the HOST still exists,
not whether some CHILD of the host still exists. That single word is the entire
difference between the launcher being immune and `_makeHandle` leaking for
months. The defect class is not "unguarded listener attach", it is **"guarded on
a child's existence when the listener's host is the parent"**, and that is the
shape to grep for next time.

**Two corrections to the directive's own premises, both minor, both worth
recording.** (1) The stale-grounding override at the top of the file was right
that `67e3863c` is already an ancestor of HEAD, but it was reasoning about the
wrong thing: `67e3863c` is the docs-only FILING of RM-126, not its fix, so the
unit was not a duplicate and was executed as written. (2) The directive routed
STEP 4 through "the ui_recon Playwright harness + :8810 static preview". Neither
exists on disk - `ls tools/ | grep -i recon` is empty and `8810` appears in no
tracked `.py` or `.ps1`. Rather than log a skip, the cycle substituted something
strictly stronger for a behaviour fix: node v24.15.0 IS present, `overlay_layout.js`
has ZERO imports and exports `_makeHandle` through `_internals`, so the module
loads under a stubbed DOM and the leak can be MEASURED instead of inferred. That
harness is what produced the 12-vs-4 number above, and it is the reason this
slice did not have to trust its own source-parsing guard.

**The digest pin fired again, as designed.** `_LIVE_HALF_DIGEST` went red on the
one-line-plus-comments edit to a LIVE web source. Re-stamped only after running
the same tokeniser over `f124f67f` and the post-fix tree: 1 of 165 web/ sources
changed its live half, `overlay_layout.js`, which is this slice's whole file set.
Second consecutive cycle where this guard did its job on the first try.

**OWED, carried forward:** the overlay visual PNG. This change alters zero markup
and zero CSS bytes, the ASCII phase is measured clean (0 non-ASCII in all three
touched files) and the HIT-TARGETS question - does drag still actuate - is
answered by the behavioural harness rather than by pixels. STRUCTURE, TYPOGRAPHY
and HIERARCHY are confirm-unchanged by construction. Same standing debt as R223.

**SELF-CORRECTION appended before wrap - the harness probe was wrong.** STEP 1 of
the directive said to prefer a BEHAVIOURAL test if a JS-execution harness exists,
falling back to a source-parsing guard only if none does. The probe grep returned
`tests/snapshot_panels/*.py`; those hits were dismissed as unrelated and they were
not. The repo HAS a node-subprocess harness, used in at least 5 tests
(`tests/test_coach_choices_trigger_render.py`, `tests/snapshot_panels/test_xss_escaping.py`
and siblings), which shell to `node --input-type=module -e` and import a web
module's `_internals`. So the ad-hoc node probe this cycle improvised to measure
the 12-vs-4 number was the repo's own committed idiom, and it belonged in the
suite. Corrected in-run: `tests/test_overlay_drag_listener_leak_behavior.py` pins
the bind count (RED 12 / GREEN 4), the handle's per-pass rebind (green both sides
by design, so an over-broad latch that killed dragging is caught), and that
`_installDrag` returns the SAME `begin` object across passes - the anti-desync
property a bind-count assertion cannot see, measuring `beginIdentical: False` on
the unfixed tree. The source-parsing guard is kept alongside it; it needs no node.

**The carryable lesson is not about this file.** A NEGATIVE harness probe deserves
the same verification as a positive claim. "The grep returned files I did not
recognise" is not "no harness exists", and the error is comfortable to make
precisely because the fallback is cheaper than the thing it replaces.

---

## Relocated 2026-09-11 - everything the plan carried after the R230 findings log

(From `docs/ORCHESTRATION_PLAN.md`, moved VERBATIM and unedited: the R227 and
R226 findings blocks, the "Older findings" doctrine block, and the three
already-relocated R220 / R221 / R224 pointer stubs. The stubs are kept rather
than dropped because they are the provenance chain - they record which cycle
relocated which block, and "the steady-state rule above" they refer to is the
doctrine block that now sits immediately above them here.

**Why this move happened.** The plan's newest `| R<n> |` row had drifted to
21306 bytes from EOF against the director's 15888-byte tail window, so
`tests/test_loop_director_context_caps.py::test_real_orchestration_plan_newest_row_survives`
was RED - the director could no longer see the newest session row and would
mis-ground the next cycle. Moving these 12962 bytes puts the row back at about
8300 bytes from EOF, inside the window with several cycles of room. The same
commit adds a HEADROOM guard alongside the survival guard, so the next drift
reds while there is still room to act instead of after the row is already gone.)

### Findings log - R227 (2026-09-11)

- **The WRAP cycle itself introduced a regression, and it was a text MOVE - the one defect shape no repo guard in this tree can see.** Fixed in `54fcf67c8` (cycle 72). The RM-407 wrap cut the `**Stated limits, not buried:**` census-guard sentence out of the RM-406 ROADMAP row and pasted it onto the RM-407 row, so RM-407 shipped four residuals that are not true of it while RM-406 - which has no `BACKLOG.md` body row, so its ROADMAP line is its only body - lost its limits entirely. Every byte stayed valid prose; only the OWNER was wrong, which is why ASCII hygiene, link checks, the disposition-drift guard and the RM-id registry all stayed green over it. The audit returned REGRESS; no automated gate did. **The transferable half is the counting trap, not the move:** the same wrap also duplicated `Next free id = RM-410` TWICE ON ONE LINE, and `grep -c` returns `1` both before and after the repair because it counts LINES - only `grep -o` piped to `wc -l` (2 -> 1) can see it. A wrap that verifies its own row edits with `grep -c` is verifying nothing. Population of the misattribution class measured and shown at 2 (`ROADMAP.md:48` FIXED, `ROADMAP.md:49` CORRECT and left alone, `BACKLOG.md` 0), and the move was proved byte-identical against `f6eef7e69` by sha256 rather than eyeballed.
- **The directive's own enumeration command manufactures a phantom.** `git ls-files "*test_*.py"` returns a sixteenth directory, bare `tools`, whose only match is `tools/pytest_guard.py` - the substring "test_" inside "pytest_". A guard built on that predicate files an orphan tree it can never close. The precise universe is 15 trees; 13 are covered by the `tests/` and `agents/daemon_slayer/tests/` prefixes and exactly 2 were orphans. No unexpected third tree exists.
- **A single green run is not a green tree.** The audit slice reported "0 failed" from one run; three runs found a 1-in-3 flake. Any future WIRE verdict on a tree must come from repeated runs under load, not one sample.
- **RM-406's census has a structural blind spot that its own AFTER figure cannot reveal.** State leaving over a SOCKET touches none of its four patched write routes and sits under none of its watched paths. `:8890` is OPEN on Legion, so the 6 `live_supervisor` tests do not skip here and POST real records into the running supervisor. Both slice agents and the verifier's own measurement tripped it. Filed RM-409.
- **The push half is closed, the nightly half is not.** Both wired steps landed in `check` only; `nightly-full-suite` still names neither tree. The guard discloses this as its own limitation rather than hiding it.
- **RM-408 - an instrument with no planted control cannot distinguish a clean tree from a dead probe.** `tools/live_write_tracer.py` carries no positive control, so a run whose patches intercept NOTHING reports a clean zero that reads exactly like a clean tree, and LEDGER 1392's headline AFTER figure rests entirely on that uncontrolled instrument. The sibling repo's equivalent control returned `proved: false` on its FIRST run against a tracer that was working correctly, because Windows `tempfile.mkdtemp` hands back the 8.3 SHORT path while the watcher resolves the LONG form - so the failure mode is real and has already been observed once. Filed as RM-408, not fixed here.
- **A cycle that measures and adjudicates but never commits leaves HEAD shipping the defect it just diagnosed.** Cycle 70 reached the right verdict - agent3 EXCEPTED, with the flake measured three ways - and wrote the repair into the working tree, but the wrap commit was never made. So for a full cycle `.github/workflows/ci.yml` ran the agent3 tree BARE in a push-blocking job while the audit doc and the guard both described a state the gate did not implement. The deliverable of a cycle is a commit, not a correct working tree.

## Older findings - relocated 2026-07-28

R205 / R206 / R207 / R216 / R217 / R217-U1 findings now live in `docs/ORCHESTRATION_PLAN_HISTORY.md`.

**Why, because this WILL recur:** the director context caps this file with
`cap_bytes_head_tail(..., PLAN_CTX_CAP=24000, PLAN_CTX_HEAD=8000)`, so only the
first 8000 and the LAST 16000 bytes reach the director, and
`tests/test_loop_director_context_caps.py::test_real_orchestration_plan_newest_row_survives`
fails when the newest `| R<n> |` row falls outside that tail window. Every cycle
appends a row AND a findings block, but the findings land AFTER the rows - so each
cycle pushes the newest row roughly one findings-block further from EOF while the
row itself barely moves. R216 crossed the line at 16087 bytes from EOF, missing the
window by 87 bytes. **The fix is to relocate old findings blocks, never to shrink the
new row or trim the guard.** Budget about two to three cycles per relocation.

**R217 changed the relocation from a periodic chore into a steady state.** Budgeting
"two to three cycles per relocation" is still a countdown to the same failure; the
distance from the newest row to EOF is just the total size of the findings blocks
sitting after the rows, so the stable rule is to keep exactly ONE findings block at
the tail. R217 relocated R216's block (5509 bytes) at the same time it appended its
own, which put the newest row at about 5000 bytes from EOF instead of 10696. Do the
same every cycle: relocate the previous cycle's findings block verbatim as you append
yours. The newest row then never drifts, and the director keeps seeing the most
recent findings because the block it can read is always the newest one.

## R220 findings - relocated 2026-07-28

R220's findings block now lives in `docs/ORCHESTRATION_PLAN_HISTORY.md`.
Relocated by R221 under the steady-state rule above - keep exactly ONE
findings block at the tail so the newest `| R<n> |` row never drifts out
of the director's 16000-byte tail window.

## R221 findings - relocated 2026-07-28

R221's findings block now lives in `docs/ORCHESTRATION_PLAN_HISTORY.md`.
Relocated by R224 under the steady-state rule above - keep exactly ONE
findings block at the tail so the newest `| R<n> |` row never drifts out
of the director's 16000-byte tail window.

## R224 findings - relocated 2026-09-11

R224's findings block now lives in `docs/ORCHESTRATION_PLAN_HISTORY.md`.
Relocated by R226 under the steady-state rule above - keep exactly ONE
findings block at the tail so the newest `| R<n> |` row never drifts out
of the director's 16000-byte tail window.

## R226 findings - 2026-09-11 (cycle 69, LAND)

**Cycle 68 measured and committed nothing, so the whole deliverable was a dirty
working tree.** This cycle landed it, and the landing was not a rubber stamp:
two read-only adversarial slices in the MAIN checkout (a worktree cannot see
uncommitted work, so worktree fan-out was forbidden) returned findings that
changed what shipped. Slice 1 returned **BLOCK**, slice 2 **SHIP with two
misses**. The merger adjudicated both.

**THE HEADLINE NUMBER, re-derived on the final tree rather than inherited.**
`tools/live_write_tracer.py` over `pytest tests -n 8 --dist loadfile`, all nine
per-process reports merged by the tool's own `--merge`: **13 units across 1
path**, and that path is `moon_sync_inbox/rc_audit_probe_inside.txt` - the one
row the census DECLARES as deliberately unprevented, because the write IS the
assertion in `tests/test_vision_server_http_hardening.py` and the test removes
it again. BEFORE was 201079 units over 17 paths. The AFTER run reproducing
exactly the declared exception and nothing else is the evidence that the other
sixteen rows are closed. Two zero-byte opens survive, both `.lock` files, which
is what a lock is for. `atomic_tmp_units` is empty. Pinned as a JOIN against
the census table at `tests/test_suite_does_not_write_live_tree.py`, not as a
restated literal: flipping the EXCEPTION row to FIXED reds it (observed).

**SLICE 2 FOUND TWO PRODUCERS THE NARROW FIX MISSED, and that is the more
valuable half of the cycle.** The root cause was never "ddragon_mirror_refresh
used `write_text`" - it is that on Windows `Path.write_text` rewrites LF as
CRLF while `read_text` translates it back, and for a TRACKED file that git
normalizes in the index `git status` stays CLEAN, so the defect is invisible
from both directions at once. `tools/daemon_slayer_extract._atomic_write_json`
(writing 44 tracked `data/daemon_slayer/**` JSON files, all pinned `eol=lf`),
its `_atomic_write_text` sibling, and
`tools/daemon_slayer_abilities_extract._atomic_write_json` all had the
identical shape and were latent - they would emit CRLF on the next DS extract.
Fixed, plus a class guard
(`tests/test_tracked_json_producers_emit_lf_bytes.py`, 20 tests) that carries
all six producers including the two RM-287 already fixed, asserts each named
target is still tracked AND still `eol=lf` via `git check-attr` so a rotted
premise fails loudly, and sweeps the tracked tree for CRLF that an earlier
broken run left behind. RED first: 6 real failures across the three unfixed
producers before the fix, 20 passed after.

**SLICE 1'S REFUTATIONS WERE ACCEPTED, NOT ARGUED WITH.** (a) The guard's
docstring claimed "removing any one redirect turns this file red"; it does not.
Narrowing `_tmp_log_path` to pass one filename through leaves both arms of
`_check_logging_handler_ctor` satisfied, and under `--dist loadfile` the test
that would attach that handler need not share the worker. The claim is now four
stated limits with the demonstrated mutation named. (b) The tracer reported
`wrote_bytes` while `_datalen` returns CHARACTERS for text handles - wrong in
the direction that undercounts, by one byte per newline plus UTF-8 expansion.
Renamed `wrote_units` throughout with the unit stated. (c) No merge code
existed for the per-worker reports, and the xdist CONTROLLER wrote an
unsuffixed near-empty file at the documented default path - a partial census
that looks like a clean one. The controller is now suffixed too and
`--merge` ships in the tool. (d) The tracer credited both the `*.tmp` half of
an atomic write and its destination, double-counting; tmp now has its own
bucket that totals never sum. (e) The default report path was inside
`ops/runtime/` - the instrument was a writer in the tree it polices, excluded
from its own count. Moved outside the repo. (f) A raise between patching
`builtins.open` and publishing `_state` would have left the process patched
forever; `_state` is published first. (g) Two tautologies removed, the
tracked-only blind spot declared, one misleading failure message corrected.

**STEP 3 DEFECT-CLASS ENUMERATION.** The prescribed grep over `tests/` returned
**991 instances across 259 files** - a population that must be shown, not
assumed. Layer 1 is lexical and reproducible (`--include=*.py`, receiver
resolved to its binding in the same file): 374 TMP-or-fixture-rooted, 154
local-only with no live marker, 361 with no statically resolvable target
(almost all `self.<attr>` bound in `setUp` from a tmp dir), 82 `.replace(` that
are string operations and not filesystem calls at all, 5 comment-only, and 15
LIVE-PATH candidates - **every one of which was opened by hand and resolves to
a tmp root**, or reads from the live tree and writes to tmp
(`shutil.copyfile(REPO / rel, tmp_path / rel)`, three sites). Layer 2 is the
authoritative one: the instrumented run attributes actual live-tree writes to
nodeids, and it found exactly the declared exception. Sibling trees
cross-checked with the same grep - `agents/agent3_testing/suite` 29,
`tools/tests` 16, `agents/daemon_slayer/tests` 97, 142 together, 3 live-path
candidates, all three safe (two read-live/write-tmp, one `rmtree` of a
tempdir).

**KNOWN AND NOT CLOSED, stated rather than buried.** `lib/ddragon/fetch.py`
now ships its writer as bytes. **CORRECTED 2026-09-11 (R229 / RM-410): the
rest of this sentence self-staled inside its own commit and is struck.** It
read "is still exercised by no test of its own ... carried in the new class
guard's table and nowhere else", which treated a `_PRODUCERS` row as inert
bookkeeping when it is a CALL SITE - the guard this same commit added invokes
every one of its six producers (`_invoke` at
`tests/test_tracked_json_producers_emit_lf_bytes.py:115`, bytes read `:137`,
asserts `:141` and `:146`; `-k fetch` collects 3). The writer HAS behavioural
CRLF coverage and always did. What it genuinely lacked, and what RM-410
shipped, is the byte-pin / tmp / fault-injection half the guard cannot assert -
see `docs/audits/LF_WRITER_DIRECT_COVERAGE_2026-09-11.md`.
`data/meta_build/ddragon/16.18.1/_assets_manifest.json` is UNTRACKED and still
carries 42318 CRLF pairs from a pre-fix run; the tracked bundles were repaired
when the fixed tool re-ran, and the new sweep asserts zero CRLF across all
tracked, git-normalized `.json`/`.txt`. The seven `-text` LFS payloads under
`data/laning_scenarios/` carry CRLF on purpose and are exempt, as
`tests/test_text_line_endings.py` already documents.
