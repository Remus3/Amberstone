# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-04b - RM-157 first half: the wrap summoned a suite the push already ran

The `/done` ritual's section 2c dispatch is RETIRED in both halves of the mirror pair
(`tools/done.md` + `.claude/commands/done.md`, copied byte-for-byte; drift guard exit 0).
Re-measured over `created>=2026-08-01`: 256 runs / 2126.6 min runner wall clock, of which
`ci` workflow_dispatch was 18 runs / 485.8 min - every one section 2c, every one a duplicate
of the push `check` run since RM-119's second half. 22.8 percent of all runner time for zero
signal. Sections 2b/8c now collect ONE run; the SHAPE note says Phase 2 fires CI by pushing.

**The measure-first instruction is what paid.** By run COUNT docs-guards (109) looks like the
problem; by MINUTES it is 8.4 percent, the smallest job in the repo, and the only watcher of
a docs-only push. CodSpeed is 3.7 percent. Both deliberately untouched - a triage done on run
count would have cut the cheap job and kept the expensive duplicate.

**Still OPEN and now an OPERATOR action: the billed number.** Every billing endpoint 404s
because the `gh` token carries `delete_repo, gist, read:org, repo, workflow` and NOT `user`.
Unlock is `gh auth refresh -h github.com -s user`, a device-code flow that cannot run
non-interactively. `/timing` still reports `billable.UBUNTU.total_ms = 0` with a correct
`run_duration_ms` on the same payload. Every figure above is WALL CLOCK, not billed.

Do NOT re-tune RM-156 (closed, CI-verified). Do NOT restore the dispatch - the two cases that
run no `ci` (docs-only push, non-main branch with no PR) were both checked and neither
justifies it. ROADMAP.md is at 71.5 KB against its 80 KB budget - tight, watch it.

---

# 2026-08-04a - RM-156: a timed-out job and a superseded one say the same word

Closed RM-156 (commit `c8199a96`). The filing said the push CI job had "13 minutes of
headroom and already blew it". **The 13 was wrong - measured over 40 runs it was about 3.**
The filing sampled the four runs around the failure, which is the middle of the
distribution and blind to the tail: successful `check` wall clock spans 22m17s to **36m49s**.

**One ceiling was bounding two independent tails.** The killed run (`30866367283`, 40m16s)
was slow in the SUITE - its dual-suite step had burned 38m41s against a 20m47s-27m40s norm.
The 36m49s run (`30820229244`), the slowest SUCCESS on record, was slow in SETUP: a 10m33s
`Install Playwright Chromium` cache miss on an otherwise normal suite. The 2026-07-28
arithmetic that produced the 40 modelled only the suite tail.

**Fix:** step-level `timeout-minutes: 45` on each dual-suite step, because a step killed by
its own timeout is marked FAILED (job concludes `failure`) while a job killed by the job
ceiling concludes `cancelled` - the same word as a concurrency supersede. Job ceilings become
backstops: `check` 40 -> 65, `nightly-full-suite` 30 -> 60. **The ordering is the invariant**
and is pinned by `tests/test_ci_job_timeout_headroom_rm156.py` (job >= step + 12): if a later
edit leaves job <= step, the job dies first and every overrun is silently `cancelled` again.

**`nightly-full-suite` had LESS headroom than the job that failed** (24m13s-28m08s against 30)
and was never mentioned in the filing. Both jobs got both halves.

**The premise is not in GitHub's docs.** They document only the job -> `cancelled` half. The
step -> FAILED half comes from `actions/runner` `src/Runner.Worker/StepsRunner.cs`. Recorded
as source-not-docs in the test docstring, so it gets re-measured if behaviour ever differs.

