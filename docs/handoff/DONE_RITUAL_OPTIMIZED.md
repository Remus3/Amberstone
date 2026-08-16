# The /done ritual - optimized, with a per-session drift guard

Written 2026-07-26 on Legion (Tailscale node `legion-rc` - the only canonical name
for this box; CLAUDE.md deliberately does not record the Windows computer name,
which is re-rolled periodically). Derived from Amberstone's `/done`, but
written to be **portable**: any project on this machine using the same
commit + push + living-docs practice can adopt it by changing the paths in
section 0.

> CANONICAL, version-controlled copy. A Desktop copy exists for handing to other
> projects; an earlier Desktop-only version was lost, hence this one lives in the
> repo. The reference implementation is now real code at `tools/drift_guard.py`
> with tests at `tests/test_drift_guard.py` - read those rather than a pasted
> snippet, which is exactly the kind of copy that drifts.

Two problems this solves:

1. **The wrap blocked for ~27 minutes** on a local full test suite.
2. **Drift accumulates silently across sessions**, then costs a whole dedicated
   session to unpick. The fix is cheap invariant checks run EVERY session, not a
   cleanup session every tenth one.

---

## 0. Per-project settings

```
PROJECT_ROOT   C:\Riot Commander
PYTHON         C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe
MAIN_BRANCH    main
CI_WORKFLOW    ci.yml
FULL_SUITE_JOB nightly-full-suite      # the job gated on workflow_dispatch
DOC_BUDGETS    ROADMAP.md=81920, CLAUDE.md=61440
MIRROR_PAIRS   tools/*.md  <->  .claude/commands/*.md
MEMORY_DIR     C:\Users\Administrator\.claude\projects\<PROJECT>\memory
```

---

## 1. WHY THE OLD SHAPE WAS SLOW - measured

| Step | Cost |
|---|---|
| Local full dual suite | **1642s (27m22s)**, 23,250 tests |
| Same suite on CI ubuntu | **1007s (16m47s)**, 22,749 tests (97.8% of local) |
| CI push job `check` | 5 min, **941 tests only** |
| Everything else in /done | ~15 min of doc/ledger/memory writing |

Two findings drive the redesign:

- **CI is FASTER than the local machine** and it is off your box. But the
  full-suite job is gated `schedule || workflow_dispatch`, so a normal push runs
  only the 941-test `check` - a green push badge covers **4%** of the local
  suite. That gap is why the local run genuinely felt mandatory.
- **The ~15 minutes of paperwork is dead time** that can overlap the CI run.

### MEASURE BEFORE CHOOSING A LEVER - the intuitive answer was wrong

The reasonable guess is that a slow suite has a slow minority. Refuted by its own
`--durations=40`: the slowest 40 tests are **176s, 10.7% of wall clock**, the
slowest single test is 17.8s, and the mean is **71ms across 23,250 tests**.
Deleting the forty worst saves under three minutes. The cost is **broad and
uniform**, so "fix the slow tests" cannot reach a 5-minute target - only
parallelism can.

So the lever depends entirely on the shape, and you cannot know the shape without
measuring:

- **Concentrated tail** -> fix those files; parallelism buys little at the price
  of flakes.
- **Broad and uniform** (this suite) -> parallelize; fixing individual tests is
  wasted effort.

**MEASURED OUTCOME:** the whole suite under `-n 8 --dist loadfile` took
**144.65s against 1642s serial - an 11.4x speedup** - with **6 failures out of
23,272**. All six are shared-state artifacts serial execution was hiding (five
fail-soft "never raises" tests, one asyncio event-loop conflict), so they are
latent test bugs worth fixing on their own merit. **Not adopted yet, and do not
adopt by suppressing them** - a suppressed failure under parallelism is how a
suite silently stops testing what you think it does.

`--dist loadfile` keeps every test in a file on ONE worker, so within-file order
and file-scoped fixtures hold; only cross-FILE isolation is newly assumed.

**Cost caveat for a PRIVATE repo:** Actions minutes are metered and this repo has
already tripped its spending limit once. Fire the full suite **once per session**,
never per push. A billing block looks exactly like a red CI - a 2-3 second
"failure" with a "job was not started" annotation.

---

## 2. THE NEW SHAPE - four phases

**Phase 1 - fast local gate (target 60-90s).** Repo-wide `ruff check .` (CI runs
it repo-wide, so a file-scoped pass can still go red on a sibling), `py_compile`
on touched files, the authored-source hygiene suite, **the targeted test slice
only**, and `python tools/drift_guard.py`.

**Phase 2 - commit, push, and FIRE CI IMMEDIATELY.** Stage only what you authored
(never `git add -A`); refuse anything matching `*SECRET*`, `*TOKEN*`, `*KEY*`,
`.env*` or the frozen-file list. Then:

```
gh workflow run <CI_WORKFLOW> --ref <MAIN_BRANCH>
```

uses the existing `workflow_dispatch` gate - no workflow edit needed. **Do not
block here.**

**Phase 3 - do the paperwork WHILE CI runs.** Hand-off notes, ledger entry,
living-doc sync, memory writes. This overlap is the whole trick: the wrap costs
the longer of the two, not their sum.

**Phase 4 - collect both runs, banner, next-session prompt.**

**Net:** local blocking time ~27 min -> ~5, CI cost ~22 min per session instead
of ~150, and an authoritative full-suite gate is preserved.

**The honest trade:** the gate moves AFTER the commit. A red full run means fixing
forward rather than catching it pre-commit.

---

## 3. THE DRIFT GUARD - the part that saves the cleanup sessions

