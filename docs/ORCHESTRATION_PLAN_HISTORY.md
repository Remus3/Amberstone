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