**Verifier refuted two of my claims, both real.** (1) I read the step-duration max off an
aggregate: it is 27m40s, not 25m29s. (2) `pyyaml` is installed only in `check`, so every
assertion in my new module AND in `test_ci_docs_guard_coverage.py` silently SKIPPED in the
nightly job - and my docstring had claimed an existing sibling covered that. It does not; it
keys on its own filename and is per-file, not per-job. Fixed with pyyaml on the nightly pip
line plus a per-JOB assertion. 8-mutation matrix: no mutation escapes all five tests.

**NEW, operator-raised at wrap: Actions minutes are blown out.** 255 workflow runs in the
first 4 days of August, and every push runs the full ~27-minute dual suite. Filed as RM-157.
**Do not confuse it with RM-156** - raising a timeout ceiling costs nothing unless it is hit;
the minute burn is the per-push full suite (RM-119's second half), which is a deliberate
coverage choice that now needs re-pricing.

Suite: 28554 passed / 108 skipped / 8102 subtests / 0 failed. ruff clean.

---

# 2026-08-03g - lane 8 cycle 7: stale relay data that called itself perfectly fresh

Audited `core/liveclient_cache.py` (criterion 1 - it parses the `:8889` relay envelope, which a
separate process authors on its own release cadence). EXPECTATION recorded before reading:
unvalidated dict access, a broad `except Exception` masking a shape change, staleness math
trusting an upstream timestamp, maybe a non-atomic write. Scored honestly: the staleness-math
prediction was RIGHT and worse than predicted; the non-atomic-write prediction was REFUTED - the
module writes nothing, it is a read-through cache.

**Method was empirical, not by reading.** `_fetch_once` was driven with nine adversarial bodies
through a mocked `urlopen` BEFORE any edit. That is what turned a hunch into three measured
defects, and it also killed one hypothesis I would otherwise have "confirmed" by reading.

**FINDING 1 - `age_s` failed OPEN three different ways.** Missing/null `ts` with data present
returned `0.0` ("perfectly fresh") forever; a FUTURE `ts` was clamped to `0.0` by
`max(0.0, ...)`; a non-numeric `ts` raised from a `float()` sited OUTSIDE the `try/except`,
escaping into the poll loop which logged it at DEBUG and left `_snapshot` frozen. **Eight**
consumers gate on that number, so one timestamp-less envelope defeated every freshness gate at
once. Now fail-closed AND total: unestablishable age reports `_UNKNOWN_AGE_S` (86400.0, kept
FINITE because two consumers pass the value outward and `json.dumps(inf)` is not valid JSON).

**FINDING 2 (sibling grep, same root cause)** - `modes/shared_vision.py:66` clamped a future
frame stamp the same way, letting an untrustworthy frame through the 90s cap that exists to stop
exactly that. The other seven `float(... or 0)` sites are fail-CLOSED already - recorded as
measured negatives, not changed.

**RM-155 CLOSED.** Root fix is an autouse `RC_FUSION_SHADOW_PATH` redirect in `tests/conftest.py`
(the path resolves through the env var at CALL time, so the existing module-global redirects
could never reach it). Backfill was real, not hypothetical: this worktree's corpus was ALREADY
polluted and the invariants test was ALREADY FAILING when the cycle began - an inherited red, not
one I caused. Removed it, then ran the full suite TWICE with identical counts and the production
path never recreated.

**Two process lessons worth keeping.** (1) A mutation caught my own test being VACUOUS - it
asserted `age_s > 12.0`, which a 1970 stamp also satisfies, so deleting the guard stayed GREEN.
Tightened to assert the sentinel exactly. (2) The verifier returned CONFIRM on all 9 claims and
STILL found a residual I had missed - `age_s` raised `TypeError` for a directly-built `Snapshot`
because `_coerce_ts` only guarded the fetch path. A CONFIRM verdict is not the same as "nothing
left"; read the residuals.

Suites from repo root: `tests/` 18162 passed / 154 skipped; DS 10341 passed. ruff clean.
Commit `b529ca89`, LEDGER 1184. Deployed to the live tree and re-probed.