Every check exists because that drift ACTUALLY HAPPENED and later cost a session.

| # | Check | The incident it prevents |
|---|---|---|
| 1 | Doc-size budgets | A budgeted doc breached and SAT over, forcing two emergency relocation passes. Warns at 90%, because 100% is already an emergency. |
| 2 | Mirror parity of duplicated command docs | Two copies of one ritual doc diverged for a month, preserving a decommissioned instruction. First run found **8** diverged files when a hand audit found 1. |
| 3 | Memory index integrity | Memory files written but never indexed are invisible to the next session. |
| 4 | Version anchors after a bump, **HTML included** | A version string lives in more doc sites than any checklist lists; a 4th site was found 25 minutes into a CI run. A `*.md`-only grep misses it. |
| 5 | Orphan doc detection | 27 orphaned docs accumulated before anyone noticed. |
| 6 | Untracked authored files | 11 authored command docs had ZERO version control for months, under a gitignored directory. |
| 7 | Self-consistency of counted claims | A doc said "the fifteen most recent" above a list of twenty. |
| 8 | `core.hooksPath` points at TRACKED hooks | See section 5 - the worst one, and entirely silent. |

**Make it a SCRIPT, not a prose checklist.** A prose checklist is precisely what
drifted: the mirror rule sat WRONG inside `done.md` for a month while that same
document told every session to follow it. A check that executes cannot rot
silently; a paragraph asking a reader to remember something can, and did.

**Never silence a breach by loosening a check.** If a finding is a genuine false
positive, fix the check and add a case to the test file - which asserts BOTH the
breach and the clean path for every check, precisely so a check cannot degrade
into always-passing. A check that can only pass is worse than none.

**A guard that warns every session trains people to ignore it.** If a warning
will stand for a while, say so explicitly at wrap and name it as next session's
item; do not move the threshold to make it quiet.

---

## 4. Fixes the audit found in the EXISTING ritual text

1. **The commit trailer was stale** - it hardcoded a model name that had changed,
   so every session wrote a wrong trailer. Defer to whatever the running harness
   specifies; a hardcoded identifier in prose is the exact drift class the guard
   catches.
2. **A deprecated section still occupied space** as a "skip this entirely" block.
   Delete retired sections - a reader must parse them to learn they are dead.
3. **Section numbering skipped a number**, making "run all sections in order"
   ambiguous about whether one was missing.

---

## 5. GIT HOOKS - the highest-value check, and the one nobody looks at

**`.git/hooks/` is NOT version controlled.** A hook that lives only there does not
reach a fresh clone, another machine, or a sibling project.

Measured on Amberstone 2026-07-26: `core.hooksPath` resolved to the untracked
`.git\hooks`, whose `pre-commit` ran only a Share-mirror sync - while the TRACKED
`.githooks/pre-commit` (running `py_compile`, an architecture-map check and a
schema check) sat inert. **Three tracked guards had silently stopped running**,
and both generated artifacts had drifted by the time it surfaced.

**Root cause:** an `install_hooks.py` that WROTE `.git/hooks/pre-commit` with a
single job, clobbering everything else, and never set `core.hooksPath`. If your
project has a hook-writing installer, it has this bug. Rewrite it to set the
pointer and write no hook body.

**The `commit-msg` pair had split the same way**, and each copy held a DIFFERENT
job - a policy trailer-strip in one, a Conventional-Commits check in the other -
so exactly one ran depending on which file won.

**Why this matters beyond tidiness:** a headless
`claude -p --permission-mode bypassPermissions` run **does not inherit PreToolUse
hooks**. Measured: it committed a banned glyph straight through. Git hooks DID
run. So the authoritative gate belongs in the git hook, where it is
channel-independent - agent, human and CI all get it.

**And the half that is easy to miss:** `pre-commit` CANNOT see the commit message.
Git's order is pre-commit -> prepare message -> commit-msg, so `COMMIT_EDITMSG`
does not exist yet. Putting a message check in `pre-commit` looks like it works,
because the staged-content half still fires, while the message half checks
nothing. Split it:

    pre-commit  -> gate staged content
    commit-msg  -> gate the message file ($1)

Order the checks so the cheap gate runs FIRST and before anything mutates the
index.

---

## 6. If the repository is going PUBLIC

Flipping private -> public exposes **the entire history**. Deleting a file later
does not remove it. Budget a dedicated session:

- **Secret scan across ALL history.** Anything ever committed is compromised and
  must be **rotated**, even if later deleted. Enable secret scanning and push
  protection at the same time.
- **Personal and network identifiers** in code, docs, commit messages and
  history: real names, emails, game handles, machine names, LAN and VPN IPs, VPN
  node names, absolute user-profile paths.
- **Third-party data redistribution** - vendored datasets need their licence
  re-checked for public redistribution, a different permission from private use.
- **Actions billing flips in your favour** - public repos get free standard
  runners, removing the metering constraint in section 1. A real upside, but not
  a reason to rush the scrub.

Treat the scrub as its own session. Do not fold it into a /done.

---

## 7. Adopting this in another project

1. Copy `tools/drift_guard.py` + `tests/test_drift_guard.py`, edit only the
   CONFIG block.
2. Add the guard to Phase 1.
3. **Check `core.hooksPath` first** - section 5 is the highest-value item and
   costs one command to diagnose.
4. Confirm CI has a full-suite job reachable by `workflow_dispatch`.
5. Replace the blocking local full suite with the targeted slice plus the
   dispatched CI run.
6. Keep the two cheap hard rules: repo-wide lint locally, and never `git add -A`.
